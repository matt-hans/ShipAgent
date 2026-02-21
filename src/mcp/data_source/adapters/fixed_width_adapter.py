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

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult
from src.mcp.data_source.utils import load_flat_records_to_duckdb

# Pattern that a valid FWF column name must match.
# Accepts identifiers like ORDER_NUM, RECIPIENT_NAME, WT_LBS, ST, ZIP.
# Rejects record-tag tokens like V2.1, HDR20260220SHIPAGENT (via the period
# check in V2.1 — the overall validation rejects any name that does not match).
_COL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def auto_detect_col_specs(
    lines: list[str],
) -> tuple[list[tuple[int, int]], list[str]] | None:
    """Auto-detect column boundaries from a fixed-width file's header line.

    Uses the start positions of whitespace-separated words in the first line
    (the header) as column start positions.  Each column spans from its word
    start to the next word start (or end of the longest line).

    This approach correctly handles FWF files where column separators are a
    single space (e.g. ``ORDER_NUM RECIPIENT_NAME``) and data values contain
    embedded spaces (e.g. ``"John Doe"`` in a 20-character name column).

    Returns ``None`` when auto-detection cannot determine valid column
    boundaries.  Callers should fall back to the two-step
    ``sniff_file`` → ``import_fixed_width`` workflow in that case.

    Args:
        lines: Raw lines from the file (header as first element, data
            lines following).  Newlines are stripped internally.

    Returns:
        A tuple ``(col_specs, names)`` where *col_specs* is a list of
        ``(start, end)`` character-position pairs and *names* is the list
        of column names extracted from the header.  Returns ``None`` when
        detection fails.

    Raises:
        Nothing — all failure paths return ``None``.

    Example:
        >>> lines = [
        ...     "NAME                CITY           ST\\n",
        ...     "John Doe            Dallas         TX\\n",
        ...     "Jane Smith          Austin         TX\\n",
        ... ]
        >>> result = auto_detect_col_specs(lines)
        >>> result is not None
        True
        >>> specs, names = result
        >>> names
        ['NAME', 'CITY', 'ST']
        >>> specs[0]
        (0, 20)
    """
    if len(lines) < 2:
        return None

    header = lines[0].rstrip("\n\r")
    data_lines = [ln.rstrip("\n\r") for ln in lines[1:6] if ln.strip()]

    if not data_lines:
        return None

    max_len = max(len(header), *(len(dl) for dl in data_lines))
    if max_len == 0:
        return None

    # Find the start position of each whitespace-separated word in the header.
    # These word-start positions become column start positions.
    word_matches = list(re.finditer(r"\S+", header))
    if len(word_matches) < 2:
        return None

    col_starts = [m.start() for m in word_matches]

    # Build col_specs: each column spans from its word start to the next
    # word start, or to the end of the longest line for the last column.
    col_specs: list[tuple[int, int]] = []
    for i, start in enumerate(col_starts):
        end = col_starts[i + 1] if i + 1 < len(col_starts) else max_len
        col_specs.append((start, end))

    # Extract column names from the header using the derived specs.
    names = [header[s:e].strip() for s, e in col_specs]

    # Validate: every name must be non-empty and look like a column identifier
    # (letters, digits, underscores — no periods, version strings, etc.).
    # This rejects legacy mainframe record-header lines like
    # "HDR20260220SHIPAGENT BATCH EXPORT V2.1".
    if any(not n or not _COL_NAME_RE.match(n) for n in names):
        return None

    return col_specs, names


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

