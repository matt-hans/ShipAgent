# Ephemeral Retention And Authorization Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Plan 4 from the OpenAI App and Claude Connector design: TTL-owned ephemeral Redis state, scheduled Redis and SQL purges, legal-hold-aware account deletion cleanup, and a durable hashed authorization ledger.

**Architecture:** Keep Redis policy in `src/control_plane/redis_keys.py`, put retention workers under `src/control_plane/retention/`, keep durable audit and authorization ledger code under `src/control_plane/audit/`, and expose account deletion cleanup through a small control-plane account service. This slice consumes Cloud Account and Provider Connection primitives from Plan 1 but does not implement invocation lifecycle, approval pages, execution grant consumption, provider projections, registry exports, or Plan 7 approval routes.

**Tech Stack:** Python 3.12, FastAPI lifespan tasks, SQLAlchemy 2 async sessions, Alembic migrations, Redis asyncio client, Pydantic settings, pytest, pytest-asyncio.

---

## Source Of Truth

Use these documents as authoritative inputs:

- `docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md`
- `docs/adr/0001-cloud-account-auth0-identity.md`
- `docs/adr/0004-cryptographic-relay-identity.md`
- `docs/adr/0005-ephemeral-cloud-state-retention.md`
- `docs/adr/0007-origin-based-provider-redaction.md`
- `docs/adr/0008-in-provider-execution-no-handoff.md`
- `AGENTS.md`
- `src/AGENTS.md`

Plan 4 owns:

- Redis TTL key policy in `src/control_plane/redis_keys.py`
- Redis sweeper every 5 minutes
- Durable SQL retention purge every day
- Account deletion cleanup for audit and ledger rows
- Explicit legal-hold guard
- Durable hashed authorization-ledger models, migration, and service

Plan 4 does not own:

- Relay device registration or relay session semantics from Plan 1
- Invocation lifecycle or recovery from Plan 2
- Approval Request creation, Approval Surface routes, or Execution Grant consumption from Plan 7
- Provider output profiles, origin redaction, registry exports, or generated artifacts from Plan 6
- Frontend, Tauri, Claude connector descriptors, or OpenAI widget UI

## Current Repo State

Relevant current files:

- `src/control_plane/redis_keys.py` has basic key helpers and incomplete TTL constants.
- `src/control_plane/config.py` has Auth0, database, Redis, and provider-client settings but no retention settings.
- `src/control_plane/audit/models.py` has `ControlPlaneAuditEvent`.
- `src/control_plane/audit/service.py` records redacted audit payloads and has `cleanup_for_account()`.
- `src/control_plane/models.py` has `CloudAccount` and `ProviderConnection`.
- `src/control_plane/app.py` creates the FastAPI app and mounts hosted MCP with the MCP app lifespan.
- `alembic/versions/20260609_0001_control_plane_core.py` creates `cloud_accounts`, `provider_connections`, and `audit_events`.
- `alembic/env.py` imports only current control-plane models into metadata.
- `tests/control_plane/conftest.py` creates SQLite metadata for unit tests.
- `docker-compose.control-plane.yml` provides Postgres on `127.0.0.1:5433` and Redis on `127.0.0.1:6380`.

The existing git worktree may contain unrelated edits from other workers. Do not modify, revert, or format files outside this plan's assigned paths.

## Target File Structure

Create:

```text
src/control_plane/accounts/__init__.py
src/control_plane/accounts/service.py
src/control_plane/audit/authorization_ledger.py
src/control_plane/audit/hash_validation.py
src/control_plane/retention/__init__.py
src/control_plane/retention/legal_hold.py
src/control_plane/retention/redis_sweeper.py
src/control_plane/retention/sql_purge.py
src/control_plane/retention/tasks.py
alembic/versions/20260630_0004_ephemeral_retention_authorization_audit.py
tests/control_plane/accounts/__init__.py
tests/control_plane/accounts/test_service.py
tests/control_plane/audit/test_authorization_ledger.py
tests/control_plane/retention/__init__.py
tests/control_plane/retention/test_redis_sweeper.py
tests/control_plane/retention/test_sql_purge.py
tests/control_plane/retention/test_tasks.py
```

Modify:

```text
src/control_plane/app.py
src/control_plane/audit/__init__.py
src/control_plane/audit/models.py
src/control_plane/config.py
src/control_plane/redis_keys.py
alembic/env.py
tests/control_plane/audit/test_service.py
tests/control_plane/test_app_auth.py
tests/control_plane/test_config.py
tests/control_plane/test_models.py
tests/control_plane/test_redis_keys.py
```

Do not modify:

```text
generated/provider_artifacts/
shipagent-frontend/
src/api/
src/control_plane/relay/
src/control_plane/result_projection.py
src/control_plane/request_controls.py
src/hosted/confirmation_service.py
src/orchestrator/
src/registry/
src/services/conversation_runtime/
src-tauri/
```

## Retention Policy

Use this concrete policy:

| State | Redis key prefix | TTL |
|---|---|---|
| Relay heartbeat | `sa:relay:heartbeat:` | 90 seconds |
| Relay session metadata | `sa:relay:session:` | 300 seconds after disconnect |
| Relay replay nonce | `sa:relay:nonce:` | 300 seconds |
| Invocation state | `sa:invocation:` | 86400 seconds |
| Job Reference mapping | `sa:job_ref:` | 86400 seconds |
| Redacted preview summary | `sa:preview:redacted:` | 86400 seconds |
| Approval Request | `sa:approval:request:` | 900 seconds |
| Public Approval locator hash | `sa:approval:locator:` | 900 seconds |
| One-time Execution Grant | `sa:approval:grant:` | 900 seconds |
| Approval browser server-side session | `sa:approval:session:` | 1800 seconds |
| Provider poll reference | `sa:poll:` | 86400 seconds |
| Label download reference | `sa:label:download:` | 300 seconds |
| Label stream lease | `sa:label:lease:` | 30 seconds |
| Rate limit counter | `sa:rate:` | 60 seconds |
| Loop guard counter | `sa:loop:` | 60 seconds |

Redis itself expires keys by TTL. The sweeper runs every 300 seconds and deletes matching ephemeral keys that have no TTL (`TTL == -1`), because TTL-less keys violate ADR 0005. It leaves active TTL-owned keys alone.

SQL durable cloud audit retention defaults to 90 days. `SHIPAGENT_AUDIT_RETENTION_DAYS` accepts 30 through 365 inclusive. Daily purge deletes expired `audit_events` and `authorization_ledger_events` unless the row's account has an active explicit legal hold.

## Task 1: Lock Redis TTL And Key Policy

**Files:**
- Modify: `tests/control_plane/test_redis_keys.py`
- Modify: `src/control_plane/redis_keys.py`

- [ ] **Step 1: Replace the Redis key tests with the full Plan 4 policy**

Replace `tests/control_plane/test_redis_keys.py` with:

```python
from src.control_plane.redis_keys import RedisKey, RedisTtl


def test_keys_are_namespaced_and_contain_no_payload_data():
    assert RedisKey.relay_heartbeat("device-1") == "sa:relay:heartbeat:device-1"
    assert RedisKey.relay_session("device-1") == "sa:relay:session:device-1"
    assert RedisKey.replay_nonce("device-1", "nonce-1") == "sa:relay:nonce:device-1:nonce-1"
    assert RedisKey.invocation("corr-1") == "sa:invocation:corr-1"
    assert RedisKey.job_reference("job-ref-1") == "sa:job_ref:job-ref-1"
    assert RedisKey.redacted_preview("preview-1") == "sa:preview:redacted:preview-1"
    assert RedisKey.approval_request("approval-1") == "sa:approval:request:approval-1"
    assert RedisKey.approval_locator("locator-hash-1") == "sa:approval:locator:locator-hash-1"
    assert RedisKey.execution_grant("approval-1") == "sa:approval:grant:approval-1"
    assert RedisKey.approval_browser_session("session-1") == "sa:approval:session:session-1"
    assert RedisKey.provider_poll("pc-1", "poll-1") == "sa:poll:pc-1:poll-1"
    assert RedisKey.label_download_reference("label-ref-1") == "sa:label:download:label-ref-1"
    assert RedisKey.label_stream_lease("label-ref-1", "browser-session-1") == (
        "sa:label:lease:label-ref-1:browser-session-1"
    )
    assert RedisKey.rate_limit("pc-1", "estimate", "1234") == "sa:rate:pc-1:estimate:1234"
    assert RedisKey.loop_guard("pc-1", "get_job_status", "hash-1") == (
        "sa:loop:pc-1:get_job_status:hash-1"
    )


def test_plan_4_ttls_match_ephemeral_retention_decisions():
    assert RedisTtl.RELAY_HEARTBEAT_SECONDS == 90
    assert RedisTtl.RELAY_SESSION_SECONDS == 300
    assert RedisTtl.REPLAY_NONCE_SECONDS == 300
    assert RedisTtl.INVOCATION_SECONDS == 86400
    assert RedisTtl.JOB_REFERENCE_SECONDS == 86400
    assert RedisTtl.REDACTED_PREVIEW_SECONDS == 86400
    assert RedisTtl.APPROVAL_REQUEST_SECONDS == 900
    assert RedisTtl.APPROVAL_LOCATOR_SECONDS == 900
    assert RedisTtl.EXECUTION_GRANT_SECONDS == 900
    assert RedisTtl.APPROVAL_BROWSER_SESSION_SECONDS == 1800
    assert RedisTtl.PROVIDER_POLL_SECONDS == 86400
    assert RedisTtl.LABEL_DOWNLOAD_REFERENCE_SECONDS == 300
    assert RedisTtl.LABEL_STREAM_LEASE_SECONDS == 30
    assert RedisTtl.RATE_LIMIT_SECONDS == 60
    assert RedisTtl.LOOP_GUARD_SECONDS == 60
    assert RedisTtl.SWEEP_INTERVAL_SECONDS == 300


def test_ephemeral_patterns_cover_ttl_owned_prefixes_only():
    assert RedisKey.ephemeral_patterns() == (
        "sa:relay:heartbeat:*",
        "sa:relay:session:*",
        "sa:relay:nonce:*",
        "sa:invocation:*",
        "sa:job_ref:*",
        "sa:preview:redacted:*",
        "sa:approval:request:*",
        "sa:approval:locator:*",
        "sa:approval:grant:*",
        "sa:approval:session:*",
        "sa:poll:*",
        "sa:label:download:*",
        "sa:label:lease:*",
        "sa:rate:*",
        "sa:loop:*",
    )
```

- [ ] **Step 2: Run the focused Redis key test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_redis_keys.py -v
```

Expected: FAIL with `AttributeError: type object 'RedisKey' has no attribute 'relay_heartbeat'`.

- [ ] **Step 3: Extend `src/control_plane/redis_keys.py` with the TTL policy implementation**

Merge the following policy into `src/control_plane/redis_keys.py`. Preserve any Plan 1, Plan 2, or Plan 5 helpers already present in the file; if a helper name already exists, keep the same public name and update only the TTL value or key format needed by this task.

```python
class RedisTtl:
    RELAY_HEARTBEAT_SECONDS = 90
    RELAY_SESSION_SECONDS = 300
    REPLAY_NONCE_SECONDS = 300
    INVOCATION_SECONDS = 86400
    JOB_REFERENCE_SECONDS = 86400
    REDACTED_PREVIEW_SECONDS = 86400
    APPROVAL_REQUEST_SECONDS = 900
    APPROVAL_LOCATOR_SECONDS = 900
    EXECUTION_GRANT_SECONDS = 900
    APPROVAL_BROWSER_SESSION_SECONDS = 1800
    PROVIDER_POLL_SECONDS = 86400
    TERMINAL_JOB_SECONDS = 86400
    LABEL_DOWNLOAD_REFERENCE_SECONDS = 300
    LABEL_STREAM_LEASE_SECONDS = 30
    RATE_LIMIT_SECONDS = 60
    LOOP_GUARD_SECONDS = 60
    SWEEP_INTERVAL_SECONDS = 300


class RedisKey:
    @staticmethod
    def relay_heartbeat(device_id: str) -> str:
        return f"sa:relay:heartbeat:{device_id}"

    @staticmethod
    def relay_session(device_id: str) -> str:
        return f"sa:relay:session:{device_id}"

    @staticmethod
    def replay_nonce(device_id: str, nonce: str) -> str:
        return f"sa:relay:nonce:{device_id}:{nonce}"

    @staticmethod
    def invocation(correlation_id: str) -> str:
        return f"sa:invocation:{correlation_id}"

    @staticmethod
    def job_reference(job_ref: str) -> str:
        return f"sa:job_ref:{job_ref}"

    @staticmethod
    def redacted_preview(preview_id: str) -> str:
        return f"sa:preview:redacted:{preview_id}"

    @staticmethod
    def approval_request(approval_request_id: str) -> str:
        return f"sa:approval:request:{approval_request_id}"

    @staticmethod
    def approval_locator(locator_hash: str) -> str:
        return f"sa:approval:locator:{locator_hash}"

    @staticmethod
    def execution_grant(approval_request_id: str) -> str:
        return f"sa:approval:grant:{approval_request_id}"

    @staticmethod
    def approval_browser_session(session_id: str) -> str:
        return f"sa:approval:session:{session_id}"

    @staticmethod
    def provider_poll(connection_id: str, reference: str) -> str:
        return f"sa:poll:{connection_id}:{reference}"

    @staticmethod
    def label_download_reference(reference: str) -> str:
        return f"sa:label:download:{reference}"

    @staticmethod
    def label_stream_lease(reference: str, browser_session_id: str) -> str:
        return f"sa:label:lease:{reference}:{browser_session_id}"

    @staticmethod
    def rate_limit(connection_id: str, rate_limit_class: str, minute_bucket: str) -> str:
        return f"sa:rate:{connection_id}:{rate_limit_class}:{minute_bucket}"

    @staticmethod
    def loop_guard(connection_id: str, tool_name: str, arguments_hash: str) -> str:
        return f"sa:loop:{connection_id}:{tool_name}:{arguments_hash}"

    @classmethod
    def ephemeral_patterns(cls) -> tuple[str, ...]:
        return (
            "sa:relay:heartbeat:*",
            "sa:relay:session:*",
            "sa:relay:nonce:*",
            "sa:invocation:*",
            "sa:job_ref:*",
            "sa:preview:redacted:*",
            "sa:approval:request:*",
            "sa:approval:locator:*",
            "sa:approval:grant:*",
            "sa:approval:session:*",
            "sa:poll:*",
            "sa:label:download:*",
            "sa:label:lease:*",
            "sa:rate:*",
            "sa:loop:*",
        )
```

- [ ] **Step 4: Run the focused Redis key test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_redis_keys.py -v
```

Expected: PASS with `3 passed`.

- [ ] **Step 5: Commit Redis policy**

Run:

```bash
git add src/control_plane/redis_keys.py tests/control_plane/test_redis_keys.py
git commit -m "feat: define control-plane ephemeral redis policy"
```

Expected: commit succeeds.

## Task 2: Add Retention Settings With Bounds

**Files:**
- Modify: `tests/control_plane/test_config.py`
- Modify: `src/control_plane/config.py`

- [ ] **Step 1: Add retention setting tests**

Replace `tests/control_plane/test_config.py` with:

```python
import pytest
from pydantic import ValidationError

from src.control_plane.config import AuthMode, ControlPlaneSettings, Environment


def settings(**updates):
    values = {
        "auth_mode": AuthMode.fake_local,
        "bind_host": "127.0.0.1",
        "public_base_url": "http://127.0.0.1:8080",
        "environment": Environment.local,
        "database_url": "postgresql+asyncpg://shipagent:shipagent@localhost/shipagent",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(updates)
    return ControlPlaneSettings(**values)


def test_fake_auth_accepts_loopback_only():
    from src.control_plane.startup import validate_startup_security

    validate_startup_security(settings())


@pytest.mark.parametrize(
    "updates",
    [
        {"bind_host": "0.0.0.0"},
        {"public_base_url": "https://dev-mcp.shipagent.app"},
        {"environment": "prototype"},
    ],
)
def test_fake_auth_rejects_public_or_deployed_modes(updates):
    from src.control_plane.startup import validate_startup_security

    with pytest.raises(RuntimeError, match="fake_local"):
        validate_startup_security(settings(**updates))


def test_audit_retention_defaults_to_90_days():
    assert settings().audit_retention_days == 90


@pytest.mark.parametrize("days", [30, 90, 365])
def test_audit_retention_accepts_bounded_values(days):
    assert settings(audit_retention_days=days).audit_retention_days == days


@pytest.mark.parametrize("days", [29, 366])
def test_audit_retention_rejects_unbounded_values(days):
    with pytest.raises(ValidationError):
        settings(audit_retention_days=days)


def test_retention_worker_intervals_default_to_spec_values():
    configured = settings()

    assert configured.retention_redis_sweep_interval_seconds == 300
    assert configured.retention_sql_purge_interval_seconds == 86400
    assert configured.retention_background_tasks_enabled is True


def test_retention_background_tasks_can_be_disabled_for_tests():
    configured = settings(retention_background_tasks_enabled=False)

    assert configured.retention_background_tasks_enabled is False
```

- [ ] **Step 2: Run the focused config test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_config.py -v
```

Expected: FAIL with `AttributeError: 'ControlPlaneSettings' object has no attribute 'audit_retention_days'`.

- [ ] **Step 3: Add retention settings to `ControlPlaneSettings`**

Replace `src/control_plane/config.py` with:

```python
from enum import StrEnum

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.control_plane.redis_keys import RedisTtl


class AuthMode(StrEnum):
    auth0 = "auth0"
    fake_local = "fake_local"


class Environment(StrEnum):
    local = "local"
    prototype = "prototype"
    beta = "beta"
    production = "production"


class ControlPlaneSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHIPAGENT_", extra="ignore")

    auth_mode: AuthMode = AuthMode.auth0
    environment: Environment = Environment.local
    bind_host: str = "127.0.0.1"
    public_base_url: AnyHttpUrl | None = None
    database_url: str
    redis_url: str
    auth0_issuer: str = ""
    auth0_audience: str = ""
    relay_signing_secret: str = Field(default="", min_length=0)
    audit_retention_days: int = Field(default=90, ge=30, le=365)
    retention_redis_sweep_interval_seconds: int = Field(
        default=RedisTtl.SWEEP_INTERVAL_SECONDS,
        ge=60,
        le=3600,
    )
    retention_sql_purge_interval_seconds: int = Field(
        default=86400,
        ge=3600,
        le=172800,
    )
    retention_background_tasks_enabled: bool = True
    auth0_provider_clients: dict[str, str] = Field(
        default_factory=lambda: {
            "chatgpt-client": "chatgpt",
            "claude-client": "claude_ai",
            "desktop-client": "desktop",
            "operator-client": "operator",
        }
    )
```

- [ ] **Step 4: Run the focused config test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_config.py -v
```

Expected: PASS with all config tests passing.

- [ ] **Step 5: Commit retention settings**

Run:

```bash
git add src/control_plane/config.py tests/control_plane/test_config.py
git commit -m "feat: add bounded control-plane retention settings"
```

Expected: commit succeeds.

## Task 3: Add Authorization Ledger And Legal Hold Models

**Files:**
- Modify: `tests/control_plane/test_models.py`
- Modify: `src/control_plane/audit/models.py`
- Modify: `alembic/env.py`
- Create: `alembic/versions/20260630_0004_ephemeral_retention_authorization_audit.py`

- [ ] **Step 1: Add model shape tests**

Replace `tests/control_plane/test_models.py` with:

```python
from sqlalchemy import select

from src.control_plane.audit.models import (
    ControlPlaneAuthorizationLedgerEvent,
    ControlPlaneLegalHold,
)
from src.control_plane.models import CloudAccount, ProviderConnection


async def test_auth0_subject_maps_to_one_cloud_account(control_db):
    account = CloudAccount(auth0_subject="auth0|owner-1")
    control_db.add(account)
    await control_db.commit()

    loaded = await control_db.scalar(
        select(CloudAccount).where(
            CloudAccount.auth0_subject == "auth0|owner-1"
        )
    )
    assert loaded.id == account.id


def test_provider_connection_never_owns_account_identity():
    columns = ProviderConnection.__table__.columns
    assert "account_id" in columns
    assert "provider_subject" not in columns


def test_authorization_ledger_uses_hashed_and_opaque_fields():
    columns = ControlPlaneAuthorizationLedgerEvent.__table__.columns

    assert "approval_request_id" in columns
    assert "preview_hash" in columns
    assert "purchase_scope_hash" in columns
    assert "authorized_amount_minor" in columns
    assert "currency" in columns
    assert "approving_subject_hash" in columns
    assert "execution_target_fingerprint_hash" in columns
    assert "grant_transition" in columns
    assert "idempotency_key_hash" in columns
    assert "result_category" in columns
    assert "correlation_id" in columns

    forbidden_columns = {
        "preview_json",
        "row_data",
        "recipient_name",
        "recipient_address",
        "label_bytes",
        "tracking_number",
        "execution_token",
        "approval_url",
        "provider_prompt",
        "raw_payload",
    }
    assert forbidden_columns.isdisjoint(set(columns.keys()))


def test_legal_hold_is_explicit_and_releasable():
    columns = ControlPlaneLegalHold.__table__.columns

    assert "account_id" in columns
    assert "reason_hash" in columns
    assert "created_by_actor_hash" in columns
    assert "released_by_actor_hash" in columns
    assert "released_at" in columns
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_models.py -v
```

Expected: FAIL with `ImportError: cannot import name 'ControlPlaneAuthorizationLedgerEvent'`.

- [ ] **Step 3: Add ledger and legal hold models**

Replace `src/control_plane/audit/models.py` with:

```python
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.control_plane.models import ControlPlaneBase


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class ControlPlaneAuditEvent(ControlPlaneBase):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    account_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider_connection_id: Mapped[str | None] = mapped_column(String(36))
    device_id: Mapped[str | None] = mapped_column(String(36))
    actor_id_hash: Mapped[str] = mapped_column(String(64))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )


class ControlPlaneAuthorizationLedgerEvent(ControlPlaneBase):
    __tablename__ = "authorization_ledger_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    provider_connection_id: Mapped[str] = mapped_column(String(36), index=True)
    approval_request_id: Mapped[str] = mapped_column(String(128), index=True)
    preview_hash: Mapped[str] = mapped_column(String(64))
    purchase_scope_hash: Mapped[str] = mapped_column(String(64))
    authorized_amount_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    approving_subject_hash: Mapped[str | None] = mapped_column(String(64))
    execution_target_fingerprint_hash: Mapped[str | None] = mapped_column(String(64))
    grant_transition: Mapped[str | None] = mapped_column(String(64))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    result_category: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )


class ControlPlaneLegalHold(ControlPlaneBase):
    __tablename__ = "legal_holds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    reason_hash: Mapped[str] = mapped_column(String(64))
    created_by_actor_hash: Mapped[str] = mapped_column(String(64))
    released_by_actor_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
```

- [ ] **Step 4: Update Alembic metadata imports**

Replace `alembic/env.py` with:

```python
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.control_plane.audit.models import (
    ControlPlaneAuditEvent,
    ControlPlaneAuthorizationLedgerEvent,
    ControlPlaneLegalHold,
)
from src.control_plane.models import CloudAccount, ControlPlaneBase, ProviderConnection


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = ControlPlaneBase.metadata


def _import_all_models() -> None:
    ControlPlaneBase.metadata
    CloudAccount
    ProviderConnection
    ControlPlaneAuditEvent
    ControlPlaneAuthorizationLedgerEvent
    ControlPlaneLegalHold


def _target_schema() -> str:
    return config.get_section("alembic:runtime").get(
        "shipagent_control_plane_schema",
        os.environ.get("SHIPAGENT_CONTROL_PLANE_SCHEMA", "shipagent_private"),
    )


def run_migrations_offline() -> None:
    _import_all_models()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _import_all_models()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schema = _target_schema()
        connection.execute(
            f'CREATE SCHEMA IF NOT EXISTS "{schema}"'
        )
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=schema,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: Create the migration**

Create `alembic/versions/20260630_0004_ephemeral_retention_authorization_audit.py` with:

```python
"""Add authorization ledger and legal holds."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260630_0004"
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
        "authorization_ledger_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("provider_connection_id", sa.String(length=36), nullable=False),
        sa.Column("approval_request_id", sa.String(length=128), nullable=False),
        sa.Column("preview_hash", sa.String(length=64), nullable=False),
        sa.Column("purchase_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("authorized_amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("approving_subject_hash", sa.String(length=64), nullable=True),
        sa.Column("execution_target_fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("grant_transition", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("result_category", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_index(
        "ix_authorization_ledger_events_event_type",
        "authorization_ledger_events",
        ["event_type"],
        schema=schema,
    )
    op.create_index(
        "ix_authorization_ledger_events_account_id",
        "authorization_ledger_events",
        ["account_id"],
        schema=schema,
    )
    op.create_index(
        "ix_authorization_ledger_events_provider_connection_id",
        "authorization_ledger_events",
        ["provider_connection_id"],
        schema=schema,
    )
    op.create_index(
        "ix_authorization_ledger_events_approval_request_id",
        "authorization_ledger_events",
        ["approval_request_id"],
        schema=schema,
    )
    op.create_index(
        "ix_authorization_ledger_events_correlation_id",
        "authorization_ledger_events",
        ["correlation_id"],
        schema=schema,
    )
    op.create_index(
        "ix_authorization_ledger_events_created_at",
        "authorization_ledger_events",
        ["created_at"],
        schema=schema,
    )

    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("reason_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_actor_hash", sa.String(length=64), nullable=False),
        sa.Column("released_by_actor_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_index(
        "ix_legal_holds_account_id",
        "legal_holds",
        ["account_id"],
        schema=schema,
    )
    op.create_index(
        "ix_legal_holds_created_at",
        "legal_holds",
        ["created_at"],
        schema=schema,
    )
    op.create_index(
        "ix_legal_holds_released_at",
        "legal_holds",
        ["released_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_table("legal_holds", schema=schema)
    op.drop_table("authorization_ledger_events", schema=schema)
```

- [ ] **Step 6: Run model tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_models.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit models and migration**

Run:

```bash
git add alembic/env.py alembic/versions/20260630_0004_ephemeral_retention_authorization_audit.py src/control_plane/audit/models.py tests/control_plane/test_models.py
git commit -m "feat: add authorization ledger retention models"
```

Expected: commit succeeds.

## Task 4: Add Strict Hashed Authorization Ledger Service

**Files:**
- Create: `src/control_plane/audit/hash_validation.py`
- Create: `src/control_plane/audit/authorization_ledger.py`
- Modify: `src/control_plane/audit/__init__.py`
- Create: `tests/control_plane/audit/test_authorization_ledger.py`

- [ ] **Step 1: Add authorization ledger service tests**

Create `tests/control_plane/audit/test_authorization_ledger.py` with:

```python
import hashlib

import pytest
from sqlalchemy import func, select

from src.control_plane.audit import AuthorizationLedgerService
from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def test_record_persists_only_hashed_authorization_metadata(control_db):
    event = await AuthorizationLedgerService.record(
        session=control_db,
        event_type="approval_decision_recorded",
        account_id="acct-1",
        provider_connection_id="pc-1",
        approval_request_id="approval_abc123",
        preview_hash=sha256_hex("preview"),
        purchase_scope_hash=sha256_hex("purchase-scope"),
        authorized_amount_minor=1299,
        currency="usd",
        approving_subject_hash=sha256_hex("auth0|owner-1"),
        execution_target_fingerprint_hash=sha256_hex("target-fingerprint"),
        grant_transition="approved",
        idempotency_key_hash=sha256_hex("idempotency-key"),
        result_category="success",
        correlation_id="corr-1",
    )
    await control_db.commit()

    loaded = await control_db.scalar(
        select(ControlPlaneAuthorizationLedgerEvent).where(
            ControlPlaneAuthorizationLedgerEvent.id == event.id
        )
    )

    assert loaded is not None
    assert loaded.event_type == "approval_decision_recorded"
    assert loaded.account_id == "acct-1"
    assert loaded.provider_connection_id == "pc-1"
    assert loaded.approval_request_id == "approval_abc123"
    assert loaded.currency == "USD"
    assert loaded.authorized_amount_minor == 1299
    assert loaded.approving_subject_hash == sha256_hex("auth0|owner-1")
    assert loaded.grant_transition == "approved"
    assert loaded.result_category == "success"


@pytest.mark.parametrize(
    ("field_name", "updates"),
    [
        ("preview_hash", {"preview_hash": "recipient address"}),
        ("purchase_scope_hash", {"purchase_scope_hash": "not-a-hash"}),
        ("approving_subject_hash", {"approving_subject_hash": "auth0|owner-1"}),
        ("execution_target_fingerprint_hash", {"execution_target_fingerprint_hash": "target-1"}),
        ("idempotency_key_hash", {"idempotency_key_hash": "idem-1"}),
    ],
)
async def test_record_rejects_raw_or_non_hash_values(control_db, field_name, updates):
    values = {
        "session": control_db,
        "event_type": "execution_grant_transition",
        "account_id": "acct-1",
        "provider_connection_id": "pc-1",
        "approval_request_id": "approval_abc123",
        "preview_hash": sha256_hex("preview"),
        "purchase_scope_hash": sha256_hex("purchase-scope"),
        "authorized_amount_minor": 1299,
        "currency": "USD",
        "approving_subject_hash": sha256_hex("auth0|owner-1"),
        "execution_target_fingerprint_hash": sha256_hex("target-fingerprint"),
        "grant_transition": "reserved",
        "idempotency_key_hash": sha256_hex("idempotency-key"),
        "result_category": "success",
        "correlation_id": "corr-1",
    }
    values.update(updates)

    with pytest.raises(ValueError, match=f"{field_name} must be a sha256 hex digest"):
        await AuthorizationLedgerService.record(**values)


@pytest.mark.parametrize(
    "approval_request_id",
    [
        "https://app.shipagent.example/approve/approval_abc123",
        "approval/abc123",
        "approval?abc123",
        "approval#abc123",
    ],
)
async def test_record_rejects_url_or_path_like_approval_references(
    control_db,
    approval_request_id,
):
    with pytest.raises(ValueError, match="approval_request_id must be an opaque reference"):
        await AuthorizationLedgerService.record(
            session=control_db,
            event_type="approval_request_created",
            account_id="acct-1",
            provider_connection_id="pc-1",
            approval_request_id=approval_request_id,
            preview_hash=sha256_hex("preview"),
            purchase_scope_hash=sha256_hex("purchase-scope"),
        )


async def test_cleanup_for_account_deletes_only_ledger_rows_for_account(control_db):
    for account_id in ("acct-a", "acct-b"):
        await AuthorizationLedgerService.record(
            session=control_db,
            event_type="approval_request_created",
            account_id=account_id,
            provider_connection_id=f"pc-{account_id}",
            approval_request_id=f"approval_{account_id}",
            preview_hash=sha256_hex(f"preview-{account_id}"),
            purchase_scope_hash=sha256_hex(f"scope-{account_id}"),
        )
    await control_db.commit()

    deleted = await AuthorizationLedgerService.cleanup_for_account(
        session=control_db,
        account_id="acct-a",
    )

    assert deleted == 1
    remaining_acct_a = await control_db.scalar(
        select(func.count())
        .select_from(ControlPlaneAuthorizationLedgerEvent)
        .where(ControlPlaneAuthorizationLedgerEvent.account_id == "acct-a")
    )
    remaining_acct_b = await control_db.scalar(
        select(func.count())
        .select_from(ControlPlaneAuthorizationLedgerEvent)
        .where(ControlPlaneAuthorizationLedgerEvent.account_id == "acct-b")
    )
    assert remaining_acct_a == 0
    assert remaining_acct_b == 1
```

- [ ] **Step 2: Run ledger service tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/audit/test_authorization_ledger.py -v
```

Expected: FAIL with `ImportError: cannot import name 'AuthorizationLedgerService'`.

- [ ] **Step 3: Add shared hash validation helpers**

Create `src/control_plane/audit/hash_validation.py` with:

```python
import re


_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


def require_sha256_hex(field_name: str, value: str) -> str:
    if not _SHA256_HEX_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a sha256 hex digest")
    return value


def require_optional_sha256_hex(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return require_sha256_hex(field_name, value)


def require_opaque_reference(field_name: str, value: str, *, max_length: int = 128) -> str:
    if not value or len(value) > max_length:
        raise ValueError(f"{field_name} must be an opaque reference")
    if "://" in value or "/" in value or "?" in value or "#" in value or ":" in value:
        raise ValueError(f"{field_name} must be an opaque reference")
    return value
```

- [ ] **Step 4: Add the authorization ledger service**

Create `src/control_plane/audit/authorization_ledger.py` with:

```python
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.hash_validation import (
    require_opaque_reference,
    require_optional_sha256_hex,
    require_sha256_hex,
)
from src.control_plane.audit.models import ControlPlaneAuthorizationLedgerEvent


class AuthorizationLedgerService:
    _ALLOWED_EVENT_TYPES = {
        "approval_request_created",
        "approval_decision_recorded",
        "execution_grant_transition",
        "provider_tool_result",
    }
    _ALLOWED_GRANT_TRANSITIONS = {
        None,
        "requested",
        "reserved",
        "approved",
        "rejected",
        "consumed",
        "expired",
        "revoked",
        "replay_rejected",
    }
    _ALLOWED_RESULT_CATEGORIES = {
        None,
        "success",
        "blocked",
        "unavailable",
        "processing_unknown",
        "validation",
        "authorization",
        "provider",
        "policy",
        "rate_limit",
        "error",
    }

    @classmethod
    async def record(
        cls,
        *,
        session: AsyncSession,
        event_type: str,
        account_id: str,
        provider_connection_id: str,
        approval_request_id: str,
        preview_hash: str,
        purchase_scope_hash: str,
        authorized_amount_minor: int | None = None,
        currency: str | None = None,
        approving_subject_hash: str | None = None,
        execution_target_fingerprint_hash: str | None = None,
        grant_transition: str | None = None,
        idempotency_key_hash: str | None = None,
        result_category: str | None = None,
        correlation_id: str | None = None,
    ) -> ControlPlaneAuthorizationLedgerEvent:
        if event_type not in cls._ALLOWED_EVENT_TYPES:
            raise ValueError("unsupported authorization ledger event type")
        if grant_transition not in cls._ALLOWED_GRANT_TRANSITIONS:
            raise ValueError("unsupported execution grant transition")
        if result_category not in cls._ALLOWED_RESULT_CATEGORIES:
            raise ValueError("unsupported result category")
        if authorized_amount_minor is not None and authorized_amount_minor < 0:
            raise ValueError("authorized_amount_minor must be non-negative")
        normalized_currency = cls._normalize_currency(currency)

        event = ControlPlaneAuthorizationLedgerEvent(
            event_type=event_type,
            account_id=account_id,
            provider_connection_id=provider_connection_id,
            approval_request_id=require_opaque_reference(
                "approval_request_id",
                approval_request_id,
            ),
            preview_hash=require_sha256_hex("preview_hash", preview_hash),
            purchase_scope_hash=require_sha256_hex(
                "purchase_scope_hash",
                purchase_scope_hash,
            ),
            authorized_amount_minor=authorized_amount_minor,
            currency=normalized_currency,
            approving_subject_hash=require_optional_sha256_hex(
                "approving_subject_hash",
                approving_subject_hash,
            ),
            execution_target_fingerprint_hash=require_optional_sha256_hex(
                "execution_target_fingerprint_hash",
                execution_target_fingerprint_hash,
            ),
            grant_transition=grant_transition,
            idempotency_key_hash=require_optional_sha256_hex(
                "idempotency_key_hash",
                idempotency_key_hash,
            ),
            result_category=result_category,
            correlation_id=correlation_id,
        )
        session.add(event)
        await session.flush()
        return event

    @classmethod
    async def cleanup_for_account(cls, session: AsyncSession, account_id: str) -> int:
        result = await session.execute(
            delete(ControlPlaneAuthorizationLedgerEvent).where(
                ControlPlaneAuthorizationLedgerEvent.account_id == account_id
            )
        )
        return result.rowcount or 0

    @classmethod
    def _normalize_currency(cls, currency: str | None) -> str | None:
        if currency is None:
            return None
        normalized = currency.upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO currency code")
        return normalized
```

- [ ] **Step 5: Export the ledger service and models**

Replace `src/control_plane/audit/__init__.py` with:

```python
"""Audit primitives for control-plane immutable operations."""

from src.control_plane.audit.authorization_ledger import AuthorizationLedgerService
from src.control_plane.audit.models import (
    ControlPlaneAuditEvent,
    ControlPlaneAuthorizationLedgerEvent,
    ControlPlaneLegalHold,
)
from src.control_plane.audit.service import ControlPlaneAuditService

__all__ = [
    "AuthorizationLedgerService",
    "ControlPlaneAuditEvent",
    "ControlPlaneAuditService",
    "ControlPlaneAuthorizationLedgerEvent",
    "ControlPlaneLegalHold",
]
```

- [ ] **Step 6: Run ledger service tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/audit/test_authorization_ledger.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit ledger service**

Run:

```bash
git add src/control_plane/audit/__init__.py src/control_plane/audit/authorization_ledger.py src/control_plane/audit/hash_validation.py tests/control_plane/audit/test_authorization_ledger.py
git commit -m "feat: record hashed authorization ledger events"
```

Expected: commit succeeds.

## Task 5: Add Redis Ephemeral State Sweeper

**Files:**
- Create: `src/control_plane/retention/__init__.py`
- Create: `src/control_plane/retention/redis_sweeper.py`
- Create: `tests/control_plane/retention/__init__.py`
- Create: `tests/control_plane/retention/test_redis_sweeper.py`

- [ ] **Step 1: Add Redis sweeper tests**

Create `tests/control_plane/retention/__init__.py` with:

```python
"""Control-plane retention tests."""
```

Create `tests/control_plane/retention/test_redis_sweeper.py` with:

```python
import fnmatch

from src.control_plane.retention.redis_sweeper import sweep_ephemeral_redis_keys


class FakeRedis:
    def __init__(self, ttl_by_key: dict[str | bytes, int]) -> None:
        self.ttl_by_key = dict(ttl_by_key)
        self.deleted: list[str | bytes] = []

    async def scan_iter(self, match: str, count: int):
        for key in list(self.ttl_by_key):
            text_key = key.decode("utf-8") if isinstance(key, bytes) else key
            if fnmatch.fnmatch(text_key, match):
                yield key

    async def ttl(self, key: str | bytes) -> int:
        return self.ttl_by_key[key]

    async def delete(self, *keys: str | bytes) -> int:
        self.deleted.extend(keys)
        for key in keys:
            self.ttl_by_key.pop(key, None)
        return len(keys)


async def test_sweeper_deletes_ephemeral_keys_without_ttl():
    redis = FakeRedis(
        {
            "sa:relay:session:device-1": -1,
            "sa:invocation:corr-1": 120,
            "sa:label:download:label-1": -1,
            "unrelated:key": -1,
        }
    )

    result = await sweep_ephemeral_redis_keys(redis)

    assert result.scanned == 3
    assert result.deleted == 2
    assert sorted(redis.deleted) == [
        "sa:label:download:label-1",
        "sa:relay:session:device-1",
    ]
    assert "sa:invocation:corr-1" in redis.ttl_by_key
    assert "unrelated:key" in redis.ttl_by_key


async def test_sweeper_handles_bytes_keys_from_binary_redis_client():
    redis = FakeRedis({b"sa:approval:grant:approval-1": -1})

    result = await sweep_ephemeral_redis_keys(redis)

    assert result.scanned == 1
    assert result.deleted == 1
    assert redis.deleted == [b"sa:approval:grant:approval-1"]


async def test_sweeper_ignores_keys_already_missing():
    redis = FakeRedis({"sa:rate:pc-1:estimate:1234": -2})

    result = await sweep_ephemeral_redis_keys(redis)

    assert result.scanned == 1
    assert result.deleted == 0
    assert redis.deleted == []
```

- [ ] **Step 2: Run Redis sweeper tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/retention/test_redis_sweeper.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.retention'`.

- [ ] **Step 3: Add retention package and Redis sweeper**

Create `src/control_plane/retention/__init__.py` with:

```python
"""Control-plane retention and purge helpers."""
```

Create `src/control_plane/retention/redis_sweeper.py` with:

```python
from dataclasses import dataclass

from src.control_plane.redis_keys import RedisKey


@dataclass(frozen=True)
class RedisSweepResult:
    scanned: int
    deleted: int


def _decode_key_for_match(key: str | bytes) -> str:
    if isinstance(key, bytes):
        return key.decode("utf-8")
    return key


async def sweep_ephemeral_redis_keys(
    redis_client,
    *,
    patterns: tuple[str, ...] | None = None,
    scan_count: int = 500,
) -> RedisSweepResult:
    ttl_patterns = patterns or RedisKey.ephemeral_patterns()
    scanned = 0
    deleted = 0

    for pattern in ttl_patterns:
        async for key in redis_client.scan_iter(match=pattern, count=scan_count):
            scanned += 1
            ttl = await redis_client.ttl(key)
            if ttl == -1:
                deleted += int(await redis_client.delete(key))
            elif ttl == -2:
                _decode_key_for_match(key)

    return RedisSweepResult(scanned=scanned, deleted=deleted)
```

- [ ] **Step 4: Run Redis sweeper tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/retention/test_redis_sweeper.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Redis sweeper**

Run:

```bash
git add src/control_plane/retention/__init__.py src/control_plane/retention/redis_sweeper.py tests/control_plane/retention/__init__.py tests/control_plane/retention/test_redis_sweeper.py
git commit -m "feat: sweep ttl-less ephemeral redis keys"
```

Expected: commit succeeds.

## Task 6: Add SQL Purge And Legal Hold Guard

**Files:**
- Create: `src/control_plane/retention/legal_hold.py`
- Create: `src/control_plane/retention/sql_purge.py`
- Create: `tests/control_plane/retention/test_sql_purge.py`
- Modify: `tests/control_plane/audit/test_service.py`

- [ ] **Step 1: Add SQL purge and legal hold tests**

Create `tests/control_plane/retention/test_sql_purge.py` with:

```python
import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from src.control_plane.audit import AuthorizationLedgerService, ControlPlaneAuditService
from src.control_plane.audit.models import (
    ControlPlaneAuditEvent,
    ControlPlaneAuthorizationLedgerEvent,
    ControlPlaneLegalHold,
)
from src.control_plane.retention.legal_hold import LegalHoldService
from src.control_plane.retention.sql_purge import purge_expired_authorization_audit


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _record_audit(control_db, account_id: str, created_at: datetime):
    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="provider_tool_result",
        actor_id_hash=sha256_hex(f"actor-{account_id}"),
        account_id=account_id,
        ids={"correlation_id": f"corr-{account_id}"},
    )
    event.created_at = created_at
    return event


async def _record_ledger(control_db, account_id: str, created_at: datetime):
    event = await AuthorizationLedgerService.record(
        session=control_db,
        event_type="provider_tool_result",
        account_id=account_id,
        provider_connection_id=f"pc-{account_id}",
        approval_request_id=f"approval_{account_id}",
        preview_hash=sha256_hex(f"preview-{account_id}"),
        purchase_scope_hash=sha256_hex(f"scope-{account_id}"),
        result_category="success",
    )
    event.created_at = created_at
    return event


async def test_purge_deletes_expired_rows_and_keeps_active_legal_hold_rows(control_db):
    now = datetime(2026, 6, 30, tzinfo=UTC)
    old = now - timedelta(days=91)
    fresh = now - timedelta(days=10)

    await _record_audit(control_db, "acct-delete", old)
    await _record_ledger(control_db, "acct-delete", old)
    await _record_audit(control_db, "acct-fresh", fresh)
    await _record_ledger(control_db, "acct-fresh", fresh)
    await _record_audit(control_db, "acct-held", old)
    await _record_ledger(control_db, "acct-held", old)
    await LegalHoldService.place(
        session=control_db,
        account_id="acct-held",
        reason_hash=sha256_hex("legal hold reason"),
        actor_id_hash=sha256_hex("operator"),
        now_fn=lambda: now,
    )
    await control_db.commit()

    result = await purge_expired_authorization_audit(
        session=control_db,
        retention_days=90,
        now_fn=lambda: now,
    )

    assert result.audit_events_deleted == 1
    assert result.authorization_ledger_events_deleted == 1
    assert result.cutoff == now - timedelta(days=90)

    remaining_audit_accounts = {
        row[0]
        for row in (
            await control_db.execute(select(ControlPlaneAuditEvent.account_id))
        ).all()
    }
    remaining_ledger_accounts = {
        row[0]
        for row in (
            await control_db.execute(
                select(ControlPlaneAuthorizationLedgerEvent.account_id)
            )
        ).all()
    }
    assert "acct-delete" not in remaining_audit_accounts
    assert "acct-delete" not in remaining_ledger_accounts
    assert {"acct-fresh", "acct-held"}.issubset(remaining_audit_accounts)
    assert {"acct-fresh", "acct-held"}.issubset(remaining_ledger_accounts)


async def test_purge_rejects_out_of_policy_retention_days(control_db):
    now = datetime(2026, 6, 30, tzinfo=UTC)

    for retention_days in (29, 366):
        try:
            await purge_expired_authorization_audit(
                session=control_db,
                retention_days=retention_days,
                now_fn=lambda: now,
            )
        except ValueError as exc:
            assert str(exc) == "retention_days must be between 30 and 365"
        else:
            raise AssertionError("expected ValueError")


async def test_legal_hold_service_records_explicit_hold_and_release(control_db):
    now = datetime(2026, 6, 30, tzinfo=UTC)
    later = now + timedelta(hours=1)

    hold = await LegalHoldService.place(
        session=control_db,
        account_id="acct-held",
        reason_hash=sha256_hex("reason"),
        actor_id_hash=sha256_hex("operator"),
        now_fn=lambda: now,
    )
    await control_db.commit()

    assert await LegalHoldService.has_active_hold(
        session=control_db,
        account_id="acct-held",
    )

    released = await LegalHoldService.release(
        session=control_db,
        hold_id=hold.id,
        actor_id_hash=sha256_hex("operator-release"),
        now_fn=lambda: later,
    )
    await control_db.commit()

    assert released.released_at == later
    assert released.released_by_actor_hash == sha256_hex("operator-release")
    assert not await LegalHoldService.has_active_hold(
        session=control_db,
        account_id="acct-held",
    )

    hold_count = await control_db.scalar(
        select(func.count()).select_from(ControlPlaneLegalHold)
    )
    audit_types = {
        row[0]
        for row in (
            await control_db.execute(select(ControlPlaneAuditEvent.event_type))
        ).all()
    }
    assert hold_count == 1
    assert {"legal_hold_placed", "legal_hold_released"}.issubset(audit_types)
```

- [ ] **Step 2: Run SQL purge tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/retention/test_sql_purge.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.retention.legal_hold'`.

- [ ] **Step 3: Add legal hold service**

Create `src/control_plane/retention/legal_hold.py` with:

```python
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.hash_validation import require_sha256_hex
from src.control_plane.audit.models import ControlPlaneLegalHold, utc_now
from src.control_plane.audit.service import ControlPlaneAuditService


class LegalHoldService:
    @classmethod
    async def place(
        cls,
        *,
        session: AsyncSession,
        account_id: str,
        reason_hash: str,
        actor_id_hash: str,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> ControlPlaneLegalHold:
        hold = ControlPlaneLegalHold(
            account_id=account_id,
            reason_hash=require_sha256_hex("reason_hash", reason_hash),
            created_by_actor_hash=require_sha256_hex(
                "actor_id_hash",
                actor_id_hash,
            ),
            created_at=now_fn(),
        )
        session.add(hold)
        await session.flush()
        await ControlPlaneAuditService.record(
            session=session,
            event_type="legal_hold_placed",
            actor_id_hash=actor_id_hash,
            account_id=account_id,
            ids={"account_id": account_id},
            hashes={"actor_id_hash": actor_id_hash},
            safe_fields={"status": "active"},
        )
        return hold

    @classmethod
    async def release(
        cls,
        *,
        session: AsyncSession,
        hold_id: str,
        actor_id_hash: str,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> ControlPlaneLegalHold:
        actor_hash = require_sha256_hex("actor_id_hash", actor_id_hash)
        hold = await session.scalar(
            select(ControlPlaneLegalHold).where(ControlPlaneLegalHold.id == hold_id)
        )
        if hold is None:
            raise LookupError("legal hold not found")
        if hold.released_at is None:
            hold.released_at = now_fn()
            hold.released_by_actor_hash = actor_hash
            await ControlPlaneAuditService.record(
                session=session,
                event_type="legal_hold_released",
                actor_id_hash=actor_hash,
                account_id=hold.account_id,
                ids={"account_id": hold.account_id},
                hashes={"actor_id_hash": actor_hash},
                safe_fields={"status": "released"},
            )
            await session.flush()
        return hold

    @classmethod
    async def has_active_hold(cls, *, session: AsyncSession, account_id: str) -> bool:
        hold_id = await session.scalar(
            select(ControlPlaneLegalHold.id).where(
                ControlPlaneLegalHold.account_id == account_id,
                ControlPlaneLegalHold.released_at.is_(None),
            )
        )
        return hold_id is not None
```

- [ ] **Step 4: Add SQL purge service**

Create `src/control_plane/retention/sql_purge.py` with:

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.models import (
    ControlPlaneAuditEvent,
    ControlPlaneAuthorizationLedgerEvent,
    ControlPlaneLegalHold,
    utc_now,
)


@dataclass(frozen=True)
class SqlPurgeResult:
    cutoff: datetime
    audit_events_deleted: int
    authorization_ledger_events_deleted: int


def _validate_retention_days(retention_days: int) -> None:
    if retention_days < 30 or retention_days > 365:
        raise ValueError("retention_days must be between 30 and 365")


def _not_on_active_legal_hold(account_column):
    active_hold_accounts = select(ControlPlaneLegalHold.account_id).where(
        ControlPlaneLegalHold.released_at.is_(None)
    )
    return or_(
        account_column.is_(None),
        account_column.not_in(active_hold_accounts),
    )


async def purge_expired_authorization_audit(
    *,
    session: AsyncSession,
    retention_days: int,
    now_fn: Callable[[], datetime] = utc_now,
) -> SqlPurgeResult:
    _validate_retention_days(retention_days)
    cutoff = now_fn() - timedelta(days=retention_days)

    audit_result = await session.execute(
        delete(ControlPlaneAuditEvent).where(
            ControlPlaneAuditEvent.created_at < cutoff,
            _not_on_active_legal_hold(ControlPlaneAuditEvent.account_id),
        )
    )
    ledger_result = await session.execute(
        delete(ControlPlaneAuthorizationLedgerEvent).where(
            ControlPlaneAuthorizationLedgerEvent.created_at < cutoff,
            _not_on_active_legal_hold(
                ControlPlaneAuthorizationLedgerEvent.account_id
            ),
        )
    )

    return SqlPurgeResult(
        cutoff=cutoff,
        audit_events_deleted=audit_result.rowcount or 0,
        authorization_ledger_events_deleted=ledger_result.rowcount or 0,
    )
```

- [ ] **Step 5: Extend audit service tests for legal-hold event fields**

Append this test to `tests/control_plane/audit/test_service.py`:

```python
async def test_record_allows_legal_hold_status_values(control_db):
    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="legal_hold_placed",
        actor_id_hash="a" * 64,
        account_id="acct-1",
        ids={"account_id": "acct-1"},
        hashes={"actor_id_hash": "a" * 64},
        safe_fields={"status": "active"},
    )
    await control_db.commit()

    details = json.loads(event.details_json)
    assert details["ids"] == {"account_id": "acct-1"}
    assert details["hashes"] == {"actor_id_hash": "a" * 64}
    assert details["safe_fields"] == {"status": "active"}
```

- [ ] **Step 6: Run SQL purge and audit tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/retention/test_sql_purge.py tests/control_plane/audit/test_service.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit SQL purge and legal hold guard**

Run:

```bash
git add src/control_plane/retention/legal_hold.py src/control_plane/retention/sql_purge.py tests/control_plane/audit/test_service.py tests/control_plane/retention/test_sql_purge.py
git commit -m "feat: purge authorization audit with legal hold guard"
```

Expected: commit succeeds.

## Task 7: Add Account Deletion Cleanup

**Files:**
- Create: `src/control_plane/accounts/__init__.py`
- Create: `src/control_plane/accounts/service.py`
- Create: `tests/control_plane/accounts/__init__.py`
- Create: `tests/control_plane/accounts/test_service.py`

- [ ] **Step 1: Add account deletion cleanup tests**

Create `tests/control_plane/accounts/__init__.py` with:

```python
"""Control-plane account service tests."""
```

Create `tests/control_plane/accounts/test_service.py` with:

```python
import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from src.control_plane.accounts.service import CloudAccountDeletionService
from src.control_plane.audit import AuthorizationLedgerService, ControlPlaneAuditService
from src.control_plane.audit.models import (
    ControlPlaneAuditEvent,
    ControlPlaneAuthorizationLedgerEvent,
)
from src.control_plane.models import CloudAccount, ProviderConnection
from src.control_plane.retention.legal_hold import LegalHoldService


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _seed_account_with_audit(control_db, subject: str):
    account = CloudAccount(auth0_subject=subject)
    control_db.add(account)
    await control_db.flush()
    connection = ProviderConnection(
        account_id=account.id,
        client_id="chatgpt-client",
        surface="chatgpt",
        scopes_text="shipagent.preview",
        status="active",
    )
    control_db.add(connection)
    await control_db.flush()
    await ControlPlaneAuditService.record(
        session=control_db,
        event_type="provider_tool_result",
        actor_id_hash=sha256_hex("actor"),
        account_id=account.id,
        provider_connection_id=connection.id,
        ids={"correlation_id": "corr-1"},
    )
    await AuthorizationLedgerService.record(
        session=control_db,
        event_type="provider_tool_result",
        account_id=account.id,
        provider_connection_id=connection.id,
        approval_request_id="approval_abc123",
        preview_hash=sha256_hex("preview"),
        purchase_scope_hash=sha256_hex("scope"),
        result_category="success",
    )
    await control_db.commit()
    return account, connection


async def test_delete_account_purges_connections_audit_and_ledger(control_db):
    account, connection = await _seed_account_with_audit(
        control_db,
        "auth0|delete-me",
    )

    result = await CloudAccountDeletionService.delete_account(
        session=control_db,
        account_id=account.id,
        actor_id_hash=sha256_hex("operator"),
    )
    await control_db.commit()

    assert result.account_deleted is True
    assert result.provider_connections_deleted == 1
    assert result.audit_events_deleted == 1
    assert result.authorization_ledger_events_deleted == 1

    assert await control_db.scalar(
        select(CloudAccount).where(CloudAccount.id == account.id)
    ) is None
    assert await control_db.scalar(
        select(ProviderConnection).where(ProviderConnection.id == connection.id)
    ) is None
    assert await control_db.scalar(
        select(func.count()).select_from(ControlPlaneAuditEvent)
    ) == 0
    assert await control_db.scalar(
        select(func.count()).select_from(ControlPlaneAuthorizationLedgerEvent)
    ) == 0


async def test_delete_account_is_blocked_by_active_legal_hold(control_db):
    account, _connection = await _seed_account_with_audit(
        control_db,
        "auth0|held",
    )
    now = datetime(2026, 6, 30, tzinfo=UTC)
    await LegalHoldService.place(
        session=control_db,
        account_id=account.id,
        reason_hash=sha256_hex("legal hold"),
        actor_id_hash=sha256_hex("operator"),
        now_fn=lambda: now,
    )
    await control_db.commit()

    with pytest.raises(PermissionError, match="active legal hold"):
        await CloudAccountDeletionService.delete_account(
            session=control_db,
            account_id=account.id,
            actor_id_hash=sha256_hex("operator"),
        )

    assert await control_db.scalar(
        select(CloudAccount).where(CloudAccount.id == account.id)
    ) is not None
```

- [ ] **Step 2: Run account cleanup tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/accounts/test_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.accounts'`.

- [ ] **Step 3: Add account service package**

Create `src/control_plane/accounts/__init__.py` with:

```python
"""Cloud Account cleanup services."""

from src.control_plane.accounts.service import (
    AccountDeletionResult,
    CloudAccountDeletionService,
)

__all__ = [
    "AccountDeletionResult",
    "CloudAccountDeletionService",
]
```

- [ ] **Step 4: Add legal-hold-aware deletion service**

Create `src/control_plane/accounts/service.py` with:

```python
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit import AuthorizationLedgerService, ControlPlaneAuditService
from src.control_plane.audit.hash_validation import require_sha256_hex
from src.control_plane.models import CloudAccount, ProviderConnection
from src.control_plane.retention.legal_hold import LegalHoldService


@dataclass(frozen=True)
class AccountDeletionResult:
    account_deleted: bool
    provider_connections_deleted: int
    audit_events_deleted: int
    authorization_ledger_events_deleted: int


class CloudAccountDeletionService:
    @classmethod
    async def delete_account(
        cls,
        *,
        session: AsyncSession,
        account_id: str,
        actor_id_hash: str,
    ) -> AccountDeletionResult:
        require_sha256_hex("actor_id_hash", actor_id_hash)
        if await LegalHoldService.has_active_hold(
            session=session,
            account_id=account_id,
        ):
            await ControlPlaneAuditService.record(
                session=session,
                event_type="account_delete_blocked_legal_hold",
                actor_id_hash=actor_id_hash,
                account_id=account_id,
                ids={"account_id": account_id},
                hashes={"actor_id_hash": actor_id_hash},
                safe_fields={"status": "blocked"},
            )
            raise PermissionError("account deletion blocked by active legal hold")

        ledger_deleted = await AuthorizationLedgerService.cleanup_for_account(
            session=session,
            account_id=account_id,
        )
        audit_deleted = await ControlPlaneAuditService.cleanup_for_account(
            session=session,
            account_id=account_id,
        )
        connection_result = await session.execute(
            delete(ProviderConnection).where(ProviderConnection.account_id == account_id)
        )
        account_result = await session.execute(
            delete(CloudAccount).where(CloudAccount.id == account_id)
        )
        await session.flush()

        return AccountDeletionResult(
            account_deleted=(account_result.rowcount or 0) == 1,
            provider_connections_deleted=connection_result.rowcount or 0,
            audit_events_deleted=audit_deleted,
            authorization_ledger_events_deleted=ledger_deleted,
        )
```

- [ ] **Step 5: Run account cleanup tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/accounts/test_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit account cleanup**

Run:

```bash
git add src/control_plane/accounts/__init__.py src/control_plane/accounts/service.py tests/control_plane/accounts/__init__.py tests/control_plane/accounts/test_service.py
git commit -m "feat: clean up account audit data on deletion"
```

Expected: commit succeeds.

## Task 8: Schedule Retention Work In The Control Plane App

**Files:**
- Create: `src/control_plane/retention/tasks.py`
- Create: `tests/control_plane/retention/test_tasks.py`
- Modify: `src/control_plane/app.py`
- Modify: `tests/control_plane/test_app_auth.py`

- [ ] **Step 1: Add retention worker tests**

Create `tests/control_plane/retention/test_tasks.py` with:

```python
from src.control_plane.retention.redis_sweeper import RedisSweepResult
from src.control_plane.retention.sql_purge import SqlPurgeResult
from src.control_plane.retention.tasks import ControlPlaneRetentionWorker


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class FakeSessionFactory:
    def __init__(self) -> None:
        self.session = FakeSession()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_run_once_sweeps_redis_and_purges_sql():
    calls: list[str] = []
    session_factory = FakeSessionFactory()

    async def redis_sweep_fn(redis_client):
        calls.append(f"redis:{redis_client}")
        return RedisSweepResult(scanned=3, deleted=2)

    async def sql_purge_fn(*, session, retention_days):
        calls.append(f"sql:{retention_days}:{session is session_factory.session}")
        return SqlPurgeResult(
            cutoff=__import__("datetime").datetime(2026, 4, 1),
            audit_events_deleted=4,
            authorization_ledger_events_deleted=5,
        )

    worker = ControlPlaneRetentionWorker(
        redis_client="redis-client",
        session_factory=session_factory,
        audit_retention_days=90,
        redis_sweep_interval_seconds=300,
        sql_purge_interval_seconds=86400,
        redis_sweep_fn=redis_sweep_fn,
        sql_purge_fn=sql_purge_fn,
    )

    result = await worker.run_once()

    assert calls == ["redis:redis-client", "sql:90:True"]
    assert result.redis.scanned == 3
    assert result.redis.deleted == 2
    assert result.sql.audit_events_deleted == 4
    assert result.sql.authorization_ledger_events_deleted == 5
    assert session_factory.session.committed is True


async def test_disabled_worker_does_not_start_background_tasks():
    session_factory = FakeSessionFactory()
    worker = ControlPlaneRetentionWorker(
        redis_client="redis-client",
        session_factory=session_factory,
        audit_retention_days=90,
        redis_sweep_interval_seconds=300,
        sql_purge_interval_seconds=86400,
        enabled=False,
    )

    await worker.start()

    assert worker.running_task_count == 0
```

- [ ] **Step 2: Run retention worker tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/retention/test_tasks.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.control_plane.retention.tasks'`.

- [ ] **Step 3: Add retention worker implementation**

Create `src/control_plane/retention/tasks.py` with:

```python
import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.control_plane.retention.redis_sweeper import (
    RedisSweepResult,
    sweep_ephemeral_redis_keys,
)
from src.control_plane.retention.sql_purge import (
    SqlPurgeResult,
    purge_expired_authorization_audit,
)


@dataclass(frozen=True)
class RetentionRunResult:
    redis: RedisSweepResult
    sql: SqlPurgeResult


class ControlPlaneRetentionWorker:
    def __init__(
        self,
        *,
        redis_client,
        session_factory,
        audit_retention_days: int,
        redis_sweep_interval_seconds: int,
        sql_purge_interval_seconds: int,
        enabled: bool = True,
        redis_sweep_fn: Callable[..., Awaitable[RedisSweepResult]] = sweep_ephemeral_redis_keys,
        sql_purge_fn: Callable[..., Awaitable[SqlPurgeResult]] = purge_expired_authorization_audit,
    ) -> None:
        self.redis_client = redis_client
        self.session_factory = session_factory
        self.audit_retention_days = audit_retention_days
        self.redis_sweep_interval_seconds = redis_sweep_interval_seconds
        self.sql_purge_interval_seconds = sql_purge_interval_seconds
        self.enabled = enabled
        self.redis_sweep_fn = redis_sweep_fn
        self.sql_purge_fn = sql_purge_fn
        self._tasks: list[asyncio.Task] = []

    @property
    def running_task_count(self) -> int:
        return len([task for task in self._tasks if not task.done()])

    async def start(self) -> None:
        if not self.enabled:
            return
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run_redis_loop()),
            asyncio.create_task(self._run_sql_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def run_once(self) -> RetentionRunResult:
        redis_result = await self.redis_sweep_fn(self.redis_client)
        async with self.session_factory() as session:
            sql_result = await self.sql_purge_fn(
                session=session,
                retention_days=self.audit_retention_days,
            )
            await session.commit()
        return RetentionRunResult(redis=redis_result, sql=sql_result)

    async def _run_redis_loop(self) -> None:
        while True:
            await self.redis_sweep_fn(self.redis_client)
            await asyncio.sleep(self.redis_sweep_interval_seconds)

    async def _run_sql_loop(self) -> None:
        while True:
            async with self.session_factory() as session:
                await self.sql_purge_fn(
                    session=session,
                    retention_days=self.audit_retention_days,
                )
                await session.commit()
            await asyncio.sleep(self.sql_purge_interval_seconds)
```

- [ ] **Step 4: Run retention worker tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/retention/test_tasks.py -v
```

Expected: PASS.

- [ ] **Step 5: Disable retention worker in current app-auth tests**

In `tests/control_plane/test_app_auth.py`, add this line inside `_build_app_with_routes()` after the `SHIPAGENT_REDIS_URL` environment variable:

```python
    monkeypatch.setenv("SHIPAGENT_RETENTION_BACKGROUND_TASKS_ENABLED", "false")
```

Append this test to `tests/control_plane/test_app_auth.py`:

```python
def test_retention_worker_is_disabled_in_auth_tests(monkeypatch):
    app = _build_app_with_routes(monkeypatch, "sqlite+aiosqlite:///:memory:")
    with TestClient(app) as client:
        response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert app.state.retention_worker.enabled is False
```

- [ ] **Step 6: Wire retention worker into the FastAPI lifespan**

Merge the following additions into `src/control_plane/app.py`. Preserve existing middleware, router, MCP, relay, version-gate, and provider-execution wiring from Plans 1, 3, and 7; this task only adds the retention worker construction, stores it on `app.state`, starts it during lifespan startup, and stops it during shutdown.

```python
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.control_plane.auth import (
    Auth0TokenVerifier,
    AuthorizationService,
    ProviderClientRegistry,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.config import ControlPlaneSettings
from src.control_plane.request_controls import RequestControls
from src.control_plane.retention.tasks import ControlPlaneRetentionWorker
from src.control_plane.routes.oauth_metadata import build_metadata_router
from src.control_plane.startup import validate_startup_security
from src.hosted_mcp.server import build_server


@lru_cache
def _build_db_sessionmaker(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


def _build_redis_client(redis_url: str):
    return redis_from_url(redis_url, decode_responses=False)


def _metadata_url(settings: ControlPlaneSettings) -> str:
    if settings.public_base_url is None:
        raise RuntimeError("SHIPAGENT_PUBLIC_BASE_URL is required for OAuth metadata")
    return f"{str(settings.public_base_url).rstrip('/')}/.well-known/oauth-protected-resource"


def _bearer_challenge(settings: ControlPlaneSettings) -> dict[str, str]:
    return {
        "WWW-Authenticate": (
            f'Bearer resource_metadata="{_metadata_url(settings)}"'
        )
    }


def _build_request_controls(settings: ControlPlaneSettings) -> RequestControls:
    return RequestControls(redis_client=_build_redis_client(settings.redis_url))


def _build_retention_worker(settings: ControlPlaneSettings) -> ControlPlaneRetentionWorker:
    return ControlPlaneRetentionWorker(
        redis_client=_build_redis_client(settings.redis_url),
        session_factory=_build_db_sessionmaker(settings.database_url),
        audit_retention_days=settings.audit_retention_days,
        redis_sweep_interval_seconds=settings.retention_redis_sweep_interval_seconds,
        sql_purge_interval_seconds=settings.retention_sql_purge_interval_seconds,
        enabled=settings.retention_background_tasks_enabled,
    )


async def _resolve_authorization(
    settings: ControlPlaneSettings,
    principal: TokenPrincipal,
) -> AuthorizationContext:
    client_registry = ProviderClientRegistry(settings.auth0_provider_clients)
    async with _build_db_sessionmaker(settings.database_url)() as session:
        service = AuthorizationService(session, client_registry)
        return await service.resolve(
            subject=principal.subject,
            client_id=principal.client_id,
            scopes=set(principal.scopes),
        )


@lru_cache
def _build_verifier(issuer: str, audience: str) -> Auth0TokenVerifier:
    return Auth0TokenVerifier(issuer=issuer, audience=audience)


def _build_lifespan(mcp_app, retention_worker: ControlPlaneRetentionWorker):
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.retention_worker = retention_worker
        await retention_worker.start()
        try:
            async with mcp_app.lifespan(app):
                yield
        finally:
            await retention_worker.stop()

    return _lifespan


def create_control_plane_app() -> FastAPI:
    settings = ControlPlaneSettings()
    validate_startup_security(settings)
    if not settings.auth0_issuer:
        raise RuntimeError("SHIPAGENT_AUTH0_ISSUER must be set")
    if not settings.auth0_audience:
        raise RuntimeError("SHIPAGENT_AUTH0_AUDIENCE must be set")
    if not settings.public_base_url:
        raise RuntimeError("SHIPAGENT_PUBLIC_BASE_URL must be set")

    mcp = build_server(request_controls=_build_request_controls(settings))
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    retention_worker = _build_retention_worker(settings)
    app = FastAPI(lifespan=_build_lifespan(mcp_app, retention_worker))
    verifier = _build_verifier(settings.auth0_issuer, settings.auth0_audience)
    metadata_resource = str(settings.public_base_url).rstrip("/")
    app.include_router(
        build_metadata_router(metadata_resource, settings.auth0_issuer)
    )
    app.mount("/mcp", mcp_app)

    @app.middleware("http")
    async def _require_authorization(request: Request, call_next):
        if request.url.path.startswith("/.well-known/oauth-protected-resource"):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=_bearer_challenge(settings),
            )

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=_bearer_challenge(settings),
            )

        try:
            principal = verifier.verify(token)
            context = await _resolve_authorization(settings, principal)
            context_token = set_authorization_context(context)
            request.state.authorization = context
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=_bearer_challenge(settings),
            )
        try:
            return await call_next(request)
        finally:
            clear_authorization_context(context_token)

    return app
```

- [ ] **Step 7: Run app auth and retention worker tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_app_auth.py tests/control_plane/retention/test_tasks.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit scheduled retention work**

Run:

```bash
git add src/control_plane/app.py src/control_plane/retention/tasks.py tests/control_plane/test_app_auth.py tests/control_plane/retention/test_tasks.py
git commit -m "feat: schedule control-plane retention purges"
```

Expected: commit succeeds.

## Task 9: Run Migration And Control-Plane Validation

**Files:**
- Verify: all files changed by Tasks 1 through 8

- [ ] **Step 1: Run all targeted Plan 4 tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/control_plane/test_redis_keys.py \
  tests/control_plane/test_config.py \
  tests/control_plane/test_models.py \
  tests/control_plane/audit/test_service.py \
  tests/control_plane/audit/test_authorization_ledger.py \
  tests/control_plane/retention/test_redis_sweeper.py \
  tests/control_plane/retention/test_sql_purge.py \
  tests/control_plane/retention/test_tasks.py \
  tests/control_plane/accounts/test_service.py \
  tests/control_plane/test_app_auth.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run the full control-plane test suite**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane -v
```

Expected: PASS.

- [ ] **Step 3: Start local control-plane dependencies**

Run:

```bash
docker compose -f docker-compose.control-plane.yml up -d
```

Expected: Docker reports `postgres` and `redis` containers as started or already running.

- [ ] **Step 4: Run Alembic upgrade against the configured control-plane database**

Run:

```bash
.venv/bin/python -m alembic -c alembic.ini upgrade head
```

Expected: Alembic reports upgrades through `20260630_0004`.

If Plan 1 has already introduced a newer Alembic head before this plan is implemented, rebase only `alembic/versions/20260630_0004_ephemeral_retention_authorization_audit.py` by changing `down_revision` to the current control-plane head, then rerun this command. Keep the revision id `20260630_0004`.

- [ ] **Step 5: Run backend lint on touched Python files**

Run:

```bash
.venv/bin/python -m ruff check \
  src/control_plane/accounts \
  src/control_plane/audit \
  src/control_plane/retention \
  src/control_plane/app.py \
  src/control_plane/config.py \
  src/control_plane/redis_keys.py \
  tests/control_plane
```

Expected: PASS with no lint violations.

- [ ] **Step 6: Run backend formatting check or apply formatter**

Run:

```bash
.venv/bin/python -m ruff format \
  src/control_plane/accounts \
  src/control_plane/audit \
  src/control_plane/retention \
  src/control_plane/app.py \
  src/control_plane/config.py \
  src/control_plane/redis_keys.py \
  tests/control_plane
```

Expected: Formatter completes. If it modifies files, rerun Step 1 and Step 2.

- [ ] **Step 7: Final commit after validation**

Run:

```bash
git status --short
git add src/control_plane tests/control_plane alembic/env.py alembic/versions/20260630_0004_ephemeral_retention_authorization_audit.py
git commit -m "test: validate control-plane retention audit slice"
```

Expected: commit succeeds only if formatting changed files or validation required small follow-up fixes. If there are no remaining changes, skip this commit.

## Dependencies Consumed

- Plan 1 supplies stable `CloudAccount` and `ProviderConnection` account primitives. This plan uses the current table names and keeps provider references connection-scoped.
- Plan 1 may add relay device tables and migration heads. This plan only depends on account IDs and provider connection IDs, not relay implementation internals.
- ADR 0001 supplies Auth0 Cloud Account identity and provider-connection isolation.
- ADR 0004 supplies replay nonce and relay-session TTL needs.
- ADR 0005 supplies Redis TTLs, Redis sweeper, 90-day SQL retention, 30-365 day setting bounds, and legal-hold exception.
- ADR 0007 supplies the durable audit redaction boundary.
- ADR 0008 supplies the rule that Claude approval may create a server-side grant but does not transfer workflow ownership.

## Dependencies Provided

- `RedisKey` and `RedisTtl` constants for Plan 1 relay code, Plan 2 lifecycle code, Plan 5 request controls, and Plan 7 approval/label references.
- `AuthorizationLedgerService.record()` for Plan 7 Approval Request, decision, Execution Grant transition, and provider tool result events.
- `LegalHoldService` and `CloudAccountDeletionService` for account-management code from Plan 1 and Plan 9.
- `purge_expired_authorization_audit()` and `ControlPlaneRetentionWorker` for production retention operations.
- Alembic migration for `authorization_ledger_events` and `legal_holds`.

## Overlap Risks

- **Plan 1 migration overlap:** Plan 1 may add relay/account migration files before this one. Keep this plan's filename and revision id stable, but set `down_revision` to the merged Plan 1 head during implementation if the current head is no longer `20260609_0001`.
- **Plan 1 account service overlap:** If Plan 1 creates a broader account-management package, keep this plan's deletion cleanup method as the implementation behind that package rather than adding duplicate deletion paths.
- **Plan 7 approval flow overlap:** Plan 7 owns creation, approval, rejection, reservation, and consumption of Approval Requests and Execution Grants. This plan only defines Redis key names, TTLs, ledger recording APIs, and retention purges.
- **Control-plane persistence overlap:** `CloudAccount` and `ProviderConnection` remain in `src/control_plane/models.py`. This plan does not move them or add hosted tenant fields.
- **Request control overlap:** Plan 5 may alter `RequestControls`; keep rate-limit and loop-guard key names compatible with Task 1 and avoid changing request-control behavior in this plan.

## Self-Review Checklist

- Spec coverage: Redis TTL policy, Redis sweeper, daily SQL purge, 90-day default, 30-365 day bounds, account deletion cleanup, legal-hold exception, and hashed authorization ledger are all assigned to tasks.
- Redaction coverage: ledger service accepts only opaque references, SHA-256 hashes, amount/currency, categories, transitions, and correlation IDs. It has no input for PII, row data, labels, tracking numbers, tokens, URLs, provider prompts, or raw payloads.
- Type consistency: `ControlPlaneAuthorizationLedgerEvent`, `ControlPlaneLegalHold`, `AuthorizationLedgerService`, `LegalHoldService`, `CloudAccountDeletionService`, `RedisSweepResult`, `SqlPurgeResult`, and `ControlPlaneRetentionWorker` names match across tests and implementation snippets.
- Execution boundary: no task edits Plan 2 lifecycle modules, Plan 7 approval routes, provider projections, registry exports, frontend files, or generated artifacts.
