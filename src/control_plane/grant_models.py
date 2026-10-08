"""Strict dormant grant values. Raw purchase detail never enters cloud storage."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.control_plane.audit.hash_validation import (
    require_account_id,
    require_connection_id,
)
from src.control_plane.execution_grants import ExecutionGrantBinding
from src.registry.identifiers import ShipAgentIdFamily, shipagent_id_pattern
from src.registry.tools.public import MONEY_PATTERN


class ApprovedPurchase(BaseModel):
    """Trusted live-preview adapter result, never model-supplied authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    account_id: str
    provider_connection_id: str
    execution_target_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
    preview_id: str = Field(pattern=shipagent_id_pattern(ShipAgentIdFamily.PREVIEW))
    tool_name: str = Field(pattern=r"^execute_[a-z0-9_]{1,55}$")
    prepare_tool: str = Field(pattern=r"^prepare_[a-z0-9_]{1,55}$")
    policy: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    amount: str = Field(pattern=MONEY_PATTERN)
    currency_code: str
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_purchase(self):
        from src.registry.tools.public import RATE_CURRENCY_CODES

        require_account_id(self.account_id)
        require_connection_id(self.provider_connection_id)
        if (
            Decimal(self.amount) <= 0
            or Decimal(self.amount) * 100 >= 2**63
            or self.currency_code not in RATE_CURRENCY_CODES
            or self.tool_name.removeprefix("execute_")
            != self.prepare_tool.removeprefix("prepare_")
        ):
            raise ValueError("invalid approved purchase")
        return self

    @property
    def scope_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class GrantRecord(BaseModel):
    """Ephemeral ownership only; never a parallel job/lifecycle record."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    purchase: ApprovedPurchase
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$", repr=False)
    status: Literal["pending", "approved", "reserved", "held", "consumed", "revoked"]
    fence: int = Field(default=0, ge=0, le=2147483647, strict=True)
    owner_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", repr=False)
    lease_expires_at: datetime | None = None
    dispatch_claimed: bool = Field(default=False, strict=True)
    attempt_generation: int = Field(default=0, ge=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def validate_owner(self):
        if self.status in {"pending", "approved"}:
            if self.owner_token is not None or self.lease_expires_at is not None:
                raise ValueError("unreserved grant cannot carry an owner")
        elif self.status in {"reserved", "held", "consumed"}:
            if (
                self.owner_token is None
                or self.lease_expires_at is None
                or not self.fence
            ):
                raise ValueError("owned grant requires a fence")
        if self.lease_expires_at is not None and self.lease_expires_at.tzinfo is None:
            raise ValueError("lease must be timezone aware")
        return self

    def binding(self, expires_at: datetime) -> ExecutionGrantBinding:
        return ExecutionGrantBinding(
            account_id=self.purchase.account_id,
            provider_connection_id=self.purchase.provider_connection_id,
            execution_target_id=self.purchase.execution_target_id,
            preview_id=self.purchase.preview_id,
            policy=self.purchase.policy,
            amount=self.purchase.amount,
            currency_code=self.purchase.currency_code,
            idempotency_key=self.idempotency_key,
            expires_at=expires_at,
            reservation_token=self.owner_token,
        )
