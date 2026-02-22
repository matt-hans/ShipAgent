"""Shared types and constants for provider connection management.

Neutral module with no DB or service-layer imports. Used by ConnectionService,
runtime_credentials.py, and agent config.py.
"""

from dataclasses import dataclass, field


# --- Shared Constants ---

VALID_PROVIDERS: frozenset[str] = frozenset({"ups", "shopify"})

VALID_AUTH_MODES: dict[str, frozenset[str]] = {
    "ups": frozenset({"client_credentials"}),
    "shopify": frozenset({"legacy_token", "client_credentials_shopify"}),
}

VALID_ENVIRONMENTS: frozenset[str] = frozenset({"test", "production"})

VALID_STATUSES: frozenset[str] = frozenset({
    "configured", "validating", "connected",
    "disconnected", "error", "needs_reconnect",
})

SKIP_STATUSES: frozenset[str] = frozenset({"disconnected", "needs_reconnect"})

RUNTIME_USABLE_STATUSES: frozenset[str] = VALID_STATUSES - SKIP_STATUSES

# --- Credential allowlists (required/optional keys + max lengths) ---

CREDENTIAL_SCHEMAS: dict[str, dict[str, dict[str, int]]] = {
    "ups:client_credentials": {
        "required": {"client_id": 1024, "client_secret": 1024},
        "optional": {},
    },
    "shopify:legacy_token": {
        "required": {"access_token": 4096},
        "optional": {},
    },
    "shopify:client_credentials_shopify": {
        "required": {"client_id": 1024, "client_secret": 1024},
        "optional": {"access_token": 4096},
    },
}


# --- Credential Dataclasses ---


@dataclass(frozen=True)
class UPSCredentials:
    """Typed credentials for UPS OAuth client_credentials."""

    client_id: str
    client_secret: str
    environment: str
    base_url: str


@dataclass(frozen=True)
class ShopifyLegacyCredentials:
    """Typed credentials for Shopify legacy admin custom app token."""

    access_token: str
    store_domain: str


@dataclass(frozen=True)
class ShopifyClientCredentials:
    """Typed credentials for Shopify Dev Dashboard client_credentials."""

    client_id: str
    client_secret: str
    store_domain: str
    access_token: str = field(default="")


# --- Validation Error ---


class ConnectionValidationError(Exception):
    """Typed validation error with structured error code.

    API routes map this to 400 with {"error": {"code": e.code, "message": e.message}}.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
