import pytest


def test_api_and_database_share_the_canonical_job_status_enum():
    from src.api.schemas import JobStatusEnum
    from src.db.models import JobStatus as DatabaseJobStatus
    from src.job_status import JobStatus

    assert JobStatusEnum is JobStatus
    assert DatabaseJobStatus is JobStatus


def test_provider_status_mapping_explicitly_preserves_exposed_job_states():
    from src.job_status import (
        BACKEND_TO_PROVIDER_JOB_STATUS,
        JobStatus,
        ProviderJobStatus,
    )

    assert BACKEND_TO_PROVIDER_JOB_STATUS == {
        JobStatus.pending: ProviderJobStatus.queued,
        JobStatus.running: ProviderJobStatus.running,
        JobStatus.completed: ProviderJobStatus.completed,
        JobStatus.completed_with_warnings: ProviderJobStatus.completed_with_warnings,
        JobStatus.failed: ProviderJobStatus.failed,
        JobStatus.cancelled: ProviderJobStatus.cancelled,
    }


def test_provider_status_mapping_accepts_backend_enum_and_wire_values():
    from src.job_status import (
        BACKEND_TO_PROVIDER_JOB_STATUS,
        JobStatus,
        to_provider_job_status,
    )

    for backend_status, provider_status in BACKEND_TO_PROVIDER_JOB_STATUS.items():
        assert to_provider_job_status(backend_status) is provider_status
        assert to_provider_job_status(backend_status.value) is provider_status

    assert (
        to_provider_job_status("completed_with_warnings")
        is BACKEND_TO_PROVIDER_JOB_STATUS[JobStatus.completed_with_warnings]
    )


def test_unexposed_backend_status_fails_provider_mapping_explicitly():
    from src.job_status import JobStatus, to_provider_job_status

    with pytest.raises(ValueError, match="paused.*not provider-visible"):
        to_provider_job_status(JobStatus.paused)


def test_canonical_status_preserves_the_existing_api_schema_name():
    from src.api.schemas import JobUpdate

    schema = JobUpdate.model_json_schema()

    assert schema["properties"]["status"]["$ref"] == "#/$defs/JobStatusEnum"
    assert "JobStatusEnum" in schema["$defs"]
