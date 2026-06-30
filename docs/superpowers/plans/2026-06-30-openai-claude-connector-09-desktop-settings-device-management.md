# Desktop Settings Device Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Plan 9 from the OpenAI/Claude connector design: Cloud AI Features enablement, desktop account linking, device management, relay status display, and keychain entitlement visibility in the settings remote.

**Architecture:** Add a thin local sidecar facade under `/api/v1/cloud-ai` that drives Plan 1 relay key, browser PKCE, cloud device, and relay-client services without putting OAuth tokens or private keys in Angular. The Angular settings remote consumes typed shared API methods and a small shared SignalStore, while Tauri exposes only a keychain entitlement status command. Plan 9 does not implement cloud relay transport, control-plane device persistence, invocation routing, approval pages, provider projection, or retention policy.

**Tech Stack:** Python 3.12, FastAPI, pytest/pytest-asyncio, Angular 21 standalone components, Nx 22, NgRx SignalStore, RxJS, Tauri v2, Rust 2021.

---

## Source Of Truth

Use these documents and files as authoritative inputs:

- `docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md`, especially Plan 9 and Q26-Q31.
- `docs/adr/0001-cloud-account-auth0-identity.md`
- `docs/adr/0002-relay-first-execution-target.md`
- `docs/adr/0004-cryptographic-relay-identity.md`
- `AGENTS.md`
- `src/AGENTS.md`
- `shipagent-frontend/AGENTS.md`
- `src-tauri/src/main.rs`
- `src-tauri/capabilities/default.json`
- `src-tauri/entitlements.plist`
- `shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts`
- `shipagent-frontend/libs/shared/api/src/api.service.ts`
- `shipagent-frontend/libs/shared/types/src/settings.types.ts`
- `shipagent-frontend/libs/shared/state/src/settings.store.ts`
- `shipagent-frontend/libs/shared/tauri/src/port-resolver.ts`
- `shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts`

Plan 9 owns:

- Local desktop settings facade for Cloud AI actions under `/api/v1/cloud-ai`.
- Browser PKCE initiation and recent-auth status projection into settings.
- Device-key generation, current-device registration, device list, revoke, rotate, set-active, and unlink actions from settings.
- Relay status indicator in settings.
- Tauri keychain entitlement status command and settings UI warning.

Plan 9 does not own:

- Cloud `/relay/connect` websocket, nonce/JWT handshake, Redis session registry, or `ExecutionTarget` implementation from Plan 1.
- Invocation lifecycle, recovery, job references, or relay dispatcher changes from Plan 2.
- Version compatibility enforcement from Plan 3.
- Redis/SQL retention and authorization audit from Plan 4.
- Ingress guard v2 from Plan 5.
- Provider descriptor projection or result redaction from Plan 6.
- Approval surface and provider execution flow from Plan 7.
- OpenAI widget UI from Plan 8.
- Golden prompt and adversarial corpus from Plan 10.

## Current Repo State

Relevant observations from planning inspection:

- `src/control_plane/relay/` is not present in this checkout, so the implementation must wait for the Plan 1 branch or merge equivalent Plan 1 names before starting source changes.
- `src/api/main.py` imports route modules from `src.api.routes` and mounts them under `/api/v1`.
- `src/api/routes/settings.py` already exposes keychain-backed credential status via `src/services/keyring_store.py`; do not extend credential APIs for device keys.
- `src/services/keyring_store.py` uses Python `keyring` with service name `com.shipagent.app`.
- `shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts` is an accordion with four standalone sections. Add a fifth `Cloud AI` section.
- `shipagent-frontend/libs/shared/api/src/api.service.ts` centralizes HttpClient calls and returns `Observable<T>`.
- `shipagent-frontend/libs/shared/types/src/index.ts` is the frontend type barrel.
- `shipagent-frontend/libs/shared/state/src/` contains NgRx SignalStores. Only `shared-state` has a dedicated Nx test target.
- `shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts` must be extended whenever `ApiService` gains Observable methods.
- `src-tauri/src/main.rs` currently exposes one command, `start_sidecar`, through Tauri `invoke`.
- `src-tauri/capabilities/default.json` contains plugin permissions for shell and updater. Keep those permissions unchanged for the local custom app command; do not widen shell access.
- `src-tauri/entitlements.plist` has no keychain access group entry.

## Plan 1 Contract Consumed

Plan 9 can implement local sidecar routes, frontend state, settings UI, and Tauri entitlement checks in parallel with Plan 1 by using the fakes in this plan. Do not wire `CloudAiSettingsService.from_environment()` into real runtime verification until Plan 1 has landed these integration surfaces, or reconcile Plan 1 to expose exactly equivalent names before starting production integration:

- `src/services/desktop_device_auth.py`
  - `DesktopDeviceAuthCoordinator.start_browser_login()`
  - `DesktopDeviceAuthCoordinator.get_current_session()`
  - `DesktopDeviceAuthCoordinator.require_recent_session(max_age_seconds=600)`
- `src/services/relay_key_service.py`
  - `RelayKeyService.ensure_device_key(display_name: str | None)`
  - `RelayKeyService.rotate_device_key()`
  - `RelayKeyService.delete_device_key()`
  - `RelayKeyService.get_key_status()`
- `src/services/relay_device_client.py`
  - `RelayDeviceClient.register_device(...)`
  - `RelayDeviceClient.list_devices(...)`
  - `RelayDeviceClient.revoke_device(...)`
  - `RelayDeviceClient.rotate_device_key(...)`
  - `RelayDeviceClient.set_active_device(...)`
  - `RelayDeviceClient.unlink_account(...)`
- `src/services/desktop_relay_client.py`
  - `DesktopRelayClient.get_status()`
  - `DesktopRelayClient.ensure_connected()`
  - `DesktopRelayClient.disconnect()`

The local sidecar facade must call cloud control-plane endpoints through Plan 1 clients. Angular never calls cloud `/relay/devices/*` directly and never stores the Auth0 access token, PKCE verifier, Ed25519 private key, or public-key registration token. If Plan 1 lands the low-level relay key or WSS client under `src.desktop.*`, add thin `src.services.*` re-export modules before this plan's Task 1 production integration so Plan 2 and Plan 9 use one stable import path.

## Local API Contract

Plan 9 adds these local sidecar endpoints under the existing desktop API origin:

| Method | Path | Body | Response |
|---|---|---|---|
| `GET` | `/api/v1/cloud-ai/status` | none | `CloudAiStatusResponse` |
| `POST` | `/api/v1/cloud-ai/auth/start` | none | `CloudAiBrowserLoginStartResponse` |
| `GET` | `/api/v1/cloud-ai/auth/session` | none | `CloudAiAuthSession` |
| `POST` | `/api/v1/cloud-ai/device-key` | `{ "display_name": "Matthew's MacBook Pro" }` | `CloudAiDeviceKeyResponse` |
| `GET` | `/api/v1/cloud-ai/devices` | none | `CloudAiDeviceListResponse` |
| `POST` | `/api/v1/cloud-ai/devices/register` | `{ "display_name": "Matthew's MacBook Pro" }` | `CloudAiStatusResponse` |
| `POST` | `/api/v1/cloud-ai/devices/current/rotate-key` | none | `CloudAiStatusResponse` |
| `POST` | `/api/v1/cloud-ai/devices/{device_id}/revoke` | none | `CloudAiDeviceActionResponse` |
| `POST` | `/api/v1/cloud-ai/devices/{device_id}/set-active` | none | `CloudAiStatusResponse` |
| `POST` | `/api/v1/cloud-ai/unlink` | `{ "delete_local_key": true, "confirmation": "unlink" }` | `CloudAiStatusResponse` |

Recent-auth failures return HTTP 401:

```json
{
  "detail": {
    "code": "recent_auth_required",
    "message": "Sign in again to manage Cloud AI devices."
  }
}
```

Unlink confirmation failures return HTTP 400:

```json
{
  "detail": {
    "code": "unlink_confirmation_required",
    "message": "Type unlink before deleting the local device key."
  }
}
```

## Target File Structure

Create:

```text
src/services/cloud_ai_settings_service.py
src/api/routes/cloud_ai.py
tests/services/test_cloud_ai_settings_service.py
tests/api/test_cloud_ai.py
shipagent-frontend/libs/shared/types/src/cloud-ai.types.ts
shipagent-frontend/libs/shared/state/src/cloud-ai.store.ts
shipagent-frontend/libs/shared/state/src/cloud-ai.store.spec.ts
shipagent-frontend/libs/shared/tauri/src/keychain-entitlement.ts
shipagent-frontend/libs/testing/src/fixtures/cloud-ai.fixtures.ts
shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-browser-auth.service.ts
shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-keychain.service.ts
shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.ts
shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.spec.ts
```

Modify:

```text
src/api/main.py
shipagent-frontend/libs/shared/types/src/index.ts
shipagent-frontend/libs/shared/api/src/api.service.ts
shipagent-frontend/libs/shared/state/src/index.ts
shipagent-frontend/libs/shared/tauri/src/index.ts
shipagent-frontend/libs/testing/src/index.ts
shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts
shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts
src-tauri/src/main.rs
src-tauri/entitlements.plist
```

Do not modify:

```text
src/control_plane/
src/services/conversation_runtime/
src/hosted_mcp/
src/registry/
generated/provider_artifacts/
provider-widget/
shipagent-frontend/apps/chat-remote/
shipagent-frontend/apps/sidebar-remote/
shipagent-frontend/apps/domain-remote/
```

## Task 1: Local Cloud AI Settings Service

**Files:**

- Create: `src/services/cloud_ai_settings_service.py`
- Test: `tests/services/test_cloud_ai_settings_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/services/test_cloud_ai_settings_service.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.services.cloud_ai_settings_service import (
    BrowserLoginStart,
    CloudAiSettingsService,
    DeviceKeySummary,
    RecentAuthRequired,
    RecentAuthSession,
    RelayDeviceSummary,
    RelayStatusSummary,
)


FIXED_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class FakeAuthCoordinator:
    def __init__(self, session: RecentAuthSession) -> None:
        self.session = session
        self.started = False

    async def start_browser_login(self) -> BrowserLoginStart:
        self.started = True
        return BrowserLoginStart(
            auth_url="https://auth.example.test/authorize?state=abc",
            expires_at=FIXED_NOW + timedelta(minutes=5),
            state_fingerprint="state-fp",
        )

    async def get_current_session(self) -> RecentAuthSession:
        return self.session

    async def require_recent_session(self, max_age_seconds: int = 600) -> RecentAuthSession:
        if not self.session.authenticated:
            raise RecentAuthRequired()
        if self.session.authenticated_at is None:
            raise RecentAuthRequired()
        if (FIXED_NOW - self.session.authenticated_at).total_seconds() > max_age_seconds:
            raise RecentAuthRequired()
        return self.session


class FakeKeyService:
    def __init__(self) -> None:
        self.key = DeviceKeySummary(
            installation_id="install-1",
            device_id=None,
            fingerprint="fp-old",
            public_key="pub-old",
            created_at=FIXED_NOW - timedelta(days=1),
            rotated_at=None,
        )
        self.deleted = False

    async def get_key_status(self) -> DeviceKeySummary | None:
        return self.key

    async def ensure_device_key(self, display_name: str | None = None) -> DeviceKeySummary:
        return self.key

    async def rotate_device_key(self) -> DeviceKeySummary:
        self.key = replace(
            self.key,
            fingerprint="fp-new",
            public_key="pub-new",
            rotated_at=FIXED_NOW,
        )
        return self.key

    async def delete_device_key(self) -> None:
        self.deleted = True
        self.key = None


class FakeDeviceClient:
    def __init__(self) -> None:
        self.devices: list[RelayDeviceSummary] = [
            RelayDeviceSummary(
                device_id="device-1",
                installation_id="install-1",
                display_name="Work Mac",
                fingerprint="fp-old",
                status="online",
                is_current=True,
                is_active=True,
                last_seen_at=FIXED_NOW,
                created_at=FIXED_NOW - timedelta(days=1),
                capabilities=["relay.invoke.v1"],
                shipagent_core_version="0.1.0",
                registry_contract_version="2026-06-10",
                ups_boundary_contract_version="2026-06-10",
            )
        ]
        self.registered_display_name: str | None = None
        self.revoked_device_id: str | None = None
        self.active_device_id: str | None = None
        self.unlinked = False

    async def register_device(
        self,
        access_token: str,
        display_name: str,
        key: DeviceKeySummary,
    ) -> RelayDeviceSummary:
        self.registered_display_name = display_name
        device = replace(
            self.devices[0],
            display_name=display_name,
            fingerprint=key.fingerprint,
            status="online",
            is_current=True,
            is_active=True,
        )
        self.devices = [device]
        return device

    async def list_devices(self, access_token: str | None) -> list[RelayDeviceSummary]:
        return self.devices

    async def revoke_device(self, access_token: str, device_id: str) -> None:
        self.revoked_device_id = device_id
        self.devices = [
            replace(device, status="revoked")
            if device.device_id == device_id
            else device
            for device in self.devices
        ]

    async def rotate_device_key(
        self,
        access_token: str,
        key: DeviceKeySummary,
    ) -> RelayDeviceSummary:
        self.devices = [replace(self.devices[0], fingerprint=key.fingerprint)]
        return self.devices[0]

    async def set_active_device(self, access_token: str, device_id: str) -> RelayDeviceSummary:
        self.active_device_id = device_id
        self.devices = [
            replace(device, is_active=device.device_id == device_id)
            for device in self.devices
        ]
        return next(device for device in self.devices if device.device_id == device_id)

    async def unlink_account(self, access_token: str) -> None:
        self.unlinked = True


class FakeRelayClient:
    def __init__(self) -> None:
        self.connected = False

    async def get_status(self) -> RelayStatusSummary:
        return RelayStatusSummary(
            state="online" if self.connected else "offline",
            relay_session_id="session-1" if self.connected else None,
            active_device_id="device-1" if self.connected else None,
            last_heartbeat_at=FIXED_NOW if self.connected else None,
            message=None,
        )

    async def ensure_connected(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


def fresh_session() -> RecentAuthSession:
    return RecentAuthSession(
        authenticated=True,
        authenticated_at=FIXED_NOW - timedelta(minutes=2),
        expires_at=FIXED_NOW + timedelta(minutes=8),
        account_id="account-1",
        account_email="ops@example.test",
        scopes=["shipagent.device"],
        access_token="secret-token",
    )


def build_service(session: RecentAuthSession) -> tuple[
    CloudAiSettingsService,
    FakeKeyService,
    FakeDeviceClient,
    FakeRelayClient,
]:
    keys = FakeKeyService()
    devices = FakeDeviceClient()
    relay = FakeRelayClient()
    service = CloudAiSettingsService(
        auth=FakeAuthCoordinator(session),
        keys=keys,
        devices=devices,
        relay=relay,
        now=lambda: FIXED_NOW,
    )
    return service, keys, devices, relay


@pytest.mark.asyncio
async def test_start_browser_login_delegates_to_auth_coordinator() -> None:
    service, _, _, _ = build_service(fresh_session())

    result = await service.start_browser_login()

    assert result.auth_url == "https://auth.example.test/authorize?state=abc"
    assert result.state_fingerprint == "state-fp"


@pytest.mark.asyncio
async def test_status_hides_access_token_and_includes_relay_state() -> None:
    service, _, _, relay = build_service(fresh_session())
    await relay.ensure_connected()

    status = await service.get_status()

    assert status.auth.authenticated is True
    assert status.auth.account_email == "ops@example.test"
    assert status.auth.access_token is None
    assert status.relay.state == "online"
    assert status.current_device_id == "device-1"
    assert status.active_device_id == "device-1"


@pytest.mark.asyncio
async def test_register_current_device_requires_recent_auth() -> None:
    stale = replace(
        fresh_session(),
        authenticated_at=FIXED_NOW - timedelta(minutes=15),
    )
    service, _, _, _ = build_service(stale)

    with pytest.raises(RecentAuthRequired):
        await service.register_current_device("Work Mac")


@pytest.mark.asyncio
async def test_register_current_device_generates_key_registers_and_connects_relay() -> None:
    service, _, devices, relay = build_service(fresh_session())

    status = await service.register_current_device("Work Mac")

    assert devices.registered_display_name == "Work Mac"
    assert status.enabled is True
    assert status.relay.state == "online"
    assert relay.connected is True


@pytest.mark.asyncio
async def test_rotate_current_device_key_requires_recent_auth_and_preserves_device_identity() -> None:
    service, _, devices, _ = build_service(fresh_session())

    status = await service.rotate_current_device_key()

    assert status.key is not None
    assert status.key.fingerprint == "fp-new"
    assert devices.devices[0].device_id == "device-1"
    assert devices.devices[0].fingerprint == "fp-new"


@pytest.mark.asyncio
async def test_unlink_requires_confirmation_before_local_key_deletion() -> None:
    service, keys, devices, relay = build_service(fresh_session())
    await relay.ensure_connected()

    status = await service.unlink_account(delete_local_key=True, confirmation="unlink")

    assert devices.unlinked is True
    assert keys.deleted is True
    assert status.enabled is False
    assert status.relay.state == "offline"
```

- [ ] **Step 2: Run the service tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_cloud_ai_settings_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.cloud_ai_settings_service'`.

- [ ] **Step 3: Implement the local service facade**

Create `src/services/cloud_ai_settings_service.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol


RelayState = Literal[
    "disabled",
    "connecting",
    "online",
    "offline",
    "degraded",
    "update_required",
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecentAuthRequired(RuntimeError):
    """Raised when device management needs a fresh desktop Auth0 session."""


@dataclass(frozen=True)
class BrowserLoginStart:
    auth_url: str
    expires_at: datetime
    state_fingerprint: str


@dataclass(frozen=True)
class RecentAuthSession:
    authenticated: bool
    authenticated_at: datetime | None
    expires_at: datetime | None
    account_id: str | None
    account_email: str | None
    scopes: list[str]
    access_token: str | None = None

    def public_copy(self, now: datetime) -> "PublicAuthSession":
        seconds_remaining = 0
        if self.expires_at is not None:
            seconds_remaining = max(
                0,
                int((self.expires_at - now).total_seconds()),
            )
        return PublicAuthSession(
            authenticated=self.authenticated,
            authenticated_at=self.authenticated_at,
            expires_at=self.expires_at,
            account_id=self.account_id,
            account_email=self.account_email,
            scopes=self.scopes,
            seconds_remaining=seconds_remaining,
            needs_browser_login=not self.authenticated or seconds_remaining == 0,
            access_token=None,
        )


@dataclass(frozen=True)
class PublicAuthSession:
    authenticated: bool
    authenticated_at: datetime | None
    expires_at: datetime | None
    account_id: str | None
    account_email: str | None
    scopes: list[str]
    seconds_remaining: int
    needs_browser_login: bool
    access_token: None = None


@dataclass(frozen=True)
class DeviceKeySummary:
    installation_id: str
    device_id: str | None
    fingerprint: str
    public_key: str
    created_at: datetime
    rotated_at: datetime | None


@dataclass(frozen=True)
class RelayDeviceSummary:
    device_id: str
    installation_id: str
    display_name: str
    fingerprint: str
    status: Literal["registered", "online", "offline", "revoked"]
    is_current: bool
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    capabilities: list[str]
    shipagent_core_version: str
    registry_contract_version: str
    ups_boundary_contract_version: str


@dataclass(frozen=True)
class RelayStatusSummary:
    state: RelayState
    relay_session_id: str | None
    active_device_id: str | None
    last_heartbeat_at: datetime | None
    message: str | None


@dataclass(frozen=True)
class CloudAiStatus:
    enabled: bool
    account_id: str | None
    account_email: str | None
    current_device_id: str | None
    active_device_id: str | None
    auth: PublicAuthSession
    key: DeviceKeySummary | None
    relay: RelayStatusSummary


class DeviceAuthCoordinator(Protocol):
    async def start_browser_login(self) -> BrowserLoginStart:
        pass

    async def get_current_session(self) -> RecentAuthSession:
        pass

    async def require_recent_session(self, max_age_seconds: int = 600) -> RecentAuthSession:
        pass


class DeviceKeyService(Protocol):
    async def get_key_status(self) -> DeviceKeySummary | None:
        pass

    async def ensure_device_key(self, display_name: str | None = None) -> DeviceKeySummary:
        pass

    async def rotate_device_key(self) -> DeviceKeySummary:
        pass

    async def delete_device_key(self) -> None:
        pass


class RelayDeviceClientProtocol(Protocol):
    async def register_device(
        self,
        access_token: str,
        display_name: str,
        key: DeviceKeySummary,
    ) -> RelayDeviceSummary:
        pass

    async def list_devices(self, access_token: str | None) -> list[RelayDeviceSummary]:
        pass

    async def revoke_device(self, access_token: str, device_id: str) -> None:
        pass

    async def rotate_device_key(
        self,
        access_token: str,
        key: DeviceKeySummary,
    ) -> RelayDeviceSummary:
        pass

    async def set_active_device(self, access_token: str, device_id: str) -> RelayDeviceSummary:
        pass

    async def unlink_account(self, access_token: str) -> None:
        pass


class DesktopRelayClientProtocol(Protocol):
    async def get_status(self) -> RelayStatusSummary:
        pass

    async def ensure_connected(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass


class CloudAiSettingsService:
    """Local desktop facade for settings-visible Cloud AI device actions."""

    def __init__(
        self,
        auth: DeviceAuthCoordinator,
        keys: DeviceKeyService,
        devices: RelayDeviceClientProtocol,
        relay: DesktopRelayClientProtocol,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._auth = auth
        self._keys = keys
        self._devices = devices
        self._relay = relay
        self._now = now

    @classmethod
    def from_environment(cls) -> "CloudAiSettingsService":
        from src.services.desktop_device_auth import DesktopDeviceAuthCoordinator
        from src.services.desktop_relay_client import DesktopRelayClient
        from src.services.relay_device_client import RelayDeviceClient
        from src.services.relay_key_service import RelayKeyService

        return cls(
            auth=DesktopDeviceAuthCoordinator(),
            keys=RelayKeyService(),
            devices=RelayDeviceClient(),
            relay=DesktopRelayClient(),
        )

    async def start_browser_login(self) -> BrowserLoginStart:
        return await self._auth.start_browser_login()

    async def get_auth_session(self) -> PublicAuthSession:
        session = await self._auth.get_current_session()
        return session.public_copy(self._now())

    async def get_status(self) -> CloudAiStatus:
        session = await self._auth.get_current_session()
        auth = session.public_copy(self._now())
        key = await self._keys.get_key_status()
        relay = await self._relay.get_status()
        devices = await self._devices.list_devices(session.access_token)
        current = next((device for device in devices if device.is_current), None)
        active = next((device for device in devices if device.is_active), None)
        return CloudAiStatus(
            enabled=current is not None and current.status != "revoked",
            account_id=auth.account_id,
            account_email=auth.account_email,
            current_device_id=current.device_id if current is not None else None,
            active_device_id=active.device_id if active is not None else relay.active_device_id,
            auth=auth,
            key=key,
            relay=relay,
        )

    async def generate_device_key(self, display_name: str | None) -> DeviceKeySummary:
        return await self._keys.ensure_device_key(display_name)

    async def list_devices(self) -> list[RelayDeviceSummary]:
        session = await self._auth.get_current_session()
        return await self._devices.list_devices(session.access_token)

    async def register_current_device(self, display_name: str) -> CloudAiStatus:
        session = await self._require_recent_auth()
        key = await self._keys.ensure_device_key(display_name)
        await self._devices.register_device(
            access_token=self._require_token(session),
            display_name=display_name,
            key=key,
        )
        await self._relay.ensure_connected()
        return await self.get_status()

    async def rotate_current_device_key(self) -> CloudAiStatus:
        session = await self._require_recent_auth()
        key = await self._keys.rotate_device_key()
        await self._devices.rotate_device_key(
            access_token=self._require_token(session),
            key=key,
        )
        await self._relay.ensure_connected()
        return await self.get_status()

    async def revoke_device(self, device_id: str) -> None:
        session = await self._require_recent_auth()
        await self._devices.revoke_device(self._require_token(session), device_id)

    async def set_active_device(self, device_id: str) -> CloudAiStatus:
        session = await self._require_recent_auth()
        await self._devices.set_active_device(self._require_token(session), device_id)
        return await self.get_status()

    async def unlink_account(self, delete_local_key: bool, confirmation: str) -> CloudAiStatus:
        if delete_local_key and confirmation != "unlink":
            raise ValueError("unlink_confirmation_required")
        session = await self._require_recent_auth()
        await self._devices.unlink_account(self._require_token(session))
        await self._relay.disconnect()
        if delete_local_key:
            await self._keys.delete_device_key()
        return await self.get_status()

    async def _require_recent_auth(self) -> RecentAuthSession:
        return await self._auth.require_recent_session(max_age_seconds=600)

    @staticmethod
    def _require_token(session: RecentAuthSession) -> str:
        if not session.access_token:
            raise RecentAuthRequired()
        return session.access_token
```

- [ ] **Step 4: Run the service tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_cloud_ai_settings_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/cloud_ai_settings_service.py tests/services/test_cloud_ai_settings_service.py
git commit -m "feat: add local cloud ai settings service"
```

## Task 2: Local Cloud AI API Routes

**Files:**

- Create: `src/api/routes/cloud_ai.py`
- Modify: `src/api/main.py`
- Test: `tests/api/test_cloud_ai.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/api/test_cloud_ai.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import cloud_ai
from src.services.cloud_ai_settings_service import (
    BrowserLoginStart,
    CloudAiStatus,
    DeviceKeySummary,
    PublicAuthSession,
    RecentAuthRequired,
    RelayDeviceSummary,
    RelayStatusSummary,
)


NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class FakeCloudAiService:
    async def start_browser_login(self) -> BrowserLoginStart:
        return BrowserLoginStart(
            auth_url="https://auth.example.test/authorize",
            expires_at=NOW + timedelta(minutes=5),
            state_fingerprint="state-fp",
        )

    async def get_auth_session(self) -> PublicAuthSession:
        return PublicAuthSession(
            authenticated=True,
            authenticated_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
            account_id="account-1",
            account_email="ops@example.test",
            scopes=["shipagent.device"],
            seconds_remaining=600,
            needs_browser_login=False,
        )

    async def get_status(self) -> CloudAiStatus:
        return CloudAiStatus(
            enabled=True,
            account_id="account-1",
            account_email="ops@example.test",
            current_device_id="device-1",
            active_device_id="device-1",
            auth=await self.get_auth_session(),
            key=DeviceKeySummary(
                installation_id="install-1",
                device_id="device-1",
                fingerprint="fp-123",
                public_key="public-key",
                created_at=NOW,
                rotated_at=None,
            ),
            relay=RelayStatusSummary(
                state="online",
                relay_session_id="session-1",
                active_device_id="device-1",
                last_heartbeat_at=NOW,
                message=None,
            ),
        )

    async def generate_device_key(self, display_name: str | None) -> DeviceKeySummary:
        return DeviceKeySummary(
            installation_id="install-1",
            device_id=None,
            fingerprint="fp-generated",
            public_key="public-key",
            created_at=NOW,
            rotated_at=None,
        )

    async def list_devices(self) -> list[RelayDeviceSummary]:
        return [
            RelayDeviceSummary(
                device_id="device-1",
                installation_id="install-1",
                display_name="Work Mac",
                fingerprint="fp-123",
                status="online",
                is_current=True,
                is_active=True,
                last_seen_at=NOW,
                created_at=NOW - timedelta(days=1),
                capabilities=["relay.invoke.v1"],
                shipagent_core_version="0.1.0",
                registry_contract_version="2026-06-10",
                ups_boundary_contract_version="2026-06-10",
            )
        ]

    async def register_current_device(self, display_name: str) -> CloudAiStatus:
        return await self.get_status()

    async def rotate_current_device_key(self) -> CloudAiStatus:
        return await self.get_status()

    async def revoke_device(self, device_id: str) -> None:
        return None

    async def set_active_device(self, device_id: str) -> CloudAiStatus:
        return await self.get_status()

    async def unlink_account(self, delete_local_key: bool, confirmation: str) -> CloudAiStatus:
        return await self.get_status()


class RecentAuthFailingService(FakeCloudAiService):
    async def rotate_current_device_key(self) -> CloudAiStatus:
        raise RecentAuthRequired()


class ConfirmationFailingService(FakeCloudAiService):
    async def unlink_account(self, delete_local_key: bool, confirmation: str) -> CloudAiStatus:
        raise ValueError("unlink_confirmation_required")


def override_service(fake: object) -> None:
    app.dependency_overrides[cloud_ai.get_cloud_ai_service] = lambda: fake


def clear_overrides() -> None:
    app.dependency_overrides.pop(cloud_ai.get_cloud_ai_service, None)


def test_get_cloud_ai_status_hides_access_token(client: TestClient) -> None:
    override_service(FakeCloudAiService())
    try:
        response = client.get("/api/v1/cloud-ai/status")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["auth"]["account_email"] == "ops@example.test"
    assert "secret-token" not in response.text
    assert payload["relay"]["state"] == "online"


def test_start_browser_login_returns_auth_url(client: TestClient) -> None:
    override_service(FakeCloudAiService())
    try:
        response = client.post("/api/v1/cloud-ai/auth/start")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["auth_url"] == "https://auth.example.test/authorize"
    assert response.json()["state_fingerprint"] == "state-fp"


def test_device_list_returns_current_and_active_flags(client: TestClient) -> None:
    override_service(FakeCloudAiService())
    try:
        response = client.get("/api/v1/cloud-ai/devices")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["devices"][0]["is_current"] is True
    assert response.json()["devices"][0]["is_active"] is True


def test_recent_auth_failure_uses_stable_error_code(client: TestClient) -> None:
    override_service(RecentAuthFailingService())
    try:
        response = client.post("/api/v1/cloud-ai/devices/current/rotate-key")
    finally:
        clear_overrides()

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "recent_auth_required"


def test_unlink_confirmation_failure_uses_stable_error_code(client: TestClient) -> None:
    override_service(ConfirmationFailingService())
    try:
        response = client.post(
            "/api/v1/cloud-ai/unlink",
            json={"delete_local_key": True, "confirmation": "delete"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unlink_confirmation_required"
```

- [ ] **Step 2: Run the route tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_cloud_ai.py -v
```

Expected: FAIL with `ImportError: cannot import name 'cloud_ai' from 'src.api.routes'`.

- [ ] **Step 3: Add the Cloud AI router**

Create `src/api/routes/cloud_ai.py`:

```python
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.services.cloud_ai_settings_service import (
    CloudAiSettingsService,
    RecentAuthRequired,
)


router = APIRouter(prefix="/cloud-ai", tags=["cloud-ai"])


class AuthSessionResponse(BaseModel):
    authenticated: bool
    authenticated_at: datetime | None
    expires_at: datetime | None
    account_id: str | None
    account_email: str | None
    scopes: list[str]
    seconds_remaining: int
    needs_browser_login: bool


class BrowserLoginStartResponse(BaseModel):
    auth_url: str
    expires_at: datetime
    state_fingerprint: str


class DeviceKeyRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)


class DeviceKeyResponse(BaseModel):
    installation_id: str
    device_id: str | None
    fingerprint: str
    public_key: str
    created_at: datetime
    rotated_at: datetime | None


class RelayDeviceResponse(BaseModel):
    device_id: str
    installation_id: str
    display_name: str
    fingerprint: str
    status: str
    is_current: bool
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    capabilities: list[str]
    shipagent_core_version: str
    registry_contract_version: str
    ups_boundary_contract_version: str


class RelayStatusResponse(BaseModel):
    state: str
    relay_session_id: str | None
    active_device_id: str | None
    last_heartbeat_at: datetime | None
    message: str | None


class CloudAiStatusResponse(BaseModel):
    enabled: bool
    account_id: str | None
    account_email: str | None
    current_device_id: str | None
    active_device_id: str | None
    auth: AuthSessionResponse
    key: DeviceKeyResponse | None
    relay: RelayStatusResponse


class DeviceListResponse(BaseModel):
    devices: list[RelayDeviceResponse]


class DeviceActionResponse(BaseModel):
    status: str
    device_id: str


class UnlinkRequest(BaseModel):
    delete_local_key: bool
    confirmation: str


def get_cloud_ai_service() -> CloudAiSettingsService:
    return CloudAiSettingsService.from_environment()


def _recent_auth_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": "recent_auth_required",
            "message": "Sign in again to manage Cloud AI devices.",
        },
    )


@router.get("/status", response_model=CloudAiStatusResponse)
async def get_status(
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> CloudAiStatusResponse:
    return CloudAiStatusResponse.model_validate(
        await service.get_status(),
        from_attributes=True,
    )


@router.post("/auth/start", response_model=BrowserLoginStartResponse)
async def start_browser_login(
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> BrowserLoginStartResponse:
    return BrowserLoginStartResponse.model_validate(
        await service.start_browser_login(),
        from_attributes=True,
    )


@router.get("/auth/session", response_model=AuthSessionResponse)
async def get_auth_session(
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> AuthSessionResponse:
    return AuthSessionResponse.model_validate(
        await service.get_auth_session(),
        from_attributes=True,
    )


@router.post("/device-key", response_model=DeviceKeyResponse)
async def generate_device_key(
    payload: DeviceKeyRequest,
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> DeviceKeyResponse:
    return DeviceKeyResponse.model_validate(
        await service.generate_device_key(payload.display_name),
        from_attributes=True,
    )


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> DeviceListResponse:
    devices = await service.list_devices()
    return DeviceListResponse(
        devices=[
            RelayDeviceResponse.model_validate(device, from_attributes=True)
            for device in devices
        ],
    )


@router.post("/devices/register", response_model=CloudAiStatusResponse)
async def register_device(
    payload: DeviceKeyRequest,
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> CloudAiStatusResponse:
    try:
        status = await service.register_current_device(payload.display_name or "ShipAgent Desktop")
    except RecentAuthRequired as exc:
        raise _recent_auth_error() from exc
    return CloudAiStatusResponse.model_validate(status, from_attributes=True)


@router.post("/devices/current/rotate-key", response_model=CloudAiStatusResponse)
async def rotate_current_device_key(
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> CloudAiStatusResponse:
    try:
        status = await service.rotate_current_device_key()
    except RecentAuthRequired as exc:
        raise _recent_auth_error() from exc
    return CloudAiStatusResponse.model_validate(status, from_attributes=True)


@router.post("/devices/{device_id}/revoke", response_model=DeviceActionResponse)
async def revoke_device(
    device_id: str,
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> DeviceActionResponse:
    try:
        await service.revoke_device(device_id)
    except RecentAuthRequired as exc:
        raise _recent_auth_error() from exc
    return DeviceActionResponse(status="revoked", device_id=device_id)


@router.post("/devices/{device_id}/set-active", response_model=CloudAiStatusResponse)
async def set_active_device(
    device_id: str,
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> CloudAiStatusResponse:
    try:
        status = await service.set_active_device(device_id)
    except RecentAuthRequired as exc:
        raise _recent_auth_error() from exc
    return CloudAiStatusResponse.model_validate(status, from_attributes=True)


@router.post("/unlink", response_model=CloudAiStatusResponse)
async def unlink_account(
    payload: UnlinkRequest,
    service: CloudAiSettingsService = Depends(get_cloud_ai_service),
) -> CloudAiStatusResponse:
    try:
        status = await service.unlink_account(
            delete_local_key=payload.delete_local_key,
            confirmation=payload.confirmation,
        )
    except RecentAuthRequired as exc:
        raise _recent_auth_error() from exc
    except ValueError as exc:
        if str(exc) == "unlink_confirmation_required":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unlink_confirmation_required",
                    "message": "Type unlink before deleting the local device key.",
                },
            ) from exc
        raise
    return CloudAiStatusResponse.model_validate(status, from_attributes=True)
```

Modify `src/api/main.py` imports:

```python
from src.api.routes import (  # noqa: E402
    agent_audit,
    cloud_ai,
    commands,
    connections,
    contacts,
    conversations,
    data_sources,
    jobs,
    labels,
    logs,
    platforms,
    preview,
    progress,
    saved_data_sources,
    settings,
)
```

Modify `src/api/main.py` router inclusion near the other settings routes:

```python
app.include_router(commands.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(cloud_ai.router, prefix="/api/v1")
```

- [ ] **Step 4: Run the route tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_cloud_ai.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/main.py src/api/routes/cloud_ai.py tests/api/test_cloud_ai.py
git commit -m "feat: expose local cloud ai settings api"
```

## Task 3: Shared Frontend Types, Fixtures, API Methods

**Files:**

- Create: `shipagent-frontend/libs/shared/types/src/cloud-ai.types.ts`
- Create: `shipagent-frontend/libs/testing/src/fixtures/cloud-ai.fixtures.ts`
- Modify: `shipagent-frontend/libs/shared/types/src/index.ts`
- Modify: `shipagent-frontend/libs/shared/api/src/api.service.ts`
- Modify: `shipagent-frontend/libs/testing/src/index.ts`
- Modify: `shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts`

- [ ] **Step 1: Write the type and fixture files**

Create `shipagent-frontend/libs/shared/types/src/cloud-ai.types.ts`:

```typescript
export type CloudAiRelayState =
  | 'disabled'
  | 'connecting'
  | 'online'
  | 'offline'
  | 'degraded'
  | 'update_required';

export type CloudAiDeviceStatus =
  | 'registered'
  | 'online'
  | 'offline'
  | 'revoked';

export interface CloudAiAuthSession {
  authenticated: boolean;
  authenticated_at: string | null;
  expires_at: string | null;
  account_id: string | null;
  account_email: string | null;
  scopes: string[];
  seconds_remaining: number;
  needs_browser_login: boolean;
}

export interface CloudAiBrowserLoginStartResponse {
  auth_url: string;
  expires_at: string;
  state_fingerprint: string;
}

export interface CloudAiDeviceKeyResponse {
  installation_id: string;
  device_id: string | null;
  fingerprint: string;
  public_key: string;
  created_at: string;
  rotated_at: string | null;
}

export interface CloudAiRelayStatus {
  state: CloudAiRelayState;
  relay_session_id: string | null;
  active_device_id: string | null;
  last_heartbeat_at: string | null;
  message: string | null;
}

export interface CloudAiDevice {
  device_id: string;
  installation_id: string;
  display_name: string;
  fingerprint: string;
  status: CloudAiDeviceStatus;
  is_current: boolean;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string;
  capabilities: string[];
  shipagent_core_version: string;
  registry_contract_version: string;
  ups_boundary_contract_version: string;
}

export interface CloudAiStatusResponse {
  enabled: boolean;
  account_id: string | null;
  account_email: string | null;
  current_device_id: string | null;
  active_device_id: string | null;
  auth: CloudAiAuthSession;
  key: CloudAiDeviceKeyResponse | null;
  relay: CloudAiRelayStatus;
}

export interface CloudAiDeviceListResponse {
  devices: CloudAiDevice[];
}

export interface CloudAiDeviceActionResponse {
  status: string;
  device_id: string;
}

export interface CloudAiUnlinkRequest {
  delete_local_key: boolean;
  confirmation: 'unlink' | string;
}
```

Create `shipagent-frontend/libs/testing/src/fixtures/cloud-ai.fixtures.ts`:

```typescript
import type {
  CloudAiAuthSession,
  CloudAiDevice,
  CloudAiDeviceKeyResponse,
  CloudAiRelayStatus,
  CloudAiStatusResponse,
} from '@shipagent/shared-types';

const now = '2026-06-30T12:00:00Z';

export const cloudAiFixtures = {
  authSession: (): CloudAiAuthSession => ({
    authenticated: true,
    authenticated_at: now,
    expires_at: '2026-06-30T12:10:00Z',
    account_id: 'account-1',
    account_email: 'ops@example.test',
    scopes: ['shipagent.device'],
    seconds_remaining: 600,
    needs_browser_login: false,
  }),

  unauthenticatedSession: (): CloudAiAuthSession => ({
    authenticated: false,
    authenticated_at: null,
    expires_at: null,
    account_id: null,
    account_email: null,
    scopes: [],
    seconds_remaining: 0,
    needs_browser_login: true,
  }),

  key: (): CloudAiDeviceKeyResponse => ({
    installation_id: 'install-1',
    device_id: 'device-1',
    fingerprint: 'fp-123',
    public_key: 'public-key',
    created_at: now,
    rotated_at: null,
  }),

  relayOnline: (): CloudAiRelayStatus => ({
    state: 'online',
    relay_session_id: 'session-1',
    active_device_id: 'device-1',
    last_heartbeat_at: now,
    message: null,
  }),

  relayOffline: (): CloudAiRelayStatus => ({
    state: 'offline',
    relay_session_id: null,
    active_device_id: null,
    last_heartbeat_at: null,
    message: 'Relay is not connected',
  }),

  currentDevice: (): CloudAiDevice => ({
    device_id: 'device-1',
    installation_id: 'install-1',
    display_name: 'Work Mac',
    fingerprint: 'fp-123',
    status: 'online',
    is_current: true,
    is_active: true,
    last_seen_at: now,
    created_at: '2026-06-29T12:00:00Z',
    capabilities: ['relay.invoke.v1'],
    shipagent_core_version: '0.1.0',
    registry_contract_version: '2026-06-10',
    ups_boundary_contract_version: '2026-06-10',
  }),

  enabledStatus: (): CloudAiStatusResponse => ({
    enabled: true,
    account_id: 'account-1',
    account_email: 'ops@example.test',
    current_device_id: 'device-1',
    active_device_id: 'device-1',
    auth: cloudAiFixtures.authSession(),
    key: cloudAiFixtures.key(),
    relay: cloudAiFixtures.relayOnline(),
  }),

  disabledStatus: (): CloudAiStatusResponse => ({
    enabled: false,
    account_id: null,
    account_email: null,
    current_device_id: null,
    active_device_id: null,
    auth: cloudAiFixtures.unauthenticatedSession(),
    key: null,
    relay: cloudAiFixtures.relayOffline(),
  }),
};
```

- [ ] **Step 2: Wire the type and fixture barrels**

Modify `shipagent-frontend/libs/shared/types/src/index.ts`:

```typescript
export * from './api.types';
export * from './job.types';
export * from './conversation.types';
export * from './settings.types';
export * from './platform.types';
export * from './contact.types';
export * from './command.types';
export * from './data-source.types';
export * from './domain-cards.types';
export * from './connection.types';
export * from './cloud-ai.types';
```

Modify `shipagent-frontend/libs/testing/src/index.ts` fixture exports:

```typescript
export { jobFixtures } from './fixtures/job.fixtures';
export { conversationFixtures } from './fixtures/conversation.fixtures';
export { settingsFixtures } from './fixtures/settings.fixtures';
export { platformFixtures } from './fixtures/platform.fixtures';
export { cloudAiFixtures } from './fixtures/cloud-ai.fixtures';
```

- [ ] **Step 3: Add ApiService imports and methods**

Modify the type imports in `shipagent-frontend/libs/shared/api/src/api.service.ts`:

```typescript
  // Cloud AI
  CloudAiAuthSession,
  CloudAiBrowserLoginStartResponse,
  CloudAiDeviceActionResponse,
  CloudAiDeviceKeyResponse,
  CloudAiDeviceListResponse,
  CloudAiStatusResponse,
  CloudAiUnlinkRequest,
```

Add these methods after `completeOnboarding()`:

```typescript
  // ===========================================================================
  // CLOUD AI DESKTOP DEVICE MANAGEMENT
  // ===========================================================================

  getCloudAiStatus(): Observable<CloudAiStatusResponse> {
    return this.http.get<CloudAiStatusResponse>(`${this.baseUrl}/cloud-ai/status`);
  }

  startCloudAiBrowserLogin(): Observable<CloudAiBrowserLoginStartResponse> {
    return this.http.post<CloudAiBrowserLoginStartResponse>(
      `${this.baseUrl}/cloud-ai/auth/start`,
      {},
    );
  }

  getCloudAiAuthSession(): Observable<CloudAiAuthSession> {
    return this.http.get<CloudAiAuthSession>(`${this.baseUrl}/cloud-ai/auth/session`);
  }

  generateCloudAiDeviceKey(displayName: string): Observable<CloudAiDeviceKeyResponse> {
    return this.http.post<CloudAiDeviceKeyResponse>(
      `${this.baseUrl}/cloud-ai/device-key`,
      { display_name: displayName },
    );
  }

  listCloudAiDevices(): Observable<CloudAiDeviceListResponse> {
    return this.http.get<CloudAiDeviceListResponse>(`${this.baseUrl}/cloud-ai/devices`);
  }

  registerCloudAiDevice(displayName: string): Observable<CloudAiStatusResponse> {
    return this.http.post<CloudAiStatusResponse>(
      `${this.baseUrl}/cloud-ai/devices/register`,
      { display_name: displayName },
    );
  }

  rotateCloudAiDeviceKey(): Observable<CloudAiStatusResponse> {
    return this.http.post<CloudAiStatusResponse>(
      `${this.baseUrl}/cloud-ai/devices/current/rotate-key`,
      {},
    );
  }

  revokeCloudAiDevice(deviceId: string): Observable<CloudAiDeviceActionResponse> {
    return this.http.post<CloudAiDeviceActionResponse>(
      `${this.baseUrl}/cloud-ai/devices/${encodeURIComponent(deviceId)}/revoke`,
      {},
    );
  }

  setActiveCloudAiDevice(deviceId: string): Observable<CloudAiStatusResponse> {
    return this.http.post<CloudAiStatusResponse>(
      `${this.baseUrl}/cloud-ai/devices/${encodeURIComponent(deviceId)}/set-active`,
      {},
    );
  }

  unlinkCloudAiAccount(payload: CloudAiUnlinkRequest): Observable<CloudAiStatusResponse> {
    return this.http.post<CloudAiStatusResponse>(
      `${this.baseUrl}/cloud-ai/unlink`,
      payload,
    );
  }
```

- [ ] **Step 4: Extend ApiService test mock**

Modify `API_SERVICE_METHODS` in `shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts` by inserting these names after `completeOnboarding`:

```typescript
  // Cloud AI
  'getCloudAiStatus',
  'startCloudAiBrowserLogin',
  'getCloudAiAuthSession',
  'generateCloudAiDeviceKey',
  'listCloudAiDevices',
  'registerCloudAiDevice',
  'rotateCloudAiDeviceKey',
  'revokeCloudAiDevice',
  'setActiveCloudAiDevice',
  'unlinkCloudAiAccount',
```

- [ ] **Step 5: Run frontend typecheck for changed shared contracts**

Run:

```bash
cd shipagent-frontend
npx nx typecheck settings-remote
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add shipagent-frontend/libs/shared/types/src/cloud-ai.types.ts shipagent-frontend/libs/shared/types/src/index.ts shipagent-frontend/libs/shared/api/src/api.service.ts shipagent-frontend/libs/testing/src/fixtures/cloud-ai.fixtures.ts shipagent-frontend/libs/testing/src/index.ts shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts
git commit -m "feat: add cloud ai frontend contracts"
```

## Task 4: Shared Cloud AI SignalStore

**Files:**

- Create: `shipagent-frontend/libs/shared/state/src/cloud-ai.store.ts`
- Create: `shipagent-frontend/libs/shared/state/src/cloud-ai.store.spec.ts`
- Modify: `shipagent-frontend/libs/shared/state/src/index.ts`

- [ ] **Step 1: Write failing store spec**

Create `shipagent-frontend/libs/shared/state/src/cloud-ai.store.spec.ts`:

```typescript
import { TestBed } from '@angular/core/testing';
import { CloudAiStore } from './cloud-ai.store';
import { cloudAiFixtures } from '@shipagent/testing';

describe('CloudAiStore', () => {
  let store: InstanceType<typeof CloudAiStore>;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(CloudAiStore);
  });

  it('starts with unloaded state', () => {
    expect(store.status()).toBeNull();
    expect(store.devices()).toEqual([]);
    expect(store.loading()).toBe(false);
    expect(store.actionInFlight()).toBeNull();
    expect(store.error()).toBeNull();
  });

  it('stores status and exposes enabled relay state', () => {
    store.setStatus(cloudAiFixtures.enabledStatus());

    expect(store.status()?.enabled).toBe(true);
    expect(store.relayState()).toBe('online');
    expect(store.currentDeviceId()).toBe('device-1');
  });

  it('stores devices without mutating input arrays', () => {
    const devices = [cloudAiFixtures.currentDevice()];
    store.setDevices(devices);
    devices.length = 0;

    expect(store.devices().length).toBe(1);
  });

  it('tracks action progress and clears errors on action start', () => {
    store.setError('first error');
    store.setActionInFlight('rotate');

    expect(store.actionInFlight()).toBe('rotate');
    expect(store.error()).toBeNull();
  });

  it('reset returns to initial state', () => {
    store.setStatus(cloudAiFixtures.enabledStatus());
    store.setDevices([cloudAiFixtures.currentDevice()]);
    store.setLoading(true);
    store.setActionInFlight('unlink');

    store.resetCloudAiState();

    expect(store.status()).toBeNull();
    expect(store.devices()).toEqual([]);
    expect(store.loading()).toBe(false);
    expect(store.actionInFlight()).toBeNull();
  });
});
```

- [ ] **Step 2: Run the store spec and verify it fails**

Run:

```bash
cd shipagent-frontend
npx nx test shared-state --watch=false
```

Expected: FAIL with `Cannot find module './cloud-ai.store'`.

- [ ] **Step 3: Implement the store**

Create `shipagent-frontend/libs/shared/state/src/cloud-ai.store.ts`:

```typescript
import { computed } from '@angular/core';
import { patchState, signalStore, withComputed, withMethods, withState } from '@ngrx/signals';
import type { CloudAiDevice, CloudAiRelayState, CloudAiStatusResponse } from '@shipagent/shared-types';

export type CloudAiAction =
  | 'login'
  | 'generate-key'
  | 'register'
  | 'rotate'
  | 'revoke'
  | 'set-active'
  | 'unlink';

export interface CloudAiState {
  status: CloudAiStatusResponse | null;
  devices: CloudAiDevice[];
  loading: boolean;
  actionInFlight: CloudAiAction | null;
  error: string | null;
}

const initialState: CloudAiState = {
  status: null,
  devices: [],
  loading: false,
  actionInFlight: null,
  error: null,
};

export const CloudAiStore = signalStore(
  { providedIn: 'root' },
  withState<CloudAiState>(initialState),
  withComputed((store) => ({
    relayState: computed<CloudAiRelayState>(() => store.status()?.relay.state ?? 'disabled'),
    currentDeviceId: computed(() => store.status()?.current_device_id ?? null),
    activeDeviceId: computed(() => store.status()?.active_device_id ?? null),
    recentAuthReady: computed(() => {
      const auth = store.status()?.auth;
      return Boolean(auth?.authenticated && auth.seconds_remaining > 0 && !auth.needs_browser_login);
    }),
  })),
  withMethods((store) => ({
    setStatus(status: CloudAiStatusResponse | null): void {
      patchState(store, { status, error: null });
    },

    setDevices(devices: CloudAiDevice[]): void {
      patchState(store, { devices: [...devices], error: null });
    },

    setLoading(loading: boolean): void {
      patchState(store, { loading });
    },

    setActionInFlight(actionInFlight: CloudAiAction | null): void {
      patchState(store, { actionInFlight, error: null });
    },

    setError(error: string | null): void {
      patchState(store, { error });
    },

    resetCloudAiState(): void {
      patchState(store, initialState);
    },
  })),
);
```

Modify `shipagent-frontend/libs/shared/state/src/index.ts`:

```typescript
export { CloudAiStore } from './cloud-ai.store';
export type { CloudAiAction, CloudAiState } from './cloud-ai.store';
```

- [ ] **Step 4: Run the store tests and verify they pass**

Run:

```bash
cd shipagent-frontend
npx nx test shared-state --watch=false
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shipagent-frontend/libs/shared/state/src/cloud-ai.store.ts shipagent-frontend/libs/shared/state/src/cloud-ai.store.spec.ts shipagent-frontend/libs/shared/state/src/index.ts
git commit -m "feat: add cloud ai shared state"
```

## Task 5: Tauri Keychain Entitlement Status

**Files:**

- Create: `shipagent-frontend/libs/shared/tauri/src/keychain-entitlement.ts`
- Modify: `shipagent-frontend/libs/shared/tauri/src/index.ts`
- Modify: `src-tauri/src/main.rs`
- Modify: `src-tauri/entitlements.plist`

- [ ] **Step 1: Add the frontend Tauri helper**

Create `shipagent-frontend/libs/shared/tauri/src/keychain-entitlement.ts`:

```typescript
const TAURI_CORE = '@tauri-apps/api/core';

export interface KeychainEntitlementStatus {
  platform: 'macos' | 'windows' | 'linux' | 'unknown';
  app_identifier: string;
  entitlements_file_present: boolean;
  keychain_access_configured: boolean;
  keychain_access_groups: string[];
  can_use_keychain: boolean;
  reason: string | null;
}

export async function getKeychainEntitlementStatus(): Promise<KeychainEntitlementStatus> {
  if (typeof window === 'undefined' || !window.__TAURI__) {
    return {
      platform: 'unknown',
      app_identifier: 'browser-dev',
      entitlements_file_present: false,
      keychain_access_configured: false,
      keychain_access_groups: [],
      can_use_keychain: false,
      reason: 'Not running inside Tauri',
    };
  }

  const tauriCore = await import(/* @vite-ignore */ TAURI_CORE) as {
    invoke: (cmd: string) => Promise<KeychainEntitlementStatus>;
  };
  return tauriCore.invoke('keychain_entitlement_status');
}
```

Modify `shipagent-frontend/libs/shared/tauri/src/index.ts`:

```typescript
/**
 * @shipagent/shared-tauri
 *
 * Tauri desktop integration utilities.
 * Provides sidecar port resolution, environment detection, and desktop
 * diagnostics used by the shell and settings remote.
 */

export { TauriDetectionService } from './tauri-detection.service';
export { resolveSidecarPort, computeApiBaseUrl } from './port-resolver';
export {
  getKeychainEntitlementStatus,
  type KeychainEntitlementStatus,
} from './keychain-entitlement';
```

- [ ] **Step 2: Add Rust unit tests for entitlement status**

Append this test module to `src-tauri/src/main.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keychain_status_reports_configured_group_when_entitlement_is_present() {
        let status = build_keychain_entitlement_status(
            "macos",
            "com.shipagent.app",
            r#"
            <plist version="1.0">
            <dict>
                <key>keychain-access-groups</key>
                <array>
                    <string>$(AppIdentifierPrefix)com.shipagent.app</string>
                </array>
            </dict>
            </plist>
            "#,
        );

        assert!(status.entitlements_file_present);
        assert!(status.keychain_access_configured);
        assert!(status.can_use_keychain);
        assert_eq!(
            status.keychain_access_groups,
            vec!["$(AppIdentifierPrefix)com.shipagent.app".to_string()]
        );
    }

    #[test]
    fn keychain_status_reports_missing_group() {
        let status = build_keychain_entitlement_status(
            "macos",
            "com.shipagent.app",
            "<plist><dict></dict></plist>",
        );

        assert!(status.entitlements_file_present);
        assert!(!status.keychain_access_configured);
        assert!(!status.can_use_keychain);
        assert_eq!(
            status.reason,
            Some("keychain-access-groups entitlement is missing".to_string())
        );
    }
}
```

- [ ] **Step 3: Run Rust tests and verify they fail**

Run:

```bash
cd src-tauri
cargo test keychain_status
```

Expected: FAIL with `cannot find function build_keychain_entitlement_status`.

- [ ] **Step 4: Implement the Tauri command and helper**

Add these imports near the top of `src-tauri/src/main.rs`:

```rust
use serde::Serialize;
```

Add these types and functions above `start_sidecar`:

```rust
#[derive(Debug, Clone, Serialize)]
struct KeychainEntitlementStatus {
    platform: String,
    app_identifier: String,
    entitlements_file_present: bool,
    keychain_access_configured: bool,
    keychain_access_groups: Vec<String>,
    can_use_keychain: bool,
    reason: Option<String>,
}

fn extract_keychain_groups(entitlements: &str) -> Vec<String> {
    if !entitlements.contains("<key>keychain-access-groups</key>") {
        return Vec::new();
    }

    let Some(after_key) = entitlements.split("<key>keychain-access-groups</key>").nth(1) else {
        return Vec::new();
    };
    let Some(array_block) = after_key.split("</array>").next() else {
        return Vec::new();
    };

    array_block
        .split("<string>")
        .skip(1)
        .filter_map(|part| part.split("</string>").next())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn build_keychain_entitlement_status(
    platform: &str,
    app_identifier: &str,
    entitlements: &str,
) -> KeychainEntitlementStatus {
    let groups = extract_keychain_groups(entitlements);
    let configured = !groups.is_empty();
    let can_use = platform != "macos" || configured;
    let reason = if platform == "macos" && !configured {
        Some("keychain-access-groups entitlement is missing".to_string())
    } else {
        None
    };

    KeychainEntitlementStatus {
        platform: platform.to_string(),
        app_identifier: app_identifier.to_string(),
        entitlements_file_present: !entitlements.trim().is_empty(),
        keychain_access_configured: configured,
        keychain_access_groups: groups,
        can_use_keychain: can_use,
        reason,
    }
}

#[tauri::command]
async fn keychain_entitlement_status() -> Result<KeychainEntitlementStatus, String> {
    let platform = if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "linux") {
        "linux"
    } else {
        "unknown"
    };
    let entitlements = include_str!("../entitlements.plist");
    Ok(build_keychain_entitlement_status(
        platform,
        "com.shipagent.app",
        entitlements,
    ))
}
```

Modify the invoke handler:

```rust
.invoke_handler(tauri::generate_handler![
    start_sidecar,
    keychain_entitlement_status
])
```

Leave `src-tauri/capabilities/default.json` unchanged. The keychain entitlement command is a local custom app command, not a shell or updater plugin command, and this slice must not broaden shell permissions.

Modify `src-tauri/entitlements.plist` by adding this key inside `<dict>`:

```xml
    <key>keychain-access-groups</key>
    <array>
        <string>$(AppIdentifierPrefix)com.shipagent.app</string>
    </array>
```

- [ ] **Step 5: Run Tauri validation**

Run:

```bash
cd src-tauri
cargo test keychain_status
cargo check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src-tauri/src/main.rs src-tauri/entitlements.plist shipagent-frontend/libs/shared/tauri/src/keychain-entitlement.ts shipagent-frontend/libs/shared/tauri/src/index.ts
git commit -m "feat: report tauri keychain entitlement status"
```

## Task 6: Settings-Remote Cloud AI Support Services

**Files:**

- Create: `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-browser-auth.service.ts`
- Create: `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-keychain.service.ts`

- [ ] **Step 1: Create browser auth launcher service**

Create `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-browser-auth.service.ts`:

```typescript
import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class CloudAiBrowserAuthService {
  open(authUrl: string): void {
    const opened = window.open(authUrl, '_blank', 'noopener,noreferrer');
    if (opened === null) {
      window.location.assign(authUrl);
    }
  }
}
```

- [ ] **Step 2: Create keychain service wrapper**

Create `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-keychain.service.ts`:

```typescript
import { Injectable } from '@angular/core';
import {
  getKeychainEntitlementStatus,
  type KeychainEntitlementStatus,
} from '@shipagent/shared-tauri';

@Injectable({ providedIn: 'root' })
export class CloudAiKeychainService {
  getStatus(): Promise<KeychainEntitlementStatus> {
    return getKeychainEntitlementStatus();
  }
}
```

- [ ] **Step 3: Run settings typecheck**

Run:

```bash
cd shipagent-frontend
npx nx typecheck settings-remote
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-browser-auth.service.ts shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-keychain.service.ts
git commit -m "feat: add cloud ai settings support services"
```

## Task 7: Cloud AI Settings Section Component

**Files:**

- Create: `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.ts`
- Test: `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.spec.ts`

- [ ] **Step 1: Write failing component spec**

Create `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.spec.ts`:

```typescript
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { CloudAiStore } from '@shipagent/shared-state';
import { cloudAiFixtures, createMockApiService, type MockApiService } from '@shipagent/testing';
import { CloudAiBrowserAuthService } from './cloud-ai-browser-auth.service';
import { CloudAiKeychainService } from './cloud-ai-keychain.service';
import { CloudAiSectionComponent } from './cloud-ai-section.component';
import type { KeychainEntitlementStatus } from '@shipagent/shared-tauri';

class FakeBrowserAuth {
  openedUrl: string | null = null;

  open(authUrl: string): void {
    this.openedUrl = authUrl;
  }
}

class FakeKeychainService {
  status: KeychainEntitlementStatus = {
    platform: 'macos',
    app_identifier: 'com.shipagent.app',
    entitlements_file_present: true,
    keychain_access_configured: true,
    keychain_access_groups: ['$(AppIdentifierPrefix)com.shipagent.app'],
    can_use_keychain: true,
    reason: null,
  };

  getStatus(): Promise<KeychainEntitlementStatus> {
    return Promise.resolve(this.status);
  }
}

describe('CloudAiSectionComponent', () => {
  let fixture: ComponentFixture<CloudAiSectionComponent>;
  let api: MockApiService;
  let browserAuth: FakeBrowserAuth;
  let keychain: FakeKeychainService;

  beforeEach(async () => {
    api = createMockApiService();
    api.getCloudAiStatus.and.returnValue(of(cloudAiFixtures.enabledStatus()));
    api.listCloudAiDevices.and.returnValue(of({ devices: [cloudAiFixtures.currentDevice()] }));
    api.startCloudAiBrowserLogin.and.returnValue(of({
      auth_url: 'https://auth.example.test/authorize',
      expires_at: '2026-06-30T12:05:00Z',
      state_fingerprint: 'state-fp',
    }));
    api.generateCloudAiDeviceKey.and.returnValue(of(cloudAiFixtures.key()));
    api.registerCloudAiDevice.and.returnValue(of(cloudAiFixtures.enabledStatus()));
    api.rotateCloudAiDeviceKey.and.returnValue(of(cloudAiFixtures.enabledStatus()));
    api.revokeCloudAiDevice.and.returnValue(of({ status: 'revoked', device_id: 'device-1' }));
    api.setActiveCloudAiDevice.and.returnValue(of(cloudAiFixtures.enabledStatus()));
    api.unlinkCloudAiAccount.and.returnValue(of(cloudAiFixtures.disabledStatus()));
    browserAuth = new FakeBrowserAuth();
    keychain = new FakeKeychainService();

    await TestBed.configureTestingModule({
      imports: [CloudAiSectionComponent],
      providers: [
        CloudAiStore,
        { provide: ApiService, useValue: api },
        { provide: CloudAiBrowserAuthService, useValue: browserAuth },
        { provide: CloudAiKeychainService, useValue: keychain },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CloudAiSectionComponent);
    fixture.componentRef.setInput('isOpen', true);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('renders enabled status and relay state', () => {
    const text = fixture.nativeElement.textContent as string;

    expect(text).toContain('Cloud AI');
    expect(text).toContain('ops@example.test');
    expect(text).toContain('Relay online');
    expect(text).toContain('Work Mac');
  });

  it('starts browser PKCE login through the local sidecar', async () => {
    await fixture.componentInstance.startLogin();

    expect(api.startCloudAiBrowserLogin).toHaveBeenCalled();
    expect(browserAuth.openedUrl).toBe('https://auth.example.test/authorize');
  });

  it('generates a local device key without exposing private material', async () => {
    fixture.componentInstance.deviceName.set('Work Mac');

    await fixture.componentInstance.generateKey();

    expect(api.generateCloudAiDeviceKey).toHaveBeenCalledWith('Work Mac');
    expect(JSON.stringify(fixture.componentInstance.key())).not.toContain('private');
  });

  it('registers the current desktop and refreshes devices', async () => {
    fixture.componentInstance.deviceName.set('Work Mac');

    await fixture.componentInstance.registerDevice();

    expect(api.registerCloudAiDevice).toHaveBeenCalledWith('Work Mac');
    expect(api.listCloudAiDevices).toHaveBeenCalled();
  });

  it('shows recent-auth guidance when rotate returns recent_auth_required', async () => {
    api.rotateCloudAiDeviceKey.and.returnValue(throwError(() => ({
      status: 401,
      error: { detail: { code: 'recent_auth_required' } },
    })));

    await fixture.componentInstance.rotateKey();

    expect(fixture.componentInstance.error()).toContain('Sign in again');
  });

  it('requires unlink confirmation before calling the API', async () => {
    fixture.componentInstance.unlinkConfirmation.set('delete');

    await fixture.componentInstance.unlink();

    expect(api.unlinkCloudAiAccount).not.toHaveBeenCalled();
    expect(fixture.componentInstance.error()).toContain('Type unlink');
  });

  it('calls unlink with explicit local key deletion confirmation', async () => {
    fixture.componentInstance.unlinkConfirmation.set('unlink');

    await fixture.componentInstance.unlink();

    expect(api.unlinkCloudAiAccount).toHaveBeenCalledWith({
      delete_local_key: true,
      confirmation: 'unlink',
    });
  });
});
```

- [ ] **Step 2: Run the component spec and verify it fails**

Run:

```bash
cd shipagent-frontend
npx nx test settings-remote --watch=false
```

Expected: FAIL with `Cannot find module './cloud-ai-section.component'`.

- [ ] **Step 3: Implement the component**

Create `shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.ts`:

```typescript
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
  inject,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { CloudAiStore } from '@shipagent/shared-state';
import type {
  CloudAiDevice,
  CloudAiDeviceKeyResponse,
  CloudAiStatusResponse,
} from '@shipagent/shared-types';
import type { KeychainEntitlementStatus } from '@shipagent/shared-tauri';
import { CloudAiBrowserAuthService } from './cloud-ai-browser-auth.service';
import { CloudAiKeychainService } from './cloud-ai-keychain.service';

@Component({
  selector: 'app-cloud-ai-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="settings-section">
      <button
        class="settings-section-header"
        (click)="toggled.emit()"
        [attr.aria-expanded]="isOpen"
      >
        <div class="flex items-center gap-2">
          <svg class="h-4 w-4 text-info" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2v20"></path>
            <path d="M2 12h20"></path>
            <path d="m4.93 4.93 14.14 14.14"></path>
            <path d="m19.07 4.93-14.14 14.14"></path>
          </svg>
          <span class="font-medium text-foreground">Cloud AI</span>
          @if (status()?.enabled) {
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-success/15 text-success border border-success/30">
              Enabled
            </span>
          } @else {
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-warning/15 text-warning border border-warning/30">
              Off
            </span>
          }
          <span class="text-[10px] px-1.5 py-0.5 rounded-full border" [class]="relayBadgeClass()">
            {{ relayLabel() }}
          </span>
        </div>
        <svg
          class="h-4 w-4 text-muted-foreground transition-transform"
          [class.rotate-180]="isOpen"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      @if (isOpen) {
        <div class="settings-section-content space-y-3">
          @if (error()) {
            <div class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {{ error() }}
            </div>
          }

          @if (keychainStatus() && !keychainStatus()?.can_use_keychain) {
            <div class="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
              {{ keychainStatus()?.reason }}
            </div>
          }

          <div class="rounded-lg border border-border p-3 space-y-2">
            <div class="flex items-center justify-between gap-2">
              <div>
                <div class="text-sm font-medium text-foreground">Cloud Account</div>
                <div class="text-xs text-muted-foreground">
                  {{ status()?.auth?.account_email || 'Not signed in' }}
                </div>
              </div>
              <button
                type="button"
                class="text-xs px-2.5 py-1.5 rounded-md border border-border hover:bg-muted/40"
                (click)="startLogin()"
                [disabled]="actionInFlight() === 'login'"
              >
                {{ status()?.auth?.authenticated ? 'Refresh Login' : 'Sign In' }}
              </button>
            </div>
            @if (loginMessage()) {
              <p class="text-xs text-muted-foreground">{{ loginMessage() }}</p>
            }
          </div>

          <div class="rounded-lg border border-border p-3 space-y-2">
            <label class="text-xs font-medium text-muted-foreground" for="cloud-ai-device-name">
              Device name
            </label>
            <input
              id="cloud-ai-device-name"
              class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              [value]="deviceName()"
              (input)="deviceName.set(inputValue($event))"
              maxlength="80"
            />
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="text-xs px-2.5 py-1.5 rounded-md border border-border hover:bg-muted/40"
                (click)="generateKey()"
                [disabled]="isBusy()"
              >
                Generate Key
              </button>
              <button
                type="button"
                class="text-xs px-2.5 py-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-50"
                (click)="registerDevice()"
                [disabled]="isBusy()"
              >
                Register Desktop
              </button>
            </div>
            @if (key()) {
              <p class="text-xs text-muted-foreground">
                Key fingerprint: <span class="font-mono">{{ key()?.fingerprint }}</span>
              </p>
            }
          </div>

          <div class="rounded-lg border border-border p-3 space-y-2">
            <div class="flex items-center justify-between gap-2">
              <div>
                <div class="text-sm font-medium text-foreground">Relay Status</div>
                <div class="text-xs text-muted-foreground">{{ relayDetail() }}</div>
              </div>
              <button
                type="button"
                class="text-xs px-2.5 py-1.5 rounded-md border border-border hover:bg-muted/40"
                (click)="refresh()"
                [disabled]="loading()"
              >
                Refresh
              </button>
            </div>
          </div>

          <div class="rounded-lg border border-border p-3 space-y-2">
            <div class="text-sm font-medium text-foreground">Devices</div>
            @for (device of devices(); track device.device_id) {
              <div class="rounded-md border border-border px-2.5 py-2 space-y-2">
                <div class="flex items-start justify-between gap-2">
                  <div>
                    <div class="text-sm text-foreground">{{ device.display_name }}</div>
                    <div class="text-[11px] text-muted-foreground font-mono">{{ device.fingerprint }}</div>
                    <div class="text-[11px] text-muted-foreground">
                      {{ device.status }} - {{ device.shipagent_core_version }}
                    </div>
                  </div>
                  <div class="flex flex-wrap justify-end gap-1">
                    @if (device.is_current) {
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-info/10 text-info border border-info/30">
                        This device
                      </span>
                    }
                    @if (device.is_active) {
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-success/10 text-success border border-success/30">
                        Active
                      </span>
                    }
                  </div>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="text-xs px-2 py-1 rounded-md border border-border hover:bg-muted/40 disabled:opacity-50"
                    (click)="setActive(device)"
                    [disabled]="device.is_active || isBusy() || device.status === 'revoked'"
                  >
                    Set Active
                  </button>
                  @if (device.is_current) {
                    <button
                      type="button"
                      class="text-xs px-2 py-1 rounded-md border border-border hover:bg-muted/40 disabled:opacity-50"
                      (click)="rotateKey()"
                      [disabled]="isBusy()"
                    >
                      Rotate Key
                    </button>
                  }
                  <button
                    type="button"
                    class="text-xs px-2 py-1 rounded-md border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50"
                    (click)="revoke(device)"
                    [disabled]="isBusy() || device.status === 'revoked'"
                  >
                    Revoke
                  </button>
                </div>
              </div>
            } @empty {
              <div class="text-xs text-muted-foreground">No registered devices.</div>
            }
          </div>

          <div class="rounded-lg border border-destructive/30 p-3 space-y-2">
            <div class="text-sm font-medium text-foreground">Unlink Cloud Account</div>
            <p class="text-xs text-muted-foreground">
              Type unlink to unregister this desktop and delete the local device key.
            </p>
            <input
              class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              [value]="unlinkConfirmation()"
              (input)="unlinkConfirmation.set(inputValue($event))"
            />
            <button
              type="button"
              class="text-xs px-2.5 py-1.5 rounded-md border border-destructive/40 text-destructive hover:bg-destructive/10 disabled:opacity-50"
              (click)="unlink()"
              [disabled]="isBusy()"
            >
              Unlink
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class CloudAiSectionComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly browserAuth = inject(CloudAiBrowserAuthService);
  private readonly keychainService = inject(CloudAiKeychainService);
  private readonly cloudAiStore = inject(CloudAiStore);

  @Input() isOpen = false;
  @Output() toggled = new EventEmitter<void>();

  deviceName = signal('ShipAgent Desktop');
  key = signal<CloudAiDeviceKeyResponse | null>(null);
  keychainStatus = signal<KeychainEntitlementStatus | null>(null);
  loginMessage = signal<string | null>(null);
  unlinkConfirmation = signal('');

  status = this.cloudAiStore.status;
  devices = this.cloudAiStore.devices;
  loading = this.cloudAiStore.loading;
  actionInFlight = this.cloudAiStore.actionInFlight;
  error = this.cloudAiStore.error;

  ngOnInit(): void {
    void this.refresh();
    void this.loadKeychainStatus();
  }

  async refresh(): Promise<void> {
    this.cloudAiStore.setLoading(true);
    try {
      const [status, list] = await Promise.all([
        firstValueFrom(this.apiService.getCloudAiStatus()),
        firstValueFrom(this.apiService.listCloudAiDevices()),
      ]);
      this.applyStatus(status);
      this.cloudAiStore.setDevices(list.devices);
    } catch {
      this.cloudAiStore.setError('Cloud AI status could not be loaded.');
    } finally {
      this.cloudAiStore.setLoading(false);
    }
  }

  async startLogin(): Promise<void> {
    this.cloudAiStore.setActionInFlight('login');
    try {
      const start = await firstValueFrom(this.apiService.startCloudAiBrowserLogin());
      this.browserAuth.open(start.auth_url);
      this.loginMessage.set('Complete the browser sign-in, then return here and refresh status.');
    } catch {
      this.cloudAiStore.setError('Cloud AI sign-in could not be started.');
    } finally {
      this.cloudAiStore.setActionInFlight(null);
    }
  }

  async generateKey(): Promise<void> {
    this.cloudAiStore.setActionInFlight('generate-key');
    try {
      const generated = await firstValueFrom(
        this.apiService.generateCloudAiDeviceKey(this.normalizedDeviceName()),
      );
      this.key.set(generated);
    } catch {
      this.cloudAiStore.setError('Device key could not be generated.');
    } finally {
      this.cloudAiStore.setActionInFlight(null);
    }
  }

  async registerDevice(): Promise<void> {
    await this.runDeviceAction('register', async () => {
      const status = await firstValueFrom(
        this.apiService.registerCloudAiDevice(this.normalizedDeviceName()),
      );
      this.applyStatus(status);
      await this.refreshDevices();
    });
  }

  async rotateKey(): Promise<void> {
    await this.runDeviceAction('rotate', async () => {
      const status = await firstValueFrom(this.apiService.rotateCloudAiDeviceKey());
      this.applyStatus(status);
      await this.refreshDevices();
    });
  }

  async revoke(device: CloudAiDevice): Promise<void> {
    await this.runDeviceAction('revoke', async () => {
      await firstValueFrom(this.apiService.revokeCloudAiDevice(device.device_id));
      await this.refresh();
    });
  }

  async setActive(device: CloudAiDevice): Promise<void> {
    await this.runDeviceAction('set-active', async () => {
      const status = await firstValueFrom(this.apiService.setActiveCloudAiDevice(device.device_id));
      this.applyStatus(status);
      await this.refreshDevices();
    });
  }

  async unlink(): Promise<void> {
    if (this.unlinkConfirmation() !== 'unlink') {
      this.cloudAiStore.setError('Type unlink before deleting the local device key.');
      return;
    }
    await this.runDeviceAction('unlink', async () => {
      const status = await firstValueFrom(this.apiService.unlinkCloudAiAccount({
        delete_local_key: true,
        confirmation: 'unlink',
      }));
      this.applyStatus(status);
      this.key.set(null);
      this.unlinkConfirmation.set('');
      await this.refreshDevices();
    });
  }

  relayLabel(): string {
    const state = this.status()?.relay.state ?? 'disabled';
    if (state === 'online') return 'Relay online';
    if (state === 'connecting') return 'Relay connecting';
    if (state === 'update_required') return 'Update required';
    if (state === 'degraded') return 'Relay degraded';
    if (state === 'offline') return 'Relay offline';
    return 'Relay off';
  }

  relayDetail(): string {
    const relay = this.status()?.relay;
    if (!relay) return 'Relay status has not loaded.';
    if (relay.message) return relay.message;
    if (relay.last_heartbeat_at) return `Last heartbeat ${relay.last_heartbeat_at}`;
    return this.relayLabel();
  }

  relayBadgeClass(): string {
    const state = this.status()?.relay.state ?? 'disabled';
    if (state === 'online') return 'bg-success/10 text-success border-success/30';
    if (state === 'update_required' || state === 'degraded') return 'bg-warning/10 text-warning border-warning/30';
    return 'bg-muted text-muted-foreground border-border';
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  isBusy(): boolean {
    return this.actionInFlight() !== null;
  }

  private async loadKeychainStatus(): Promise<void> {
    try {
      this.keychainStatus.set(await this.keychainService.getStatus());
    } catch {
      this.keychainStatus.set({
        platform: 'unknown',
        app_identifier: 'com.shipagent.app',
        entitlements_file_present: false,
        keychain_access_configured: false,
        keychain_access_groups: [],
        can_use_keychain: false,
        reason: 'Keychain entitlement status could not be read',
      });
    }
  }

  private async refreshDevices(): Promise<void> {
    const list = await firstValueFrom(this.apiService.listCloudAiDevices());
    this.cloudAiStore.setDevices(list.devices);
  }

  private applyStatus(status: CloudAiStatusResponse): void {
    this.cloudAiStore.setStatus(status);
    this.key.set(status.key);
  }

  private async runDeviceAction(
    action: 'register' | 'rotate' | 'revoke' | 'set-active' | 'unlink',
    work: () => Promise<void>,
  ): Promise<void> {
    this.cloudAiStore.setActionInFlight(action);
    try {
      await work();
      this.loginMessage.set(null);
    } catch (error) {
      if (this.isRecentAuthError(error)) {
        this.cloudAiStore.setError('Sign in again to manage Cloud AI devices.');
      } else {
        this.cloudAiStore.setError('Cloud AI device action failed.');
      }
    } finally {
      this.cloudAiStore.setActionInFlight(null);
    }
  }

  private isRecentAuthError(error: unknown): boolean {
    const payload = error as {
      status?: number;
      error?: { detail?: { code?: string } };
    };
    return payload.status === 401 && payload.error?.detail?.code === 'recent_auth_required';
  }

  private normalizedDeviceName(): string {
    const value = this.deviceName().trim();
    return value.length > 0 ? value : 'ShipAgent Desktop';
  }
}
```

- [ ] **Step 4: Run the component spec and verify it passes**

Run:

```bash
cd shipagent-frontend
npx nx test settings-remote --watch=false
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.ts shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.spec.ts
git commit -m "feat: add cloud ai settings section"
```

## Task 8: Settings Flyout Integration

**Files:**

- Modify: `shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts`

- [ ] **Step 1: Add Cloud AI section import**

Modify imports in `settings-flyout.component.ts`:

```typescript
import { CloudAiSectionComponent } from '../cloud-ai-section/cloud-ai-section.component';
```

Modify the component `imports` array:

```typescript
  imports: [
    ConnectionsSectionComponent,
    ShipmentBehaviourSectionComponent,
    AddressBookSectionComponent,
    CustomCommandsSectionComponent,
    CloudAiSectionComponent,
  ],
```

- [ ] **Step 2: Add the accordion entry**

Add this block after `<app-connections-section ... />`:

```angular-html
        <!-- Cloud AI -->
        <app-cloud-ai-section
          [isOpen]="openSection() === 'cloud-ai'"
          (toggled)="toggleSection('cloud-ai')"
        />
```

- [ ] **Step 3: Run settings tests and typecheck**

Run:

```bash
cd shipagent-frontend
npx nx test settings-remote --watch=false
npx nx typecheck settings-remote
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts
git commit -m "feat: surface cloud ai in settings flyout"
```

## Task 9: Targeted Validation

**Files:**

- No source changes.

- [ ] **Step 1: Run backend targeted tests**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_cloud_ai_settings_service.py tests/api/test_cloud_ai.py -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend targeted tests**

Run:

```bash
cd shipagent-frontend
npx nx test shared-state --watch=false
npx nx test settings-remote --watch=false
npx nx typecheck settings-remote
npx nx lint settings-remote
```

Expected: PASS.

- [ ] **Step 3: Run Tauri validation**

Run:

```bash
cd src-tauri
cargo test
cargo check
```

Expected: PASS.

- [ ] **Step 4: Run production build for the changed remote**

Run:

```bash
cd shipagent-frontend
npx nx build settings-remote --configuration=production
```

Expected: PASS.

- [ ] **Step 5: Commit validation-only fixes if commands exposed integration failures**

Use this command only if Step 1 through Step 4 required follow-up edits:

```bash
git add src/services/cloud_ai_settings_service.py src/api/routes/cloud_ai.py src/api/main.py tests/services/test_cloud_ai_settings_service.py tests/api/test_cloud_ai.py shipagent-frontend/libs/shared/types/src/cloud-ai.types.ts shipagent-frontend/libs/shared/types/src/index.ts shipagent-frontend/libs/shared/api/src/api.service.ts shipagent-frontend/libs/shared/state/src/cloud-ai.store.ts shipagent-frontend/libs/shared/state/src/cloud-ai.store.spec.ts shipagent-frontend/libs/shared/state/src/index.ts shipagent-frontend/libs/shared/tauri/src/keychain-entitlement.ts shipagent-frontend/libs/shared/tauri/src/index.ts shipagent-frontend/libs/testing/src/fixtures/cloud-ai.fixtures.ts shipagent-frontend/libs/testing/src/index.ts shipagent-frontend/libs/testing/src/mocks/api.service.mock.ts shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-browser-auth.service.ts shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-keychain.service.ts shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.ts shipagent-frontend/apps/settings-remote/src/app/cloud-ai-section/cloud-ai-section.component.spec.ts shipagent-frontend/apps/settings-remote/src/app/settings-flyout/settings-flyout.component.ts src-tauri/src/main.rs src-tauri/entitlements.plist
git commit -m "fix: complete cloud ai settings validation"
```

## Dependencies Consumed

- Plan 1 cloud control-plane device endpoints for register, list, revoke, rotate, set-active, and unlink.
- Plan 1 relay key service with Ed25519 private key stored in OS keychain through Python `keyring`, exposed through the stable `src.services.relay_key_service.RelayKeyService` import path.
- Plan 1 desktop relay client status and reconnect primitives, exposed through the stable `src.services.desktop_relay_client.DesktopRelayClient` import path.
- Plan 9 owns the local browser PKCE coordinator and cloud relay-device HTTP client if Plan 1 provides only cloud endpoints and low-level relay primitives.
- Existing local FastAPI sidecar mounted under `/api/v1`.
- Existing Angular settings remote, shared API, shared types, shared state, and testing fixtures.
- Existing Tauri v2 invoke pattern in `src-tauri/src/main.rs`.

## Dependencies Provided

- Local sidecar `/api/v1/cloud-ai/*` contract for desktop Cloud AI settings.
- Shared frontend `CloudAi*` DTOs for future shell/sidebar status surfaces.
- `CloudAiStore` for cross-remote relay/account/device status if later plans need it.
- Settings UI path for users to enable Cloud AI Features and manage devices.
- Tauri keychain entitlement status command for desktop diagnostics.

## Overlap Risks

- **Plan 1:** High naming risk. This plan consumes Plan 1 service names and device-client methods. Resolve Plan 1 names before coding Task 1; do not duplicate relay crypto, cloud device persistence, or websocket logic in this slice.
- **Plan 1:** Device list, set-active, and unlink must be cloud-side Plan 1 capabilities or Plan 1 extension points. If Plan 1 only exposes register, rotate-key, and revoke, update Plan 1 first rather than adding cloud control-plane routes here.
- **Plan 4:** This plan must not add retention, audit ledger, Redis TTL, or purge behavior. It may display device and relay status returned by Plan 1, but it must not persist cloud audit state.
- **Plan 4:** Revocation, active-device replacement, and unlink may invalidate approval requests or grants through Plan 1/Plan 4 services. This UI calls the local facade and displays the result; it does not implement invalidation storage.

## Final Validation Commands

Run these before marking the implementation complete:

```bash
.venv/bin/python -m pytest tests/services/test_cloud_ai_settings_service.py tests/api/test_cloud_ai.py -v
cd shipagent-frontend && npx nx test shared-state --watch=false
cd shipagent-frontend && npx nx test settings-remote --watch=false
cd shipagent-frontend && npx nx typecheck settings-remote
cd shipagent-frontend && npx nx lint settings-remote
cd shipagent-frontend && npx nx build settings-remote --configuration=production
cd src-tauri && cargo test
cd src-tauri && cargo check
```

## Self-Review Checklist

- [ ] Q26 is covered by browser PKCE start, loopback-owned auth session, and no OAuth token in Angular.
- [ ] Q27 is covered by recent-auth errors for register, rotate, revoke, set-active, and unlink, plus explicit unlink confirmation before local key deletion.
- [ ] Q28 and Q29 are not implemented here; durable audit and retention remain Plan 4 responsibilities.
- [ ] Q30 is not implemented here; approval URL exposure remains Plan 7.
- [ ] Q31 is not implemented here; relay replay protection remains Plan 1 and Plan 2.
- [ ] Plan 9 enablement is covered by sign-in, generate key, register, status, relay indicator, device list, revoke, rotate, set-active, unlink, and keychain entitlement status.
- [ ] No private key, Auth0 token, row data, labels, raw UPS payloads, or provider prompts are rendered in the settings UI.
- [ ] No generated provider artifact is edited by this plan.
