"""Fixed-width file adapter for Data Source MCP.

Uses pure Python string slicing at agent-specified byte positions.
No pandas dependency. The agent determines column specs by inspecting
the file via the sniff_file MCP tool, then calls import_fixed_width
with explicit positions.

Per CONTEXT.md:
- Import all rows, flag invalid ones (no threshold)
- Silent skip for empty rows
- Best-effort parsing with string fallback
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult
from src.mcp.data_source.utils import load_flat_records_to_duckdb


class FixedWidthAdapter(BaseSourceAdapter):
    """Adapter for importing fixed-width format files.

    Parses files by slicing each line at agent-specified byte positions.
    Column names can be provided explicitly, extracted from a header line,
    or auto-generated as col_0, col_1, etc.

    Example:
        >>> adapter = FixedWidthAdapter()
        >>> result = adapter.import_data(
        ...     conn, file_path="report.fwf",
        ...     col_specs=[(0, 20), (20, 35), (35, 37)],
        ...     names=["name", "city", "state"],
        ... )
    """

    @property
    def source_type(self) -> str:
        """Return the adapter's source type identifier.

        Returns:
            'fixed_width' — identifies this as a fixed-width file adapter.
        """
        return "fixed_width"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        col_specs: list[tuple[int, int]] | None = None,
        names: list[str] | None = None,
        header: bool = False,
        **kwargs,
    ) -> ImportResult:
        """Import fixed-width file into DuckDB.

        Args:
            conn: DuckDB connection.
            file_path: Path to the fixed-width file.
            col_specs: List of (start, end) byte positions for each column.
                Required — the agent determines these via sniff_file.
            names: Column names. Auto-generated as col_0, col_1, ... if not provided
                and header is False. If header is True, names are extracted from
                the first line using col_specs.
            header: If True, first line is treated as header (names extracted
                from it using col_specs).

        Returns:
            ImportResult with schema and row count.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If col_specs is not provided.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fixed-width file not found: {file_path}")
        if not col_specs:
            raise ValueError("col_specs required for fixed-width import")

        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        start_line = 0
        if header and lines:
            if names is None:
                # Extract column names from first line using col_specs
                names = [lines[0][s:e].strip() for s, e in col_specs]
            start_line = 1

        if names is None:
            names = [f"col_{i}" for i in range(len(col_specs))]

        records: list[dict] = []
        for line in lines[start_line:]:
            if not line.strip():
                continue
            record = {
                names[i]: line[s:e].strip()
                for i, (s, e) in enumerate(col_specs)
            }
            records.append(record)

        return load_flat_records_to_duckdb(conn, records, source_type="fixed_width")

