import hashlib
import json

import pytest
from sqlalchemy import func, select

from src.control_plane.audit import ControlPlaneAuditService
from src.control_plane.audit.models import ControlPlaneAuditEvent


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
            account_id="acct-1",
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
    with pytest.raises(ValueError, match="opaque ID"):
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
async def test_record_validates_top_level_opaque_ids(control_db, field_name):
    with pytest.raises(ValueError, match="opaque ID"):
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
        account_id="acct-1",
        provider_connection_id="pc-1",
        device_id="device-1",
        ids={"job_id": "job-1", "correlation_id": "corr-1"},
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
    assert details["ids"] == {"job_id": "job-1", "correlation_id": "corr-1"}
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
        account_id="acct-a",
        ids={"job_id": "job-a"},
    )
    await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash=digest("actor-1"),
        account_id="acct-b",
        ids={"job_id": "job-b"},
    )
    await control_db.commit()

    deleted = await ControlPlaneAuditService.cleanup_for_account(
        session=control_db,
        account_id="acct-a",
    )
    assert deleted == 1

    remaining = (
        await control_db.execute(
            select(ControlPlaneAuditEvent.account_id).where(
                ControlPlaneAuditEvent.account_id == "acct-a"
            )
        )
    ).all()
    assert remaining == []

    # Keep the second account intact.
    account_b_count = (
        await control_db.execute(
            select(func.count())
            .select_from(ControlPlaneAuditEvent)
            .where(ControlPlaneAuditEvent.account_id == "acct-b")
        )
    ).scalar()
    assert account_b_count == 1
