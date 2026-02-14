"""Centralized MCP gateway provider — single owner of process-global singletons.

All callers (API routes, agent tools, conversation processing) import
gateway accessors from HERE. This module owns the singleton lifecycle.
Never instantiate ExternalSourcesMCPClient elsewhere.

Note: DataSourceMCPClient singleton will be added in a later task.
"""

import asyncio
import logging

from src.services.external_sources_mcp_client import ExternalSourcesMCPClient

logger = logging.getLogger(__name__)

# ── ExternalSourcesMCPClient singleton ─────────────────────────────
_ext_sources_client: ExternalSourcesMCPClient | None = None
_ext_sources_lock = asyncio.Lock()


async def get_external_sources_client() -> ExternalSourcesMCPClient:
    """Get or create the process-global ExternalSourcesMCPClient.

    Thread-safe via double-checked locking.

    Returns:
        The shared ExternalSourcesMCPClient instance.
    """
    global _ext_sources_client
    if _ext_sources_client is not None:
        return _ext_sources_client
    async with _ext_sources_lock:
        if _ext_sources_client is None:
            _ext_sources_client = ExternalSourcesMCPClient()
            await _ext_sources_client.connect()
            logger.info("ExternalSourcesMCPClient singleton initialized")
    return _ext_sources_client


async def shutdown_gateways() -> None:
    """Shutdown hook — disconnect all gateway clients. Call from FastAPI lifespan."""
    global _ext_sources_client
    if _ext_sources_client is not None:
        try:
            await _ext_sources_client.disconnect()
        except Exception as e:
            logger.warning("Failed to disconnect ExternalSourcesMCPClient: %s", e)
        _ext_sources_client = None
