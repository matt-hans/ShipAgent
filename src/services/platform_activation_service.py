# src/services/platform_activation_service.py
"""PlatformActivationService: connect → page → normalize → upsert → checkpoint.

Orchestrates the full activation/refresh lifecycle for a platform integration.
Uses PlatformGateway for MCP communication and DuckDB for order storage.

Flow:
1. Validate platform config exists
2. Check for resume_cursor (crash recovery)
3. Connect via auth.connect (gateway handles lazy spawn)
4. Page through orders.list with cursor pagination
5. For each page: map → upsert → checkpoint cursor
6. On completion: clear cursor, advance watermark
"""
from __future__ import annotations

import importlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import duckdb

from src.mcp.data_source.tools.upsert_tools import upsert_records_to_duckdb
from src.services.platform_models import (
    ActivationReport,
    PlatformError,
    PlatformErrorCode,
)

logger = logging.getLogger(__name__)

PK_COLUMNS = ["platform", "external_id", "credential_ref"]
TABLE_NAME = "external_orders"


class PlatformActivationService:
    """Orchestrates platform activation: connect → page → normalize → upsert → checkpoint."""

    def __init__(
        self,
        registry: Any,
        gateway: Any,
        duckdb_conn: duckdb.DuckDBPyConnection,
    ):
        self._registry = registry
        self._gateway = gateway
        self._conn = duckdb_conn

    async def activate_platform(
        self,
        platform_id: str,
        credential_ref: str,
        mode: str = "initial",
    ) -> ActivationReport:
        """Activate or refresh a platform integration.

        Args:
            platform_id: Platform identifier (must exist in registry).
            credential_ref: Credential profile reference.
            mode: 'initial' for full pull, 'refresh' for watermark-based incremental.

        Returns:
            ActivationReport with import statistics.

        Raises:
            PlatformError: If platform not found or activation fails.
        """
        start_time = time.monotonic()
        sync_run_id = str(uuid.uuid4())

        # Step 1: Validate platform config
        config = self._registry.get_config(platform_id)
        if config is None:
            raise PlatformError(
                error_code=PlatformErrorCode.INVALID_ARGUMENT,
                message=f"Unknown platform: {platform_id}",
            )

        # Step 2: Check for resume state
        state = self._registry.get_state(platform_id, credential_ref)
        resume_cursor = None
        since = None

        if state:
            resume_cursor = getattr(state, "resume_cursor", None)
            if mode == "refresh" and not resume_cursor:
                watermark = getattr(state, "last_completed_watermark", None)
                if watermark:
                    since = watermark

        # Step 3: Connect via auth.connect
        await self._gateway.call_tool(
            platform_id, credential_ref, "auth.connect",
            {"credential_ref": credential_ref},
        )

        # Step 4: Load the mapper for this platform
        mapper = self._load_mapper(platform_id)

        # Step 5: Page through orders
        cursor = resume_cursor
        total_imported = 0
        pages_fetched = 0
        last_watermark = None
        warnings: list[str] = []

        while True:
            # Build args for orders.list
            args: dict[str, Any] = {}
            if cursor:
                args["cursor"] = cursor
            if since and not cursor:
                args["since"] = since

            # Fetch page
            page = await self._gateway.call_tool(
                platform_id, credential_ref, "orders.list", args,
            )

            items = page.get("items", [])
            next_cursor = page.get("next_cursor")
            page_watermark = page.get("watermark")
            pages_fetched += 1

            if items:
                # Map orders to flat rows
                rows = []
                for order in items:
                    try:
                        row = mapper.to_flat_row(order, credential_ref)
                        row["sync_run_id"] = sync_run_id
                        rows.append(row)
                    except Exception as e:
                        warnings.append(f"Mapper error for order {order.get('id')}: {e}")
                        continue

                # Upsert to DuckDB
                if rows:
                    result = upsert_records_to_duckdb(
                        self._conn, rows, TABLE_NAME, PK_COLUMNS,
                    )
                    total_imported += result["inserted"] + result["updated"]

            # Track last watermark from pages
            if page_watermark:
                last_watermark = page_watermark

            # Checkpoint: save cursor for crash recovery
            if next_cursor:
                self._registry.record_sync_checkpoint(
                    platform_id, credential_ref,
                    resume_cursor=next_cursor,
                    watermark=None,
                    row_count=total_imported,
                )
            else:
                # Final page: clear cursor, advance watermark
                self._registry.record_sync_checkpoint(
                    platform_id, credential_ref,
                    resume_cursor=None,
                    watermark=last_watermark,
                    row_count=total_imported,
                )
                break

            cursor = next_cursor

        duration = time.monotonic() - start_time

        return ActivationReport(
            platform_id=platform_id,
            credential_ref=credential_ref,
            mode=mode,
            total_imported=total_imported,
            pages_fetched=pages_fetched,
            watermark=last_watermark,
            duration_seconds=round(duration, 2),
            warnings=warnings,
        )

    def _load_mapper(self, platform_id: str) -> Any:
        """Dynamically load the mapper for a platform.

        Convention: src.mcp.platforms.{platform_id}.mapper contains a class
        named {Platform}Mapper (e.g., DummyMapper, ShopifyMapper).
        """
        module_path = f"src.mcp.platforms.{platform_id}.mapper"
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.PERMANENT,
                message=f"Cannot load mapper for {platform_id}: {e}",
            ) from e

        # Find the Mapper class by convention
        mapper_class_name = f"{platform_id.capitalize()}Mapper"
        mapper_class = getattr(mod, mapper_class_name, None)
        if mapper_class is None:
            raise PlatformError(
                error_code=PlatformErrorCode.PERMANENT,
                message=f"Mapper class {mapper_class_name} not found in {module_path}",
            )
        return mapper_class()
