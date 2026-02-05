"""FastAPI application for ShipAgent API.

Provides the main application instance with routers, middleware,
and exception handlers configured. Serves the React frontend build
when available.
"""

import logging
import sys
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

from src.api.routes import commands, jobs, labels, logs, platforms, preview, progress
from src.db.connection import init_db
from src.errors import ShipAgentError

# Frontend build directory
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

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


@app.on_event("startup")
def startup_event() -> None:
    """Initialize database on startup."""
    init_db()


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
app.include_router(commands.router, prefix="/api/v1")
app.include_router(labels.router, prefix="/api/v1")
app.include_router(preview.router, prefix="/api/v1")
app.include_router(progress.router, prefix="/api/v1")
app.include_router(platforms.router, prefix="/api/v1")


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
