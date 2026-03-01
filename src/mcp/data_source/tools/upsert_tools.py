# src/mcp/data_source/tools/upsert_tools.py
"""DuckDB upsert operations for platform order import.

Uses INSERT ... ON CONFLICT DO UPDATE ... WHERE canonical_hash <> excluded.canonical_hash
for atomic, change-detection-aware upserts. See DuckDB docs:
https://duckdb.org/docs/stable/sql/statements/insert.html

Counting strategy:
1. Dedupe batch by PK (keep last occurrence)
2. Single SELECT of existing hashes for those PKs
3. Classify: new (inserted) / changed (updated) / unchanged (skipped)
4. Single INSERT ... ON CONFLICT for ALL rows (atomic)
5. Return pre-computed counts
"""
from __future__ import annotations

import logging
from typing import Any

import duckdb
from fastmcp import Context

logger = logging.getLogger(__name__)


def _dedupe_batch(
    records: list[dict[str, Any]],
    pk_columns: list[str],
) -> list[dict[str, Any]]:
    """Deduplicate records within a batch by PK, keeping the last occurrence.

    Required because DuckDB INSERT ... ON CONFLICT errors when the same PK
    appears multiple times in a single statement (common with overlap windows).
    """
    seen: dict[tuple, dict[str, Any]] = {}
    for record in records:
        key = tuple(record.get(col) for col in pk_columns)
        seen[key] = record  # last one wins
    return list(seen.values())


def _classify_records(
    conn: duckdb.DuckDBPyConnection,
    records: list[dict[str, Any]],
    table_name: str,
    pk_columns: list[str],
) -> dict[str, int]:
    """Pre-compute inserted/updated/skipped counts via hash comparison.

    Single SELECT for all PKs in the batch. Returns counts only — the actual
    write is handled by the ON CONFLICT upsert.
    """
    existing_hashes: dict[tuple, str] = {}
    pk_tuples = [tuple(r.get(col) for col in pk_columns) for r in records]

    if pk_tuples:
        pk_cols_sql = ", ".join(pk_columns)
        # Build safe parameterized IN clause
        pk_placeholders = ", ".join(
            f"({', '.join('?' for _ in pk_columns)})" for _ in pk_tuples
        )
        pk_values = [v for t in pk_tuples for v in t]
        try:
            rows = conn.execute(
                f"SELECT {pk_cols_sql}, canonical_hash FROM {table_name} "
                f"WHERE ({pk_cols_sql}) IN ({pk_placeholders})",
                pk_values,
            ).fetchall()
            for row in rows:
                key = tuple(row[:-1])
                existing_hashes[key] = row[-1]
        except duckdb.CatalogException:
            pass  # Table doesn't exist yet — all records are inserts

    inserted = updated = skipped = 0
    for record in records:
        key = tuple(record.get(col) for col in pk_columns)
        existing_hash = existing_hashes.get(key)
        if existing_hash is None:
            inserted += 1
        elif existing_hash != record.get("canonical_hash"):
            updated += 1
        else:
            skipped += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def upsert_records_to_duckdb(
    conn: duckdb.DuckDBPyConnection,
    records: list[dict[str, Any]],
    table_name: str,
    pk_columns: list[str],
) -> dict[str, int]:
    """Upsert records into DuckDB with hash-based change detection.

    1. Deduplicates within batch (last occurrence wins per PK)
    2. Pre-computes inserted/updated/skipped counts via hash comparison
    3. Executes atomic INSERT ... ON CONFLICT DO UPDATE ... WHERE hash differs
    4. Returns pre-computed counts
    """
    if not records:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    # Step 1: Dedupe within batch (prevents DuckDB duplicate-PK-in-statement errors)
    deduped = _dedupe_batch(records, pk_columns)

    # Step 2: Pre-compute counts
    counts = _classify_records(conn, deduped, table_name, pk_columns)

    # Step 3: Atomic upsert via ON CONFLICT DO UPDATE ... WHERE hash differs
    columns = list(deduped[0].keys())
    cols_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    pk_conflict = ", ".join(pk_columns)

    # Build SET clause for all non-PK columns
    non_pk = [c for c in columns if c not in pk_columns]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in non_pk)

    upsert_sql = (
        f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_conflict}) DO UPDATE SET {set_clause} "
        f"WHERE {table_name}.canonical_hash <> excluded.canonical_hash"
    )

    for record in deduped:
        values = [record.get(col) for col in columns]
        conn.execute(upsert_sql, values)

    return counts


async def upsert_records(
    records: list[dict[str, Any]],
    table_name: str,
    pk_columns: list[str],
    ctx: Context,
) -> dict[str, int]:
    """Upsert records into a DuckDB table with hash-based change detection.

    MCP-facing wrapper around upsert_records_to_duckdb. Uses the shared
    DuckDB connection from the server lifespan context.

    Args:
        records: List of flat dicts to upsert.
        table_name: Target DuckDB table name (e.g., 'external_orders').
        pk_columns: Columns forming the composite primary key.
        ctx: FastMCP context with lifespan DuckDB connection.

    Returns:
        Dict with inserted, updated, skipped counts.
    """
    db = ctx.request_context.lifespan_context["db"]
    await ctx.info(f"Upserting {len(records)} records into {table_name}")
    result = upsert_records_to_duckdb(db, records, table_name, pk_columns)
    await ctx.info(
        f"Upsert complete: {result['inserted']} inserted, "
        f"{result['updated']} updated, {result['skipped']} skipped"
    )
    return result
