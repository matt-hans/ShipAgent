"""FastAPI routes for external platform integrations.

Provides REST API endpoints for managing connections to external platforms
via the federated PlatformGateway architecture.

All routes delegate to PlatformRegistry, PlatformGateway, and
PlatformActivationService singletons via gateway_provider.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/platforms", tags=["platforms"])


# === Request/Response Schemas ===


class PlatformListResponse(BaseModel):
    """Response from listing all registered platforms."""

    success: bool
    platforms: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    error: str | None = None


class PlatformActivateRequest(BaseModel):
    """Request body for platform activation."""

    platform_id: str = Field(..., description="Platform identifier (e.g., 'shopify')")
    credential_ref: str | None = Field(None, description="Credential profile name")


class PlatformActivateResponse(BaseModel):
    """Response from platform activation."""

    success: bool
    platform_id: str | None = None
    mode: str | None = None
    total_imported: int = 0
    pages_fetched: int = 0
    watermark: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


class PlatformStatusResponse(BaseModel):
    """Detailed status for a single platform."""

    success: bool
    platform_id: str | None = None
    display_name: str | None = None
    connection_status: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    last_sync_row_count: int | None = None
    error: str | None = None


class PlatformDisconnectRequest(BaseModel):
    """Request body for platform disconnection."""

    platform_id: str = Field(..., description="Platform identifier")
    credential_ref: str | None = Field(None, description="Credential profile name")


class SetActivePlatformsRequest(BaseModel):
    """Request body for setting active platforms."""

    active_platform_ids: list[str] = Field(
        ..., description="Platform IDs to set as active"
    )


class SetActivePlatformsResponse(BaseModel):
    """Response from setting active platforms."""

    success: bool
    active_platforms: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


# === Platform Routes (federated architecture) ===


@router.get("/", response_model=PlatformListResponse)
async def list_platforms() -> PlatformListResponse:
    """List all registered platforms with connection status.

    Uses PlatformRegistry to return summary of each platform.

    Returns:
        List of platform summaries with connection state.
    """
    try:
        from src.services.gateway_provider import get_platform_registry

        registry = get_platform_registry()
        summaries = registry.get_platforms_summary()
        platforms = []
        for s in summaries:
            platforms.append({
                "platform_id": s.platform_id,
                "display_name": s.display_name,
                "connection_status": s.connection_status,
                "enabled": s.enabled,
                "has_credentials": s.has_credentials,
                "health_ok": s.health_ok,
                "last_sync_row_count": s.last_sync_row_count,
                "capabilities": s.capabilities,
                "account_label": s.account_label,
                "is_active": s.is_active,
            })
        return PlatformListResponse(
            success=True,
            platforms=platforms,
            total=len(platforms),
        )
    except RuntimeError:
        # Platform singletons not initialized
        return PlatformListResponse(
            success=True,
            platforms=[],
            total=0,
        )
    except Exception as e:
        return PlatformListResponse(
            success=False,
            error=f"Failed to list platforms: {e}",
        )


@router.post("/activate", response_model=PlatformActivateResponse)
async def activate_platform(request: PlatformActivateRequest) -> PlatformActivateResponse:
    """Activate a platform — full initial sync of orders into DuckDB.

    Args:
        request: Platform ID and optional credential reference.

    Returns:
        Activation report with import stats.
    """
    try:
        from src.services.gateway_provider import get_activation_service

        service = get_activation_service()
        report = await service.activate_platform(
            platform_id=request.platform_id,
            credential_ref=request.credential_ref or "primary",
            mode="initial",
        )
        return PlatformActivateResponse(
            success=True,
            platform_id=report.platform_id,
            mode=report.mode,
            total_imported=report.total_imported,
            pages_fetched=report.pages_fetched,
            watermark=report.watermark,
            duration_seconds=report.duration_seconds,
        )
    except Exception as e:
        return PlatformActivateResponse(
            success=False,
            platform_id=request.platform_id,
            error=f"Activation failed: {e}",
        )


@router.post("/refresh", response_model=PlatformActivateResponse)
async def refresh_platform(request: PlatformActivateRequest) -> PlatformActivateResponse:
    """Refresh a platform — incremental sync using watermark.

    Args:
        request: Platform ID and optional credential reference.

    Returns:
        Refresh report with import stats.
    """
    try:
        from src.services.gateway_provider import get_activation_service

        service = get_activation_service()
        report = await service.activate_platform(
            platform_id=request.platform_id,
            credential_ref=request.credential_ref or "primary",
            mode="refresh",
        )
        return PlatformActivateResponse(
            success=True,
            platform_id=report.platform_id,
            mode=report.mode,
            total_imported=report.total_imported,
            pages_fetched=report.pages_fetched,
            watermark=report.watermark,
            duration_seconds=report.duration_seconds,
        )
    except Exception as e:
        return PlatformActivateResponse(
            success=False,
            platform_id=request.platform_id,
            error=f"Refresh failed: {e}",
        )


@router.post("/disconnect-platform", response_model=dict)
async def disconnect_platform_generic(
    request: PlatformDisconnectRequest,
) -> dict:
    """Disconnect a platform via PlatformGateway.

    Args:
        request: Platform ID and optional credential reference.

    Returns:
        Success status.
    """
    try:
        from src.services.gateway_provider import get_platform_gateway

        gateway = get_platform_gateway()
        await gateway.disconnect(request.platform_id, request.credential_ref or "primary")
        return {"success": True, "platform_id": request.platform_id, "status": "disconnected"}
    except Exception as e:
        return {"success": False, "error": f"Disconnect failed: {e}"}


@router.get("/status/{platform_id}", response_model=PlatformStatusResponse)
async def get_platform_status_detail(platform_id: str) -> PlatformStatusResponse:
    """Get detailed status and capabilities for a specific platform.

    Args:
        platform_id: Platform identifier.

    Returns:
        Detailed platform status with capabilities.
    """
    try:
        from src.services.gateway_provider import get_platform_registry

        registry = get_platform_registry()
        summaries = registry.get_platforms_summary()
        for s in summaries:
            if s.platform_id == platform_id:
                return PlatformStatusResponse(
                    success=True,
                    platform_id=s.platform_id,
                    display_name=s.display_name,
                    connection_status=s.connection_status,
                    capabilities=s.capabilities or [],
                    last_sync_row_count=s.last_sync_row_count,
                )
        return PlatformStatusResponse(
            success=False,
            platform_id=platform_id,
            error=f"Platform {platform_id} not found",
        )
    except RuntimeError:
        return PlatformStatusResponse(
            success=False,
            platform_id=platform_id,
            error="Platform singletons not initialized",
        )
    except Exception as e:
        return PlatformStatusResponse(
            success=False,
            platform_id=platform_id,
            error=f"Failed to get status: {e}",
        )


@router.patch("/active", response_model=SetActivePlatformsResponse)
async def set_active_platforms(
    request: SetActivePlatformsRequest,
) -> SetActivePlatformsResponse:
    """Set which platforms are active data sources.

    Platforms in the list are set active; all others are deactivated.
    Only profiles that are connected or have credentials can be activated.
    A platform_id is rejected only if ALL its profiles fail validation.

    Args:
        request: Contains list of platform IDs to activate.

    Returns:
        Updated list of active platforms.
    """
    try:
        from src.services.gateway_provider import get_platform_registry

        registry = get_platform_registry()
        summaries = registry.get_platforms_summary()

        # Build lookup: platform_id → list of summaries (multi-profile safe)
        summaries_by_pid: dict[str, list[Any]] = {}
        for s in summaries:
            summaries_by_pid.setdefault(s.platform_id, []).append(s)

        requested_ids = set(request.active_platform_ids)
        rejected: list[dict[str, str]] = []

        def _is_activatable(summary: Any) -> bool:
            """A profile is activatable if connected or has credentials."""
            if summary.connection_status != "disconnected":
                return True
            return summary.has_credentials

        # Validate: each requested platform_id must have at least one
        # activatable profile. Reject only if ALL profiles fail.
        for pid in requested_ids:
            profiles = summaries_by_pid.get(pid)
            if profiles is None:
                rejected.append({"platform_id": pid, "reason": "unknown platform"})
                continue
            if not any(_is_activatable(p) for p in profiles):
                rejected.append({
                    "platform_id": pid,
                    "reason": "not connected and no credentials available",
                })

        if rejected:
            reasons = "; ".join(
                f"{r['platform_id']}: {r['reason']}" for r in rejected
            )
            return SetActivePlatformsResponse(
                success=False,
                error=f"Cannot activate: {reasons}",
            )

        # Activate/deactivate per-profile: only activate activatable profiles
        # for requested platforms; deactivate everything else.
        for summary in summaries:
            if summary.platform_id in requested_ids:
                should_be_active = _is_activatable(summary)
            else:
                should_be_active = False
            registry.set_platform_active(
                summary.platform_id, summary.credential_ref, should_be_active,
            )

        # Return updated active platforms
        active_summaries = registry.get_active_platforms()
        active_list = [
            {
                "platform_id": s.platform_id,
                "display_name": s.display_name,
                "connection_status": s.connection_status,
                "credential_ref": s.credential_ref,
                "is_active": s.is_active,
            }
            for s in active_summaries
        ]
        return SetActivePlatformsResponse(
            success=True,
            active_platforms=active_list,
        )
    except RuntimeError:
        return SetActivePlatformsResponse(
            success=False,
            error="Platform singletons not initialized",
        )
    except Exception as e:
        return SetActivePlatformsResponse(
            success=False,
            error=f"Failed to set active platforms: {e}",
        )
