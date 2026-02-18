"""FastAPI application for ShipAgent API.

Provides the main application instance with routers, middleware,
and exception handlers configured. Serves the React frontend build
when available.
"""

import asyncio
import json as _json
import logging
import os
import sys
import time as _time
import uuid
import warnings
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request

# Configure logging to stdout for uvicorn to capture
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Ensure our application loggers are captured
logging.getLogger("src").setLevel(logging.INFO)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.middleware.auth import maybe_require_api_key
from src.api.routes import (
    agent_audit,
    conversations,
    data_sources,
    jobs,
    labels,
    logs,
    platforms,
    preview,
    progress,
    saved_data_sources,
)
from src.db.connection import init_db
from src.db.models import JobStatus
from src.errors import ShipAgentError
from src.services.batch_engine import BatchEngine
from src.services.ups_mcp_client import UPSMCPClient

# Frontend build directory
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"
logger = logging.getLogger(__name__)

# Module-level state for health endpoint and watchdog
_startup_time: float = 0.0
_watchdog_service = None  # Set by watchdog startup in lifespan


def _parse_allowed_origins() -> list[str]:
    """Parse comma-separated CORS allowlist from ALLOWED_ORIGINS env var."""
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _ensure_agent_sdk_available() -> None:
    """Fail fast when backend is not running with the project virtualenv."""
    if os.environ.get("SHIPAGENT_SKIP_SDK_CHECK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        logger.warning("Skipping claude_agent_sdk availability check by configuration.")
        return
    try:
        import claude_agent_sdk  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name != "claude_agent_sdk":
            raise
        raise RuntimeError(
            "Missing required dependency 'claude_agent_sdk'. "
            "Start the backend with ./scripts/start-backend.sh "
            "or install deps with .venv/bin/python -m pip install -e '.[dev]'."
        ) from exc
    sdk_version = getattr(claude_agent_sdk, "__version__", "unknown")
    logger.info("Claude Agent SDK version: %s", sdk_version)


async def _process_watched_file(file_path: str, config) -> None:
    """Process a file detected by the watchdog.

    This is the callback passed to HotFolderService.start().
    It claims the file, imports it, runs the agent command,
    applies auto-confirm rules, and moves the file to processed/failed.

    Serialized globally via HotFolderService.processing_lock to prevent
    data-source gateway cross-contamination.

    Args:
        file_path: Path to the detected file.
        config: WatchFolderConfig for this directory.
    """
    from src.cli.auto_confirm import evaluate_auto_confirm
    from src.cli.config import AutoConfirmRules, load_config
    from src.services.gateway_provider import get_data_gateway

    global _watchdog_service
    if not _watchdog_service:
        return

    async with _watchdog_service.processing_lock:
        processing_path = _watchdog_service.claim_file(file_path)
        if not processing_path:
            return

        try:
            gw = await get_data_gateway()
            ext = processing_path.suffix.lower()
            if ext == ".csv":
                await gw.import_csv(file_path=str(processing_path))
            elif ext in (".xlsx", ".xls"):
                await gw.import_excel(file_path=str(processing_path))
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            from src.services.agent_session_manager import AgentSessionManager
            from src.services.conversation_handler import ensure_agent, process_message

            mgr = AgentSessionManager()
            session_id = str(uuid.uuid4())
            session = mgr.get_or_create_session(session_id)
            pending_job_id: str | None = None
            try:
                source_info = await gw.get_source_info_typed()
                await ensure_agent(session, source_info)
                async for event in process_message(session, config.command):
                    event_type = event.get("event")
                    data = event.get("data", {})

                    if event_type == "error":
                        raise RuntimeError(data.get("message", "Agent error"))

                    if event_type == "preview_ready":
                        pending_job_id = data.get("job_id")
                        logger.info(
                            "Watchdog: agent produced preview for job %s",
                            pending_job_id,
                        )
            finally:
                await mgr.stop_session_agent(session_id)
                mgr.remove_session(session_id)

            if pending_job_id and config.auto_confirm:
                from src.db.connection import get_db as get_db_session
                from src.db.models import Job, JobRow
                from src.services.batch_executor import execute_batch

                db = next(get_db_session())
                try:
                    job = db.query(Job).filter(Job.id == pending_job_id).first()
                    if not job or job.status != "pending":
                        logger.warning(
                            "Watchdog: job %s not pending (status=%s), skipping auto-confirm",
                            pending_job_id,
                            getattr(job, "status", "NOT FOUND"),
                        )
                    else:
                        _cfg_path = os.environ.get("SHIPAGENT_CONFIG_PATH")
                        global_config = load_config(config_path=_cfg_path)
                        global_rules = global_config.auto_confirm if global_config else AutoConfirmRules()
                        folder_rules = AutoConfirmRules(
                            enabled=True,
                            max_cost_cents=config.max_cost_cents or global_rules.max_cost_cents,
                            max_rows=config.max_rows or global_rules.max_rows,
                            max_cost_per_row_cents=global_rules.max_cost_per_row_cents,
                            allowed_services=global_rules.allowed_services,
                            require_valid_addresses=global_rules.require_valid_addresses,
                            allow_warnings=global_rules.allow_warnings,
                        )

                        rows = db.query(JobRow).filter(
                            JobRow.job_id == pending_job_id
                        ).all()
                        row_costs = [r.cost_cents or 0 for r in rows]

                        service_codes_set: set[str] = set()
                        for r in rows:
                            if r.order_data:
                                try:
                                    od = _json.loads(r.order_data)
                                    sc = od.get("service_code") or od.get("ServiceCode")
                                    if sc:
                                        service_codes_set.add(str(sc))
                                except (_json.JSONDecodeError, TypeError):
                                    pass

                        preview_data = {
                            "total_rows": len(rows),
                            "total_cost_cents": sum(row_costs),
                            "max_row_cost_cents": max(row_costs) if row_costs else 0,
                            "service_codes": list(service_codes_set),
                            "all_addresses_valid": False,
                            "has_address_warnings": True,
                        }
                        confirm_result = evaluate_auto_confirm(
                            rules=folder_rules,
                            preview=preview_data,
                        )

                        if confirm_result.approved:
                            logger.info(
                                "Watchdog: auto-confirm APPROVED job %s (%s)",
                                pending_job_id,
                                confirm_result.reason,
                            )
                            job.status = "running"
                            job.started_at = datetime.now(UTC).isoformat()
                            db.commit()

                            async def _watchdog_progress(
                                event_type: str, **kwargs: Any
                            ) -> None:
                                logger.info(
                                    "Watchdog progress [%s]: %s %s",
                                    pending_job_id, event_type, kwargs,
                                )

                            await execute_batch(
                                job_id=pending_job_id,
                                db_session=db,
                                on_progress=_watchdog_progress,
                            )
                        else:
                            logger.warning(
                                "Watchdog: auto-confirm REJECTED job %s — %s "
                                "(violations: %s)",
                                pending_job_id,
                                confirm_result.reason,
                                [v.message for v in confirm_result.violations],
                            )
                finally:
                    db.close()
            elif pending_job_id:
                logger.info(
                    "Watchdog: auto_confirm disabled for folder %s, "
                    "job %s stays pending",
                    config.path,
                    pending_job_id,
                )

            _watchdog_service.complete_file(processing_path)
            logger.info("Watchdog: completed processing %s", processing_path.name)

        except Exception as e:
            logger.exception("Watchdog: failed processing %s", processing_path.name)
            _watchdog_service.fail_file(processing_path, {
                "error": str(e),
                "file": str(file_path),
                "command": config.command,
            })


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    """Parse ISO8601 timestamp to UTC datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reap_orphan_pending_jobs(job_service: object) -> int:
    """Delete stale pending jobs with zero rows (crash leftovers)."""
    from src.services.job_service import JobService

    js: JobService = job_service  # type: ignore[assignment]
    raw_hours = os.environ.get("ORPHAN_JOB_REAPER_HOURS", "6")
    try:
        max_age_hours = float(raw_hours)
    except ValueError:
        max_age_hours = 6.0
    if max_age_hours <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    try:
        pending_jobs = js.list_jobs(status=JobStatus.pending, limit=500)
    except Exception as e:
        logger.warning("Failed listing pending jobs for orphan reaper: %s", e)
        return 0

    deleted = 0
    for job in pending_jobs:
        created_at = _parse_iso_timestamp(getattr(job, "created_at", None))
        if created_at is None or created_at > cutoff:
            continue
        try:
            rows = js.get_rows(job.id)
        except Exception:
            continue
        if rows:
            continue
        try:
            if js.delete_job(job.id):
                deleted += 1
        except Exception as e:
            logger.warning("Failed deleting orphan pending job %s: %s", job.id, e)
    return deleted


async def run_startup_recovery(db: object, job_service: object) -> None:
    """Run crash recovery on startup: recover in-flight rows, then clean staging.

    Order matters: recovery MUST run before staging cleanup, because recovery
    may need staging labels for verification. Cleanup only removes staging
    files for jobs with no in_flight/needs_review rows.

    Creates a temporary UPSMCPClient for recovery so track_package works.
    Falls back gracefully if UPS MCP is unavailable (rows stay in_flight
    for next restart attempt).

    Args:
        db: Database session.
        job_service: JobService instance for querying jobs and rows.
    """
    from src.services.job_service import JobService

    js: JobService = job_service  # type: ignore[assignment]

    # 0. Reap stale zero-row pending jobs (created before crash, never populated).
    try:
        deleted_orphans = _reap_orphan_pending_jobs(js)
        if deleted_orphans:
            logger.info("Orphan pending jobs reaped: %d", deleted_orphans)
    except Exception as e:
        logger.warning("Orphan pending job reaper failed (non-blocking): %s", e)

    # 1. Find interrupted jobs (running or paused)
    interrupted: list = []
    for st in (JobStatus.running,):
        try:
            interrupted.extend(js.list_jobs(status=st, limit=500))
        except Exception:
            pass  # Status may not exist in older schemas

    # 2. Recover in-flight rows for each interrupted job
    jobs_needing_recovery = []
    for job in interrupted:
        rows = js.get_rows(job.id)
        in_flight = [r for r in rows if r.status == "in_flight"]
        if in_flight:
            jobs_needing_recovery.append((job, rows))

    if jobs_needing_recovery:
        # Create a real UPS MCP client for recovery (track_package needs it)
        ups_client = None
        try:
            ups_client = UPSMCPClient()
            await ups_client.connect()
        except Exception as e:
            logger.warning(
                "UPS MCP unavailable for recovery (rows stay in_flight): %s", e,
            )
            ups_client = None

        for job, rows in jobs_needing_recovery:
            try:
                engine = BatchEngine(
                    ups_service=ups_client,
                    db_session=db,
                    account_number="",
                )
                recovery_result = await engine.recover_in_flight_rows(
                    job.id, rows,
                )
                logger.info(
                    "Job %s recovery: %d recovered, %d needs_review, %d unresolved",
                    job.id,
                    recovery_result["recovered"],
                    recovery_result["needs_review"],
                    recovery_result["unresolved"],
                )
                if recovery_result.get("details"):
                    logger.warning(
                        "Rows requiring operator review for job %s: %s",
                        job.id,
                        recovery_result["details"],
                    )
            except Exception as e:
                logger.error(
                    "Recovery failed for job %s (non-blocking): %s",
                    job.id, e,
                )

        # Clean up the temporary UPS client
        if ups_client is not None:
            try:
                await ups_client.disconnect()
            except Exception:
                pass

    # 3. Clean up orphaned staging labels (skips jobs with unresolved rows)
    try:
        orphans = BatchEngine.cleanup_staging(js)
        if orphans:
            logger.info("Cleaned up %d orphaned staging labels", orphans)
    except Exception as e:
        logger.error("Staging cleanup failed (non-blocking): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Async lifespan: startup recovery + shutdown cleanup."""
    global _startup_time, _watchdog_service

    from src.db.connection import get_db_context
    from src.services.gateway_provider import shutdown_gateways
    from src.services.job_service import JobService

    # --- Startup ---
    _startup_time = _time.time()
    _ensure_agent_sdk_available()
    warnings.filterwarnings("default", category=DeprecationWarning, module="claude_agent_sdk")

    # Fail fast if filter token secret is missing or too short
    from src.orchestrator.filter_config import validate_filter_config

    validate_filter_config()

    init_db()

    allow_multi_worker = os.environ.get("SHIPAGENT_ALLOW_MULTI_WORKER", "false").lower()
    if allow_multi_worker not in {"1", "true", "yes", "on"}:
        logger.warning(
            "ShipAgent runtime policy: single-worker mode only. "
            "Start uvicorn/gunicorn with one worker unless externalized "
            "shared state is configured. Set SHIPAGENT_ALLOW_MULTI_WORKER=true "
            "to suppress this warning."
        )

    queue_mode = os.environ.get("CONVERSATION_TASK_QUEUE_MODE", "memory").lower()
    if queue_mode in {"", "memory", "in-memory", "in_memory"}:
        logger.warning(
            "Conversation task queue mode is in-memory; pending agent responses "
            "are not crash-durable. Use an external queue for hard-failure durability."
        )

    # Run crash recovery (non-blocking — failures logged, not propagated)
    try:
        with get_db_context() as db:
            js = JobService(db)
            await run_startup_recovery(db, js)
    except Exception as e:
        logger.error("Startup recovery failed (non-blocking): %s", e)

    # Start watchdog if configured
    config_path = os.environ.get("SHIPAGENT_CONFIG_PATH")
    if config_path:
        from src.cli.config import load_config as _load_config
        cfg = _load_config(config_path=config_path)
        if cfg and cfg.watch_folders:
            from src.cli.watchdog_service import HotFolderService

            _watchdog_service = HotFolderService(configs=cfg.watch_folders)

            backlog = _watchdog_service.scan_existing_files()
            if backlog:
                logger.info("Found %d backlog files to process", len(backlog))
                for backlog_file in backlog:
                    resolved_parent = backlog_file.parent.resolve()
                    for wf_config in cfg.watch_folders:
                        resolved_config = Path(wf_config.path).resolve()
                        if resolved_parent == resolved_config:
                            asyncio.create_task(
                                _process_watched_file(str(backlog_file), wf_config)
                            )
                            break

            await _watchdog_service.start(process_callback=_process_watched_file)
            logger.info("Watchdog started with %d watch folders", len(cfg.watch_folders))

    yield

    # --- Shutdown ---
    if _watchdog_service:
        await _watchdog_service.stop()
        _watchdog_service = None

    await preview.shutdown_batch_runtime()
    await conversations.shutdown_conversation_runtime()
    await shutdown_gateways()


# Create FastAPI app with async lifespan for startup recovery + shutdown cleanup
app = FastAPI(
    title="ShipAgent API",
    description="Natural language interface for batch shipment processing",
    version="0.1.0",
    lifespan=lifespan,
)

# Optional API auth for /api/* when SHIPAGENT_API_KEY is configured.
app.middleware("http")(maybe_require_api_key)

# CORS allowlist is env-driven. If unset, CORS is disabled (same-origin only).
allowed_origins = _parse_allowed_origins()
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )


@app.exception_handler(ShipAgentError)
async def shipagent_error_handler(
    request: Request, exc: ShipAgentError
) -> JSONResponse:
    """Handle ShipAgentError exceptions with consistent format.

    Args:
        request: The incoming request.
        exc: The ShipAgentError exception.

    Returns:
        JSONResponse with error details.
    """
    return JSONResponse(
        status_code=400,
        content={
            "error_code": exc.code,
            "message": exc.message,
            "remediation": exc.remediation,
            "details": exc.details if exc.details else None,
        },
    )


# Include routers
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")
app.include_router(data_sources.router, prefix="/api/v1")
app.include_router(labels.router, prefix="/api/v1")
app.include_router(preview.router, prefix="/api/v1")
app.include_router(progress.router, prefix="/api/v1")
app.include_router(platforms.router, prefix="/api/v1")
app.include_router(saved_data_sources.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(agent_audit.router, prefix="/api/v1")


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint with system status.

    Returns all fields required by the CLI HealthStatus contract:
    status, version, uptime_seconds, active_jobs, watchdog_active, watch_folders.

    Returns:
        Dictionary with health status and metrics.
    """
    from src.db.connection import get_db as _get_db
    from src.db.models import Job, JobStatus

    uptime = int(_time.time() - _startup_time) if _startup_time else 0

    # Count active (running) jobs
    try:
        db = next(_get_db())
        active_jobs = db.query(Job).filter(Job.status == JobStatus.running.value).count()
        db.close()
    except Exception:
        active_jobs = 0

    # Version from package metadata (matches pyproject.toml)
    try:
        version = _pkg_version("shipagent")
    except Exception:
        version = "unknown"

    # Watchdog status
    watchdog_active = _watchdog_service is not None and getattr(_watchdog_service, "_observer", None) is not None
    watch_folders: list[str] = []
    if _watchdog_service and hasattr(_watchdog_service, "_configs"):
        watch_folders = [c.path for c in _watchdog_service._configs]

    return {
        "status": "healthy",
        "version": version,
        "uptime_seconds": uptime,
        "active_jobs": active_jobs,
        "watchdog_active": watchdog_active,
        "watch_folders": watch_folders,
    }


@app.get("/readyz")
def readiness_check():
    """Dependency-aware readiness check for local/container deployments."""
    from sqlalchemy import text

    from src.db.connection import get_db_context

    uptime = int(_time.time() - _startup_time) if _startup_time else 0
    checks: dict[str, dict[str, Any]] = {}

    # DB connectivity gate.
    try:
        with get_db_context() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "uptime_seconds": uptime,
                "checks": {
                    "database": {"status": "error", "message": str(exc)},
                },
            },
        )

    filter_secret = os.environ.get("FILTER_TOKEN_SECRET", "")
    if len(filter_secret) < 32:
        checks["filter_token_secret"] = {
            "status": "error",
            "message": "FILTER_TOKEN_SECRET missing or too short",
        }
        status = "degraded"
    else:
        checks["filter_token_secret"] = {"status": "ok"}
        status = "ready"

    missing_ups = [
        key
        for key in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ACCOUNT_NUMBER")
        if not os.environ.get(key)
    ]
    if missing_ups:
        checks["ups_credentials"] = {"status": "degraded", "missing": missing_ups}
        status = "degraded"
    else:
        checks["ups_credentials"] = {"status": "configured"}

    return {
        "status": status,
        "uptime_seconds": uptime,
        "checks": checks,
    }


@app.get("/api")
def api_root() -> dict:
    """API root with links to docs.

    Returns:
        Dictionary with API info and links.
    """
    return {
        "name": "ShipAgent API",
        "version": "0.1.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


# Static file serving and SPA fallback (must be AFTER API routes)
if FRONTEND_DIR.exists():
    # Serve static assets (JS, CSS, images)
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Serve other static files (vite.svg, etc.)
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve React SPA for all non-API routes.

        This enables client-side routing by returning index.html for all
        paths not handled by the API or static file mounts.

        Args:
            full_path: The requested path.

        Returns:
            FileResponse with index.html for SPA routing.
        """
        # Check if the path is an API or docs route (should be handled above)
        if full_path.startswith(
            ("api/", "docs", "redoc", "openapi.json", "health", "readyz")
        ):
            # This shouldn't be reached as those routes are defined above
            # but return 404 just in case
            return FileResponse(FRONTEND_DIR / "index.html")

        # Check if the path matches an actual file in dist
        requested_file = FRONTEND_DIR / full_path
        if requested_file.exists() and requested_file.is_file():
            return FileResponse(requested_file)

        # Default: serve index.html for SPA routing
        return FileResponse(FRONTEND_DIR / "index.html")
else:
    # No frontend build - serve API-only root
    @app.get("/")
    def root() -> dict:
        """API root when frontend is not built.

        Returns:
            Dictionary with API info and links.
        """
        return {
            "name": "ShipAgent API",
            "version": "0.1.0",
            "docs": "/docs",
            "redoc": "/redoc",
            "note": "Frontend not built. Run 'cd frontend && npm run build' to enable UI.",
        }
