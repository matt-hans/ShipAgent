# tests/mcp/data_source/test_schema_migration.py
"""Tests for external_orders schema migration."""
import pytest
import duckdb
from src.mcp.data_source.tools.schema_migration import ensure_external_orders_table


class TestExternalOrdersSchema:
    def test_creates_table_if_missing(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        # Table should exist
        result = conn.execute("SELECT * FROM external_orders LIMIT 0").description
        column_names = [col[0] for col in result]
        assert "platform" in column_names
        assert "external_id" in column_names
        assert "credential_ref" in column_names
        assert "canonical_hash" in column_names
        assert "raw_json" in column_names
        assert "attrs_json" in column_names
        conn.close()

    def test_idempotent_creation(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        ensure_external_orders_table(conn)  # Should not error
        count = conn.execute("SELECT COUNT(*) FROM external_orders").fetchone()[0]
        assert count == 0
        conn.close()

    def test_primary_key_exists(self):
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        # Insert duplicate PK should fail
        conn.execute("""
            INSERT INTO external_orders (platform, external_id, credential_ref, canonical_hash, ingested_at)
            VALUES ('shopify', '1', 'primary', 'aaa', CURRENT_TIMESTAMP)
        """)
        with pytest.raises(duckdb.ConstraintException):
            conn.execute("""
                INSERT INTO external_orders (platform, external_id, credential_ref, canonical_hash, ingested_at)
                VALUES ('shopify', '1', 'primary', 'bbb', CURRENT_TIMESTAMP)
            """)
        conn.close()

    def test_schema_introspection_includes_platform(self):
        """NL filter engine needs to see 'platform' in get_schema."""
        conn = duckdb.connect(":memory:")
        ensure_external_orders_table(conn)
        cols = conn.execute("DESCRIBE external_orders").fetchall()
        col_names = [c[0] for c in cols]
        assert "platform" in col_names
        assert "credential_ref" in col_names
        assert "total_weight_grams" in col_names
        # Verify weight is integer, not float
        weight_col = next(c for c in cols if c[0] == "total_weight_grams")
        assert "BIGINT" in weight_col[1].upper()
        conn.close()
