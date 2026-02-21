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
    *,
    _threshold: float = 0.90,
) -> tuple[list[tuple[int, int]], list[str]] | None:
    """Auto-detect column boundaries from a fixed-width file's header line.

    Uses a space-fraction gap detection algorithm: positions where at least
    ``_threshold`` (default 90 %) of data rows have a space character are
    classified as *gap* positions.  Consecutive gap positions form *gap runs*
    that separate data columns.  After computing the raw data-based column
    ranges the function:

    1. Assigns each range to the header word with the most character overlap.
    2. Merges adjacent ranges that share the same best header word (handles
       multi-word column values such as ``"Next Day Air"``).
    3. Removes ranges with no header-word match (transient gap artefacts).
    4. Extends each range start left to the header word start when the header
       word begins before the detected range (handles columns where the data
       value is shorter than the column header, e.g. a 1-char ``Y``/``N``
       boolean under a 6-char ``HAZMAT`` header).
    5. Validates that every extracted name is a legal column identifier.

    This approach correctly handles:
    - Columns where data is narrower than the header (e.g. numeric weight
      columns like ``WT_LBS`` whose header is 6 chars but data is 4 chars).
    - Multi-word service codes (``"Next Day Air"``, ``"3 Day Select"``) that
      contain internal spaces.
    - Boolean columns (``Y``/``N``) whose 1-char data sits just before the
      header word's first character.

    Returns ``None`` when auto-detection cannot determine valid column
    boundaries.  Callers should fall back to the two-step
    ``sniff_file`` → ``import_fixed_width`` workflow in that case.

    Args:
        lines: Raw lines from the file (header as first element, data
            lines following).  Newlines are stripped internally.
        _threshold: Space-fraction threshold for gap detection (private,
            exposed for testing only).  Default 0.90 works well for files
            with 10–20 data rows.

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
    data_lines = [ln.rstrip("\n\r") for ln in lines[1:] if ln.strip()]

    if not data_lines:
        return None

    max_len = max(len(header), *(len(dl) for dl in data_lines))
    if max_len == 0:
        return None

    # Locate header words — used for naming and validation.
    header_words = list(re.finditer(r"\S+", header))
    if len(header_words) < 2:
        return None

    # Validate ALL header words upfront.  Any non-identifier token (e.g. "V2.1"
    # in legacy mainframe headers like "HDR20260220SHIPAGENT BATCH EXPORT V2.1")
    # invalidates the entire file for auto-detection.
    if any(not _COL_NAME_RE.match(m.group()) for m in header_words):
        return None

    n = len(data_lines)

    # -----------------------------------------------------------------------
    # Step 1: Compute space fraction at each character position across all
    # data rows.  A position extending beyond a row's length counts as space.
    # -----------------------------------------------------------------------
    space_fracs: list[float] = []
    for pos in range(max_len):
        spaces = sum(
            1 for dl in data_lines if pos >= len(dl) or dl[pos] == " "
        )
        space_fracs.append(spaces / n)

    # -----------------------------------------------------------------------
    # Step 2: Identify gap positions (>= threshold fraction have spaces) and
    # group them into consecutive *gap runs*.
    # -----------------------------------------------------------------------
    gap_positions = [
        pos for pos, frac in enumerate(space_fracs) if frac >= _threshold
    ]

    def _group_runs(positions: list[int]) -> list[tuple[int, int]]:
        if not positions:
            return []
        runs: list[tuple[int, int]] = []
        start = positions[0]
        prev = positions[0]
        for pos in positions[1:]:
            if pos != prev + 1:
                runs.append((start, prev + 1))
                start = pos
            prev = pos
        runs.append((start, prev + 1))
        return runs

    gap_runs = _group_runs(gap_positions)

    # Find the first position that is NOT a gap (= start of first data column).
    first_data = next(
        (pos for pos in range(max_len) if space_fracs[pos] < _threshold),
        None,
    )
    if first_data is None:
        return None  # Every position is a gap — nothing to detect

    # -----------------------------------------------------------------------
    # Step 3: Derive raw column ranges from gap runs.
    # -----------------------------------------------------------------------
    col_ranges: list[tuple[int, int]] = []
    prev_end = first_data
    for gap_s, gap_e in gap_runs:
        if gap_s > prev_end:
            col_ranges.append((prev_end, gap_s))
        prev_end = gap_e
    if prev_end < max_len:
        col_ranges.append((prev_end, max_len))

    if not col_ranges:
        return None

    # -----------------------------------------------------------------------
    # Step 4: Assign each raw range to the header word with maximum overlap.
    # -----------------------------------------------------------------------
    def _best_header_word(
        col_start: int, col_end: int
    ) -> re.Match | None:  # type: ignore[type-arg]
        best_overlap = 0
        best_word = None
        for m in header_words:
            overlap = min(col_end, m.end()) - max(col_start, m.start())
            if overlap > best_overlap:
                best_overlap = overlap
                best_word = m
        return best_word

    tagged = [
        (s, e, _best_header_word(s, e)) for s, e in col_ranges
    ]

    # -----------------------------------------------------------------------
    # Step 5: Merge adjacent ranges that share the same best header word
    # (or where the next range has no header word — transient artefact).
    # -----------------------------------------------------------------------
    merged: list[tuple[int, int, re.Match | None]] = []  # type: ignore[type-arg]
    i = 0
    while i < len(tagged):
        s, e, best = tagged[i]
        while i + 1 < len(tagged):
            _ns, ne, nbest = tagged[i + 1]
            same_word = (
                nbest is None
                or (
                    best is not None
                    and nbest is not None
                    and nbest.group() == best.group()
                )
            )
            if same_word:
                e = ne
                if nbest is not None:
                    best = nbest
                i += 1
            else:
                break
        merged.append((s, e, best))
        i += 1

    # Drop ranges with no header-word match.
    merged = [(s, e, w) for s, e, w in merged if w is not None]

    if not merged:
        return None

    # -----------------------------------------------------------------------
    # Step 6: Extend range start left to the header word start when the
    # header word begins before the detected data range (handles 1-char
    # boolean columns like Y/N that sit just before the header word).
    # -----------------------------------------------------------------------
    final: list[tuple[int, int, re.Match]] = []  # type: ignore[type-arg]
    prev_end_used = 0
    for s, e, w in merged:
        assert w is not None  # guaranteed by filter above
        if w.start() < s and w.start() >= prev_end_used:
            s = w.start()
        final.append((s, e, w))
        prev_end_used = e

    col_specs = [(s, e) for s, e, _ in final]
    names = [w.group() for _, _, w in final]

    # -----------------------------------------------------------------------
    # Step 7: Validate — every name must be a legal column identifier.
    # Rejects legacy mainframe record-header lines like
    # "HDR20260220SHIPAGENT BATCH EXPORT V2.1".
    # -----------------------------------------------------------------------
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

