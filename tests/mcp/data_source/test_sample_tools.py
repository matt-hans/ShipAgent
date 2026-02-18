"""Tests for the get_column_samples MCP tool."""

import duckdb
import pytest

from src.mcp.data_source.tools.sample_tools import get_column_samples_impl


@pytest.fixture
def db_with_data():
    """Create an in-memory DuckDB with test data."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE imported_data (
            _source_row_num INTEGER,
            state VARCHAR,
            company VARCHAR,
            weight DOUBLE,
            notes VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO imported_data VALUES
        (1, 'CA', 'Acme Corp', 5.0, 'urgent'),
        (2, 'NY', 'Beta Inc', 3.0, NULL),
        (3, 'CA', NULL, 7.0, 'fragile'),
        (4, 'TX', 'Gamma LLC', 2.0, 'urgent'),
        (5, 'NY', 'Delta Co', 3.0, NULL),
        (6, 'FL', 'Epsilon', 1.5, 'standard'),
        (7, 'CA', 'Zeta Ltd', 9.0, 'fragile'),
        (8, 'TX', NULL, 4.0, NULL)
    """)
    yield conn
    conn.close()


class TestColumnSamples:
    """Verify get_column_samples returns correct sample values."""

    def test_returns_samples_for_each_column(self, db_with_data):
        """Returns sample values for all data columns (excluding _source_row_num)."""
        result = get_column_samples_impl(db_with_data)
        assert "state" in result
        assert "company" in result
        assert "weight" in result
        assert "_source_row_num" not in result

    def test_limits_to_max_samples(self, db_with_data):
        """Limits distinct values to max_samples (default 5)."""
        result = get_column_samples_impl(db_with_data, max_samples=3)
        # state has 4 distinct non-null values (CA, NY, TX, FL)
        assert len(result["state"]) <= 3

    def test_excludes_null_values(self, db_with_data):
        """NULL values are excluded from samples."""
        result = get_column_samples_impl(db_with_data)
        # company has NULLs in rows 3, 8
        assert None not in result["company"]
        # notes has NULLs in rows 2, 5, 8
        assert None not in result["notes"]

    def test_string_column_samples(self, db_with_data):
        """String columns return string sample values."""
        result = get_column_samples_impl(db_with_data)
        assert all(isinstance(v, str) for v in result["state"])

    def test_numeric_column_samples(self, db_with_data):
        """Numeric columns return numeric sample values."""
        result = get_column_samples_impl(db_with_data)
        assert all(isinstance(v, (int, float)) for v in result["weight"])

    def test_default_max_samples_is_five(self, db_with_data):
        """Default max_samples is 5."""
        result = get_column_samples_impl(db_with_data)
        # state has 4 distinct non-null values, so all should be returned
        assert len(result["state"]) == 4
        # weight has 6 distinct values (5.0, 3.0, 7.0, 2.0, 1.5, 9.0, 4.0)
        assert len(result["weight"]) <= 5

    def test_empty_table(self):
        """Returns empty lists for an empty table."""
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE imported_data (
                _source_row_num INTEGER,
                state VARCHAR,
                weight DOUBLE
            )
        """)
        result = get_column_samples_impl(conn)
        assert result["state"] == []
        assert result["weight"] == []
        conn.close()
