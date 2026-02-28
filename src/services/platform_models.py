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
