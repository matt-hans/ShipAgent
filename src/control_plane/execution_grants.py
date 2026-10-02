"""Server-side Execution Grant contract (ADR 0003, ADR 0008).

An Execution Grant is minted by ShipAgent only after an explicit approval of one
immutable priced preview. The model never holds it: provider calls carry only the
opaque Approval Request reference, which the authority resolves server-side.
This module defines the contract the hosted tool boundary enforces; storage and
the approval flow are separate concerns (no store exists yet).

Responsibility split (callers must honour it):

* The gate (``BoundRegistryTool.run``) enforces what it can check without live
  data: caller account and Provider Connection, requested preview, expiry,
  policy equal to the tool's ``confirmation_policy``, and well-formed target,
  amount (``MONEY_PATTERN``, positive), currency (``RATE_CURRENCY_CODES``) and
  idempotency key. Anything else denies the call and releases the reservation.
* The authority owns live verification. Before ``reserve`` returns, it must
  compare the exact Execution Target, policy, amount, currency and payload of
  the approved preview against the *live* approved preview, and reject drift,
  including a lower amount (ADR 0003), with ``ExecutionGrantDenial.PREVIEW_CHANGED``.
* The handler registered for a confirming tool receives the server-owned
  ``ExecutionGrantBinding`` and must invoke the exact bound Execution Target
  with the binding's idempotency key and approved amount. It signals a failure
  that provably happened before the target accepted anything by raising
  ``PreAcceptFailure``; every other failure or cancellation is ambiguous and
  keeps the grant non-reusable until accepted work is reconciled. A failed
  ``consume`` after acceptance is also held.
* The gate reads ``reservation.binding`` once and accepts only the exact
  ``ExecutionGrantBinding`` type; that validated object is what the handler gets.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from src.control_plane.auth.context import AuthorizationContext
from src.registry.tools.public import MONEY_PATTERN, RATE_CURRENCY_CODES


class ExecutionGrantDenial(StrEnum):
    """Closed, provider-safe reasons an Execution Grant cannot be used."""

    APPROVAL_PENDING = "approval_pending"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    GRANT_CONSUMED = "grant_consumed"
    GRANT_IN_USE = "grant_in_use"
    RECONCILIATION_PENDING = "reconciliation_pending"
    PREVIEW_CHANGED = "preview_changed"
    GRANT_UNAVAILABLE = "execution_grant_unavailable"
    GRANT_INVALID = "execution_grant_invalid"


class ExecutionGrantError(Exception):
    """Raised by an authority when no valid grant can be reserved."""

    def __init__(self, denial: ExecutionGrantDenial) -> None:
        """Carry only the closed denial reason."""
        self.denial = denial
        super().__init__(denial.value)


class PreAcceptFailure(Exception):
    """Handler failure that provably occurred before the target accepted work.

    Only this exception releases a reservation for retry. Raising it when the
    target may have accepted the invocation risks a duplicate purchase.
    """


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

    def validate(self, *, policy: str | None) -> None:
        """Raise ``ValueError`` unless every field is well formed.

        ``policy`` is the tool contract's ``confirmation_policy`` the binding
        must equal. Account, connection and preview matching is the gate's job.
        """
        text_fields = (
            self.account_id,
            self.provider_connection_id,
            self.execution_target_id,
            self.preview_id,
            self.policy,
            self.idempotency_key,
        )
        if not all(isinstance(value, str) and value for value in text_fields):
            raise ValueError("binding identity fields must be non-empty strings")
        if policy is None or self.policy != policy:
            raise ValueError("binding policy does not match the tool policy")
        if not isinstance(self.amount, str) or not re.fullmatch(
            MONEY_PATTERN, self.amount
        ):
            raise ValueError("binding amount is not canonical money")
        if Decimal(self.amount) <= 0:
            raise ValueError("binding amount must be positive")
        if self.currency_code not in RATE_CURRENCY_CODES:
            raise ValueError("binding currency is not supported")
        if (
            not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("binding expiry must be timezone-aware")


class ExecutionGrantReservation(Protocol):
    """A grant held while the exact Execution Target is being invoked."""

    binding: ExecutionGrantBinding

    async def consume(self) -> None:
        """Mark the grant used once the target durably accepts the invocation."""

    async def release(self) -> None:
        """Return the grant for retry after a provable failure before acceptance."""

    async def hold_for_reconciliation(self) -> None:
        """Keep the grant non-reusable when acceptance is unknown.

        The authority later resolves it from the idempotency key: repeated calls
        return the original or recovered job rather than a second purchase.
        """


class ExecutionGrantAuthority(Protocol):
    """Resolves an opaque Approval Request reference to a reserved grant."""

    async def reserve(
        self,
        *,
        context: AuthorizationContext,
        tool_name: str,
        prepare_tool: str,
        approval_request_id: str,
        preview_id: str,
    ) -> ExecutionGrantReservation:
        """Exclusively reserve the approved grant or raise ``ExecutionGrantError``.

        Must verify the live approved preview (see module docstring) and must
        deny a second reservation of the same grant while one is held.
        """
