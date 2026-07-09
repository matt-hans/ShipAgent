# PR #28 Relay Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PR #28 conform to Plan 1’s relay security, liveness, execution-target, and portability contracts so it can be merged safely.

**Architecture:** Preserve the existing relay walking-skeleton scope: only `get_shipagent_status` is publicly exported, but all public calls cross a provider-neutral `ExecutionTarget.invoke(TargetToolRequest)` seam. The relay uses canonical typed JSON frames, a short-lived EdDSA JWT handshake, durable device state, and an atomic Redis liveness publication. Mutating a device must commit durable state before closing and unregistering its live socket, which rejects every pending invocation.

**Tech Stack:** Python 3.12, FastAPI WebSockets, PyJWT EdDSA, SQLAlchemy/Alembic, Redis Lua, keyring, websockets, pytest, Ruff.

## Global Constraints

- Work only on branch `plan-1-relay-walking-skeleton` in its existing worktree; never change `main` and never force-push.
- Preserve the currently uncommitted review-remediation patch; it is within this task’s scope but must be validated, completed, and committed in the task owning each file.
- Keep public hosted MCP exports status-only in this plan. Do not export shipment execution or add speculative workflow tools.
- Relay authentication is a single short-lived EdDSA JWT with audience `shipagent-cloud-relay`, binding device, account, nonce, and relay-session ID. Enforce `iat`, `exp`, and a maximum 60-second signed lifetime.
- Canonical wire-message `type` values are `relay.challenge`, `relay.authenticate`, `relay.authenticated`, `relay.heartbeat`, `relay.invoke`, and `relay.invocation_result`.
- Heartbeats contain the authenticated session and device IDs, version metadata, `active_source_fingerprint`, and `sent_at`. A source fingerprint must never be substituted with the relay public-key fingerprint.
- A public production relay endpoint must use `wss://`. Plaintext `ws://` is allowed only through an explicitly opted-in loopback development transport, never for a non-loopback host.
- `RelayDevice` persists `key_version` (starting at 1 and incremented on rotation) and `revoked_at` (set on revocation). Routes only expose safe device metadata.
- Publish session, heartbeat, and active-target Redis records atomically for a device. Refresh and cleanup must never remove a newer relay session.
- Each relay session allows one in-flight invocation. Send failures, disconnects, replacement, rotation, revocation, and unlinking must resolve as relay-domain/offline outcomes, not raw transport exceptions.
- Device policy mutations close the matching WebSocket with close code `1008`, unregister the broker session, and fail all pending futures only after their durable mutation commits.
- Tests use public behavior and real interfaces/fakes at the external boundary; they must not inspect private implementation details. Use red → green → refactor one behavior at a time.
- Run targeted tests before broad validation, format changed Python files, regenerate artifacts only when their canonical registry source changes, and do not hand-edit generated artifacts.

---

## File Structure

- `src/control_plane/relay/protocol.py` — canonical typed relay frames and JWT verification policy.
- `src/services/desktop_relay_client.py` and `src/services/relay_key_service.py` — secure desktop transport, truthful heartbeat metadata, and default keyring-backed device keys.
- `src/control_plane/models.py`, `alembic/versions/20260630_0002_relay_devices.py`, and `src/control_plane/relay/registry.py` — durable device-version/revocation data and atomic Redis liveness.
- `src/control_plane/relay/invocations.py`, `src/control_plane/relay/routes.py`, `src/control_plane/execution_targets.py`, and `src/hosted_mcp/execution_target_handlers.py` — session lifecycle and provider-neutral invocation boundary.
- `tests/control_plane/relay/`, `tests/services/`, and `tests/e2e/test_portability_smoke.py` — behavioral coverage for every reviewed finding.

### Task 1: Canonical protocol and desktop transport hardening

**Files:**
- Modify: `src/control_plane/relay/protocol.py`
- Modify: `src/services/desktop_relay_client.py`
- Modify: `src/services/relay_key_service.py`
- Modify: `tests/control_plane/relay/test_protocol.py`
- Modify: `tests/services/test_desktop_relay_client.py`
- Modify: `tests/services/test_relay_key_service.py`

**Interfaces:**
- Produces `RelayAuthenticateMessage(type="relay.authenticate", token: str)` and protocol models whose `type` values match the global constraints.
- Produces `verify_handshake_jwt(handshake: RelayAuthenticateMessage, public_key_pem: str) -> RelayHandshakeClaims`, accepting only an EdDSA token with valid audience, non-future `iat`, unexpired `exp`, and `0 < exp - iat <= 60`.
- Produces `WebSocketRelayTransport(allow_insecure_loopback: bool = False)`, which permits `wss://` and permits `ws://` only when both the opt-in is true and the parsed host is loopback.
- Produces `RelayKeyService(store: RelayKeyStore | None = None)` backed by `KeyringStore` when no test store is supplied.

- [ ] **Step 1: Write one failing JWT-boundary test**

```python
def test_handshake_jwt_rejects_lifetime_longer_than_sixty_seconds():
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    private_key_pem = _private_key_pem()
    public_key_pem = _public_key_pem(private_key_pem)
    token = encode_handshake_jwt(
        build_handshake_claims(
            device_id="device-1", account_id="acct-1",
            relay_session_id="session-1", nonce="nonce-1",
            version=_version(), lifetime_seconds=61, now=now,
        ),
        private_key_pem,
    )
    with pytest.raises(ValueError, match="lifetime"):
        verify_handshake_jwt(token, public_key_pem)
```

- [ ] **Step 2: Run it red**

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_protocol.py -k lifetime -v`

Expected: FAIL because verification accepts a signed lifetime longer than 60 seconds.

- [ ] **Step 3: Implement the minimal JWT and typed-frame contract**

```python
MAX_RELAY_HANDSHAKE_LIFETIME_SECONDS = 60

if claims.expires_at <= claims.issued_at or (
    claims.expires_at - claims.issued_at
).total_seconds() > MAX_RELAY_HANDSHAKE_LIFETIME_SECONDS:
    raise ValueError("invalid handshake lifetime")

class RelayAuthenticateMessage(RelayProtocolModel):
    type: Literal["relay.authenticate"] = "relay.authenticate"
    token: str
```

Use the typed challenge, authenticated, heartbeat, invocation, and result frames in the desktop client and later route task. Include `device_id` and `sent_at` in heartbeat data. Keep source identity independent: default it to `None` unless the desktop runtime explicitly supplies a real source fingerprint; never assign `keypair.fingerprint` to it.

- [ ] **Step 4: Write and run the next red/green transport and default-key-store tests**

```python
def test_websocket_transport_rejects_public_plaintext_url():
    with pytest.raises(ValueError, match="wss"):
        WebSocketRelayTransport().connect("ws://relay.example/relay/connect")

def test_websocket_transport_allows_explicit_loopback_development_url():
    transport = WebSocketRelayTransport(allow_insecure_loopback=True)
    assert transport.connect("ws://127.0.0.1:8080/relay/connect")

def test_relay_key_service_uses_keyring_store_by_default(monkeypatch):
    monkeypatch.setattr(relay_key_service, "KeyringStore", FakeKeyringStore)
    assert RelayKeyService().generate_or_load_keypair().public_key_pem
```

Run: `.venv/bin/python -m pytest tests/services/test_desktop_relay_client.py tests/services/test_relay_key_service.py -k 'plaintext or loopback or keyring' -v`

Expected: tests fail before each implementation and pass afterward.

- [ ] **Step 5: Run the task suite and commit**

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_protocol.py tests/services/test_desktop_relay_client.py tests/services/test_relay_key_service.py -v`

Run: `.venv/bin/python -m ruff format src/control_plane/relay/protocol.py src/services/desktop_relay_client.py src/services/relay_key_service.py tests/control_plane/relay/test_protocol.py tests/services/test_desktop_relay_client.py tests/services/test_relay_key_service.py && .venv/bin/python -m ruff check src/control_plane/relay/protocol.py src/services/desktop_relay_client.py src/services/relay_key_service.py tests/control_plane/relay/test_protocol.py tests/services/test_desktop_relay_client.py tests/services/test_relay_key_service.py`

Commit: `git add src/control_plane/relay/protocol.py src/services/desktop_relay_client.py src/services/relay_key_service.py tests/control_plane/relay/test_protocol.py tests/services/test_desktop_relay_client.py tests/services/test_relay_key_service.py && git commit -m "fix: harden relay protocol and desktop transport"`

### Task 2: Durable device versioning and atomic liveness publication

**Files:**
- Modify: `src/control_plane/models.py`
- Modify: `alembic/versions/20260630_0002_relay_devices.py`
- Modify: `src/control_plane/relay/registry.py`
- Modify: `tests/control_plane/relay/test_registry.py`
- Modify: `tests/control_plane/test_models.py`

**Interfaces:**
- Produces durable `RelayDevice.key_version: int` and `RelayDevice.revoked_at: datetime | None`.
- Produces `RelayDeviceRegistry.accept_handshake(handshake, challenge_relay_session_id)` that atomically writes matching session/heartbeat/active-target values for one accepted session.
- Preserves liveness only when Redis records agree on account, device, and session; heartbeat source metadata is descriptive and must not equal or be checked against the relay signing-key fingerprint.

- [ ] **Step 1: Write a failing persistence test**

```python
async def test_rotate_increments_key_version_and_revoke_persists_timestamp(registry):
    device = await registry.register_device(
        "acct-1", "desktop-1", _public_key_pem(_private_key_pem())
    )
    assert device.key_version == 1
    rotated = await registry.rotate_key(
        device.account_id, device.device_id, _public_key_pem(_private_key_pem())
    )
    revoked = await registry.revoke_device(device.account_id, device.device_id)
    assert rotated.key_version == 2
    assert revoked.revoked_at is not None
```

- [ ] **Step 2: Run it red**

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_registry.py -k 'key_version or revoked_at' -v`

Expected: FAIL because the fields are absent or never updated.

- [ ] **Step 3: Add model and migration fields, then make the registry round-trip them**

```python
key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

record.key_version += 1
record.revoked_at = utc_now()
record.revoked = True
record.active = False
```

Update the existing unmerged relay-device migration rather than adding a second migration. Include safe `key_version` in the public device response in Task 3; keep private key material and source identity out of responses.

- [ ] **Step 4: Write a failing concurrent-handshake liveness test**

```python
async def test_two_accepted_sessions_never_publish_mixed_liveness_records(registry, redis):
    first, second = await asyncio.gather(
        registry.accept_handshake(first_handshake, first_challenge.relay_session_id),
        registry.accept_handshake(second_handshake, second_challenge.relay_session_id),
    )
    session = RelaySession.model_validate_json(await redis.get(RedisKey.relay_session("device-1")))
    heartbeat = RelayHeartbeat.model_validate_json(await redis.get(RedisKey.relay_heartbeat("device-1")))
    active = RelaySession.model_validate_json(await redis.get(RedisKey.relay_active_target("acct-1")))
    assert len({session.relay_session_id, heartbeat.relay_session_id, active.relay_session_id}) == 1
    assert session.relay_session_id in {first.relay_session_id, second.relay_session_id}
```

- [ ] **Step 5: Implement atomic publish and test green**

```lua
redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[4])
redis.call("SET", KEYS[2], ARGV[2], "EX", ARGV[4])
if ARGV[3] == "1" then
    redis.call("SET", KEYS[3], ARGV[1], "EX", ARGV[4])
end
return 1
```

Use this Lua transaction from `accept_handshake`, with `RelaySession` and `RelayHeartbeat` payloads captured before the call. Update the fake Redis evaluator to execute the observable atomic result. Remove the old signing-key/source-fingerprint equality gate from `get_active_heartbeat`.

- [ ] **Step 6: Run the task suite, migration check, and commit**

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_registry.py tests/control_plane/test_models.py -v`

Run: `rm -f /tmp/shipagent-pr28-alembic.db && SHIPAGENT_DATABASE_URL=sqlite+aiosqlite:////tmp/shipagent-pr28-alembic.db .venv/bin/alembic -c alembic.ini upgrade head`

Commit: `git add src/control_plane/models.py alembic/versions/20260630_0002_relay_devices.py src/control_plane/relay/registry.py tests/control_plane/relay/test_registry.py tests/control_plane/test_models.py && git commit -m "fix: make relay device liveness durable and atomic"`

### Task 3: Generic target invocation and immediate session termination

**Files:**
- Modify: `src/control_plane/execution_targets.py`
- Modify: `src/hosted_mcp/execution_target_handlers.py`
- Modify: `src/control_plane/relay/invocations.py`
- Modify: `src/control_plane/relay/routes.py`
- Modify: `src/control_plane/app.py`
- Modify: `tests/control_plane/relay/test_invocations.py`
- Modify: `tests/control_plane/relay/test_routes.py`
- Modify: `tests/control_plane/relay/test_registry.py`

**Interfaces:**
- Produces `@dataclass(frozen=True) TargetToolRequest(account_id, provider_connection_id, provider_surface, tool_name, arguments, correlation_id)`.
- Produces `ExecutionTarget.invoke(request: TargetToolRequest) -> dict[str, Any]`.
- `RelayExecutionTarget` relays `request.tool_name` and `request.arguments`; only status gets the schema-valid offline fallback. `LoopbackExecutionTarget` implements the same seam.
- `RelayInvocationBroker.disconnect_device(account_id, device_id, code=1008, reason="relay device disconnected")` closes matching connections, unregisters them, and completes pending calls with `NoLiveRelaySession`.

- [ ] **Step 1: Write a failing generic-seam test**

```python
async def test_status_handler_builds_full_target_tool_request():
    target = RecordingTarget(result={
        "status": "ready",
        "executionTarget": {"state": "ready", "target_id": "device-1", "capabilities": []},
    })
    context = AuthorizationContext(
        account_id="acct-1", provider_connection_id="pc-1", provider_surface="chatgpt",
        subject="auth0|owner-1", client_id="chatgpt-client", scopes=frozenset(),
    )
    result = await build_execution_target_tool_handlers(target)["get_shipagent_status"](
        context, {"correlation_id": "corr-1"}
    )
    assert target.requests == [TargetToolRequest(
        account_id="acct-1", provider_connection_id="pc-1",
        provider_surface="chatgpt", tool_name="get_shipagent_status",
        arguments={"correlation_id": "corr-1"}, correlation_id="corr-1",
    )]
    assert result["status"] == "ready"
```

- [ ] **Step 2: Run it red**

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_routes.py -k target_tool_request -v`

Expected: FAIL because the handler calls the status-specific API.

- [ ] **Step 3: Implement only the generic seam**

```python
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
        """Invoke a provider-neutral workflow tool on the active target."""
```

Use `request.tool_name` when constructing `RelayInvocationBroker.invoke(...)`. For `get_shipagent_status`, validate the returned `ShipAgentStatus`, filter public capabilities, and turn `NoLiveRelaySession`, `RelayInvocationTimeout`, `RelayInvocationBusy`, or send failure into the advertised offline dict. For other future callers, return the relay result/error without inventing new tools.

- [ ] **Step 4: Write and run red/green lifecycle tests**

```python
async def test_disconnect_device_closes_unregisters_and_fails_pending_call():
    broker = RelayInvocationBroker()
    websocket = FakeRelayWebSocket()
    await broker.register("session-1", websocket, account_id="acct-1", device_id="device-1")
    pending = asyncio.create_task(broker.invoke(
        relay_session_id="session-1", tool_name="get_shipagent_status", arguments={},
        audit_correlation_id="corr-1", timeout_seconds=30,
    ))
    await asyncio.sleep(0)
    await broker.disconnect_device(account_id="acct-1", device_id="device-1", code=1008)
    with pytest.raises(NoLiveRelaySession):
        await pending
    assert websocket.close_calls == [(1008, "relay device disconnected")]
```

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_invocations.py tests/control_plane/relay/test_routes.py -k 'disconnect or send_failure or policy_mutation' -v`

Expected: each new test fails before its minimal implementation and passes after it.

- [ ] **Step 5: Finish route integration and commit**

After each durable `set-active` replacement, rotation, revocation, or unlink return, call the broker disconnect by `(account_id, device_id)` with code `1008`. Register each WebSocket with those identities, parse canonical typed frames, and always unregister/clear only the matching session during cleanup. Do not release a raw websocket exception past `RelayExecutionTarget`.

Run: `.venv/bin/python -m pytest tests/control_plane/relay/test_invocations.py tests/control_plane/relay/test_routes.py tests/control_plane/test_app_auth.py -v`

Commit: `git add src/control_plane/execution_targets.py src/hosted_mcp/execution_target_handlers.py src/control_plane/relay/invocations.py src/control_plane/relay/routes.py src/control_plane/app.py tests/control_plane/relay/test_invocations.py tests/control_plane/relay/test_routes.py tests/control_plane/relay/test_registry.py && git commit -m "fix: terminate relay sessions through generic targets"`

### Task 4: Portability contract, formatting, and merge validation

**Files:**
- Modify: `tests/e2e/test_portability_smoke.py`
- Modify: only files Ruff changes from Tasks 1–3

**Interfaces:**
- The generic MCP artifact remains status-only, while provider-specific public surfaces retain only the tools their canonical registry projection permits.

- [ ] **Step 1: Use the existing portability failure as the red test**

Run: `.venv/bin/python -m pytest tests/e2e/test_portability_smoke.py::test_relay_execution_tools_are_projected_safely -v`

Expected: FAIL because it incorrectly requires `execute_shipments` in a nonempty generic MCP artifact containing only `get_shipagent_status`.

- [ ] **Step 2: Assert the actual Plan 1 projection and run green**

```python
assert generic_names == {"get_shipagent_status"}
assert "execute_shipments" not in generic_names

if "execute_shipments" in openai_names:
    public_tool = next(tool for tool in openai_public if tool["name"] == "execute_shipments")
    assert public_tool["annotations"]["openWorldHint"] is True
```

Run: `.venv/bin/python -m pytest tests/e2e/test_portability_smoke.py -v`

- [ ] **Step 3: Format, lint, and run broad validations**

Run: `.venv/bin/python -m ruff format src/control_plane src/services tests/control_plane tests/services tests/e2e`

Run: `.venv/bin/python -m ruff check src/ tests/`

Run: `.venv/bin/python -m pytest tests/control_plane -v`

Run: `.venv/bin/python -m pytest -k "not stream and not sse and not progress"`

Run: `.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v`

Run: `uv lock --check`

- [ ] **Step 4: Commit**

Commit: `git add tests/e2e/test_portability_smoke.py src/control_plane src/services tests/control_plane tests/services tests/e2e && git commit -m "test: align relay portability and format fixes"`

## Final Review and Publish

- [ ] Generate a complete merge-base review package, then obtain a final independent review for critical/important findings.
- [ ] Resolve every critical or important finding through one TDD fix task and repeat the final review.
- [ ] Confirm `git status --short` is clean and every commit is on `plan-1-relay-walking-skeleton`.
- [ ] Push `plan-1-relay-walking-skeleton` to `origin`; PR #28 updates automatically. Do not create a replacement PR.
