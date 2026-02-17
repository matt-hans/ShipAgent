"""FastAPI application for ShipAgent API.

Provides the main application instance with routers, middleware,
and exception handlers configured. Serves the React frontend build
when available.
"""

import logging
import os
import sys
import time as _time
import warnings
from importlib.metadata import version as _pkg_version
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


@app.on_event("startup")
def startup_event() -> None:
    """Initialize database on startup."""
    global _startup_time
    _startup_time = _time.time()
    _ensure_agent_sdk_available()
    warnings.filterwarnings("default", category=DeprecationWarning, module="claude_agent_sdk")
    init_db()
    allow_multi_worker = os.environ.get("SHIPAGENT_ALLOW_MULTI_WORKER", "false").lower()
    if allow_multi_worker not in {"1", "true", "yes", "on"}:
        logger.warning(
            (
                "ShipAgent runtime policy: single-worker mode only. "
                "Start uvicorn/gunicorn with one worker unless externalized "
                "shared state is configured. Set SHIPAGENT_ALLOW_MULTI_WORKER=true "
                "to suppress this warning."
            ),
        )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Clean up shared async resources on shutdown."""
    from src.services.gateway_provider import shutdown_gateways

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
