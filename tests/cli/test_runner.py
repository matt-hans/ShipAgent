"""Tests for InProcessRunner — in-process agent stack."""


from uuid import uuid4

import pytest

from src.cli.runner import InProcessRunner


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Use a fresh temporary database for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Force re-creation of engine with new URL
    import importlib

    import src.db.connection as conn_mod
    importlib.reload(conn_mod)


class TestInProcessRunnerLifecycle:
    """Tests for runner initialization and cleanup."""

    @pytest.mark.asyncio
    async def test_context_manager_initializes_db(self):
        """Entering context initializes the database."""
        runner = InProcessRunner()
        async with runner:
            assert runner._initialized is True

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self):
        """In-process runner always reports healthy."""
        runner = InProcessRunner()
        async with runner:
            status = await runner.health()
            assert status.healthy is True


class TestInProcessRunnerJobs:
    """Tests for job operations via direct DB access."""

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self):
        """Empty database returns empty job list."""
        runner = InProcessRunner()
        async with runner:
            jobs = await runner.list_jobs()
            assert isinstance(jobs, list)
            assert len(jobs) == 0

    @pytest.mark.asyncio
    async def test_list_jobs_with_data(self):
        """Returns JobSummary objects from database."""
        runner = InProcessRunner()
        async with runner:
            from src.db.connection import get_db
            from src.db.models import Job

            db = next(get_db())
            job = Job(
                id=str(uuid4()),
                name="Test Job",
                status="completed",
                original_command="Ship all",
                total_rows=5,
                processed_rows=5,
                successful_rows=4,
                failed_rows=1,
            )
            db.add(job)
            db.commit()

            jobs = await runner.list_jobs()
            assert len(jobs) == 1
            assert jobs[0].status == "completed"

            db.close()

    @pytest.mark.asyncio
    async def test_get_job(self):
        """Returns JobDetail from database."""
        runner = InProcessRunner()
        async with runner:
            from src.db.connection import get_db
            from src.db.models import Job

            job_id = str(uuid4())
            db = next(get_db())
            job = Job(
                id=job_id,
                name="Detail Test",
                status="pending",
                original_command="Ship ground",
                total_rows=10,
            )
            db.add(job)
            db.commit()

            detail = await runner.get_job(job_id)
            assert detail.id == job_id
            assert detail.original_command == "Ship ground"

            db.close()

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        """Raises error for nonexistent job."""
        from src.cli.protocol import ShipAgentClientError

        runner = InProcessRunner()
        async with runner:
            with pytest.raises(ShipAgentClientError):
                await runner.get_job("nonexistent-job")

    @pytest.mark.asyncio
    async def test_cancel_job(self):
        """Cancels a pending job."""
        runner = InProcessRunner()
        async with runner:
            from src.db.connection import get_db
            from src.db.models import Job

            job_id = str(uuid4())
            db = next(get_db())
            job = Job(
                id=job_id,
                name="Cancel Test",
                status="pending",
                original_command="Ship all",
                total_rows=5,
            )
            db.add(job)
            db.commit()

            await runner.cancel_job(job_id)

            db.refresh(job)
            assert job.status == "cancelled"

            db.close()


class TestInProcessRunnerSessions:
    """Tests for session management."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Creates a new agent session."""
        runner = InProcessRunner()
        async with runner:
            session_id = await runner.create_session()
            assert isinstance(session_id, str)
            assert len(session_id) > 0

    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Deletes an agent session without error."""
        runner = InProcessRunner()
        async with runner:
            session_id = await runner.create_session()
            await runner.delete_session(session_id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self):
        """Deleting nonexistent session is a no-op."""
        runner = InProcessRunner()
        async with runner:
            await runner.delete_session("nonexistent")
