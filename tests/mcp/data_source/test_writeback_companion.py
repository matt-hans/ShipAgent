"""Tests for companion file write-back and delimiter-aware delimited write-back."""

import csv
from pathlib import Path

import pytest

from src.services.write_back_utils import (
    apply_delimited_updates_atomic,
    write_companion_csv,
)


class TestDelimitedWriteBack:
    def test_tsv_write_back(self, tmp_path):
        """Write-back preserves tab delimiter."""
        f = tmp_path / "data.tsv"
        f.write_text("name\tcity\nJohn\tDallas\nJane\tAustin")
        updated = apply_delimited_updates_atomic(
            str(f),
            row_updates={1: {"tracking_number": "1Z123"}},
            delimiter="\t",
        )
        assert updated == 1
        content = f.read_text()
        assert "\t" in content
        assert "1Z123" in content

    def test_pipe_write_back(self, tmp_path):
        """Write-back preserves pipe delimiter."""
        f = tmp_path / "data.txt"
        f.write_text("name|city\nJohn|Dallas")
        apply_delimited_updates_atomic(
            str(f),
            row_updates={1: {"tracking_number": "1Z456"}},
            delimiter="|",
        )
        content = f.read_text()
        assert "|" in content
        assert "1Z456" in content

    def test_empty_updates_returns_zero(self, tmp_path):
        """Empty row_updates returns 0 without touching file."""
        f = tmp_path / "data.csv"
        f.write_text("name,city\nJohn,Dallas")
        assert apply_delimited_updates_atomic(str(f), row_updates={}, delimiter=",") == 0

    def test_no_header_raises(self, tmp_path):
        """File with no header raises ValueError."""
        f = tmp_path / "empty.csv"
        f.write_text("")
        with pytest.raises(ValueError, match="no header"):
            apply_delimited_updates_atomic(str(f), row_updates={1: {"x": "y"}})

    def test_row_out_of_range(self, tmp_path):
        """Row number beyond data raises ValueError."""
        f = tmp_path / "data.csv"
        f.write_text("name,city\nJohn,Dallas")
        with pytest.raises(ValueError, match="out of range"):
            apply_delimited_updates_atomic(str(f), row_updates={5: {"x": "y"}})


class TestCompanionFile:
    def test_creates_companion_csv(self, tmp_path):
        """First call creates companion file with header + row."""
        source = tmp_path / "orders.json"
        source.write_text("{}")
        companion = write_companion_csv(
            source_path=str(source),
            row_number=1,
            reference_id="ORD-001",
            tracking_number="1Z999",
            shipped_at="2026-02-20T00:00:00Z",
        )
        assert Path(companion).exists()
        with open(companion) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Tracking_Number"] == "1Z999"
        assert rows[0]["Reference_ID"] == "ORD-001"

    def test_appends_to_existing(self, tmp_path):
        """Subsequent calls append without duplicating header."""
        source = tmp_path / "orders.xml"
        source.write_text("")
        write_companion_csv(str(source), 1, "A", "1Z1", "2026-01-01T00:00:00Z")
        write_companion_csv(str(source), 2, "B", "1Z2", "2026-01-02T00:00:00Z")
        companion_path = str(source).replace(".xml", "_results.csv")
        with open(companion_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2

    def test_companion_path_derives_from_source(self, tmp_path):
        """Companion file name is {stem}_results.csv."""
        source = tmp_path / "shipments.edi"
        source.write_text("")
        companion = write_companion_csv(str(source), 1, "X", "1Z0", "2026-01-01T00:00:00Z")
        assert companion.endswith("shipments_results.csv")

    def test_cost_cents_included(self, tmp_path):
        """Cost cents is written when provided."""
        source = tmp_path / "data.json"
        source.write_text("{}")
        companion = write_companion_csv(
            str(source), 1, "REF", "1Z0", "2026-01-01T00:00:00Z", cost_cents=1299,
        )
        with open(companion) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["Cost_Cents"] == "1299"
