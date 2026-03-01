# src/mcp/data_source/tools/schema_migration.py
"""Schema migration for external_orders DuckDB table.

Called during Data Source MCP lifespan to ensure the table exists
before any upsert operations.
"""
from __future__ import annotations

import logging
import duckdb

logger = logging.getLogger(__name__)

EXTERNAL_ORDERS_DDL = """
CREATE TABLE IF NOT EXISTS external_orders (
    platform            VARCHAR NOT NULL,
    external_id         VARCHAR NOT NULL,
    credential_ref      VARCHAR NOT NULL,

    order_number        VARCHAR,
    order_status        VARCHAR,
    payment_status      VARCHAR,
    fulfillment_status  VARCHAR,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,

    ship_to_name        VARCHAR,
    ship_to_company     VARCHAR,
    ship_to_address1    VARCHAR,
    ship_to_address2    VARCHAR,
    ship_to_city        VARCHAR,
    ship_to_state       VARCHAR,
    ship_to_postal      VARCHAR,
    ship_to_country     VARCHAR,
    ship_to_phone       VARCHAR,
    is_residential      BOOLEAN,

    total_weight_grams  BIGINT,
    package_count       INTEGER DEFAULT 1,
    shipping_method     VARCHAR,
    service_code        VARCHAR,

    total_price_cents   BIGINT,
    currency            VARCHAR DEFAULT 'USD',

    customer_name       VARCHAR,
    customer_email      VARCHAR,
    item_count          INTEGER,
    tags                VARCHAR,

    canonical_hash      VARCHAR NOT NULL,
    mapping_version     VARCHAR DEFAULT '1.0',
    ingested_at         TIMESTAMPTZ NOT NULL,
    sync_run_id         VARCHAR,

    attrs_json          VARCHAR,
    raw_json            VARCHAR,

    PRIMARY KEY (platform, external_id, credential_ref)
);
"""


def ensure_external_orders_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Create external_orders table if it doesn't exist."""
    conn.execute(EXTERNAL_ORDERS_DDL)
    logger.info("external_orders table ensured")
