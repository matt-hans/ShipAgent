"""Column sample tools for Data Source MCP.

Provides sample distinct values per column to ground the LLM's
FilterIntent generation with real data values from the source.
"""

from typing import Any

import duckdb
from fastmcp import Context

from ..models import SOURCE_ROW_NUM_COLUMN


def get_column_samples_impl(
    db: duckdb.DuckDBPyConnection,
    max_samples: int = 5,
) -> dict[str, list[Any]]:
    """Get sample distinct values for each column (pure function for testing).

    Args:
        db: DuckDB connection with imported_data table.
        max_samples: Maximum distinct values per column (default 5).

    Returns:
        Dict mapping column names to lists of sample values.
        NULL values are excluded. Internal columns are excluded.
    """
    schema = db.execute("DESCRIBE imported_data").fetchall()
    columns = [col[0] for col in schema if col[0] != SOURCE_ROW_NUM_COLUMN]

    samples: dict[str, list[Any]] = {}
    for col in columns:
        rows = db.execute(
            f'SELECT DISTINCT "{col}" FROM imported_data '
            f'WHERE "{col}" IS NOT NULL '
            f"ORDER BY 1 "
            f"LIMIT {max_samples}"
        ).fetchall()
        samples[col] = [row[0] for row in rows]

    return samples


async def get_column_samples(
    ctx: Context,
    max_samples: int = 5,
) -> dict:
    """Get sample distinct values for each column in the data source.

    Returns up to max_samples distinct non-NULL values per column,
    useful for grounding LLM filter generation with real data values.

    Args:
        max_samples: Maximum distinct values per column (default 5).

    Returns:
        Dict mapping column names to lists of sample values.
    """
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Fetching column samples (max {max_samples} per column)")

    result = get_column_samples_impl(db, max_samples)

    await ctx.info(f"Returned samples for {len(result)} columns")
    return result
