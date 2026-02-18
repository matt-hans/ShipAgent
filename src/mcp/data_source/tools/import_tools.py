"""Import tools for Data Source MCP.

Provides MCP tools for importing data from various sources (CSV, Excel, databases).
Each tool uses the appropriate adapter to load data into DuckDB and returns
the discovered schema with any warnings.

Per CONTEXT.md:
- One source at a time (import replaces previous)
- User can import a CSV and see discovered schema
- Ambiguous dates generate warnings

Security:
- Connection strings are NEVER logged - they contain credentials
- Database connections are not stored after import
"""

from fastmcp import Context

from src.mcp.data_source.adapters.csv_adapter import CSVAdapter
from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter
from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter


async def import_csv(
    file_path: str,
    ctx: Context,
    delimiter: str = ",",
    header: bool = True,
) -> dict:
    """Import CSV file and discover schema.

    Imports a CSV file into DuckDB using auto-detection for types.
    Returns the discovered schema along with any warnings about
    ambiguous dates or mixed-type columns.

    Args:
        file_path: Absolute path to the CSV file
        delimiter: Column delimiter (default: comma)
        header: Whether first row contains headers (default: True)

    Returns:
        Dictionary with:
        - row_count: Number of rows imported
        - columns: List of column metadata (name, type, nullable, warnings)
        - warnings: Import-level warnings
        - source_type: 'csv'

    Example:
        >>> result = await import_csv("/path/to/orders.csv", ctx)
        >>> print(result["row_count"])
        150
        >>> print(result["columns"][0])
        {"name": "order_id", "type": "INTEGER", "nullable": false, "warnings": []}
    """
    # Access DuckDB connection from lifespan context
    # CRITICAL: Use ctx.request_context.lifespan_context per FastMCP v2 pattern
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Importing CSV from {file_path}")

    adapter = CSVAdapter()
    result = adapter.import_data(
        conn=db,
        file_path=file_path,
        delimiter=delimiter,
        header=header,
    )

    # Update current source tracking for session state
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "csv",
        "path": file_path,
        "row_count": result.row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": ["_source_row_num"],
    }

    await ctx.info(
        f"Imported {result.row_count} rows with {len(result.columns)} columns"
    )

    return result.model_dump()


async def list_sheets(file_path: str, ctx: Context) -> dict:
    """List all sheets in an Excel file.

    Inspects an Excel file and returns the names of all worksheets.
    Use this before import_excel to discover available sheets.

    Args:
        file_path: Absolute path to the Excel file (.xlsx)

    Returns:
        Dictionary with:
        - sheets: List of sheet names in workbook order
        - count: Number of sheets

    Example:
        >>> result = await list_sheets("/path/to/workbook.xlsx", ctx)
        >>> print(result["sheets"])
        ["January Orders", "February Orders", "Summary"]
    """
    await ctx.info(f"Listing sheets in {file_path}")

    adapter = ExcelAdapter()
    sheets = adapter.list_sheets(file_path)

    await ctx.info(f"Found {len(sheets)} sheets")

    return {"sheets": sheets, "count": len(sheets)}


async def import_excel(
    file_path: str,
    ctx: Context,
    sheet: str | None = None,
    header: bool = True,
) -> dict:
    """Import Excel sheet and discover schema.

    Imports an Excel worksheet into DuckDB using openpyxl.
    Returns the discovered schema along with any warnings about
    ambiguous dates or mixed-type columns.

    Args:
        file_path: Absolute path to the Excel file (.xlsx)
        sheet: Name of sheet to import (default: first sheet)
        header: Whether first row contains headers (default: True)

    Returns:
        Dictionary with:
        - row_count: Number of rows imported
        - columns: List of column metadata (name, type, nullable, warnings)
        - warnings: Import-level warnings
        - source_type: 'excel'

    Example:
        >>> result = await import_excel("/path/to/orders.xlsx", ctx, sheet="January")
        >>> print(result["row_count"])
        250
    """
    # Access DuckDB connection from lifespan context
    db = ctx.request_context.lifespan_context["db"]

    sheet_info = f" sheet={sheet}" if sheet else ""
    await ctx.info(f"Importing Excel from {file_path}{sheet_info}")

    adapter = ExcelAdapter()
    result = adapter.import_data(
        conn=db,
        file_path=file_path,
        sheet=sheet,
        header=header,
    )

    # Update current source tracking for session state
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "excel",
        "path": file_path,
        "sheet": sheet or "(first sheet)",
        "row_count": result.row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": ["_source_row_num"],
    }

    await ctx.info(
        f"Imported {result.row_count} rows with {len(result.columns)} columns"
    )

    return result.model_dump()


async def list_tables(
    connection_string: str,
    ctx: Context,
    schema: str = "public",
) -> dict:
    """List tables in a remote database.

    Args:
        connection_string: Database connection URL
            - PostgreSQL: postgresql://user:pass@host:5432/dbname
            - MySQL: mysql://user:pass@host:3306/dbname
        schema: Schema to list tables from (default: public)

    Returns:
        Dictionary with list of tables and their row counts.
        Tables > 10,000 rows are flagged as requiring a WHERE clause.

    Security: Connection string is used only during this call and NOT stored.

    Example:
        >>> result = await list_tables("postgresql://user:pass@localhost/orders", ctx)
        >>> print(result["tables"])
        [{"name": "orders", "row_count": 50000, "requires_filter": True}, ...]
    """
    db = ctx.request_context.lifespan_context["db"]

    # SECURITY: Do not log connection string - it contains credentials!
    await ctx.info("Listing tables from database")

    adapter = DatabaseAdapter()
    tables = adapter.list_tables(
        conn=db, connection_string=connection_string, schema=schema
    )

    await ctx.info(f"Found {len(tables)} tables")

    return {"tables": tables, "count": len(tables), "schema": schema}


async def import_database(
    connection_string: str,
    query: str,
    ctx: Context,
    schema: str = "public",
    row_key_columns: list[str] | None = None,
) -> dict:
    """Import data from a database using a SQL query.

    Creates a snapshot of the query results - the database is NOT kept connected.

    Args:
        connection_string: Database connection URL
            - PostgreSQL: postgresql://user:pass@host:5432/dbname
            - MySQL: mysql://user:pass@host:3306/dbname
        query: SQL SELECT query to execute
        schema: Schema name for table references (default: public)

    Returns:
        Dictionary with schema, row_count, and any warnings.

    Security:
        - Connection string is used only during import and NOT stored
        - Query is executed read-only
        - Tables > 10,000 rows require a WHERE clause

    Example:
        >>> result = await import_database(
        ...     "postgresql://user:pass@localhost/shipping",
        ...     "SELECT * FROM orders WHERE created_at > '2026-01-01'",
        ...     ctx
        ... )
        >>> print(result["row_count"])
        1500
    """
    db = ctx.request_context.lifespan_context["db"]

    # SECURITY: Do not log connection string - it contains credentials!
    await ctx.info("Importing from database")

    adapter = DatabaseAdapter()
    result = adapter.import_data(
        conn=db,
        connection_string=connection_string,
        query=query,
        schema=schema,
        row_key_columns=row_key_columns,
    )

    # Update current source tracking (without connection string!)
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "database",
        "query": query,
        "row_count": result.row_count,
        "deterministic_ready": result.deterministic_ready,
        "row_key_strategy": result.row_key_strategy,
        "row_key_columns": result.row_key_columns,
    }

    await ctx.info(
        f"Imported {result.row_count} rows with {len(result.columns)} columns"
    )

    return result.model_dump()
