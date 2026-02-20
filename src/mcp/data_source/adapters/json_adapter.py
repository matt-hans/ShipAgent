"""JSON adapter for importing JSON files into DuckDB.

Supports two tiers:
- Tier 1: Flat JSON arrays loaded via Python flattening + DuckDB.
- Tier 2: Nested JSON flattened via Python, then loaded into DuckDB.

Per CONTEXT.md:
- Import all rows, flag invalid ones (no threshold)
- Silent skip for empty rows
- Best-effort parsing with string fallback
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult
from src.mcp.data_source.utils import flatten_record, load_flat_records_to_duckdb

# Guard against OOM — Python json.load() buffers entire file in memory.
# 50MB is generous for shipping manifests; truly large files should use
# streaming or database import instead.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class JSONAdapter(BaseSourceAdapter):
    """Adapter for importing JSON files into DuckDB.

    Handles flat arrays of objects, nested structures with auto-discovery
    of the repeating record array, and explicit record_path navigation.
    Lists within records are serialized as JSON strings to avoid row explosion.

    Example:
        >>> adapter = JSONAdapter()
        >>> result = adapter.import_data(conn, file_path="/path/to/orders.json")
        >>> print(result.row_count, result.columns)
    """

    @property
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            'json' — identifies this as a JSON file adapter.
        """
        return "json"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        record_path: str | None = None,
        header: bool = True,
    ) -> ImportResult:
        """Import JSON file into DuckDB.

        Args:
            conn: DuckDB connection.
            file_path: Path to the JSON file.
            record_path: Slash-separated path to repeating records
                (e.g., "response/data/orders"). Auto-detected if not provided.
            header: Unused (JSON has keys as headers). Kept for interface compat.

        Returns:
            ImportResult with schema and row count.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file exceeds MAX_FILE_SIZE_BYTES.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"JSON file exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB limit "
                f"({file_size // (1024 * 1024)}MB). Use database import for large files."
            )

        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        records = self._discover_records(data, record_path)

        # Check if records are flat (no nested dicts)
        needs_flattening = any(
            isinstance(v, (dict, list)) for record in records for v in record.values()
        )

        if needs_flattening:
            records = [flatten_record(r) for r in records]

        return load_flat_records_to_duckdb(conn, records, source_type="json")

    def _discover_records(
        self, data: Any, record_path: str | None = None
    ) -> list[dict]:
        """Find the list of records to import.

        Args:
            data: Parsed JSON data (list or dict).
            record_path: Explicit path to records (e.g., "orders/items").

        Returns:
            List of dicts representing individual records.
        """
        if record_path:
            for key in record_path.split("/"):
                data = data[key]
            return data if isinstance(data, list) else [data]

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            # Find first key whose value is a list of dicts
            for key, value in data.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value
            # No list found — treat entire dict as single record
            return [data]

        raise ValueError(f"Cannot discover records in JSON: unexpected type {type(data)}")

