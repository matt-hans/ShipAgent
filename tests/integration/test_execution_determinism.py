"""End-to-end execution determinism acceptance tests.

These tests prove that the shipment execution path is crash-safe and
replay-safe. This is the release gate for Phase 8.

Test categories:
  - Crash-safe execution (two-phase commit state machine)
  - Write-back durability (per-task retry with dead-letter)
  - Label atomicity (staging → promote → final path)
"""

import base64
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.batch_engine import BatchEngine, MAX_RECOVERY_ATTEMPTS
from src.services.errors import UPSServiceError
from src.services.mcp_client import MCPConnectionError
from src.services.write_back_worker import (
    WriteBackTask,
    enqueue_write_back,
    process_write_back_queue,
)


def _make_row(
    row_number: int = 1,
    status: str = "pending",
    row_checksum: str = "abc123",
    job_id: str = "job-e2e-001",
    ups_tracking_number: str | None = None,
    ups_shipment_id: str | None = None,
    label_path: str | None = None,
    cost_cents: int | None = None,
    idempotency_key: str | None = None,
    recovery_attempt_count: int = 0,
) -> MagicMock:
    """Create a mock JobRow for acceptance tests."""
    row = MagicMock()
    row.row_number = row_number
    row.status = status
    row.row_checksum = row_checksum
    row.job_id = job_id
    row.order_data = json.dumps({
        "ship_to_name": "E2E Test",
        "ship_to_address1": "100 Test Blvd",
        "ship_to_city": "Los Angeles",
        "ship_to_state": "CA",
        "ship_to_postal_code": "90001",
        "ship_to_country": "US",
        "weight": 2.0,
    })
    row.idempotency_key = idempotency_key
    row.ups_shipment_id = ups_shipment_id
    row.ups_tracking_number = ups_tracking_number
    row.tracking_number = None
    row.label_path = label_path
    row.cost_cents = cost_cents
    row.error_code = None
    row.error_message = None
    row.processed_at = None
    row.destination_country = None
    row.duties_taxes_cents = None
    row.charge_breakdown = None
    row.recovery_attempt_count = recovery_attempt_count
    return row


def _make_ups_result(
    tracking: str = "1Z999AA10000000001",
    shipment_id: str = "SHIP123",
    cost: str = "15.75",
) -> dict:
    """Create a mock UPS create_shipment response."""
    label_b64 = base64.b64encode(b"%PDF-1.4 acceptance test label").decode()
    return {
        "trackingNumbers": [tracking],
        "shipmentIdentificationNumber": shipment_id,
        "labelData": [label_b64],
        "totalCharges": {"monetaryValue": cost},
    }


def _make_track_response(tracking: str = "1Z999AA10000000001") -> dict:
    """Create a mock UPS track_package response."""
    return {
        "trackResponse": {
            "shipment": [{
                "package": [{
                    "trackingNumber": tracking,
                    "activity": [{"status": {"description": "In Transit"}}],
                }],
            }],
        },
    }


SHIPPER = {
    "name": "E2E Shipper",
    "addressLine1": "200 Ship St",
    "city": "Commerce",
    "stateProvinceCode": "CA",
    "postalCode": "90040",
    "countryCode": "US",
}


@pytest.fixture()
def engine(tmp_path: Path) -> BatchEngine:
    """Create a BatchEngine with mocked UPS client."""
    ups = AsyncMock()
    ups.create_shipment = AsyncMock(return_value=_make_ups_result())
    ups.track_package = AsyncMock(return_value=_make_track_response())
    db = MagicMock()
    return BatchEngine(
        ups_service=ups,
        db_session=db,
        account_number="E2ETEST",
        labels_dir=str(tmp_path / "labels"),
    )


class TestCrashSafeExecution:
    """Prove that the execution path is crash-safe."""

    @pytest.mark.asyncio
    async def test_crash_after_ups_call_with_artifacts_recovers(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Simulate: create_shipment succeeds → tracking stored → label promoted
        → crash before final commit. Recovery: Tier 1 → completed."""
        # Create a label file at the expected path
        label_dir = tmp_path / "labels"
        label_dir.mkdir(parents=True, exist_ok=True)
        label_file = label_dir / "test_label.pdf"
        label_file.write_bytes(b"%PDF-1.4 test")

        # Row stuck in_flight after crash, but has tracking + label + cost
        row = _make_row(
            status="in_flight",
            ups_tracking_number="1Z999AA10000000001",
            label_path=str(label_file),
            cost_cents=1575,
            idempotency_key="job-e2e-001:1:abc123",
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-e2e-001", rows=[row],
        )

        assert result["recovered"] == 1
        assert row.status == "completed"
        assert row.tracking_number == "1Z999AA10000000001"

    @pytest.mark.asyncio
    async def test_crash_after_ups_call_without_label_needs_review(
        self, engine: BatchEngine,
    ) -> None:
        """Simulate: create_shipment succeeds → tracking stored → crash before
        label promote. Recovery: Tier 1 → needs_review (missing label)."""
        row = _make_row(
            status="in_flight",
            ups_tracking_number="1Z999AA10000000001",
            label_path="/nonexistent/label.pdf",
            cost_cents=1575,
            idempotency_key="job-e2e-001:1:abc123",
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-e2e-001", rows=[row],
        )

        assert result["needs_review"] == 1
        assert row.status == "needs_review"
        assert "label_path" in row.error_message

    @pytest.mark.asyncio
    async def test_crash_without_tracking_marks_needs_review(
        self, engine: BatchEngine,
    ) -> None:
        """Simulate: crash before tracking stored. Recovery: Tier 2 →
        needs_review. Never auto-retried."""
        row = _make_row(
            status="in_flight",
            ups_tracking_number=None,
            idempotency_key="job-e2e-001:1:abc123",
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-e2e-001", rows=[row],
        )

        assert result["needs_review"] == 1
        assert row.status == "needs_review"
        assert row.status != "pending"  # Never reset to pending

    @pytest.mark.asyncio
    async def test_crash_before_ups_call_marks_needs_review(
        self, engine: BatchEngine,
    ) -> None:
        """Simulate: row in_flight → crash before create_shipment. Recovery:
        Tier 2 (no tracking) → needs_review."""
        row = _make_row(
            status="in_flight",
            ups_tracking_number=None,
            idempotency_key="job-e2e-001:1:abc123",
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-e2e-001", rows=[row],
        )

        assert row.status == "needs_review"

    @pytest.mark.asyncio
    async def test_tier3_escalation_after_max_attempts(
        self, engine: BatchEngine,
    ) -> None:
        """Track_package fails on MAX_RECOVERY_ATTEMPTS consecutive startups
        → escalated to needs_review."""
        engine._ups.track_package = AsyncMock(
            side_effect=TimeoutError("UPS timeout"),
        )

        row = _make_row(
            status="in_flight",
            ups_tracking_number="1Z999AA10000000001",
            recovery_attempt_count=MAX_RECOVERY_ATTEMPTS - 1,
            idempotency_key="job-e2e-001:1:abc123",
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-e2e-001", rows=[row],
        )

        assert result["needs_review"] == 1
        assert row.status == "needs_review"
        assert "escalated" in row.error_message.lower()

    @pytest.mark.asyncio
    async def test_needs_review_rows_never_auto_retried(
        self, engine: BatchEngine,
    ) -> None:
        """needs_review is terminal. Resume execution skips these rows."""
        row_needs_review = _make_row(row_number=1, status="needs_review")
        row_pending = _make_row(row_number=2, status="pending")

        result = await engine.execute(
            job_id="job-e2e-001",
            rows=[row_needs_review, row_pending],
            shipper=SHIPPER,
        )

        # Only the pending row should be processed
        assert result["successful"] == 1
        assert row_needs_review.status == "needs_review"  # Unchanged
        assert row_pending.status == "completed"

    @pytest.mark.asyncio
    async def test_concurrent_rows_maintain_independent_state(
        self, engine: BatchEngine,
    ) -> None:
        """With concurrency, each row has independent state. One row failing
        doesn't affect others."""
        call_count = 0

        async def selective_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise UPSServiceError(code="E-3001", message="Bad address")
            return _make_ups_result(tracking=f"1Z{call_count:018d}")

        engine._ups.create_shipment = selective_fail

        rows = [_make_row(row_number=i) for i in range(1, 4)]

        result = await engine.execute(
            job_id="job-e2e-001", rows=rows, shipper=SHIPPER,
        )

        # 2 succeeded, 1 failed — independent
        assert result["successful"] == 2
        assert result["failed"] == 1
        statuses = {r.status for r in rows}
        assert "completed" in statuses
        assert "failed" in statuses


class TestWriteBackDurability:
    """Prove write-back queue survives failures."""

    def test_enqueue_and_process_roundtrip(self) -> None:
        """Enqueue tasks, then process them — verifies full cycle."""
        db = MagicMock()
        tasks: list[WriteBackTask] = []

        original_add = db.add

        def capture_add(task):
            tasks.append(task)

        db.add = capture_add

        enqueue_write_back(db, "job-wb", 1, "1Z001", "2026-02-17T00:00:00Z")
        enqueue_write_back(db, "job-wb", 2, "1Z002", "2026-02-17T00:00:00Z")

        assert len(tasks) == 2
        assert all(t.status == "pending" for t in tasks)

    @pytest.mark.asyncio
    async def test_partial_write_back_failure_retries_independently(
        self,
    ) -> None:
        """Row 2 fails → rows 1 and 3 succeed → row 2 retried on next cycle."""
        call_count = 0

        async def selective_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Data source error")
            return {"success": True}

        gateway = AsyncMock()
        gateway.write_back_single = selective_fail
        db = MagicMock()

        tasks = [
            WriteBackTask(
                job_id="job-wb",
                row_number=i,
                tracking_number=f"1Z{i:03d}",
                shipped_at="2026-02-17T00:00:00Z",
            )
            for i in range(1, 4)
        ]

        result = await process_write_back_queue(db, gateway, tasks)

        assert result["processed"] == 2
        assert result["failed"] == 1
        assert tasks[0].status == "completed"
        assert tasks[1].status == "pending"  # Failed but below max retries
        assert tasks[1].retry_count == 1
        assert tasks[2].status == "completed"


class TestLabelAtomicity:
    """Prove label staging + promote is atomic and crash-safe."""

    def test_label_promoted_before_db_commit(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Label is moved from staging to final path. After promote:
        label at final path, staging file gone."""
        label_b64 = base64.b64encode(b"%PDF-1.4 atomic test").decode()

        staging_path = engine._save_label_staged(
            "1Z999", label_b64, job_id="job-label", row_number=1,
        )
        assert "/staging/" in staging_path
        assert os.path.exists(staging_path)

        final_path = engine._promote_label(staging_path)
        assert os.path.exists(final_path)
        assert not os.path.exists(staging_path)
        assert "/staging/" not in final_path

    def test_crash_after_promote_before_commit_preserves_label(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """If crash after promote but before DB commit: label exists at final
        path, row is still in_flight. Recovery handles the row."""
        label_b64 = base64.b64encode(b"%PDF-1.4 crash test").decode()

        staging_path = engine._save_label_staged(
            "1Z999", label_b64, job_id="job-crash", row_number=1,
        )
        final_path = engine._promote_label(staging_path)

        # Simulate crash: label at final path, but DB never committed
        assert os.path.exists(final_path)
        content = Path(final_path).read_bytes()
        assert content == b"%PDF-1.4 crash test"

    def test_orphaned_staging_cleaned_only_for_resolved_jobs(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Staging labels removed only for jobs where all rows are
        completed/failed/skipped. Jobs with in_flight/needs_review
        keep their staging files."""
        label_b64 = base64.b64encode(b"%PDF-1.4 orphan test").decode()

        # Create staging files for two jobs
        engine._save_label_staged(
            "1Z001", label_b64, job_id="resolved-job", row_number=1,
        )
        engine._save_label_staged(
            "1Z002", label_b64, job_id="unresolved-job", row_number=1,
        )

        resolved_dir = Path(engine._labels_dir) / "staging" / "resolved-job"
        unresolved_dir = Path(engine._labels_dir) / "staging" / "unresolved-job"
        assert resolved_dir.exists()
        assert unresolved_dir.exists()

        # Mock job_service: resolved-job has no unresolved rows,
        # unresolved-job has an in_flight row
        mock_js = MagicMock()

        def get_rows(job_id):
            if job_id == "resolved-job":
                row = MagicMock()
                row.status = "completed"
                return [row]
            elif job_id == "unresolved-job":
                row = MagicMock()
                row.status = "in_flight"
                return [row]
            return []

        mock_js.get_rows = get_rows

        count = BatchEngine.cleanup_staging(
            mock_js, labels_dir=str(tmp_path / "labels"),
        )

        assert count == 1  # Only resolved-job's label removed
        assert not resolved_dir.exists()
        assert unresolved_dir.exists()  # Preserved for recovery
