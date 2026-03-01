# Federated Platform MCP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the monolithic `external_sources` MCP server with per-platform MCP servers, a PlatformRegistry, PlatformGateway, PlatformActivationService, unified DuckDB import, and meta-platform agent tools.

**Architecture:** Federated model — each platform is an isolated stdio MCP subprocess. A PlatformGateway manages connections with lazy spawn, idle reap, circuit breaking, and QPS limiting. PlatformActivationService orchestrates connect → page → normalize → upsert. Agent interacts through thin meta-tools. DuckDB `external_orders` table with flat columns + `platform` discriminator enables cross-platform NL queries.

**Tech Stack:** Python 3.12+, FastMCP, SQLAlchemy, DuckDB, asyncio, `keyring`, Pydantic, pytest

**Design Doc:** `docs/plans/2026-02-28-meta-platform-mcp-design.md`

---

## Phase A: Build New Infrastructure Alongside Old

### Task 1: Contract Models + Error Taxonomy

Foundational models used by every subsequent task. No external dependencies.

**Files:**
- Create: `src/services/platform_models.py`
- Test: `tests/services/test_platform_models.py`

**Step 1: Write failing tests for error taxonomy and contract models**

```python
# tests/services/test_platform_models.py
"""Tests for platform contract models and error taxonomy."""
import pytest
from src.services.platform_models import (
    PlatformErrorCode,
    PlatformError,
    HealthReport,
    CapabilityManifest,
    AuthResult,
    OrderPage,
    TrackingWriteBackPayload,
    WriteBackResult,
    ActivationReport,
    PlatformConfig,
    PlatformSummary,
)


class TestPlatformErrorCode:
    def test_all_codes_are_strings(self):
        for code in PlatformErrorCode:
            assert isinstance(code.value, str)

    def test_required_codes_exist(self):
        required = {
            "AUTH_REQUIRED", "AUTH_EXPIRED", "RATE_LIMITED",
            "NOT_FOUND", "INVALID_ARGUMENT", "UPSTREAM_ERROR",
            "TRANSIENT", "PERMANENT",
        }
        actual = {c.value for c in PlatformErrorCode}
        assert required.issubset(actual)

    def test_retryable_codes(self):
        retryable = PlatformErrorCode.retryable_codes()
        assert PlatformErrorCode.TRANSIENT in retryable
        assert PlatformErrorCode.RATE_LIMITED in retryable
        assert PlatformErrorCode.UPSTREAM_ERROR in retryable
        assert PlatformErrorCode.PERMANENT not in retryable
        assert PlatformErrorCode.AUTH_EXPIRED not in retryable

    def test_trips_circuit_breaker(self):
        breaker_codes = PlatformErrorCode.circuit_breaker_codes()
        assert PlatformErrorCode.TRANSIENT in breaker_codes
        assert PlatformErrorCode.UPSTREAM_ERROR in breaker_codes
        assert PlatformErrorCode.RATE_LIMITED not in breaker_codes  # critical: rate limit != failure


class TestPlatformError:
    def test_from_dict(self):
        d = {
            "error_code": "RATE_LIMITED",
            "message": "Too many requests",
            "retry_after_seconds": 2,
            "provider_status": 429,
        }
        err = PlatformError.from_dict(d)
        assert err.error_code == PlatformErrorCode.RATE_LIMITED
        assert err.retry_after_seconds == 2

    def test_to_dict_roundtrip(self):
        err = PlatformError(
            error_code=PlatformErrorCode.TRANSIENT,
            message="timeout",
        )
        d = err.to_dict()
        assert d["error_code"] == "TRANSIENT"
        assert "request_id" not in d or d["request_id"] is None


class TestHealthReport:
    def test_contract_version_required(self):
        report = HealthReport(
            ok=True,
            platform_id="shopify",
            server_version="1.0.0",
            contract_version="1.0",
            api_reachable=True,
            auth_valid=True,
        )
        assert report.contract_version == "1.0"


class TestCapabilityManifest:
    def test_supports_tool(self):
        manifest = CapabilityManifest(
            platform_id="shopify",
            contract_version="1.0",
            supports=["orders.list", "orders.get", "tracking.write_back"],
            limits={"rate_limit_per_second": 2, "max_concurrency": 3},
            paging={"strategy": "cursor", "default_page_size": 50, "max_page_size": 250, "overlap_seconds": 300},
        )
        assert manifest.supports_tool("orders.list")
        assert not manifest.supports_tool("orders.delta")

    def test_get_rate_limit(self):
        manifest = CapabilityManifest(
            platform_id="test",
            contract_version="1.0",
            supports=[],
            limits={"rate_limit_per_second": 5, "max_concurrency": 2},
            paging={},
        )
        assert manifest.rate_limit_per_second == 5
        assert manifest.max_concurrency == 2

    def test_defaults_when_limits_missing(self):
        manifest = CapabilityManifest(
            platform_id="test",
            contract_version="1.0",
            supports=[],
            limits={},
            paging={},
        )
        assert manifest.rate_limit_per_second == 5  # default
        assert manifest.max_concurrency == 3  # default


class TestOrderPage:
    def test_has_more_when_next_cursor_present(self):
        page = OrderPage(items=[{"id": "1"}], next_cursor="abc", watermark="2026-01-01T00:00:00Z")
        assert page.has_more is True

    def test_no_more_when_next_cursor_none(self):
        page = OrderPage(items=[], next_cursor=None, watermark="2026-01-01T00:00:00Z")
        assert page.has_more is False


class TestPlatformConfig:
    def test_frozen(self):
        config = PlatformConfig(
            platform_id="shopify",
            display_name="Shopify",
            default_profile="primary",
            required_secret_keys=["SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"],
            mcp_module="src.mcp.platforms.shopify.server",
            mcp_bundle_subcommand="mcp-shopify",
            contract_version="1.0",
            default_sync_overlap_seconds=300,
            enabled=True,
        )
        with pytest.raises(AttributeError):
            config.platform_id = "amazon"


class TestTrackingWriteBackPayload:
    def test_multiple_tracking_numbers(self):
        payload = TrackingWriteBackPayload(
            tracking_numbers=["1Z999AA10123456784", "1Z999AA10123456785"],
            carrier="UPS",
        )
        assert len(payload.tracking_numbers) == 2


class TestActivationReport:
    def test_summary(self):
        report = ActivationReport(
            platform_id="shopify",
            credential_ref="primary",
            mode="initial",
            total_imported=150,
            pages_fetched=3,
            watermark="2026-02-28T12:00:00Z",
            duration_seconds=4.5,
            warnings=[],
        )
        assert report.total_imported == 150
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_platform_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.platform_models'`

**Step 3: Implement contract models**

```python
# src/services/platform_models.py
"""Contract models for the federated platform MCP architecture.

These models define the rigid interface between PlatformGateway,
platform MCP servers, PlatformRegistry, and PlatformActivationService.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class PlatformErrorCode(str, Enum):
    """Normalized error codes returned by platform MCP servers."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"

    @classmethod
    def retryable_codes(cls) -> frozenset[PlatformErrorCode]:
        """Error codes where retry is appropriate."""
        return frozenset({cls.TRANSIENT, cls.RATE_LIMITED, cls.UPSTREAM_ERROR})

    @classmethod
    def circuit_breaker_codes(cls) -> frozenset[PlatformErrorCode]:
        """Error codes that increment the circuit breaker.

        RATE_LIMITED is explicitly excluded — throttling is healthy, not failing.
        """
        return frozenset({cls.TRANSIENT, cls.UPSTREAM_ERROR})


@dataclass
class PlatformError:
    """Structured error from a platform MCP tool call."""

    error_code: PlatformErrorCode
    message: str
    retry_after_seconds: float | None = None
    provider_status: int | None = None
    provider_message: str | None = None
    request_id: str | None = None
    trace_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlatformError:
        """Parse from MCP tool error response."""
        return cls(
            error_code=PlatformErrorCode(d["error_code"]),
            message=d.get("message", ""),
            retry_after_seconds=d.get("retry_after_seconds"),
            provider_status=d.get("provider_status"),
            provider_message=d.get("provider_message"),
            request_id=d.get("request_id"),
            trace_id=d.get("trace_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for MCP tool response."""
        d: dict[str, Any] = {
            "error_code": self.error_code.value,
            "message": self.message,
        }
        if self.retry_after_seconds is not None:
            d["retry_after_seconds"] = self.retry_after_seconds
        if self.provider_status is not None:
            d["provider_status"] = self.provider_status
        if self.provider_message is not None:
            d["provider_message"] = self.provider_message
        if self.request_id is not None:
            d["request_id"] = self.request_id
        if self.trace_id is not None:
            d["trace_id"] = self.trace_id
        return d


@dataclass
class HealthReport:
    """Response from platform.health() tool."""

    ok: bool
    platform_id: str
    server_version: str
    contract_version: str
    api_reachable: bool
    auth_valid: bool
    capabilities_hash: str | None = None
    time_utc: str | None = None
    last_error: str | None = None


@dataclass
class CapabilityManifest:
    """Response from platform.capabilities() tool."""

    platform_id: str
    contract_version: str
    supports: list[str]
    limits: dict[str, Any]
    paging: dict[str, Any]
    writeback: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)

    def supports_tool(self, tool_name: str) -> bool:
        """Check if this platform supports a specific tool."""
        return tool_name in self.supports

    @property
    def rate_limit_per_second(self) -> int:
        """QPS limit for this platform. Defaults to 5."""
        return self.limits.get("rate_limit_per_second", 5)

    @property
    def max_concurrency(self) -> int:
        """Max concurrent in-flight requests. Defaults to 3."""
        return self.limits.get("max_concurrency", 3)

    @property
    def overlap_seconds(self) -> int:
        """Overlap window for watermark-based sync. Defaults to 300."""
        return self.paging.get("overlap_seconds", 300)

    @property
    def max_page_size(self) -> int:
        """Maximum page size. Defaults to 250."""
        return self.paging.get("max_page_size", 250)

    @property
    def default_page_size(self) -> int:
        """Default page size. Defaults to 50."""
        return self.paging.get("default_page_size", 50)


@dataclass
class AuthResult:
    """Response from auth.connect() tool."""

    connected: bool
    auth_valid: bool
    account_id: str | None = None
    account_label: str | None = None
    scopes: list[str] | None = None
    expires_at: str | None = None
    error: str | None = None


@dataclass
class OrderPage:
    """Response from orders.list() tool."""

    items: list[dict[str, Any]]
    next_cursor: str | None = None
    watermark: str | None = None
    total_estimate: int | None = None

    @property
    def has_more(self) -> bool:
        """Whether more pages are available."""
        return self.next_cursor is not None


@dataclass
class TrackingWriteBackPayload:
    """Payload for tracking.write_back() tool."""

    tracking_numbers: list[str]
    carrier: str
    tracking_url: str | None = None
    line_items: list[str] | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class WriteBackResult:
    """Response from tracking.write_back() tool."""

    success: bool
    error: str | None = None


@dataclass(frozen=True)
class PlatformConfig:
    """Immutable definition of a platform integration.

    Extension point: add a PlatformConfig entry to PLATFORM_CONFIGS
    to register a new platform.
    """

    platform_id: str
    display_name: str
    default_profile: str
    required_secret_keys: list[str]
    mcp_module: str
    mcp_bundle_subcommand: str
    contract_version: str
    default_sync_overlap_seconds: int
    enabled: bool


@dataclass
class PlatformSummary:
    """Agent/UI-facing view joining static config + dynamic state."""

    platform_id: str
    display_name: str
    credential_ref: str
    enabled: bool
    connection_status: str
    account_label: str | None
    last_sync_completed_at: datetime | None
    last_sync_row_count: int | None
    capabilities: list[str] | None
    has_credentials: bool
    health_ok: bool | None
    last_error: str | None
    contract_version_ok: bool
    capabilities_stale: bool


@dataclass
class ActivationReport:
    """Result of a platform activation or refresh."""

    platform_id: str
    credential_ref: str
    mode: str
    total_imported: int
    pages_fetched: int
    watermark: str | None
    duration_seconds: float
    warnings: list[str]


# --- Canonical hash computation ---

HASH_FIELDS = [
    "platform", "external_id", "credential_ref",
    "order_number", "order_status", "payment_status", "fulfillment_status",
    "ship_to_name", "ship_to_company", "ship_to_address1", "ship_to_address2",
    "ship_to_city", "ship_to_state", "ship_to_postal", "ship_to_country",
    "ship_to_phone", "is_residential",
    "total_weight_grams", "package_count", "shipping_method", "service_code",
    "total_price_cents", "currency",
    "customer_name", "customer_email", "item_count", "tags",
    "mapping_version",
]


def compute_canonical_hash(row: dict[str, Any]) -> str:
    """Deterministic hash of queryable column values.

    Includes mapping_version so a mapper version bump forces rewrite.
    Uses only integer/string types (no floats) for hash stability.
    """
    payload = json.dumps(
        {k: row.get(k) for k in HASH_FIELDS},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_platform_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/platform_models.py tests/services/test_platform_models.py
git commit -m "feat(platform): add contract models and error taxonomy for federated platform MCP"
```

---

### Task 2: PlatformSyncState DB Model + Migration

SQLAlchemy model for persisted dynamic state, keyed by `(platform_id, credential_ref)`.

**Files:**
- Modify: `src/db/models.py:921` (after `FilterTokenConsumed`)
- Modify: `src/db/connection.py` (ensure table creation)
- Test: `tests/db/test_platform_sync_state.py`

**Step 1: Write failing tests**

```python
# tests/db/test_platform_sync_state.py
"""Tests for PlatformSyncState model."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.db.models import Base, PlatformSyncState


@pytest.fixture
def db_session(tmp_path):
    """Use temp file DB (not :memory:) so multiple sessions see same data."""
    db_path = str(tmp_path / "test_sync_state.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestPlatformSyncState:
    def test_create_and_read(self, db_session):
        now = datetime.now(timezone.utc)
        state = PlatformSyncState(
            platform_id="shopify",
            credential_ref="primary",
            connection_status="disconnected",
            created_at=now,
            updated_at=now,
        )
        db_session.add(state)
        db_session.commit()

        loaded = db_session.get(PlatformSyncState, ("shopify", "primary"))
        assert loaded is not None
        assert loaded.connection_status == "disconnected"
        assert loaded.consecutive_failure_count == 0

    def test_composite_primary_key(self, db_session):
        now = datetime.now(timezone.utc)
        state1 = PlatformSyncState(
            platform_id="shopify", credential_ref="primary",
            connection_status="connected", created_at=now, updated_at=now,
        )
        state2 = PlatformSyncState(
            platform_id="shopify", credential_ref="sandbox",
            connection_status="disconnected", created_at=now, updated_at=now,
        )
        db_session.add_all([state1, state2])
        db_session.commit()

        assert db_session.query(PlatformSyncState).count() == 2

    def test_update_sync_checkpoint(self, db_session):
        now = datetime.now(timezone.utc)
        state = PlatformSyncState(
            platform_id="amazon", credential_ref="us_store",
            connection_status="connected", created_at=now, updated_at=now,
        )
        db_session.add(state)
        db_session.commit()

        state.resume_cursor = "cursor_page_3"
        state.last_sync_row_count = 150
        db_session.commit()

        loaded = db_session.get(PlatformSyncState, ("amazon", "us_store"))
        assert loaded.resume_cursor == "cursor_page_3"
        assert loaded.last_sync_row_count == 150

    def test_default_values(self, db_session):
        now = datetime.now(timezone.utc)
        state = PlatformSyncState(
            platform_id="test", credential_ref="default",
            created_at=now, updated_at=now,
        )
        db_session.add(state)
        db_session.commit()

        loaded = db_session.get(PlatformSyncState, ("test", "default"))
        assert loaded.connection_status == "disconnected"
        assert loaded.consecutive_failure_count == 0
        assert loaded.resume_cursor is None
        assert loaded.last_completed_watermark is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_platform_sync_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlatformSyncState'`

**Step 3: Add PlatformSyncState to db/models.py**

Add after line 921 of `src/db/models.py` (after `FilterTokenConsumed`):

```python
class PlatformSyncState(Base):
    """Persisted sync state for each platform integration.

    Keyed by (platform_id, credential_ref) for multi-account support.
    Stores sync checkpoints, health tracking, and capabilities cache.
    """

    __tablename__ = "platform_sync_state"

    platform_id: Mapped[str] = mapped_column(String, primary_key=True)
    credential_ref: Mapped[str] = mapped_column(String, primary_key=True)
    connection_status: Mapped[str] = mapped_column(
        String, default="disconnected"
    )  # connected | disconnected | degraded | auth_expired
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    account_label: Mapped[str | None] = mapped_column(String, nullable=True)

    # Sync checkpoints (resumable)
    resume_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    last_completed_watermark: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Health tracking
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Capabilities cache
    capabilities_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    capabilities_contract_version: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    capabilities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<PlatformSyncState({self.platform_id}/{self.credential_ref} "
            f"status={self.connection_status})>"
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/db/test_platform_sync_state.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/db/models.py tests/db/test_platform_sync_state.py
git commit -m "feat(platform): add PlatformSyncState SQLAlchemy model with composite PK"
```

---

### Task 3: PlatformRegistry Service

Static config + dynamic state management. Pure service, no MCP or gateway dependencies.

**IMPORTANT: Session management pattern.** PlatformRegistry uses a `session_factory` (not a shared Session) to avoid "shared session across async tasks" bugs. Every method creates its own short-lived session internally.

**Files:**
- Create: `src/services/platform_registry.py`
- Test: `tests/services/test_platform_registry.py`

**Step 1: Write failing tests**

```python
# tests/services/test_platform_registry.py
"""Tests for PlatformRegistry service."""
import os
import tempfile
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, PlatformSyncState
from src.services.platform_models import PlatformConfig, CapabilityManifest
from src.services.platform_registry import PlatformRegistry, PLATFORM_CONFIGS


@pytest.fixture
def db_path(tmp_path):
    """Use a temp file DB (not :memory:) so sessions see the same data."""
    return str(tmp_path / "test_registry.db")


@pytest.fixture
def session_factory(db_path):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture
def registry(session_factory):
    return PlatformRegistry(session_factory)


class TestStaticConfig:
    def test_get_config_exists(self, registry):
        config = registry.get_config("shopify")
        assert config is not None
        assert config.platform_id == "shopify"
        assert config.display_name == "Shopify"

    def test_get_config_not_found(self, registry):
        assert registry.get_config("nonexistent") is None

    def test_list_configs_enabled_only(self, registry):
        configs = registry.list_configs(enabled_only=True)
        assert all(c.enabled for c in configs)

    def test_list_configs_all(self, registry):
        configs = registry.list_configs(enabled_only=False)
        assert len(configs) >= 1  # at least shopify

    def test_platform_configs_has_shopify(self):
        assert "shopify" in PLATFORM_CONFIGS
        shopify = PLATFORM_CONFIGS["shopify"]
        assert shopify.contract_version == "1.0"


class TestDynamicState:
    def test_get_state_returns_none_when_missing(self, registry):
        state = registry.get_state("shopify", "primary")
        assert state is None

    def test_update_state_creates_if_missing(self, registry, session_factory):
        state = registry.update_state(
            "shopify", "primary",
            connection_status="connected",
            account_label="test-store.myshopify.com",
        )
        assert state.connection_status == "connected"
        assert state.account_label == "test-store.myshopify.com"

        # Verify via separate session (proves data persisted)
        with session_factory() as s:
            loaded = s.get(PlatformSyncState, ("shopify", "primary"))
            assert loaded is not None

    def test_update_state_updates_existing(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.update_state("shopify", "primary", connection_status="degraded")

        state = registry.get_state("shopify", "primary")
        assert state.connection_status == "degraded"

    def test_record_sync_checkpoint(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_sync_checkpoint(
            "shopify", "primary",
            resume_cursor="cursor_abc",
            watermark=None,
            row_count=50,
        )
        state = registry.get_state("shopify", "primary")
        assert state.resume_cursor == "cursor_abc"
        assert state.last_completed_watermark is None  # not advanced mid-sync

    def test_record_sync_completion_clears_cursor_advances_watermark(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_sync_checkpoint(
            "shopify", "primary",
            resume_cursor=None,  # cleared
            watermark="2026-02-28T12:00:00Z",  # advanced
            row_count=150,
        )
        state = registry.get_state("shopify", "primary")
        assert state.resume_cursor is None
        assert state.last_completed_watermark == "2026-02-28T12:00:00Z"
        assert state.last_sync_row_count == 150

    def test_record_health_check_ok(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_health_check("shopify", "primary", ok=True)
        state = registry.get_state("shopify", "primary")
        assert state.last_health_ok is True
        assert state.last_health_check_at is not None

    def test_record_health_check_failure(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_health_check(
            "shopify", "primary", ok=False,
            error_code="UPSTREAM_ERROR", error_message="503 from Shopify",
        )
        state = registry.get_state("shopify", "primary")
        assert state.last_health_ok is False
        assert state.last_error_code == "UPSTREAM_ERROR"

    def test_record_capabilities(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        manifest = {"supports": ["orders.list"], "limits": {}, "paging": {}}
        registry.record_capabilities("shopify", "primary", manifest, "abc123", "1.0")
        state = registry.get_state("shopify", "primary")
        assert state.capabilities_hash == "abc123"
        assert state.capabilities_contract_version == "1.0"

    def test_list_states(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.update_state("amazon", "us_store", connection_status="disconnected")
        states = registry.list_states()
        assert len(states) == 2


class TestCredentialRefNamespacing:
    """Verify credentials are checked with namespaced keys: {platform}:{ref}:{key}."""

    @patch("src.services.platform_registry.KeyringStore")
    def test_has_credentials_checks_namespaced_keys(self, mock_keyring_cls, registry):
        mock_keyring = MagicMock()
        calls = []
        def has_side_effect(key):
            calls.append(key)
            return True
        mock_keyring.has.side_effect = has_side_effect
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")
        summaries = registry.get_platforms_summary()

        # Verify keys are namespaced as shopify:primary:ACCESS_TOKEN etc.
        shopify_calls = [c for c in calls if c.startswith("shopify:primary:")]
        assert len(shopify_calls) > 0
        assert "shopify:primary:ACCESS_TOKEN" in shopify_calls


class TestPlatformSummary:
    @patch("src.services.platform_registry.KeyringStore")
    def test_get_platforms_summary(self, mock_keyring_cls, registry):
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")

        summaries = registry.get_platforms_summary()
        shopify_summaries = [s for s in summaries if s.platform_id == "shopify"]
        assert len(shopify_summaries) >= 1
        assert shopify_summaries[0].has_credentials is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_platform_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.platform_registry'`

**Step 3: Implement PlatformRegistry**

**CRITICAL: Session factory pattern.** PlatformRegistry takes a `session_factory` (callable returning Session), not a shared Session. Every method creates its own short-lived session, preventing "shared session across async tasks" bugs.

**CRITICAL: Namespaced credential keys.** Keyring keys use `{platform_id}:{credential_ref}:{key_name}` format (e.g., `shopify:primary:ACCESS_TOKEN`). This prevents collisions between profiles and makes `has_credentials` checks unambiguous.

```python
# src/services/platform_registry.py
"""PlatformRegistry: static config + persisted dynamic state for platform integrations.

Extension point: add a PlatformConfig entry to PLATFORM_CONFIGS to register a new platform.

Session management: uses session_factory pattern. Every method creates its own
short-lived session to avoid shared-session-across-async-tasks bugs.

Credential keys: namespaced as {platform_id}:{credential_ref}:{key_name}
(e.g., shopify:primary:ACCESS_TOKEN) to support multi-profile.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import PlatformSyncState
from src.services.keyring_store import KeyringStore
from src.services.platform_models import (
    PlatformConfig,
    PlatformSummary,
)

logger = logging.getLogger(__name__)

# --- Static platform configs (the extension point) ---
# required_secret_keys are LOGICAL names, namespaced at runtime as
# {platform_id}:{credential_ref}:{key_name}

PLATFORM_CONFIGS: dict[str, PlatformConfig] = {
    "shopify": PlatformConfig(
        platform_id="shopify",
        display_name="Shopify",
        default_profile="primary",
        required_secret_keys=["ACCESS_TOKEN", "STORE_DOMAIN"],
        mcp_module="src.mcp.platforms.shopify.server",
        mcp_bundle_subcommand="mcp-shopify",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "amazon": PlatformConfig(
        platform_id="amazon",
        display_name="Amazon Seller Central",
        default_profile="primary",
        required_secret_keys=[
            "SP_API_REFRESH_TOKEN",
            "SP_API_CLIENT_ID",
            "SP_API_CLIENT_SECRET",
            "MARKETPLACE_ID",
        ],
        mcp_module="src.mcp.platforms.amazon.server",
        mcp_bundle_subcommand="mcp-amazon",
        contract_version="1.0",
        default_sync_overlap_seconds=600,
        enabled=True,
    ),
    "woocommerce": PlatformConfig(
        platform_id="woocommerce",
        display_name="WooCommerce",
        default_profile="primary",
        required_secret_keys=["CONSUMER_KEY", "CONSUMER_SECRET", "SITE_URL"],
        mcp_module="src.mcp.platforms.woocommerce.server",
        mcp_bundle_subcommand="mcp-woocommerce",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "sap": PlatformConfig(
        platform_id="sap",
        display_name="SAP Business One",
        default_profile="primary",
        required_secret_keys=["BASE_URL", "USERNAME", "PASSWORD", "CLIENT"],
        mcp_module="src.mcp.platforms.sap.server",
        mcp_bundle_subcommand="mcp-sap",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "oracle": PlatformConfig(
        platform_id="oracle",
        display_name="Oracle ERP",
        default_profile="primary",
        required_secret_keys=["DSN", "USER", "PASSWORD"],
        mcp_module="src.mcp.platforms.oracle.server",
        mcp_bundle_subcommand="mcp-oracle",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
}

CAPABILITIES_TTL_SECONDS = 3600  # 1 hour


def keyring_key(platform_id: str, credential_ref: str, key_name: str) -> str:
    """Build namespaced keyring key: {platform_id}:{credential_ref}:{key_name}."""
    return f"{platform_id}:{credential_ref}:{key_name}"


class PlatformRegistry:
    """Registry for platform integrations — static config + persisted dynamic state.

    Takes a session_factory (not a Session) — every method creates its own
    short-lived session to avoid cross-task session sharing bugs.
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    # --- Static config ---

    def get_config(self, platform_id: str) -> PlatformConfig | None:
        """Get static config for a platform."""
        return PLATFORM_CONFIGS.get(platform_id)

    def list_configs(self, enabled_only: bool = True) -> list[PlatformConfig]:
        """List all platform configs."""
        configs = list(PLATFORM_CONFIGS.values())
        if enabled_only:
            configs = [c for c in configs if c.enabled]
        return configs

    # --- Dynamic state ---

    def get_state(self, platform_id: str, credential_ref: str) -> PlatformSyncState | None:
        """Get persisted dynamic state for a platform connection."""
        with self._session_factory() as session:
            state = session.get(PlatformSyncState, (platform_id, credential_ref))
            if state:
                session.expunge(state)
            return state

    def list_states(self) -> list[PlatformSyncState]:
        """List all platform sync states."""
        with self._session_factory() as session:
            states = session.query(PlatformSyncState).all()
            for s in states:
                session.expunge(s)
            return states

    def update_state(self, platform_id: str, credential_ref: str, **fields: Any) -> PlatformSyncState:
        """Update (or create) dynamic state for a platform connection."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            state = session.get(PlatformSyncState, (platform_id, credential_ref))
            if state is None:
                state = PlatformSyncState(
                    platform_id=platform_id,
                    credential_ref=credential_ref,
                    created_at=now,
                    updated_at=now,
                )
                session.add(state)

            for key, value in fields.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            state.updated_at = now
            session.commit()
            session.expunge(state)
            return state

    def record_sync_checkpoint(
        self,
        platform_id: str,
        credential_ref: str,
        resume_cursor: str | None,
        watermark: str | None,
        row_count: int,
    ) -> None:
        """Record sync progress. Clears resume_cursor and advances watermark on completion."""
        fields: dict[str, Any] = {
            "resume_cursor": resume_cursor,
            "last_sync_row_count": row_count,
        }
        if watermark is not None:
            fields["last_completed_watermark"] = watermark
            fields["last_sync_completed_at"] = datetime.now(timezone.utc)
        self.update_state(platform_id, credential_ref, **fields)

    def record_health_check(
        self,
        platform_id: str,
        credential_ref: str,
        ok: bool,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record result of a health check."""
        now = datetime.now(timezone.utc)
        fields: dict[str, Any] = {
            "last_health_check_at": now,
            "last_health_ok": ok,
        }
        if not ok:
            fields["last_error_code"] = error_code
            fields["last_error_message"] = error_message
            fields["last_error_at"] = now
        self.update_state(platform_id, credential_ref, **fields)

    def record_capabilities(
        self,
        platform_id: str,
        credential_ref: str,
        manifest: dict[str, Any],
        capabilities_hash: str,
        contract_version: str,
    ) -> None:
        """Cache a capabilities manifest."""
        self.update_state(
            platform_id, credential_ref,
            capabilities_json=json.dumps(manifest),
            capabilities_hash=capabilities_hash,
            capabilities_contract_version=contract_version,
            capabilities_fetched_at=datetime.now(timezone.utc),
        )

    # --- Summary (agent/UI facing) ---

    def _check_credentials(
        self, keyring: KeyringStore, config: PlatformConfig, credential_ref: str,
    ) -> bool:
        """Check if all required credentials exist for a (platform, ref) profile."""
        return all(
            keyring.has(keyring_key(config.platform_id, credential_ref, k))
            for k in config.required_secret_keys
        )

    def get_platforms_summary(self) -> list[PlatformSummary]:
        """Join static config + dynamic state for all platforms."""
        keyring = KeyringStore()
        summaries: list[PlatformSummary] = []

        with self._session_factory() as session:
            for config in self.list_configs(enabled_only=True):
                states = (
                    session.query(PlatformSyncState)
                    .filter(PlatformSyncState.platform_id == config.platform_id)
                    .all()
                )

                if not states:
                    has_creds = self._check_credentials(keyring, config, config.default_profile)
                    summaries.append(PlatformSummary(
                        platform_id=config.platform_id,
                        display_name=config.display_name,
                        credential_ref=config.default_profile,
                        enabled=config.enabled,
                        connection_status="disconnected",
                        account_label=None,
                        last_sync_completed_at=None,
                        last_sync_row_count=None,
                        capabilities=None,
                        has_credentials=has_creds,
                        health_ok=None,
                        last_error=None,
                        contract_version_ok=True,
                        capabilities_stale=True,
                    ))
                else:
                    for state in states:
                        caps = json.loads(state.capabilities_json).get("supports", []) if state.capabilities_json else None
                        cv_ok = state.capabilities_contract_version == config.contract_version if state.capabilities_contract_version else True
                        stale = True
                        if state.capabilities_fetched_at:
                            age = (datetime.now(timezone.utc) - state.capabilities_fetched_at).total_seconds()
                            stale = age > CAPABILITIES_TTL_SECONDS
                        has_creds = self._check_credentials(keyring, config, state.credential_ref)

                        summaries.append(PlatformSummary(
                            platform_id=config.platform_id,
                            display_name=config.display_name,
                            credential_ref=state.credential_ref,
                            enabled=config.enabled,
                            connection_status=state.connection_status,
                            account_label=state.account_label,
                            last_sync_completed_at=state.last_sync_completed_at,
                            last_sync_row_count=state.last_sync_row_count,
                            capabilities=caps,
                            has_credentials=has_creds,
                            health_ok=state.last_health_ok,
                            last_error=state.last_error_message,
                            contract_version_ok=cv_ok,
                            capabilities_stale=stale,
                        ))

        return summaries
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_platform_registry.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/platform_registry.py tests/services/test_platform_registry.py
git commit -m "feat(platform): add PlatformRegistry with static config and persisted dynamic state"
```

---

### Task 4: Shopify Platform MCP Server (Extract from Monolith)

Extract the Shopify client from `src/mcp/external_sources/clients/shopify.py` into a standalone MCP server implementing the standardized contract.

**Files:**
- Create: `src/mcp/platforms/__init__.py`
- Create: `src/mcp/platforms/shopify/__init__.py`
- Create: `src/mcp/platforms/shopify/server.py`
- Create: `src/mcp/platforms/shopify/client.py` (extract from `src/mcp/external_sources/clients/shopify.py`)
- Create: `src/mcp/platforms/shopify/mapper.py` (extract from `src/services/shopify_activation_service.py:_prepare_shopify_import_rows`)
- Create: `src/mcp/platforms/shopify/constants.py`
- Create: `src/mcp/platforms/shopify/models.py`
- Test: `tests/mcp/platforms/__init__.py`
- Test: `tests/mcp/platforms/shopify/__init__.py`
- Test: `tests/mcp/platforms/shopify/test_server.py`
- Test: `tests/mcp/platforms/shopify/test_mapper.py`

This is a large task. Focus on: (1) mapper tests first (pure, no MCP), (2) server contract compliance tests.

**Step 1: Write failing tests for the mapper**

```python
# tests/mcp/platforms/shopify/test_mapper.py
"""Tests for Shopify order mapper (provider order -> flat DuckDB row)."""
import pytest
from src.mcp.platforms.shopify.mapper import ShopifyMapper


@pytest.fixture
def mapper():
    return ShopifyMapper()


@pytest.fixture
def sample_shopify_order():
    return {
        "id": 5678901234,
        "order_number": 1042,
        "financial_status": "paid",
        "fulfillment_status": None,
        "created_at": "2026-02-28T10:30:00-05:00",
        "updated_at": "2026-02-28T11:00:00-05:00",
        "shipping_address": {
            "name": "Jane Doe",
            "company": "Acme Corp",
            "address1": "123 Main St",
            "address2": "Suite 4",
            "city": "Austin",
            "province_code": "TX",
            "zip": "78701",
            "country_code": "US",
            "phone": "512-555-0100",
        },
        "total_price": "49.99",
        "currency": "USD",
        "customer": {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
        "line_items": [
            {"quantity": 2, "grams": 500, "title": "Widget"},
            {"quantity": 1, "grams": 200, "title": "Gadget"},
        ],
        "tags": "vip, wholesale",
        "note": "Handle with care",
        "shipping_lines": [{"title": "Standard Shipping", "code": "STANDARD"}],
    }


class TestShopifyMapper:
    def test_platform_column(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["platform"] == "shopify"

    def test_credential_ref(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "sandbox")
        assert row["credential_ref"] == "sandbox"

    def test_external_id_is_string(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["external_id"] == "5678901234"
        assert isinstance(row["external_id"], str)

    def test_ship_to_fields(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["ship_to_name"] == "Jane Doe"
        assert row["ship_to_company"] == "Acme Corp"
        assert row["ship_to_city"] == "Austin"
        assert row["ship_to_state"] == "TX"
        assert row["ship_to_postal"] == "78701"
        assert row["ship_to_country"] == "US"

    def test_weight_is_integer_grams(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["total_weight_grams"] == 1200  # (2*500)+(1*200)
        assert isinstance(row["total_weight_grams"], int)

    def test_price_in_cents(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["total_price_cents"] == 4999

    def test_item_count(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["item_count"] == 3  # 2 + 1

    def test_canonical_hash_present(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert "canonical_hash" in row
        assert len(row["canonical_hash"]) == 64  # SHA256 hex

    def test_canonical_hash_deterministic(self, mapper, sample_shopify_order):
        row1 = mapper.to_flat_row(sample_shopify_order, "primary")
        row2 = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row1["canonical_hash"] == row2["canonical_hash"]

    def test_canonical_hash_changes_on_status_change(self, mapper, sample_shopify_order):
        row1 = mapper.to_flat_row(sample_shopify_order, "primary")
        sample_shopify_order["fulfillment_status"] = "fulfilled"
        row2 = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row1["canonical_hash"] != row2["canonical_hash"]

    def test_raw_json_preserved(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert "raw_json" in row
        assert "5678901234" in row["raw_json"]

    def test_attrs_json_contains_non_core_fields(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        import json
        attrs = json.loads(row["attrs_json"])
        assert "note" in attrs

    def test_mapping_version(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["mapping_version"] == ShopifyMapper.MAPPING_VERSION

    def test_missing_shipping_address(self, mapper):
        order = {"id": 999, "order_number": 1, "line_items": []}
        row = mapper.to_flat_row(order, "primary")
        assert row["ship_to_name"] is None
        assert row["ship_to_state"] is None

    def test_fulfillment_status_defaults_to_unfulfilled(self, mapper, sample_shopify_order):
        row = mapper.to_flat_row(sample_shopify_order, "primary")
        assert row["fulfillment_status"] == "unfulfilled"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/platforms/shopify/test_mapper.py -v`
Expected: FAIL — import errors

**Step 3: Create directory structure and implement mapper**

Create `__init__.py` files for `src/mcp/platforms/`, `src/mcp/platforms/shopify/`, `tests/mcp/platforms/`, `tests/mcp/platforms/shopify/`.

Implement `src/mcp/platforms/shopify/mapper.py` — a pure module that maps Shopify order dicts to flat DuckDB rows. Extract logic from `src/services/shopify_activation_service.py:_prepare_shopify_import_rows` and the Shopify client's `_normalize_order`. Add `canonical_hash`, `raw_json`, `attrs_json`, `mapping_version`.

Implement `src/mcp/platforms/shopify/constants.py` with API version, endpoints.

Implement `src/mcp/platforms/shopify/models.py` with `ShopifyCredentials` dataclass.

**Step 4: Run mapper tests to verify they pass**

Run: `pytest tests/mcp/platforms/shopify/test_mapper.py -v`
Expected: All PASS

**Step 5: Write failing tests for server contract compliance**

**IMPORTANT: Do NOT introspect FastMCP internals (e.g., `mcp._tool_manager`).** Test via
the actual tool handler functions exported from server.py. This is resilient to FastMCP
version changes. If you need to verify tool registration, use `mcp.list_tools()` (the
public MCP method).

```python
# tests/mcp/platforms/shopify/test_server.py
"""Tests for Shopify platform MCP server contract compliance.

Tests call exported handler functions directly — no FastMCP internal introspection.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestShopifyServerContract:
    """Verify the Shopify MCP server implements the required tool contract."""

    def test_server_exposes_required_tools(self):
        """Verify tool registration via the public list_tools() MCP method."""
        from src.mcp.platforms.shopify.server import mcp
        # Use the public API, not _tool_manager internals
        tools = asyncio.get_event_loop().run_until_complete(mcp.list_tools())
        tool_names = {t.name for t in tools}
        required = {"platform.health", "platform.capabilities", "auth.connect",
                     "auth.disconnect", "orders.list", "orders.get", "tracking.write_back"}
        assert required.issubset(tool_names), f"Missing tools: {required - tool_names}"

    def test_health_returns_required_shape(self):
        """Call the handler function directly and verify response shape."""
        from src.mcp.platforms.shopify.server import health
        result = asyncio.get_event_loop().run_until_complete(health())
        # Required fields per contract
        assert "ok" in result
        assert "platform_id" in result
        assert result["platform_id"] == "shopify"
        assert "server_version" in result
        assert "contract_version" in result
        assert result["contract_version"] == "1.0"
        assert "api_reachable" in result
        assert "auth_valid" in result

    def test_capabilities_returns_required_shape(self):
        """Call the handler function directly and verify response shape."""
        from src.mcp.platforms.shopify.server import capabilities
        result = asyncio.get_event_loop().run_until_complete(capabilities())
        assert "supports" in result
        assert "limits" in result
        assert "paging" in result
        assert "contract_version" in result
        assert "orders.list" in result["supports"]
        # Verify paging contract fields
        assert "default_page_size" in result["paging"]
        assert "max_page_size" in result["paging"]
        assert "overlap_seconds" in result["paging"]

    def test_health_and_capabilities_contract_versions_match(self):
        """Contract version must be consistent across tools."""
        from src.mcp.platforms.shopify.server import health, capabilities
        h = asyncio.get_event_loop().run_until_complete(health())
        c = asyncio.get_event_loop().run_until_complete(capabilities())
        assert h["contract_version"] == c["contract_version"]
```

**Step 6: Implement server.py and client.py**

Extract `src/mcp/external_sources/clients/shopify.py` → `src/mcp/platforms/shopify/client.py`. Implement `src/mcp/platforms/shopify/server.py` with FastMCP, registering all 7 required tools. Server tools are thin dispatchers to client methods. Error wrapping converts httpx/API errors to `PlatformError` taxonomy. `auth.connect` reads credentials from `KeyringStore` using `credential_ref`.

**Step 7: Run all Shopify tests**

Run: `pytest tests/mcp/platforms/shopify/ -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add src/mcp/platforms/ tests/mcp/platforms/
git commit -m "feat(platform): extract Shopify into standalone platform MCP with contract compliance"
```

---

### Task 4.1: Mapper Purity Enforcement Test

Verify that mapper modules under `src/mcp/platforms/` do not accidentally import FastMCP or server-side dependencies. This prevents circular imports and packaging issues.

**Files:**
- Test: `tests/mcp/platforms/test_mapper_purity.py`

**Step 1: Write the purity test**

```python
# tests/mcp/platforms/test_mapper_purity.py
"""Verify mapper modules are pure — no FastMCP or server imports."""
import importlib
import sys
import pytest


MAPPER_MODULES = [
    "src.mcp.platforms.shopify.mapper",
    # Add new platforms here as they're extracted
]


@pytest.mark.parametrize("module_path", MAPPER_MODULES)
def test_mapper_does_not_import_fastmcp(module_path):
    """Mapper modules must not pull in FastMCP or server dependencies."""
    # Clear any cached imports to get a clean check
    mod = importlib.import_module(module_path)
    imported = set(sys.modules.keys())
    fastmcp_imports = [m for m in imported if "fastmcp" in m.lower() or "mcp.server" in m]
    assert not fastmcp_imports, (
        f"{module_path} transitively imports FastMCP/server modules: {fastmcp_imports}"
    )


@pytest.mark.parametrize("module_path", MAPPER_MODULES)
def test_mapper_does_not_import_its_own_server(module_path):
    """Mapper must not import the server module from its own package."""
    mod = importlib.import_module(module_path)
    # Check that the corresponding server module was not imported
    server_module = module_path.rsplit(".", 1)[0] + ".server"
    assert server_module not in sys.modules, (
        f"{module_path} imported its own server module: {server_module}"
    )
```

**Step 2: Run test**

Run: `pytest tests/mcp/platforms/test_mapper_purity.py -v`
Expected: PASS (after Task 4 mappers are implemented correctly)

**Step 3: Commit**

```bash
git add tests/mcp/platforms/test_mapper_purity.py
git commit -m "test(platform): add mapper purity enforcement tests"
```

---

### Task 5.0: DuckDB External Orders Schema Migration

Create the `external_orders` table in the Data Source MCP. This must run before upsert tools or activation service.

**Files:**
- Create: `src/mcp/data_source/tools/schema_migration.py`
- Modify: `src/mcp/data_source/server.py` (call migration in lifespan)
- Test: `tests/mcp/data_source/test_schema_migration.py`

**Step 1: Write failing test**

```python
# tests/mcp/data_source/test_schema_migration.py
"""Tests for external_orders schema migration."""
import pytest
import duckdb
from src.mcp.data_source.tools.schema_migration import ensure_external_orders_table


class TestExternalOrdersSchema:
    def test_creates_table_if_missing(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        # Table should exist
        result = conn.execute("SELECT * FROM external_orders LIMIT 0").description
        column_names = [col[0] for col in result]
        assert "platform" in column_names
        assert "external_id" in column_names
        assert "credential_ref" in column_names
        assert "canonical_hash" in column_names
        assert "raw_json" in column_names
        assert "attrs_json" in column_names
        conn.close()

    def test_idempotent_creation(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        ensure_external_orders_table(conn)  # Should not error
        count = conn.execute("SELECT COUNT(*) FROM external_orders").fetchone()[0]
        assert count == 0
        conn.close()

    def test_primary_key_exists(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        # Insert duplicate PK should fail
        conn.execute("""
            INSERT INTO external_orders (platform, external_id, credential_ref, canonical_hash, ingested_at)
            VALUES ('shopify', '1', 'primary', 'aaa', CURRENT_TIMESTAMP)
        """)
        with pytest.raises(duckdb.ConstraintException):
            conn.execute("""
                INSERT INTO external_orders (platform, external_id, credential_ref, canonical_hash, ingested_at)
                VALUES ('shopify', '1', 'primary', 'bbb', CURRENT_TIMESTAMP)
            """)
        conn.close()

    def test_schema_introspection_includes_platform(self):
        """NL filter engine needs to see 'platform' in get_schema."""
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        cols = conn.execute("DESCRIBE external_orders").fetchall()
        col_names = [c[0] for c in cols]
        assert "platform" in col_names
        assert "credential_ref" in col_names
        assert "total_weight_grams" in col_names
        # Verify weight is integer, not float
        weight_col = next(c for c in cols if c[0] == "total_weight_grams")
        assert "BIGINT" in weight_col[1].upper()
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mcp/data_source/test_schema_migration.py -v`
Expected: FAIL — import error

**Step 3: Implement schema migration**

```python
# src/mcp/data_source/tools/schema_migration.py
"""Schema migration for external_orders DuckDB table.

Called during Data Source MCP lifespan to ensure the table exists
before any upsert operations.
"""
from __future__ import annotations

import logging
import duckdb

logger = logging.getLogger(__name__)

EXTERNAL_ORDERS_DDL = """
CREATE TABLE IF NOT EXISTS external_orders (
    platform            VARCHAR NOT NULL,
    external_id         VARCHAR NOT NULL,
    credential_ref      VARCHAR NOT NULL,

    order_number        VARCHAR,
    order_status        VARCHAR,
    payment_status      VARCHAR,
    fulfillment_status  VARCHAR,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,

    ship_to_name        VARCHAR,
    ship_to_company     VARCHAR,
    ship_to_address1    VARCHAR,
    ship_to_address2    VARCHAR,
    ship_to_city        VARCHAR,
    ship_to_state       VARCHAR,
    ship_to_postal      VARCHAR,
    ship_to_country     VARCHAR,
    ship_to_phone       VARCHAR,
    is_residential      BOOLEAN,

    total_weight_grams  BIGINT,
    package_count       INTEGER DEFAULT 1,
    shipping_method     VARCHAR,
    service_code        VARCHAR,

    total_price_cents   BIGINT,
    currency            VARCHAR DEFAULT 'USD',

    customer_name       VARCHAR,
    customer_email      VARCHAR,
    item_count          INTEGER,
    tags                VARCHAR,

    canonical_hash      VARCHAR NOT NULL,
    mapping_version     VARCHAR DEFAULT '1.0',
    ingested_at         TIMESTAMPTZ NOT NULL,
    sync_run_id         VARCHAR,

    attrs_json          VARCHAR,
    raw_json            VARCHAR,

    PRIMARY KEY (platform, external_id, credential_ref)
);
"""


def ensure_external_orders_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Create external_orders table if it doesn't exist."""
    conn.execute(EXTERNAL_ORDERS_DDL)
    logger.info("external_orders table ensured")
```

**Step 4: Wire into Data Source MCP lifespan**

In `src/mcp/data_source/server.py`, call `ensure_external_orders_table(conn)` during the lifespan startup, after the DuckDB connection is created.

**Step 5: Run tests**

Run: `pytest tests/mcp/data_source/test_schema_migration.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/mcp/data_source/tools/schema_migration.py tests/mcp/data_source/test_schema_migration.py src/mcp/data_source/server.py
git commit -m "feat(data-source): add external_orders schema migration with PK constraints"
```

---

### Task 5: DuckDB Upsert Support in Data Source MCP

Add `upsert_records` tool to the Data Source MCP server.

**Files:**
- Create: `src/mcp/data_source/tools/upsert_tools.py`
- Modify: `src/mcp/data_source/server.py:130` (register upsert_records)
- Test: `tests/mcp/data_source/test_upsert_tools.py`

**Step 1: Write failing tests**

```python
# tests/mcp/data_source/test_upsert_tools.py
"""Tests for DuckDB upsert_records tool."""
import pytest
import duckdb


class TestUpsertRecords:
    @pytest.fixture
    def db(self):
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE external_orders (
                platform VARCHAR NOT NULL,
                external_id VARCHAR NOT NULL,
                credential_ref VARCHAR NOT NULL,
                order_status VARCHAR,
                ship_to_state VARCHAR,
                canonical_hash VARCHAR NOT NULL,
                raw_json VARCHAR,
                PRIMARY KEY (platform, external_id, credential_ref)
            )
        """)
        yield conn
        conn.close()

    def test_insert_new_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
            {"platform": "shopify", "external_id": "2", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "CA", "canonical_hash": "bbb", "raw_json": "{}"},
        ]
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["inserted"] == 2
        assert result["updated"] == 0

    def test_skip_unchanged_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
        ]
        upsert_records_to_duckdb(db, records, "external_orders",
                                  ["platform", "external_id", "credential_ref"])

        # Re-upsert same data — should skip (hash unchanged)
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["inserted"] == 0
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_update_changed_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
        ]
        upsert_records_to_duckdb(db, records, "external_orders",
                                  ["platform", "external_id", "credential_ref"])

        # Change status + hash
        records[0]["order_status"] = "closed"
        records[0]["canonical_hash"] = "bbb"
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["updated"] == 1
        row = db.execute("SELECT order_status FROM external_orders WHERE external_id='1'").fetchone()
        assert row[0] == "closed"

    def test_batch_dedupe_keeps_latest(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "canonical_hash": "aaa", "raw_json": "{}"},
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "closed", "canonical_hash": "bbb", "raw_json": "{}"},
        ]
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        row = db.execute("SELECT order_status FROM external_orders WHERE external_id='1'").fetchone()
        assert row[0] == "closed"  # last one wins

    def test_cross_platform_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
            {"platform": "amazon", "external_id": "1", "credential_ref": "us_store",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "bbb", "raw_json": "{}"},
        ]
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["inserted"] == 2
        count = db.execute("SELECT COUNT(*) FROM external_orders").fetchone()[0]
        assert count == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/data_source/test_upsert_tools.py -v`
Expected: FAIL — import errors

**Step 3: Implement upsert_records_to_duckdb**

**CRITICAL: Uses atomic INSERT ... ON CONFLICT DO UPDATE ... WHERE canonical_hash differs.**
Counts (inserted/updated/skipped) are computed from a single pre-read SELECT of existing hashes,
then one bulk INSERT ... ON CONFLICT handles all writes atomically.

```python
# src/mcp/data_source/tools/upsert_tools.py
"""DuckDB upsert operations for platform order import.

Uses INSERT ... ON CONFLICT DO UPDATE ... WHERE canonical_hash <> excluded.canonical_hash
for atomic, change-detection-aware upserts. See DuckDB docs:
https://duckdb.org/docs/stable/sql/statements/insert.html

Counting strategy:
1. Dedupe batch by PK (keep last occurrence)
2. Single SELECT of existing hashes for those PKs
3. Classify: new (inserted) / changed (updated) / unchanged (skipped)
4. Single INSERT ... ON CONFLICT for ALL rows (atomic)
5. Return pre-computed counts
"""
from __future__ import annotations

import logging
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


def _dedupe_batch(
    records: list[dict[str, Any]],
    pk_columns: list[str],
) -> list[dict[str, Any]]:
    """Deduplicate records within a batch by PK, keeping the last occurrence.

    Required because DuckDB INSERT ... ON CONFLICT errors when the same PK
    appears multiple times in a single statement (common with overlap windows).
    """
    seen: dict[tuple, dict[str, Any]] = {}
    for record in records:
        key = tuple(record.get(col) for col in pk_columns)
        seen[key] = record  # last one wins
    return list(seen.values())


def _classify_records(
    conn: duckdb.DuckDBPyConnection,
    records: list[dict[str, Any]],
    table_name: str,
    pk_columns: list[str],
) -> dict[str, int]:
    """Pre-compute inserted/updated/skipped counts via hash comparison.

    Single SELECT for all PKs in the batch. Returns counts only — the actual
    write is handled by the ON CONFLICT upsert.
    """
    existing_hashes: dict[tuple, str] = {}
    pk_tuples = [tuple(r.get(col) for col in pk_columns) for r in records]

    if pk_tuples:
        pk_cols_sql = ", ".join(pk_columns)
        # Build safe parameterized IN clause
        pk_placeholders = ", ".join(
            f"({', '.join('?' for _ in pk_columns)})" for _ in pk_tuples
        )
        pk_values = [v for t in pk_tuples for v in t]
        try:
            rows = conn.execute(
                f"SELECT {pk_cols_sql}, canonical_hash FROM {table_name} "
                f"WHERE ({pk_cols_sql}) IN ({pk_placeholders})",
                pk_values,
            ).fetchall()
            for row in rows:
                key = tuple(row[:-1])
                existing_hashes[key] = row[-1]
        except duckdb.CatalogException:
            pass  # Table doesn't exist yet — all records are inserts

    inserted = updated = skipped = 0
    for record in records:
        key = tuple(record.get(col) for col in pk_columns)
        existing_hash = existing_hashes.get(key)
        if existing_hash is None:
            inserted += 1
        elif existing_hash != record.get("canonical_hash"):
            updated += 1
        else:
            skipped += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def upsert_records_to_duckdb(
    conn: duckdb.DuckDBPyConnection,
    records: list[dict[str, Any]],
    table_name: str,
    pk_columns: list[str],
) -> dict[str, int]:
    """Upsert records into DuckDB with hash-based change detection.

    1. Deduplicates within batch (last occurrence wins per PK)
    2. Pre-computes inserted/updated/skipped counts via hash comparison
    3. Executes atomic INSERT ... ON CONFLICT DO UPDATE ... WHERE hash differs
    4. Returns pre-computed counts

    The ON CONFLICT ... WHERE clause ensures unchanged rows are skipped at
    the SQL level, keeping DuckDB churn minimal.
    """
    if not records:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    # Step 1: Dedupe within batch (prevents DuckDB duplicate-PK-in-statement errors)
    deduped = _dedupe_batch(records, pk_columns)

    # Step 2: Pre-compute counts
    counts = _classify_records(conn, deduped, table_name, pk_columns)

    # Step 3: Atomic upsert via ON CONFLICT DO UPDATE ... WHERE hash differs
    columns = list(deduped[0].keys())
    cols_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    pk_conflict = ", ".join(pk_columns)

    # Build SET clause for all non-PK columns
    non_pk = [c for c in columns if c not in pk_columns]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in non_pk)

    upsert_sql = (
        f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_conflict}) DO UPDATE SET {set_clause} "
        f"WHERE {table_name}.canonical_hash <> excluded.canonical_hash"
    )

    for record in deduped:
        values = [record.get(col) for col in columns]
        conn.execute(upsert_sql, values)

    return counts
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp/data_source/test_upsert_tools.py -v`
Expected: All PASS

**Step 5: Register upsert_records as MCP tool in server.py**

Modify `src/mcp/data_source/server.py` — add `from src.mcp.data_source.tools.upsert_tools import upsert_records` and register: `mcp.tool()(upsert_records)` after line 130.

Also create the MCP-facing `upsert_records` async function in the tools module that wraps `upsert_records_to_duckdb` with the server's DuckDB connection from lifespan context.

**Step 6: Commit**

```bash
git add src/mcp/data_source/tools/upsert_tools.py src/mcp/data_source/server.py tests/mcp/data_source/test_upsert_tools.py
git commit -m "feat(data-source): add upsert_records tool with hash-based change detection"
```

---

### Task 5.1: DummyPlatform MCP (Vertical Slice)

**De-risk the orchestration core before dealing with real platform quirks.** Build a minimal DummyPlatform MCP that returns fixed 2-page order data. Then wire ActivationService against it to prove the end-to-end shape: spawn → connect → page → normalize → upsert → checkpoint.

**Files:**
- Create: `src/mcp/platforms/dummy/__init__.py`
- Create: `src/mcp/platforms/dummy/server.py`
- Create: `src/mcp/platforms/dummy/mapper.py`
- Test: `tests/mcp/platforms/dummy/test_vertical_slice.py`

**Step 1: Implement DummyPlatform MCP**

Minimal FastMCP server implementing the full contract:
- `platform.health()` — always returns ok, contract_version "1.0"
- `platform.capabilities()` — supports ["orders.list", "orders.get"]
- `auth.connect(credential_ref)` — always succeeds
- `orders.list(cursor?, since?)` — returns 2 pages of 3 fixed orders each. Page 1 returns `next_cursor="page2"`, page 2 returns `next_cursor=None`
- `orders.get(order_id)` — returns matching fixed order
- `tracking.write_back(...)` — no-op success

**Step 2: Implement DummyMapper**

Pure mapper that converts dummy orders to flat DuckDB rows with canonical_hash.

**Step 3: Add "dummy" to PLATFORM_CONFIGS (enabled=False by default, enabled in tests)**

**Step 4: Write vertical slice integration test**

```python
# tests/mcp/platforms/dummy/test_vertical_slice.py
"""End-to-end vertical slice: DummyPlatform -> Gateway -> ActivationService -> DuckDB."""
import pytest
# This test imports ActivationService, Gateway, Registry, and DummyPlatform
# and proves the full chain works before real platform extraction.

class TestDummyPlatformVerticalSlice:
    @pytest.mark.asyncio
    async def test_full_activation_imports_all_pages(self):
        """Activate dummy platform -> 2 pages -> 6 orders in DuckDB."""
        # Setup: registry, gateway, data gateway (DuckDB in-memory)
        # Activate: activation_service.activate_platform("dummy", "test")
        # Assert: 6 rows in external_orders with platform="dummy"
        # Assert: watermark advanced, resume_cursor cleared
        pass  # Implementation depends on Tasks 3-7 being wired

    @pytest.mark.asyncio
    async def test_refresh_with_watermark_skips_old_orders(self):
        """Second activation with mode=refresh passes since= to orders.list."""
        pass

    @pytest.mark.asyncio
    async def test_resume_after_simulated_crash(self):
        """Set resume_cursor in registry, verify activation resumes from cursor."""
        pass
```

**Step 5: Commit**

```bash
git add src/mcp/platforms/dummy/ tests/mcp/platforms/dummy/
git commit -m "feat(platform): add DummyPlatform MCP for vertical slice testing"
```

---

### Task 6: PlatformGateway Service

Runtime client manager with lazy spawn, idle reap, circuit breaker, QPS limiting, and state update queue. This is the most complex service.

**Files:**
- Create: `src/services/platform_gateway.py`
- Create: `tests/services/fake_mcp_session.py` (test helper)
- Test: `tests/services/test_platform_gateway.py`

**IMPORTANT: Use a FakeSession, not pure mocks.** Mocks miss sequencing bugs (timeouts,
cancellation, active_calls decrement in finally, probe exclusivity). The FakeSession has
programmable behavior per tool and call counters.

```python
# tests/services/fake_mcp_session.py
"""Fake MCP session for deterministic gateway tests."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class FakeSession:
    """Programmable fake MCP session for gateway testing.

    Supports: success responses, error responses, timeouts, call counting.
    """

    def __init__(self):
        self.call_count: dict[str, int] = defaultdict(int)
        self._responses: dict[str, list[dict | Exception]] = {}
        self._default_response: dict[str, Any] = {"success": True}
        self.closed = False

    def program(self, tool_name: str, responses: list[dict | Exception]):
        """Set responses for a tool (consumed in order, last one repeats)."""
        self._responses[tool_name] = list(responses)

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Simulate an MCP tool call."""
        self.call_count[tool_name] += 1
        responses = self._responses.get(tool_name, [self._default_response])
        response = responses.pop(0) if len(responses) > 1 else responses[0]
        if isinstance(response, asyncio.TimeoutError):
            raise response
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        self.closed = True
```

**Step 1: Write failing tests for core gateway behavior**

Tests use FakeSession for deterministic behavior. Key test cases:
- `test_call_tool_spawns_on_first_use` — connection created lazily
- `test_call_tool_reuses_existing_connection` — second call doesn't respawn
- `test_circuit_opens_after_consecutive_failures` — 5 TRANSIENT errors → open
- `test_circuit_half_open_allows_one_probe` — after timeout, one call allowed
- `test_circuit_closes_on_probe_success` — successful probe → closed
- `test_rate_limited_does_not_trip_circuit` — RATE_LIMITED errors don't increment breaker
- `test_reaper_skips_connections_with_active_calls` — in-flight calls prevent teardown
- `test_reaper_tears_down_idle_connections` — idle > TTL → teardown
- `test_contract_version_mismatch_raises` — wrong version → PlatformContractMismatchError
- `test_disconnect_tears_down_and_updates_registry` — clean disconnect
- `test_shutdown_flushes_state_update_queue` — enqueue updates, shutdown, verify flushed
- `test_per_call_timeout_triggers_transient` — hung call → timeout → failure recorded

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_platform_gateway.py -v`
Expected: FAIL — import errors

**Step 3: Implement PlatformGateway**

Implement `src/services/platform_gateway.py` with:
- `PlatformConnection` dataclass (process, session, semaphore, qps_limiter, circuit state, active_calls, lifecycle_lock)
- `PlatformGateway` class with `startup()`, `shutdown()`, `call_tool()`, convenience methods
- Lazy `_ensure_connection()` with contract version check
- Circuit breaker with `_record_failure()`, `_record_success()`, probe exclusivity
- State update queue (asyncio.Queue + background worker)
- Reaper loop checking `active_calls == 0` before teardown
- Per-call timeout via `asyncio.wait_for`

Use `src/services/mcp_client.py:MCPClient` patterns for stdio lifecycle. The gateway creates its own `MCPClient` instances per connection (not the singleton pattern from `gateway_provider.py`).

For QPS limiting, implement a simple token bucket or use `asyncio.Semaphore` with timed release. If `aiolimiter` is not a dependency, implement a minimal `TokenBucketLimiter` class inline.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_platform_gateway.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/services/platform_gateway.py tests/services/test_platform_gateway.py
git commit -m "feat(platform): add PlatformGateway with lifecycle, circuit breaker, and QPS limiting"
```

---

### Task 7: PlatformActivationService

Connect → page → normalize → upsert → checkpoint orchestration.

**Files:**
- Create: `src/services/platform_activation_service.py`
- Test: `tests/services/test_platform_activation_service.py`

**Step 1: Write failing tests**

Key test cases:
- `test_activate_initial_sync_full_pull` — pages through all orders, imports to DuckDB
- `test_activate_refresh_uses_watermark_minus_overlap` — since = watermark - overlap_seconds
- `test_checkpoint_persisted_per_page` — resume_cursor saved after each batch
- `test_watermark_only_advanced_on_completion` — watermark is None during sync, set at end
- `test_resume_from_cursor_after_crash` — if resume_cursor set, starts from there
- `test_missing_credentials_raises` — KeyringStore missing keys → clear error
- `test_capabilities_cached_after_connect` — registry.record_capabilities called
- `test_activate_multiple_runs_in_parallel` — asyncio.gather with error handling
- `test_batch_dedupe_before_upsert` — overlapping orders deduplicated
- `test_sync_run_id_consistent_within_run` — all rows in a run share the same sync_run_id
- `test_checkpoint_only_after_upsert_commit` — simulate upsert failure, verify cursor NOT advanced
- `test_watermark_not_advanced_on_partial_failure` — crash mid-sync, watermark stays at previous value

**Step 2-5: Implement, test, commit**

Implement `src/services/platform_activation_service.py` following the design doc Section 5 flow exactly. The service takes `PlatformRegistry`, `PlatformGateway`, and a data gateway reference. The page loop calls `gateway.fetch_orders_page()`, maps via the platform's mapper module, dedupes, upserts via `data_gateway.upsert_records()`, and checkpoints.

```bash
git add src/services/platform_activation_service.py tests/services/test_platform_activation_service.py
git commit -m "feat(platform): add PlatformActivationService with resumable sync and change detection"
```

---

### Task 8: Meta-Platform Agent Tools

Thin dispatchers that replace `connect_shopify` and `get_platform_status`.

**Files:**
- Create: `src/orchestrator/agent/tools/platforms.py`
- Modify: `src/orchestrator/agent/tools/__init__.py:29-37` (update imports)
- Modify: `src/orchestrator/agent/tools/__init__.py:281-302` (replace tool definitions)
- Modify: `src/orchestrator/agent/tools/__init__.py:768-779` (update interactive_allowed)
- Test: `tests/orchestrator/agent/tools/test_platforms.py`

**Step 1: Write failing tests**

```python
# tests/orchestrator/agent/tools/test_platforms.py
"""Tests for meta-platform agent tools."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.orchestrator.agent.tools.platforms import (
    list_platforms_tool,
    activate_platform_tool,
    refresh_platform_tool,
    refresh_all_platforms_tool,
    disconnect_platform_tool,
    get_platform_capabilities_tool,
)


class TestListPlatformsTool:
    @pytest.mark.asyncio
    async def test_returns_platform_summaries(self):
        mock_summary = MagicMock()
        mock_summary.platform_id = "shopify"
        mock_summary.connection_status = "connected"

        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get:
            mock_registry = AsyncMock()
            mock_registry.get_platforms_summary.return_value = [mock_summary]
            mock_get.return_value = mock_registry

            result = await list_platforms_tool({})
            assert result["success"] is True
            assert result["data"]["total"] == 1


class TestActivatePlatformTool:
    @pytest.mark.asyncio
    async def test_validates_platform_id_against_registry(self):
        with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_get:
            mock_registry = AsyncMock()
            mock_registry.get_config.return_value = None  # Unknown platform
            mock_get.return_value = mock_registry

            result = await activate_platform_tool({"platform_id": "nonexistent"})
            assert result["success"] is False
            assert "not found" in result["error"].lower() or "unknown" in result["error"].lower()


class TestRefreshPlatformTool:
    @pytest.mark.asyncio
    async def test_delegates_to_activation_service_with_refresh_mode(self):
        with patch("src.orchestrator.agent.tools.platforms.get_activation_service") as mock_get:
            mock_svc = AsyncMock()
            mock_svc.activate_platform.return_value = MagicMock(
                platform_id="shopify", credential_ref="primary",
                mode="refresh", total_imported=10, pages_fetched=1,
                watermark="2026-02-28T12:00:00Z", duration_seconds=1.5,
                warnings=[],
            )
            mock_get.return_value = mock_svc

            with patch("src.orchestrator.agent.tools.platforms.get_platform_registry") as mock_reg:
                mock_registry = MagicMock()
                mock_registry.get_config.return_value = MagicMock(enabled=True)
                mock_reg.return_value = mock_registry

                result = await refresh_platform_tool({"platform_id": "shopify"})
                mock_svc.activate_platform.assert_called_once_with(
                    platform_id="shopify", credential_ref="primary", mode="refresh",
                )
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestrator/agent/tools/test_platforms.py -v`
Expected: FAIL — import errors

**Step 3: Implement tools/platforms.py**

Implement 6 thin tool handlers. Each validates args, calls the appropriate service, returns structured result. `platform_id` validated against `PlatformRegistry.get_config()` — NOT against a static enum.

**Step 4: Update tools/__init__.py**

- Remove `connect_shopify_tool` and `get_platform_status_tool` imports (lines 29-37)
- Add platform tool imports
- Replace tool definitions at lines 281-302 with `PLATFORM_TOOLS` list
- Ensure platform tools are NOT in `interactive_allowed` set

**Step 5: Run all tool tests**

Run: `pytest tests/orchestrator/agent/tools/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/orchestrator/agent/tools/platforms.py src/orchestrator/agent/tools/__init__.py \
        tests/orchestrator/agent/tools/test_platforms.py
git commit -m "feat(platform): add meta-platform agent tools replacing connect_shopify"
```

---

## Phase B: Switch Over

### Task 9: System Prompt + Agent Config Updates

Wire platform awareness into the agent.

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py:750` (add platform section)
- Modify: `src/orchestrator/agent/config.py:222-224` (remove "external" MCP config)

**Step 1: Add platform section to system prompt**

Add a `_build_platforms_section()` function similar to `_build_contacts_section()`. Inject between line 750 and 751 in the f-string. The section is conditional — only included when platform sync states exist.

**Step 2: Remove external sources MCP config**

In `create_mcp_servers_config()` at line 222-224, remove the `"external"` entry. Platform MCPs are now gateway-managed, not agent-managed.

**Step 3: Run existing agent tests**

Run: `pytest tests/orchestrator/agent/ -v`
Expected: All PASS (no regressions)

**Step 4: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py src/orchestrator/agent/config.py
git commit -m "feat(platform): add platform section to system prompt, remove external MCP from agent config"
```

---

### Task 10: BatchEngine Write-Back Routing

Route tracking write-back through PlatformGateway based on row columns.

**Files:**
- Modify: `src/services/batch_engine.py:839-850` (replace source-type routing)
- Test: `tests/services/test_batch_engine_writeback.py`

**Step 1: Write failing test for platform-aware write-back routing**

Test that when a row has `platform="shopify"` and `credential_ref="primary"`, write-back calls `PlatformGateway.write_back_tracking()` with the correct arguments.

Key test cases:
- `test_writeback_routes_to_correct_platform` — shopify rows → shopify gateway call
- `test_capability_fetch_once_per_platform_per_run` — 5 shopify rows → 1 get_capabilities call
- `test_writeback_skipped_when_unsupported` — platform without tracking.write_back in capabilities → no call
- `test_rate_limited_writeback_does_not_fail_batch` — RATE_LIMITED on write-back retries, doesn't abort the batch
- `test_reads_platform_from_row_columns_not_blob` — uses row.platform/row.credential_ref, not JSON parsing

**Step 2: Modify BatchEngine._write_back_external()**

Replace the current `ExternalSourcesMCPClient.update_tracking()` call with `PlatformGateway.write_back_tracking()`. Read `platform`, `credential_ref`, `external_id` from row columns (not from serialized `order_data` blob). Cache capabilities per `(platform, credential_ref)` per batch run.

**Step 3: Run batch engine tests**

Run: `pytest tests/services/test_batch_engine.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/services/batch_engine.py tests/services/test_batch_engine_writeback.py
git commit -m "feat(platform): route tracking write-back through PlatformGateway by row columns"
```

---

### Task 11: FastAPI Lifespan + Platform API Routes

Wire PlatformGateway into FastAPI lifecycle and add platform management endpoints.

**Files:**
- Modify: `src/api/main.py:458-662` (add gateway startup/shutdown to lifespan)
- Modify: `src/api/routes/platforms.py` (replace monolithic routes with registry-driven routes)
- Test: `tests/api/test_platforms_routes.py`

**Step 1: Add PlatformGateway to FastAPI lifespan**

In `src/api/main.py` lifespan function, after existing startup logic:
- Create `PlatformRegistry` with DB session
- Create `PlatformGateway(registry)`
- Call `gateway.startup()`
- Store in app state
- In shutdown: call `gateway.shutdown()`

**Step 2: Update platform routes**

Replace Shopify-specific routes with generic platform routes:
- `GET /platforms/` → `list_platforms` (from registry)
- `POST /platforms/activate` → `activate_platform` (calls PlatformActivationService)
- `POST /platforms/refresh` → refresh single or all
- `POST /platforms/disconnect` → disconnect
- `GET /platforms/{id}/status` → detailed status + capabilities

Keep backward-compat shims for `GET /platforms/shopify/env-status` and `POST /platforms/shopify/activate` that redirect to the generic endpoints.

**Step 3: Run API tests**

Run: `pytest tests/api/ -v -k "not stream and not sse"`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/api/main.py src/api/routes/platforms.py tests/api/test_platforms_routes.py
git commit -m "feat(platform): wire PlatformGateway into FastAPI lifespan, add generic platform routes"
```

---

### Task 12: Migration Shim — connect_shopify → activate_platform

Temporary backward compatibility during burn-in.

**Files:**
- Modify: `src/orchestrator/agent/tools/data.py:744-777` (point to new activation service)

**Step 1: Replace connect_shopify_tool body**

Keep the tool name registered temporarily. Change its implementation to call `PlatformActivationService.activate_platform("shopify", "primary")`. This is the shim — it will be removed in Phase C.

**Step 2: Run tests**

Run: `pytest tests/orchestrator/agent/tools/ -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add src/orchestrator/agent/tools/data.py
git commit -m "refactor(platform): shim connect_shopify to use PlatformActivationService"
```

---

## Phase C: Clean Up + Expand

### Task 13: Extract WooCommerce/SAP/Oracle Platform MCPs

For each platform, extract client from `src/mcp/external_sources/clients/` into `src/mcp/platforms/{name}/`.

**Files:**
- Create: `src/mcp/platforms/woocommerce/` (server.py, client.py, mapper.py, constants.py, models.py)
- Create: `src/mcp/platforms/sap/` (same structure)
- Create: `src/mcp/platforms/oracle/` (same structure)
- Test: `tests/mcp/platforms/woocommerce/test_server.py` (contract compliance)
- Test: `tests/mcp/platforms/sap/test_server.py`
- Test: `tests/mcp/platforms/oracle/test_server.py`

For each platform: extract client, implement mapper with `to_flat_row()`, implement server with 7 required tools, write contract compliance tests. Follow the same pattern as Task 4 (Shopify).

**Commit per platform:**

```bash
git commit -m "feat(platform): extract WooCommerce into standalone platform MCP"
git commit -m "feat(platform): extract SAP into standalone platform MCP"
git commit -m "feat(platform): extract Oracle into standalone platform MCP"
```

---

### Task 14: Add Amazon Platform MCP

New platform from scratch.

**Files:**
- Create: `src/mcp/platforms/amazon/` (server.py, client.py, mapper.py, constants.py, models.py)
- Test: `tests/mcp/platforms/amazon/test_mapper.py`
- Test: `tests/mcp/platforms/amazon/test_server.py`

Amazon SP-API specifics: OAuth with refresh token, marketplace-specific endpoints, LWA (Login with Amazon) token exchange. The client handles token refresh internally. Mapper normalizes Amazon order fields to the flat column contract.

**Add Amazon credential keys to KeyringStore:**

Modify `src/services/keyring_store.py:21-28` — add `AMAZON_SP_API_REFRESH_TOKEN`, `AMAZON_SP_API_CLIENT_ID`, `AMAZON_SP_API_CLIENT_SECRET`, `AMAZON_MARKETPLACE_ID` to `MANAGED_CREDENTIALS`.

```bash
git commit -m "feat(platform): add Amazon Seller Central platform MCP with SP-API client"
```

---

### Task 15: Delete Monolithic External Sources + Old Shims

Final cleanup after burn-in confirms all platforms work through the new architecture.

**Files:**
- Delete: `src/mcp/external_sources/` (entire directory)
- Delete: `src/services/external_sources_mcp_client.py`
- Delete: `src/services/shopify_activation_service.py`
- Modify: `src/orchestrator/agent/tools/data.py` (remove `connect_shopify_tool`, `get_platform_status_tool`)
- Modify: `src/orchestrator/agent/tools/__init__.py` (remove old imports/definitions)
- Modify: `src/services/gateway_provider.py:42-63` (remove external sources singleton)
- Modify: `src/api/routes/platforms.py` (remove backward-compat shims)
- Delete or update affected tests

**Step 1: Remove all references**

Search for all imports of deleted modules and update or remove them.

Run: `grep -r "external_sources" src/ --include="*.py"` to find all references.
Run: `grep -r "shopify_activation_service" src/ --include="*.py"` to find all references.

**Step 2: Run full test suite**

Run: `pytest -k "not stream and not sse and not progress and not test_stream_endpoint_exists" -v`
Expected: All PASS (no regressions)

**Step 3: Commit**

```bash
git commit -m "refactor(platform): delete monolithic external_sources MCP and old shims"
```

---

## Test Strategy

| Layer | Test Type | What to Test |
|-------|-----------|-------------|
| Contract models | Unit | Serialization, enums, hash computation |
| DB model | Unit | CRUD, composite PK, default values |
| PlatformRegistry | Unit | Config lookup, state transitions, summary join |
| PlatformGateway | Unit (mocked MCP) | Circuit breaker, reaper, concurrency, timeouts |
| Upsert tools | Integration (DuckDB) | Insert, update, skip, dedupe, cross-platform |
| ActivationService | Integration (mocked gateway) | Page loop, checkpoints, resume, watermark |
| Platform mappers | Unit (pure) | Field mapping, hash stability, missing data |
| Platform MCP servers | Contract compliance | Required tools exist, response shapes |
| Meta-tools | Unit (mocked services) | Arg validation, service delegation |
| API routes | Integration (TestClient) | HTTP layer, response shapes |
| End-to-end | Integration | Activate → query → ship → write-back |

Run: `pytest -k "not stream and not sse and not progress and not test_stream_endpoint_exists" -v`

---

## Risk Mitigation

1. **Phase A builds alongside old** — no existing functionality broken until Phase B switch-over.
2. **Migration shim** in Phase B keeps `connect_shopify` working during burn-in.
3. **Each phase has its own commit** — revertable at any point.
4. **Contract compliance tests** catch drift in platform MCP implementations.
5. **Gateway circuit breaker** prevents cascading failures across platforms.
6. **Hash-based upserts** prevent data churn and keep DuckDB efficient.
