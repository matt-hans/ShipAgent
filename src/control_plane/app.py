import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.control_plane.auth import (
    Auth0TokenVerifier,
    AuthorizationService,
    ProviderClientRegistry,
    clear_authorization_context,
    set_authorization_context,
)
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.oauth_contract import (
    METADATA_PATH,
    ROOT_METADATA_PATH,
    canonical_mcp_resource,
    resource_metadata_url,
)
from src.control_plane.config import ControlPlaneSettings
from src.control_plane.db import build_session_factory
from src.control_plane.execution_targets import ExecutionTarget, RelayExecutionTarget
from src.control_plane.relay.invocations import RelayInvocationBroker
from src.control_plane.relay.registry import RelayDeviceRegistry
from src.control_plane.relay.routes import build_relay_router
from src.control_plane.request_controls import RequestControls
from src.control_plane.retention.tasks import ControlPlaneRetentionWorker
from src.control_plane.routes.oauth_metadata import build_metadata_router
from src.control_plane.startup import validate_startup_security
from src.hosted_mcp.execution_target_handlers import (
    build_execution_target_tool_handlers,
)
from src.hosted_mcp.server import build_server


@lru_cache
def _build_db_sessionmaker(database_url: str) -> async_sessionmaker[AsyncSession]:
    return build_session_factory(database_url)


def _build_redis_client(redis_url: str):
    return redis_from_url(redis_url, decode_responses=False)


def _metadata_url(settings: ControlPlaneSettings) -> str:
    if settings.public_base_url is None:
        raise RuntimeError("SHIPAGENT_PUBLIC_BASE_URL is required for OAuth metadata")
    return resource_metadata_url(str(settings.public_base_url))


def _bearer_challenge(
    settings: ControlPlaneSettings, *, mcp_request: bool = False
) -> dict[str, str]:
    scope = ', scope="shipagent.status"' if mcp_request else ""
    return {
        "WWW-Authenticate": f'Bearer resource_metadata="{_metadata_url(settings)}"{scope}'
    }


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    safe_errors: list[dict[str, object]] = []
    for err in exc.errors():
        safe_errors.append(
            {
                "type": err.get("type", "unknown"),
                "msg": "Invalid request field",
            }
        )
    return safe_errors


async def _resolve_authorization(
    settings: ControlPlaneSettings,
    principal: TokenPrincipal,
    db_session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    operation_deadline: float | None = None,
) -> AuthorizationContext:
    if operation_deadline is None:
        operation_deadline = time.monotonic() + 2.0
    client_registry = ProviderClientRegistry(settings.auth0_provider_clients)
    session_factory = db_session_factory or _build_db_sessionmaker(
        settings.database_url
    )
    async with session_factory() as session:
        service = AuthorizationService(session, client_registry)
        return await service.resolve(
            subject=principal.subject,
            client_id=principal.client_id,
            scopes=set(principal.scopes),
            auth_time=principal.auth_time,
            issuer=principal.issuer,
            issuer_link_id=principal.issuer_link_id,
            token_expires_at=principal.expires_at,
            operation_deadline=operation_deadline,
        )


@lru_cache
def _build_verifier(
    issuer: str, audience: str, provider_link_claim: str | None = None
) -> Auth0TokenVerifier:
    return Auth0TokenVerifier(
        issuer=issuer, audience=audience, provider_link_claim=provider_link_claim
    )


def create_control_plane_app(
    *,
    settings: ControlPlaneSettings | None = None,
    redis_client: Any | None = None,
    db_session_factory: async_sessionmaker[AsyncSession] | None = None,
    execution_target: ExecutionTarget | None = None,
    relay_registry: RelayDeviceRegistry | None = None,
    relay_invocation_broker: RelayInvocationBroker | None = None,
) -> FastAPI:
    settings = settings or ControlPlaneSettings()
    validate_startup_security(settings)
    if not settings.auth0_issuer:
        raise RuntimeError("SHIPAGENT_AUTH0_ISSUER must be set")
    if not settings.auth0_audience:
        raise RuntimeError("SHIPAGENT_AUTH0_AUDIENCE must be set")
    if not settings.public_base_url:
        raise RuntimeError("SHIPAGENT_PUBLIC_BASE_URL must be set")
    metadata_resource = canonical_mcp_resource(str(settings.public_base_url))
    if settings.auth0_audience != metadata_resource:
        raise ValueError(
            "SHIPAGENT_AUTH0_AUDIENCE must equal the canonical MCP resource"
        )

    redis_client = redis_client or _build_redis_client(settings.redis_url)
    db_session_factory = db_session_factory or _build_db_sessionmaker(
        settings.database_url
    )
    relay_registry = relay_registry or RelayDeviceRegistry(
        redis_client,
        db_session_factory=db_session_factory,
    )
    relay_invocation_broker = relay_invocation_broker or RelayInvocationBroker()
    execution_target = execution_target or RelayExecutionTarget(
        relay_registry,
        relay_invocation_broker,
    )
    mcp = build_server(
        tool_handlers=build_execution_target_tool_handlers(execution_target),
        request_controls=RequestControls(redis_client=redis_client),
        oauth_resource_metadata_url=_metadata_url(settings),
    )
    # Workflow continuity is target-owned. Do not retain transport sessions or
    # server-initiated streams that could outlive per-request authorization.
    mcp_app = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)
    retention_worker = ControlPlaneRetentionWorker(
        redis_client=redis_client,
        session_factory=db_session_factory,
        audit_retention_days=settings.audit_retention_days,
        enabled=settings.retention_background_tasks_enabled,
    )

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(app):
            await retention_worker.start()
            try:
                yield
            finally:
                await retention_worker.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.retention_worker = retention_worker
    verifier = (
        _build_verifier(
            settings.auth0_issuer,
            settings.auth0_audience,
            settings.auth0_provider_link_claim,
        )
        if settings.auth0_provider_link_claim is not None
        else _build_verifier(settings.auth0_issuer, settings.auth0_audience)
    )
    app.include_router(build_metadata_router(metadata_resource, settings.auth0_issuer))
    app.include_router(build_relay_router(relay_registry, relay_invocation_broker))
    app.mount("/mcp", mcp_app)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": _sanitize_validation_errors(exc)},
        )

    @app.middleware("http")
    async def _require_authorization(request: Request, call_next):
        if request.method == "GET" and request.url.path in {
            METADATA_PATH,
            ROOT_METADATA_PATH,
        }:
            return await call_next(request)

        challenge = _bearer_challenge(
            settings, mcp_request=request.url.path in {"/mcp", "/mcp/"}
        )

        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=challenge,
            )

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=challenge,
            )

        try:
            principal = verifier.verify(token)
            context = await _resolve_authorization(
                settings,
                principal,
                db_session_factory,
            )
            context_token = set_authorization_context(context)
            request.state.authorization = context
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=challenge,
            )
        try:
            if request.url.path in {"/mcp", "/mcp/"} and request.method in {
                "GET",
                "DELETE",
            }:
                return JSONResponse(
                    status_code=405,
                    content={"detail": "MCP transport sessions are not supported"},
                    headers={"Allow": "POST"},
                )
            return await call_next(request)
        finally:
            clear_authorization_context(context_token)

    return app
