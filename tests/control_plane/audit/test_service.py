import json

import pytest
from sqlalchemy import func, select

from src.control_plane.audit import ControlPlaneAuditService
from src.control_plane.audit.models import ControlPlaneAuditEvent


async def test_record_accepts_only_allowed_audit_fields(control_db):
    with pytest.raises(ValueError, match="disallowed key"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="execute_shipment",
            actor_id_hash="actor-1",
            ids={"bad_key": "value"},
        )


async def test_record_rejects_nested_payload_values(control_db):
    with pytest.raises(TypeError, match="sensitive payload values must be scalar"):
        await ControlPlaneAuditService.record(
            session=control_db,
            event_type="prepare_shipments",
            actor_id_hash="actor-1",
            account_id="acct-1",
            safe_fields={"status": {"nested": "value"}},
        )


async def test_record_persists_filtered_payload(control_db):
    event = await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash="actor-1",
        account_id="acct-1",
        provider_connection_id="pc-1",
        device_id="device-1",
        ids={"job_id": "job-1", "correlation_id": "corr-1"},
        hashes={"actor_id_hash": "abc123", "preview_hash": "def456"},
        counts={"row_count": 12},
        safe_fields={"status": "ok", "policy_version": "v1"},
        versions={"schema_version": "1.0.0"},
        error_category="validation",
    )
    await control_db.commit()

    details = json.loads(event.details_json)
    assert details["ids"] == {"job_id": "job-1", "correlation_id": "corr-1"}
    assert details["hashes"] == {"actor_id_hash": "abc123", "preview_hash": "def456"}
    assert details["counts"] == {"row_count": 12}
    assert details["safe_fields"] == {"status": "ok", "policy_version": "v1"}
    assert details["versions"] == {"schema_version": "1.0.0"}
    assert details["error_category"] == "validation"


async def test_cleanup_deletes_account_events_only(control_db):
    await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash="actor-1",
        account_id="acct-a",
        ids={"job_id": "job-a"},
    )
    await ControlPlaneAuditService.record(
        session=control_db,
        event_type="prepare_shipments",
        actor_id_hash="actor-1",
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
