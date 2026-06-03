import base64
import hashlib
import hmac
import json

from src.hosted.confirmation_service import ConfirmationService

SECRET = "x" * 32


def _signed_token(payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    envelope = {"payload": payload, "sig": sig}
    return base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()


def test_issue_and_validate_confirmation_token():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    payload = service.validate_token(
        token, tenant_id="tenant-1", operation="create_shipments"
    )

    assert payload["confirmation_id"] == "conf-1"


def test_token_rejects_wrong_tenant():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    assert (
        service.validate_token(
            token, tenant_id="tenant-2", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_wrong_operation():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    assert (
        service.validate_token(token, tenant_id="tenant-1", operation="void_shipments")
        is None
    )


def test_token_rejects_tampered_signature():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    envelope = json.loads(base64.urlsafe_b64decode(token.encode()))
    envelope["payload"]["confirmation_id"] = "conf-2"
    tampered_token = base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()

    assert (
        service.validate_token(
            tampered_token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_malformed_token():
    service = ConfirmationService(secret="x" * 32)

    assert (
        service.validate_token(
            "not-a-token", tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_invalid_base64_characters():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    for invalid_char in ("!", " ", "\n", "$"):
        malformed_token = f"{token[:8]}{invalid_char}{token[8:]}"

        assert (
            service.validate_token(
                malformed_token, tenant_id="tenant-1", operation="create_shipments"
            )
            is None
        ), repr(invalid_char)


def test_token_rejects_standard_base64_alphabet_characters():
    service = ConfirmationService(secret=SECRET)

    for confirmation_id, urlsafe_char, standard_char in (
        ("~~", "-", "+"),
        ("~?", "_", "/"),
    ):
        token = _signed_token(
            {
                "tenant_id": "tenant-1",
                "confirmation_id": confirmation_id,
                "operation": "create_shipments",
            }
        )
        assert urlsafe_char in token

        malformed_token = token.replace(urlsafe_char, standard_char, 1)

        assert (
            service.validate_token(
                malformed_token, tenant_id="tenant-1", operation="create_shipments"
            )
            is None
        ), standard_char


def test_token_rejects_bad_base64_padding():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    malformed_token = token.rstrip("=")

    assert (
        service.validate_token(
            malformed_token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_non_string_signature():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    envelope = json.loads(base64.urlsafe_b64decode(token.encode()))
    envelope["sig"] = 123
    malformed_token = base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()

    assert (
        service.validate_token(
            malformed_token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_non_ascii_signature():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
    )

    envelope = json.loads(base64.urlsafe_b64decode(token.encode()))
    envelope["sig"] = "\u00e9" * 64
    malformed_token = base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()

    assert (
        service.validate_token(
            malformed_token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_malformed_payload_type():
    service = ConfirmationService(secret="x" * 32)
    malformed_token = base64.urlsafe_b64encode(
        json.dumps({"payload": "not-a-payload", "sig": "signature"}).encode()
    ).decode()

    assert (
        service.validate_token(
            malformed_token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_signed_payload_missing_confirmation_id():
    service = ConfirmationService(secret=SECRET)
    token = _signed_token(
        {
            "tenant_id": "tenant-1",
            "operation": "create_shipments",
        }
    )

    assert (
        service.validate_token(
            token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_token_rejects_signed_payload_with_non_string_confirmation_id():
    service = ConfirmationService(secret=SECRET)
    token = _signed_token(
        {
            "tenant_id": "tenant-1",
            "confirmation_id": 123,
            "operation": "create_shipments",
        }
    )

    assert (
        service.validate_token(
            token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_short_secret_is_rejected():
    try:
        ConfirmationService(secret="x" * 31)
    except ValueError as exc:
        assert str(exc) == "confirmation secret must be at least 32 characters"
    else:
        raise AssertionError("expected short confirmation secret to be rejected")
