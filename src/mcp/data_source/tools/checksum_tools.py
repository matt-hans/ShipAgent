"""Checksum tools for data integrity verification."""

from fastmcp import Context

from ..models import ChecksumResult
from ..utils import compute_row_checksum


async def compute_checksums(
    ctx: Context,
    start_row: int = 1,
    end_row: int | None = None,
) -> dict:
    """Compute SHA-256 checksums for rows in imported data.

    Checksums are deterministic - same row data always produces same checksum.
    Used for data integrity verification during batch processing.

    Args:
        start_row: First row to checksum (1-based, default: 1)
        end_row: Last row to checksum (default: all rows)

    Returns:
        Dictionary with list of row checksums.

    Example:
        >>> result = await compute_checksums(ctx, start_row=1, end_row=100)
        >>> print(result["checksums"][0])
        {"row_number": 1, "checksum": "a1b2c3d4..."}
    """
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Computing checksums for rows {start_row} to {end_row or 'end'}")

    # Get column names
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema]

    # Get total row count
    total_rows = db.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]

    if end_row is None:
        end_row = total_rows

    # Validate range
    if start_row < 1:
        start_row = 1
    if end_row > total_rows:
        end_row = total_rows
    if start_row > end_row:
        raise ValueError(f"start_row ({start_row}) cannot be greater than end_row ({end_row})")

    # Fetch rows in the range
    limit = end_row - start_row + 1
    offset = start_row - 1

    results = db.execute(f"""
        SELECT * FROM imported_data
        LIMIT {limit} OFFSET {offset}
    """).fetchall()

    checksums = []
    for i, row in enumerate(results):
        row_dict = dict(zip(columns, row))
        checksum = compute_row_checksum(row_dict)
        checksums.append(ChecksumResult(
            row_number=start_row + i,
            checksum=checksum
        ).model_dump())

    await ctx.info(f"Computed {len(checksums)} checksums")

    return {
        "checksums": checksums,
        "count": len(checksums),
        "start_row": start_row,
        "end_row": end_row,
    }


async def verify_checksum(
    row_number: int,
    expected_checksum: str,
    ctx: Context,
) -> dict:
    """Verify that a row's current checksum matches an expected value.

    Used to detect if source data has changed since job creation.

    Args:
        row_number: 1-based row number
        expected_checksum: Expected SHA-256 checksum

    Returns:
        Dictionary with verification result.

    Example:
        >>> result = await verify_checksum(1, "a1b2c3d4...", ctx)
        >>> print(result["matches"])
        True
    """
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Verifying checksum for row {row_number}")

    # Get column names
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema]

    # Get the row
    result = db.execute(f"""
        SELECT * FROM imported_data
        LIMIT 1 OFFSET {row_number - 1}
    """).fetchone()

    if result is None:
        raise ValueError(f"Row {row_number} not found")

    row_dict = dict(zip(columns, result))
    actual_checksum = compute_row_checksum(row_dict)

    matches = actual_checksum == expected_checksum

    if not matches:
        await ctx.info(f"Checksum mismatch for row {row_number}")

    return {
        "row_number": row_number,
        "expected_checksum": expected_checksum,
        "actual_checksum": actual_checksum,
        "matches": matches,
    }
