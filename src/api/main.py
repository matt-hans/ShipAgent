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
from datetime import UTC, datetime
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

from src.api.routes import (
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
from src.errors import ShipAgentError

# Frontend build directory
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"
logger = logging.getLogger(__name__)

# Module-level state for health endpoint
_startup_time: float = 0.0
_watchdog_service = None  # Set by watchdog startup in lifespan

# Create FastAPI app
app = FastAPI(
    title="ShipAgent API",
    description="Natural language interface for batch shipment processing",
    version="0.1.0",
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_agent_sdk_available() -> None:
    """Fail fast when backend is not running with the project virtualenv."""
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


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize database and start watchdog if configured."""
    global _startup_time, _watchdog_service

    _startup_time = _time.time()
    _ensure_agent_sdk_available()
    warnings.filterwarnings("default", category=DeprecationWarning, module="claude_agent_sdk")
    init_db()

    allow_multi_worker = os.environ.get("SHIPAGENT_ALLOW_MULTI_WORKER", "false").lower()
    if allow_multi_worker not in {"1", "true", "yes", "on"}:
        logger.warning(
            "ShipAgent runtime policy: single-worker mode only. "
            "Start uvicorn/gunicorn with one worker unless externalized "
            "shared state is configured. Set SHIPAGENT_ALLOW_MULTI_WORKER=true "
            "to suppress this warning."
        )

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


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Clean up watchdog and MCP gateways on shutdown."""
    global _watchdog_service
    from src.services.gateway_provider import shutdown_gateways

    if _watchdog_service:
        await _watchdog_service.stop()
        _watchdog_service = None

    await shutdown_gateways()


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
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
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
