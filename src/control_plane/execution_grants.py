"""Server-side Execution Grant contract (ADR 0003, ADR 0008).

An Execution Grant is minted by ShipAgent only after an explicit approval of one
immutable priced preview. The model never holds it: provider calls carry only the
opaque Approval Request reference, which the authority resolves server-side.
This module defines the contract the hosted tool boundary enforces; storage and
the approval flow are separate concerns.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from src.control_plane.auth.context import AuthorizationContext


class ExecutionGrantDenial(StrEnum):
    """Closed, provider-safe reasons an Execution Grant cannot be reserved."""

    APPROVAL_PENDING = "approval_pending"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    GRANT_CONSUMED = "grant_consumed"
    PREVIEW_CHANGED = "preview_changed"


class ExecutionGrantError(Exception):
    """Raised by an authority when no valid grant can be reserved."""

    def __init__(self, denial: ExecutionGrantDenial) -> None:
        self.denial = denial
        super().__init__(denial.value)


@dataclass(frozen=True)
class ExecutionGrantBinding:
    """Exact approved purchase a grant authorizes; every field is server-side."""

    account_id: str
    provider_connection_id: str
    execution_target_id: str
    preview_id: str
    policy: str
    amount: str
    currency_code: str
    idempotency_key: str
    expires_at: datetime


class ExecutionGrantReservation(Protocol):
    """A grant held while the exact Execution Target is being invoked."""

    binding: ExecutionGrantBinding

    async def consume(self) -> None:
        """Mark the grant used once the target durably accepts the invocation."""

    async def release(self) -> None:
        """Return the grant for retry after a failure before acceptance."""


class ExecutionGrantAuthority(Protocol):
    """Resolves an opaque Approval Request reference to a reserved grant."""

    async def reserve(
        self,
        *,
        context: AuthorizationContext,
        tool_name: str,
        prepare_tool: str,
        approval_request_id: str,
    ) -> ExecutionGrantReservation:
        """Reserve the approved grant or raise ``ExecutionGrantError``."""
