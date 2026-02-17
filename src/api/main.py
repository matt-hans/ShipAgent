"""FastAPI application for ShipAgent API.

Provides the main application instance with routers, middleware,
and exception handlers configured. Serves the React frontend build
when available.
"""

import logging
import os
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

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
from src.db.models import JobStatus
from src.errors import ShipAgentError
from src.services.batch_engine import BatchEngine
from src.services.ups_mcp_client import UPSMCPClient

# Frontend build directory
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"
logger = logging.getLogger(__name__)


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
    from src.db.connection import get_db_context
    from src.services.gateway_provider import shutdown_gateways
    from src.services.job_service import JobService

    # --- Startup ---
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

    # Run crash recovery (non-blocking — failures logged, not propagated)
    try:
        with get_db_context() as db:
            js = JobService(db)
            await run_startup_recovery(db, js)
    except Exception as e:
        logger.error("Startup recovery failed (non-blocking): %s", e)

    yield

    # --- Shutdown ---
    await shutdown_gateways()


# Create FastAPI app with async lifespan for startup recovery + shutdown cleanup
app = FastAPI(
    title="ShipAgent API",
    description="Natural language interface for batch shipment processing",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint.

    Returns:
        Dictionary with health status.
    """
    return {"status": "healthy"}


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
