"""Tests for international shipping database columns."""

import json
import os
import tempfile

from sqlalchemy import create_engine, text

from src.db.models import Job, JobRow


class TestJobInternationalColumns:
    """Verify Job model has international columns."""

    def test_job_has_total_duties_taxes_cents(self):
        job = Job(name="test", original_command="test", status="pending")
        assert hasattr(job, "total_duties_taxes_cents")
        assert job.total_duties_taxes_cents is None

    def test_job_has_international_row_count(self):
        job = Job(name="test", original_command="test", status="pending")
        assert hasattr(job, "international_row_count")
        # mapped_column default=0 applies at INSERT time; in-memory may be None
        assert job.international_row_count is None or job.international_row_count == 0


class TestJobRowInternationalColumns:
    """Verify JobRow model has international columns."""

    def test_row_has_destination_country(self):
        row = JobRow(job_id="test", row_number=1, row_checksum="abc")
        assert hasattr(row, "destination_country")
        assert row.destination_country is None

    def test_row_has_duties_taxes_cents(self):
        row = JobRow(job_id="test", row_number=1, row_checksum="abc")
        assert hasattr(row, "duties_taxes_cents")
        assert row.duties_taxes_cents is None

    def test_row_has_charge_breakdown(self):
        row = JobRow(job_id="test", row_number=1, row_checksum="abc")
        assert hasattr(row, "charge_breakdown")
        assert row.charge_breakdown is None

    def test_charge_breakdown_stores_json(self):
        breakdown = {
            "version": "1.0",
            "transportationCharges": {"monetaryValue": "45.50", "currencyCode": "USD"},
            "dutiesAndTaxes": {"monetaryValue": "12.00", "currencyCode": "USD"},
        }
        row = JobRow(
            job_id="test", row_number=1, row_checksum="abc",
            charge_breakdown=json.dumps(breakdown),
        )
        parsed = json.loads(row.charge_breakdown)
        assert parsed["version"] == "1.0"
        assert parsed["transportationCharges"]["monetaryValue"] == "45.50"


class TestMigrationOnExistingDB:
    """Verify columns are added to an existing database without the new columns."""

    def test_migration_adds_columns_to_existing_db(self):
        """Simulate an existing DB that lacks international columns."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Create a DB with the OLD schema (no international columns)
            engine = create_engine(f"sqlite:///{db_path}")
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        original_command TEXT,
                        status TEXT,
                        total_cost_cents INTEGER,
                        shipper_json TEXT,
                        is_interactive BOOLEAN NOT NULL DEFAULT 0
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE job_rows (
                        id TEXT PRIMARY KEY,
                        job_id TEXT,
                        row_number INTEGER,
                        row_checksum TEXT,
                        cost_cents INTEGER
                    )
                """))

            # Run migration
            from src.db.connection import _ensure_columns_exist
            with engine.begin() as conn:
                _ensure_columns_exist(conn)

            # Verify new columns exist
            with engine.begin() as conn:
                cols_jobs = {r[1] for r in conn.execute(text("PRAGMA table_info(jobs)")).fetchall()}
                assert "total_duties_taxes_cents" in cols_jobs
                assert "international_row_count" in cols_jobs

                cols_rows = {r[1] for r in conn.execute(text("PRAGMA table_info(job_rows)")).fetchall()}
                assert "destination_country" in cols_rows
                assert "duties_taxes_cents" in cols_rows
                assert "charge_breakdown" in cols_rows

            # Verify idempotent — running again doesn't crash
            with engine.begin() as conn:
                _ensure_columns_exist(conn)
        finally:
            os.unlink(db_path)
