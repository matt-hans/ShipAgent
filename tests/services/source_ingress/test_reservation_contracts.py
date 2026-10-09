"""Closed private metadata contracts do not convey upload/source authority."""

import importlib
import importlib.util
from dataclasses import asdict

import pytest


def contracts():
    name = "src.services.source_ingress.reservation_contracts"
    assert importlib.util.find_spec(name) is not None, (
        "reservation contracts are absent"
    )
    return importlib.import_module(name)


def request(**overrides):
    values = {
        "request_key": "private-key",
        "content_length": 1,
        "content_sha256": "a" * 64,
    }
    values.update(overrides)
    return contracts().ReservationRequest(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_key": ""},
        {"request_key": "x" * 129},
        {"request_key": "CANARY\n"},
        {"request_key": "CANARY\u0080"},
        {"request_key": "CANARY\ud800"},
        {"content_length": True},
        {"content_length": 0},
        {"content_length": 2**20 + 1},
        {"content_length": 1.0},
        {"content_sha256": "A" * 64},
        {"content_sha256": "a" * 63},
        {"content_sha256": "CANARY\n"},
        {"media_type": "text/csv; charset=utf-8"},
        {"parser_profile": "other_profile"},
    ],
)
def test_invalid_request_has_closed_error_without_values(overrides):
    module = contracts()
    with pytest.raises(module.ReservationError) as caught:
        request(**overrides)
    assert caught.value.code == "invalid_request"
    assert "CANARY" not in str(caught.value) + repr(caught.value)


def test_request_preserves_exact_private_identity_and_is_immutable():
    value = request(request_key="é" * 128, content_length=2**20)
    assert value.request_key == "é" * 128
    assert value.media_type == "text/csv"
    assert value.parser_profile == "synthetic_csv_v1"
    assert "é" not in repr(value)
    assert "a" * 64 not in repr(value)
    with pytest.raises((AttributeError, TypeError)):
        value.request_key = "replacement"


def authority(**overrides):
    values = {
        "account_id": "account-a",
        "provider_connection_id": "connection-a",
        "link_epoch": "epoch-a",
        "execution_target_id": "target-a",
        "target_fingerprint": "fingerprint-a",
        "purpose": "operator_source_setup",
        "authorization_expires_at": 1000,
    }
    values.update(overrides)
    return contracts().ResolvedSourceAuthority(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"account_id": ""},
        {"target_fingerprint": "é" * 129},
        {"link_epoch": None},
        {"link_epoch": "x" * 129},
        {"purpose": "shipagent.preview"},
        {"purpose": "shipagent.status"},
        {"authorization_expires_at": True},
        {"authorization_expires_at": float("inf")},
        {"authorization_expires_at": 0},
    ],
)
def test_authority_data_is_bounded_but_not_itself_a_fence(overrides):
    with pytest.raises(contracts().ReservationError):
        authority(**overrides)


def test_principal_and_resolved_binding_are_private_selectors():
    module = contracts()
    principal = module.SourceOperatorContext("PRIVATE_PRINCIPAL_CANARY")
    resolved = authority(target_fingerprint="PRIVATE_KEY_CANARY")
    assert "PRIVATE_" not in repr(principal) + repr(resolved)
    assert not hasattr(principal, "epoch")
    assert not hasattr(resolved, "acquire")


def namespace(**overrides):
    values = {
        "account_id": "account-a",
        "provider_connection_id": "connection-a",
        "link_epoch": "epoch-a",
        "conversation_reference": "sa_conversation_" + "a" * 32,
        "execution_target_id": "target-a",
        "target_fingerprint": "PRIVATE_KEY_CANARY",
        "request_key": "PRIVATE_REQUEST_CANARY",
    }
    values.update(overrides)
    return contracts().ReservationNamespace(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"conversation_reference": "sa_input_" + "a" * 32},
        {"operation": "execute"},
        {"link_epoch": ""},
        {"request_key": "PRIVATE_REQUEST_CANARY\x00"},
    ],
)
def test_namespace_is_exact_bounded_and_has_no_authorization_expiry(overrides):
    module = contracts()
    with pytest.raises(module.ReservationError):
        namespace(**overrides)
    value = namespace()
    assert value.operation == "upload"
    assert "PRIVATE_" not in repr(value)
    assert "authorization_expires_at" not in asdict(value)


def test_receipt_contains_only_bounded_materialized_reservation_metadata():
    module = contracts()
    value = module.ReservationReceipt(
        reservation_id="b" * 32,
        status="reserved",
        admitted_at=100,
        upload_expires_at=400,
        prospective_source_expires_at=86500,
    )
    assert asdict(value) == {
        "reservation_id": "b" * 32,
        "status": "reserved",
        "admitted_at": 100,
        "upload_expires_at": 400,
        "prospective_source_expires_at": 86500,
    }
    with pytest.raises((AttributeError, TypeError)):
        value.status = "completed"


@pytest.mark.parametrize(
    "code",
    [
        "reservation_unavailable",
        "reservation_expired",
        "request_conflict",
        "source_limit_exceeded",
        "invalid_request",
    ],
)
def test_error_codes_are_closed(code):
    module = contracts()
    error = module.ReservationError(code)
    assert error.code == code
    assert str(error)
    with pytest.raises(ValueError):
        module.ReservationError("PRIVATE_ERROR_CANARY")
