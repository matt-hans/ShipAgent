"""Job-completion artifact validation at the persistence ingress."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.routes.conversations import get_session_messages
from src.api.schemas_conversations import SaveArtifactRequest
from src.db.models import ConversationMessage, ConversationSession, MessageType
from src.errors.terminal_diagnostics import MAX_TERMINAL_ROW_DIAGNOSTICS


def test_completion_artifact_rejects_raw_extra_row_diagnostic_fields():
    raw_carrier_text = "request recipient=Jane Doe address=1 Main api_key=token"

    with pytest.raises(ValidationError):
        SaveArtifactRequest(
            metadata={
                "type": "completion",
                "jobId": "job-1",
                "action": "complete",
                "completion": {
                    "successful": 0,
                    "failed": 1,
                    "totalCostCents": 0,
                    "row_failures": [
                        {
                            "row_number": 1,
                            "error_code": "E-3003",
                            "error_category": "ups_api",
                            "message": "The carrier could not process this shipment.",
                            "carrier_response": raw_carrier_text,
                        }
                    ],
                    "omitted_failure_count": 0,
                },
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
            "message": "carrier said recipient=Jane Doe token=secret",
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
                "jobId": "job-1",
                "action": "complete",
                "completion": {
                    "successful": 0,
                    "failed": 1,
                    "totalCostCents": 0,
                    "row_failures": [diagnostic],
                    "omitted_failure_count": 0,
                },
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
                "completion": {
                    "successful": 0,
                    "failed": 2,
                    "totalCostCents": 0,
                    "row_failures": [safe_failure],
                    "omitted_failure_count": 0,
                },
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
                "completion": {
                    "successful": 0,
                    "failed": MAX_TERMINAL_ROW_DIAGNOSTICS + 1,
                    "totalCostCents": 0,
                    "row_failures": [safe_failure] * (MAX_TERMINAL_ROW_DIAGNOSTICS + 1),
                    "omitted_failure_count": 0,
                },
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
            "jobId": "job-1",
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


@pytest.mark.asyncio
async def test_history_api_projects_legacy_carrier_canary_before_serialization(
    test_db: Session,
):
    raw_carrier_text = "request recipient=Jane Doe address=1 Main api_key=token"
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
                                "errorMessage": raw_carrier_text,
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
    assert raw_carrier_text not in json.dumps(payload)
