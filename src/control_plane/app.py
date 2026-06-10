from functools import lru_cache

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from src.control_plane.hosted_mcp.server import build_server
from src.control_plane.request_controls import RequestControls
from src.control_plane.routes.oauth_metadata import build_metadata_router
from src.control_plane.startup import validate_startup_security


@lru_cache
def _build_db_sessionmaker(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


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


def _build_request_controls(settings: ControlPlaneSettings) -> RequestControls:
    return RequestControls(redis_client=_build_redis_client(settings.redis_url))


async def _resolve_authorization(
    settings: ControlPlaneSettings,
    principal: TokenPrincipal,
) -> AuthorizationContext:
    client_registry = ProviderClientRegistry(settings.auth0_provider_clients)
    async with _build_db_sessionmaker(settings.database_url)() as session:
        service = AuthorizationService(session, client_registry)
        return await service.resolve(
            subject=principal.subject,
            client_id=principal.client_id,
            scopes=set(principal.scopes),
        )


@lru_cache
def _build_verifier(issuer: str, audience: str) -> Auth0TokenVerifier:
    return Auth0TokenVerifier(issuer=issuer, audience=audience)


def create_control_plane_app() -> FastAPI:
    settings = ControlPlaneSettings()
    validate_startup_security(settings)
    if not settings.auth0_issuer:
        raise RuntimeError("SHIPAGENT_AUTH0_ISSUER must be set")
    if not settings.auth0_audience:
        raise RuntimeError("SHIPAGENT_AUTH0_AUDIENCE must be set")
    if not settings.public_base_url:
        raise RuntimeError("SHIPAGENT_PUBLIC_BASE_URL must be set")

    mcp = build_server(request_controls=_build_request_controls(settings))
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    app = FastAPI(lifespan=mcp_app.lifespan)
    verifier = _build_verifier(settings.auth0_issuer, settings.auth0_audience)
    metadata_resource = str(settings.public_base_url).rstrip("/")
    app.include_router(
        build_metadata_router(metadata_resource, settings.auth0_issuer)
    )
    app.mount("/mcp", mcp_app)

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
            context = await _resolve_authorization(settings, principal)
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
