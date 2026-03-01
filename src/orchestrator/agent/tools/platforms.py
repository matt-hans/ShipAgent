# src/orchestrator/agent/tools/platforms.py
"""Meta-platform agent tools — thin dispatchers for platform operations.

These tools replace `connect_shopify` and `get_platform_status` with
generic, registry-driven operations that work for any platform.

Each tool validates args, calls the appropriate service, and returns a
structured result dict with {success: bool, data?: ..., error?: str}.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# --- Service accessors ---
# These are module-level functions so they can be patched in tests.
# In production, they resolve to singleton instances from gateway_provider.


def get_platform_registry():
    """Get the PlatformRegistry singleton."""
    from src.services.gateway_provider import get_platform_registry as _get
    return _get()


def get_platform_gateway():
    """Get the PlatformGateway singleton."""
    from src.services.gateway_provider import get_platform_gateway as _get
    return _get()


def get_activation_service():
    """Get the PlatformActivationService singleton."""
    from src.services.gateway_provider import get_activation_service as _get
    return _get()


def _ok(data: Any = None) -> dict[str, Any]:
    """Build a success response."""
    result: dict[str, Any] = {"success": True}
    if data is not None:
        result["data"] = data
    return result


def _err(message: str) -> dict[str, Any]:
    """Build an error response."""
    return {"success": False, "error": message}


# --- Tool handlers ---


async def list_platforms_tool(args: dict[str, Any]) -> dict[str, Any]:
    """List all registered platforms with their connection status.

    Returns summary of each platform including connection state,
    credentials status, capabilities, and sync history.
    """
    try:
        registry = get_platform_registry()
        summaries = registry.get_platforms_summary()

        platforms = []
        for s in summaries:
            platforms.append({
                "platform_id": s.platform_id,
                "display_name": s.display_name,
                "credential_ref": s.credential_ref,
                "connection_status": s.connection_status,
                "enabled": s.enabled,
                "has_credentials": s.has_credentials,
                "health_ok": s.health_ok,
                "last_error": s.last_error,
                "last_sync_completed_at": str(s.last_sync_completed_at) if s.last_sync_completed_at else None,
                "last_sync_row_count": s.last_sync_row_count,
                "capabilities": s.capabilities,
                "account_label": s.account_label,
                "contract_version_ok": s.contract_version_ok,
                "capabilities_stale": s.capabilities_stale,
            })

        return _ok({"platforms": platforms, "total": len(platforms)})
    except Exception as e:
        logger.exception("list_platforms failed")
        return _err(f"Failed to list platforms: {e}")


async def activate_platform_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Activate a platform — full initial sync of orders into DuckDB.

    Connects to the platform, pages through all orders, normalizes them,
    and upserts into the external_orders table.
    """
    platform_id = args.get("platform_id")
    if not platform_id:
        return _err("platform_id is required")

    credential_ref = args.get("credential_ref")

    try:
        registry = get_platform_registry()
        config = registry.get_config(platform_id)
        if config is None:
            return _err(f"Unknown platform: {platform_id}")
        if not config.enabled:
            return _err(f"Platform {platform_id} is not enabled")

        if not credential_ref:
            credential_ref = config.default_profile

        service = get_activation_service()
        report = await service.activate_platform(
            platform_id=platform_id,
            credential_ref=credential_ref,
            mode="initial",
        )

        return _ok({
            "platform_id": report.platform_id,
            "credential_ref": report.credential_ref,
            "mode": report.mode,
            "total_imported": report.total_imported,
            "pages_fetched": report.pages_fetched,
            "watermark": report.watermark,
            "duration_seconds": report.duration_seconds,
            "warnings": report.warnings,
        })
    except Exception as e:
        logger.exception("activate_platform failed for %s", platform_id)
        return _err(f"Activation failed: {e}")


async def refresh_platform_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Refresh a platform — incremental sync using watermark.

    Only fetches orders updated since the last watermark, reducing
    API calls and import time.
    """
    platform_id = args.get("platform_id")
    if not platform_id:
        return _err("platform_id is required")

    credential_ref = args.get("credential_ref")

    try:
        registry = get_platform_registry()
        config = registry.get_config(platform_id)
        if config is None:
            return _err(f"Unknown platform: {platform_id}")

        if not credential_ref:
            credential_ref = config.default_profile

        service = get_activation_service()
        report = await service.activate_platform(
            platform_id=platform_id,
            credential_ref=credential_ref,
            mode="refresh",
        )

        return _ok({
            "platform_id": report.platform_id,
            "credential_ref": report.credential_ref,
            "mode": report.mode,
            "total_imported": report.total_imported,
            "pages_fetched": report.pages_fetched,
            "watermark": report.watermark,
            "duration_seconds": report.duration_seconds,
            "warnings": report.warnings,
        })
    except Exception as e:
        logger.exception("refresh_platform failed for %s", platform_id)
        return _err(f"Refresh failed: {e}")


async def refresh_all_platforms_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Refresh all connected platforms.

    Iterates through all platforms with active state and refreshes each one.
    Failures on individual platforms don't block others.
    """
    try:
        registry = get_platform_registry()
        states = registry.list_states()

        if not states:
            return _ok({"message": "No platforms to refresh", "results": []})

        results = []
        for state in states:
            try:
                service = get_activation_service()
                report = await service.activate_platform(
                    platform_id=state.platform_id,
                    credential_ref=state.credential_ref,
                    mode="refresh",
                )
                results.append({
                    "platform_id": report.platform_id,
                    "credential_ref": report.credential_ref,
                    "total_imported": report.total_imported,
                    "status": "ok",
                })
            except Exception as e:
                results.append({
                    "platform_id": state.platform_id,
                    "credential_ref": state.credential_ref,
                    "status": "error",
                    "error": str(e),
                })

        return _ok({"results": results, "total": len(results)})
    except Exception as e:
        logger.exception("refresh_all_platforms failed")
        return _err(f"Refresh all failed: {e}")


async def disconnect_platform_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Disconnect a platform — close the MCP connection and update state."""
    platform_id = args.get("platform_id")
    if not platform_id:
        return _err("platform_id is required")

    credential_ref = args.get("credential_ref")

    try:
        registry = get_platform_registry()
        config = registry.get_config(platform_id)
        if config is None:
            return _err(f"Unknown platform: {platform_id}")

        if not credential_ref:
            credential_ref = config.default_profile

        gateway = get_platform_gateway()
        await gateway.disconnect(platform_id, credential_ref)

        return _ok({"platform_id": platform_id, "status": "disconnected"})
    except Exception as e:
        logger.exception("disconnect_platform failed for %s", platform_id)
        return _err(f"Disconnect failed: {e}")


async def get_platform_capabilities_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get capabilities for a specific platform.

    Returns the platform's supported operations, limits, and paging config.
    """
    platform_id = args.get("platform_id")
    if not platform_id:
        return _err("platform_id is required")

    credential_ref = args.get("credential_ref")

    try:
        registry = get_platform_registry()
        config = registry.get_config(platform_id)
        if config is None:
            return _err(f"Unknown platform: {platform_id}")

        if not credential_ref:
            credential_ref = config.default_profile

        gateway = get_platform_gateway()
        caps = await gateway.call_tool(
            platform_id, credential_ref, "platform.capabilities", {},
        )

        return _ok(caps)
    except Exception as e:
        logger.exception("get_platform_capabilities failed for %s", platform_id)
        return _err(f"Failed to get capabilities: {e}")
