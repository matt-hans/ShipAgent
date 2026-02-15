"""Integration tests for Data Source MCP.

Tests the complete workflow through adapters (not MCP protocol).
MCP protocol testing requires running the server.
"""

import asyncio
import tempfile

import duckdb
import pytest
from openpyxl import Workbook

from src.mcp.data_source import CSVAdapter, ExcelAdapter
from src.mcp.data_source.utils import compute_row_checksum


@pytest.fixture
def duckdb_conn():
    """Create in-memory DuckDB connection."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


class TestCSVWorkflow:
    """Test complete CSV import workflow."""

    @pytest.fixture
    def csv_file(self):
        """Create test CSV file."""
        content = """order_id,customer_name,address,city,state,zip,weight
1001,Alice Johnson,123 Main St,Los Angeles,CA,90001,5.5
1002,Bob Smith,456 Oak Ave,New York,NY,10001,3.2
1003,Carol White,789 Pine Rd,Houston,TX,77001,7.8
1004,David Brown,321 Elm St,Miami,FL,33101,2.1"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write(content)
            return f.name

    def test_import_and_query(self, csv_file, duckdb_conn):
        """Test import CSV then query rows."""
        adapter = CSVAdapter()

        # Import
        result = adapter.import_data(duckdb_conn, csv_file)
        assert result.row_count == 4
        assert len(result.columns) == 7

        # Query specific state
        ca_rows = duckdb_conn.execute(
            """
            SELECT * FROM imported_data WHERE state = 'CA'
        """
        ).fetchall()
        assert len(ca_rows) == 1
        assert ca_rows[0][1] == "Alice Johnson"

    def test_checksum_consistency(self, csv_file, duckdb_conn):
        """Test that checksums are consistent across imports."""
        adapter = CSVAdapter()
        adapter.import_data(duckdb_conn, csv_file)

        # Get first row and compute checksum
        row1 = duckdb_conn.execute(
            "SELECT * FROM imported_data LIMIT 1"
        ).fetchone()
        columns = [desc[0] for desc in duckdb_conn.description]
        row_dict = dict(zip(columns, row1))

        checksum1 = compute_row_checksum(row_dict)

        # Re-import and verify checksum is same
        adapter.import_data(duckdb_conn, csv_file)
        row1_again = duckdb_conn.execute(
            "SELECT * FROM imported_data LIMIT 1"
        ).fetchone()
        row_dict_again = dict(zip(columns, row1_again))

        checksum2 = compute_row_checksum(row_dict_again)

        assert checksum1 == checksum2

    def test_filtered_query(self, csv_file, duckdb_conn):
        """Test filtering data after import."""
        adapter = CSVAdapter()
        adapter.import_data(duckdb_conn, csv_file)

        # Query with weight filter
        heavy_rows = duckdb_conn.execute(
            """
            SELECT customer_name, weight FROM imported_data
            WHERE weight > 5.0
            ORDER BY weight DESC
        """
        ).fetchall()

        assert len(heavy_rows) == 2
        assert heavy_rows[0][0] == "Carol White"  # 7.8 lbs
        assert heavy_rows[1][0] == "Alice Johnson"  # 5.5 lbs


class TestExcelWorkflow:
    """Test complete Excel import workflow."""

    @pytest.fixture
    def excel_file(self):
        """Create test Excel file with multiple sheets."""
        wb = Workbook()

        ws1 = wb.active
        ws1.title = "January"
        ws1.append(["order_id", "customer", "amount"])
        ws1.append([1001, "Alice", 150.50])
        ws1.append([1002, "Bob", 200.00])

        ws2 = wb.create_sheet("February")
        ws2.append(["order_id", "customer", "amount"])
        ws2.append([2001, "Carol", 175.25])

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb.save(f.name)
            return f.name

    def test_list_and_import_sheets(self, excel_file, duckdb_conn):
        """Test listing sheets and importing specific one."""
        adapter = ExcelAdapter()

        # List sheets
        sheets = adapter.list_sheets(excel_file)
        assert "January" in sheets
        assert "February" in sheets

        # Import specific sheet
        result = adapter.import_data(duckdb_conn, excel_file, sheet="February")
        assert result.row_count == 1  # Only one data row in February

    def test_import_default_sheet(self, excel_file, duckdb_conn):
        """Test importing the first sheet by default."""
        adapter = ExcelAdapter()

        # Import without specifying sheet (should use first)
        result = adapter.import_data(duckdb_conn, excel_file)
        assert result.row_count == 2  # Two data rows in January


class TestAllToolsRegistered:
    """Verify all expected tools are registered.

    The EDI tool (import_edi) is optional — it requires pydifact which
    may not be installed. Core tool count is 18 (including 2 commodity tools);
    19 with EDI support.
    """

    def test_tool_count(self):
        """Verify core tools are registered (EDI tool is optional)."""
        from src.mcp.data_source import mcp
        from src.mcp.data_source.server import _edi_available

        async def get_tool_count():
            tools = await mcp.get_tools()
            return len(tools)

        count = asyncio.run(get_tool_count())
        expected_count = 19 if _edi_available else 18
        assert count == expected_count, f"Expected {expected_count} tools, got {count}"

    def test_tool_names(self):
        """Verify all expected tool names are present (EDI optional)."""
        from src.mcp.data_source import mcp
        from src.mcp.data_source.server import _edi_available

        async def get_tool_names():
            tools = await mcp.get_tools()
            return list(tools)

        tool_names = asyncio.run(get_tool_names())

        expected = [
            "import_csv",
            "import_excel",
            "list_sheets",
            "import_database",
            "list_tables",
            "get_schema",
            "override_column_type",
            "get_row",
            "get_rows_by_filter",
            "query_data",
            "compute_checksums",
            "verify_checksum",
            "write_back",
            "get_source_info",
            "import_records",
            "clear_source",
            "import_commodities",
            "get_commodities_bulk",
        ]

        if _edi_available:
            expected.append("import_edi")

        for name in expected:
            assert name in tool_names, f"Tool '{name}' not found"


class TestRequirementsCoverage:
    """Verify Phase 2 requirements are covered."""

    def test_data_01_csv_import(self):
        """DATA-01: CSV with schema discovery."""
        from src.mcp.data_source import mcp

        async def check():
            tools = await mcp.get_tools()
            return list(tools)

        tool_names = asyncio.run(check())
        assert "import_csv" in tool_names

    def test_data_02_excel_import(self):
        """DATA-02: Excel with sheet selection."""
        from src.mcp.data_source import mcp

        async def check():
            tools = await mcp.get_tools()
            return list(tools)

        tool_names = asyncio.run(check())
        assert "import_excel" in tool_names
        assert "list_sheets" in tool_names

    def test_data_03_database_import(self):
        """DATA-03: Database via connection string."""
        from src.mcp.data_source import mcp

        async def check():
            tools = await mcp.get_tools()
            return list(tools)

        tool_names = asyncio.run(check())
        assert "import_database" in tool_names
        assert "list_tables" in tool_names

    def test_data_05_checksums(self):
        """DATA-05: SHA-256 row checksums."""
        from src.mcp.data_source import mcp

        async def check():
            tools = await mcp.get_tools()
            return list(tools)

        tool_names = asyncio.run(check())
        assert "compute_checksums" in tool_names
        assert "verify_checksum" in tool_names

    def test_orch_02_mcp_server(self):
        """ORCH-02: FastMCP server with stdio transport."""
        from src.mcp.data_source import mcp

        assert mcp is not None
        # Server can run via: python -m src.mcp.data_source.server


class TestPackageExports:
    """Verify package exports are complete."""

    def test_all_exports_available(self):
        """Test that all required exports are accessible."""
        from src.mcp.data_source import (
            BaseSourceAdapter,
            ChecksumResult,
            CSVAdapter,
            DatabaseAdapter,
            ExcelAdapter,
            ImportResult,
            QueryResult,
            RowData,
            SchemaColumn,
            mcp,
        )

        assert mcp is not None
        assert CSVAdapter is not None
        assert ExcelAdapter is not None
        assert DatabaseAdapter is not None
        assert BaseSourceAdapter is not None
        assert SchemaColumn is not None
        assert ImportResult is not None
        assert RowData is not None
        assert QueryResult is not None
        assert ChecksumResult is not None


class TestEndToEndWorkflow:
    """Test complete end-to-end workflows."""

    @pytest.fixture
    def shipping_csv(self):
        """Create a realistic shipping CSV file."""
        content = """order_id,recipient_name,street_address,city,state,zip_code,weight_lbs,ship_date
ORD-001,John Doe,123 Main Street,Los Angeles,CA,90001,2.5,2024-01-15
ORD-002,Jane Smith,456 Oak Avenue,San Francisco,CA,94102,5.0,2024-01-15
ORD-003,Bob Johnson,789 Pine Road,Seattle,WA,98101,3.2,2024-01-16
ORD-004,Alice Brown,321 Elm Drive,Portland,OR,97201,8.0,2024-01-16
ORD-005,Charlie Wilson,654 Maple Lane,Denver,CO,80201,1.5,2024-01-17"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write(content)
            return f.name

    def test_import_query_checksum_workflow(self, shipping_csv, duckdb_conn):
        """Test the full workflow: import -> query -> checksum."""
        adapter = CSVAdapter()

        # Step 1: Import
        result = adapter.import_data(duckdb_conn, shipping_csv)
        assert result.row_count == 5
        assert result.source_type == "csv"

        # Verify schema discovered correctly
        column_names = [col.name for col in result.columns]
        assert "order_id" in column_names
        assert "weight_lbs" in column_names

        # Step 2: Query California orders
        ca_orders = duckdb_conn.execute(
            """
            SELECT order_id, recipient_name, weight_lbs
            FROM imported_data
            WHERE state = 'CA'
            ORDER BY order_id
        """
        ).fetchall()

        assert len(ca_orders) == 2
        assert ca_orders[0][0] == "ORD-001"
        assert ca_orders[1][0] == "ORD-002"

        # Step 3: Compute checksums for integrity
        all_rows = duckdb_conn.execute(
            "SELECT * FROM imported_data"
        ).fetchall()
        columns = [desc[0] for desc in duckdb_conn.description]

        checksums = []
        for row in all_rows:
            row_dict = dict(zip(columns, row))
            checksum = compute_row_checksum(row_dict)
            checksums.append(checksum)

        # Verify all checksums are unique (different data)
        assert len(checksums) == len(set(checksums))

        # Verify checksum is deterministic
        first_row = duckdb_conn.execute(
            "SELECT * FROM imported_data WHERE order_id = 'ORD-001'"
        ).fetchone()
        first_row_dict = dict(zip(columns, first_row))
        checksum_again = compute_row_checksum(first_row_dict)
        assert checksums[0] == checksum_again

    def test_heavy_shipments_filter(self, shipping_csv, duckdb_conn):
        """Test filtering for heavy shipments."""
        adapter = CSVAdapter()
        adapter.import_data(duckdb_conn, shipping_csv)

        # Find shipments over 5 lbs
        heavy = duckdb_conn.execute(
            """
            SELECT order_id, recipient_name, weight_lbs
            FROM imported_data
            WHERE weight_lbs >= 5.0
            ORDER BY weight_lbs DESC
        """
        ).fetchall()

        assert len(heavy) == 2
        assert heavy[0][0] == "ORD-004"  # 8.0 lbs
        assert heavy[1][0] == "ORD-002"  # 5.0 lbs
