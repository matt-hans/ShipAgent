"""Utility functions for Data Source MCP.

Provides helper functions for:
- Row checksum computation (SHA-256 with deterministic JSON serialization)
- Date parsing with ambiguity detection (US vs EU format)
- Hierarchical data flattening (nested dicts → flat dicts for DuckDB)
- Flat record loading into DuckDB imported_data table

Per RESEARCH.md:
- Use hashlib + JSON with sorted keys for deterministic checksums
- Use dateutil.parser for date parsing with ambiguity detection
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

from dateutil.parser import ParserError, parse

# Excel serial date detection pattern (5-digit numbers)
EXCEL_SERIAL_PATTERN = re.compile(r"^\d{5}$")


def compute_row_checksum(row_data: dict[str, Any]) -> str:
    """Compute SHA-256 checksum for a row.

    Uses JSON serialization with sorted keys for deterministic output.
    This ensures the same data always produces the same checksum,
    regardless of dictionary key insertion order.

    Args:
        row_data: Dictionary of column name to value

    Returns:
        Hex-encoded SHA-256 checksum string (64 characters)

    Example:
        >>> compute_row_checksum({"a": 1, "b": 2})
        >>> compute_row_checksum({"b": 2, "a": 1})  # Same result
    """
    # Sort keys for consistent ordering
    # Use default=str to handle non-JSON-serializable types (dates, decimals, etc.)
    canonical = json.dumps(row_data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_date_with_warnings(value: str | None) -> dict[str, Any]:
    """Parse date string with ambiguity detection.

    Per CONTEXT.md decisions:
    - Auto-detect common formats (ISO, US, EU, Excel serial)
    - Default to US format (MM/DD/YYYY) when ambiguous
    - Flag ambiguous dates with warnings

    Args:
        value: Date string to parse (or None)

    Returns:
        Dictionary with:
        - value: Parsed date as ISO format string (YYYY-MM-DD), or original if unparseable
        - format_detected: Format identifier ('iso', 'us', 'eu', 'excel_serial', 'auto', None)
        - warnings: List of warning dictionaries with type, message, and interpretations

    Example:
        >>> parse_date_with_warnings("2026-01-24")
        {"value": "2026-01-24", "format_detected": "auto", "warnings": []}

        >>> parse_date_with_warnings("01/02/26")  # Ambiguous
        {"value": "2026-01-02",
         "format_detected": "auto",
         "warnings": [{"type": "AMBIGUOUS_DATE", ...}]}
    """
    if not value or not isinstance(value, str):
        return {"value": None, "format_detected": None, "warnings": []}

    value = value.strip()
    if not value:
        return {"value": None, "format_detected": None, "warnings": []}

    warnings: list[dict[str, str]] = []

    # Check for Excel serial date (5-digit number)
    if EXCEL_SERIAL_PATTERN.match(value):
        serial = int(value)
        # Excel epoch is Dec 30, 1899 (accounting for Excel's leap year bug)
        excel_epoch = datetime(1899, 12, 30)
        parsed = excel_epoch + timedelta(days=serial)
        return {
            "value": parsed.date().isoformat(),
            "format_detected": "excel_serial",
            "warnings": [],
        }

    try:
        # Try US format (default per CONTEXT.md)
        us_parsed = parse(value, dayfirst=False)

        # Check for ambiguity by also trying EU format
        try:
            eu_parsed = parse(value, dayfirst=True)
            if us_parsed.date() != eu_parsed.date():
                warnings.append(
                    {
                        "type": "AMBIGUOUS_DATE",
                        "message": (
                            f"Date '{value}' could be "
                            f"{us_parsed.strftime('%b %d, %Y')} (US) or "
                            f"{eu_parsed.strftime('%b %d, %Y')} (EU). "
                            "Using US format."
                        ),
                        "us_interpretation": us_parsed.date().isoformat(),
                        "eu_interpretation": eu_parsed.date().isoformat(),
                    }
                )
        except ParserError:
            # EU parsing failed - no ambiguity
            pass

        return {
            "value": us_parsed.date().isoformat(),
            "format_detected": "auto",
            "warnings": warnings,
        }
    except ParserError:
        # Could not parse - return original value as string
        return {
            "value": value,  # Keep original as string
            "format_detected": None,
            "warnings": [
                {
                    "type": "UNPARSEABLE_DATE",
                    "message": f"Could not parse '{value}' as date",
                }
            ],
        }


def _infer_duckdb_types(
    records: list[dict[str, Any]], keys: list[str]
) -> dict[str, str]:
    """Infer DuckDB column types from Python values.

    Samples the first non-None value per key across all records
    and maps Python types to DuckDB column types.

    Args:
        records: List of flat dictionaries.
        keys: Ordered list of column keys.

    Returns:
        Mapping of key → DuckDB type string.
    """
    _py_to_duckdb = {
        int: "BIGINT",
        float: "DOUBLE",
        bool: "BOOLEAN",
        str: "VARCHAR",
    }
    result: dict[str, str] = {}
    for key in keys:
        for record in records:
            value = record.get(key)
            if value is not None:
                result[key] = _py_to_duckdb.get(type(value), "VARCHAR")
                break
        else:
            result[key] = "VARCHAR"
    return result


def flatten_record(
    record: dict[str, Any],
    separator: str = "_",
    prefix: str = "",
    max_depth: int = 5,
    _current_depth: int = 0,
) -> dict[str, Any]:
    """Recursively flatten a nested dict into a single-level dict.

    Nested dict keys are joined with separator. Lists are serialized
    as JSON strings to preserve array data without row explosion.
    Recursion stops at max_depth to prevent stack overflow on deeply
    nested structures — remaining dicts are serialized as JSON strings.

    Args:
        record: Nested dictionary to flatten.
        separator: Key separator for nested paths (default: underscore).
        prefix: Internal prefix for recursion (callers should not set this).
        max_depth: Maximum nesting depth before serializing remainder as JSON.
        _current_depth: Internal recursion counter (callers should not set this).

    Returns:
        Flat dictionary with all leaf values.
    """
    flat: dict[str, Any] = {}
    for key, value in record.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, dict):
            if _current_depth >= max_depth:
                flat[full_key] = json.dumps(value)
            else:
                flat.update(
                    flatten_record(
                        value, separator, full_key, max_depth, _current_depth + 1
                    )
                )
        elif isinstance(value, list):
            flat[full_key] = json.dumps(value)
        else:
            flat[full_key] = value
    return flat


def load_flat_records_to_duckdb(
    conn: Any,
    records: list[dict[str, Any]],
    source_type: str = "unknown",
) -> "ImportResult":
    """Load a list of flat dicts into DuckDB imported_data table.

    Uses executemany for batch insertion (OLAP-friendly, not row-by-row).
    Preserves Python types (int, float, str) so DuckDB can infer column
    types instead of defaulting everything to VARCHAR.
    Adds _source_row_num (1-based). Returns ImportResult with schema.

    Args:
        conn: DuckDB connection.
        records: List of flat dictionaries (one per row).
        source_type: Source type string for ImportResult.

    Returns:
        ImportResult with row count, schema columns, and warnings.
    """
    from src.mcp.data_source.models import (
        SOURCE_ROW_NUM_COLUMN,
        ImportResult,
        SchemaColumn,
    )

    if not records:
        conn.execute(f"""
            CREATE OR REPLACE TABLE imported_data (
                {SOURCE_ROW_NUM_COLUMN} BIGINT
            )
        """)
        return ImportResult(
            row_count=0,
            columns=[],
            warnings=["No records to import"],
            source_type=source_type,
        )

    # Collect all unique keys (union across all records, preserving order)
    all_keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                all_keys.append(key)
                seen.add(key)

    # Infer DuckDB column types from first non-None Python value per key
    type_map = _infer_duckdb_types(records, all_keys)
    col_defs = ", ".join(
        f'"{key}" {type_map.get(key, "VARCHAR")}' for key in all_keys
    )
    conn.execute(f"""
        CREATE OR REPLACE TABLE imported_data (
            {SOURCE_ROW_NUM_COLUMN} BIGINT,
            {col_defs}
        )
    """)

    # Batch insert using executemany
    placeholders = ", ".join(["?"] * (len(all_keys) + 1))
    insert_sql = f"INSERT INTO imported_data VALUES ({placeholders})"

    batch = []
    for i, record in enumerate(records, 1):
        values = [i] + [record.get(key) for key in all_keys]
        batch.append(values)

    conn.executemany(insert_sql, batch)

    # Build schema (excluding _source_row_num)
    schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
    columns = [
        SchemaColumn(name=col[0], type=col[1], nullable=True, warnings=[])
        for col in schema_rows
        if col[0] != SOURCE_ROW_NUM_COLUMN
    ]

    row_count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    return ImportResult(
        row_count=row_count,
        columns=columns,
        warnings=[],
        source_type=source_type,
    )
