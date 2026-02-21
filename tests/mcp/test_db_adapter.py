"""Test database adapter functionality.

Tests for DatabaseAdapter class which handles PostgreSQL and MySQL imports.
Full database integration tests require actual database connections and are
deferred to CI/CD with docker-compose.

These tests focus on:
- Database type detection from connection strings
- Large table threshold validation
- Adapter instantiation and source_type property
- Error handling for unsupported databases
"""

import duckdb
import pytest

from src.mcp.data_source.adapters.db_adapter import (
    LARGE_TABLE_THRESHOLD,
    DatabaseAdapter,
)


@pytest.fixture
def adapter():
    """Create a fresh DatabaseAdapter instance."""
    return DatabaseAdapter()


@pytest.fixture
def duckdb_conn():
    """Create in-memory DuckDB connection for testing.

    Note: postgres/mysql extensions require actual databases to test fully.
    These are loaded on demand when list_tables or import_data is called.
    """
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


class TestDatabaseTypeDetection:
    """Test database type detection from connection strings."""

    def test_detect_postgresql_scheme(self, adapter):
        """PostgreSQL URLs with 'postgresql://' scheme are detected correctly."""
        result = adapter._detect_db_type("postgresql://user:pass@host:5432/dbname")
        assert result == "postgres"

    def test_detect_postgres_short_scheme(self, adapter):
        """PostgreSQL URLs with 'postgres://' scheme are detected correctly."""
        result = adapter._detect_db_type("postgres://user:pass@host:5432/dbname")
        assert result == "postgres"

    def test_detect_mysql_scheme(self, adapter):
        """MySQL URLs with 'mysql://' scheme are detected correctly."""
        result = adapter._detect_db_type("mysql://user:pass@host:3306/dbname")
        assert result == "mysql"

    def test_unsupported_sqlite_raises_error(self, adapter):
        """SQLite is not supported and should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            adapter._detect_db_type("sqlite:///path/to/db.sqlite")

        error_msg = str(exc_info.value)
        assert "Unsupported database type" in error_msg
        assert "sqlite" in error_msg
        assert "postgresql://" in error_msg  # Shows supported types

    def test_unsupported_mssql_raises_error(self, adapter):
        """MS SQL Server is not supported and should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            adapter._detect_db_type("mssql://user:pass@host/db")

        assert "Unsupported database type" in str(exc_info.value)

    def test_empty_scheme_raises_error(self, adapter):
        """Connection strings without valid scheme raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            adapter._detect_db_type("not-a-valid-url")

        assert "Unsupported database type" in str(exc_info.value)

    def test_case_insensitive_scheme(self, adapter):
        """Database type detection is case-insensitive."""
        assert adapter._detect_db_type("POSTGRESQL://user:pass@host/db") == "postgres"
        assert adapter._detect_db_type("PostgreSQL://user:pass@host/db") == "postgres"
        assert adapter._detect_db_type("MYSQL://user:pass@host/db") == "mysql"
        assert adapter._detect_db_type("MySQL://user:pass@host/db") == "mysql"


class TestLargeTableProtection:
    """Test large table threshold validation logic."""

    def test_threshold_value_is_10000(self):
        """LARGE_TABLE_THRESHOLD is 10,000 rows per CONTEXT.md."""
        assert LARGE_TABLE_THRESHOLD == 10000

    def test_threshold_is_integer(self):
        """Threshold should be an integer for comparison."""
        assert isinstance(LARGE_TABLE_THRESHOLD, int)


class TestAdapterProperties:
    """Test DatabaseAdapter instance properties."""

    def test_source_type_is_database(self, adapter):
        """source_type property returns 'database'."""
        assert adapter.source_type == "database"

    def test_adapter_instantiation(self, adapter):
        """Verify adapter can be created without arguments."""
        assert adapter is not None
        assert isinstance(adapter, DatabaseAdapter)


class TestGetMetadata:
    """Test get_metadata method behavior."""

    def test_get_metadata_no_data_returns_error(self, adapter, duckdb_conn):
        """get_metadata returns error dict when no data is imported."""
        result = adapter.get_metadata(duckdb_conn)
        assert "error" in result
        assert result["error"] == "No data imported"

    def test_get_metadata_with_table(self, adapter, duckdb_conn):
        """get_metadata returns correct info when imported_data table exists."""
        # Create a test table to simulate import
        duckdb_conn.execute(
            """
            CREATE TABLE imported_data AS
            SELECT 1 as id, 'test' as name
            UNION ALL
            SELECT 2, 'example'
        """
        )

        result = adapter.get_metadata(duckdb_conn)
        assert result["row_count"] == 2
        assert result["column_count"] == 2
        assert result["source_type"] == "database"


class TestBaseSourceAdapterCompliance:
    """Verify DatabaseAdapter implements BaseSourceAdapter correctly."""

    def test_inherits_from_base_adapter(self, adapter):
        """DatabaseAdapter inherits from BaseSourceAdapter."""
        from src.mcp.data_source.adapters.base import BaseSourceAdapter

        assert isinstance(adapter, BaseSourceAdapter)

    def test_has_import_data_method(self, adapter):
        """DatabaseAdapter has import_data method."""
        assert hasattr(adapter, "import_data")
        assert callable(adapter.import_data)

    def test_has_get_metadata_method(self, adapter):
        """DatabaseAdapter has get_metadata method."""
        assert hasattr(adapter, "get_metadata")
        assert callable(adapter.get_metadata)

    def test_has_list_tables_method(self, adapter):
        """DatabaseAdapter has list_tables method for database discovery."""
        assert hasattr(adapter, "list_tables")
        assert callable(adapter.list_tables)


class TestConnectionStringSecurity:
    """Verify connection string handling is secure."""

    def test_adapter_does_not_store_connection_string(self, adapter):
        """DatabaseAdapter does not have connection string as instance attribute."""
        # Adapter should not store credentials
        assert not hasattr(adapter, "connection_string")
        assert not hasattr(adapter, "_connection_string")
        assert not hasattr(adapter, "credentials")

    def test_get_metadata_does_not_include_credentials(self, adapter, duckdb_conn):
        """get_metadata output does not include connection credentials."""
        # Create test data
        duckdb_conn.execute("CREATE TABLE imported_data AS SELECT 1 as id")

        result = adapter.get_metadata(duckdb_conn)

        # Ensure no credential-related keys in output
        result_str = str(result).lower()
        assert "password" not in result_str
        assert "connection_string" not in result_str
        assert "credentials" not in result_str


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        text_sql = str(sql)
        self.statements.append(text_sql)
        if text_sql.startswith("ATTACH ") or text_sql.startswith("DETACH "):
            return _FakeResult([])
        if text_sql.startswith("DESCRIBE SELECT * FROM ("):
            return _FakeResult([("id", "INTEGER"), ("created_at", "VARCHAR")])
        if text_sql.startswith("DESCRIBE imported_data"):
            return _FakeResult(
                [
                    ("_source_row_num", "INTEGER", "YES"),
                    ("id", "INTEGER", "NO"),
                    ("created_at", "VARCHAR", "YES"),
                ]
            )
        if "SELECT COUNT(*) FROM remote_db." in text_sql:
            return _FakeResult([(100,)])
        if text_sql.startswith("SELECT COUNT(*) FROM imported_data"):
            return _FakeResult([(2,)])
        return _FakeResult([])


class TestDeterministicRowKeys:
    """Test deterministic row-key strategy resolution during import."""

    def test_import_data_uses_auto_pk_row_key_when_available(self, adapter):
        fake_conn = _FakeConn()
        adapter._get_key_candidates = lambda **kwargs: [("PRIMARY KEY", ["id"])]  # type: ignore[method-assign]

        result = adapter.import_data(
            conn=fake_conn,
            connection_string="postgresql://u:p@localhost/db",
            query="SELECT * FROM orders WHERE created_at > '2026-01-01'",
        )

        assert result.deterministic_ready is True
        assert result.row_key_strategy == "auto_pk"
        assert result.row_key_columns == ["id"]
        assert any('ORDER BY sub."id" ASC' in stmt for stmt in fake_conn.statements)

    def test_import_data_rejects_unknown_explicit_row_key_columns(self, adapter):
        fake_conn = _FakeConn()
        adapter._get_key_candidates = lambda **kwargs: []  # type: ignore[method-assign]

        with pytest.raises(ValueError, match="row_key_columns must exist"):
            adapter.import_data(
                conn=fake_conn,
                connection_string="postgresql://u:p@localhost/db",
                query="SELECT * FROM orders WHERE created_at > '2026-01-01'",
                row_key_columns=["missing_key"],
            )
