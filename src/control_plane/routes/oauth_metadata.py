"""Public protected-resource discovery; management scopes stay private."""

from fastapi import APIRouter

from src.control_plane.auth.oauth_contract import (
    METADATA_PATH,
    PUBLIC_SCOPES,
    ROOT_METADATA_PATH,
)

# Retained for existing imports of the public metadata vocabulary.
SUPPORTED_SCOPES = PUBLIC_SCOPES


def build_metadata_router(resource: str, issuer: str) -> APIRouter:
    router = APIRouter()

    @router.get(METADATA_PATH)
    @router.get(ROOT_METADATA_PATH)
    async def protected_resource_metadata() -> dict[str, object]:
        return {
            "resource": resource,
            "authorization_servers": [issuer.rstrip("/") + "/"],
            "scopes_supported": SUPPORTED_SCOPES,
            "bearer_methods_supported": ["header"],
        }

    return router
