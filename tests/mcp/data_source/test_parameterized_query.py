"""Tests for parameterized query execution in the data source MCP."""

import duckdb
import pytest


@pytest.fixture
def db_with_data():
    """Create an in-memory DuckDB with test data."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE imported_data (
            _source_row_num INTEGER,
            state VARCHAR,
            company VARCHAR,
            weight DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO imported_data VALUES
        (1, 'CA', 'Acme Corp', 5.0),
        (2, 'NY', 'Beta Inc', 3.0),
        (3, 'CA', NULL, 7.0),
        (4, 'TX', 'Gamma LLC', 2.0)
    """)
    yield conn
    conn.close()


class TestParameterizedExecution:
    """Tests for parameterized SQL execution via DuckDB."""

    def test_parameterized_count(self, db_with_data):
        """Parameterized count query returns correct count."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "state" = $1',
            ["CA"],
        ).fetchone()
        assert result[0] == 2

    def test_parameterized_in_query(self, db_with_data):
        """Parameterized IN query returns correct rows."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "state" IN ($1, $2)',
            ["CA", "NY"],
        ).fetchone()
        assert result[0] == 3

    def test_parameterized_prevents_injection(self, db_with_data):
        """SQL injection attempt is treated as literal string value."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "state" = $1',
            ["CA'; DROP TABLE imported_data; --"],
        ).fetchone()
        assert result[0] == 0
        # Table still exists
        count = db_with_data.execute(
            "SELECT COUNT(*) FROM imported_data"
        ).fetchone()
        assert count[0] == 4

    def test_parameterized_null_handling(self, db_with_data):
        """IS NULL works without parameters."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "company" IS NULL',
        ).fetchone()
        assert result[0] == 1

    def test_parameterized_ilike(self, db_with_data):
        """ILIKE with parameterized pattern works."""
        result = db_with_data.execute(
            r"""SELECT COUNT(*) FROM imported_data WHERE "company" ILIKE $1 ESCAPE '\'""",
            ["%Corp%"],
        ).fetchone()
        assert result[0] == 1

    def test_empty_params_list_works(self, db_with_data):
        """Empty params list works identically to no-params execution."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "company" IS NULL',
            [],
        ).fetchone()
        assert result[0] == 1

    def test_between_parameterized(self, db_with_data):
        """BETWEEN with parameterized bounds works."""
        result = db_with_data.execute(
            'SELECT COUNT(*) FROM imported_data WHERE "weight" BETWEEN $1 AND $2',
            [3.0, 6.0],
        ).fetchone()
        assert result[0] == 2  # weight 5.0 and 3.0
