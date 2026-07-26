"""Safe diagnostic projections for normal job and row REST responses."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.models import Job, JobRow, JobStatus, RowStatus


def test_job_response_projects_legacy_error_text(
    client: TestClient,
    test_db: Session,
) -> None:
    marker = "UNSAFE_LEGACY_JOB_DIAGNOSTIC"
    job = Job(
        name="Safe projection job",
        original_command="Run the safe projection fixture",
        status=JobStatus.failed.value,
        total_rows=0,
        error_code="E-3001",
        error_message=marker,
    )
    test_db.add(job)
    test_db.commit()

    response = client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["error_code"] == "E-3001"
    assert payload["error_message"] == ("The carrier could not process this shipment.")
    assert marker not in response.text


def test_row_response_projects_unknown_legacy_diagnostic(
    client: TestClient,
    test_db: Session,
) -> None:
    marker = "UNSAFE_LEGACY_ROW_DIAGNOSTIC"
    job = Job(
        name="Safe row projection job",
        original_command="Run the safe row projection fixture",
        status=JobStatus.failed.value,
        total_rows=1,
    )
    test_db.add(job)
    test_db.flush()
    row = JobRow(
        job_id=job.id,
        row_number=1,
        row_checksum="safe-row-checksum",
        status=RowStatus.failed.value,
        error_code="UNSAFE_CODE",
        error_message=marker,
    )
    test_db.add(row)
    test_db.commit()

    response = client.get(f"/api/v1/jobs/{job.id}/rows")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["error_code"] == "E-4001"
    assert payload[0]["error_message"] == (
        "The row could not be processed because of a system error."
    )
    assert marker not in response.text


def test_row_response_projects_message_without_legacy_code(
    client: TestClient,
    test_db: Session,
) -> None:
    marker = "UNSAFE_CODELESS_ROW_DIAGNOSTIC"
    job = Job(
        name="Codeless row projection job",
        original_command="Run the codeless row fixture",
        status=JobStatus.failed.value,
        total_rows=1,
    )
    test_db.add(job)
    test_db.flush()
    row = JobRow(
        job_id=job.id,
        row_number=1,
        row_checksum="safe-codeless-row-checksum",
        status=RowStatus.failed.value,
        error_message=marker,
    )
    test_db.add(row)
    test_db.commit()

    response = client.get(f"/api/v1/jobs/{job.id}/rows")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["error_code"] == "E-4001"
    assert payload[0]["error_message"] == (
        "The row could not be processed because of a system error."
    )
    assert marker not in response.text
