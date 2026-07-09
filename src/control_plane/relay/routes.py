from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import ValidationError, field_validator
from starlette.websockets import WebSocketDisconnect

from src.control_plane.auth.context import get_authorization_context
from src.control_plane.relay.invocations import RelayInvocationBroker
from src.control_plane.relay.protocol import (
    RelayAuthenticatedMessage,
    RelayHandshakeToken,
    RelayHeartbeatFrame,
    RelayInvocationResultFrame,
    RelayProtocolModel,
)
from src.control_plane.relay.registry import (
    RelayDevice,
    RelayDeviceRegistry,
    validate_relay_public_key,
)

RELAY_DEVICE_MANAGE_SCOPE = "relay:device:manage"
RECENT_AUTH_WINDOW = timedelta(minutes=10)
RELAY_POLICY_CLOSE_CODE = 1008
RELAY_POLICY_CLOSE_REASON = "relay device policy changed"


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
    active: bool = False


def _require_relay_manage_account_id() -> str:
    context = get_authorization_context()
    if context is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if RELAY_DEVICE_MANAGE_SCOPE not in context.scopes:
        raise HTTPException(status_code=403, detail="Insufficient relay scope")
    if context.auth_time is None:
        raise HTTPException(status_code=401, detail="recent_auth_required")
    auth_time = context.auth_time
    if auth_time.tzinfo is None:
        auth_time = auth_time.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if auth_time > now:
        raise HTTPException(status_code=401, detail="recent_auth_required")
    if now - auth_time > RECENT_AUTH_WINDOW:
        raise HTTPException(status_code=401, detail="recent_auth_required")
    return context.account_id


def _device_response(device: RelayDevice) -> RelayDeviceResponse:
    return RelayDeviceResponse(
        account_id=device.account_id,
        device_id=device.device_id,
        fingerprint=device.fingerprint,
        revoked=device.revoked,
        active=device.active,
    )


def _relay_registry_http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "device not found" in message:
        return HTTPException(status_code=404, detail="Relay device not found")
    if "revoked" in message:
        return HTTPException(status_code=410, detail="Relay device revoked")
    return HTTPException(status_code=400, detail="Relay request rejected")


async def _request_model(request: Request, model_type):
    try:
        payload = await request.json()
        return model_type.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "msg": "Invalid request field"}],
        ) from exc


def build_relay_router(
    registry: RelayDeviceRegistry,
    invocation_broker: RelayInvocationBroker | None = None,
) -> APIRouter:
    invocation_broker = invocation_broker or RelayInvocationBroker()
    router = APIRouter(prefix="/relay")

    @router.post("/devices/register", response_model=RelayDeviceResponse)
    async def register_device(
        request: Request,
    ) -> RelayDeviceResponse:
        account_id = _require_relay_manage_account_id()
        body = await _request_model(request, RegisterRelayDeviceRequest)
        try:
            device = await registry.register_device(
                account_id=account_id,
                device_name=body.device_name,
                public_key_pem=body.public_key_pem,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        return _device_response(device)

    @router.get("/devices", response_model=list[RelayDeviceResponse])
    async def list_devices() -> list[RelayDeviceResponse]:
        devices = await registry.list_devices(_require_relay_manage_account_id())
        return [_device_response(device) for device in devices]

    @router.post("/devices/{device_id}/set-active", response_model=RelayDeviceResponse)
    async def set_active_device(device_id: str) -> RelayDeviceResponse:
        account_id = _require_relay_manage_account_id()
        previous_devices = await registry.list_devices(account_id)
        previous_active_device_ids = [
            device.device_id
            for device in previous_devices
            if device.active and device.device_id != device_id
        ]
        try:
            device = await registry.set_active_device(
                account_id=account_id,
                device_id=device_id,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        for previous_device_id in previous_active_device_ids:
            await invocation_broker.disconnect_device(
                account_id=account_id,
                device_id=previous_device_id,
                code=RELAY_POLICY_CLOSE_CODE,
                reason=RELAY_POLICY_CLOSE_REASON,
            )
        return _device_response(device)

    @router.post("/devices/{device_id}/rotate-key", response_model=RelayDeviceResponse)
    async def rotate_key(
        device_id: str,
        request: Request,
    ) -> RelayDeviceResponse:
        account_id = _require_relay_manage_account_id()
        body = await _request_model(request, RotateRelayDeviceKeyRequest)
        try:
            device = await registry.rotate_key(
                account_id=account_id,
                device_id=device_id,
                public_key_pem=body.public_key_pem,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        await invocation_broker.disconnect_device(
            account_id=account_id,
            device_id=device_id,
            code=RELAY_POLICY_CLOSE_CODE,
            reason=RELAY_POLICY_CLOSE_REASON,
        )
        return _device_response(device)

    @router.post("/devices/{device_id}/revoke", response_model=RelayDeviceResponse)
    async def revoke_device(device_id: str) -> RelayDeviceResponse:
        account_id = _require_relay_manage_account_id()
        try:
            device = await registry.revoke_device(
                account_id=account_id,
                device_id=device_id,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        await invocation_broker.disconnect_device(
            account_id=account_id,
            device_id=device_id,
            code=RELAY_POLICY_CLOSE_CODE,
            reason=RELAY_POLICY_CLOSE_REASON,
        )
        return _device_response(device)

    @router.post("/devices/{device_id}/unlink", response_model=RelayDeviceResponse)
    async def unlink_device(device_id: str) -> RelayDeviceResponse:
        account_id = _require_relay_manage_account_id()
        try:
            device = await registry.unlink_device(
                account_id=account_id,
                device_id=device_id,
            )
        except ValueError as exc:
            raise _relay_registry_http_error(exc) from exc
        await invocation_broker.disconnect_device(
            account_id=account_id,
            device_id=device_id,
            code=RELAY_POLICY_CLOSE_CODE,
            reason=RELAY_POLICY_CLOSE_REASON,
        )
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
            handshake = RelayHandshakeToken.model_validate(
                await websocket.receive_json()
            )
            session = await registry.accept_handshake(
                handshake,
                challenge_relay_session_id=challenge.relay_session_id,
            )
            await websocket.send_json(
                RelayAuthenticatedMessage(
                    relay_session_id=session.relay_session_id,
                    execution_target_id=session.execution_target_id,
                    state=session.state,
                ).model_dump(mode="json")
            )
            await invocation_broker.register(
                session.relay_session_id,
                websocket,
                account_id=session.account_id,
                device_id=session.device_id,
            )
            while True:
                payload = await websocket.receive_json()
                frame_type = payload.get("type") if isinstance(payload, dict) else None
                if frame_type == "relay.heartbeat":
                    heartbeat = RelayHeartbeatFrame.model_validate(payload)
                    if (
                        heartbeat.relay_session_id != session.relay_session_id
                        or heartbeat.device_id != session.device_id
                    ):
                        raise ValueError("wrong heartbeat identity")
                    await registry.refresh_session(
                        session.account_id,
                        session.device_id,
                        session.relay_session_id,
                        version=heartbeat.version,
                        active_source_fingerprint=heartbeat.active_source_fingerprint,
                    )
                    continue
                if frame_type == "relay.invocation_result":
                    result = RelayInvocationResultFrame.model_validate(payload)
                    if result.relay_session_id != session.relay_session_id:
                        raise ValueError("wrong invocation result session")
                    await invocation_broker.accept_result(result)
                    continue
                raise ValueError("unknown relay frame")
        except WebSocketDisconnect:
            pass
        except (ValidationError, ValueError):
            await websocket.close(code=1008)
        finally:
            if session is not None:
                await invocation_broker.unregister(
                    session.relay_session_id,
                    connection=websocket,
                )
                await registry.disconnect_session(
                    session.account_id,
                    session.device_id,
                    session.relay_session_id,
                )

    return router
