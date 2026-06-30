from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import ValidationError, field_validator
from starlette.websockets import WebSocketDisconnect

from src.control_plane.auth.context import get_authorization_context
from src.control_plane.relay.protocol import (
    RelayProtocolModel,
    RelaySignedHandshakeClaims,
)
from src.control_plane.relay.registry import (
    RelayDevice,
    RelayDeviceRegistry,
    validate_relay_public_key,
)


class RegisterRelayDeviceRequest(RelayProtocolModel):
    device_name: str
    public_key_pem: str

    @field_validator("public_key_pem")
    @classmethod
    def reject_private_key_material(cls, value: str) -> str:
        validate_relay_public_key(value)
        return value


class RotateRelayDeviceKeyRequest(RelayProtocolModel):
    public_key_pem: str

    @field_validator("public_key_pem")
    @classmethod
    def reject_private_key_material(cls, value: str) -> str:
        validate_relay_public_key(value)
        return value


class RelayConnectHello(RelayProtocolModel):
    account_id: str
    device_id: str


class RelayDeviceResponse(RelayProtocolModel):
    account_id: str
    device_id: str
    fingerprint: str
    revoked: bool


def _require_account_id() -> str:
    context = get_authorization_context()
    if context is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return context.account_id


def _device_response(device: RelayDevice) -> RelayDeviceResponse:
    return RelayDeviceResponse(
        account_id=device.account_id,
        device_id=device.device_id,
        fingerprint=device.fingerprint,
        revoked=device.revoked,
    )


def _relay_registry_http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "device not found" in message:
        return HTTPException(status_code=404, detail="Relay device not found")
    if "revoked" in message:
        return HTTPException(status_code=410, detail="Relay device revoked")
    return HTTPException(status_code=400, detail="Relay request rejected")


def build_relay_router(registry: RelayDeviceRegistry) -> APIRouter:
    router = APIRouter(prefix="/relay")

    @router.post("/devices/register", response_model=RelayDeviceResponse)
    async def register_device(
        request: RegisterRelayDeviceRequest,
    ) -> RelayDeviceResponse:
        device = await registry.register_device(
            account_id=_require_account_id(),
            device_name=request.device_name,
            public_key_pem=request.public_key_pem,
        )
        return _device_response(device)

    @router.post("/devices/{device_id}/rotate-key", response_model=RelayDeviceResponse)
    async def rotate_key(
        device_id: str,
        request: RotateRelayDeviceKeyRequest,
    ) -> RelayDeviceResponse:
        try:
            device = await registry.rotate_key(
                account_id=_require_account_id(),
                device_id=device_id,
                public_key_pem=request.public_key_pem,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        return _device_response(device)

    @router.post("/devices/{device_id}/revoke", response_model=RelayDeviceResponse)
    async def revoke_device(device_id: str) -> RelayDeviceResponse:
        try:
            device = await registry.revoke_device(
                account_id=_require_account_id(),
                device_id=device_id,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        return _device_response(device)

    @router.websocket("/connect")
    async def connect(websocket: WebSocket) -> None:
        await websocket.accept()
        session = None
        try:
            hello = RelayConnectHello.model_validate(await websocket.receive_json())
            challenge = await registry.create_challenge(
                account_id=hello.account_id,
                device_id=hello.device_id,
            )
            await websocket.send_json(challenge.model_dump(mode="json"))
            signed_claims = RelaySignedHandshakeClaims.model_validate(
                await websocket.receive_json()
            )
            session = await registry.accept_handshake(signed_claims)
            await websocket.send_json(
                {
                    "relay_session_id": session.relay_session_id,
                    "execution_target_id": session.execution_target_id,
                    "state": session.state.value,
                }
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except (ValidationError, ValueError):
            await websocket.close(code=1008)
        finally:
            if session is not None:
                await registry.disconnect_session(session.device_id)

    return router
