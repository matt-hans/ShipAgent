# Relay Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first cloud-to-desktop relay path so `get_shipagent_status` can be called through the hosted `/mcp` control-plane surface and answered by either a loopback target in CI or a real connected desktop relay client.

**Architecture:** Add a canonical relay protocol module shared by cloud and desktop code, persist registered relay devices against Auth0-backed Cloud Accounts, track live device sessions in Redis plus process-local WebSocket state, and dispatch public tools through an `ExecutionTarget` protocol. The walking skeleton keeps invocation lifecycle minimal: one authenticated WSS session, strict per-session sequence numbers, one in-flight request/response, and schema-valid provider results; Plan 2 owns durable recovery and timeout state machines.

**Tech Stack:** Python 3.12, FastAPI WebSockets, FastMCP Streamable HTTP, SQLAlchemy/Alembic, Redis asyncio client, PyJWT EdDSA, `cryptography` Ed25519, `keyring`, `websockets`, pytest, httpx ASGI transport.

---

## Source Context

- Required spec: `docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md`.
- Required slice: Plan 1 in section 4, plus sections 3.1, 3.2, 3.3, 3.4, 5, and 7.
- Existing instructions: `AGENTS.md` and `src/AGENTS.md`.
- Existing control plane:
  - `src/control_plane/app.py` creates the FastAPI app, mounts FastMCP at `/mcp`, verifies Auth0 bearer tokens, resolves Cloud Account and Provider Connection identity, and wires `RequestControls`.
  - `src/control_plane/models.py` currently contains `CloudAccount` and `ProviderConnection`.
  - `src/control_plane/redis_keys.py` already has relay session TTL/key constants.
  - `src/hosted_mcp/server.py` registers only exported registry tools that also have bound handlers.
- Existing public registry:
  - `src/registry/tools/public.py` contains `get_shipagent_status`, but public exports are disabled by default.
  - The walking skeleton must enable only `get_shipagent_status` so `/mcp` can exercise the relay; leave provider-specific projection and broader public-scope cleanup to Plan 6.

## File Structure

Create these files:

- `src/control_plane/relay/__init__.py` — package exports for relay protocol and services.
- `src/control_plane/relay/protocol.py` — canonical relay message models, Ed25519 JWT helpers, fingerprints, target status helpers, and protocol error codes.
- `src/control_plane/relay/device_service.py` — SQL-backed register, rotate, revoke, active-device lookup, and fresh-auth checks.
- `src/control_plane/relay/session_registry.py` — Redis JSON records for live relay heartbeats and session metadata.
- `src/control_plane/relay/session_manager.py` — process-local WebSocket session map, sequence counters, pending invocation futures, and immediate device disconnect.
- `src/control_plane/relay/routes.py` — FastAPI router for `POST /relay/devices/register`, `GET /relay/devices`, `POST /relay/devices/rotate-key`, `POST /relay/devices/revoke`, `POST /relay/devices/set-active`, `POST /relay/devices/unlink`, and `WS /relay/connect`.
- `src/control_plane/execution_targets/__init__.py` — package exports for execution target classes.
- `src/control_plane/execution_targets/base.py` — provider-neutral `ExecutionTarget` protocol and `TargetToolRequest` dataclass.
- `src/control_plane/execution_targets/loopback.py` — CI/test execution target that dispatches to in-process handlers.
- `src/control_plane/execution_targets/relay.py` — production target that finds the active registered device and sends relay invocations through `RelayWebSocketSessionManager`.
- `src/control_plane/public_tool_handlers.py` — hosted public MCP handlers backed by an `ExecutionTarget`; Plan 1 binds only `get_shipagent_status`.
- `src/desktop/__init__.py` — desktop relay package marker.
- `src/desktop/relay_key_service.py` — Ed25519 relay key generation, OS keychain persistence through `KeyringStore`, public-key export, fingerprint, and auth-token signing.
- `src/desktop/desktop_relay_client.py` — outbound WSS client that authenticates, validates invocation envelopes, dispatches local handlers, and returns results.
- `tests/control_plane/relay/__init__.py` — relay tests package marker.
- `tests/control_plane/relay/fakes.py` — in-memory async Redis and keyring fakes used by control-plane relay tests.
- `tests/control_plane/relay/test_protocol.py` — protocol model and Ed25519 auth-token tests.
- `tests/control_plane/relay/test_device_service.py` — SQL device registration, rotation, revocation, active-device, and recent-auth tests.
- `tests/control_plane/relay/test_session_registry.py` — Redis TTL/session record tests.
- `tests/control_plane/relay/test_session_manager.py` — WebSocket session manager invocation and disconnect tests using a fake socket.
- `tests/control_plane/relay/test_routes.py` — HTTP device endpoints and WSS handshake tests against `TestClient`.
- `tests/control_plane/test_public_tool_handlers.py` — status handler and target dispatch tests.
- `tests/control_plane/test_control_plane_mcp_status.py` — CI loopback `/mcp` test using FastMCP Streamable HTTP over httpx ASGI transport.
- `tests/desktop/test_relay_key_service.py` — key generation, persistence, fingerprint, and signing tests.
- `tests/desktop/test_desktop_relay_client.py` — desktop envelope validation and one-invocation dispatch tests.
- `tests/control_plane/relay/test_two_process_relay_mcp.py` — local uvicorn + real `DesktopRelayClient` WSS integration proving `/mcp` can traverse cloud to desktop.

Modify these files:

- `pyproject.toml` — add direct `websockets>=14.0` dependency because the desktop relay client imports it directly.
- `src/control_plane/auth/context.py` — carry `auth_time` in `AuthorizationContext` for device-management freshness checks.
- `src/control_plane/auth/jwt_verifier.py` — parse optional Auth0 `auth_time` into `TokenPrincipal`.
- `src/control_plane/auth/service.py` — preserve `auth_time` when resolving a Cloud Account and Provider Connection.
- `src/control_plane/app.py` — build Redis/session manager/device service, include relay router, bind `get_shipagent_status` handler, and accept optional `execution_target`/`redis_client` injection for tests.
- `src/control_plane/models.py` — add `RelayDevice` model.
- `src/control_plane/redis_keys.py` — add relay session key helpers only where the existing `relay_session(device_id)` key is insufficient.
- `src/control_plane/routes/oauth_metadata.py` — add `shipagent.status` to supported scopes for the exported status tool.
- `src/registry/tools/public.py` — enable only `get_shipagent_status` for provider export, update its scope to `shipagent.status`, and update its output schema to the target-agnostic `executionTarget` shape.
- `tests/control_plane/auth/test_jwt_verifier.py` — cover `auth_time` parsing.
- `tests/control_plane/auth/test_service.py` — cover `auth_time` propagation.
- `tests/control_plane/test_app_auth.py` — update fake token/context scopes and include `auth_time`.
- `tests/hosted/test_hosted_mcp_registry.py` — update status result schema/scopes.
- `tests/registry/test_catalog.py` — assert only status is export-enabled in this slice.
- `tests/registry/test_export.py` and `tests/registry/test_artifact_drift.py` — keep generated snapshots aligned after regeneration.
- `generated/provider_artifacts/registry.json`
- `generated/provider_artifacts/generic_mcp_tools.json`
- `generated/provider_artifacts/claude_remote_mcp_public_tools.json`
- `generated/provider_artifacts/openai_apps_public_tools.json`
- `generated/provider_artifacts/openai_apps_tools.json`
- `generated/provider_artifacts/gemini_functions.json`
- `generated/provider_artifacts/microsoft_openapi_operations.json`

Create this migration:

- `alembic/versions/20260630_0002_relay_devices.py` — creates `relay_devices` in the configured control-plane schema.

## Tasks

### Task 1: Canonical Relay Protocol

**Files:**
- Create: `src/control_plane/relay/__init__.py`
- Create: `src/control_plane/relay/protocol.py`
- Test: `tests/control_plane/relay/__init__.py`
- Test: `tests/control_plane/relay/test_protocol.py`

- [ ] **Step 1: Write the failing protocol tests**

Create `tests/control_plane/relay/__init__.py` as an empty file.

Create `tests/control_plane/relay/test_protocol.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.control_plane.relay.protocol import (
    RELAY_AUDIENCE,
    RelayAuthClaims,
    RelayInvocationEnvelope,
    RelayProtocolError,
    VersionMetadata,
    generate_relay_challenge,
    public_key_fingerprint,
    sign_relay_auth_token,
    verify_relay_auth_token,
)


def _private_key_pem() -> str:
    private_key = ed25519.Ed25519PrivateKey.generate()
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _public_key_pem(private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("ascii"),
        password=None,
    )
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def test_relay_auth_token_round_trips_with_account_nonce_and_session_binding():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    private_key_pem = _private_key_pem()
    public_key_pem = _public_key_pem(private_key_pem)
    challenge = generate_relay_challenge(now=now)
    claims = RelayAuthClaims(
        device_id="device-1",
        account_id="acct-1",
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        issued_at=now,
        expires_at=now + timedelta(seconds=60),
        version=VersionMetadata(
            shipagent_core_version="0.1.0",
            registry_contract_version="1.0.0",
            ups_boundary_contract_version="shipagent_v1",
            capabilities=("status", "relay.invoke"),
        ),
    )

    token = sign_relay_auth_token(
        private_key_pem,
        claims,
        key_id=public_key_fingerprint(public_key_pem),
    )
    decoded = verify_relay_auth_token(
        token,
        public_key_pem,
        expected_device_id="device-1",
        expected_account_id="acct-1",
        expected_session_id=challenge.relay_session_id,
        expected_nonce=challenge.nonce,
    )

    assert decoded.device_id == "device-1"
    assert decoded.account_id == "acct-1"
    assert decoded.version.capabilities == ("status", "relay.invoke")
    assert RELAY_AUDIENCE == "shipagent-cloud-relay"


def test_relay_auth_token_rejects_wrong_nonce():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    private_key_pem = _private_key_pem()
    public_key_pem = _public_key_pem(private_key_pem)
    claims = RelayAuthClaims(
        device_id="device-1",
        account_id="acct-1",
        relay_session_id="session-1",
        nonce="nonce-1",
        issued_at=now,
        expires_at=now + timedelta(seconds=60),
        version=VersionMetadata(
            shipagent_core_version="0.1.0",
            registry_contract_version="1.0.0",
            ups_boundary_contract_version="shipagent_v1",
            capabilities=("status",),
        ),
    )
    token = sign_relay_auth_token(private_key_pem, claims)

    with pytest.raises(RelayProtocolError, match="nonce_mismatch"):
        verify_relay_auth_token(
            token,
            public_key_pem,
            expected_device_id="device-1",
            expected_account_id="acct-1",
            expected_session_id="session-1",
            expected_nonce="nonce-2",
        )


def test_invocation_envelope_requires_positive_sequence_and_hash():
    deadline = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    envelope = RelayInvocationEnvelope(
        relay_session_id="session-1",
        sequence=1,
        relay_invocation_id="inv-1",
        tool_name="get_shipagent_status",
        arguments={"correlation_id": "corr-1"},
        input_hash="a" * 64,
        deadline_at=deadline,
        idempotency_key="idem-1",
        audit_correlation_id="audit-1",
    )

    assert envelope.sequence == 1
    assert envelope.input_hash == "a" * 64

    with pytest.raises(ValueError):
        RelayInvocationEnvelope(
            relay_session_id="session-1",
            sequence=0,
            relay_invocation_id="inv-2",
            tool_name="get_shipagent_status",
            arguments={},
            input_hash="not-a-sha256",
            deadline_at=deadline,
            idempotency_key="idem-2",
            audit_correlation_id="audit-2",
        )
```

- [ ] **Step 2: Run the tests and verify they fail for missing module**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_protocol.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.relay'`.

- [ ] **Step 3: Create the canonical protocol implementation**

Create `src/control_plane/relay/__init__.py`:

```python
"""Relay control-plane package."""
```

Create `src/control_plane/relay/protocol.py`:

```python
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jwt import InvalidTokenError
from pydantic import BaseModel, ConfigDict, Field, field_validator

RELAY_AUDIENCE = "shipagent-cloud-relay"
DEFAULT_RELAY_AUTH_TTL_SECONDS = 60


class RelayProtocolError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class RelayMessageType(StrEnum):
    CHALLENGE = "relay.challenge"
    AUTHENTICATE = "relay.authenticate"
    AUTHENTICATED = "relay.authenticated"
    HEARTBEAT = "relay.heartbeat"
    INVOKE = "relay.invoke"
    INVOCATION_RESULT = "relay.invocation_result"
    ERROR = "relay.error"


class RelayDeviceStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class RelayTargetState(StrEnum):
    READY = "ready"
    OFFLINE = "offline"
    UPDATE_REQUIRED = "update_required"


class VersionMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    shipagent_core_version: str = Field(min_length=1)
    registry_contract_version: str = Field(min_length=1)
    ups_boundary_contract_version: str = Field(min_length=1)
    capabilities: tuple[str, ...] = ()


class RelayChallenge(BaseModel):
    type: Literal[RelayMessageType.CHALLENGE] = RelayMessageType.CHALLENGE
    relay_session_id: str
    nonce: str
    issued_at: datetime


class RelayAuthenticateMessage(BaseModel):
    type: Literal[RelayMessageType.AUTHENTICATE] = RelayMessageType.AUTHENTICATE
    token: str


class RelayAuthenticatedMessage(BaseModel):
    type: Literal[RelayMessageType.AUTHENTICATED] = RelayMessageType.AUTHENTICATED
    relay_session_id: str
    device_id: str
    heartbeat_interval_seconds: int = Field(default=30, ge=10, le=90)


class RelayAuthClaims(BaseModel):
    device_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    relay_session_id: str = Field(min_length=1)
    nonce: str = Field(min_length=16)
    issued_at: datetime
    expires_at: datetime
    version: VersionMetadata


class RelayHeartbeat(BaseModel):
    type: Literal[RelayMessageType.HEARTBEAT] = RelayMessageType.HEARTBEAT
    relay_session_id: str
    device_id: str
    version: VersionMetadata
    active_source_fingerprint: str | None = None
    sent_at: datetime


class RelayInvocationEnvelope(BaseModel):
    type: Literal[RelayMessageType.INVOKE] = RelayMessageType.INVOKE
    relay_session_id: str
    sequence: int = Field(gt=0)
    relay_invocation_id: str
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, Any]
    input_hash: str
    deadline_at: datetime
    idempotency_key: str
    audit_correlation_id: str

    @field_validator("input_hash")
    @classmethod
    def _sha256_hex(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("input_hash must be lowercase sha256 hex")
        return value


class RelayInvocationResult(BaseModel):
    type: Literal[RelayMessageType.INVOCATION_RESULT] = RelayMessageType.INVOCATION_RESULT
    relay_session_id: str
    relay_invocation_id: str
    sequence: int = Field(gt=0)
    status: Literal["ok", "error"]
    result: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class RelayErrorEnvelope(BaseModel):
    type: Literal[RelayMessageType.ERROR] = RelayMessageType.ERROR
    code: str
    message: str
    relay_session_id: str | None = None
    relay_invocation_id: str | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def generate_relay_challenge(now: datetime | None = None) -> RelayChallenge:
    return RelayChallenge(
        relay_session_id=str(uuid4()),
        nonce=secrets.token_urlsafe(32),
        issued_at=now or utc_now(),
    )


def load_private_key(private_key_pem: str) -> ed25519.Ed25519PrivateKey:
    key = serialization.load_pem_private_key(
        private_key_pem.encode("ascii"),
        password=None,
    )
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise RelayProtocolError("invalid_private_key", "relay key must be Ed25519")
    return key


def load_public_key(public_key_pem: str) -> ed25519.Ed25519PublicKey:
    key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise RelayProtocolError("invalid_public_key", "relay public key must be Ed25519")
    return key


def public_key_fingerprint(public_key_pem: str) -> str:
    key = load_public_key(public_key_pem)
    der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def private_key_to_public_pem(private_key_pem: str) -> str:
    public_key = load_private_key(private_key_pem).public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def relay_auth_claims_for_now(
    *,
    device_id: str,
    account_id: str,
    relay_session_id: str,
    nonce: str,
    version: VersionMetadata,
    now: datetime | None = None,
) -> RelayAuthClaims:
    issued_at = now or utc_now()
    return RelayAuthClaims(
        device_id=device_id,
        account_id=account_id,
        relay_session_id=relay_session_id,
        nonce=nonce,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=DEFAULT_RELAY_AUTH_TTL_SECONDS),
        version=version,
    )


def sign_relay_auth_token(
    private_key_pem: str,
    claims: RelayAuthClaims,
    *,
    key_id: str | None = None,
) -> str:
    private_key = load_private_key(private_key_pem)
    payload = {
        "sub": claims.device_id,
        "aud": RELAY_AUDIENCE,
        "account_id": claims.account_id,
        "relay_session_id": claims.relay_session_id,
        "nonce": claims.nonce,
        "iat": int(claims.issued_at.timestamp()),
        "exp": int(claims.expires_at.timestamp()),
        "version": claims.version.model_dump(mode="json"),
    }
    headers = {"kid": key_id} if key_id else None
    return jwt.encode(payload, private_key, algorithm="EdDSA", headers=headers)


def peek_relay_auth_identity(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
            },
        )
    except InvalidTokenError as exc:
        raise RelayProtocolError("invalid_relay_token", "relay token is malformed") from exc
    device_id = payload.get("sub")
    account_id = payload.get("account_id")
    if not isinstance(device_id, str) or not isinstance(account_id, str):
        raise RelayProtocolError("invalid_relay_token", "relay token identity is incomplete")
    return device_id, account_id


def verify_relay_auth_token(
    token: str,
    public_key_pem: str,
    *,
    expected_device_id: str,
    expected_account_id: str,
    expected_session_id: str,
    expected_nonce: str,
) -> RelayAuthClaims:
    try:
        payload = jwt.decode(
            token,
            load_public_key(public_key_pem),
            algorithms=["EdDSA"],
            audience=RELAY_AUDIENCE,
            options={"require": ["sub", "aud", "exp", "iat", "account_id", "relay_session_id", "nonce", "version"]},
        )
    except InvalidTokenError as exc:
        raise RelayProtocolError("invalid_relay_token", "relay token failed verification") from exc

    checks = {
        "device_mismatch": payload.get("sub") == expected_device_id,
        "account_mismatch": payload.get("account_id") == expected_account_id,
        "session_mismatch": payload.get("relay_session_id") == expected_session_id,
        "nonce_mismatch": payload.get("nonce") == expected_nonce,
    }
    for code, ok in checks.items():
        if not ok:
            raise RelayProtocolError(code, code)

    return RelayAuthClaims(
        device_id=payload["sub"],
        account_id=payload["account_id"],
        relay_session_id=payload["relay_session_id"],
        nonce=payload["nonce"],
        issued_at=datetime.fromtimestamp(int(payload["iat"]), UTC),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), UTC),
        version=VersionMetadata.model_validate(payload["version"]),
    )


def target_status_result(
    *,
    state: RelayTargetState,
    target_id: str | None,
    capabilities: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    return {
        "status": state.value,
        "executionTarget": {
            "state": state.value,
            "target_id": target_id,
            "capabilities": list(capabilities),
        },
    }
```

- [ ] **Step 4: Run protocol tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_protocol.py -v
```

Expected: PASS.

- [ ] **Step 5: Format and lint the new protocol files**

Run:

```bash
.venv/bin/python -m ruff format src/control_plane/relay tests/control_plane/relay
.venv/bin/python -m ruff check src/control_plane/relay tests/control_plane/relay
```

Expected: both commands pass.

- [ ] **Step 6: Commit**

```bash
git add src/control_plane/relay/__init__.py src/control_plane/relay/protocol.py tests/control_plane/relay/__init__.py tests/control_plane/relay/test_protocol.py
git commit -m "feat: add canonical relay protocol"
```

### Task 2: Auth0 Recent-Authentication Context

**Files:**
- Modify: `src/control_plane/auth/context.py`
- Modify: `src/control_plane/auth/jwt_verifier.py`
- Modify: `src/control_plane/auth/service.py`
- Modify: `src/control_plane/app.py`
- Test: `tests/control_plane/auth/test_jwt_verifier.py`
- Test: `tests/control_plane/auth/test_service.py`
- Test: `tests/control_plane/test_app_auth.py`

- [ ] **Step 1: Write failing tests for `auth_time` parsing and propagation**

Append to `tests/control_plane/auth/test_jwt_verifier.py`:

```python
from datetime import UTC, datetime
```

Add this test:

```python
def test_claim_validation_preserves_auth_time_when_present():
    verifier = Auth0TokenVerifier(
        issuer="https://tenant.us.auth0.com/",
        audience="https://dev-mcp.shipagent.app",
        jwks_client=None,
    )
    claims = {
        "iss": "https://tenant.us.auth0.com/",
        "aud": "https://dev-mcp.shipagent.app",
        "sub": "auth0|owner-1",
        "azp": "desktop-client",
        "scope": "relay:device:manage",
        "auth_time": 1782820800,
    }

    principal = verifier.validate_claims(claims)

    assert principal.auth_time == datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
```

Append to `tests/control_plane/auth/test_service.py`:

```python
from datetime import UTC, datetime
```

Add this test:

```python
@pytest.mark.asyncio
async def test_resolve_preserves_auth_time(control_db):
    service = AuthorizationService(
        control_db,
        ProviderClientRegistry({"desktop-client": "desktop"}),
    )
    auth_time = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

    context = await service.resolve(
        subject="auth0|owner-1",
        client_id="desktop-client",
        scopes={"relay:device:manage"},
        auth_time=auth_time,
    )

    assert context.auth_time == auth_time
```

Update the `_TokenVerifier.verify` fake in `tests/control_plane/test_app_auth.py` so it returns a fresh desktop-like auth time:

```python
from datetime import UTC, datetime


class _TokenVerifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def verify(self, token: str) -> TokenPrincipal:
        return TokenPrincipal(
            subject="auth0|owner-1",
            client_id="chatgpt-client",
            scopes=frozenset({"shipagent.status"}),
            auth_time=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )
```

Update `_AuthorizationService.resolve` in the same file:

```python
class _AuthorizationService(AuthorizationService):
    async def resolve(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: set[str],
        auth_time=None,
    ) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
            auth_time=auth_time,
        )
```

Update `test_valid_token_populates_context` in `tests/control_plane/test_app_auth.py`:

```python
    assert set(payload["authorization"]["scopes"]) == {"shipagent.status"}
    assert payload["authorization"]["auth_time"] == "2026-06-30T12:00:00+00:00"
```

- [ ] **Step 2: Run the auth tests and verify they fail for missing `auth_time`**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/auth/test_jwt_verifier.py tests/control_plane/auth/test_service.py tests/control_plane/test_app_auth.py -v
```

Expected: FAIL with `AttributeError` or `TypeError` mentioning `auth_time`.

- [ ] **Step 3: Add `auth_time` to context, verifier, service, and app resolution**

Modify `src/control_plane/auth/context.py`:

```python
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuthorizationContext:
    account_id: str
    provider_connection_id: str
    provider_surface: str
    subject: str
    client_id: str
    scopes: frozenset[str]
    auth_time: datetime | None = None
```

Modify `TokenPrincipal` and `validate_claims` in `src/control_plane/auth/jwt_verifier.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
```

```python
@dataclass(frozen=True)
class TokenPrincipal:
    subject: str
    client_id: str
    scopes: frozenset[str]
    auth_time: datetime | None = None
```

Inside `validate_claims`, after scope parsing:

```python
        auth_time = None
        auth_time_claim = claims.get("auth_time")
        if isinstance(auth_time_claim, int | float):
            auth_time = datetime.fromtimestamp(auth_time_claim, UTC)

        return TokenPrincipal(
            subject=subject,
            client_id=client_id,
            scopes=scopes,
            auth_time=auth_time,
        )
```

Modify `src/control_plane/auth/service.py`:

```python
from datetime import datetime
```

Update the method signature:

```python
    async def resolve(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: set[str],
        auth_time: datetime | None = None,
    ) -> AuthorizationContext:
```

Update the returned context:

```python
        return AuthorizationContext(
            account_id=account.id,
            provider_connection_id=connection.id,
            provider_surface=surface,
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
            auth_time=auth_time,
        )
```

Modify `_resolve_authorization` in `src/control_plane/app.py`:

```python
        return await service.resolve(
            subject=principal.subject,
            client_id=principal.client_id,
            scopes=set(principal.scopes),
            auth_time=principal.auth_time,
        )
```

- [ ] **Step 4: Run the auth tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/auth/test_jwt_verifier.py tests/control_plane/auth/test_service.py tests/control_plane/test_app_auth.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/control_plane/auth/context.py src/control_plane/auth/jwt_verifier.py src/control_plane/auth/service.py src/control_plane/app.py tests/control_plane/auth/test_jwt_verifier.py tests/control_plane/auth/test_service.py tests/control_plane/test_app_auth.py
git commit -m "feat: preserve Auth0 auth time for relay device management"
```

### Task 3: Relay Device Persistence and Device Service

**Files:**
- Modify: `src/control_plane/models.py`
- Create: `alembic/versions/20260630_0002_relay_devices.py`
- Create: `src/control_plane/relay/device_service.py`
- Test: `tests/control_plane/relay/test_device_service.py`

- [ ] **Step 1: Write failing device-service tests**

Create `tests/control_plane/relay/test_device_service.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import select

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.models import RelayDevice
from src.control_plane.relay.device_service import (
    RelayDeviceService,
    RelayDeviceServiceError,
    require_recent_device_management_auth,
)


def _context(auth_time: datetime | None) -> AuthorizationContext:
    return AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-desktop",
        provider_surface="desktop",
        subject="auth0|owner-1",
        client_id="desktop-client",
        scopes=frozenset({"relay:device:manage"}),
        auth_time=auth_time,
    )


def _public_key_pem() -> str:
    private_key = ed25519.Ed25519PrivateKey.generate()
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def test_recent_auth_requires_auth_time_and_management_scope():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

    require_recent_device_management_auth(_context(now - timedelta(minutes=9)), now=now)

    with pytest.raises(RelayDeviceServiceError, match="recent_auth_required"):
        require_recent_device_management_auth(_context(now - timedelta(minutes=11)), now=now)

    missing_scope = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-desktop",
        provider_surface="desktop",
        subject="auth0|owner-1",
        client_id="desktop-client",
        scopes=frozenset(),
        auth_time=now,
    )
    with pytest.raises(RelayDeviceServiceError, match="insufficient_scope"):
        require_recent_device_management_auth(missing_scope, now=now)


@pytest.mark.asyncio
async def test_register_device_binds_public_key_to_account(control_db):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    service = RelayDeviceService(control_db)

    device = await service.register_device(
        _context(now),
        public_key_pem=_public_key_pem(),
        now=now,
    )

    assert device.account_id == "acct-1"
    assert device.status == "active"
    assert device.active is True
    assert len(device.fingerprint) == 64
    loaded = await control_db.scalar(select(RelayDevice).where(RelayDevice.id == device.id))
    assert loaded is not None
    assert loaded.fingerprint == device.fingerprint


@pytest.mark.asyncio
async def test_rotate_key_keeps_device_id_and_increments_key_version(control_db):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    service = RelayDeviceService(control_db)
    device = await service.register_device(
        _context(now),
        public_key_pem=_public_key_pem(),
        now=now,
    )

    rotated = await service.rotate_key(
        _context(now),
        device_id=device.id,
        public_key_pem=_public_key_pem(),
        now=now + timedelta(seconds=1),
    )

    assert rotated.id == device.id
    assert rotated.key_version == 2
    assert rotated.fingerprint != device.fingerprint


@pytest.mark.asyncio
async def test_revoke_device_marks_inactive_and_active_lookup_returns_none(control_db):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    service = RelayDeviceService(control_db)
    device = await service.register_device(
        _context(now),
        public_key_pem=_public_key_pem(),
        now=now,
    )

    revoked = await service.revoke_device(_context(now), device_id=device.id, now=now)
    active = await service.get_active_device("acct-1")

    assert revoked.status == "revoked"
    assert revoked.active is False
    assert revoked.revoked_at == now
    assert active is None
```

- [ ] **Step 2: Run the device-service tests and verify they fail for missing model/service**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_device_service.py -v
```

Expected: FAIL with `ImportError` for `RelayDevice`.

- [ ] **Step 3: Add `RelayDevice` SQLAlchemy model**

Modify imports in `src/control_plane/models.py`:

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
```

Append this model:

```python
class RelayDevice(ControlPlaneBase):
    __tablename__ = "relay_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cloud_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    public_key_pem: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "fingerprint"),
    )
```

- [ ] **Step 4: Add the Alembic migration**

Create `alembic/versions/20260630_0002_relay_devices.py`:

```python
"""Create relay device table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260630_0002"
down_revision = "20260609_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    from alembic import context

    return context.config.get_section("alembic:runtime").get(
        "shipagent_control_plane_schema",
        "shipagent_private",
    )


def upgrade() -> None:
    schema = _schema()
    op.create_table(
        "relay_devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            [f"{schema}.cloud_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("account_id", "fingerprint"),
        schema=schema,
    )
    op.create_index(
        "ix_relay_devices_account_id",
        "relay_devices",
        ["account_id"],
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_relay_devices_account_id", table_name="relay_devices", schema=schema)
    op.drop_table("relay_devices", schema=schema)
```

- [ ] **Step 5: Add the relay device service**

Create `src/control_plane/relay/device_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.models import RelayDevice
from src.control_plane.relay.protocol import public_key_fingerprint

DEVICE_MANAGEMENT_SCOPE = "relay:device:manage"
RECENT_AUTH_WINDOW = timedelta(minutes=10)


@dataclass
class RelayDeviceServiceError(PermissionError):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def require_recent_device_management_auth(
    context: AuthorizationContext,
    *,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(UTC)
    if DEVICE_MANAGEMENT_SCOPE not in context.scopes:
        raise RelayDeviceServiceError("insufficient_scope", "relay device management scope is required")
    if context.auth_time is None:
        raise RelayDeviceServiceError("recent_auth_required", "fresh Auth0 authentication is required")
    if current - context.auth_time > RECENT_AUTH_WINDOW:
        raise RelayDeviceServiceError("recent_auth_required", "Auth0 authentication is older than ten minutes")


class RelayDeviceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register_device(
        self,
        context: AuthorizationContext,
        *,
        public_key_pem: str,
        now: datetime | None = None,
    ) -> RelayDevice:
        current = now or datetime.now(UTC)
        require_recent_device_management_auth(context, now=current)
        fingerprint = public_key_fingerprint(public_key_pem)
        await self.db.execute(
            update(RelayDevice)
            .where(RelayDevice.account_id == context.account_id)
            .values(active=False, updated_at=current)
        )
        device = RelayDevice(
            account_id=context.account_id,
            public_key_pem=public_key_pem,
            fingerprint=fingerprint,
            status="active",
            active=True,
            key_version=1,
            created_at=current,
            updated_at=current,
        )
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def rotate_key(
        self,
        context: AuthorizationContext,
        *,
        device_id: str,
        public_key_pem: str,
        now: datetime | None = None,
    ) -> RelayDevice:
        current = now or datetime.now(UTC)
        require_recent_device_management_auth(context, now=current)
        device = await self._device_for_account(context.account_id, device_id)
        if device.status != "active":
            raise RelayDeviceServiceError("device_revoked", "revoked relay device cannot rotate key")
        device.public_key_pem = public_key_pem
        device.fingerprint = public_key_fingerprint(public_key_pem)
        device.key_version += 1
        device.updated_at = current
        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def revoke_device(
        self,
        context: AuthorizationContext,
        *,
        device_id: str,
        now: datetime | None = None,
    ) -> RelayDevice:
        current = now or datetime.now(UTC)
        require_recent_device_management_auth(context, now=current)
        device = await self._device_for_account(context.account_id, device_id)
        device.status = "revoked"
        device.active = False
        device.revoked_at = current
        device.updated_at = current
        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def get_active_device(self, account_id: str) -> RelayDevice | None:
        return await self.db.scalar(
            select(RelayDevice).where(
                RelayDevice.account_id == account_id,
                RelayDevice.status == "active",
                RelayDevice.active.is_(True),
            )
        )

    async def get_device_for_handshake(
        self,
        *,
        account_id: str,
        device_id: str,
    ) -> RelayDevice:
        device = await self._device_for_account(account_id, device_id)
        if device.status != "active" or not device.active:
            raise RelayDeviceServiceError("device_revoked", "relay device is not active")
        return device

    async def _device_for_account(self, account_id: str, device_id: str) -> RelayDevice:
        device = await self.db.scalar(
            select(RelayDevice).where(
                RelayDevice.id == device_id,
                RelayDevice.account_id == account_id,
            )
        )
        if device is None:
            raise RelayDeviceServiceError("device_not_found", "relay device was not found")
        return device
```

- [ ] **Step 6: Run the device-service tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_device_service.py -v
```

Expected: PASS.

- [ ] **Step 7: Run migration validation**

Run:

```bash
alembic -c alembic.ini upgrade head
```

Expected: command completes with revision `20260630_0002`.

- [ ] **Step 8: Commit**

```bash
git add src/control_plane/models.py alembic/versions/20260630_0002_relay_devices.py src/control_plane/relay/device_service.py tests/control_plane/relay/test_device_service.py
git commit -m "feat: persist relay device registrations"
```

### Task 4: Redis Session Registry and WebSocket Session Manager

**Files:**
- Create: `tests/control_plane/relay/fakes.py`
- Create: `src/control_plane/relay/session_registry.py`
- Create: `src/control_plane/relay/session_manager.py`
- Test: `tests/control_plane/relay/test_session_registry.py`
- Test: `tests/control_plane/relay/test_session_manager.py`

- [ ] **Step 1: Add relay test fakes**

Create `tests/control_plane/relay/fakes.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class FakeAsyncRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}
        self.deleted: list[str] = []

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> bool:
        self.values[key] = value.encode("utf-8") if isinstance(value, str) else value
        if ex is not None:
            self.expirations[key] = ex
        return True

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        self.deleted.append(key)
        return 1 if existed else 0

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        key = keys_and_args[0]
        ttl = int(keys_and_args[-1])
        current = int((self.values.get(key) or b"0").decode("utf-8")) + 1
        self.values[key] = str(current).encode("utf-8")
        self.expirations[key] = ttl
        return current


@dataclass
class FakeWebSocket:
    sent: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False
    close_code: int | None = None

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code

    async def receive_text(self) -> str:
        raise RuntimeError("FakeWebSocket.receive_text is not used by session manager tests")

    def sent_json(self, index: int) -> dict[str, Any]:
        return json.loads(json.dumps(self.sent[index]))
```

- [ ] **Step 2: Write failing registry and manager tests**

Create `tests/control_plane/relay/test_session_registry.py`:

```python
from datetime import UTC, datetime

import pytest

from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import VersionMetadata
from src.control_plane.relay.session_registry import (
    RedisRelaySessionRegistry,
    RelaySessionRecord,
)
from tests.control_plane.relay.fakes import FakeAsyncRedis


@pytest.mark.asyncio
async def test_session_registry_stores_json_with_relay_ttl():
    redis = FakeAsyncRedis()
    registry = RedisRelaySessionRegistry(redis)
    record = RelaySessionRecord(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
        fingerprint="f" * 64,
        connected_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        version=VersionMetadata(
            shipagent_core_version="0.1.0",
            registry_contract_version="1.0.0",
            ups_boundary_contract_version="shipagent_v1",
            capabilities=("status",),
        ),
        active_source_fingerprint=None,
    )

    await registry.store_session(record)
    loaded = await registry.get_session("device-1")

    assert loaded == record
    assert redis.expirations[RedisKey.relay_session("device-1")] == RedisTtl.RELAY_SESSION_SECONDS


@pytest.mark.asyncio
async def test_session_registry_delete_clears_device_session():
    redis = FakeAsyncRedis()
    registry = RedisRelaySessionRegistry(redis)

    await registry.clear_session("device-1")

    assert redis.deleted == [RedisKey.relay_session("device-1")]
```

Create `tests/control_plane/relay/test_session_manager.py`:

```python
from datetime import UTC, datetime

import pytest

from src.control_plane.relay.protocol import RelayInvocationResult, VersionMetadata
from src.control_plane.relay.session_manager import RelayWebSocketSessionManager
from src.control_plane.relay.session_registry import RelaySessionRecord
from tests.control_plane.relay.fakes import FakeAsyncRedis, FakeWebSocket


def _record() -> RelaySessionRecord:
    return RelaySessionRecord(
        account_id="acct-1",
        device_id="device-1",
        relay_session_id="session-1",
        fingerprint="f" * 64,
        connected_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        version=VersionMetadata(
            shipagent_core_version="0.1.0",
            registry_contract_version="1.0.0",
            ups_boundary_contract_version="shipagent_v1",
            capabilities=("status",),
        ),
        active_source_fingerprint=None,
    )


@pytest.mark.asyncio
async def test_session_manager_sends_invocation_and_resolves_result():
    manager = RelayWebSocketSessionManager.from_redis(FakeAsyncRedis())
    websocket = FakeWebSocket()
    await manager.register_session(_record(), websocket)

    invoke_task = manager.invoke(
        account_id="acct-1",
        device_id="device-1",
        tool_name="get_shipagent_status",
        arguments={"correlation_id": "corr-1"},
        audit_correlation_id="audit-1",
        idempotency_key="idem-1",
        timeout_seconds=1.0,
    )
    pending = await invoke_task.__anext__()
    sent = websocket.sent_json(0)
    assert sent["type"] == "relay.invoke"
    assert sent["sequence"] == 1
    await manager.handle_invocation_result(
        RelayInvocationResult(
            relay_session_id="session-1",
            relay_invocation_id=sent["relay_invocation_id"],
            sequence=1,
            status="ok",
            result={"status": "ready"},
        )
    )
    result = await pending

    assert result == {"status": "ready"}


@pytest.mark.asyncio
async def test_session_manager_disconnect_closes_socket_and_clears_registry():
    redis = FakeAsyncRedis()
    manager = RelayWebSocketSessionManager.from_redis(redis)
    websocket = FakeWebSocket()
    await manager.register_session(_record(), websocket)

    await manager.disconnect_device("device-1", code=1008)

    assert websocket.closed is True
    assert websocket.close_code == 1008
    assert "sa:relay:session:device-1" in redis.deleted
```

- [ ] **Step 3: Run the registry/manager tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_session_registry.py tests/control_plane/relay/test_session_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `session_registry`.

- [ ] **Step 4: Implement the Redis session registry**

Create `src/control_plane/relay/session_registry.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import VersionMetadata


@dataclass(frozen=True)
class RelaySessionRecord:
    account_id: str
    device_id: str
    relay_session_id: str
    fingerprint: str
    connected_at: datetime
    version: VersionMetadata
    active_source_fingerprint: str | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "account_id": self.account_id,
                "device_id": self.device_id,
                "relay_session_id": self.relay_session_id,
                "fingerprint": self.fingerprint,
                "connected_at": self.connected_at.isoformat(),
                "version": self.version.model_dump(mode="json"),
                "active_source_fingerprint": self.active_source_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: bytes | str) -> "RelaySessionRecord":
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(text)
        return cls(
            account_id=payload["account_id"],
            device_id=payload["device_id"],
            relay_session_id=payload["relay_session_id"],
            fingerprint=payload["fingerprint"],
            connected_at=datetime.fromisoformat(payload["connected_at"]),
            version=VersionMetadata.model_validate(payload["version"]),
            active_source_fingerprint=payload["active_source_fingerprint"],
        )


class RedisRelaySessionRegistry:
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def store_session(self, record: RelaySessionRecord) -> None:
        await self.redis.set(
            RedisKey.relay_session(record.device_id),
            record.to_json(),
            ex=RedisTtl.RELAY_SESSION_SECONDS,
        )

    async def get_session(self, device_id: str) -> RelaySessionRecord | None:
        raw = await self.redis.get(RedisKey.relay_session(device_id))
        if raw is None:
            return None
        return RelaySessionRecord.from_json(raw)

    async def clear_session(self, device_id: str) -> None:
        await self.redis.delete(RedisKey.relay_session(device_id))
```

- [ ] **Step 5: Implement the WebSocket session manager**

Create `src/control_plane/relay/session_manager.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.control_plane.request_controls import hash_arguments
from src.control_plane.relay.protocol import (
    RelayInvocationEnvelope,
    RelayInvocationResult,
)
from src.control_plane.relay.session_registry import (
    RedisRelaySessionRegistry,
    RelaySessionRecord,
)


@dataclass
class _LiveRelaySession:
    record: RelaySessionRecord
    websocket: Any
    next_sequence: int = 1
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)


class RelaySessionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class RelayWebSocketSessionManager:
    def __init__(self, registry: RedisRelaySessionRegistry) -> None:
        self.registry = registry
        self._sessions_by_device: dict[str, _LiveRelaySession] = {}
        self._sessions_by_id: dict[str, _LiveRelaySession] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_redis(cls, redis_client) -> "RelayWebSocketSessionManager":
        return cls(RedisRelaySessionRegistry(redis_client))

    async def register_session(self, record: RelaySessionRecord, websocket) -> None:
        async with self._lock:
            previous = self._sessions_by_device.get(record.device_id)
            if previous is not None:
                await previous.websocket.close(code=1008)
            live = _LiveRelaySession(record=record, websocket=websocket)
            self._sessions_by_device[record.device_id] = live
            self._sessions_by_id[record.relay_session_id] = live
            await self.registry.store_session(record)

    async def refresh_session(self, record: RelaySessionRecord) -> None:
        async with self._lock:
            live = self._sessions_by_device.get(record.device_id)
            if live is not None and live.record.relay_session_id == record.relay_session_id:
                live.record = record
                self._sessions_by_id[record.relay_session_id] = live
            await self.registry.store_session(record)

    async def get_record(self, device_id: str) -> RelaySessionRecord | None:
        live = self._sessions_by_device.get(device_id)
        if live is not None:
            return live.record
        return await self.registry.get_session(device_id)

    async def invoke(
        self,
        *,
        account_id: str,
        device_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        audit_correlation_id: str,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> AsyncIterator[asyncio.Future[dict[str, Any]]]:
        live = self._sessions_by_device.get(device_id)
        if live is None or live.record.account_id != account_id:
            raise RelaySessionError("target_offline", "relay target is offline")
        sequence = live.next_sequence
        live.next_sequence += 1
        invocation_id = str(uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        live.pending[invocation_id] = future
        envelope = RelayInvocationEnvelope(
            relay_session_id=live.record.relay_session_id,
            sequence=sequence,
            relay_invocation_id=invocation_id,
            tool_name=tool_name,
            arguments=arguments,
            input_hash=hash_arguments(arguments),
            deadline_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            idempotency_key=idempotency_key,
            audit_correlation_id=audit_correlation_id,
        )
        await live.websocket.send_json(envelope.model_dump(mode="json"))
        yield future

    async def handle_invocation_result(self, result: RelayInvocationResult) -> None:
        live = self._sessions_by_id.get(result.relay_session_id)
        if live is None:
            raise RelaySessionError("session_not_found", "relay session is not active")
        future = live.pending.pop(result.relay_invocation_id, None)
        if future is None:
            raise RelaySessionError("invocation_not_found", "relay invocation is not pending")
        if result.status == "ok":
            future.set_result(result.result)
        else:
            future.set_exception(
                RelaySessionError(
                    (result.error or {}).get("code", "relay_invocation_error"),
                    (result.error or {}).get("message", "relay invocation failed"),
                )
            )

    async def disconnect_device(self, device_id: str, *, code: int = 1000) -> None:
        async with self._lock:
            live = self._sessions_by_device.pop(device_id, None)
            if live is None:
                await self.registry.clear_session(device_id)
                return
            self._sessions_by_id.pop(live.record.relay_session_id, None)
            for future in live.pending.values():
                if not future.done():
                    future.set_exception(RelaySessionError("target_disconnected", "relay target disconnected"))
            await live.websocket.close(code=code)
            await self.registry.clear_session(device_id)
```

- [ ] **Step 6: Fix the session-manager test helper to await the async iterator**

Replace `test_session_manager_sends_invocation_and_resolves_result` body with:

```python
@pytest.mark.asyncio
async def test_session_manager_sends_invocation_and_resolves_result():
    manager = RelayWebSocketSessionManager.from_redis(FakeAsyncRedis())
    websocket = FakeWebSocket()
    await manager.register_session(_record(), websocket)

    iterator = manager.invoke(
        account_id="acct-1",
        device_id="device-1",
        tool_name="get_shipagent_status",
        arguments={"correlation_id": "corr-1"},
        audit_correlation_id="audit-1",
        idempotency_key="idem-1",
        timeout_seconds=1.0,
    )
    pending = await iterator.__anext__()
    sent = websocket.sent_json(0)
    assert sent["type"] == "relay.invoke"
    assert sent["sequence"] == 1
    await manager.handle_invocation_result(
        RelayInvocationResult(
            relay_session_id="session-1",
            relay_invocation_id=sent["relay_invocation_id"],
            sequence=1,
            status="ok",
            result={"status": "ready"},
        )
    )
    result = await pending

    assert result == {"status": "ready"}
```

- [ ] **Step 7: Run the registry and manager tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_session_registry.py tests/control_plane/relay/test_session_manager.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/control_plane/relay/fakes.py src/control_plane/relay/session_registry.py src/control_plane/relay/session_manager.py tests/control_plane/relay/test_session_registry.py tests/control_plane/relay/test_session_manager.py
git commit -m "feat: track relay sessions in redis and websocket manager"
```

### Task 5: Cloud Relay Routes

**Files:**
- Create: `src/control_plane/relay/routes.py`
- Test: `tests/control_plane/relay/test_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/control_plane/relay/test_routes.py`:

```python
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.context import clear_authorization_context, set_authorization_context
from src.control_plane.models import ControlPlaneBase
from src.control_plane.relay.routes import build_relay_router
from src.control_plane.relay.session_manager import RelayWebSocketSessionManager
from src.control_plane.relay.session_registry import RedisRelaySessionRegistry
from src.desktop.relay_key_service import RelayKeyService
from tests.control_plane.relay.fakes import FakeAsyncRedis


def _desktop_context() -> AuthorizationContext:
    return AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-desktop",
        provider_surface="desktop",
        subject="auth0|owner-1",
        client_id="desktop-client",
        scopes=frozenset({"relay:device:manage"}),
        auth_time=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )


class _MemoryStore:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _build_app(tmp_path):
    db_path = tmp_path / "control.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    sync_engine = create_engine(f"sqlite:///{db_path}")
    ControlPlaneBase.metadata.create_all(sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)
    session_manager = RelayWebSocketSessionManager(
        RedisRelaySessionRegistry(FakeAsyncRedis())
    )
    app = FastAPI()

    @app.middleware("http")
    async def _inject_context(request: Request, call_next):
        token = set_authorization_context(_desktop_context())
        try:
            return await call_next(request)
        finally:
            clear_authorization_context(token)

    app.include_router(
        build_relay_router(
            session_factory=session_factory,
            session_manager=session_manager,
        ),
        prefix="/relay",
    )
    return app


def test_register_rotate_and_revoke_device(tmp_path):
    app = _build_app(tmp_path)
    key_service = RelayKeyService(store=_MemoryStore())
    public_key = key_service.public_key_pem()

    with TestClient(app) as client:
        register = client.post(
            "/relay/devices/register",
            json={"public_key_pem": public_key},
            headers={"Authorization": "Bearer valid"},
        )
        assert register.status_code == 200
        device = register.json()
        assert device["status"] == "active"
        assert len(device["fingerprint"]) == 64

        rotate = client.post(
            "/relay/devices/rotate-key",
            json={"device_id": device["device_id"], "public_key_pem": RelayKeyService(store=_MemoryStore()).public_key_pem()},
            headers={"Authorization": "Bearer valid"},
        )
        assert rotate.status_code == 200
        assert rotate.json()["key_version"] == 2

        revoke = client.post(
            "/relay/devices/revoke",
            json={"device_id": device["device_id"]},
            headers={"Authorization": "Bearer valid"},
        )
        assert revoke.status_code == 200
        assert revoke.json()["status"] == "revoked"


def test_relay_connect_accepts_registered_device(tmp_path):
    app = _build_app(tmp_path)
    key_service = RelayKeyService(store=_MemoryStore())

    with TestClient(app) as client:
        registered = client.post(
            "/relay/devices/register",
            json={"public_key_pem": key_service.public_key_pem()},
            headers={"Authorization": "Bearer valid"},
        ).json()
        with client.websocket_connect("/relay/connect") as websocket:
            challenge = websocket.receive_json()
            token = key_service.sign_auth_token(
                device_id=registered["device_id"],
                account_id="acct-1",
                relay_session_id=challenge["relay_session_id"],
                nonce=challenge["nonce"],
            )
            websocket.send_json({"type": "relay.authenticate", "token": token})
            accepted = websocket.receive_json()

    assert accepted["type"] == "relay.authenticated"
    assert accepted["device_id"] == registered["device_id"]
```

- [ ] **Step 2: Run route tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_routes.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `src.desktop.relay_key_service` or missing `/relay` routes.

- [ ] **Step 3: Add the desktop key service needed by route tests**

Create `src/desktop/__init__.py`:

```python
"""ShipAgent Desktop runtime helpers."""
```

Create `src/desktop/relay_key_service.py`:

```python
from __future__ import annotations

from datetime import datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.control_plane.relay.protocol import (
    VersionMetadata,
    private_key_to_public_pem,
    public_key_fingerprint,
    relay_auth_claims_for_now,
    sign_relay_auth_token,
)
from src.services.keyring_store import KeyringStore

RELAY_PRIVATE_KEY_NAME = "SHIPAGENT_RELAY_DEVICE_PRIVATE_KEY"


class RelayKeyService:
    def __init__(
        self,
        *,
        store=None,
        key_name: str = RELAY_PRIVATE_KEY_NAME,
    ) -> None:
        self.store = store or KeyringStore()
        self.key_name = key_name

    def private_key_pem(self) -> str:
        existing = self.store.get(self.key_name)
        if existing:
            return existing
        private_key = ed25519.Ed25519PrivateKey.generate()
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        self.store.set(self.key_name, private_key_pem)
        return private_key_pem

    def public_key_pem(self) -> str:
        return private_key_to_public_pem(self.private_key_pem())

    def fingerprint(self) -> str:
        return public_key_fingerprint(self.public_key_pem())

    def rotate(self) -> str:
        self.store.delete(self.key_name)
        return self.public_key_pem()

    def sign_auth_token(
        self,
        *,
        device_id: str,
        account_id: str,
        relay_session_id: str,
        nonce: str,
        now: datetime | None = None,
        version: VersionMetadata | None = None,
    ) -> str:
        metadata = version or VersionMetadata(
            shipagent_core_version="0.1.0",
            registry_contract_version="1.0.0",
            ups_boundary_contract_version="shipagent_v1",
            capabilities=("status", "relay.invoke"),
        )
        claims = relay_auth_claims_for_now(
            device_id=device_id,
            account_id=account_id,
            relay_session_id=relay_session_id,
            nonce=nonce,
            version=metadata,
            now=now,
        )
        return sign_relay_auth_token(
            self.private_key_pem(),
            claims,
            key_id=self.fingerprint(),
        )
```

- [ ] **Step 4: Implement relay routes**

Create `src/control_plane/relay/routes.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.control_plane.auth.context import get_authorization_context
from src.control_plane.relay.device_service import (
    RelayDeviceService,
    RelayDeviceServiceError,
)
from src.control_plane.relay.protocol import (
    RelayAuthenticateMessage,
    RelayAuthenticatedMessage,
    RelayHeartbeat,
    RelayInvocationResult,
    RelayProtocolError,
    generate_relay_challenge,
    peek_relay_auth_identity,
    verify_relay_auth_token,
)
from src.control_plane.relay.session_manager import RelayWebSocketSessionManager
from src.control_plane.relay.session_registry import RelaySessionRecord


class RegisterDeviceRequest(BaseModel):
    public_key_pem: str = Field(min_length=32)


class RotateDeviceKeyRequest(BaseModel):
    device_id: str = Field(min_length=1)
    public_key_pem: str = Field(min_length=32)


class RevokeDeviceRequest(BaseModel):
    device_id: str = Field(min_length=1)


def _device_response(device) -> dict[str, object]:
    return {
        "device_id": device.id,
        "fingerprint": device.fingerprint,
        "status": device.status,
        "active": device.active,
        "key_version": device.key_version,
    }


def _context_or_unauthorized():
    context = get_authorization_context()
    if context is None:
        raise RelayDeviceServiceError("missing_authorization_context", "authorization context unavailable")
    return context


def build_relay_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    session_manager: RelayWebSocketSessionManager,
    now_fn=None,
) -> APIRouter:
    router = APIRouter()
    now = now_fn or (lambda: datetime.now(UTC))

    @router.post("/devices/register")
    async def register_device(body: RegisterDeviceRequest, request: Request) -> dict[str, object]:
        context = _context_or_unauthorized()
        async with session_factory() as db:
            device = await RelayDeviceService(db).register_device(
                context,
                public_key_pem=body.public_key_pem,
                now=now(),
            )
            return _device_response(device)

    @router.post("/devices/rotate-key")
    async def rotate_key(body: RotateDeviceKeyRequest, request: Request) -> dict[str, object]:
        context = _context_or_unauthorized()
        async with session_factory() as db:
            device = await RelayDeviceService(db).rotate_key(
                context,
                device_id=body.device_id,
                public_key_pem=body.public_key_pem,
                now=now(),
            )
            await session_manager.disconnect_device(body.device_id, code=1008)
            return _device_response(device)

    @router.post("/devices/revoke")
    async def revoke_device(body: RevokeDeviceRequest, request: Request) -> dict[str, object]:
        context = _context_or_unauthorized()
        async with session_factory() as db:
            device = await RelayDeviceService(db).revoke_device(
                context,
                device_id=body.device_id,
                now=now(),
            )
            await session_manager.disconnect_device(body.device_id, code=1008)
            return _device_response(device)

    @router.websocket("/connect")
    async def connect(websocket: WebSocket) -> None:
        await websocket.accept()
        challenge = generate_relay_challenge()
        await websocket.send_json(challenge.model_dump(mode="json"))
        record: RelaySessionRecord | None = None
        try:
            auth = RelayAuthenticateMessage.model_validate_json(await websocket.receive_text())
            device_id, account_id = peek_relay_auth_identity(auth.token)
            async with session_factory() as db:
                device = await RelayDeviceService(db).get_device_for_handshake(
                    account_id=account_id,
                    device_id=device_id,
                )
                claims = verify_relay_auth_token(
                    auth.token,
                    device.public_key_pem,
                    expected_device_id=device.id,
                    expected_account_id=device.account_id,
                    expected_session_id=challenge.relay_session_id,
                    expected_nonce=challenge.nonce,
                )
            record = RelaySessionRecord(
                account_id=claims.account_id,
                device_id=claims.device_id,
                relay_session_id=claims.relay_session_id,
                fingerprint=device.fingerprint,
                connected_at=challenge.issued_at,
                version=claims.version,
                active_source_fingerprint=None,
            )
            await session_manager.register_session(record, websocket)
            await websocket.send_json(
                RelayAuthenticatedMessage(
                    relay_session_id=claims.relay_session_id,
                    device_id=claims.device_id,
                ).model_dump(mode="json")
            )
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "relay.heartbeat":
                    heartbeat = RelayHeartbeat.model_validate(message)
                    updated = RelaySessionRecord(
                        account_id=record.account_id,
                        device_id=record.device_id,
                        relay_session_id=record.relay_session_id,
                        fingerprint=record.fingerprint,
                        connected_at=record.connected_at,
                        version=heartbeat.version,
                        active_source_fingerprint=heartbeat.active_source_fingerprint,
                    )
                    await session_manager.refresh_session(updated)
                elif message_type == "relay.invocation_result":
                    await session_manager.handle_invocation_result(
                        RelayInvocationResult.model_validate(message)
                    )
        except (RelayProtocolError, RelayDeviceServiceError):
            await websocket.close(code=1008)
        except WebSocketDisconnect:
            if record is not None:
                await session_manager.disconnect_device(record.device_id)

    return router
```

- [ ] **Step 5: Run route tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_routes.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/control_plane/relay/routes.py src/desktop/__init__.py src/desktop/relay_key_service.py tests/control_plane/relay/test_routes.py
git commit -m "feat: add relay device routes and websocket handshake"
```

### Task 6: Execution Target Abstraction and Public Status Handler

**Files:**
- Create: `src/control_plane/execution_targets/__init__.py`
- Create: `src/control_plane/execution_targets/base.py`
- Create: `src/control_plane/execution_targets/loopback.py`
- Create: `src/control_plane/execution_targets/relay.py`
- Create: `src/control_plane/public_tool_handlers.py`
- Test: `tests/control_plane/test_public_tool_handlers.py`

- [ ] **Step 1: Write failing execution-target tests**

Create `tests/control_plane/test_public_tool_handlers.py`:

```python
import pytest

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_targets.base import TargetToolRequest
from src.control_plane.execution_targets.loopback import LoopbackExecutionTarget
from src.control_plane.public_tool_handlers import build_public_tool_handlers


@pytest.mark.asyncio
async def test_status_handler_dispatches_through_execution_target():
    seen: list[TargetToolRequest] = []

    async def status_handler(request: TargetToolRequest):
        seen.append(request)
        return {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "device-1",
                "capabilities": ["status"],
            },
        }

    target = LoopbackExecutionTarget({"get_shipagent_status": status_handler})
    handlers = build_public_tool_handlers(target)
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.status"}),
    )

    result = await handlers["get_shipagent_status"](
        context,
        {"correlation_id": "corr-1"},
    )

    assert result["status"] == "ready"
    assert result["executionTarget"]["target_id"] == "device-1"
    assert seen[0].account_id == "acct-1"
    assert seen[0].provider_connection_id == "pc-1"
    assert seen[0].tool_name == "get_shipagent_status"
    assert seen[0].arguments == {"correlation_id": "corr-1"}
```

- [ ] **Step 2: Run the execution-target test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_public_tool_handlers.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `execution_targets`.

- [ ] **Step 3: Add the execution target protocol**

Create `src/control_plane/execution_targets/__init__.py`:

```python
"""Execution target implementations for hosted public tools."""
```

Create `src/control_plane/execution_targets/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TargetToolRequest:
    account_id: str
    provider_connection_id: str
    provider_surface: str
    tool_name: str
    arguments: dict[str, Any]
    correlation_id: str


class ExecutionTarget(Protocol):
    async def invoke(self, request: TargetToolRequest) -> dict[str, Any]:
        """Invoke a provider-neutral workflow tool on the active execution target."""
```

- [ ] **Step 4: Add the loopback target**

Create `src/control_plane/execution_targets/loopback.py`:

```python
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.control_plane.execution_targets.base import TargetToolRequest

LoopbackHandler = Callable[[TargetToolRequest], Awaitable[dict[str, Any]] | dict[str, Any]]


class LoopbackExecutionTarget:
    def __init__(self, handlers: Mapping[str, LoopbackHandler]) -> None:
        self.handlers = dict(handlers)

    async def invoke(self, request: TargetToolRequest) -> dict[str, Any]:
        handler = self.handlers[request.tool_name]
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
        return result
```

- [ ] **Step 5: Add the relay target**

Create `src/control_plane/execution_targets/relay.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.control_plane.execution_targets.base import TargetToolRequest
from src.control_plane.relay.device_service import RelayDeviceService
from src.control_plane.relay.protocol import RelayTargetState, target_status_result
from src.control_plane.relay.session_manager import (
    RelaySessionError,
    RelayWebSocketSessionManager,
)


class RelayExecutionTarget:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        session_manager: RelayWebSocketSessionManager,
    ) -> None:
        self.session_factory = session_factory
        self.session_manager = session_manager

    async def invoke(self, request: TargetToolRequest) -> dict[str, Any]:
        async with self.session_factory() as db:
            device = await RelayDeviceService(db).get_active_device(request.account_id)
        if device is None:
            return target_status_result(
                state=RelayTargetState.OFFLINE,
                target_id=None,
                capabilities=(),
            )
        try:
            iterator = self.session_manager.invoke(
                account_id=request.account_id,
                device_id=device.id,
                tool_name=request.tool_name,
                arguments=request.arguments,
                audit_correlation_id=request.correlation_id,
                idempotency_key=request.correlation_id,
                timeout_seconds=25.0,
            )
            future = await iterator.__anext__()
            return await asyncio.wait_for(future, timeout=25.0)
        except (RelaySessionError, asyncio.TimeoutError):
            if request.tool_name == "get_shipagent_status":
                return target_status_result(
                    state=RelayTargetState.OFFLINE,
                    target_id=device.id,
                    capabilities=(),
                )
            return {
                "status": "unavailable",
                "reason": "target_offline",
                "terminal": True,
                "message": "The active ShipAgent runtime is offline. Ask the user to open ShipAgent Desktop and try again.",
            }
```

- [ ] **Step 6: Add public MCP handlers**

Create `src/control_plane/public_tool_handlers.py`:

```python
from __future__ import annotations

from typing import Any

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_targets.base import ExecutionTarget, TargetToolRequest


def build_public_tool_handlers(
    execution_target: ExecutionTarget,
) -> dict[str, object]:
    async def get_shipagent_status(
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        correlation_id = str(arguments.get("correlation_id", ""))
        return await execution_target.invoke(
            TargetToolRequest(
                account_id=context.account_id,
                provider_connection_id=context.provider_connection_id,
                provider_surface=context.provider_surface,
                tool_name="get_shipagent_status",
                arguments=arguments,
                correlation_id=correlation_id,
            )
        )

    return {"get_shipagent_status": get_shipagent_status}
```

- [ ] **Step 7: Run the public-handler test**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_public_tool_handlers.py -v
```

Expected: PASS.

- [ ] **Step 8: Re-run relay route tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_routes.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/control_plane/execution_targets src/control_plane/public_tool_handlers.py tests/control_plane/test_public_tool_handlers.py
git commit -m "feat: route public status through execution targets"
```

### Task 7: Export Status Tool and Prove Loopback `/mcp` in CI

**Files:**
- Modify: `src/control_plane/app.py`
- Modify: `src/registry/tools/public.py`
- Modify: `src/control_plane/routes/oauth_metadata.py`
- Modify: `tests/hosted/test_hosted_mcp_registry.py`
- Modify: `tests/registry/test_catalog.py`
- Modify: `tests/control_plane/test_app_auth.py`
- Create: `tests/control_plane/test_control_plane_mcp_status.py`
- Regenerate: `generated/provider_artifacts/registry.json`
- Regenerate: `generated/provider_artifacts/generic_mcp_tools.json`
- Regenerate: `generated/provider_artifacts/claude_remote_mcp_public_tools.json`
- Regenerate: `generated/provider_artifacts/openai_apps_public_tools.json`
- Regenerate: `generated/provider_artifacts/openai_apps_tools.json`
- Regenerate: `generated/provider_artifacts/gemini_functions.json`
- Regenerate: `generated/provider_artifacts/microsoft_openapi_operations.json`

- [ ] **Step 1: Write the failing loopback `/mcp` test**

Create `tests/control_plane/test_control_plane_mcp_status.py`:

```python
from datetime import UTC, datetime

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.execution_targets.base import TargetToolRequest
from src.control_plane.execution_targets.loopback import LoopbackExecutionTarget
from tests.control_plane.relay.fakes import FakeAsyncRedis


class _TokenVerifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def verify(self, token: str) -> TokenPrincipal:
        return TokenPrincipal(
            subject="auth0|owner-1",
            client_id="chatgpt-client",
            scopes=frozenset({"shipagent.status"}),
            auth_time=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )


class _AuthorizationService(AuthorizationService):
    async def resolve(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: set[str],
        auth_time=None,
    ) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1",
            provider_surface="chatgpt",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
            auth_time=auth_time,
        )


@pytest.mark.asyncio
async def test_get_shipagent_status_traverses_control_plane_mcp_to_loopback(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr("src.control_plane.app.Auth0TokenVerifier", _TokenVerifier)
    monkeypatch.setattr("src.control_plane.app.AuthorizationService", _AuthorizationService)

    async def status_handler(request: TargetToolRequest):
        assert request.account_id == "acct-1"
        assert request.tool_name == "get_shipagent_status"
        return {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "loopback",
                "capabilities": ["status"],
            },
        }

    app = create_control_plane_app(
        execution_target=LoopbackExecutionTarget({"get_shipagent_status": status_handler}),
        redis_client=FakeAsyncRedis(),
    )

    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            timeout=timeout or httpx.Timeout(30.0),
            follow_redirects=True,
            auth=auth,
        )

    transport = StreamableHttpTransport(
        "http://testserver/mcp",
        headers={"Authorization": "Bearer valid-token"},
        httpx_client_factory=client_factory,
    )
    async with Client(transport) as client:
        result = await client.call_tool_mcp(
            "get_shipagent_status",
            {"correlation_id": "corr-1"},
        )

    assert result.isError is False
    assert result.structuredContent == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": "loopback",
            "capabilities": ["status"],
        },
    }
```

- [ ] **Step 2: Run the loopback `/mcp` test and verify app injection is missing**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_control_plane_mcp_status.py -v
```

Expected: FAIL with `TypeError: create_control_plane_app() got an unexpected keyword argument 'execution_target'`.

- [ ] **Step 3: Wire execution targets and relay routes into the control-plane app**

Modify imports in `src/control_plane/app.py`:

```python
from src.control_plane.execution_targets.base import ExecutionTarget
from src.control_plane.execution_targets.relay import RelayExecutionTarget
from src.control_plane.public_tool_handlers import build_public_tool_handlers
from src.control_plane.relay.routes import build_relay_router
from src.control_plane.relay.session_manager import RelayWebSocketSessionManager
from src.control_plane.relay.session_registry import RedisRelaySessionRegistry
```

Change the function signature:

```python
def create_control_plane_app(
    *,
    execution_target: ExecutionTarget | None = None,
    redis_client=None,
) -> FastAPI:
```

Replace request-control and MCP construction:

```python
    redis = redis_client or _build_redis_client(settings.redis_url)
    request_controls = RequestControls(redis_client=redis)
    session_factory = _build_db_sessionmaker(settings.database_url)
    relay_registry = RedisRelaySessionRegistry(redis)
    relay_session_manager = RelayWebSocketSessionManager(relay_registry)
    target = execution_target or RelayExecutionTarget(
        session_factory=session_factory,
        session_manager=relay_session_manager,
    )
    mcp = build_server(
        tool_handlers=build_public_tool_handlers(target),
        request_controls=request_controls,
    )
```

After this existing metadata router block:

```python
    app.include_router(
        build_metadata_router(metadata_resource, settings.auth0_issuer)
    )
```

add:

```python
    app.state.relay_session_manager = relay_session_manager
    app.state.relay_registry = relay_registry
    app.include_router(
        build_relay_router(
            session_factory=session_factory,
            session_manager=relay_session_manager,
        ),
        prefix="/relay",
    )
```

- [ ] **Step 4: Run the loopback `/mcp` test and verify status is not exported yet**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_control_plane_mcp_status.py -v
```

Expected: FAIL with a FastMCP tool-not-found error for `get_shipagent_status`.

- [ ] **Step 5: Update the canonical status tool schema, scope, and export flag**

In `src/registry/tools/public.py`, replace the `get_shipagent_status` entry with:

```python
    public_tool(
        "get_shipagent_status",
        "Get shipagent status",
        "Return operational status for the active account and execution target.",
        SideEffectClass.read,
        ["shipagent.status"],
        object_schema(
            {
                "correlation_id": {
                    "type": "string",
                    "description": "Opaque client correlation identifier.",
                }
            },
            ["correlation_id"],
        ),
        object_schema(
            {
                "status": {"type": "string", "enum": ["ready", "offline", "update_required"]},
                "executionTarget": {
                    "type": "object",
                    "properties": {
                        "state": {"type": "string", "enum": ["ready", "offline", "update_required"]},
                        "target_id": {"type": ["string", "null"]},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["state", "target_id", "capabilities"],
                    "additionalProperties": False,
                },
            },
            ["status", "executionTarget"],
        ),
        provider_export_enabled=True,
        result_profile="aggregate",
    ),
```

In `src/control_plane/routes/oauth_metadata.py`, replace `SUPPORTED_SCOPES` with:

```python
SUPPORTED_SCOPES: Final = [
    "shipagent.status",
    "shipments:preview",
    "shipments:create",
    "shipments:execute",
    "jobs:read",
    "labels:read",
]
```

- [ ] **Step 6: Update hosted MCP tests for the target-agnostic status result**

In `tests/hosted/test_hosted_mcp_registry.py`, replace status handler return values with:

```python
        return {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "device-1",
                "capabilities": ["status", "rate", "ship"],
            },
        }
```

Replace contexts that currently use `{"account:read", "device:read"}` with:

```python
        scopes=frozenset({"shipagent.status"}),
```

Replace the missing-scope context with:

```python
        scopes=frozenset(),
```

Replace the required-scope assertion with:

```python
    assert exc.value.required_scopes == ["shipagent.status"]
```

Replace the expected structured content for status with:

```python
    assert result.structured_content == {
        "status": "ready",
        "executionTarget": {
            "state": "ready",
            "target_id": "device-1",
            "capabilities": ["status", "rate", "ship"],
        },
    }
```

- [ ] **Step 7: Update registry catalog tests for the narrow export**

In `tests/registry/test_catalog.py`, replace `test_public_tools_are_tenant_safe_and_provider_exportable` with:

```python
def test_public_tools_are_tenant_safe_and_provider_exportable():
    for tool in public_tools():
        assert tool.visibility == ToolVisibility.public
        assert tool.tenant_safe is True
        assert tool.implementation_status == "implemented"
        assert tool.hosted_readiness == "ready"
        assert tool.provider_export_enabled is (tool.name == "get_shipagent_status")
        assert ProviderExport.openai_apps_public in tool.provider_exports
        assert ProviderExport.claude_remote_mcp_public in tool.provider_exports
        assert ProviderExport.generic_mcp in tool.provider_exports
        assert ProviderExport.anthropic not in tool.provider_exports
```

- [ ] **Step 8: Regenerate provider artifacts**

Run:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
```

Expected: generated artifacts are updated and no command error occurs.

- [ ] **Step 9: Run status export and loopback tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_control_plane_mcp_status.py tests/hosted/test_hosted_mcp_registry.py tests/registry/test_catalog.py tests/registry/test_export.py tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/control_plane/app.py src/registry/tools/public.py src/control_plane/routes/oauth_metadata.py tests/hosted/test_hosted_mcp_registry.py tests/registry/test_catalog.py tests/control_plane/test_app_auth.py tests/control_plane/test_control_plane_mcp_status.py generated/provider_artifacts/registry.json generated/provider_artifacts/generic_mcp_tools.json generated/provider_artifacts/claude_remote_mcp_public_tools.json generated/provider_artifacts/openai_apps_public_tools.json generated/provider_artifacts/openai_apps_tools.json generated/provider_artifacts/gemini_functions.json generated/provider_artifacts/microsoft_openapi_operations.json
git commit -m "feat: expose status through hosted mcp loopback"
```

### Task 8: Desktop Relay Key Service

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/desktop/__init__.py`
- Modify: `src/desktop/relay_key_service.py`
- Test: `tests/desktop/test_relay_key_service.py`

- [ ] **Step 1: Declare the direct desktop WebSocket dependency**

In `pyproject.toml`, add this dependency near `httpx`:

```toml
    "websockets>=14.0",
```

Run:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

Expected: dependencies install successfully.

- [ ] **Step 2: Write failing relay-key tests**

Create `tests/desktop/test_relay_key_service.py`:

```python
from src.desktop.relay_key_service import RelayKeyService


class _MemoryStore:
    def __init__(self) -> None:
        self.values = {}
        self.deleted = []

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


def test_relay_key_service_generates_and_reuses_private_key():
    store = _MemoryStore()
    first = RelayKeyService(store=store)
    second = RelayKeyService(store=store)

    assert first.private_key_pem() == second.private_key_pem()
    assert first.public_key_pem().startswith("-----BEGIN PUBLIC KEY-----")
    assert len(first.fingerprint()) == 64


def test_relay_key_service_signs_auth_token():
    service = RelayKeyService(store=_MemoryStore())

    token = service.sign_auth_token(
        device_id="device-1",
        account_id="acct-1",
        relay_session_id="session-1",
        nonce="n" * 32,
    )

    assert token.count(".") == 2
```

- [ ] **Step 3: Implement desktop relay key service**

Ensure `src/desktop/__init__.py` contains:

```python
"""ShipAgent Desktop runtime helpers."""
```

Create `src/desktop/relay_key_service.py`:

```python
from __future__ import annotations

from datetime import datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.control_plane.relay.protocol import (
    VersionMetadata,
    private_key_to_public_pem,
    public_key_fingerprint,
    relay_auth_claims_for_now,
    sign_relay_auth_token,
)
from src.services.keyring_store import KeyringStore

RELAY_PRIVATE_KEY_NAME = "SHIPAGENT_RELAY_DEVICE_PRIVATE_KEY"


class RelayKeyService:
    def __init__(
        self,
        *,
        store=None,
        key_name: str = RELAY_PRIVATE_KEY_NAME,
    ) -> None:
        self.store = store or KeyringStore()
        self.key_name = key_name

    def private_key_pem(self) -> str:
        existing = self.store.get(self.key_name)
        if existing:
            return existing
        private_key = ed25519.Ed25519PrivateKey.generate()
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        self.store.set(self.key_name, private_key_pem)
        return private_key_pem

    def public_key_pem(self) -> str:
        return private_key_to_public_pem(self.private_key_pem())

    def fingerprint(self) -> str:
        return public_key_fingerprint(self.public_key_pem())

    def rotate(self) -> str:
        self.store.delete(self.key_name)
        return self.public_key_pem()

    def sign_auth_token(
        self,
        *,
        device_id: str,
        account_id: str,
        relay_session_id: str,
        nonce: str,
        now: datetime | None = None,
        version: VersionMetadata | None = None,
    ) -> str:
        metadata = version or VersionMetadata(
            shipagent_core_version="0.1.0",
            registry_contract_version="1.0.0",
            ups_boundary_contract_version="shipagent_v1",
            capabilities=("status", "relay.invoke"),
        )
        claims = relay_auth_claims_for_now(
            device_id=device_id,
            account_id=account_id,
            relay_session_id=relay_session_id,
            nonce=nonce,
            version=metadata,
            now=now,
        )
        return sign_relay_auth_token(
            self.private_key_pem(),
            claims,
            key_id=self.fingerprint(),
        )
```

- [ ] **Step 4: Run desktop key tests**

Run:

```bash
.venv/bin/python -m pytest tests/desktop/test_relay_key_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/desktop/__init__.py src/desktop/relay_key_service.py tests/desktop/test_relay_key_service.py
git commit -m "feat: add desktop relay key service"
```

### Task 9: Desktop Relay Client

**Files:**
- Create: `src/desktop/desktop_relay_client.py`
- Test: `tests/desktop/test_desktop_relay_client.py`

- [ ] **Step 1: Write failing desktop relay client tests**

Create `tests/desktop/test_desktop_relay_client.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.relay.protocol import RelayInvocationEnvelope
from src.desktop.desktop_relay_client import DesktopRelayClient, RelayEnvelopeRejected
from src.desktop.relay_key_service import RelayKeyService


class _MemoryStore:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _envelope(sequence: int, session_id: str = "session-1") -> RelayInvocationEnvelope:
    return RelayInvocationEnvelope(
        relay_session_id=session_id,
        sequence=sequence,
        relay_invocation_id=f"inv-{sequence}",
        tool_name="get_shipagent_status",
        arguments={"correlation_id": "corr-1"},
        input_hash="a" * 64,
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
        idempotency_key="idem-1",
        audit_correlation_id="audit-1",
    )


@pytest.mark.asyncio
async def test_desktop_client_rejects_wrong_session_and_duplicate_sequence():
    client = DesktopRelayClient(
        relay_url="ws://localhost/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=RelayKeyService(store=_MemoryStore()),
        handlers={},
    )
    client.mark_authenticated("session-1")

    with pytest.raises(RelayEnvelopeRejected, match="session_mismatch"):
        client.validate_envelope(_envelope(1, session_id="other"))

    client.validate_envelope(_envelope(1))
    with pytest.raises(RelayEnvelopeRejected, match="non_increasing_sequence"):
        client.validate_envelope(_envelope(1))


@pytest.mark.asyncio
async def test_desktop_client_dispatches_invocation_to_handler():
    async def handler(arguments):
        return {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": "device-1",
                "capabilities": ["status"],
            },
        }

    client = DesktopRelayClient(
        relay_url="ws://localhost/relay/connect",
        account_id="acct-1",
        device_id="device-1",
        key_service=RelayKeyService(store=_MemoryStore()),
        handlers={"get_shipagent_status": handler},
    )
    client.mark_authenticated("session-1")

    result = await client.dispatch_envelope(_envelope(1))

    assert result.status == "ok"
    assert result.result["executionTarget"]["target_id"] == "device-1"
```

- [ ] **Step 2: Run the desktop relay client tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/desktop/test_desktop_relay_client.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `desktop_relay_client`.

- [ ] **Step 3: Implement the desktop relay client**

Create `src/desktop/desktop_relay_client.py`:

```python
from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import websockets

from src.control_plane.relay.protocol import (
    RelayAuthenticateMessage,
    RelayAuthenticatedMessage,
    RelayChallenge,
    RelayErrorEnvelope,
    RelayInvocationEnvelope,
    RelayInvocationResult,
)
from src.desktop.relay_key_service import RelayKeyService

DesktopRelayHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


class RelayEnvelopeRejected(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class DesktopRelayClient:
    def __init__(
        self,
        *,
        relay_url: str,
        account_id: str,
        device_id: str,
        key_service: RelayKeyService,
        handlers: Mapping[str, DesktopRelayHandler],
    ) -> None:
        self.relay_url = relay_url
        self.account_id = account_id
        self.device_id = device_id
        self.key_service = key_service
        self.handlers = dict(handlers)
        self.relay_session_id: str | None = None
        self.last_sequence = 0
        self.accepted_invocations: set[str] = set()

    def mark_authenticated(self, relay_session_id: str) -> None:
        self.relay_session_id = relay_session_id
        self.last_sequence = 0
        self.accepted_invocations.clear()

    def validate_envelope(self, envelope: RelayInvocationEnvelope) -> None:
        if self.relay_session_id is None:
            raise RelayEnvelopeRejected("not_authenticated", "relay session is not authenticated")
        if envelope.relay_session_id != self.relay_session_id:
            raise RelayEnvelopeRejected("session_mismatch", "relay invocation used the wrong session")
        if envelope.sequence <= self.last_sequence:
            raise RelayEnvelopeRejected("non_increasing_sequence", "relay invocation sequence must increase")
        if envelope.relay_invocation_id in self.accepted_invocations:
            raise RelayEnvelopeRejected("duplicate_invocation", "relay invocation id was already accepted")
        if envelope.deadline_at <= datetime.now(UTC):
            raise RelayEnvelopeRejected("deadline_exceeded", "relay invocation deadline has passed")
        self.last_sequence = envelope.sequence
        self.accepted_invocations.add(envelope.relay_invocation_id)

    async def dispatch_envelope(self, envelope: RelayInvocationEnvelope) -> RelayInvocationResult:
        self.validate_envelope(envelope)
        handler = self.handlers.get(envelope.tool_name)
        if handler is None:
            return RelayInvocationResult(
                relay_session_id=envelope.relay_session_id,
                relay_invocation_id=envelope.relay_invocation_id,
                sequence=envelope.sequence,
                status="error",
                error={
                    "code": "unknown_tool",
                    "message": f"Desktop relay has no handler for {envelope.tool_name}",
                },
            )
        result = handler(envelope.arguments)
        if inspect.isawaitable(result):
            result = await result
        return RelayInvocationResult(
            relay_session_id=envelope.relay_session_id,
            relay_invocation_id=envelope.relay_invocation_id,
            sequence=envelope.sequence,
            status="ok",
            result=result,
        )

    async def run_forever(self) -> None:
        async with websockets.connect(self.relay_url) as websocket:
            challenge = RelayChallenge.model_validate_json(await websocket.recv())
            token = self.key_service.sign_auth_token(
                device_id=self.device_id,
                account_id=self.account_id,
                relay_session_id=challenge.relay_session_id,
                nonce=challenge.nonce,
            )
            await websocket.send(
                RelayAuthenticateMessage(token=token).model_dump_json()
            )
            accepted = RelayAuthenticatedMessage.model_validate_json(await websocket.recv())
            self.mark_authenticated(accepted.relay_session_id)
            async for raw_message in websocket:
                payload = json.loads(raw_message)
                if payload.get("type") != "relay.invoke":
                    await websocket.send(
                        RelayErrorEnvelope(
                            code="unexpected_message",
                            message="desktop relay expected invocation envelope",
                            relay_session_id=self.relay_session_id,
                        ).model_dump_json()
                    )
                    continue
                result = await self.dispatch_envelope(
                    RelayInvocationEnvelope.model_validate(payload)
                )
                await websocket.send(result.model_dump_json())
```

- [ ] **Step 4: Run desktop relay client tests**

Run:

```bash
.venv/bin/python -m pytest tests/desktop/test_desktop_relay_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/desktop/desktop_relay_client.py tests/desktop/test_desktop_relay_client.py
git commit -m "feat: add desktop relay websocket client"
```

### Task 10: Real Relay `/mcp` Integration

**Files:**
- Create: `tests/control_plane/relay/test_two_process_relay_mcp.py`

- [ ] **Step 1: Write the end-to-end integration test**

Create `tests/control_plane/relay/test_two_process_relay_mcp.py`:

```python
from __future__ import annotations

import asyncio
import socket
import threading
import time
from datetime import UTC, datetime

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy import create_engine

from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.models import ControlPlaneBase
from src.desktop.desktop_relay_client import DesktopRelayClient
from src.desktop.relay_key_service import RelayKeyService
from tests.control_plane.relay.fakes import FakeAsyncRedis


class _TokenVerifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def verify(self, token: str) -> TokenPrincipal:
        return TokenPrincipal(
            subject="auth0|owner-1",
            client_id="chatgpt-client" if token == "provider" else "desktop-client",
            scopes=frozenset({"shipagent.status"} if token == "provider" else {"relay:device:manage"}),
            auth_time=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )


class _AuthorizationService(AuthorizationService):
    async def resolve(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: set[str],
        auth_time=None,
    ) -> AuthorizationContext:
        return AuthorizationContext(
            account_id="acct-1",
            provider_connection_id="pc-1" if client_id == "chatgpt-client" else "pc-desktop",
            provider_surface="chatgpt" if client_id == "chatgpt-client" else "desktop",
            subject=subject,
            client_id=client_id,
            scopes=frozenset(scopes),
            auth_time=auth_time,
        )


class _MemoryStore:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _ServerThread:
    def __init__(self, app, port: int) -> None:
        self.config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 5
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        assert self.server.started is True

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.mark.asyncio
async def test_get_shipagent_status_traverses_cloud_mcp_to_real_desktop_client(monkeypatch, tmp_path):
    db_path = tmp_path / "control.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    sync_engine = create_engine(f"sqlite:///{db_path}")
    ControlPlaneBase.metadata.create_all(sync_engine)
    sync_engine.dispose()

    monkeypatch.setenv("SHIPAGENT_PUBLIC_BASE_URL", "https://dev-mcp.shipagent.app/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_ISSUER", "https://tenant.us.auth0.com/")
    monkeypatch.setenv("SHIPAGENT_AUTH0_AUDIENCE", "https://dev-mcp.shipagent.app")
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", database_url)
    monkeypatch.setenv("SHIPAGENT_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr("src.control_plane.app.Auth0TokenVerifier", _TokenVerifier)
    monkeypatch.setattr("src.control_plane.app.AuthorizationService", _AuthorizationService)

    app = create_control_plane_app(redis_client=FakeAsyncRedis())
    port = _free_port()
    server = _ServerThread(app, port)
    server.start()
    key_service = RelayKeyService(store=_MemoryStore())
    base_url = f"http://127.0.0.1:{port}"
    relay_url = f"ws://127.0.0.1:{port}/relay/connect"

    async with httpx.AsyncClient(base_url=base_url) as http:
        registered = await http.post(
            "/relay/devices/register",
            json={"public_key_pem": key_service.public_key_pem()},
            headers={"Authorization": "Bearer desktop"},
        )
        assert registered.status_code == 200
        device_id = registered.json()["device_id"]

    async def status_handler(arguments):
        return {
            "status": "ready",
            "executionTarget": {
                "state": "ready",
                "target_id": device_id,
                "capabilities": ["status", "relay.invoke"],
            },
        }

    desktop = DesktopRelayClient(
        relay_url=relay_url,
        account_id="acct-1",
        device_id=device_id,
        key_service=key_service,
        handlers={"get_shipagent_status": status_handler},
    )
    desktop_task = asyncio.create_task(desktop.run_forever())

    try:
        for _ in range(20):
            if desktop.relay_session_id is not None:
                break
            await asyncio.sleep(0.05)
        assert desktop.relay_session_id is not None

        transport = StreamableHttpTransport(
            f"{base_url}/mcp",
            headers={"Authorization": "Bearer provider"},
        )
        async with Client(transport) as client:
            result = await client.call_tool_mcp(
                "get_shipagent_status",
                {"correlation_id": "corr-1"},
            )

        assert result.isError is False
        assert result.structuredContent["status"] == "ready"
        assert result.structuredContent["executionTarget"]["target_id"] == device_id
    finally:
        desktop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await desktop_task
        server.stop()
```

- [ ] **Step 2: Run the real relay integration test and verify failures are actionable**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay/test_two_process_relay_mcp.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/control_plane/relay/test_two_process_relay_mcp.py
git commit -m "test: prove status traverses cloud relay to desktop"
```

### Task 11: Slice Verification

**Files:**
- Verify: `src/control_plane/`
- Verify: `src/desktop/`
- Verify: `tests/control_plane/`
- Verify: `tests/desktop/`
- Verify: `tests/hosted/test_hosted_mcp_registry.py`
- Verify: `tests/registry/`
- Verify: `generated/provider_artifacts/`

- [ ] **Step 1: Run all targeted relay and control-plane tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/relay tests/control_plane/test_public_tool_handlers.py tests/control_plane/test_control_plane_mcp_status.py tests/control_plane/auth tests/control_plane/test_app_auth.py tests/desktop tests/hosted/test_hosted_mcp_registry.py tests/registry -v
```

Expected: PASS.

- [ ] **Step 2: Run control-plane migration check**

Run:

```bash
alembic -c alembic.ini upgrade head
```

Expected: database upgrades through `20260630_0002`.

- [ ] **Step 3: Run registry artifact drift check**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 4: Run ruff formatting and lint checks**

Run:

```bash
.venv/bin/python -m ruff format src/control_plane src/desktop tests/control_plane tests/desktop tests/hosted tests/registry
.venv/bin/python -m ruff check src/control_plane src/desktop tests/control_plane tests/desktop tests/hosted tests/registry
```

Expected: both commands pass.

- [ ] **Step 5: Run broader backend validation scoped away from slow stream/progress tests**

Run:

```bash
.venv/bin/python -m pytest -k "not stream and not sse and not progress"
```

Expected: PASS.

- [ ] **Step 6: Commit verification-only fixes**

If Step 1 through Step 5 required formatting or test-only adjustments, commit them:

```bash
git add src/control_plane src/desktop tests/control_plane tests/desktop tests/hosted tests/registry generated/provider_artifacts pyproject.toml alembic/versions/20260630_0002_relay_devices.py
git commit -m "chore: verify relay walking skeleton"
```

If there were no changes after verification, do not create an empty commit.

## Dependencies Delivered to Later Plans

- `src/control_plane/relay/protocol.py` is the canonical source for relay handshake, heartbeat, invocation, and target status envelope types.
- `RelayDevice` and `RelayDeviceService` provide the account-bound device identity store that Plans 2, 3, 4, 9, and 10 should reuse.
- `RedisRelaySessionRegistry` provides the heartbeat/session Redis record; Plan 4 should extend TTL policy and purge behavior instead of introducing alternate relay keys.
- `RelayWebSocketSessionManager` provides the first process-local send/result path; Plan 2 should extend this with durable invocation lifecycle and recovery.
- `ExecutionTarget`, `RelayExecutionTarget`, and `LoopbackExecutionTarget` provide the SaaS-forward dispatch seam required by ADR 0002.
- `build_public_tool_handlers` establishes where hosted `/mcp` handlers bind registry tools to execution targets; later public tools should add handlers here or in a sibling module rather than in provider adapters.
- `RelayKeyService` and `DesktopRelayClient` provide the desktop-side PoP handshake and local invocation dispatcher that Plan 9 can call from Cloud AI settings.
- Relay device management must expose the full Plan 9 control surface: register, list, rotate key, revoke, set active, and unlink. If the first Plan 1 implementation lands only register/rotate/revoke, extend Plan 1 before starting Plan 9 implementation rather than adding cloud relay-device routes from Plan 9.

## Overlap Notes for Plans 2-10

- Plan 2 owns durable invocation lifecycle, timeout ladder, reconnect reconciliation, and recovery states. Plan 1 must not add Redis invocation state beyond the one in-flight future needed for the skeleton.
- Plan 3 owns compatibility enforcement. Plan 1 records version metadata and capabilities but always accepts compatible-looking handshakes without matrix checks.
- Plan 4 owns retention sweeps, purge jobs, and durable authorization audit. Plan 1 only sets relay heartbeat/session TTLs already required for live routing.
- Plan 5 owns dedupe, coalescing, loop breaker v2, and result-size caps. Plan 1 only uses existing `RequestControls` and `hash_arguments`.
- Plan 6 owns provider projections, output profiles, origin-based redaction, public scope vocabulary cleanup, and wider registry export decisions. Plan 1 changes only `get_shipagent_status` because the walking skeleton needs a callable `/mcp` tool.
- Plan 7 owns prepare/execute grants, Approval Requests, label download references, and money-changing dispatch. Plan 1 must not implement shipment execution or approval state.
- Plan 8 owns OpenAI widget resources and app-only execute visibility. Plan 1 should not touch `shipagent-frontend/`.
- Plan 9 owns desktop settings, PKCE login UX, device list UI, local sidecar facade, set-active/unlink UI actions, and Tauri keychain entitlement checks. Plan 1 provides the cloud relay-device endpoints and desktop relay primitives that those local actions call.
- Plan 10 owns the full adversarial/golden corpus. Plan 1 includes basic handshake and replay tests so Plan 10 can expand them rather than inventing new protocol entry points.

## Review Notes

- Spec coverage: Plan 1 maps to protocol, Auth0 account identity for device management, relay topology, Ed25519 PoP, register/list/rotate/revoke/set-active/unlink, Redis session registry, desktop key/client code, `ExecutionTarget` seam, loopback CI test, and real WSS integration.
- Boundary check: no UPS, shipment creation, label, approval-grant, provider-widget, or output-profile behavior is assigned to this slice.
- Type consistency: status output uses `executionTarget` in registry schema, loopback, relay target, desktop handler, and tests.
