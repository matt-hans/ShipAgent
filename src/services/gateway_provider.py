"""Centralized MCP gateway provider — single owner of process-global singletons.

All callers (API routes, agent tools, conversation processing) import
gateway accessors from HERE. This module owns the singleton lifecycle.
Never instantiate DataSourceMCPClient or ExternalSourcesMCPClient elsewhere.
"""

import asyncio
import logging
from typing import Any

from src.services.data_source_mcp_client import DataSourceMCPClient
from src.services.external_sources_mcp_client import ExternalSourcesMCPClient
from src.services.mapping_cache import invalidate as invalidate_mapping_cache

logger = logging.getLogger(__name__)

# -- DataSourceMCPClient singleton -----------------------------------------
_data_gateway: DataSourceMCPClient | None = None
_data_gateway_lock = asyncio.Lock()


async def get_data_gateway() -> DataSourceMCPClient:
    """Get or create the process-global DataSourceMCPClient.

    Thread-safe via double-checked locking. If a previous connect()
    failed, the stale instance is discarded and a fresh one created.

    Returns:
        The shared DataSourceMCPClient instance.
    """
    global _data_gateway
    if _data_gateway is not None and _data_gateway.is_connected:
        return _data_gateway
    async with _data_gateway_lock:
        if _data_gateway is None or not _data_gateway.is_connected:
            client = DataSourceMCPClient()
            await client.connect()
            _data_gateway = client
            logger.info("DataSourceMCPClient singleton initialized")
    return _data_gateway


# -- ExternalSourcesMCPClient singleton ------------------------------------
_ext_sources_client: ExternalSourcesMCPClient | None = None
_ext_sources_lock = asyncio.Lock()


async def get_external_sources_client() -> ExternalSourcesMCPClient:
    """Get or create the process-global ExternalSourcesMCPClient.

    Thread-safe via double-checked locking. If a previous connect()
    failed, the stale instance is discarded and a fresh one created.

    Returns:
        The shared ExternalSourcesMCPClient instance.
    """
    global _ext_sources_client
    if _ext_sources_client is not None and _ext_sources_client.is_connected:
        return _ext_sources_client
    async with _ext_sources_lock:
        if _ext_sources_client is None or not _ext_sources_client.is_connected:
            client = ExternalSourcesMCPClient()
            await client.connect()
            _ext_sources_client = client
            logger.info("ExternalSourcesMCPClient singleton initialized")
    return _ext_sources_client


def get_data_gateway_if_connected() -> DataSourceMCPClient | None:
    """Return the data gateway if already connected, None otherwise.

    Non-async peek used by conversation creation to avoid opening an MCP
    stdio connection during the request lifecycle.
    """
    if _data_gateway is not None and _data_gateway.is_connected:
        return _data_gateway
    return None


# -- UPSMCPClient singleton ---------------------------------------------------
_ups_gateway: Any = None
_ups_gateway_lock = asyncio.Lock()


def _build_ups_gateway() -> Any:
    """Build a UPSMCPClient using runtime credential resolution.

    Resolves credentials via runtime_credentials adapter (DB priority,
    env var fallback). Uses deferred import to avoid circular imports.

    Returns:
        A new UPSMCPClient instance (not yet connected).

    Raises:
        RuntimeError: If no UPS credentials are available.
    """
    import os

    from src.services.runtime_credentials import resolve_ups_credentials
    from src.services.ups_mcp_client import UPSMCPClient

    creds = resolve_ups_credentials()
    if creds is None:
        raise RuntimeError(
            "No UPS credentials configured. Open Settings to connect UPS."
        )

    return UPSMCPClient(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        environment=creds.environment,
        account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
    )


async def get_ups_gateway() -> Any:
    """Get or create the process-global UPSMCPClient.

    Thread-safe via double-checked locking. If a previous connect()
    failed or the client disconnected, a fresh one is created.

    Returns:
        The shared UPSMCPClient instance.
    """
    global _ups_gateway
    if _ups_gateway is not None:
        connected = getattr(_ups_gateway, "is_connected", False)
        if isinstance(connected, bool) and connected:
            return _ups_gateway
    async with _ups_gateway_lock:
        if _ups_gateway is not None:
            connected = getattr(_ups_gateway, "is_connected", False)
            if isinstance(connected, bool) and connected:
                return _ups_gateway
            await _ups_gateway.connect()
            return _ups_gateway
        client = _build_ups_gateway()
        await client.connect()
        _ups_gateway = client
        logger.info("UPSMCPClient singleton initialized")
    return _ups_gateway


async def check_gateway_health() -> dict[str, dict[str, str]]:
    """Probe connected MCP gateways for liveness. Non-blocking, best-effort.

    Returns:
        Dict mapping gateway name to status dict.
    """
    results: dict[str, dict[str, str]] = {}
    for name, client in [
        ("data_source", _data_gateway),
        ("external_sources", _ext_sources_client),
        ("ups", _ups_gateway),
    ]:
        if client is None:
            results[name] = {"status": "not_initialized"}
        elif not getattr(client, "is_connected", False):
            results[name] = {"status": "disconnected"}
        else:
            try:
                healthy = await client.check_health()
                results[name] = {"status": "ok" if healthy else "unhealthy"}
            except Exception:
                results[name] = {"status": "unhealthy"}
    return results


async def shutdown_gateways() -> None:
    """Shutdown hook — disconnect all gateway clients. Call from FastAPI lifespan."""
    global _data_gateway, _ext_sources_client, _ups_gateway
    invalidate_mapping_cache()
    if _data_gateway is not None:
        try:
            await _data_gateway.disconnect_mcp()
        except Exception as e:
            logger.warning("Failed to disconnect DataSourceMCPClient: %s", e)
        _data_gateway = None
    if _ext_sources_client is not None:
        try:
            await _ext_sources_client.disconnect()
        except Exception as e:
            logger.warning("Failed to disconnect ExternalSourcesMCPClient: %s", e)
        _ext_sources_client = None
    if _ups_gateway is not None:
        try:
            await _ups_gateway.disconnect()
        except Exception as e:
            logger.warning("Failed to disconnect UPSMCPClient: %s", e)
        _ups_gateway = None
