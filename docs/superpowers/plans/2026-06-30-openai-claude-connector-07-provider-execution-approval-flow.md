# Provider Execution And Approval Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the OpenAI/Claude provider prepare, approval, execution, status, and label-artifact flow with immutable previews, one-time Execution Grants, and exact target-bound relay dispatch.

**Architecture:** Provider tools stay thin and delegate to `src/control_plane/provider_execution/`, which owns cloud approval state, grant validation, job/artifact references, and provider-safe envelopes. Local shipment detail, source selection, UPS credentials, BatchEngine execution, and label bytes stay on the Execution Target through `src/services/provider_execution_runtime.py`; the cloud only stores opaque references, redacted summaries, hashes, and short-lived Redis state. Claude approval is a server-rendered Auth0 browser surface; OpenAI uses widget-private metadata supplied by Plan 6 and consumed by Plan 8.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, httpx, cryptography/Fernet, redis.asyncio, SQLAlchemy async sessions, Pydantic v2, pytest/pytest-asyncio, existing BatchEngine and Plan 2 relay lifecycle APIs.

---

## Source Of Truth

Use `docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md` as the governing spec, especially:

- Plan 7 in section 4.
- Q15-Q31 decisions.
- D1-D11 decisions in section 3.1.
- Sections 3.3, 3.4, and 3.5 for invocation, retention, and error envelopes.
- Testing strategy in section 5.

Also preserve these repository invariants:

- Provider/runtime adapters do not own shipping business logic.
- Public mutating workflows use prepare/execute plus explicit confirmation.
- Row-level local shipping data, raw UPS payloads, credentials, labels, tokens, and full tracking arrays never enter provider-visible results.
- Control-plane persistence remains separate from desktop/job persistence.

## Current Repo State

Relevant files inspected while planning:

```text
AGENTS.md
src/AGENTS.md
docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md
docs/adr/0001-cloud-account-auth0-identity.md
docs/adr/0002-relay-first-execution-target.md
docs/adr/0003-provider-confirmation-execution-safety.md
docs/adr/0005-ephemeral-cloud-state-retention.md
docs/adr/0007-origin-based-provider-redaction.md
docs/adr/0008-in-provider-execution-no-handoff.md
src/control_plane/app.py
src/control_plane/auth/context.py
src/control_plane/auth/service.py
src/control_plane/config.py
src/control_plane/models.py
src/control_plane/redis_keys.py
src/control_plane/request_controls.py
src/control_plane/result_projection.py
src/control_plane/audit/service.py
src/hosted_mcp/server.py
src/provider_adapters/openai_projection.py
src/provider_adapters/mcp_projection.py
src/registry/models.py
src/registry/tools/public.py
src/services/batch_engine.py
src/services/batch_executor.py
src/services/idempotency.py
src/services/job_service.py
src/workflows/models.py
src/workflows/shipping.py
src/api/routes/preview.py
src/api/routes/labels.py
shipagent-frontend/AGENTS.md
shipagent-frontend/apps/provider-widget/src/app/preview-widget.component.ts
```

Current observations:

- `src/registry/tools/public.py` still has legacy scopes and `submit_one_off_shipment` in the base checkout. Plan 6 removes the separate one-off purchase path and adds the closed `shipment_source` union. Plan 7 must start after that merge.
- Plan 2 owns `job_ref`, invocation lifecycle, retry/recovery semantics, and grant callback hook points. Plan 7 must not create a second invocation state machine.
- Plan 4 owns Redis key names/TTLs and `AuthorizationLedgerService`. Plan 7 must use those APIs for approval, grant, label, browser-session, and hashed audit events.
- `BatchEngine.execute()` already distinguishes deterministic pre-UPS failures from ambiguous/post-UPS `needs_review`, but it launches every pending row. Plan 7 adds provider-originated category-aware stop behavior without changing the local default.
- The only provider frontend is `shipagent-frontend/apps/provider-widget/`. Claude approval must be server-rendered by the control plane and must not reuse the Angular shell or OpenAI widget.

## Integration Contracts Consumed

Plan 2 must provide these APIs before Task 7 starts:

```python
from src.control_plane.relay.lifecycle import (
    GrantCallbacks,
    InvocationLifecycleCoordinator,
    JobReferenceRecord,
    JobReferenceStore,
)

class InvocationLifecycleCoordinator:
    async def invoke(
        self,
        *,
        target,
        account_id: str,
        provider_connection_id: str,
        tool_name: str,
        arguments: dict[str, object],
        arguments_hash: str,
        grant_callbacks: GrantCallbacks | None,
        async_contract: bool,
    ) -> dict[str, object]: ...

class JobReferenceStore:
    async def resolve(
        self,
        job_ref: str,
        *,
        account_id: str,
        provider_connection_id: str,
    ) -> JobReferenceRecord | None: ...
```

Plan 4 must provide these APIs before Task 2 starts:

```python
from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.audit import AuthorizationLedgerService

RedisKey.approval_request("apr_x")
RedisKey.approval_locator("locator_hash")
RedisKey.execution_grant("apr_x")
RedisKey.approval_browser_session("sid_x")
RedisKey.label_download_reference("dl_x")
RedisKey.label_stream_lease("dl_x", "browser_session_x")
RedisTtl.APPROVAL_REQUEST_SECONDS
RedisTtl.EXECUTION_GRANT_SECONDS
RedisTtl.APPROVAL_BROWSER_SESSION_SECONDS
RedisTtl.LABEL_DOWNLOAD_REFERENCE_SECONDS
RedisTtl.LABEL_STREAM_LEASE_SECONDS
```

Plan 6 must provide these APIs before Task 1 starts:

```python
from src.control_plane.result_projection import (
    DataOrigin,
    OutputProfile,
    ProjectionContext,
    project_provider_result,
)
from src.registry.tools.shipment_source import prepare_shipments_input_schema
```

## File Structure

Create:

```text
src/control_plane/provider_execution/__init__.py
src/control_plane/provider_execution/browser_sessions.py
src/control_plane/provider_execution/models.py
src/control_plane/provider_execution/service.py
src/control_plane/provider_execution/store.py
src/control_plane/routes/approval.py
src/control_plane/routes/artifacts.py
src/control_plane/templates/approval_detail.html
src/control_plane/templates/approval_done.html
src/control_plane/templates/approval_not_found.html
src/control_plane/templates/approval_unavailable.html
src/registry/tools/provider_execution.py
src/services/provider_execution_runtime.py
tests/control_plane/provider_execution/__init__.py
tests/control_plane/provider_execution/conftest.py
tests/control_plane/provider_execution/test_approval_routes.py
tests/control_plane/provider_execution/test_browser_sessions.py
tests/control_plane/provider_execution/test_label_downloads.py
tests/control_plane/provider_execution/test_service.py
tests/control_plane/provider_execution/test_store.py
tests/services/test_batch_engine_provider_mode.py
tests/services/test_provider_execution_runtime.py
```

Modify:

```text
src/control_plane/app.py
src/control_plane/config.py
src/hosted_mcp/server.py
src/registry/tools/public.py
src/services/batch_engine.py
src/services/batch_executor.py
tests/control_plane/test_app_auth.py
tests/hosted/test_hosted_mcp_registry.py
tests/registry/test_catalog.py
tests/registry/test_export.py
tests/provider_adapters/test_projections.py
generated/provider_artifacts/claude_remote_mcp_public_tools.json
generated/provider_artifacts/openai_apps_public_tools.json
generated/provider_artifacts/registry.json
```

Do not modify:

```text
src/control_plane/relay/lifecycle.py
src/control_plane/relay/protocol.py
src/control_plane/relay/session_store.py
src/control_plane/relay/version_gate.py
src/control_plane/retention/
src/control_plane/audit/authorization_ledger.py
src/control_plane/audit/models.py
src/control_plane/redis_keys.py
src/control_plane/request_controls.py
src/control_plane/result_projection.py
shipagent-frontend/
src-tauri/
```

Plan 7 consumes those adjacent files through public APIs only.

---

### Task 1: Provider Execution Registry Schemas

**Files:**
- Create: `src/registry/tools/provider_execution.py`
- Modify: `src/registry/tools/public.py`
- Modify: `tests/registry/test_catalog.py`
- Modify: `tests/registry/test_export.py`
- Modify: `tests/hosted/test_hosted_mcp_registry.py`
- Modify by generator only: `generated/provider_artifacts/claude_remote_mcp_public_tools.json`
- Modify by generator only: `generated/provider_artifacts/openai_apps_public_tools.json`
- Modify by generator only: `generated/provider_artifacts/registry.json`

- [ ] **Step 1: Write failing registry tests for approval, execution, status, and artifact schemas**

Append these tests to `tests/registry/test_catalog.py` after the Plan 6 public-scope tests.

```python
def test_prepare_shipments_output_contains_provider_approval_fields():
    tool = next(tool for tool in public_tools() if tool.name == "prepare_shipments")
    props = tool.output_schema["properties"]

    assert {"status", "source_origin", "preview_ref", "summary"}.issubset(props)
    assert "approval_request_ref" in props
    assert "approval_url" in props
    assert "widget_meta" in props
    assert "preview_rows" not in props
    assert "shipment_source" not in props


def test_execute_shipments_accepts_approval_request_ref_and_idempotency_key():
    tool = next(tool for tool in public_tools() if tool.name == "execute_shipments")

    assert set(tool.input_schema["properties"]) == {
        "approval_request_ref",
        "idempotency_key",
    }
    assert tool.input_schema["required"] == [
        "approval_request_ref",
        "idempotency_key",
    ]
    assert "confirmation_token" not in tool.input_schema["properties"]
    assert set(tool.output_schema["properties"]) >= {
        "status",
        "job_ref",
        "poll_after_ms",
        "reason",
        "terminal",
        "message",
    }


def test_job_status_and_label_download_use_provider_references_only():
    status_tool = next(tool for tool in public_tools() if tool.name == "get_job_status")
    label_tool = next(tool for tool in public_tools() if tool.name == "create_label_download")

    assert set(status_tool.input_schema["properties"]) == {"job_ref"}
    assert status_tool.input_schema["required"] == ["job_ref"]
    assert "job_id" not in status_tool.input_schema["properties"]
    assert set(label_tool.input_schema["properties"]) == {"job_ref"}
    assert label_tool.input_schema["required"] == ["job_ref"]
    assert "job_id" not in label_tool.input_schema["properties"]


def test_provider_artifact_schema_is_one_job_level_action():
    tool = next(tool for tool in public_tools() if tool.name == "create_label_download")
    props = tool.output_schema["properties"]

    assert {"status", "download_url", "expires_at"}.issubset(props)
    assert "download_urls" not in props
    assert "label_paths" not in props
    assert "tracking_numbers" not in props
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py -v -k "approval_fields or approval_request_ref or provider_references_only or job_level_action"
```

Expected: FAIL because the current public contracts still expose `preview_id`, `confirmation_token`, `job_id`, and `download_url` without approval/job-ref semantics.

- [ ] **Step 3: Add reusable provider execution schema helpers**

Create `src/registry/tools/provider_execution.py` with this complete content.

```python
from __future__ import annotations

from typing import Any

from src.registry.tools.schema import object_schema


def provider_failure_properties() -> dict[str, Any]:
    return {
        "reason": {
            "type": "string",
            "enum": [
                "approval_expired",
                "approval_pending",
                "approval_rejected",
                "artifact_not_ready",
                "download_reference_expired",
                "grant_consumed",
                "preview_changed",
                "processing_unknown",
                "repeated_tool_call",
                "target_offline",
                "target_update_required",
            ],
        },
        "terminal": {"type": "boolean"},
        "message": {"type": "string"},
    }


def provider_summary_schema() -> dict[str, Any]:
    return object_schema(
        {
            "shipment_count": {"type": "integer", "minimum": 0},
            "warning_count": {"type": "integer", "minimum": 0},
            "failed_count": {"type": "integer", "minimum": 0},
            "needs_review_count": {"type": "integer", "minimum": 0},
            "not_started_count": {"type": "integer", "minimum": 0},
            "total_charge": {"type": "number", "minimum": 0},
            "currency": {"type": "string", "minLength": 3, "maxLength": 3},
        },
        ["shipment_count", "warning_count", "total_charge", "currency"],
    )


def widget_meta_schema() -> dict[str, Any]:
    return object_schema(
        {
            "approval_request_ref": {"type": "string", "minLength": 8, "maxLength": 128},
            "execute_tool": {"type": "string", "const": "execute_shipments"},
            "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
            "preview_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        },
        ["approval_request_ref", "execute_tool", "idempotency_key", "preview_hash"],
    )


def prepare_shipments_output_schema() -> dict[str, Any]:
    return object_schema(
        {
            "status": {
                "type": "string",
                "enum": ["preview_ready", "blocked", "unavailable"],
            },
            "source_origin": {
                "type": "string",
                "enum": ["one_off", "active_source_selection", "existing_batch"],
            },
            "preview_ref": {"type": "string", "minLength": 8, "maxLength": 128},
            "approval_request_ref": {"type": "string", "minLength": 8, "maxLength": 128},
            "approval_url": {"type": "string", "format": "uri"},
            "expires_at": {"type": "string", "format": "date-time"},
            "summary": provider_summary_schema(),
            "widget_meta": widget_meta_schema(),
            **provider_failure_properties(),
        },
        ["status", "source_origin", "preview_ref", "summary"],
    )


def execute_shipments_input_schema() -> dict[str, Any]:
    return object_schema(
        {
            "approval_request_ref": {
                "type": "string",
                "minLength": 8,
                "maxLength": 128,
                "description": "Opaque Approval Request reference returned by prepare_shipments.",
            },
            "idempotency_key": {
                "type": "string",
                "minLength": 8,
                "maxLength": 128,
                "description": "Client idempotency key bound to the approved preview.",
            },
        },
        ["approval_request_ref", "idempotency_key"],
    )


def execute_shipments_output_schema() -> dict[str, Any]:
    return object_schema(
        {
            "status": {
                "type": "string",
                "enum": [
                    "approval_pending",
                    "blocked",
                    "processing",
                    "processing_unknown",
                    "unavailable",
                ],
            },
            "job_ref": {"type": "string", "minLength": 8, "maxLength": 128},
            "poll_after_ms": {"type": "integer", "minimum": 250},
            **provider_failure_properties(),
        },
        ["status"],
    )


def job_status_input_schema() -> dict[str, Any]:
    return object_schema(
        {
            "job_ref": {
                "type": "string",
                "minLength": 8,
                "maxLength": 128,
                "description": "Opaque job reference returned by execute_shipments.",
            }
        },
        ["job_ref"],
    )


def job_status_output_schema() -> dict[str, Any]:
    return object_schema(
        {
            "status": {
                "type": "string",
                "enum": [
                    "processing",
                    "processing_unknown",
                    "completed",
                    "completed_with_warnings",
                    "failed",
                    "needs_review",
                    "blocked",
                    "unavailable",
                ],
            },
            "job_ref": {"type": "string", "minLength": 8, "maxLength": 128},
            "source_origin": {
                "type": "string",
                "enum": ["one_off", "active_source_selection", "existing_batch"],
            },
            "summary": provider_summary_schema(),
            "tracking_number": {"type": "string"},
            "artifact_ready": {"type": "boolean"},
            **provider_failure_properties(),
        },
        ["status", "job_ref"],
    )


def label_download_input_schema() -> dict[str, Any]:
    return job_status_input_schema()


def label_download_output_schema() -> dict[str, Any]:
    return object_schema(
        {
            "status": {
                "type": "string",
                "enum": ["ready", "blocked", "unavailable"],
            },
            "download_url": {"type": "string", "format": "uri"},
            "expires_at": {"type": "string", "format": "date-time"},
            **provider_failure_properties(),
        },
        ["status"],
    )
```

- [ ] **Step 4: Wire public tools to the new schemas**

In `src/registry/tools/public.py`, add these imports below the Plan 6 `prepare_shipments_input_schema` import.

```python
from src.registry.tools.provider_execution import (
    execute_shipments_input_schema,
    execute_shipments_output_schema,
    job_status_input_schema,
    job_status_output_schema,
    label_download_input_schema,
    label_download_output_schema,
    prepare_shipments_output_schema,
)
```

Update the `prepare_shipments` contract to use:

```python
        prepare_shipments_input_schema(),
        prepare_shipments_output_schema(),
```

Update the `execute_shipments` contract to use:

```python
        execute_shipments_input_schema(),
        execute_shipments_output_schema(),
```

Update the `get_job_status` contract to use:

```python
        job_status_input_schema(),
        job_status_output_schema(),
```

Update the `create_label_download` contract to use:

```python
        label_download_input_schema(),
        label_download_output_schema(),
```

- [ ] **Step 5: Run schema tests**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py tests/registry/test_export.py tests/hosted/test_hosted_mcp_registry.py -v -k "approval_fields or approval_request_ref or provider_references_only or job_level_action or registry_to_json_dict or identity_fields"
```

Expected: PASS after Plan 2 and Plan 6 registry tests have been reconciled.

- [ ] **Step 6: Regenerate provider artifacts**

Run:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: generator exits 0 and artifact drift test PASS.

- [ ] **Step 7: Commit registry schema changes**

```bash
git add src/registry/tools/provider_execution.py src/registry/tools/public.py tests/registry/test_catalog.py tests/registry/test_export.py tests/hosted/test_hosted_mcp_registry.py generated/provider_artifacts/claude_remote_mcp_public_tools.json generated/provider_artifacts/openai_apps_public_tools.json generated/provider_artifacts/registry.json
git commit -m "feat: define provider execution approval schemas"
```

---

### Task 2: Provider Execution Records And Store

**Files:**
- Create: `src/control_plane/provider_execution/__init__.py`
- Create: `src/control_plane/provider_execution/models.py`
- Create: `src/control_plane/provider_execution/store.py`
- Create: `tests/control_plane/provider_execution/conftest.py`
- Create: `tests/control_plane/provider_execution/test_store.py`

- [ ] **Step 1: Add fake Redis and store tests**

Create `tests/control_plane/provider_execution/conftest.py`:

```python
from __future__ import annotations

import time

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.expiry: dict[str, float] = {}

    async def get(self, key: str):
        if key in self.expiry and time.monotonic() > self.expiry[key]:
            self.values.pop(key, None)
            self.ttls.pop(key, None)
            self.expiry.pop(key, None)
            return None
        return self.values.get(key)

    async def set(self, key: str, value, *, ex: int | None = None, nx: bool = False):
        if nx and await self.get(key) is not None:
            return False
        self.values[key] = value.encode("utf-8") if isinstance(value, str) else value
        if ex is not None:
            self.ttls[key] = ex
            self.expiry[key] = time.monotonic() + ex
        return True

    async def delete(self, key: str):
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        self.expiry.pop(key, None)
        return 1 if existed else 0


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
```

Create `tests/control_plane/provider_execution/test_store.py`:

```python
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.provider_execution.models import (
    ApprovalRequestState,
    ExecutionGrantState,
    PreviewBinding,
    ProviderExecutionStoreError,
)
from src.control_plane.provider_execution.store import ProviderExecutionStore
from src.control_plane.redis_keys import RedisKey, RedisTtl


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def binding(**overrides) -> PreviewBinding:
    base = {
        "account_id": "acct-1",
        "provider_connection_id": "pc-1",
        "execution_target_id": "target-1",
        "execution_target_fingerprint_hash": sha256_hex("target-fingerprint"),
        "preview_ref": "preview_ref_1",
        "preview_hash": sha256_hex("preview"),
        "purchase_scope_hash": sha256_hex("purchase-scope"),
        "source_checksum": sha256_hex("source"),
        "row_set_hash": sha256_hex("rows"),
        "selected_rate_hash": sha256_hex("rate"),
        "authorized_amount_minor": 1299,
        "currency": "USD",
        "source_origin": "active_source_selection",
        "idempotency_key": "idem-prepare-1",
        "expires_at": datetime.now(UTC) + timedelta(minutes=15),
    }
    base.update(overrides)
    return PreviewBinding(**base)


@pytest.mark.asyncio
async def test_create_approval_request_uses_public_locator_not_internal_id(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "fixedlocator",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )

    result = await store.create_approval_request(
        binding=binding(),
        redacted_summary={"shipment_count": 3, "total_charge": 12.99, "currency": "USD"},
        channel="claude_approval_page",
    )

    assert result.approval_request_ref.startswith("apr_")
    assert "fixedlocator" in result.approval_url
    assert result.approval_request_ref not in result.approval_url
    locator_hash = sha256_hex("fixedlocator")
    assert RedisKey.approval_locator(locator_hash) in fake_redis.values
    assert fake_redis.ttls[RedisKey.approval_request(result.approval_request_ref)] == RedisTtl.APPROVAL_REQUEST_SECONDS


@pytest.mark.asyncio
async def test_openai_prepare_creates_approved_widget_private_grant(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "openai",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )

    result = await store.create_approval_request(
        binding=binding(idempotency_key="idem-openai"),
        redacted_summary={"shipment_count": 1, "total_charge": 12.99, "currency": "USD"},
        channel="openai_widget",
    )
    grant = await store.get_grant(result.approval_request_ref)

    assert grant is not None
    assert grant.state is ExecutionGrantState.APPROVED
    assert grant.idempotency_key == "idem-openai"


@pytest.mark.asyncio
async def test_claude_approval_creates_server_side_grant(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "claude",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    created = await store.create_approval_request(
        binding=binding(),
        redacted_summary={"shipment_count": 2, "total_charge": 12.99, "currency": "USD"},
        channel="claude_approval_page",
    )

    approved = await store.approve_from_locator(
        public_locator="claude",
        account_id="acct-1",
        approving_subject_hash=sha256_hex("auth0|owner-1"),
    )
    grant = await store.get_grant(created.approval_request_ref)

    assert approved.state is ApprovalRequestState.APPROVED
    assert grant is not None
    assert grant.state is ExecutionGrantState.APPROVED
    assert grant.approving_subject_hash == sha256_hex("auth0|owner-1")


@pytest.mark.asyncio
async def test_reserve_release_and_consume_grant_state_machine(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "claude",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    created = await store.create_approval_request(
        binding=binding(idempotency_key="idem-execute"),
        redacted_summary={"shipment_count": 2, "total_charge": 12.99, "currency": "USD"},
        channel="openai_widget",
    )

    reserved = await store.reserve_grant(
        approval_request_ref=created.approval_request_ref,
        account_id="acct-1",
        provider_connection_id="pc-1",
        idempotency_key="idem-execute",
    )
    released = await store.release_reserved_grant(created.approval_request_ref)
    reserved_again = await store.reserve_grant(
        approval_request_ref=created.approval_request_ref,
        account_id="acct-1",
        provider_connection_id="pc-1",
        idempotency_key="idem-execute",
    )
    consumed = await store.consume_reserved_grant(
        approval_request_ref=created.approval_request_ref,
        job_ref="jobref-1",
    )

    assert reserved.state is ExecutionGrantState.RESERVED
    assert released.state is ExecutionGrantState.APPROVED
    assert reserved_again.state is ExecutionGrantState.RESERVED
    assert consumed.state is ExecutionGrantState.CONSUMED
    assert consumed.job_ref == "jobref-1"


@pytest.mark.asyncio
async def test_grant_rejects_wrong_connection_or_idempotency_key(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "openai",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    created = await store.create_approval_request(
        binding=binding(idempotency_key="idem-1"),
        redacted_summary={"shipment_count": 1, "total_charge": 12.99, "currency": "USD"},
        channel="openai_widget",
    )

    with pytest.raises(ProviderExecutionStoreError, match="provider_connection_mismatch"):
        await store.reserve_grant(
            approval_request_ref=created.approval_request_ref,
            account_id="acct-1",
            provider_connection_id="pc-2",
            idempotency_key="idem-1",
        )

    with pytest.raises(ProviderExecutionStoreError, match="idempotency_key_mismatch"):
        await store.reserve_grant(
            approval_request_ref=created.approval_request_ref,
            account_id="acct-1",
            provider_connection_id="pc-1",
            idempotency_key="different",
        )
```

- [ ] **Step 2: Run store tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.provider_execution'`.

- [ ] **Step 3: Create provider execution models**

Create `src/control_plane/provider_execution/__init__.py`:

```python
"""Provider execution approval flow primitives."""
```

Create `src/control_plane/provider_execution/models.py` with this complete content.

```python
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SourceOrigin = Literal["one_off", "active_source_selection", "existing_batch"]
ApprovalChannel = Literal["openai_widget", "claude_approval_page"]


class ApprovalRequestState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ExecutionGrantState(StrEnum):
    APPROVED = "approved"
    RESERVED = "reserved"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class LabelDownloadState(StrEnum):
    READY = "ready"
    STREAMING = "streaming"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class ProviderExecutionStoreError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


class PreviewBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    provider_connection_id: str
    execution_target_id: str
    execution_target_fingerprint_hash: str
    preview_ref: str
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    purchase_scope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    row_set_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_rate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    authorized_amount_minor: int = Field(ge=0)
    currency: str
    source_origin: SourceOrigin
    idempotency_key: str
    expires_at: datetime

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        normalized = value.upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO currency code")
        return normalized


class ApprovalRequestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_request_ref: str
    public_locator_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    channel: ApprovalChannel
    state: ApprovalRequestState
    binding: PreviewBinding
    redacted_summary: dict[str, object]
    created_at: datetime
    updated_at: datetime
    approving_subject_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ExecutionGrantRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_request_ref: str
    state: ExecutionGrantState
    binding: PreviewBinding
    idempotency_key: str
    approving_subject_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    job_ref: str | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalCreateResult(BaseModel):
    approval_request_ref: str
    approval_url: str
    expires_at: datetime
```

- [ ] **Step 4: Create the Redis-backed store**

Create `src/control_plane/provider_execution/store.py` with this complete content.

```python
from __future__ import annotations

import secrets
from datetime import datetime

from src.control_plane.provider_execution.models import (
    ApprovalChannel,
    ApprovalCreateResult,
    ApprovalRequestRecord,
    ApprovalRequestState,
    ExecutionGrantRecord,
    ExecutionGrantState,
    PreviewBinding,
    ProviderExecutionStoreError,
    sha256_text,
    utc_now,
)
from src.control_plane.redis_keys import RedisKey, RedisTtl


def _decode_json(raw) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return ApprovalRequestRecord.model_validate_json(raw).model_dump(mode="json")


def _decode_approval(raw) -> ApprovalRequestRecord:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return ApprovalRequestRecord.model_validate_json(raw)


def _decode_grant(raw) -> ExecutionGrantRecord:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return ExecutionGrantRecord.model_validate_json(raw)


class ProviderExecutionStore:
    def __init__(
        self,
        redis_client,
        *,
        public_base_url: str,
        token_urlsafe=secrets.token_urlsafe,
        now_fn=utc_now,
    ) -> None:
        self.redis = redis_client
        self.public_base_url = public_base_url.rstrip("/")
        self._token_urlsafe = token_urlsafe
        self._now = now_fn

    async def create_approval_request(
        self,
        *,
        binding: PreviewBinding,
        redacted_summary: dict[str, object],
        channel: ApprovalChannel,
    ) -> ApprovalCreateResult:
        public_locator = self._token_urlsafe(32)
        approval_request_ref = f"apr_{self._token_urlsafe(24)}"
        now = self._now()
        record = ApprovalRequestRecord(
            approval_request_ref=approval_request_ref,
            public_locator_hash=sha256_text(public_locator),
            channel=channel,
            state=(
                ApprovalRequestState.APPROVED
                if channel == "openai_widget"
                else ApprovalRequestState.PENDING
            ),
            binding=binding,
            redacted_summary=redacted_summary,
            created_at=now,
            updated_at=now,
        )
        created = await self.redis.set(
            RedisKey.approval_request(approval_request_ref),
            record.model_dump_json(),
            ex=RedisTtl.APPROVAL_REQUEST_SECONDS,
            nx=True,
        )
        if not created:
            raise ProviderExecutionStoreError("approval_request_collision")
        await self.redis.set(
            RedisKey.approval_locator(record.public_locator_hash),
            approval_request_ref,
            ex=RedisTtl.APPROVAL_LOCATOR_SECONDS,
            nx=True,
        )
        if channel == "openai_widget":
            await self._save_grant(
                ExecutionGrantRecord(
                    approval_request_ref=approval_request_ref,
                    state=ExecutionGrantState.APPROVED,
                    binding=binding,
                    idempotency_key=binding.idempotency_key,
                    created_at=now,
                    updated_at=now,
                )
            )
        return ApprovalCreateResult(
            approval_request_ref=approval_request_ref,
            approval_url=f"{self.public_base_url}/approval/{public_locator}",
            expires_at=binding.expires_at,
        )

    async def get_approval(self, approval_request_ref: str) -> ApprovalRequestRecord | None:
        raw = await self.redis.get(RedisKey.approval_request(approval_request_ref))
        if raw is None:
            return None
        return _decode_approval(raw)

    async def get_approval_by_locator(
        self,
        public_locator: str,
    ) -> ApprovalRequestRecord | None:
        ref = await self.redis.get(RedisKey.approval_locator(sha256_text(public_locator)))
        if ref is None:
            return None
        if isinstance(ref, bytes):
            ref = ref.decode("utf-8")
        return await self.get_approval(str(ref))

    async def approve_from_locator(
        self,
        *,
        public_locator: str,
        account_id: str,
        approving_subject_hash: str,
    ) -> ApprovalRequestRecord:
        record = await self.get_approval_by_locator(public_locator)
        if record is None:
            raise ProviderExecutionStoreError("approval_not_found")
        if record.binding.account_id != account_id:
            raise ProviderExecutionStoreError("account_mismatch")
        if record.state is not ApprovalRequestState.PENDING:
            raise ProviderExecutionStoreError(f"approval_{record.state.value}")
        now = self._now()
        approved = record.model_copy(
            update={
                "state": ApprovalRequestState.APPROVED,
                "approving_subject_hash": approving_subject_hash,
                "updated_at": now,
            }
        )
        await self._save_approval(approved)
        await self._save_grant(
            ExecutionGrantRecord(
                approval_request_ref=approved.approval_request_ref,
                state=ExecutionGrantState.APPROVED,
                binding=approved.binding,
                idempotency_key=approved.binding.idempotency_key,
                approving_subject_hash=approving_subject_hash,
                created_at=now,
                updated_at=now,
            )
        )
        await self.redis.delete(RedisKey.approval_locator(record.public_locator_hash))
        return approved

    async def reject_from_locator(
        self,
        *,
        public_locator: str,
        account_id: str,
        approving_subject_hash: str,
    ) -> ApprovalRequestRecord:
        record = await self.get_approval_by_locator(public_locator)
        if record is None:
            raise ProviderExecutionStoreError("approval_not_found")
        if record.binding.account_id != account_id:
            raise ProviderExecutionStoreError("account_mismatch")
        rejected = record.model_copy(
            update={
                "state": ApprovalRequestState.REJECTED,
                "approving_subject_hash": approving_subject_hash,
                "updated_at": self._now(),
            }
        )
        await self._save_approval(rejected)
        await self.redis.delete(RedisKey.approval_locator(record.public_locator_hash))
        return rejected

    async def get_grant(self, approval_request_ref: str) -> ExecutionGrantRecord | None:
        raw = await self.redis.get(RedisKey.execution_grant(approval_request_ref))
        if raw is None:
            return None
        return _decode_grant(raw)

    async def reserve_grant(
        self,
        *,
        approval_request_ref: str,
        account_id: str,
        provider_connection_id: str,
        idempotency_key: str,
    ) -> ExecutionGrantRecord:
        grant = await self.get_grant(approval_request_ref)
        if grant is None:
            approval = await self.get_approval(approval_request_ref)
            if approval is not None and approval.state is ApprovalRequestState.PENDING:
                raise ProviderExecutionStoreError("approval_pending")
            raise ProviderExecutionStoreError("grant_not_found")
        self._validate_grant_binding(
            grant,
            account_id=account_id,
            provider_connection_id=provider_connection_id,
            idempotency_key=idempotency_key,
        )
        if grant.state is ExecutionGrantState.CONSUMED:
            if grant.job_ref:
                return grant
            raise ProviderExecutionStoreError("grant_consumed")
        if grant.state is not ExecutionGrantState.APPROVED:
            raise ProviderExecutionStoreError(f"grant_{grant.state.value}")
        reserved = grant.model_copy(
            update={"state": ExecutionGrantState.RESERVED, "updated_at": self._now()}
        )
        await self._save_grant(reserved)
        return reserved

    async def release_reserved_grant(
        self,
        approval_request_ref: str,
    ) -> ExecutionGrantRecord:
        grant = await self.get_grant(approval_request_ref)
        if grant is None:
            raise ProviderExecutionStoreError("grant_not_found")
        if grant.state is not ExecutionGrantState.RESERVED:
            raise ProviderExecutionStoreError(f"grant_{grant.state.value}")
        released = grant.model_copy(
            update={"state": ExecutionGrantState.APPROVED, "updated_at": self._now()}
        )
        await self._save_grant(released)
        return released

    async def consume_reserved_grant(
        self,
        *,
        approval_request_ref: str,
        job_ref: str,
    ) -> ExecutionGrantRecord:
        grant = await self.get_grant(approval_request_ref)
        if grant is None:
            raise ProviderExecutionStoreError("grant_not_found")
        if grant.state is ExecutionGrantState.CONSUMED and grant.job_ref == job_ref:
            return grant
        if grant.state is not ExecutionGrantState.RESERVED:
            raise ProviderExecutionStoreError(f"grant_{grant.state.value}")
        consumed = grant.model_copy(
            update={
                "state": ExecutionGrantState.CONSUMED,
                "job_ref": job_ref,
                "updated_at": self._now(),
            }
        )
        await self._save_grant(consumed)
        return consumed

    async def _save_approval(self, record: ApprovalRequestRecord) -> None:
        await self.redis.set(
            RedisKey.approval_request(record.approval_request_ref),
            record.model_dump_json(),
            ex=RedisTtl.APPROVAL_REQUEST_SECONDS,
        )

    async def _save_grant(self, record: ExecutionGrantRecord) -> None:
        await self.redis.set(
            RedisKey.execution_grant(record.approval_request_ref),
            record.model_dump_json(),
            ex=RedisTtl.EXECUTION_GRANT_SECONDS,
        )

    def _validate_grant_binding(
        self,
        grant: ExecutionGrantRecord,
        *,
        account_id: str,
        provider_connection_id: str,
        idempotency_key: str,
    ) -> None:
        binding = grant.binding
        if binding.account_id != account_id:
            raise ProviderExecutionStoreError("account_mismatch")
        if binding.provider_connection_id != provider_connection_id:
            raise ProviderExecutionStoreError("provider_connection_mismatch")
        if grant.idempotency_key != idempotency_key:
            raise ProviderExecutionStoreError("idempotency_key_mismatch")
```

During implementation, replace the read-modify-write state transitions above with Redis `WATCH` or Lua if concurrent tests expose a race. The public behavior and tests stay the same: approval, rejection, reservation, release, and consumption must be atomic from the caller's perspective.

- [ ] **Step 5: Run store tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_store.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit provider execution store**

```bash
git add src/control_plane/provider_execution tests/control_plane/provider_execution
git commit -m "feat: add provider execution approval store"
```

---

### Task 3: Approval Browser Sessions And CSRF

**Files:**
- Create: `src/control_plane/provider_execution/browser_sessions.py`
- Create: `tests/control_plane/provider_execution/test_browser_sessions.py`
- Modify: `src/control_plane/config.py`

- [ ] **Step 1: Write failing browser session tests**

Create `tests/control_plane/provider_execution/test_browser_sessions.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.control_plane.provider_execution.browser_sessions import (
    ApprovalBrowserSession,
    ApprovalBrowserSessionStore,
    BrowserSessionError,
)
from src.control_plane.redis_keys import RedisKey, RedisTtl


@pytest.mark.asyncio
async def test_browser_session_cookie_is_opaque_and_server_state_is_in_redis(fake_redis):
    store = ApprovalBrowserSessionStore(
        fake_redis,
        secret="test-secret",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
        token_urlsafe=lambda _size: "sid-fixed",
    )

    cookie = await store.create(
        account_id="acct-1",
        auth0_subject="auth0|owner-1",
    )

    assert "acct-1" not in cookie
    assert "auth0" not in cookie
    assert RedisKey.approval_browser_session("sid-fixed") in fake_redis.values
    assert fake_redis.ttls[RedisKey.approval_browser_session("sid-fixed")] == RedisTtl.APPROVAL_BROWSER_SESSION_SECONDS


@pytest.mark.asyncio
async def test_browser_session_round_trips_and_csrf_is_single_session_bound(fake_redis):
    store = ApprovalBrowserSessionStore(
        fake_redis,
        secret="test-secret",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
        token_urlsafe=lambda size: "csrf-fixed" if size == 24 else "sid-fixed",
    )

    cookie = await store.create(
        account_id="acct-1",
        auth0_subject="auth0|owner-1",
    )
    session = await store.load(cookie)

    assert session == ApprovalBrowserSession(
        session_id="sid-fixed",
        account_id="acct-1",
        auth0_subject="auth0|owner-1",
        csrf_token="csrf-fixed",
        created_at=datetime(2026, 6, 30, tzinfo=UTC),
    )
    assert await store.validate_csrf(cookie, "csrf-fixed") == session
    with pytest.raises(BrowserSessionError, match="csrf_mismatch"):
        await store.validate_csrf(cookie, "wrong")
```

- [ ] **Step 2: Run browser session tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_browser_sessions.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `browser_sessions`.

- [ ] **Step 3: Add approval browser configuration**

In `src/control_plane/config.py`, add these fields to `ControlPlaneSettings` after `auth0_provider_clients`:

```python
    approval_session_secret: str = Field(default="", min_length=0)
    approval_cookie_name: str = "shipagent_approval_session"
    auth0_web_client_id: str = ""
    auth0_web_client_secret: str = ""
```

Plan 10 should adversarially test that production startup rejects an empty `approval_session_secret`. For this slice, the route constructor in Task 4 raises when the secret is empty.

- [ ] **Step 4: Implement encrypted opaque browser sessions**

Create `src/control_plane/provider_execution/browser_sessions.py` with this complete content.

```python
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict

from src.control_plane.provider_execution.models import utc_now
from src.control_plane.redis_keys import RedisKey, RedisTtl


class BrowserSessionError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ApprovalBrowserSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    account_id: str
    auth0_subject: str
    csrf_token: str
    created_at: datetime


def _fernet_from_secret(secret: str) -> Fernet:
    if not secret:
        raise BrowserSessionError("missing_session_secret")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


class ApprovalBrowserSessionStore:
    def __init__(
        self,
        redis_client,
        *,
        secret: str,
        now_fn=utc_now,
        token_urlsafe=secrets.token_urlsafe,
    ) -> None:
        self.redis = redis_client
        self._fernet = _fernet_from_secret(secret)
        self._now = now_fn
        self._token_urlsafe = token_urlsafe

    async def create(self, *, account_id: str, auth0_subject: str) -> str:
        session_id = self._token_urlsafe(32)
        session = ApprovalBrowserSession(
            session_id=session_id,
            account_id=account_id,
            auth0_subject=auth0_subject,
            csrf_token=self._token_urlsafe(24),
            created_at=self._now(),
        )
        await self.redis.set(
            RedisKey.approval_browser_session(session_id),
            session.model_dump_json(),
            ex=RedisTtl.APPROVAL_BROWSER_SESSION_SECONDS,
        )
        return self._fernet.encrypt(session_id.encode("utf-8")).decode("utf-8")

    async def load(self, encrypted_cookie: str | None) -> ApprovalBrowserSession | None:
        if not encrypted_cookie:
            return None
        try:
            session_id = self._fernet.decrypt(
                encrypted_cookie.encode("utf-8")
            ).decode("utf-8")
        except InvalidToken:
            raise BrowserSessionError("invalid_session_cookie") from None
        raw = await self.redis.get(RedisKey.approval_browser_session(session_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ApprovalBrowserSession.model_validate_json(raw)

    async def validate_csrf(
        self,
        encrypted_cookie: str | None,
        csrf_token: str | None,
    ) -> ApprovalBrowserSession:
        session = await self.load(encrypted_cookie)
        if session is None:
            raise BrowserSessionError("missing_session")
        if not csrf_token or csrf_token != session.csrf_token:
            raise BrowserSessionError("csrf_mismatch")
        return session
```

- [ ] **Step 5: Run browser session tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_browser_sessions.py tests/control_plane/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit browser session support**

```bash
git add src/control_plane/config.py src/control_plane/provider_execution/browser_sessions.py tests/control_plane/provider_execution/test_browser_sessions.py
git commit -m "feat: add approval browser sessions"
```

---

### Task 4: Claude Approval Surface Routes

**Files:**
- Create: `src/control_plane/routes/approval.py`
- Create: `src/control_plane/templates/approval_detail.html`
- Create: `src/control_plane/templates/approval_done.html`
- Create: `src/control_plane/templates/approval_not_found.html`
- Create: `src/control_plane/templates/approval_unavailable.html`
- Create: `tests/control_plane/provider_execution/test_approval_routes.py`
- Modify: `src/control_plane/app.py`
- Modify: `tests/control_plane/test_app_auth.py`

- [ ] **Step 1: Write approval route tests**

Create `tests/control_plane/provider_execution/test_approval_routes.py`:

```python
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.control_plane.provider_execution.browser_sessions import (
    ApprovalBrowserSessionStore,
)
from src.control_plane.provider_execution.models import PreviewBinding
from src.control_plane.provider_execution.store import ProviderExecutionStore
from src.control_plane.routes.approval import build_approval_router


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def binding() -> PreviewBinding:
    return PreviewBinding(
        account_id="acct-1",
        provider_connection_id="pc-1",
        execution_target_id="target-1",
        execution_target_fingerprint_hash=sha256_hex("target-fingerprint"),
        preview_ref="preview_ref_1",
        preview_hash=sha256_hex("preview"),
        purchase_scope_hash=sha256_hex("purchase-scope"),
        source_checksum=sha256_hex("source"),
        row_set_hash=sha256_hex("rows"),
        selected_rate_hash=sha256_hex("rate"),
        authorized_amount_minor=1299,
        currency="USD",
        source_origin="active_source_selection",
        idempotency_key="idem-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


class DetailProvider:
    def __init__(self, online: bool = True) -> None:
        self.online = online

    async def fetch_approval_detail(self, approval):
        if not self.online:
            return None
        return {
            "rows": [
                {
                    "ordinal": 1,
                    "recipient": "Jane Doe",
                    "city": "Boston",
                    "service": "UPS Ground",
                    "amount": "$12.99",
                }
            ],
            "preview_hash": approval.binding.preview_hash,
        }


async def build_client(fake_redis, *, online: bool = True):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "locator",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    created = await store.create_approval_request(
        binding=binding(),
        redacted_summary={"shipment_count": 1, "total_charge": 12.99, "currency": "USD"},
        channel="claude_approval_page",
    )
    sessions = ApprovalBrowserSessionStore(
        fake_redis,
        secret="test-secret",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
        token_urlsafe=lambda size: "csrf" if size == 24 else "browser",
    )
    cookie = await sessions.create(account_id="acct-1", auth0_subject="auth0|owner-1")
    app = FastAPI()
    app.include_router(
        build_approval_router(
            execution_store=store,
            browser_sessions=sessions,
            detail_provider=DetailProvider(online=online),
            cookie_name="shipagent_approval_session",
        )
    )
    return TestClient(app), cookie, created


async def test_detail_page_requires_browser_session(fake_redis):
    client, _cookie, _created = await build_client(fake_redis)

    response = client.get("/approval/locator", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/approval/login")


async def test_detail_page_renders_live_preview_with_no_store_headers(fake_redis):
    client, cookie, _created = await build_client(fake_redis)

    response = client.get(
        "/approval/locator",
        cookies={"shipagent_approval_session": cookie},
    )

    assert response.status_code == 200
    assert "Jane Doe" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "https://" not in response.text


async def test_offline_target_page_cannot_approve(fake_redis):
    client, cookie, _created = await build_client(fake_redis, online=False)

    response = client.get(
        "/approval/locator",
        cookies={"shipagent_approval_session": cookie},
    )

    assert response.status_code == 503
    assert "Approve" not in response.text
    assert "Retry" in response.text


async def test_approve_requires_csrf_and_creates_grant(fake_redis):
    client, cookie, created = await build_client(fake_redis)

    bad = client.post(
        "/approval/locator/approve",
        cookies={"shipagent_approval_session": cookie},
        data={"csrf_token": "wrong"},
    )
    good = client.post(
        "/approval/locator/approve",
        cookies={"shipagent_approval_session": cookie},
        data={"csrf_token": "csrf"},
    )

    assert bad.status_code == 403
    assert good.status_code == 200
    assert "return to Claude" in good.text
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
    )
    grant = await store.get_grant(created.approval_request_ref)
    assert grant is not None
```

- [ ] **Step 2: Run approval route tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_approval_routes.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.routes.approval'`.

- [ ] **Step 3: Add approval templates**

Create `src/control_plane/templates/approval_detail.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Review Shipment Purchase</title>
  <style>
    body { font-family: Inter, system-ui, sans-serif; margin: 0; color: #111827; background: #f8fafc; }
    main { max-width: 920px; margin: 0 auto; padding: 32px 20px; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d1d5db; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; }
    .actions { display: flex; gap: 12px; margin-top: 20px; }
    button { padding: 10px 14px; border: 1px solid #111827; background: #111827; color: white; }
    .reject { background: white; color: #111827; }
  </style>
</head>
<body>
  <main>
    <h1>Review Shipment Purchase</h1>
    <p>Total authorization: {{ total }} {{ currency }}</p>
    <table>
      <thead><tr><th>#</th><th>Recipient</th><th>City</th><th>Service</th><th>Amount</th></tr></thead>
      <tbody>
      {% for row in rows %}
        <tr><td>{{ row.ordinal }}</td><td>{{ row.recipient }}</td><td>{{ row.city }}</td><td>{{ row.service }}</td><td>{{ row.amount }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
    <form class="actions" method="post" action="/approval/{{ locator }}/approve">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <button type="submit">Approve</button>
    </form>
    <form class="actions" method="post" action="/approval/{{ locator }}/reject">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <button class="reject" type="submit">Reject</button>
    </form>
  </main>
</body>
</html>
```

Create `src/control_plane/templates/approval_unavailable.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ShipAgent Unavailable</title></head>
<body><main><h1>ShipAgent Runtime Unavailable</h1><p>The exact execution target that created this preview is offline. Reopen ShipAgent before the request expires.</p><a href="/approval/{{ locator }}">Retry</a></main></body>
</html>
```

Create `src/control_plane/templates/approval_done.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Approval Recorded</title></head>
<body><main><h1>{{ title }}</h1><p>{{ message }}</p></main></body>
</html>
```

Create `src/control_plane/templates/approval_not_found.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Approval Request Not Found</title></head>
<body><main><h1>Approval Request Not Found</h1><p>This request is expired, already used, or unavailable for this account.</p></main></body>
</html>
```

- [ ] **Step 4: Implement approval routes**

Create `src/control_plane/routes/approval.py` with this complete content.

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.control_plane.provider_execution.browser_sessions import (
    ApprovalBrowserSessionStore,
    BrowserSessionError,
)
from src.control_plane.provider_execution.models import sha256_text
from src.control_plane.provider_execution.store import ProviderExecutionStore


TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


class ApprovalDetailProvider(Protocol):
    async def fetch_approval_detail(self, approval) -> dict[str, object] | None: ...


def _headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def build_approval_router(
    *,
    execution_store: ProviderExecutionStore,
    browser_sessions: ApprovalBrowserSessionStore,
    detail_provider: ApprovalDetailProvider,
    cookie_name: str,
) -> APIRouter:
    router = APIRouter()

    @router.get("/approval/login")
    async def login(locator: str):
        return HTMLResponse(
            "<!doctype html><title>Sign in required</title><p>Sign in with ShipAgent to continue.</p>",
            headers=_headers(),
        )

    @router.get("/approval/{locator}")
    async def approval_detail(request: Request, locator: str):
        session = await browser_sessions.load(request.cookies.get(cookie_name))
        if session is None:
            return RedirectResponse(
                f"/approval/login?locator={locator}",
                status_code=303,
                headers=_headers(),
            )
        approval = await execution_store.get_approval_by_locator(locator)
        if approval is None or approval.binding.account_id != session.account_id:
            return TEMPLATES.TemplateResponse(
                request,
                "approval_not_found.html",
                {},
                status_code=404,
                headers=_headers(),
            )
        detail = await detail_provider.fetch_approval_detail(approval)
        if detail is None:
            return TEMPLATES.TemplateResponse(
                request,
                "approval_unavailable.html",
                {"locator": locator},
                status_code=503,
                headers=_headers(),
            )
        if detail.get("preview_hash") != approval.binding.preview_hash:
            return TEMPLATES.TemplateResponse(
                request,
                "approval_not_found.html",
                {},
                status_code=409,
                headers=_headers(),
            )
        return TEMPLATES.TemplateResponse(
            request,
            "approval_detail.html",
            {
                "locator": locator,
                "rows": detail["rows"],
                "total": f"{approval.binding.authorized_amount_minor / 100:.2f}",
                "currency": approval.binding.currency,
                "csrf_token": session.csrf_token,
            },
            headers=_headers(),
        )

    @router.post("/approval/{locator}/approve")
    async def approve(
        request: Request,
        locator: str,
        csrf_token: str = Form(...),
    ):
        try:
            session = await browser_sessions.validate_csrf(
                request.cookies.get(cookie_name),
                csrf_token,
            )
        except BrowserSessionError:
            return HTMLResponse("Forbidden", status_code=403, headers=_headers())
        approval = await execution_store.get_approval_by_locator(locator)
        if approval is None or approval.binding.account_id != session.account_id:
            return TEMPLATES.TemplateResponse(
                request,
                "approval_not_found.html",
                {},
                status_code=404,
                headers=_headers(),
            )
        detail = await detail_provider.fetch_approval_detail(approval)
        if detail is None or detail.get("preview_hash") != approval.binding.preview_hash:
            return TEMPLATES.TemplateResponse(
                request,
                "approval_unavailable.html",
                {"locator": locator},
                status_code=503,
                headers=_headers(),
            )
        await execution_store.approve_from_locator(
            public_locator=locator,
            account_id=session.account_id,
            approving_subject_hash=sha256_text(session.auth0_subject),
        )
        return TEMPLATES.TemplateResponse(
            request,
            "approval_done.html",
            {
                "title": "Approved",
                "message": "Approval recorded. Return to Claude and continue.",
            },
            headers=_headers(),
        )

    @router.post("/approval/{locator}/reject")
    async def reject(
        request: Request,
        locator: str,
        csrf_token: str = Form(...),
    ):
        try:
            session = await browser_sessions.validate_csrf(
                request.cookies.get(cookie_name),
                csrf_token,
            )
        except BrowserSessionError:
            return HTMLResponse("Forbidden", status_code=403, headers=_headers())
        await execution_store.reject_from_locator(
            public_locator=locator,
            account_id=session.account_id,
            approving_subject_hash=sha256_text(session.auth0_subject),
        )
        return TEMPLATES.TemplateResponse(
            request,
            "approval_done.html",
            {
                "title": "Rejected",
                "message": "Request rejected. Return to Claude and prepare a new preview if needed.",
            },
            headers=_headers(),
        )

    return router
```

Task 9 wires real Auth0 code-flow login into `/approval/login`; this task keeps the approval page, session, CSRF, no-store, offline, and approve/reject behavior testable without provider OAuth.

- [ ] **Step 5: Exempt approval browser routes from bearer-token MCP middleware**

In `src/control_plane/app.py`, inside `_require_authorization`, add this branch before the bearer-token check:

```python
        browser_paths = ("/approval", "/artifacts/labels")
        if request.url.path.startswith(browser_paths):
            return await call_next(request)
```

- [ ] **Step 6: Run approval tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_approval_routes.py tests/control_plane/test_app_auth.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit approval surface**

```bash
git add src/control_plane/app.py src/control_plane/routes/approval.py src/control_plane/templates/approval_detail.html src/control_plane/templates/approval_done.html src/control_plane/templates/approval_not_found.html src/control_plane/templates/approval_unavailable.html tests/control_plane/provider_execution/test_approval_routes.py tests/control_plane/test_app_auth.py
git commit -m "feat: add claude approval surface"
```

---

### Task 5: Target Runtime Preview, Exact Binding, Status, And Artifacts

**Files:**
- Create: `src/services/provider_execution_runtime.py`
- Create: `tests/services/test_provider_execution_runtime.py`

- [ ] **Step 1: Write target runtime tests**

Create `tests/services/test_provider_execution_runtime.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.services.provider_execution_runtime import (
    ExactPurchaseDriftError,
    ProviderExecutionRuntime,
    ProviderPreviewResult,
    compute_purchase_scope_hash,
)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_purchase_scope_hash_changes_on_rate_or_amount_drift():
    original = compute_purchase_scope_hash(
        row_set_hash=sha256_hex("rows"),
        source_checksum=sha256_hex("source"),
        selected_rate_hash=sha256_hex("rate-a"),
        authorized_amount_minor=1299,
        currency="USD",
    )
    changed = compute_purchase_scope_hash(
        row_set_hash=sha256_hex("rows"),
        source_checksum=sha256_hex("source"),
        selected_rate_hash=sha256_hex("rate-b"),
        authorized_amount_minor=1299,
        currency="USD",
    )

    assert original != changed


def test_verify_exact_purchase_rejects_lower_cost_drift():
    runtime = ProviderExecutionRuntime(db_session=None, batch_executor=None)
    approved = ProviderPreviewResult(
        preview_ref="preview_ref_1",
        source_origin="one_off",
        execution_target_id="target-1",
        execution_target_fingerprint_hash=sha256_hex("target-fingerprint"),
        preview_hash=sha256_hex("preview"),
        row_set_hash=sha256_hex("rows"),
        source_checksum=sha256_hex("source"),
        selected_rate_hash=sha256_hex("rate"),
        authorized_amount_minor=1299,
        currency="USD",
        redacted_summary={"shipment_count": 1, "total_charge": 12.99, "currency": "USD"},
        approval_detail={"rows": []},
    )
    current = approved.model_copy(update={"authorized_amount_minor": 1099})

    with pytest.raises(ExactPurchaseDriftError, match="authorized_amount_minor"):
        runtime.verify_exact_purchase(approved=approved, current=current)


def test_label_manifest_contains_no_recipient_pii(tmp_path: Path):
    runtime = ProviderExecutionRuntime(db_session=None, batch_executor=None)
    manifest = runtime.build_label_manifest(
        [
            {"ordinal": 1, "tracking_number": "1Z999AA10123456784", "status": "completed", "recipient": "Jane Doe"},
            {"ordinal": 2, "tracking_number": "1Z999AA10123456785", "status": "failed", "recipient": "John Smith"},
        ]
    )

    assert "Jane Doe" not in manifest
    assert "John Smith" not in manifest
    assert "ordinal,tracking_number,status" in manifest
    assert "1Z999AA10123456784" in manifest
```

- [ ] **Step 2: Run target runtime tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_provider_execution_runtime.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.provider_execution_runtime'`.

- [ ] **Step 3: Implement provider execution runtime models and exact binding helpers**

Create `src/services/provider_execution_runtime.py` with this initial content.

```python
from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SourceOrigin = Literal["one_off", "active_source_selection", "existing_batch"]


class ExactPurchaseDriftError(RuntimeError):
    pass


def sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def compute_purchase_scope_hash(
    *,
    row_set_hash: str,
    source_checksum: str,
    selected_rate_hash: str,
    authorized_amount_minor: int,
    currency: str,
) -> str:
    return sha256_json(
        {
            "row_set_hash": row_set_hash,
            "source_checksum": source_checksum,
            "selected_rate_hash": selected_rate_hash,
            "authorized_amount_minor": authorized_amount_minor,
            "currency": currency.upper(),
        }
    )


class ProviderPreviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_ref: str
    source_origin: SourceOrigin
    execution_target_id: str
    execution_target_fingerprint_hash: str
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    row_set_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_rate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    authorized_amount_minor: int = Field(ge=0)
    currency: str
    redacted_summary: dict[str, object]
    approval_detail: dict[str, object]

    @property
    def purchase_scope_hash(self) -> str:
        return compute_purchase_scope_hash(
            row_set_hash=self.row_set_hash,
            source_checksum=self.source_checksum,
            selected_rate_hash=self.selected_rate_hash,
            authorized_amount_minor=self.authorized_amount_minor,
            currency=self.currency,
        )


class ProviderExecutionRuntime:
    def __init__(self, *, db_session: Any, batch_executor: Any) -> None:
        self.db = db_session
        self.batch_executor = batch_executor

    def verify_exact_purchase(
        self,
        *,
        approved: ProviderPreviewResult,
        current: ProviderPreviewResult,
    ) -> None:
        fields = (
            "preview_hash",
            "row_set_hash",
            "source_checksum",
            "selected_rate_hash",
            "authorized_amount_minor",
            "currency",
        )
        for field in fields:
            if getattr(approved, field) != getattr(current, field):
                raise ExactPurchaseDriftError(field)
        if approved.purchase_scope_hash != current.purchase_scope_hash:
            raise ExactPurchaseDriftError("purchase_scope_hash")

    def build_label_manifest(self, rows: list[dict[str, object]]) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["ordinal", "tracking_number", "status"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "ordinal": row.get("ordinal"),
                    "tracking_number": row.get("tracking_number", ""),
                    "status": row.get("status", ""),
                }
            )
        return buffer.getvalue()
```

- [ ] **Step 4: Add runtime method contracts for relay handlers**

Append these method stubs with concrete behavior to `ProviderExecutionRuntime`:

```python
    async def prepare_shipments(self, shipment_source: dict[str, object]) -> ProviderPreviewResult:
        source_type = str(shipment_source["source_type"])
        source_checksum = sha256_json(shipment_source)
        preview_ref = f"preview_ref_{sha256_json({'source': shipment_source})[:16]}"
        row_set_hash = sha256_json({"source_type": source_type, "preview_ref": preview_ref})
        selected_rate_hash = sha256_json({"rate": "selected", "preview_ref": preview_ref})
        authorized_amount_minor = 0
        redacted_summary = {
            "shipment_count": 0,
            "warning_count": 0,
            "total_charge": 0.0,
            "currency": "USD",
        }
        approval_detail = {"rows": [], "preview_hash": sha256_json({"preview_ref": preview_ref})}
        preview_hash = sha256_json(
            {
                "source_checksum": source_checksum,
                "row_set_hash": row_set_hash,
                "selected_rate_hash": selected_rate_hash,
                "authorized_amount_minor": authorized_amount_minor,
                "currency": "USD",
            }
        )
        return ProviderPreviewResult(
            preview_ref=preview_ref,
            source_origin=source_type,  # type: ignore[arg-type]
            execution_target_id="target-1",
            execution_target_fingerprint_hash=sha256_json("target-1"),
            preview_hash=preview_hash,
            row_set_hash=row_set_hash,
            source_checksum=source_checksum,
            selected_rate_hash=selected_rate_hash,
            authorized_amount_minor=authorized_amount_minor,
            currency="USD",
            redacted_summary=redacted_summary,
            approval_detail=approval_detail | {"preview_hash": preview_hash},
        )

    async def get_job_status(self, *, local_job_id: str) -> dict[str, object]:
        if self.db is None:
            return {
                "status": "processing",
                "job_ref": local_job_id,
                "summary": {"shipment_count": 0, "warning_count": 0, "total_charge": 0.0, "currency": "USD"},
                "artifact_ready": False,
            }
        raise RuntimeError("database-backed status is added when wiring the desktop relay handler")
```

During wiring, replace the deterministic zero-row `prepare_shipments()` body with the existing source adapters and `BatchEngine.preview()` calls. Keep the output shape and hash fields identical to the snippet above so approval binding tests remain stable.

- [ ] **Step 5: Run target runtime tests**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_provider_execution_runtime.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit target runtime helpers**

```bash
git add src/services/provider_execution_runtime.py tests/services/test_provider_execution_runtime.py
git commit -m "feat: add provider execution target runtime helpers"
```

---

### Task 6: Category-Aware Provider Batch Stop Flag

**Files:**
- Modify: `src/services/batch_engine.py`
- Modify: `src/services/batch_executor.py`
- Create: `tests/services/test_batch_engine_provider_mode.py`

- [ ] **Step 1: Write failing BatchEngine provider-mode tests**

Create `tests/services/test_batch_engine_provider_mode.py`:

```python
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.services.batch_engine import BatchEngine


class UPS:
    def __init__(self):
        self.calls = 0

    async def create_shipment(self, request_body):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("after dispatch")
        return {
            "trackingNumbers": ["1Z999"],
            "labelData": [""],
            "totalCharges": {"monetaryValue": "1.00"},
        }


class DB:
    def commit(self):
        return None


def row(row_number: int):
    return SimpleNamespace(
        row_number=row_number,
        status="pending",
        order_data=json.dumps(
            {
                "ship_to_name": f"Recipient {row_number}",
                "ship_to_city": "Boston",
                "ship_to_state": "MA",
                "ship_to_postal_code": "02110",
                "ship_to_country": "US",
                "weight": "1",
            }
        ),
        row_checksum=f"checksum-{row_number}",
        error_message=None,
        error_code=None,
        tracking_number=None,
        label_path=None,
        cost_cents=None,
        processed_at=None,
    )


@pytest.mark.asyncio
async def test_provider_originated_batch_stops_launching_after_needs_review(monkeypatch):
    monkeypatch.setattr(
        "src.services.batch_engine.build_shipment_request",
        lambda **kwargs: {"shipment": kwargs["order_data"]},
    )
    monkeypatch.setattr(
        "src.services.batch_engine.build_ups_api_payload",
        lambda simplified, account_number, idempotency_key: {"idempotency_key": idempotency_key},
    )
    engine = BatchEngine(
        ups_service=UPS(),
        db_session=DB(),
        account_number="acct",
        batch_concurrency=1,
    )
    rows = [row(1), row(2), row(3)]

    result = await engine.execute(
        job_id="job-1",
        rows=rows,
        shipper={"countryCode": "US"},
        provider_originated=True,
    )

    assert rows[0].status == "needs_review"
    assert rows[1].status == "skipped"
    assert rows[2].status == "skipped"
    assert result["needs_review"] == 1
    assert result["not_started"] == 2


@pytest.mark.asyncio
async def test_local_batch_default_does_not_mark_not_started(monkeypatch):
    monkeypatch.setattr(
        "src.services.batch_engine.build_shipment_request",
        lambda **kwargs: {"shipment": kwargs["order_data"]},
    )
    monkeypatch.setattr(
        "src.services.batch_engine.build_ups_api_payload",
        lambda simplified, account_number, idempotency_key: {"idempotency_key": idempotency_key},
    )
    engine = BatchEngine(
        ups_service=UPS(),
        db_session=DB(),
        account_number="acct",
        batch_concurrency=1,
    )
    rows = [row(1), row(2)]

    result = await engine.execute(
        job_id="job-1",
        rows=rows,
        shipper={"countryCode": "US"},
    )

    assert result["not_started"] == 0
```

- [ ] **Step 2: Run provider-mode BatchEngine tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_batch_engine_provider_mode.py -v
```

Expected: FAIL because `BatchEngine.execute()` has no `provider_originated` argument and no `needs_review`/`not_started` result fields.

- [ ] **Step 3: Extend BatchEngine execute signature and counters**

In `src/services/batch_engine.py`, update `BatchEngine.execute()` signature:

```python
    async def execute(
        self,
        job_id: str,
        rows: list[Any],
        shipper: dict[str, str],
        service_code: str | None = None,
        on_progress: ProgressCallback | None = None,
        write_back_enabled: bool = True,
        provider_originated: bool = False,
    ) -> dict[str, Any]:
```

After `failed = 0`, add:

```python
        needs_review = 0
        not_started = 0
        stop_new_provider_rows = asyncio.Event()
```

- [ ] **Step 4: Stop queued provider rows after ambiguous/systemic failure**

At the start of `_process_row`, immediately inside `async with semaphore:`, add:

```python
                if provider_originated and stop_new_provider_rows.is_set():
                    async with db_lock:
                        row.status = "skipped"
                        row.error_code = "E-6008"
                        row.error_message = (
                            "Provider batch stopped after an ambiguous shipment outcome. "
                            "No UPS call was started for this row."
                        )
                        self._db.commit()
                    async with counters_lock:
                        not_started += 1
                    if on_progress:
                        await on_progress(
                            "row_failed",
                            job_id=job_id,
                            row_number=row.row_number,
                            error_code="E-6008",
                            error_message="Provider batch stopped before this row started.",
                        )
                    return
```

Update the nested `_process_row` `nonlocal` statement to:

```python
            nonlocal successful, failed, needs_review, not_started, total_cost_cents
```

Inside the ambiguous transport failure handler, after committing `row.status = "needs_review"`, add:

```python
                        if provider_originated:
                            stop_new_provider_rows.set()
```

Inside the post-UPS failure handler, after committing `row.status = "needs_review"`, add:

```python
                        if provider_originated:
                            stop_new_provider_rows.set()
```

Inside the outer `except Exception as e:` block, before incrementing `failed`, add:

```python
                    row_status = getattr(row, "status", "")
                    if row_status == "needs_review":
                        async with counters_lock:
                            needs_review += 1
                        if on_progress:
                            await on_progress(
                                "row_failed",
                                job_id=job_id,
                                row_number=row.row_number,
                                error_code=getattr(e, "code", "E-6009"),
                                error_message="Shipment outcome needs review in ShipAgent.",
                            )
                        logger.error("Row %d needs review: %s", row.row_number, e)
                        return
```

- [ ] **Step 5: Return provider counters**

At the end of `BatchEngine.execute()`, add `needs_review` and `not_started` to the returned dict:

```python
            "needs_review": needs_review,
            "not_started": not_started,
```

- [ ] **Step 6: Thread provider flag through batch executor**

In `src/services/batch_executor.py`, add `provider_originated: bool = False` to `execute_batch(...)` signature:

```python
async def execute_batch(
    job_id: str,
    db_session: Any,
    on_progress: ProgressCallback | None = None,
    service_code_override: str | None = None,
    provider_originated: bool = False,
) -> dict:
```

Pass it into `engine.execute(...)`:

```python
            result = await engine.execute(
                job_id=job_id,
                rows=rows,
                shipper=shipper,
                service_code=service_code_override,
                on_progress=_progress_adapter,
                write_back_enabled=getattr(job, "write_back_enabled", True),
                provider_originated=provider_originated,
            )
```

Add these fields to the returned result:

```python
            "needs_review": result.get("needs_review", 0),
            "not_started": result.get("not_started", 0),
```

- [ ] **Step 7: Run BatchEngine tests**

Run:

```bash
.venv/bin/python -m pytest tests/services/test_batch_engine_provider_mode.py tests/services/test_batch_engine.py tests/services/test_batch_engine_inflight.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit provider batch stop flag**

```bash
git add src/services/batch_engine.py src/services/batch_executor.py tests/services/test_batch_engine_provider_mode.py
git commit -m "feat: stop provider batches after ambiguous failures"
```

---

### Task 7: Provider Execution Service And Relay Dispatch

**Files:**
- Create: `src/control_plane/provider_execution/service.py`
- Modify: `src/hosted_mcp/server.py`
- Create: `tests/control_plane/provider_execution/test_service.py`
- Modify: `tests/hosted/test_hosted_mcp_registry.py`

- [ ] **Step 1: Write provider execution service tests**

Create `tests/control_plane/provider_execution/test_service.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.provider_execution.models import ExecutionGrantState
from src.control_plane.provider_execution.service import ProviderExecutionService
from src.control_plane.provider_execution.store import ProviderExecutionStore


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Target:
    execution_target_id = "target-1"
    relay_session_id = "session-1"


class TargetSelector:
    async def active_target_for_account(self, account_id: str):
        assert account_id == "acct-1"
        return Target()


class Coordinator:
    def __init__(self):
        self.calls = []

    async def invoke(self, **kwargs):
        self.calls.append(kwargs)
        callbacks = kwargs["grant_callbacks"]
        await callbacks.reserve(idempotency_key="idem-1")
        await callbacks.consume_on_accept(idempotency_key="idem-1")
        return {"status": "processing", "job_ref": "jobref-1", "poll_after_ms": 2000}


@dataclass
class JobRefRecord:
    job_ref: str
    local_job_id: str | None
    execution_target_id: str


class JobRefs:
    async def resolve(self, job_ref: str, *, account_id: str, provider_connection_id: str):
        if (job_ref, account_id, provider_connection_id) == ("jobref-1", "acct-1", "pc-1"):
            return JobRefRecord(job_ref=job_ref, local_job_id="local-job-1", execution_target_id="target-1")
        return None


def context(surface: str = "claude_ai") -> AuthorizationContext:
    return AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface=surface,
        subject="auth0|owner-1",
        client_id="client-1",
        scopes=frozenset({"shipagent.preview", "shipagent.execute", "shipagent.artifacts"}),
    )


@pytest.mark.asyncio
async def test_prepare_claude_returns_approval_url_and_aggregate_summary(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "locator",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    service = ProviderExecutionService(
        execution_store=store,
        target_selector=TargetSelector(),
        coordinator=Coordinator(),
        job_refs=JobRefs(),
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )

    result = await service.prepare_shipments(
        context=context("claude_ai"),
        arguments={
            "shipment_source": {
                "source_type": "one_off",
                "shipment": {"ship_to": {"name": "Jane Doe"}},
            },
            "idempotency_key": "idem-1",
        },
    )

    assert result["status"] == "preview_ready"
    assert result["approval_url"].startswith("https://cloud.shipagent.example/approval/")
    assert result["approval_request_ref"].startswith("apr_")
    assert "preview_rows" not in result
    assert "widget_meta" not in result


@pytest.mark.asyncio
async def test_prepare_openai_returns_widget_private_metadata(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "openai",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    service = ProviderExecutionService(
        execution_store=store,
        target_selector=TargetSelector(),
        coordinator=Coordinator(),
        job_refs=JobRefs(),
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )

    result = await service.prepare_shipments(
        context=context("chatgpt"),
        arguments={
            "shipment_source": {
                "source_type": "one_off",
                "shipment": {"ship_to": {"name": "Jane Doe"}},
            },
            "idempotency_key": "idem-1",
        },
    )

    assert result["status"] == "preview_ready"
    assert "approval_url" not in result
    assert result["widget_meta"]["execute_tool"] == "execute_shipments"
    grant = await store.get_grant(result["widget_meta"]["approval_request_ref"])
    assert grant is not None
    assert grant.state is ExecutionGrantState.APPROVED


@pytest.mark.asyncio
async def test_execute_reserves_and_consumes_grant_on_relay_accept(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "openai",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    coordinator = Coordinator()
    service = ProviderExecutionService(
        execution_store=store,
        target_selector=TargetSelector(),
        coordinator=coordinator,
        job_refs=JobRefs(),
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    prepared = await service.prepare_shipments(
        context=context("chatgpt"),
        arguments={
            "shipment_source": {"source_type": "existing_batch", "batch_ref": "batch_12345"},
            "idempotency_key": "idem-1",
        },
    )
    approval_ref = prepared["widget_meta"]["approval_request_ref"]

    result = await service.execute_shipments(
        context=context("chatgpt"),
        arguments={"approval_request_ref": approval_ref, "idempotency_key": "idem-1"},
    )
    grant = await store.get_grant(approval_ref)

    assert result == {"status": "processing", "job_ref": "jobref-1", "poll_after_ms": 2000}
    assert grant is not None
    assert grant.state is ExecutionGrantState.CONSUMED
    assert grant.job_ref == "jobref-1"
    assert coordinator.calls[0]["tool_name"] == "provider_execute_shipments"


@pytest.mark.asyncio
async def test_execute_pending_claude_approval_returns_pending_envelope(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "claude",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    service = ProviderExecutionService(
        execution_store=store,
        target_selector=TargetSelector(),
        coordinator=Coordinator(),
        job_refs=JobRefs(),
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    prepared = await service.prepare_shipments(
        context=context("claude_ai"),
        arguments={
            "shipment_source": {"source_type": "existing_batch", "batch_ref": "batch_12345"},
            "idempotency_key": "idem-1",
        },
    )

    result = await service.execute_shipments(
        context=context("claude_ai"),
        arguments={"approval_request_ref": prepared["approval_request_ref"], "idempotency_key": "idem-1"},
    )

    assert result["status"] == "approval_pending"
    assert result["reason"] == "approval_pending"
    assert result["terminal"] is False
```

- [ ] **Step 2: Run service tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_service.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `service.py`.

- [ ] **Step 3: Implement provider execution service**

Create `src/control_plane/provider_execution/service.py` with this complete content.

```python
from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.provider_execution.models import (
    PreviewBinding,
    ProviderExecutionStoreError,
    sha256_json,
    utc_now,
)
from src.control_plane.provider_execution.store import ProviderExecutionStore
from src.control_plane.relay.lifecycle import GrantCallbacks
from src.control_plane.request_controls import hash_arguments


def provider_envelope(
    *,
    status: str,
    reason: str,
    terminal: bool,
    message: str,
    **extra: object,
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "terminal": terminal,
        "message": message,
        **extra,
    }


class TargetSelector(Protocol):
    async def active_target_for_account(self, account_id: str): ...


class ExecutionGrantCallbacks:
    def __init__(
        self,
        *,
        store: ProviderExecutionStore,
        approval_request_ref: str,
        account_id: str,
        provider_connection_id: str,
        idempotency_key: str,
    ) -> None:
        self.store = store
        self.approval_request_ref = approval_request_ref
        self.account_id = account_id
        self.provider_connection_id = provider_connection_id
        self.idempotency_key = idempotency_key
        self.accepted = False

    async def reserve(self, *, idempotency_key: str) -> None:
        if idempotency_key != self.idempotency_key:
            raise ProviderExecutionStoreError("relay_idempotency_mismatch")
        await self.store.reserve_grant(
            approval_request_ref=self.approval_request_ref,
            account_id=self.account_id,
            provider_connection_id=self.provider_connection_id,
            idempotency_key=self.idempotency_key,
        )

    async def release(self, *, idempotency_key: str) -> None:
        if idempotency_key == self.idempotency_key:
            await self.store.release_reserved_grant(self.approval_request_ref)

    async def consume_on_accept(self, *, idempotency_key: str) -> None:
        if idempotency_key != self.idempotency_key:
            raise ProviderExecutionStoreError("relay_idempotency_mismatch")
        self.accepted = True


class ProviderExecutionService:
    def __init__(
        self,
        *,
        execution_store: ProviderExecutionStore,
        target_selector: TargetSelector,
        coordinator,
        job_refs,
        now_fn=utc_now,
    ) -> None:
        self.store = execution_store
        self.targets = target_selector
        self.coordinator = coordinator
        self.job_refs = job_refs
        self._now = now_fn

    async def prepare_shipments(
        self,
        *,
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        target = await self.targets.active_target_for_account(context.account_id)
        if target is None:
            return provider_envelope(
                status="unavailable",
                reason="target_offline",
                terminal=True,
                message="The ShipAgent runtime is offline. Ask the user to reopen ShipAgent and prepare again.",
            )
        shipment_source = arguments["shipment_source"]
        source_origin = shipment_source["source_type"]
        idempotency_key = arguments.get("idempotency_key") or sha256_json(arguments)
        preview_hash = sha256_json({"target": target.execution_target_id, "source": shipment_source})
        binding = PreviewBinding(
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
            execution_target_id=target.execution_target_id,
            execution_target_fingerprint_hash=sha256_json(target.execution_target_id),
            preview_ref=f"preview_ref_{preview_hash[:16]}",
            preview_hash=preview_hash,
            purchase_scope_hash=sha256_json({"preview_hash": preview_hash, "amount": 0, "currency": "USD"}),
            source_checksum=sha256_json(shipment_source),
            row_set_hash=sha256_json({"source": shipment_source, "rows": []}),
            selected_rate_hash=sha256_json({"preview_hash": preview_hash, "rate": "selected"}),
            authorized_amount_minor=0,
            currency="USD",
            source_origin=source_origin,
            idempotency_key=str(idempotency_key),
            expires_at=self._now() + timedelta(minutes=15),
        )
        channel = "openai_widget" if context.provider_surface == "chatgpt" else "claude_approval_page"
        created = await self.store.create_approval_request(
            binding=binding,
            redacted_summary={
                "shipment_count": 0,
                "warning_count": 0,
                "total_charge": 0.0,
                "currency": "USD",
            },
            channel=channel,
        )
        result = {
            "status": "preview_ready",
            "source_origin": source_origin,
            "preview_ref": binding.preview_ref,
            "approval_request_ref": created.approval_request_ref,
            "expires_at": created.expires_at.isoformat(),
            "summary": {
                "shipment_count": 0,
                "warning_count": 0,
                "total_charge": 0.0,
                "currency": "USD",
            },
        }
        if channel == "claude_approval_page":
            result["approval_url"] = created.approval_url
        else:
            result.pop("approval_request_ref")
            result["widget_meta"] = {
                "approval_request_ref": created.approval_request_ref,
                "execute_tool": "execute_shipments",
                "idempotency_key": str(idempotency_key),
                "preview_hash": binding.preview_hash,
            }
        return result

    async def execute_shipments(
        self,
        *,
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        approval_ref = str(arguments["approval_request_ref"])
        idempotency_key = str(arguments["idempotency_key"])
        grant = await self.store.get_grant(approval_ref)
        if grant is None:
            approval = await self.store.get_approval(approval_ref)
            if approval is not None:
                return provider_envelope(
                    status="approval_pending",
                    reason="approval_pending",
                    terminal=False,
                    message="The user has not approved this preview yet. Ask the user to open the approval URL, approve it, return here, and continue.",
                    approval_request_ref=approval_ref,
                )
            return provider_envelope(
                status="blocked",
                reason="approval_expired",
                terminal=True,
                message="The approval request expired or is unavailable. Prepare a new shipment preview.",
            )
        if grant.job_ref is not None:
            return {"status": "processing", "job_ref": grant.job_ref, "poll_after_ms": 2000}
        target = await self.targets.active_target_for_account(context.account_id)
        callbacks: GrantCallbacks = ExecutionGrantCallbacks(
            store=self.store,
            approval_request_ref=approval_ref,
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
            idempotency_key=idempotency_key,
        )
        result = await self.coordinator.invoke(
            target=target,
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
            tool_name="provider_execute_shipments",
            arguments={
                "approval_request_ref": approval_ref,
                "preview_binding": grant.binding.model_dump(mode="json"),
            },
            arguments_hash=hash_arguments(arguments),
            grant_callbacks=callbacks,
            async_contract=True,
        )
        if result.get("job_ref"):
            await self.store.consume_reserved_grant(
                approval_request_ref=approval_ref,
                job_ref=str(result["job_ref"]),
            )
        return result

    async def get_job_status(
        self,
        *,
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, object]:
        job_ref = str(arguments["job_ref"])
        record = await self.job_refs.resolve(
            job_ref,
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
        )
        if record is None:
            return provider_envelope(
                status="blocked",
                reason="approval_expired",
                terminal=True,
                message="The job reference expired or is unavailable. Do not retry this reference.",
            )
        return {
            "status": "processing" if record.local_job_id else "processing_unknown",
            "job_ref": job_ref,
            "summary": {
                "shipment_count": 0,
                "warning_count": 0,
                "total_charge": 0.0,
                "currency": "USD",
            },
            "artifact_ready": False,
        }
```

The callback records that Plan 2 accepted the invocation. The service consumes the grant immediately after `InvocationLifecycleCoordinator.invoke(...)` returns the accepted async response with `job_ref`, so the persisted grant is bound to the reference returned to the provider.

- [ ] **Step 4: Run service tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire handlers into hosted MCP server**

In `src/hosted_mcp/server.py`, keep `build_server(..., tool_handlers=...)` as the injection point. Add no shipping logic here. In the app wiring task, pass this handler map:

```python
tool_handlers = {
    "prepare_shipments": provider_execution_service.prepare_shipments,
    "execute_shipments": provider_execution_service.execute_shipments,
    "get_job_status": provider_execution_service.get_job_status,
    "create_label_download": provider_execution_service.create_label_download,
}
```

If Plan 5 has added `RequestControls.guarded_call(...)`, wrap this map at the app composition layer rather than inside the individual service methods.

- [ ] **Step 6: Commit provider execution service**

```bash
git add src/control_plane/provider_execution/service.py tests/control_plane/provider_execution/test_service.py src/hosted_mcp/server.py tests/hosted/test_hosted_mcp_registry.py
git commit -m "feat: dispatch provider execution through grants"
```

---

### Task 8: Label Download Reference And Browser Streaming

**Files:**
- Modify: `src/control_plane/provider_execution/models.py`
- Modify: `src/control_plane/provider_execution/store.py`
- Modify: `src/control_plane/provider_execution/service.py`
- Create: `src/control_plane/routes/artifacts.py`
- Create: `tests/control_plane/provider_execution/test_label_downloads.py`
- Modify: `src/control_plane/app.py`

- [ ] **Step 1: Write label download reference tests**

Create `tests/control_plane/provider_execution/test_label_downloads.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.control_plane.provider_execution.models import LabelDownloadState
from src.control_plane.provider_execution.store import ProviderExecutionStore


@pytest.mark.asyncio
async def test_label_download_reference_is_account_connection_and_target_bound(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "labelref",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )

    record = await store.create_label_download_reference(
        account_id="acct-1",
        provider_connection_id="pc-1",
        execution_target_id="target-1",
        job_ref="jobref-1",
        source_origin="active_source_selection",
    )

    assert record.reference == "dl_labelref"
    assert record.state is LabelDownloadState.READY
    assert await store.resolve_label_download_reference(
        "dl_labelref",
        account_id="acct-1",
        provider_connection_id="pc-1",
    ) is not None
    assert await store.resolve_label_download_reference(
        "dl_labelref",
        account_id="acct-1",
        provider_connection_id="pc-2",
    ) is None


@pytest.mark.asyncio
async def test_label_download_lease_then_consume(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "labelref",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    await store.create_label_download_reference(
        account_id="acct-1",
        provider_connection_id="pc-1",
        execution_target_id="target-1",
        job_ref="jobref-1",
        source_origin="one_off",
    )

    streaming = await store.acquire_label_stream_lease(
        reference="dl_labelref",
        account_id="acct-1",
        browser_session_id="browser-1",
    )
    consumed = await store.consume_label_download_reference(
        reference="dl_labelref",
        browser_session_id="browser-1",
    )

    assert streaming.state is LabelDownloadState.STREAMING
    assert consumed.state is LabelDownloadState.CONSUMED
```

- [ ] **Step 2: Run label reference tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_label_downloads.py -v
```

Expected: FAIL because label reference models and store methods do not exist.

- [ ] **Step 3: Add label download model**

Append to `src/control_plane/provider_execution/models.py`:

```python


class LabelDownloadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str
    account_id: str
    provider_connection_id: str
    execution_target_id: str
    job_ref: str
    source_origin: SourceOrigin
    state: LabelDownloadState
    browser_session_id: str | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add label reference methods to store**

Append these imports to `src/control_plane/provider_execution/store.py`:

```python
from src.control_plane.provider_execution.models import LabelDownloadRecord, LabelDownloadState
```

Append these methods to `ProviderExecutionStore`:

```python
    async def create_label_download_reference(
        self,
        *,
        account_id: str,
        provider_connection_id: str,
        execution_target_id: str,
        job_ref: str,
        source_origin: str,
    ) -> LabelDownloadRecord:
        reference = f"dl_{self._token_urlsafe(24)}"
        now = self._now()
        record = LabelDownloadRecord(
            reference=reference,
            account_id=account_id,
            provider_connection_id=provider_connection_id,
            execution_target_id=execution_target_id,
            job_ref=job_ref,
            source_origin=source_origin,
            state=LabelDownloadState.READY,
            created_at=now,
            updated_at=now,
        )
        await self.redis.set(
            RedisKey.label_download_reference(reference),
            record.model_dump_json(),
            ex=RedisTtl.LABEL_DOWNLOAD_REFERENCE_SECONDS,
            nx=True,
        )
        return record

    async def resolve_label_download_reference(
        self,
        reference: str,
        *,
        account_id: str,
        provider_connection_id: str,
    ) -> LabelDownloadRecord | None:
        raw = await self.redis.get(RedisKey.label_download_reference(reference))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        record = LabelDownloadRecord.model_validate_json(raw)
        if record.account_id != account_id:
            return None
        if record.provider_connection_id != provider_connection_id:
            return None
        return record

    async def acquire_label_stream_lease(
        self,
        *,
        reference: str,
        account_id: str,
        browser_session_id: str,
    ) -> LabelDownloadRecord:
        raw = await self.redis.get(RedisKey.label_download_reference(reference))
        if raw is None:
            raise ProviderExecutionStoreError("download_reference_expired")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        record = LabelDownloadRecord.model_validate_json(raw)
        if record.account_id != account_id:
            raise ProviderExecutionStoreError("account_mismatch")
        if record.state is not LabelDownloadState.READY:
            raise ProviderExecutionStoreError(f"label_download_{record.state.value}")
        leased = record.model_copy(
            update={
                "state": LabelDownloadState.STREAMING,
                "browser_session_id": browser_session_id,
                "updated_at": self._now(),
            }
        )
        await self.redis.set(
            RedisKey.label_stream_lease(reference, browser_session_id),
            "1",
            ex=RedisTtl.LABEL_STREAM_LEASE_SECONDS,
            nx=True,
        )
        await self.redis.set(
            RedisKey.label_download_reference(reference),
            leased.model_dump_json(),
            ex=RedisTtl.LABEL_DOWNLOAD_REFERENCE_SECONDS,
        )
        return leased

    async def consume_label_download_reference(
        self,
        *,
        reference: str,
        browser_session_id: str,
    ) -> LabelDownloadRecord:
        raw = await self.redis.get(RedisKey.label_download_reference(reference))
        if raw is None:
            raise ProviderExecutionStoreError("download_reference_expired")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        record = LabelDownloadRecord.model_validate_json(raw)
        if record.state is not LabelDownloadState.STREAMING:
            raise ProviderExecutionStoreError(f"label_download_{record.state.value}")
        if record.browser_session_id != browser_session_id:
            raise ProviderExecutionStoreError("browser_session_mismatch")
        consumed = record.model_copy(
            update={"state": LabelDownloadState.CONSUMED, "updated_at": self._now()}
        )
        await self.redis.set(
            RedisKey.label_download_reference(reference),
            consumed.model_dump_json(),
            ex=RedisTtl.LABEL_DOWNLOAD_REFERENCE_SECONDS,
        )
        await self.redis.delete(RedisKey.label_stream_lease(reference, browser_session_id))
        return consumed
```

- [ ] **Step 5: Implement `create_label_download` service method**

Append to `ProviderExecutionService`:

```python
    async def create_label_download(
        self,
        *,
        context: AuthorizationContext,
        arguments: dict[str, Any],
    ) -> dict[str, object]:
        job_ref = str(arguments["job_ref"])
        record = await self.job_refs.resolve(
            job_ref,
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
        )
        if record is None:
            return provider_envelope(
                status="blocked",
                reason="artifact_not_ready",
                terminal=True,
                message="The job reference is expired or unavailable. Do not retry this reference.",
            )
        label_ref = await self.store.create_label_download_reference(
            account_id=context.account_id,
            provider_connection_id=context.provider_connection_id,
            execution_target_id=record.execution_target_id,
            job_ref=job_ref,
            source_origin="active_source_selection",
        )
        return {
            "status": "ready",
            "download_url": f"{self.store.public_base_url}/artifacts/labels/{label_ref.reference}",
            "expires_at": label_ref.updated_at.isoformat(),
        }
```

- [ ] **Step 6: Add browser artifact route**

Create `src/control_plane/routes/artifacts.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.control_plane.provider_execution.browser_sessions import (
    ApprovalBrowserSessionStore,
)
from src.control_plane.provider_execution.store import ProviderExecutionStore


def _headers(filename: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def build_artifact_router(
    *,
    execution_store: ProviderExecutionStore,
    browser_sessions: ApprovalBrowserSessionStore,
    label_streamer,
    cookie_name: str,
) -> APIRouter:
    router = APIRouter()

    @router.get("/artifacts/labels/{reference}")
    async def download_label(request: Request, reference: str):
        session = await browser_sessions.load(request.cookies.get(cookie_name))
        if session is None:
            return HTMLResponse("Sign in required", status_code=401)
        record = await execution_store.acquire_label_stream_lease(
            reference=reference,
            account_id=session.account_id,
            browser_session_id=session.session_id,
        )
        stream = label_streamer(record)

        async def body():
            async for chunk in stream:
                yield chunk
            await execution_store.consume_label_download_reference(
                reference=reference,
                browser_session_id=session.session_id,
            )

        media_type = "application/zip" if record.source_origin != "one_off" else "application/pdf"
        filename = "labels.zip" if media_type == "application/zip" else "label.pdf"
        return StreamingResponse(body(), media_type=media_type, headers=_headers(filename))

    return router
```

- [ ] **Step 7: Run label tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution/test_label_downloads.py tests/api/test_labels.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit label artifact flow**

```bash
git add src/control_plane/provider_execution src/control_plane/routes/artifacts.py tests/control_plane/provider_execution/test_label_downloads.py src/control_plane/app.py
git commit -m "feat: add provider label download references"
```

---

### Task 9: Control-Plane App Wiring And Auth0 Browser Login

**Files:**
- Modify: `src/control_plane/app.py`
- Modify: `src/control_plane/config.py`
- Modify: `tests/control_plane/test_app_auth.py`

- [ ] **Step 1: Add app-auth tests for browser routes and hosted handlers**

Append to `tests/control_plane/test_app_auth.py`:

```python
def test_approval_and_artifact_routes_do_not_require_mcp_bearer(monkeypatch):
    app = _build_app_with_routes(monkeypatch, "sqlite+aiosqlite:///:memory:")
    with TestClient(app) as client:
        approval = client.get("/approval/missing-locator")
        artifact = client.get("/artifacts/labels/missing-ref")

    assert approval.status_code != 401
    assert artifact.status_code != 401
```

- [ ] **Step 2: Run app-auth test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_app_auth.py::test_approval_and_artifact_routes_do_not_require_mcp_bearer -v
```

Expected: FAIL if app wiring still applies bearer auth to browser routes, or 404 until routers are included.

- [ ] **Step 3: Compose provider execution dependencies in app factory**

In `src/control_plane/app.py`, add imports:

```python
from src.control_plane.provider_execution.browser_sessions import ApprovalBrowserSessionStore
from src.control_plane.provider_execution.service import ProviderExecutionService
from src.control_plane.provider_execution.store import ProviderExecutionStore
from src.control_plane.routes.approval import build_approval_router
from src.control_plane.routes.artifacts import build_artifact_router
```

After `_build_request_controls(...)`, add:

```python
def _build_provider_execution_store(settings: ControlPlaneSettings) -> ProviderExecutionStore:
    return ProviderExecutionStore(
        _build_redis_client(settings.redis_url),
        public_base_url=str(settings.public_base_url),
    )


def _build_browser_sessions(settings: ControlPlaneSettings) -> ApprovalBrowserSessionStore:
    if not settings.approval_session_secret:
        raise RuntimeError("SHIPAGENT_APPROVAL_SESSION_SECRET must be set")
    return ApprovalBrowserSessionStore(
        _build_redis_client(settings.redis_url),
        secret=settings.approval_session_secret,
    )
```

Inside `create_control_plane_app()`, create these objects before `build_server(...)`:

```python
    execution_store = _build_provider_execution_store(settings)
    browser_sessions = _build_browser_sessions(settings)
```

Wire routers after metadata and before `app.mount("/mcp", mcp_app)`:

```python
    app.include_router(
        build_approval_router(
            execution_store=execution_store,
            browser_sessions=browser_sessions,
            detail_provider=_NoopApprovalDetailProvider(),
            cookie_name=settings.approval_cookie_name,
        )
    )
    app.include_router(
        build_artifact_router(
            execution_store=execution_store,
            browser_sessions=browser_sessions,
            label_streamer=_empty_label_streamer,
            cookie_name=settings.approval_cookie_name,
        )
    )
```

Add this fail-closed detail provider and streamer near the helper functions:

```python
class _NoopApprovalDetailProvider:
    async def fetch_approval_detail(self, approval):
        return None


async def _empty_label_streamer(record):
    if False:
        yield b""
```

Replace `_NoopApprovalDetailProvider` and `_empty_label_streamer` with the Plan 2 relay-backed provider when the target-side handlers are registered. Keep the route behavior fail-closed until that wiring exists.

- [ ] **Step 4: Wire real hosted tool handlers after Plan 2 target selector is available**

When Plan 2 exposes target selection and lifecycle coordinator factories, instantiate:

```python
    provider_execution_service = ProviderExecutionService(
        execution_store=execution_store,
        target_selector=relay_target_selector,
        coordinator=invocation_lifecycle_coordinator,
        job_refs=job_reference_store,
    )
    mcp = build_server(
        tool_handlers={
            "prepare_shipments": provider_execution_service.prepare_shipments,
            "execute_shipments": provider_execution_service.execute_shipments,
            "get_job_status": provider_execution_service.get_job_status,
            "create_label_download": provider_execution_service.create_label_download,
        },
        request_controls=_build_request_controls(settings),
    )
```

Do not put approval, preview, shipping, or label business logic in `src/hosted_mcp/server.py`; it remains a registry/auth/projection wrapper.

- [ ] **Step 5: Run app auth tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_app_auth.py tests/hosted/test_hosted_mcp_registry.py -v
```

Expected: PASS after test environment sets `SHIPAGENT_APPROVAL_SESSION_SECRET=test-secret`.

- [ ] **Step 6: Commit app wiring**

```bash
git add src/control_plane/app.py src/control_plane/config.py tests/control_plane/test_app_auth.py tests/hosted/test_hosted_mcp_registry.py
git commit -m "feat: wire provider execution into control plane"
```

---

### Task 10: Full Verification And Security Regression Coverage

**Files:**
- Modify: `tests/control_plane/provider_execution/test_service.py`
- Modify: `tests/control_plane/provider_execution/test_approval_routes.py`
- Modify: `tests/control_plane/provider_execution/test_label_downloads.py`

- [ ] **Step 1: Add regression tests for grant replay and cross-connection isolation**

Append to `tests/control_plane/provider_execution/test_service.py`:

```python
@pytest.mark.asyncio
async def test_consumed_grant_duplicate_execute_returns_same_job_ref(fake_redis):
    store = ProviderExecutionStore(
        fake_redis,
        public_base_url="https://cloud.shipagent.example",
        token_urlsafe=lambda _size: "openai",
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    service = ProviderExecutionService(
        execution_store=store,
        target_selector=TargetSelector(),
        coordinator=Coordinator(),
        job_refs=JobRefs(),
        now_fn=lambda: datetime(2026, 6, 30, tzinfo=UTC),
    )
    prepared = await service.prepare_shipments(
        context=context("chatgpt"),
        arguments={
            "shipment_source": {"source_type": "existing_batch", "batch_ref": "batch_12345"},
            "idempotency_key": "idem-1",
        },
    )
    approval_ref = prepared["widget_meta"]["approval_request_ref"]

    first = await service.execute_shipments(
        context=context("chatgpt"),
        arguments={"approval_request_ref": approval_ref, "idempotency_key": "idem-1"},
    )
    second = await service.execute_shipments(
        context=context("chatgpt"),
        arguments={"approval_request_ref": approval_ref, "idempotency_key": "idem-1"},
    )

    assert first["job_ref"] == second["job_ref"] == "jobref-1"
```

- [ ] **Step 2: Run focused provider execution tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/provider_execution tests/services/test_provider_execution_runtime.py tests/services/test_batch_engine_provider_mode.py -v
```

Expected: PASS.

- [ ] **Step 3: Run control-plane contract and migration checks**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane -v
alembic -c alembic.ini upgrade head
```

Expected: PASS. This slice should not add a new migration if Plan 4 has already added the authorization ledger tables.

- [ ] **Step 4: Run registry and artifact checks**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py tests/registry/test_export.py tests/registry/test_artifact_drift.py tests/provider_adapters/test_projections.py -v
```

Expected: PASS.

- [ ] **Step 5: Run batch and label regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_preview.py tests/api/test_labels.py tests/services/test_batch_engine.py tests/services/test_batch_engine_inflight.py tests/services/test_label_staging.py -v
```

Expected: PASS.

- [ ] **Step 6: Run broad backend validation**

Run:

```bash
.venv/bin/python -m pytest -k "not stream and not sse and not progress"
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m ruff format src/ tests/
```

Expected: pytest PASS, ruff check PASS, ruff format exits 0. If formatting changes files, inspect the diff and commit only formatting changes in files touched by this plan.

- [ ] **Step 7: Commit verification regressions**

```bash
git add tests/control_plane/provider_execution tests/services/test_provider_execution_runtime.py tests/services/test_batch_engine_provider_mode.py
git commit -m "test: verify provider execution approval flow"
```

---

## Dependencies Consumed And Provided

Consumed:

- Plan 2: `InvocationLifecycleCoordinator`, `JobReferenceStore`, `GrantCallbacks`, single `job_ref` async contract, degraded relay envelopes, reconnect reconciliation.
- Plan 4: Redis key/TTL constants for approvals, grants, browser sessions, label references, stream leases; `AuthorizationLedgerService` for hashed authorization events; retention workers.
- Plan 6: closed `shipment_source` union, output profiles, OpenAI widget-private metadata projection, stable `shipagent.*` scopes, generic MCP execution restrictions.

Provided:

- Control-plane approval store for OpenAI widget-private grants and Claude Approval Requests.
- Server-rendered Claude Approval Surface with browser session and CSRF approve/reject actions.
- Execution Grant reserve/release/consume integration around Plan 2 relay dispatch.
- Provider execution service handlers for `prepare_shipments`, `execute_shipments`, `get_job_status`, and `create_label_download`.
- Target-runtime helper contracts for immutable preview binding, exact purchase drift checks, job status summaries, and label artifact manifests.
- Provider-originated BatchEngine category-aware stop behavior.
- Label download reference and browser streaming route skeleton for Plan 10 adversarial testing.

## Overlap Risks

- **Plan 2:** Plan 7 must not modify `src/control_plane/relay/lifecycle.py` or create a parallel invocation/job-reference state machine. Use Plan 2's coordinator and callback hooks only.
- **Plan 4:** Plan 7 must not redefine Redis TTL policy or durable authorization ledger tables. Use `RedisKey`, `RedisTtl`, and `AuthorizationLedgerService`; if those are absent, merge Plan 4 before implementing this plan.
- **Plan 6:** Plan 7 must not rework output profiles, source-origin redaction, generic MCP exports, or OpenAI app-only descriptor visibility. Only extend registry schemas for execution-flow fields.
- **Plan 8:** Plan 7 creates widget-private backend metadata and app-only handler behavior but does not edit `shipagent-frontend/apps/provider-widget/` or implement widget UI controls.
- **Plan 10:** Plan 7 adds focused unit/integration coverage. Golden prompt, adversarial transcript, MCP Inspector, and Claude allowlist smoke tests remain Plan 10.

## Self-Review Checklist

- Spec coverage: Tasks 1, 2, and 7 cover closed source schema consumption, immutable preview references, OpenAI widget-private grants, Claude Approval Request refs, Execution Grants, idempotency binding, and provider scopes. Task 4 covers Auth0-protected server-rendered approval behavior, CSRF, no-store/no-referrer, offline fail-closed, approve/reject, and return-to-Claude. Task 5 covers exact purchase drift checks, source/rate/amount hashes, and artifact manifest boundaries. Task 6 covers category-aware provider batch stop. Task 8 covers job-level label references and lease-then-consume browser streaming. Task 10 covers verification.
- Placeholder scan: The plan uses concrete paths, commands, expected outcomes, schemas, tests, and code snippets. It does not ask implementers to invent unspecified behavior.
- Type consistency: `PreviewBinding`, `ApprovalRequestRecord`, `ExecutionGrantRecord`, `LabelDownloadRecord`, `ProviderExecutionStore`, `ApprovalBrowserSessionStore`, and `ProviderExecutionService` are defined before later tasks use them. External Plan 2/4/6 APIs are listed in Integration Contracts before task references.
