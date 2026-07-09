from typing import Final

from fastapi import APIRouter

SUPPORTED_SCOPES: Final = [
    "shipagent.status",
    "shipments:preview",
    "shipments:create",
    "jobs:read",
    "labels:read",
    "relay:device:manage",
    "relay:manage",
]


def build_metadata_router(resource: str, issuer: str) -> APIRouter:
    router = APIRouter()

    @router.get("/.well-known/oauth-protected-resource")
    async def protected_resource_metadata() -> dict[str, object]:
        return {
            "resource": resource,
            "authorization_servers": [issuer.rstrip("/") + "/"],
            "scopes_supported": SUPPORTED_SCOPES,
            "bearer_methods_supported": ["header"],
        }

    return router
