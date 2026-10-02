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
from src.control_plane.config import ControlPlaneSettings
from src.control_plane.db import build_session_factory
from src.control_plane.execution_targets import ExecutionTarget, RelayExecutionTarget
from src.control_plane.relay.invocations import RelayInvocationBroker
from src.control_plane.relay.registry import RelayDeviceRegistry
from src.control_plane.relay.routes import build_relay_router
from src.control_plane.request_controls import RequestControls
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
    return f"{str(settings.public_base_url).rstrip('/')}/.well-known/oauth-protected-resource"


def _bearer_challenge(settings: ControlPlaneSettings) -> dict[str, str]:
    return {
        "WWW-Authenticate": (
            f'Bearer resource_metadata="{_metadata_url(settings)}"'
        )
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
) -> AuthorizationContext:
    client_registry = ProviderClientRegistry(settings.auth0_provider_clients)
    session_factory = db_session_factory or _build_db_sessionmaker(settings.database_url)
    async with session_factory() as session:
        service = AuthorizationService(session, client_registry)
        return await service.resolve(
            subject=principal.subject,
            client_id=principal.client_id,
            scopes=set(principal.scopes),
            auth_time=principal.auth_time,
        )


@lru_cache
def _build_verifier(issuer: str, audience: str) -> Auth0TokenVerifier:
    return Auth0TokenVerifier(issuer=issuer, audience=audience)


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
    )
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    app = FastAPI(lifespan=mcp_app.lifespan)
    verifier = _build_verifier(settings.auth0_issuer, settings.auth0_audience)
    metadata_resource = str(settings.public_base_url).rstrip("/")
    app.include_router(
        build_metadata_router(metadata_resource, settings.auth0_issuer)
    )
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
        if request.url.path.startswith("/.well-known/oauth-protected-resource"):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=_bearer_challenge(settings),
            )

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers=_bearer_challenge(settings),
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
                headers=_bearer_challenge(settings),
            )
        try:
            return await call_next(request)
        finally:
            clear_authorization_context(context_token)

    return app
