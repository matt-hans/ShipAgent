# tests/mcp/data_source/test_upsert_tools.py
"""Tests for DuckDB upsert_records tool."""
import pytest
import duckdb


class TestUpsertRecords:
    @pytest.fixture
    def db(self):
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE external_orders (
                platform VARCHAR NOT NULL,
                external_id VARCHAR NOT NULL,
                credential_ref VARCHAR NOT NULL,
                order_status VARCHAR,
                ship_to_state VARCHAR,
                canonical_hash VARCHAR NOT NULL,
                raw_json VARCHAR,
                PRIMARY KEY (platform, external_id, credential_ref)
            )
        """)
        yield conn
        conn.close()

    def test_insert_new_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
            {"platform": "shopify", "external_id": "2", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "CA", "canonical_hash": "bbb", "raw_json": "{}"},
        ]
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["inserted"] == 2
        assert result["updated"] == 0

    def test_skip_unchanged_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
        ]
        upsert_records_to_duckdb(db, records, "external_orders",
                                  ["platform", "external_id", "credential_ref"])

        # Re-upsert same data — should skip (hash unchanged)
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["inserted"] == 0
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_update_changed_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
        ]
        upsert_records_to_duckdb(db, records, "external_orders",
                                  ["platform", "external_id", "credential_ref"])

        # Change status + hash
        records[0]["order_status"] = "closed"
        records[0]["canonical_hash"] = "bbb"
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["updated"] == 1
        row = db.execute("SELECT order_status FROM external_orders WHERE external_id='1'").fetchone()
        assert row[0] == "closed"

    def test_batch_dedupe_keeps_latest(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "canonical_hash": "aaa", "raw_json": "{}"},
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "closed", "canonical_hash": "bbb", "raw_json": "{}"},
        ]
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        row = db.execute("SELECT order_status FROM external_orders WHERE external_id='1'").fetchone()
        assert row[0] == "closed"  # last one wins

    def test_cross_platform_records(self, db):
        from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
        records = [
            {"platform": "shopify", "external_id": "1", "credential_ref": "primary",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "aaa", "raw_json": "{}"},
            {"platform": "amazon", "external_id": "1", "credential_ref": "us_store",
             "order_status": "open", "ship_to_state": "TX", "canonical_hash": "bbb", "raw_json": "{}"},
        ]
        result = upsert_records_to_duckdb(db, records, "external_orders",
                                           ["platform", "external_id", "credential_ref"])
        assert result["inserted"] == 2
        count = db.execute("SELECT COUNT(*) FROM external_orders").fetchone()[0]
        assert count == 2
