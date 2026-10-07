"""Strict, dormant authorization-persistence contracts (no grant authority)."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.control_plane.redis_keys import RedisKey, RedisTtl


def metadata(**changes):
    from src.control_plane.audit.authorization_ledger import AuthorizationMetadata

    values = {
        "account_id": str(uuid4()),
        "provider_connection_id": str(uuid4()),
        "approval_request_id": "sa_approval_request_" + "a" * 32,
        "preview_hash": "b" * 64,
        "purchase_scope_hash": "c" * 64,
        "authorized_amount_minor": 1200,
        "currency": "USD",
        "approving_subject_hash": "d" * 64,
        "execution_target_fingerprint_hash": "e" * 64,
        "idempotency_key_hash": "f" * 64,
        "correlation_id": "sa_correlation_" + "a" * 32,
    }
    values.update(changes)
    return AuthorizationMetadata(**values)


def test_shared_key_and_original_lifetime_policy():
    assert RedisTtl.APPROVAL_REQUEST_SECONDS == 900
    assert RedisTtl.EXECUTION_GRANT_SECONDS == 900
    assert RedisTtl.INVOCATION_SECONDS == RedisTtl.JOB_REFERENCE_SECONDS == 86400
    assert RedisTtl.SWEEP_INTERVAL_SECONDS == 300
    assert RedisKey.approval_request("opaque") == "sa:approval:request:opaque"
    assert RedisKey.execution_grant("opaque") == "sa:approval:grant:opaque"
    assert RedisKey.job_reference("opaque") == "sa:jobref:opaque"
    assert RedisKey.invocation("opaque") == RedisKey.relay_invocation("opaque")
    assert "sa:jobref:*" in RedisKey.ephemeral_patterns()
    assert "sa:job_ref:*" not in RedisKey.ephemeral_patterns()


def test_metadata_is_closed_immutable_and_not_a_capability():
    record = metadata()
    with pytest.raises(AttributeError):
        record.currency = "EUR"
    assert "amount" not in vars(record)  # No raw grant binding or secret credential.
    assert "AuthorizationMetadata" in repr(record)
    assert record.approval_request_id not in repr(record)
    with pytest.raises(TypeError):
        metadata(raw_rows=[{"name": "CUSTOMER_CANARY"}])


@pytest.mark.parametrize(
    "field",
    [
        "account_id",
        "provider_connection_id",
        "approval_request_id",
        "preview_hash",
        "purchase_scope_hash",
        "approving_subject_hash",
        "execution_target_fingerprint_hash",
        "idempotency_key_hash",
        "correlation_id",
        "currency",
    ],
)
@pytest.mark.parametrize(
    "canary",
    [
        "person@example.invalid",
        "https://example.invalid/private",
        "Bearer secret-canary",
        "1Z9999999999999999",
        '{"rows":["ROW_CANARY"],"label":"LABEL_CANARY"}',
    ],
)
def test_metadata_rejects_sensitive_free_text_without_echo(field, canary):
    with pytest.raises(ValueError) as error:
        metadata(**{field: canary})
    assert canary not in str(error.value)


@pytest.mark.parametrize("value", [-1, True, 1.2, "1200", 2**63])
def test_amount_is_a_bounded_strict_minor_unit_integer(value):
    with pytest.raises(ValueError):
        metadata(authorized_amount_minor=value)


@pytest.mark.parametrize(
    "values",
    [
        {"currency": None},
        {"authorized_amount_minor": None},
        {"currency": "usd"},
        {"currency": "ßSD"},
        {"currency": "ABC"},
    ],
)
def test_amount_currency_pair_and_canonical_currency_are_required(values):
    with pytest.raises(ValueError):
        metadata(**values)


def test_nonmonetary_metadata_is_allowed():
    metadata(authorized_amount_minor=None, currency=None)


def test_fixed_lifetime_requires_aware_bounded_original_deadlines():
    from src.control_plane.authorization_state import AuthorizationState

    now = datetime.now(UTC)
    original = AuthorizationState.new(metadata=metadata(), now=now)
    assert (original.expires_at - original.created_at).total_seconds() == 900
    assert original.revision == 0
    with pytest.raises(ValueError):
        AuthorizationState.new(metadata=metadata(), now=now.replace(tzinfo=None))
    with pytest.raises(ValueError):
        replace(original, expires_at=original.created_at)


def test_retention_is_bounded_and_not_enabled_by_local_settings():
    from pydantic import ValidationError

    from src.control_plane.config import ControlPlaneSettings

    settings = ControlPlaneSettings()
    assert settings.audit_retention_days == 90
    assert settings.retention_background_tasks_enabled is False
    for days in (30, 365):
        assert (
            ControlPlaneSettings(audit_retention_days=days).audit_retention_days == days
        )
    for days in (29, 366, True):
        with pytest.raises(ValidationError):
            ControlPlaneSettings(audit_retention_days=days)


def test_state_serializer_rejects_subclasses_before_persisting():
    from src.control_plane.authorization_state import AuthorizationState, _encode

    class UntrustedState(AuthorizationState):
        def __post_init__(self):
            pass

    now = datetime.now(UTC)
    record = UntrustedState(metadata=metadata(), created_at=now, expires_at=now)
    with pytest.raises(ValueError, match="invalid authorization state"):
        _encode(record)
