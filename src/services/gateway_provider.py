"""Centralized MCP gateway provider — single owner of process-global singletons.

All callers (API routes, agent tools, conversation processing) import
gateway accessors from HERE. This module owns the singleton lifecycle.
Never instantiate DataSourceMCPClient elsewhere.
"""

import asyncio
import logging
from typing import Any

from src.services.data_source_mcp_client import DataSourceMCPClient
from src.services.mapping_cache import invalidate as invalidate_mapping_cache

logger = logging.getLogger(__name__)

# -- DataSourceMCPClient singleton -----------------------------------------
_data_gateway: DataSourceMCPClient | None = None
_data_gateway_lock = asyncio.Lock()


async def get_data_gateway() -> DataSourceMCPClient:
    """Get or create the process-global DataSourceMCPClient.

    Always acquires the lock to prevent returning a stale reference
    that a concurrent task may be replacing (B-2, CWE-362).

    Returns:
        The shared DataSourceMCPClient instance.
    """
    global _data_gateway
    async with _data_gateway_lock:
        if _data_gateway is None or not _data_gateway.is_connected:
            client = DataSourceMCPClient()
            await client.connect()
            _data_gateway = client
            logger.info("DataSourceMCPClient singleton initialized")
        return _data_gateway



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

    logger.info("UPS gateway using environment=%s", creds.environment)
    return UPSMCPClient(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        environment=creds.environment,
        account_number=creds.account_number or os.environ.get("UPS_ACCOUNT_NUMBER", ""),
    )


async def get_ups_gateway() -> Any:
    """Get or create the process-global UPSMCPClient.

    Always acquires the lock to prevent returning a stale reference
    that a concurrent task may be replacing (B-2, CWE-362).

    Returns:
        The shared UPSMCPClient instance.
    """
    global _ups_gateway
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


# -- PlatformGateway + PlatformRegistry singletons ---------------------------
_platform_registry: Any = None
_platform_gateway: Any = None
_activation_service: Any = None
_platform_lock = asyncio.Lock()


def get_platform_registry() -> Any:
    """Get the PlatformRegistry singleton.

    Must be initialized during FastAPI lifespan startup via
    init_platform_singletons().

    Returns:
        The shared PlatformRegistry instance.

    Raises:
        RuntimeError: If not yet initialized.
    """
    if _platform_registry is None:
        raise RuntimeError(
            "PlatformRegistry not initialized. "
            "Call init_platform_singletons() during app startup."
        )
    return _platform_registry


def get_platform_gateway() -> Any:
    """Get the PlatformGateway singleton.

    Must be initialized during FastAPI lifespan startup via
    init_platform_singletons().

    Returns:
        The shared PlatformGateway instance.

    Raises:
        RuntimeError: If not yet initialized.
    """
    if _platform_gateway is None:
        raise RuntimeError(
            "PlatformGateway not initialized. "
            "Call init_platform_singletons() during app startup."
        )
    return _platform_gateway


def get_activation_service() -> Any:
    """Get the PlatformActivationService singleton.

    Must be initialized during FastAPI lifespan startup via
    init_platform_singletons().

    Returns:
        The shared PlatformActivationService instance.

    Raises:
        RuntimeError: If not yet initialized.
    """
    if _activation_service is None:
        raise RuntimeError(
            "PlatformActivationService not initialized. "
            "Call init_platform_singletons() during app startup."
        )
    return _activation_service


async def init_platform_singletons(duckdb_conn: Any = None) -> None:
    """Initialize platform singletons during app startup.

    Creates PlatformRegistry, PlatformGateway, and PlatformActivationService.
    Must be called once during FastAPI lifespan.

    Args:
        duckdb_conn: Optional DuckDB connection for activation service.
    """
    global _platform_registry, _platform_gateway, _activation_service
    async with _platform_lock:
        if _platform_registry is not None:
            return  # Already initialized

        from src.services.platform_registry import PlatformRegistry
        from src.services.platform_gateway import PlatformGateway
        from src.services.platform_activation_service import PlatformActivationService

        _platform_registry = PlatformRegistry()
        _platform_gateway = PlatformGateway(_platform_registry)
        _activation_service = PlatformActivationService(
            registry=_platform_registry,
            gateway=_platform_gateway,
            duckdb_conn=duckdb_conn,
        )
        logger.info("Platform singletons initialized (registry, gateway, activation)")


async def shutdown_platform_singletons() -> None:
    """Shutdown platform singletons. Call from FastAPI lifespan."""
    global _platform_registry, _platform_gateway, _activation_service
    async with _platform_lock:
        if _platform_gateway is not None:
            try:
                await _platform_gateway.shutdown()
            except Exception as e:
                logger.warning("Failed to shutdown PlatformGateway: %s", e)
            _platform_gateway = None
        _platform_registry = None
        _activation_service = None


async def check_gateway_health() -> dict[str, dict[str, str]]:
    """Probe connected MCP gateways for liveness. Non-blocking, best-effort.

    Returns:
        Dict mapping gateway name to status dict.
    """
    results: dict[str, dict[str, str]] = {}
    for name, client in [
        ("data_source", _data_gateway),
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
    """Shutdown hook — disconnect all gateway clients. Call from FastAPI lifespan.

    Acquires each gateway lock before setting to None to prevent race
    conditions with concurrent get_*_gateway() calls (H-5, CWE-362).
    """
    global _data_gateway, _ups_gateway
    invalidate_mapping_cache()

    async with _data_gateway_lock:
        if _data_gateway is not None:
            try:
                await _data_gateway.disconnect_mcp()
            except Exception as e:
                logger.warning("Failed to disconnect DataSourceMCPClient: %s", e)
            _data_gateway = None

    async with _ups_gateway_lock:
        if _ups_gateway is not None:
            try:
                await _ups_gateway.disconnect()
            except Exception as e:
                logger.warning("Failed to disconnect UPSMCPClient: %s", e)
            _ups_gateway = None
