"""Schema inspection and modification tools for Data Source MCP."""

from fastmcp import Context

from ..models import SchemaColumn


async def get_schema(ctx: Context) -> dict:
    """Get schema of currently imported data.

    Returns the column names, types, and any warnings about data quality
    (such as ambiguous date formats or mixed types).

    Returns:
        Dictionary with columns list and source metadata.

    Raises:
        ValueError: If no data has been imported yet.

    Example:
        >>> result = await get_schema(ctx)
        >>> print(result["columns"])
        [{"name": "order_id", "type": "INTEGER", "nullable": false}, ...]
    """
    db = ctx.request_context.lifespan_context["db"]
    current_source = ctx.request_context.lifespan_context.get("current_source")

    if current_source is None:
        raise ValueError("No data imported. Use import_csv, import_excel, or import_database first.")

    await ctx.info("Retrieving schema for imported data")

    try:
        schema_rows = db.execute("DESCRIBE imported_data").fetchall()
    except Exception as e:
        raise ValueError(f"No data available: {e}")

    columns = [
        SchemaColumn(
            name=col[0],
            type=col[1],
            nullable=col[2] == "YES",
            warnings=[]
        ).model_dump()
        for col in schema_rows
    ]

    type_overrides = ctx.request_context.lifespan_context.get("type_overrides", {})

    # Apply type overrides to response
    for col in columns:
        if col["name"] in type_overrides:
            col["type_override"] = type_overrides[col["name"]]

    return {
        "columns": columns,
        "row_count": current_source.get("row_count", 0),
        "source_type": current_source.get("type", "unknown"),
        "type_overrides": type_overrides,
    }


async def override_column_type(
    column_name: str,
    new_type: str,
    ctx: Context,
) -> dict:
    """Override the inferred type for a column.

    Use this when schema inference got the type wrong (e.g., order_id inferred
    as INTEGER but should be treated as VARCHAR to preserve leading zeros).

    The override is applied when querying data - the original data is unchanged.

    Args:
        column_name: Name of column to override
        new_type: New type to use (VARCHAR, INTEGER, DOUBLE, DATE, TIMESTAMP, BOOLEAN)

    Returns:
        Dictionary confirming the override.

    Example:
        >>> await override_column_type("order_id", "VARCHAR", ctx)
        {"column": "order_id", "original_type": "BIGINT", "new_type": "VARCHAR"}
    """
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Overriding type for column {column_name} to {new_type}")

    # Validate column exists
    schema_rows = db.execute("DESCRIBE imported_data").fetchall()
    col_names = [row[0] for row in schema_rows]

    if column_name not in col_names:
        raise ValueError(
            f"Column '{column_name}' not found. Available columns: {col_names}"
        )

    # Get original type
    original_type = next(row[1] for row in schema_rows if row[0] == column_name)

    # Validate new type
    valid_types = {"VARCHAR", "INTEGER", "BIGINT", "DOUBLE", "DATE", "TIMESTAMP", "BOOLEAN"}
    if new_type.upper() not in valid_types:
        raise ValueError(
            f"Invalid type '{new_type}'. Valid types: {sorted(valid_types)}"
        )

    # Store override in lifespan context
    type_overrides = ctx.request_context.lifespan_context.setdefault("type_overrides", {})
    type_overrides[column_name] = new_type.upper()

    await ctx.info(f"Type override saved: {column_name} from {original_type} to {new_type}")

    return {
        "column": column_name,
        "original_type": original_type,
        "new_type": new_type.upper(),
    }
