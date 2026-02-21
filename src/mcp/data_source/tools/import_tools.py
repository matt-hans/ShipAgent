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
- File paths are validated against allowed directories to prevent path traversal
"""

from fastmcp import Context

import os
from itertools import islice
from pathlib import Path

from src.mcp.data_source.adapters.csv_adapter import CSVAdapter
from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter
from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter

# --- Path security -----------------------------------------------------------

# Project root: four levels up from this file (tools/ → data_source/ → mcp/ → src/ → root)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Allowed directories for file operations.
# Extend via SHIPAGENT_ALLOWED_PATHS env var (colon-separated paths).
_ALLOWED_ROOTS: list[Path] = [
    _PROJECT_ROOT / "uploads",
    _PROJECT_ROOT,
]
_extra = os.environ.get("SHIPAGENT_ALLOWED_PATHS", "").strip()
if _extra:
    _ALLOWED_ROOTS.extend(Path(p).resolve() for p in _extra.split(":") if p.strip())

# Sensitive file patterns that must never be read via sniff_file.
_BLOCKED_NAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.staging",
    "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
})

_BLOCKED_DIRS = frozenset({".git", ".ssh", "__pycache__"})


def _validate_file_path(file_path: str) -> Path:
    """Validate a file path is safe for MCP tool access.

    Resolves symlinks and ensures the path falls within allowed
    project directories.  Blocks access to sensitive files.

    Allowed roots default to the project root and uploads dir. Extend
    via the ``SHIPAGENT_ALLOWED_PATHS`` environment variable
    (colon-separated absolute paths).

    Args:
        file_path: Absolute or relative path to validate.

    Returns:
        Resolved Path object.

    Raises:
        PermissionError: If path falls outside allowed directories or
            targets a sensitive file.
    """
    resolved = Path(file_path).resolve()

    # Must fall within at least one allowed root
    if not any(
        resolved == root or resolved.is_relative_to(root)
        for root in _ALLOWED_ROOTS
    ):
        raise PermissionError(
            f"Access denied: path '{file_path}' is outside allowed directories. "
            f"Files must be within the project directory or uploads folder."
        )

    # Block sensitive filenames
    if resolved.name in _BLOCKED_NAMES:
        raise PermissionError(
            f"Access denied: '{resolved.name}' is a sensitive file."
        )

    # Block sensitive directory components anywhere in the path
    if _BLOCKED_DIRS.intersection(resolved.parts):
        raise PermissionError(
            f"Access denied: path is within a restricted directory."
        )

    return resolved


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


# --- Format extension map for import_file router ---
EXTENSION_MAP: dict[str, str] = {
    ".csv": "delimited",
    ".tsv": "delimited",
    ".ssv": "delimited",
    ".dat": "delimited",
    ".txt": "delimited",
    ".json": "json",
    ".xml": "xml",
    ".xlsx": "excel",
    ".xls": "excel",
    ".edi": "edi",
    ".x12": "edi",
    ".edifact": "edi",
    ".fwf": "fixed_width",
}


async def import_file(
    file_path: str,
    ctx: Context,
    format_hint: str | None = None,
    delimiter: str | None = None,
    quotechar: str | None = None,
    sheet: str | None = None,
    record_path: str | None = None,
    header: bool = True,
) -> dict:
    """Import any supported file format into DuckDB.

    Routes to the appropriate adapter based on file extension.
    Use format_hint to override auto-detection.

    Args:
        file_path: Absolute path to the file to import.
        format_hint: Override extension-based detection ('delimited', 'json', 'xml', 'excel').
        delimiter: Column delimiter for delimited files (auto-detected if None).
        quotechar: Quote character for delimited files (auto-detected if None).
        sheet: Sheet name for Excel files (default: first sheet).
        record_path: Slash-separated path to records for JSON/XML files.
        header: Whether first row contains headers (default: True).

    Returns:
        Dictionary with row_count, columns, warnings, and source_type.

    Raises:
        ValueError: If file type is unsupported or format requires special handling.
        FileNotFoundError: If file does not exist.
    """
    from src.mcp.data_source.adapters.csv_adapter import DelimitedAdapter
    from src.mcp.data_source.adapters.json_adapter import JSONAdapter
    from src.mcp.data_source.adapters.xml_adapter import XMLAdapter

    _validate_file_path(file_path)
    db = ctx.request_context.lifespan_context["db"]

    ext = os.path.splitext(file_path)[1].lower()
    source_type = format_hint or EXTENSION_MAP.get(ext)

    if source_type is None:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(sorted(EXTENSION_MAP.keys()))}"
        )

    await ctx.info(f"Importing {file_path} as {source_type}")

    detected_delim: str | None = None

    if source_type == "delimited":
        adapter_delim = DelimitedAdapter()
        delim_kwargs: dict = {"file_path": file_path, "header": header}
        if delimiter:
            delim_kwargs["delimiter"] = delimiter
        if quotechar:
            delim_kwargs["quotechar"] = quotechar
        result = adapter_delim.import_data(conn=db, **delim_kwargs)
        detected_delim = adapter_delim.detected_delimiter

    elif source_type == "excel":
        adapter_excel = ExcelAdapter()
        result = adapter_excel.import_data(
            conn=db, file_path=file_path, sheet=sheet, header=header
        )

    elif source_type == "json":
        adapter_json = JSONAdapter()
        result = adapter_json.import_data(
            conn=db, file_path=file_path, record_path=record_path
        )

    elif source_type == "xml":
        adapter_xml = XMLAdapter()
        result = adapter_xml.import_data(
            conn=db, file_path=file_path, record_path=record_path
        )

    elif source_type == "fixed_width":
        from src.mcp.data_source.adapters.fixed_width_adapter import (
            FixedWidthAdapter,
            auto_detect_col_specs,
        )

        fwf_path = _validate_file_path(file_path)
        if not fwf_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(fwf_path, encoding="utf-8") as _fwf:
            _lines = _fwf.readlines()

        detected = auto_detect_col_specs(_lines)
        if detected is None:
            raise ValueError(
                "Fixed-width files require explicit column specs. "
                "Use sniff_file to inspect the file, then call import_fixed_width."
            )

        _col_specs, _names = detected
        await ctx.info(
            f"Auto-detected {len(_col_specs)} columns in fixed-width file"
        )
        fwf_adapter = FixedWidthAdapter()
        result = fwf_adapter.import_data(
            conn=db,
            file_path=file_path,
            col_specs=_col_specs,
            names=_names,
            header=True,
        )

    elif source_type == "edi":
        try:
            from src.mcp.data_source.tools.edi_tools import import_edi

            return await import_edi(file_path, ctx)
        except ImportError:
            raise ValueError("EDI support requires pydifact: pip install pydifact")

    else:
        raise ValueError(f"Unknown source type: {source_type}")

    ctx.request_context.lifespan_context["current_source"] = {
        "type": source_type,
        "path": file_path,
        "sheet": sheet,
        "row_count": result.row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": ["_source_row_num"],
        "detected_delimiter": detected_delim,
    }

    await ctx.info(
        f"Imported {result.row_count} rows with {len(result.columns)} columns"
    )
    return result.model_dump()


async def sniff_file(
    file_path: str,
    ctx: Context,
    num_lines: int = 10,
    offset: int = 0,
) -> str:
    """Read raw text lines from a file for agent inspection.

    Returns the first N lines as raw text so the agent can reason
    about format (delimiters, fixed-width columns, etc.).
    Uses itertools.islice for lazy reading — safe for large files.

    Args:
        file_path: Absolute path to the file.
        num_lines: Number of lines to return (default: 10).
        offset: Number of lines to skip before reading (default: 0).

    Returns:
        Raw text of the selected lines.

    Raises:
        FileNotFoundError: If file does not exist.
    """
    path = _validate_file_path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, encoding="utf-8", errors="replace") as f:
        selected = list(islice(f, offset, offset + num_lines))

    await ctx.info(
        f"Sniffed {len(selected)} lines from {file_path} (offset={offset})"
    )
    return "".join(selected)


async def import_fixed_width(
    file_path: str,
    ctx: Context,
    col_specs: list[tuple[int, int]],
    names: list[str] | None = None,
    header: bool = False,
) -> dict:
    """Import a fixed-width format file using explicit column positions.

    The agent determines col_specs by inspecting the file via sniff_file,
    then calls this tool with the discovered positions.

    Args:
        file_path: Absolute path to the fixed-width file.
        col_specs: List of (start, end) byte positions for each column.
        names: Column names (auto-generated if not provided).
        header: If True, first line is treated as header.

    Returns:
        Dictionary with row_count, columns, warnings, and source_type.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If col_specs is empty.
    """
    from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter

    _validate_file_path(file_path)
    db = ctx.request_context.lifespan_context["db"]

    adapter = FixedWidthAdapter()
    result = adapter.import_data(
        conn=db,
        file_path=file_path,
        col_specs=col_specs,
        names=names,
        header=header,
    )

    ctx.request_context.lifespan_context["current_source"] = {
        "type": "fixed_width",
        "path": file_path,
        "row_count": result.row_count,
        "deterministic_ready": True,
        "row_key_strategy": "source_row_num",
        "row_key_columns": ["_source_row_num"],
    }

    await ctx.info(f"Imported {result.row_count} fixed-width rows")
    return result.model_dump()
