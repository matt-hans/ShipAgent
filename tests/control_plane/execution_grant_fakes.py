"""Deterministic in-memory ExecutionGrantAuthority for tests only.

TEST DOUBLE: never import from production code. It models the server-side
approve -> reserve -> consume/release lifecycle so gate behaviour can be
asserted without a control-plane store.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_grants import (
    ExecutionGrantBinding,
    ExecutionGrantDenial,
    ExecutionGrantError,
)

FAKE_AMOUNT = "12.34"
FAKE_CURRENCY = "USD"


def make_binding(
    context: AuthorizationContext,
    default_preview_id: str,
    **overrides,
) -> ExecutionGrantBinding:
    """Build a binding that matches ``context`` and the preview by default."""
    values = {
        "account_id": context.account_id,
        "provider_connection_id": context.provider_connection_id,
        "execution_target_id": "target-1",
        "preview_id": default_preview_id,
        "policy": "provider_and_shipagent",
        "amount": FAKE_AMOUNT,
        "currency_code": FAKE_CURRENCY,
        "idempotency_key": "idem-1",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    values.update(overrides)
    return ExecutionGrantBinding(**values)


@dataclass
class FakeReservation:
    """Reservation handed back by the fake authority; mutates its parent state."""

    binding: ExecutionGrantBinding
    approval_request_id: str
    authority: "FakeExecutionGrantAuthority"

    async def consume(self) -> None:
        """Mark the grant terminally consumed (one-time)."""
        self.authority.events.append("consume")
        self.authority.state[self.approval_request_id] = GrantState.CONSUMED

    async def release(self) -> None:
        """Return the grant to reusable after a provable pre-accept failure."""
        self.authority.events.append("release")
        self.authority.state.pop(self.approval_request_id, None)

    async def hold_for_reconciliation(self) -> None:
        """Keep the grant non-reusable until accepted work is reconciled."""
        self.authority.events.append("hold")
        self.authority.state[self.approval_request_id] = GrantState.HELD


class GrantState:
    """Terminal/in-flight states tracked by the stateful fake."""

    RESERVED = "reserved"
    CONSUMED = "consumed"
    HELD = "held"


@dataclass
class FakeExecutionGrantAuthority:
    """Stateful approved-request registry: exclusive reserve, terminal consume."""

    approved: dict[str, ExecutionGrantBinding] = field(default_factory=dict)
    state: dict[str, str] = field(default_factory=dict)
    calls: list[dict[str, str]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    fail_with: Exception | None = None

    async def reserve(
        self,
        *,
        context: AuthorizationContext,
        tool_name: str,
        prepare_tool: str,
        approval_request_id: str,
        preview_id: str,
    ) -> FakeReservation:
        """Reserve exclusively or raise ``ExecutionGrantError``."""
        self.calls.append(
            {
                "tool_name": tool_name,
                "prepare_tool": prepare_tool,
                "approval_request_id": approval_request_id,
                "preview_id": preview_id,
            }
        )
        if self.fail_with is not None:
            raise self.fail_with
        binding = self.approved.get(approval_request_id)
        if binding is None:
            raise ExecutionGrantError(ExecutionGrantDenial.APPROVAL_PENDING)
        current = self.state.get(approval_request_id)
        if current == GrantState.CONSUMED:
            raise ExecutionGrantError(ExecutionGrantDenial.GRANT_CONSUMED)
        if current == GrantState.HELD:
            raise ExecutionGrantError(ExecutionGrantDenial.RECONCILIATION_PENDING)
        if current == GrantState.RESERVED:
            raise ExecutionGrantError(ExecutionGrantDenial.GRANT_IN_USE)
        self.state[approval_request_id] = GrantState.RESERVED
        self.events.append("reserve")
        return FakeReservation(binding, approval_request_id, self)


def approved_authority(
    approval_request_id: str,
    preview_id: str,
    *,
    account_id: str = "acct-1",
    provider_connection_id: str = "pc-1",
) -> FakeExecutionGrantAuthority:
    """Return an authority with one approved request for a fixed caller."""
    context = AuthorizationContext(
        account_id=account_id,
        provider_connection_id=provider_connection_id,
        provider_surface="test",
        subject="test-subject",
        client_id="test-client",
        scopes=frozenset(),
    )
    return FakeExecutionGrantAuthority(
        approved={approval_request_id: make_binding(context, preview_id)}
    )
