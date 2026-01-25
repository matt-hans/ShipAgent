"""FastAPI application for ShipAgent API.

Provides the main application instance with routers, middleware,
and exception handlers configured.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import commands, jobs, labels, logs, progress
from src.db.connection import init_db
from src.errors import ShipAgentError

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
app.include_router(progress.router, prefix="/api/v1")


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint.

    Returns:
        Dictionary with health status.
    """
    return {"status": "healthy"}


@app.get("/")
def root() -> dict:
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
