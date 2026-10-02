"""Storage-boundary validation for one-based bounded job row numbers."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, JobRow
from src.errors.terminal_diagnostics import MAX_TERMINAL_ROW_NUMBER
from src.services.job_service import JobService


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.mark.parametrize(
    "row_number",
    [True, 0, -1, MAX_TERMINAL_ROW_NUMBER + 1],
)
def test_create_rows_rejects_invalid_row_numbers_atomically(
    db_session: Session,
    row_number: object,
) -> None:
    service = JobService(db_session)
    job = service.create_job(
        name="Row boundary job",
        original_command="Run the row boundary fixture",
    )

    with pytest.raises(ValueError, match="row_number"):
        service.create_rows(
            job.id,
            [
                {
                    "row_number": 1,
                    "row_checksum": "1" * 64,
                },
                {
                    "row_number": row_number,
                    "row_checksum": "2" * 64,
                },
            ],
        )

    assert db_session.query(JobRow).filter(JobRow.job_id == job.id).count() == 0
    db_session.refresh(job)
    assert job.total_rows == 0


def test_create_rows_rejects_duplicate_row_numbers_atomically(
    db_session: Session,
) -> None:
    service = JobService(db_session)
    job = service.create_job(
        name="Duplicate row boundary job",
        original_command="Run the duplicate row fixture",
    )

    with pytest.raises(ValueError, match="row_number"):
        service.create_rows(
            job.id,
            [
                {"row_number": 1, "row_checksum": "1" * 64},
                {"row_number": 1, "row_checksum": "2" * 64},
            ],
        )

    assert db_session.query(JobRow).filter(JobRow.job_id == job.id).count() == 0
