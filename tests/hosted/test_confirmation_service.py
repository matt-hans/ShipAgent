import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ConfirmationRecord, HostedTenant
from src.hosted.confirmation_service import ConfirmationService

SECRET = "x" * 32
FUTURE_EXPIRES_AT = "2999-01-01T00:00:00+00:00"


def _signed_token(payload):
    payload = {"expires_at": FUTURE_EXPIRES_AT, **payload}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    envelope = {"payload": payload, "sig": sig}
    return base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def create_tenant(db_session):
    tenant = HostedTenant(provider_host="openai", provider_subject="user-1")
    db_session.add(tenant)
    db_session.commit()
    return tenant


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
    assert payload["expires_at"] is not None


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
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
        expires_at=FUTURE_EXPIRES_AT,
    )

    for standard_char in ("+", "/"):
        malformed_token = f"{token[:8]}{standard_char}{token[9:]}"

        assert (
            service.validate_token(
                malformed_token, tenant_id="tenant-1", operation="create_shipments"
            )
            is None
        ), standard_char


def test_token_rejects_bad_base64_padding():
    service = ConfirmationService(secret="x" * 32)
    token = ""
    for i in range(100):
        token = service.issue_token(
            tenant_id="tenant-1",
            confirmation_id=f"conf-{i}",
            operation="create_shipments",
            expires_at=FUTURE_EXPIRES_AT,
        )
        if token.endswith("="):
            break
    assert token.endswith("=")

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


def test_token_rejects_expired_payload():
    service = ConfirmationService(secret="x" * 32)
    token = service.issue_token(
        tenant_id="tenant-1",
        confirmation_id="conf-1",
        operation="create_shipments",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert (
        service.validate_token(
            token, tenant_id="tenant-1", operation="create_shipments"
        )
        is None
    )


def test_persisted_token_records_hash_and_expiry(db_session):
    tenant = create_tenant(db_session)
    service = ConfirmationService(secret=SECRET)
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    token = service.issue_persisted_token(
        db_session,
        tenant_id=tenant.id,
        operation="create_shipments",
        preview_id="preview-1",
        idempotency_key="idem-1",
        expires_at=expires_at,
    )

    record = db_session.scalar(
        select(ConfirmationRecord).where(
            ConfirmationRecord.token_hash == service.token_hash(token)
        )
    )

    assert record is not None
    assert record.tenant_id == tenant.id
    assert record.used_at is None
    assert record.expires_at == expires_at.isoformat()


def test_persisted_token_consumes_once(db_session):
    tenant = create_tenant(db_session)
    service = ConfirmationService(secret=SECRET)
    token = service.issue_persisted_token(
        db_session,
        tenant_id=tenant.id,
        operation="create_shipments",
        preview_id="preview-1",
        idempotency_key="idem-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    payload = service.validate_and_consume_token(
        db_session,
        token=token,
        tenant_id=tenant.id,
        operation="create_shipments",
    )
    replay = service.validate_and_consume_token(
        db_session,
        token=token,
        tenant_id=tenant.id,
        operation="create_shipments",
    )
    record = db_session.scalar(
        select(ConfirmationRecord).where(
            ConfirmationRecord.token_hash == service.token_hash(token)
        )
    )

    assert payload is not None
    assert payload["tenant_id"] == tenant.id
    assert replay is None
    assert record.used_at is not None


def test_signed_but_unpersisted_token_cannot_be_consumed(db_session):
    tenant = create_tenant(db_session)
    service = ConfirmationService(secret=SECRET)
    token = service.issue_token(
        tenant_id=tenant.id,
        confirmation_id="conf-1",
        operation="create_shipments",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    assert (
        service.validate_and_consume_token(
            db_session,
            token=token,
            tenant_id=tenant.id,
            operation="create_shipments",
        )
        is None
    )


def test_persisted_token_rejects_expired_record(db_session):
    tenant = create_tenant(db_session)
    service = ConfirmationService(secret=SECRET)
    token = service.issue_persisted_token(
        db_session,
        tenant_id=tenant.id,
        operation="create_shipments",
        preview_id="preview-1",
        idempotency_key="idem-1",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    payload = service.validate_and_consume_token(
        db_session,
        token=token,
        tenant_id=tenant.id,
        operation="create_shipments",
    )

    assert payload is None


def test_short_secret_is_rejected():
    try:
        ConfirmationService(secret="x" * 31)
    except ValueError as exc:
        assert str(exc) == "confirmation secret must be at least 32 characters"
    else:
        raise AssertionError("expected short confirmation secret to be rejected")
