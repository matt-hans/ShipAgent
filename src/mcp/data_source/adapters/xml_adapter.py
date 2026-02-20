"""XML adapter for importing XML files into DuckDB.

Uses xmltodict to convert XML to dict, then flattens nested
structures and loads into DuckDB via shared utilities.

Per CONTEXT.md:
- Import all rows, flag invalid ones (no threshold)
- Silent skip for empty rows
- Best-effort parsing with string fallback
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import xmltodict

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult
from src.mcp.data_source.utils import flatten_record, load_flat_records_to_duckdb

# Guard against OOM — xmltodict.parse() buffers entire file in memory.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class XMLAdapter(BaseSourceAdapter):
    """Adapter for importing XML files into DuckDB.

    Converts XML to dict via xmltodict, auto-discovers the repeating
    record element (largest list of dicts), strips namespace prefixes,
    flattens nested structures, and loads into DuckDB.

    Example:
        >>> adapter = XMLAdapter()
        >>> result = adapter.import_data(conn, file_path="/path/to/orders.xml")
        >>> print(result.row_count, result.columns)
    """

    @property
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            'xml' — identifies this as an XML file adapter.
        """
        return "xml"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        record_path: str | None = None,
        header: bool = True,
    ) -> ImportResult:
        """Import XML file into DuckDB.

        Args:
            conn: DuckDB connection.
            file_path: Path to the XML file.
            record_path: Slash-separated path to repeating records
                (e.g., "Orders/Order"). Auto-detected if not provided.
            header: Unused (XML has element names as headers). Kept for interface compat.

        Returns:
            ImportResult with schema and row count.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file exceeds MAX_FILE_SIZE_BYTES.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"XML file not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"XML file exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB limit "
                f"({file_size // (1024 * 1024)}MB). Use database import for large files."
            )

        with open(file_path, encoding="utf-8") as f:
            raw = xmltodict.parse(f.read())

        records = self._discover_records(raw, record_path)
        cleaned = [self._clean_xml_record(r) for r in records]
        flat_records = [flatten_record(r) for r in cleaned]
        result = load_flat_records_to_duckdb(conn, flat_records, source_type="xml")

        # Warn when auto-discovery was used — it picks the largest list of dicts
        # which may be line items rather than top-level orders.
        if record_path is None and result.row_count > 0:
            result.warnings.append(
                "XML records were auto-discovered (largest repeating element). "
                "If the wrong element was selected (e.g., line items instead of "
                "orders), re-import with an explicit record_path parameter."
            )
        return result

    def _clean_xml_record(self, record: Any) -> dict:
        """Remove XML artifacts from dict keys (namespaces, @attributes, #text).

        Args:
            record: Dictionary from xmltodict parse.

        Returns:
            Cleaned dictionary with namespace prefixes and XML artifacts removed.
        """
        if not isinstance(record, dict):
            return record
        cleaned: dict[str, Any] = {}
        for key, value in record.items():
            # Strip namespace prefix (e.g., "ns0:Name" → "Name")
            clean_key = key.split(":")[-1] if ":" in key else key
            # Strip attribute marker (e.g., "@type" → "type")
            clean_key = clean_key.lstrip("@")
            # Skip #text nodes (content already captured by parent)
            if clean_key == "#text":
                continue
            if isinstance(value, dict):
                if "#text" in value:
                    # Element with attributes + text: extract text value
                    cleaned[clean_key] = value["#text"]
                else:
                    cleaned[clean_key] = self._clean_xml_record(value)
            elif isinstance(value, list):
                cleaned[clean_key] = [
                    self._clean_xml_record(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                cleaned[clean_key] = value
        return cleaned

    def _discover_records(
        self, data: Any, record_path: str | None = None
    ) -> list[dict]:
        """Find repeating elements in XML dict structure.

        Args:
            data: Parsed XML dict from xmltodict.
            record_path: Explicit slash-separated path to records.

        Returns:
            List of dicts representing individual records.
        """
        if record_path:
            for key in record_path.split("/"):
                data = data[key]
            return data if isinstance(data, list) else [data]
        return self._find_largest_list(data) or ([data] if isinstance(data, dict) else [])

    def _find_largest_list(
        self, data: Any, best: list | None = None
    ) -> list | None:
        """Recursively find the list[dict] with the most items.

        Args:
            data: Current node in the XML dict tree.
            best: Current best candidate list.

        Returns:
            The largest list of dicts found, or None.
        """
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if best is None or len(data) > len(best):
                best = data
        if isinstance(data, dict):
            for value in data.values():
                result = self._find_largest_list(value, best)
                if result is not None:
                    best = result
        return best

