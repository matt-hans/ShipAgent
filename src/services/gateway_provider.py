"""Centralized MCP gateway provider — single owner of process-global singletons.

All callers (API routes, agent tools, conversation processing) import
gateway accessors from HERE. This module owns the singleton lifecycle.
Never instantiate DataSourceMCPClient or ExternalSourcesMCPClient elsewhere.
"""

import asyncio
import logging

from src.services.data_source_mcp_client import DataSourceMCPClient
from src.services.external_sources_mcp_client import ExternalSourcesMCPClient

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


async def shutdown_gateways() -> None:
    """Shutdown hook — disconnect all gateway clients. Call from FastAPI lifespan."""
    global _data_gateway, _ext_sources_client
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
