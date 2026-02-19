"""Shared schema-column inference helpers for batch filter enforcement.

These helpers keep prompt hints and deterministic pipeline enforcement aligned.
"""

from __future__ import annotations


def resolve_total_column(schema_columns: set[str]) -> str | None:
    """Resolve the most likely monetary total column from a schema."""
    preferred = (
        "total_price",
        "order_total",
        "total_amount",
        "subtotal_price",
        "subtotal",
        "total",
        "amount",
        # Best-effort fallbacks used by some exported shipment datasets.
        "declared_value",
        "order_value",
        "invoice_monetary_value",
    )
    normalized_lookup = {col.casefold(): col for col in schema_columns}
    for key in preferred:
        match = normalized_lookup.get(key.casefold())
        if match:
            return match
    for col in sorted(schema_columns):
        lowered = col.casefold()
        if "total" in lowered or "amount" in lowered or "price" in lowered:
            return col
    return None


def resolve_fulfillment_status_column(schema_columns: set[str]) -> str | None:
    """Resolve a fulfillment-status-like column name case-insensitively."""
    preferred = (
        "fulfillment_status",
        "fulfilment_status",
        "display_fulfillment_status",
        "display_fulfilment_status",
        "fulfillmentstatus",
        "fulfilmentstatus",
        "displayfulfillmentstatus",
        "displayfulfilmentstatus",
    )
    normalized_lookup = {col.casefold(): col for col in schema_columns}
    for key in preferred:
        match = normalized_lookup.get(key.casefold())
        if match:
            return match

    # Fallback for mixed formatting (camelCase, no underscores, etc.).
    for column in sorted(schema_columns):
        compact = "".join(ch for ch in column.casefold() if ch.isalnum())
        if "fulfillment" in compact or "fulfilment" in compact:
            return column
    return None
