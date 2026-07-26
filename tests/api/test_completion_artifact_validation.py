"""Job-completion artifact validation at the persistence ingress."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.routes.conversations import get_session_messages
from src.api.schemas_conversations import SaveArtifactRequest
from src.db.models import (
    ConversationMessage,
    ConversationSession,
    Job,
    JobRow,
    JobStatus,
    MessageType,
    RowStatus,
)
from src.errors.terminal_diagnostics import MAX_TERMINAL_ROW_DIAGNOSTICS

VALID_JOB_ID = "11111111-1111-4111-8111-111111111111"


def _valid_completion(
    **overrides: object,
) -> dict[str, object]:
    return {
        "status": "completed",
        "outcome": "complete",
        "hasWarnings": False,
        "cancelled": False,
        "statusMessage": "Batch completed.",
        "successful": 1,
        "failed": 0,
        "totalCostCents": 100,
        "omitted_failure_count": 0,
        **overrides,
    }


def test_completion_artifact_rejects_caller_controlled_content():
    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            content="NONEMPTY_COMPLETION_CONTENT",
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": _valid_completion(),
            },
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("successful", "NOT_A_NUMBER"),
        ("successful", True),
        ("successful", -1),
        ("successful", 2_147_483_648),
        ("totalCostCents", "NOT_A_NUMBER"),
        ("totalCostCents", True),
        ("totalCostCents", -1),
        ("totalCostCents", 2_147_483_648),
        ("dutiesTaxesCents", "NOT_A_NUMBER"),
        ("internationalCount", "NOT_A_NUMBER"),
    ],
)
def test_completion_artifact_rejects_unbounded_numeric_scalars(field, value):
    completion = _valid_completion(**{field: value})

    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": completion,
            },
        )


@pytest.mark.parametrize(
    "override",
    [
        {"status": "NOT_A_STATUS"},
        {"outcome": "NOT_AN_OUTCOME"},
        {"hasWarnings": "NOT_A_BOOLEAN"},
        {"cancelled": 1},
        {"status": "completed_with_warnings", "hasWarnings": False},
        {"status": "failed", "outcome": "complete"},
        {"status": "cancelled", "cancelled": False},
        {"status": "completed", "statusMessage": "Batch failed."},
    ],
)
def test_completion_artifact_rejects_invalid_terminal_scalar_mappings(override):
    completion = _valid_completion(**override)

    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": completion,
            },
        )


@pytest.mark.parametrize(
    ("metadata_override", "completion_override"),
    [
        ({"jobId": "NONCANONICAL_JOB_ID"}, {}),
        ({"jobId": 7}, {}),
        ({"action": "NOT_COMPLETE"}, {}),
        ({}, {"jobName": "CALLER_CONTROLLED_NAME"}),
        ({}, {"command": "CALLER_CONTROLLED_COMMAND"}),
    ],
)
def test_completion_artifact_rejects_untrusted_identity_and_display_scalars(
    metadata_override, completion_override
):
    metadata = {
        "type": "completion",
        "jobId": VALID_JOB_ID,
        "action": "complete",
        "completion": _valid_completion(**completion_override),
        **metadata_override,
    }

    with pytest.raises(ValidationError):
        SaveArtifactRequest(metadata=metadata)


@pytest.mark.parametrize(
    "missing_field",
    [
        "status",
        "outcome",
        "hasWarnings",
        "cancelled",
        "statusMessage",
        "successful",
        "failed",
        "totalCostCents",
        "omitted_failure_count",
    ],
)
def test_completion_artifact_requires_the_closed_terminal_shape(missing_field):
    completion = _valid_completion()
    completion.pop(missing_field)

    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": completion,
            },
        )


def test_completion_artifact_rejects_raw_extra_row_diagnostic_fields():
    unsafe_detail = "UNSAFE_DIAGNOSTIC_DETAIL"

    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": _valid_completion(
                    status="failed",
                    outcome="failed",
                    statusMessage="Batch failed.",
                    successful=0,
                    failed=1,
                    totalCostCents=0,
                    row_failures=[
                        {
                            "row_number": 1,
                            "error_code": "E-3003",
                            "error_category": "ups_api",
                            "message": "The carrier could not process this shipment.",
                            "unexpected_detail": unsafe_detail,
                        }
                    ],
                    omitted_failure_count=0,
                ),
            }
        )


@pytest.mark.parametrize(
    "diagnostic",
    [
        {
            "row_number": 1,
            "error_code": "E-9999",
            "error_category": "ups_api",
            "message": "The carrier could not process this shipment.",
        },
        {
            "row_number": 1,
            "error_code": "E-3003",
            "error_category": "ups_api",
            "message": "UNSAFE_NONCANONICAL_MESSAGE",
        },
        {
            "row_number": 0,
            "error_code": "E-3003",
            "error_category": "ups_api",
            "message": "The carrier could not process this shipment.",
        },
    ],
)
def test_completion_artifact_rejects_noncanonical_diagnostics(diagnostic):
    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": _valid_completion(
                    status="failed",
                    outcome="failed",
                    statusMessage="Batch failed.",
                    successful=0,
                    failed=1,
                    totalCostCents=0,
                    row_failures=[diagnostic],
                    omitted_failure_count=0,
                ),
            }
        )


def test_completion_artifact_rejects_inconsistent_omitted_failure_count():
    safe_failure = {
        "row_number": 1,
        "error_code": "E-3003",
        "error_category": "ups_api",
        "message": "The carrier could not process this shipment.",
    }
    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": _valid_completion(
                    status="failed",
                    outcome="failed",
                    statusMessage="Batch failed.",
                    successful=0,
                    failed=2,
                    totalCostCents=0,
                    row_failures=[safe_failure],
                    omitted_failure_count=0,
                ),
            }
        )


def test_completion_artifact_rejects_oversized_diagnostic_array():
    safe_failure = {
        "row_number": 1,
        "error_code": "E-3003",
        "error_category": "ups_api",
        "message": "The carrier could not process this shipment.",
    }
    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": VALID_JOB_ID,
                "action": "complete",
                "completion": _valid_completion(
                    status="failed",
                    outcome="failed",
                    statusMessage="Batch failed.",
                    successful=0,
                    failed=MAX_TERMINAL_ROW_DIAGNOSTICS + 1,
                    totalCostCents=0,
                    row_failures=[safe_failure] * (MAX_TERMINAL_ROW_DIAGNOSTICS + 1),
                    omitted_failure_count=0,
                ),
            }
        )


def test_completion_artifact_accepts_bounded_safe_diagnostics_with_omission():
    row_failures = [
        {
            "row_number": row_number,
            "error_code": "E-3003",
            "error_category": "ups_api",
            "message": "The carrier could not process this shipment.",
        }
        for row_number in range(1, MAX_TERMINAL_ROW_DIAGNOSTICS + 1)
    ]

    payload = SaveArtifactRequest(
        metadata={
            "type": "completion",
            "jobId": VALID_JOB_ID,
            "action": "complete",
            "completion": {
                "status": "completed_with_warnings",
                "outcome": "complete",
                "hasWarnings": True,
                "cancelled": False,
                "statusMessage": "Batch completed with warnings.",
                "successful": 0,
                "failed": MAX_TERMINAL_ROW_DIAGNOSTICS + 3,
                "totalCostCents": 0,
                "row_failures": row_failures,
                "omitted_failure_count": 3,
            },
        }
    )

    assert payload.metadata["completion"]["omitted_failure_count"] == 3


def test_live_artifact_endpoint_accepts_current_empty_content_and_uuid_payload(
    client,
    test_db: Session,
):
    session = ConversationSession(id="live-completion", mode="batch")
    job = Job(
        id=VALID_JOB_ID,
        name="Stored display text",
        original_command="Stored command text",
        status=JobStatus.completed.value,
        total_rows=1,
        processed_rows=1,
        successful_rows=1,
        failed_rows=0,
        total_cost_cents=125,
    )
    row = JobRow(
        job_id=VALID_JOB_ID,
        row_number=1,
        row_checksum="1" * 64,
        status=RowStatus.completed.value,
        cost_cents=125,
    )
    test_db.add_all([session, job, row])
    test_db.commit()

    @contextmanager
    def test_db_context():
        yield test_db

    with patch("src.db.connection.get_db_context", test_db_context):
        response = client.post(
            f"/api/v1/conversations/{session.id}/artifacts",
            json={
                "content": "",
                "metadata": {
                    "type": "completion",
                    "jobId": VALID_JOB_ID,
                    "action": "complete",
                    "completion": _valid_completion(totalCostCents=125),
                },
            },
        )

    assert response.status_code == 201
    stored = (
        test_db.query(ConversationMessage)
        .filter(ConversationMessage.session_id == session.id)
        .one()
    )
    assert stored.content == ""
    assert json.loads(stored.metadata_json)["completion"] == {
        "status": "completed",
        "outcome": "complete",
        "hasWarnings": False,
        "cancelled": False,
        "statusMessage": "Batch completed.",
        "jobName": "Shipping batch",
        "successful": 1,
        "failed": 0,
        "totalCostCents": 125,
        "dutiesTaxesCents": 0,
        "internationalCount": 0,
        "row_failures": [],
        "omitted_failure_count": 0,
    }


@pytest.mark.asyncio
async def test_history_api_projects_legacy_unsafe_detail_before_serialization(
    test_db: Session,
):
    unsafe_detail = "UNSAFE_LEGACY_DETAIL"
    session = ConversationSession(id="history-safe", mode="batch")
    test_db.add(session)
    test_db.add(
        ConversationMessage(
            id="history-message",
            session_id=session.id,
            role="assistant",
            message_type=MessageType.system_artifact.value,
            content="",
            sequence=1,
            metadata_json=json.dumps(
                {
                    "type": "completion",
                    "completion": {
                        "successful": 0,
                        "failed": 1,
                        "rowFailures": [
                            {
                                "rowNumber": 1,
                                "errorCode": "E-3003",
                                "errorMessage": unsafe_detail,
                            }
                        ],
                    },
                }
            ),
        )
    )
    test_db.commit()

    @contextmanager
    def test_db_context():
        yield test_db

    with patch("src.db.connection.get_db_context", test_db_context):
        response = await get_session_messages("history-safe")

    payload = response.model_dump(mode="json")
    completion = payload["messages"][0]["metadata"]["completion"]
    assert completion["row_failures"][0]["message"] == (
        "The carrier could not process this shipment."
    )
    assert unsafe_detail not in json.dumps(payload)
