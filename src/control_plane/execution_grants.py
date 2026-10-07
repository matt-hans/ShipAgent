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
  idempotency key. Anything else denies the call and attempts pre-dispatch release.
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
  ``consume`` after acceptance also attempts hold; even if that fails the
  original reservation must remain non-reusable.
* The gate reads ``reservation.binding`` once and accepts only the exact
  ``ExecutionGrantBinding`` type; that validated object is what the handler gets.

The reservation is already non-reusable before dispatch. Settlement has a bounded
local wait; timeout or cancellation does not prove a remote write was rolled back.
An authority must fence every mutation against the original reservation owner,
keep failed/unknown settlements non-reusable, and recheck expiry at consume.
Expiry or lost Redis state denies old authorization; it never remints a grant.
See ``docs/components/execution-grant-authority-contract.md`` for the contract
and the still-missing real-store and invocation-recovery prerequisites.
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
    """Exclusive, fenced ownership while the exact target is being invoked.

    Operations must be idempotent, use bounded I/O, and cooperate with local
    cancellation. A delayed write must never downgrade consumed/held state or
    mutate a replacement reservation. A failed hold is safe only because the
    original reserve already denies reuse. No implementation exists here.
    """

    binding: ExecutionGrantBinding

    async def consume(self) -> None:
        """Record durable acceptance, rechecking original expiry and ownership.

        Expired/lost ownership requires reconciliation, never release or renewed
        authorization. Already accepted target work stays accepted even if this
        write fails. Use the shared Plan 2 lifecycle for acceptance evidence.
        """

    async def release(self) -> None:
        """Allow retry only on proof of nonacceptance within original expiry.

        Compare the reservation fence atomically; never make held/consumed,
        expired, missing, or another owner's reservation reusable.
        """

    async def hold_for_reconciliation(self) -> None:
        """Keep the grant non-reusable when acceptance is unknown.

        The authority later resolves it from the exact target and server-owned
        idempotency key through Plan 2. Its job-reference path returns original
        or recovered work; this gate denies replay until then. Unknown evidence
        stays non-reusable. Neither hold nor recovery renews approval expiry.
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
        atomically deny a second reservation while one is held. Cancellation or
        a lost response after committing leaves a stranded exclusive reserve:
        clean it up only with fenced proof of no dispatch/acceptance, otherwise
        reconcile or expire to denial. Never suppress cancellation and return
        dispatchable ownership. Missing state cannot be rebuilt from an approved
        request or the SQL ledger. Redis/ledger implementation is separate work.
        """
