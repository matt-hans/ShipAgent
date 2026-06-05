"""Pydantic DTOs for hosted UPS MCP boundary readiness."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UpsBoundaryCapability(StrEnum):
    """ShipAgent capability names declared by a hosted UPS MCP server."""

    RATE_QUOTE = "rate_quote"
    RATE_SHOP = "rate_shop"
    ADDRESS_VALIDATION = "address_validation"
    CREATE_SHIPMENT = "create_shipment"
    IDEMPOTENCY_METADATA_PASSTHROUGH = "idempotency_metadata_passthrough"
    CARRIER_IDEMPOTENT_CREATE = "carrier_idempotent_create"
    SHIPMENT_RESPONSE_NORMALIZATION = "shipment_response_normalization"
    INTERNATIONAL_CHARGES = "international_charges"
    SAFE_ERROR_MAPPING = "safe_error_mapping"
    MUTATING_RETRY_POLICY = "mutating_retry_policy"


class UpsBoundarySeverity(StrEnum):
    """Readiness check severity levels."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"


class UpsBoundaryCheck(BaseModel):
    """Single hosted UPS boundary readiness check."""

    model_config = ConfigDict(use_enum_values=True)

    name: str
    severity: UpsBoundarySeverity
    message: str


class UpsBoundaryValidationResult(BaseModel):
    """Public validation result for one boundary contract element."""

    name: str
    valid: bool
    error_code: str | None = None
    message: str = ""


class UpsBoundaryCapabilityReport(BaseModel):
    """Hosted UPS MCP capability and readiness report."""

    model_config = ConfigDict(use_enum_values=True)

    contract_version: str = "hosted-v1"
    server_name: str = "ups_mcp"
    server_version: str | None = None
    available_tools: set[str] = Field(default_factory=set)
    declared_capabilities: set[UpsBoundaryCapability] = Field(default_factory=set)
    response_formats: set[str] = Field(default_factory=set)
    missing_tools: list[str] = Field(default_factory=list)
    missing_capabilities: list[UpsBoundaryCapability] = Field(default_factory=list)
    missing_response_formats: list[str] = Field(default_factory=list)
    checks: list[UpsBoundaryCheck] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def ready(self) -> bool:
        """Whether the hosted UPS boundary satisfies required capabilities."""
        if (
            self.missing_tools
            or self.missing_capabilities
            or self.missing_response_formats
        ):
            return False
        if any(check.severity == UpsBoundarySeverity.ERROR for check in self.checks):
            return False

        has_contract_success = any(
            check.name == "boundary_contract"
            and check.severity == UpsBoundarySeverity.OK
            for check in self.checks
        )
        return (
            bool(self.available_tools)
            and bool(self.declared_capabilities)
            and bool(self.response_formats)
            and has_contract_success
        )


class UpsBoundaryReadiness(BaseModel):
    """Hosted UPS MCP production readiness result."""

    model_config = ConfigDict(use_enum_values=True)

    status: Literal["ready", "degraded", "not_ready"]
    report: UpsBoundaryCapabilityReport

    @property
    def production_ready(self) -> bool:
        """Whether the boundary should be treated as production ready."""
        return self.status == "ready"
