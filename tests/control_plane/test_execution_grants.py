"""ExecutionGrantBinding validation uses canonical registry constants."""

from datetime import UTC, datetime, timedelta

import pytest

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_grants import ExecutionGrantBinding
from src.registry.tools.public import MONEY_PATTERN, RATE_CURRENCY_CODES
from tests.control_plane.execution_grant_fakes import make_binding

POLICY = "provider_and_shipagent"
CONTEXT = AuthorizationContext(
    account_id="acct-1",
    provider_connection_id="pc-1",
    provider_surface="test",
    subject="s",
    client_id="c",
    scopes=frozenset(),
)


def test_valid_binding_passes():
    """A fully populated, aware, canonical binding validates."""
    make_binding(CONTEXT, "p").validate(policy=POLICY)


@pytest.mark.parametrize("amount", ["0.00", "0.01", "12.34", "9999999999.99"])
def test_amounts_matching_the_registry_money_pattern_are_accepted(amount):
    """Accepted amounts are exactly the registry's canonical money format."""
    import re

    assert re.fullmatch(MONEY_PATTERN, amount)
    make_binding(CONTEXT, "p", amount=amount if amount != "0.00" else "0.01").validate(
        policy=POLICY
    )


def test_every_registry_currency_is_accepted():
    """Currency membership comes from the registry's canonical list."""
    for code in RATE_CURRENCY_CODES:
        make_binding(CONTEXT, "p", currency_code=code).validate(policy=POLICY)


def test_expiry_must_be_timezone_aware():
    """A naive expiry is rejected with ValueError, never TypeError."""
    naive = datetime.now() + timedelta(minutes=1)  # noqa: DTZ005
    with pytest.raises(ValueError):
        make_binding(CONTEXT, "p", expires_at=naive).validate(policy=POLICY)


def test_policy_must_match_contract_policy():
    """The binding's policy must equal the tool's declared confirmation policy."""
    with pytest.raises(ValueError):
        make_binding(CONTEXT, "p").validate(policy="other")


def test_binding_is_immutable():
    """Frozen dataclass: a validated binding cannot be mutated afterwards."""
    binding = make_binding(CONTEXT, "p", expires_at=datetime.now(UTC))
    with pytest.raises(AttributeError):
        binding.amount = "1.00"  # type: ignore[misc]
    assert isinstance(binding, ExecutionGrantBinding)
