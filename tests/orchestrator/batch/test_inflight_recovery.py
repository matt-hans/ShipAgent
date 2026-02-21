"""Tests for in-flight row recovery after crash.

Covers the three-tier recovery system in BatchEngine.recover_in_flight_rows():
  Tier 1: Has ups_tracking_number → verify via track_package → complete or needs_review
  Tier 2: No tracking info → mark needs_review (never auto-retry)
  Tier 3: UPS lookup fails → increment counter → escalate after MAX_RECOVERY_ATTEMPTS
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.batch_engine import MAX_RECOVERY_ATTEMPTS, BatchEngine


def _make_inflight_row(
    row_number: int = 1,
    ups_tracking_number: str | None = None,
    ups_shipment_id: str | None = None,
    label_path: str | None = None,
    cost_cents: int | None = None,
    idempotency_key: str = "job-abc:1:checksum",
    recovery_attempt_count: int = 0,
) -> MagicMock:
    """Create a mock in_flight JobRow for recovery tests."""
    row = MagicMock()
    row.row_number = row_number
    row.status = "in_flight"
    row.ups_tracking_number = ups_tracking_number
    row.ups_shipment_id = ups_shipment_id
    row.label_path = label_path
    row.cost_cents = cost_cents
    row.idempotency_key = idempotency_key
    row.recovery_attempt_count = recovery_attempt_count
    row.tracking_number = None
    row.error_message = None
    row.processed_at = None
    return row


def _make_track_response(tracking_number: str = "1Z999AA10000000001") -> dict:
    """Create a mock UPS track_package response."""
    return {
        "trackResponse": {
            "shipment": [{
                "package": [{
                    "trackingNumber": tracking_number,
                    "activity": [{"status": {"description": "Delivered"}}],
                }],
            }],
        },
    }


def _make_empty_track_response() -> dict:
    """Create a mock UPS track_package response with no tracking number."""
    return {
        "trackResponse": {
            "shipment": [{
                "package": [{
                    "trackingNumber": "",
                }],
            }],
        },
    }


@pytest.fixture()
def engine(tmp_path: Path) -> BatchEngine:
    """Create a BatchEngine with mocked UPS client and DB."""
    ups = AsyncMock()
    ups.track_package = AsyncMock(return_value=_make_track_response())
    db = MagicMock()
    return BatchEngine(
        ups_service=ups,
        db_session=db,
        account_number="TEST123",
        labels_dir=str(tmp_path / "labels"),
    )


class TestInFlightRecovery:
    """Verify the three-tier recovery system for in-flight rows."""

    @pytest.mark.asyncio
    async def test_recovery_tier1_completes_with_verified_artifacts(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Tier 1: Row has tracking, UPS confirms, artifacts present → completed."""
        # Create a real label file on disk
        label_dir = tmp_path / "labels"
        label_dir.mkdir(parents=True, exist_ok=True)
        label_file = label_dir / "test_label.pdf"
        label_file.write_bytes(b"%PDF-1.4 test")

        row = _make_inflight_row(
            ups_tracking_number="1Z999AA10000000001",
            label_path=str(label_file),
            cost_cents=1250,
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["recovered"] == 1
        assert result["needs_review"] == 0
        assert result["unresolved"] == 0
        assert row.status == "completed"
        assert row.tracking_number == "1Z999AA10000000001"

    @pytest.mark.asyncio
    async def test_recovery_tier1_needs_review_if_label_missing(
        self, engine: BatchEngine,
    ) -> None:
        """Tier 1: UPS confirms but label file missing → needs_review."""
        row = _make_inflight_row(
            ups_tracking_number="1Z999AA10000000001",
            label_path="/nonexistent/label.pdf",
            cost_cents=1250,
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["needs_review"] == 1
        assert result["recovered"] == 0
        assert row.status == "needs_review"
        assert "label_path" in row.error_message

    @pytest.mark.asyncio
    async def test_recovery_tier1_needs_review_if_cost_missing(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Tier 1: UPS confirms but cost_cents is None → needs_review."""
        label_dir = tmp_path / "labels"
        label_dir.mkdir(parents=True, exist_ok=True)
        label_file = label_dir / "test_label.pdf"
        label_file.write_bytes(b"%PDF-1.4 test")

        row = _make_inflight_row(
            ups_tracking_number="1Z999AA10000000001",
            label_path=str(label_file),
            cost_cents=None,  # Missing cost
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["needs_review"] == 1
        assert row.status == "needs_review"
        assert "cost_cents" in row.error_message

    @pytest.mark.asyncio
    async def test_recovery_tier1_needs_review_if_ups_rejects(
        self, engine: BatchEngine,
    ) -> None:
        """Tier 1: Row has tracking but UPS returns empty → needs_review."""
        engine._ups.track_package = AsyncMock(
            return_value=_make_empty_track_response(),
        )

        row = _make_inflight_row(
            ups_tracking_number="1ZINVALID",
            label_path="/some/path.pdf",
            cost_cents=1000,
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["needs_review"] == 1
        assert row.status == "needs_review"
        assert "empty tracking" in row.error_message.lower() or "invalid" in row.error_message.lower()

    @pytest.mark.asyncio
    async def test_recovery_tier2_marks_needs_review_no_tracking(
        self, engine: BatchEngine,
    ) -> None:
        """Tier 2: No ups_tracking_number → needs_review immediately."""
        row = _make_inflight_row(
            ups_tracking_number=None,
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["needs_review"] == 1
        assert result["recovered"] == 0
        assert result["unresolved"] == 0
        assert row.status == "needs_review"
        assert "idempotency" in row.error_message.lower() or "quantum" in row.error_message.lower()

    @pytest.mark.asyncio
    async def test_recovery_tier2_never_auto_retries(
        self, engine: BatchEngine,
    ) -> None:
        """Tier 2: Rows without tracking are NEVER reset to pending."""
        row = _make_inflight_row(ups_tracking_number=None)

        await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        # Must be needs_review, never pending (which would enable auto-retry)
        assert row.status == "needs_review"
        assert row.status != "pending"

    @pytest.mark.asyncio
    async def test_recovery_tier3_leaves_in_flight_below_max(
        self, engine: BatchEngine,
    ) -> None:
        """Tier 3: track_package fails, below max attempts → stays in_flight."""
        engine._ups.track_package = AsyncMock(
            side_effect=TimeoutError("Network timeout"),
        )

        row = _make_inflight_row(
            ups_tracking_number="1Z999AA10000000001",
            recovery_attempt_count=0,
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["unresolved"] == 1
        assert result["needs_review"] == 0
        assert row.status == "in_flight"  # Not changed
        assert row.recovery_attempt_count == 1

    @pytest.mark.asyncio
    async def test_recovery_tier3_escalates_after_max_attempts(
        self, engine: BatchEngine,
    ) -> None:
        """Tier 3: track_package fails at max attempts → needs_review."""
        engine._ups.track_package = AsyncMock(
            side_effect=TimeoutError("Network timeout"),
        )

        row = _make_inflight_row(
            ups_tracking_number="1Z999AA10000000001",
            recovery_attempt_count=MAX_RECOVERY_ATTEMPTS - 1,
        )

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row],
        )

        assert result["needs_review"] == 1
        assert result["unresolved"] == 0
        assert row.status == "needs_review"
        assert "escalated" in row.error_message.lower()

    @pytest.mark.asyncio
    async def test_recovery_report_includes_all_details(
        self, engine: BatchEngine, tmp_path: Path,
    ) -> None:
        """Recovery returns structured report with per-row details."""
        # Create label for row 1
        label_dir = tmp_path / "labels"
        label_dir.mkdir(parents=True, exist_ok=True)
        label_file = label_dir / "label1.pdf"
        label_file.write_bytes(b"%PDF")

        row1 = _make_inflight_row(
            row_number=1,
            ups_tracking_number="1Z999AA10000000001",
            label_path=str(label_file),
            cost_cents=1000,
            idempotency_key="job-abc:1:aaa",
        )
        row2 = _make_inflight_row(
            row_number=2,
            ups_tracking_number=None,
            idempotency_key="job-abc:2:bbb",
        )
        # Non-in_flight row should be ignored
        row3 = MagicMock()
        row3.status = "completed"

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=[row1, row2, row3],
        )

        assert result["recovered"] == 1
        assert result["needs_review"] == 1
        assert len(result["details"]) == 2
        # Row 1 should be recovered
        r1_detail = next(d for d in result["details"] if d["row_number"] == 1)
        assert r1_detail["action"] == "recovered"
        # Row 2 should be needs_review
        r2_detail = next(d for d in result["details"] if d["row_number"] == 2)
        assert r2_detail["action"] == "needs_review"
        assert "idempotency_key" in r2_detail

    @pytest.mark.asyncio
    async def test_recovery_skips_non_inflight_rows(
        self, engine: BatchEngine,
    ) -> None:
        """Only in_flight rows are processed; pending/completed/failed are skipped."""
        rows = [
            _make_inflight_row(row_number=1, ups_tracking_number=None),
        ]
        # Add non-in_flight rows
        for status in ("pending", "completed", "failed", "needs_review"):
            r = MagicMock()
            r.status = status
            rows.append(r)

        result = await engine.recover_in_flight_rows(
            job_id="job-abc", rows=rows,
        )

        # Only the one in_flight row should be processed
        assert result["needs_review"] == 1
        assert len(result["details"]) == 1
