import hashlib
import json

import pytest
from sqlalchemy import func, select

from src.control_plane.audit import ControlPlaneAuditService
from src.control_plane.audit.models import ControlPlaneAuditEvent

ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"
PROVIDER_CONNECTION_ID = "33333333-3333-4333-8333-333333333333"
DEVICE_ID = "44444444-4444-4444-8444-444444444444"
JOB_ID = "sa_job_0123456789abcdef"
SECOND_JOB_ID = "sa_job_fedcba9876543210"
CORRELATION_ID = "sa_correlation_0123456789abcdef"
PREVIEW_ID = "sa_preview_0123456789abcdef"
CONFIRMATION_ID = "sa_confirmation_0123456789abcdef"
ARTIFACT_ID = "sa_artifact_0123456789abcdef"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def test_record_accepts_only_allowed_audit_fields(control_db):
    with pytest.raises(ValueError, match="disallowed key"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="execute_shipment",
            actor_id_hash=digest("actor-1"),
            ids={"bad_key": "value"},
        )
    with pytest.raises(ValueError, match="disallowed key"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="execute_shipment",
            actor_id_hash=digest("actor-1"),
            safe_fields={"notes": "plain-text"},
        )


async def test_record_rejects_nested_payload_values(control_db):
    with pytest.raises(TypeError, match="sensitive payload values must be scalar"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            account_id=ACCOUNT_ID,
            safe_fields={"status": {"nested": "value"}},
        )


@pytest.mark.parametrize("malformed_hash", ["abc123", "A" * 64, "g" * 64])
async def test_record_rejects_malformed_hash_values(control_db, malformed_hash):
    with pytest.raises(ValueError, match="SHA-256"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            hashes={"request_hash": malformed_hash},
        )


async def test_record_rejects_malformed_actor_hash(control_db):
    with pytest.raises(ValueError, match="SHA-256"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash="actor-1",
        )


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "JaneDoe",
        "742MAINStreet",
        "CustomerAddress",
        "recipientNAME",
        "ApiKeyLiveValue",
        "ACCESSKEYLiveValue",
        "BearerTOKENValue",
        "ClientSECRETValue",
        "PasswordValue",
        "skLiveCredential",
    ],
)
async def test_record_rejects_compact_pii_and_credential_job_ids(
    control_db,
    unsafe_value,
):
    with pytest.raises(ValueError, match="canonical job_id"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            ids={"job_id": unsafe_value},
        )


@pytest.mark.parametrize(
    ("field_name", "unsafe_value"),
    [
        ("account_id", "JaneDoe"),
        ("provider_connection_id", "742MainStreet"),
        ("device_id", "ApiKeyLiveValue"),
    ],
)
async def test_record_rejects_compact_internal_entity_ids(
    control_db,
    field_name,
    unsafe_value,
):
    with pytest.raises(ValueError, match=f"canonical {field_name}"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            **{field_name: unsafe_value},
        )


@pytest.mark.parametrize(
    ("field_name", "unsafe_value"),
    [
        ("correlation_id", "CustomerAddress"),
        ("preview_id", "742MainStreet"),
        ("confirmation_id", "AccessKeyLiveValue"),
    ],
)
async def test_record_rejects_compact_workflow_ids(
    control_db,
    field_name,
    unsafe_value,
):
    with pytest.raises(ValueError, match=f"canonical {field_name}"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            ids={field_name: unsafe_value},
        )


async def test_record_hashes_external_identifiers_before_persistence(control_db):
    external_ids = {
        "provider_subject": "auth0|external-user-123",
        "provider_reference": "provider-reference-456",
        "external_order_id": "customer-order-789",
        "tracking_number": "1Z999AA10123456784",
    }

    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        external_ids=external_ids,
    )

    details = json.loads(event.details_json)
    assert details["hashes"] == {
        f"{key}_hash": digest(value) for key, value in external_ids.items()
    }
    assert all(value not in event.details_json for value in external_ids.values())


@pytest.mark.parametrize(
    ("field_name", "valid_value"),
    [
        ("account_id", ACCOUNT_ID),
        ("account_id", "sa_account_0123456789abcdef"),
        ("provider_connection_id", PROVIDER_CONNECTION_ID),
        ("provider_connection_id", "sa_connection_0123456789abcdef"),
        ("device_id", DEVICE_ID),
        ("device_id", "sa_device_0123456789abcdef"),
    ],
)
async def test_record_accepts_each_internal_entity_id_family(
    control_db,
    field_name,
    valid_value,
):
    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        **{field_name: valid_value},
    )

    assert getattr(event, field_name) == valid_value


@pytest.mark.parametrize(
    ("field_name", "valid_value"),
    [
        ("job_id", JOB_ID),
        ("job_id", "55555555-5555-4555-8555-555555555555"),
        ("correlation_id", CORRELATION_ID),
        ("preview_id", PREVIEW_ID),
        ("confirmation_id", CONFIRMATION_ID),
        ("artifact_id", ARTIFACT_ID),
        ("artifact_id", "sa_label_0123456789abcdef"),
    ],
)
async def test_record_accepts_each_workflow_id_family(
    control_db,
    field_name,
    valid_value,
):
    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        ids={field_name: valid_value},
    )

    assert json.loads(event.details_json)["ids"] == {field_name: valid_value}


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "Alice Smith",
        "alice@example.com",
        '{"recipient":"Alice"}',
        "sk-live-secret-token",
        "job-1\ncustomer-data",
        "j" * 37,
    ],
)
async def test_record_rejects_plaintext_and_token_like_id_values(
    control_db,
    unsafe_value,
):
    with pytest.raises(ValueError, match="canonical job_id"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            ids={"job_id": unsafe_value},
        )


@pytest.mark.parametrize(
    "field_name",
    ["account_id", "provider_connection_id", "device_id"],
)
async def test_record_validates_top_level_canonical_ids(control_db, field_name):
    with pytest.raises(ValueError, match=f"canonical {field_name}"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            **{field_name: "alice@example.com"},
        )


@pytest.mark.parametrize(
    "unsafe_status",
    ["alice@example.com", '{"status":"customer payload"}', "made_up_status"],
)
async def test_record_rejects_invalid_status_codes(control_db, unsafe_status):
    with pytest.raises(ValueError, match="status code"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            safe_fields={"status": unsafe_status},
        )


@pytest.mark.parametrize(
    "unsafe_reason",
    ["alice@example.com", "customer requested shipment to 123 Main St", "other"],
)
async def test_record_rejects_invalid_reason_codes(control_db, unsafe_reason):
    with pytest.raises(ValueError, match="reason code"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            safe_fields={"reason_code": unsafe_reason},
        )


async def test_record_rejects_free_form_status_notes(control_db):
    with pytest.raises(ValueError, match="disallowed key: status_note"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            safe_fields={"status_note": "alice@example.com queued a shipment"},
        )


@pytest.mark.parametrize("unsafe_count", [-1, True, 2**63])
async def test_record_rejects_invalid_counts(control_db, unsafe_count):
    with pytest.raises((TypeError, ValueError), match="counts"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            counts={"row_count": unsafe_count},
        )


@pytest.mark.parametrize(
    "versions",
    [
        {"schema_version": "alice@example.com"},
        {"contract_version": '{"payload":"customer"}'},
        {"policy_version": "version one"},
        {"api_version": "secret-token"},
    ],
)
async def test_record_rejects_invalid_versions(control_db, versions):
    with pytest.raises(ValueError, match="version"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            versions=versions,
        )


@pytest.mark.parametrize(
    "oversized_version",
    [
        f"1.{'9' * 65}.0",
        f"1.0.0-{'a' * 65}",
        f"1.0.0+{'b' * 65}",
        f"{'1' * 22}.{'2' * 22}.{'3' * 22}",
    ],
    ids=["numeric", "prerelease", "build", "total"],
)
async def test_record_rejects_oversized_version_codes(
    control_db,
    oversized_version,
):
    with pytest.raises(ValueError, match="at most 64 characters"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            versions={"schema_version": oversized_version},
        )


@pytest.mark.parametrize(
    "unsafe_event_type",
    [
        "alice@example.com shipped to 123 Main St",
        '{"payload":"customer"}',
        "sk-live-secret-token",
    ],
)
async def test_record_rejects_plaintext_event_types(control_db, unsafe_event_type):
    with pytest.raises(ValueError, match="event type code"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type=unsafe_event_type,
            actor_id_hash=digest("actor-1"),
        )


@pytest.mark.parametrize(
    "unsafe_category",
    ["alice@example.com", '{"payload":"customer"}', "unexpected"],
)
async def test_record_rejects_invalid_error_categories(control_db, unsafe_category):
    with pytest.raises(ValueError, match="error category"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash=digest("actor-1"),
            error_category=unsafe_category,
        )


async def test_record_persists_filtered_payload(control_db):
    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        account_id=ACCOUNT_ID,
        provider_connection_id=PROVIDER_CONNECTION_ID,
        device_id=DEVICE_ID,
        ids={"job_id": JOB_ID, "correlation_id": CORRELATION_ID},
        hashes={
            "actor_id_hash": digest("actor-1"),
            "preview_hash": digest("preview-1"),
        },
        counts={"row_count": 12},
        safe_fields={"status": "prepared", "reason_code": "user_confirmed"},
        versions={
            "api_version": "v1",
            "policy_version": "v1",
            "schema_version": "1.0.0",
        },
        error_category="validation",
    )
    await control_db.commit()

    details = json.loads(event.details_json)
    assert details["ids"] == {
        "job_id": JOB_ID,
        "correlation_id": CORRELATION_ID,
    }
    assert details["hashes"] == {
        "actor_id_hash": digest("actor-1"),
        "preview_hash": digest("preview-1"),
    }
    assert details["counts"] == {"row_count": 12}
    assert details["safe_fields"] == {
        "reason_code": "user_confirmed",
        "status": "prepared",
    }
    assert details["versions"] == {
        "api_version": "v1",
        "policy_version": "v1",
        "schema_version": "1.0.0",
    }
    assert details["error_category"] == "validation"


async def test_cleanup_deletes_account_events_only(control_db):
    await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        account_id=ACCOUNT_ID,
        ids={"job_id": JOB_ID},
    )
    await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        account_id=SECOND_ACCOUNT_ID,
        ids={"job_id": SECOND_JOB_ID},
    )
    await control_db.commit()

    deleted = await ControlPlaneAuditService.cleanup_for_account(
        session=control_db,
        account_id=ACCOUNT_ID,
    )
    assert deleted == 1

    remaining = (
        await control_db.execute(
            select(ControlPlaneAuditEvent.account_id).where(
                ControlPlaneAuditEvent.account_id == ACCOUNT_ID
            )
        )
    ).all()
    assert remaining == []

    # Keep the second account intact.
    account_b_count = (
        await control_db.execute(
            select(func.count())
            .select_from(ControlPlaneAuditEvent)
            .where(ControlPlaneAuditEvent.account_id == SECOND_ACCOUNT_ID)
        )
    ).scalar()
    assert account_b_count == 1
