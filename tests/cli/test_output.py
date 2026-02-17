"""Tests for CLI output formatting."""

import json

from src.cli.output import format_job_table, format_job_detail, format_cost
from src.cli.protocol import JobSummary, JobDetail


class TestFormatCost:
    """Tests for cost formatting helper."""

    def test_formats_cents_to_dollars(self):
        """Converts cents integer to $X.XX string."""
        assert format_cost(1250) == "$12.50"
        assert format_cost(0) == "$0.00"
        assert format_cost(99) == "$0.99"
        assert format_cost(100000) == "$1,000.00"

    def test_none_returns_dash(self):
        """None cost displays as dash."""
        assert format_cost(None) == "—"


class TestFormatJobTable:
    """Tests for job list table rendering."""

    def test_renders_jobs_as_text(self):
        """Job list renders as a readable table."""
        jobs = [
            JobSummary(
                id="job-123", name="CA Orders", status="completed",
                original_command="Ship all CA orders",
                total_rows=50, processed_rows=50,
                successful_rows=48, failed_rows=2,
                total_cost_cents=24000,
                created_at="2026-02-16T10:00:00Z",
            ),
        ]
        output = format_job_table(jobs, as_json=False)
        assert "job-123" in output
        assert "CA Orders" in output
        assert "completed" in output

    def test_renders_jobs_as_json(self):
        """Job list renders as valid JSON array."""
        jobs = [
            JobSummary(
                id="job-123", name="CA Orders", status="completed",
                original_command="Ship all CA orders",
                total_rows=50, processed_rows=50,
                successful_rows=48, failed_rows=2,
                total_cost_cents=24000,
                created_at="2026-02-16T10:00:00Z",
            ),
        ]
        output = format_job_table(jobs, as_json=True)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert parsed[0]["id"] == "job-123"

    def test_empty_list(self):
        """Empty job list shows informative message."""
        output = format_job_table([], as_json=False)
        assert "No jobs found" in output


class TestFormatJobDetail:
    """Tests for detailed job view rendering."""

    def test_renders_detail_as_text(self):
        """Job detail renders with all fields."""
        detail = JobDetail(
            id="job-123", name="CA Orders", status="completed",
            original_command="Ship all CA orders",
            total_rows=50, processed_rows=50,
            successful_rows=48, failed_rows=2,
            total_cost_cents=62350,
            created_at="2026-02-16T10:00:00Z",
            started_at="2026-02-16T10:01:00Z",
            completed_at="2026-02-16T10:05:00Z",
            error_code=None, error_message=None,
        )
        output = format_job_detail(detail, as_json=False)
        assert "job-123" in output
        assert "$623.50" in output
        assert "Ship all CA orders" in output

    def test_renders_detail_as_json(self):
        """Job detail renders as valid JSON object."""
        detail = JobDetail(
            id="job-123", name="CA Orders", status="completed",
            original_command="Ship all CA orders",
            total_rows=50, processed_rows=50,
            successful_rows=48, failed_rows=2,
            total_cost_cents=62350,
            created_at="2026-02-16T10:00:00Z",
            started_at=None, completed_at=None,
            error_code=None, error_message=None,
        )
        output = format_job_detail(detail, as_json=True)
        parsed = json.loads(output)
        assert parsed["id"] == "job-123"
        assert parsed["total_cost_cents"] == 62350
