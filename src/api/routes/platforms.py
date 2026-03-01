"""FastAPI routes for external platform integrations.

Provides REST API endpoints for managing connections to external platforms
via the federated PlatformGateway architecture.

All routes delegate to PlatformRegistry, PlatformGateway, and
PlatformActivationService singletons via gateway_provider.
"""

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from src.utils.redaction import sanitize_error_message

router = APIRouter(prefix="/platforms", tags=["platforms"])
logger = logging.getLogger(__name__)


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
    row_count: int = 0
    source_type: str | None = None
    error_code: str | None = None
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
    failed_platforms: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None


# === Platform Routes (federated architecture) ===


def _compat_mode_enabled() -> bool:
    """Whether compatibility rollback mode is enabled for activation semantics."""
    raw = os.environ.get("PLATFORM_ACTIVATION_COMPAT_MODE", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _source_is_query_ready(source_info: dict[str, Any] | None) -> bool:
    """Return True when current source info points to query-ready platform data."""
    if source_info is None:
        return False
    source_type = str(source_info.get("source_type", "") or "").strip().lower()
    if source_type == "external_orders":
        return True
    path = str(source_info.get("path", "") or "").strip().lower()
    if "imported_data" in path:
        return True
    return False


async def _verify_queryable_source_after_activation() -> tuple[bool, dict[str, Any] | None]:
    """Check that activation yielded a queryable platform source."""
    from src.services.gateway_provider import get_data_gateway

    try:
        gw = await get_data_gateway()
        source_info = await gw.get_source_info()
    except Exception:
        logger.warning("Platform activation source verification failed", exc_info=True)
        return False, None
    return _source_is_query_ready(source_info), source_info


def _candidate_activation_mode(summary: Any) -> str:
    """Choose activation mode based on prior sync state."""
    if summary.last_sync_row_count:
        return "refresh"
    status = str(summary.connection_status or "").strip().lower()
    if status in {"connected", "degraded", "auth_expired"}:
        return "refresh"
    return "initial"


def _activation_error_response(
    platform_id: str,
    err: Exception,
    *,
    error_code: str = "ACTIVATION_FAILED",
) -> PlatformActivateResponse:
    """Build sanitized error response for activation failures."""
    return PlatformActivateResponse(
        success=False,
        platform_id=platform_id,
        error_code=error_code,
        error=sanitize_error_message(f"Activation failed: {err}"),
    )


async def _activate_platform_and_verify(
    platform_id: str,
    credential_ref: str,
    mode: str,
) -> PlatformActivateResponse:
    """Activate a platform profile and verify queryable source readiness."""
    from src.services.gateway_provider import get_activation_service

    service = get_activation_service()
    logger.info(
        "platform_activation_start platform_id=%s credential_ref=%s mode=%s",
        platform_id,
        credential_ref,
        mode,
    )
    report = await service.activate_platform(
        platform_id=platform_id,
        credential_ref=credential_ref,
        mode=mode,
    )

    source_ok, source_info = await _verify_queryable_source_after_activation()
    source_type = (source_info or {}).get("source_type") if source_info else None
    row_count = int((source_info or {}).get("row_count", 0)) if source_info else 0

    logger.info(
        "platform_activation_done platform_id=%s credential_ref=%s mode=%s pages=%s imported=%s source_ok=%s source_type=%s row_count=%s",
        platform_id,
        credential_ref,
        report.mode,
        report.pages_fetched,
        report.total_imported,
        source_ok,
        source_type,
        row_count,
    )

    if not source_ok:
        return PlatformActivateResponse(
            success=False,
            platform_id=report.platform_id,
            mode=report.mode,
            total_imported=report.total_imported,
            pages_fetched=report.pages_fetched,
            watermark=report.watermark,
            duration_seconds=report.duration_seconds,
            row_count=row_count,
            source_type=source_type,
            error_code="SOURCE_NOT_READY",
            error=(
                "Platform synced but queryable source is not ready yet. "
                "Retry activation or refresh and verify source status."
            ),
        )

    return PlatformActivateResponse(
        success=True,
        platform_id=report.platform_id,
        mode=report.mode,
        total_imported=report.total_imported,
        pages_fetched=report.pages_fetched,
        watermark=report.watermark,
        duration_seconds=report.duration_seconds,
        row_count=row_count,
        source_type=str(source_type or "external_orders"),
    )


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
        from src.services.gateway_provider import get_platform_registry

        registry = get_platform_registry()
        config = registry.get_config(request.platform_id)
        if config is None:
            return PlatformActivateResponse(
                success=False,
                platform_id=request.platform_id,
                error_code="UNKNOWN_PLATFORM",
                error=f"Unknown platform: {request.platform_id}",
            )
        credential_ref = request.credential_ref or config.default_profile
        state = registry.get_state(request.platform_id, credential_ref)
        mode = "refresh" if state and (
            state.last_completed_watermark or state.last_sync_row_count
        ) else "initial"
        return await _activate_platform_and_verify(
            platform_id=request.platform_id,
            credential_ref=credential_ref,
            mode=mode,
        )
    except Exception as e:
        return _activation_error_response(request.platform_id, e)


@router.post("/refresh", response_model=PlatformActivateResponse)
async def refresh_platform(request: PlatformActivateRequest) -> PlatformActivateResponse:
    """Refresh a platform — incremental sync using watermark.

    Args:
        request: Platform ID and optional credential reference.

    Returns:
        Refresh report with import stats.
    """
    try:
        return await _activate_platform_and_verify(
            platform_id=request.platform_id,
            credential_ref=request.credential_ref or "primary",
            mode="refresh",
        )
    except Exception as e:
        return _activation_error_response(request.platform_id, e, error_code="REFRESH_FAILED")


@router.post("/shopify/activate", response_model=PlatformActivateResponse)
async def activate_shopify_compat() -> PlatformActivateResponse:
    """Compatibility endpoint for deterministic Shopify activation."""
    return await activate_platform(
        PlatformActivateRequest(platform_id="shopify"),
    )


@router.post("/amazon/activate", response_model=PlatformActivateResponse)
async def activate_amazon_compat() -> PlatformActivateResponse:
    """Compatibility endpoint for deterministic Amazon activation."""
    return await activate_platform(
        PlatformActivateRequest(platform_id="amazon"),
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
        from src.services.gateway_provider import get_activation_service, get_platform_registry

        registry = get_platform_registry()
        summaries = registry.get_platforms_summary()
        activation_service = get_activation_service() if _compat_mode_enabled() else None

        # Build lookup: platform_id → list of summaries (multi-profile safe)
        summaries_by_pid: dict[str, list[Any]] = {}
        for s in summaries:
            summaries_by_pid.setdefault(s.platform_id, []).append(s)

        requested_ids = set(request.active_platform_ids)
        rejected: list[dict[str, str]] = []

        # Statuses where the platform is already usable without credentials.
        _CONNECTED_STATUSES = frozenset({"connected", "degraded"})

        def _is_activatable(summary: Any) -> bool:
            """A profile is activatable if in a connected status or has credentials.

            Connected/degraded profiles are directly usable. Disconnected or
            auth_expired profiles can still be activated if credentials are
            available (the activation flow will re-connect automatically).
            """
            if summary.connection_status in _CONNECTED_STATUSES:
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

        # Compat mode guardrail: any newly activated platform must pass
        # deterministic activation + source verification before toggling active.
        failed_platforms: list[dict[str, str]] = []
        if _compat_mode_enabled():
            for pid in requested_ids:
                profiles = summaries_by_pid.get(pid, [])
                if not profiles:
                    continue
                already_active = any(bool(p.is_active) for p in profiles)
                if already_active:
                    continue

                candidates = [p for p in profiles if _is_activatable(p)]
                activated = False
                for candidate in candidates:
                    mode = _candidate_activation_mode(candidate)
                    try:
                        logger.info(
                            "platform_toggle_activation_start platform_id=%s credential_ref=%s mode=%s",
                            candidate.platform_id,
                            candidate.credential_ref,
                            mode,
                        )
                        report = await activation_service.activate_platform(
                            platform_id=candidate.platform_id,
                            credential_ref=candidate.credential_ref,
                            mode=mode,
                        )
                        source_ok, source_info = await _verify_queryable_source_after_activation()
                        logger.info(
                            "platform_toggle_activation_done platform_id=%s credential_ref=%s mode=%s pages=%s imported=%s source_ok=%s source_type=%s",
                            candidate.platform_id,
                            candidate.credential_ref,
                            report.mode,
                            report.pages_fetched,
                            report.total_imported,
                            source_ok,
                            (source_info or {}).get("source_type"),
                        )
                        if source_ok:
                            activated = True
                            break
                    except Exception as exc:
                        logger.warning(
                            "platform_toggle_activation_failed platform_id=%s credential_ref=%s mode=%s error=%s",
                            candidate.platform_id,
                            candidate.credential_ref,
                            mode,
                            sanitize_error_message(str(exc)),
                        )
                        continue

                if not activated:
                    failed_platforms.append({
                        "platform_id": pid,
                        "reason": "activation failed or source not query-ready",
                    })

        if failed_platforms:
            reasons = "; ".join(
                f"{item['platform_id']}: {item['reason']}" for item in failed_platforms
            )
            return SetActivePlatformsResponse(
                success=False,
                failed_platforms=failed_platforms,
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
                "last_sync_row_count": s.last_sync_row_count,
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
