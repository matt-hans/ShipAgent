"""Runtime credential adapter — single contract for credential resolution.

All call sites use this module to resolve provider credentials at runtime.
Resolution order: DB (encrypted) → env var fallback → None.
"""

import logging
import os
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from src.services.connection_types import (
    ShopifyClientCredentials,
    ShopifyLegacyCredentials,
    UPSCredentials,
)

logger = logging.getLogger(__name__)

_UPS_BASE_URLS = {
    "test": "https://wwwcie.ups.com",
    "production": "https://onlinetools.ups.com",
}

# Per-process flags to avoid spamming fallback warnings.
_ups_fallback_warned: bool = False
_shopify_fallback_warned: bool = False


def resolve_ups_credentials(
    *,
    environment: str = "production",
    db: Session | None = None,
    key_dir: str | None = None,
) -> UPSCredentials | None:
    """Resolve UPS credentials with DB priority, env fallback.

    Args:
        environment: 'test' or 'production'.
        db: SQLAlchemy session (optional — acquires one if None).
        key_dir: Encryption key directory (optional).

    Returns:
        UPSCredentials or None if unavailable.
    """
    global _ups_fallback_warned

    # Try DB first
    if db is not None:
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db, key_dir=key_dir)
        result = service.get_ups_credentials(environment)
        if result is not None:
            return result

    # Env fallback
    client_id = os.environ.get("UPS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("UPS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    if not _ups_fallback_warned:
        logger.warning(
            "UPS credentials resolved from env vars (provider=ups, env=%s). "
            "Configure in Settings for persistent storage.",
            environment,
        )
        _ups_fallback_warned = True

    base_url = _UPS_BASE_URLS.get(environment, _UPS_BASE_URLS["production"])

    # Check for UPS_BASE_URL mismatch
    env_base_url = os.environ.get("UPS_BASE_URL", "").strip()
    if env_base_url and env_base_url != base_url:
        logger.warning(
            "UPS base URL mismatch: UPS_BASE_URL=%s but environment=%s implies %s",
            env_base_url, environment, base_url,
        )

    return UPSCredentials(
        client_id=client_id,
        client_secret=client_secret,
        environment=environment,
        base_url=base_url,
    )


def _normalize_domain_simple(raw: str) -> str:
    """Normalize a domain string for comparison (lowercase, strip protocol/slash)."""
    raw = raw.strip().lower()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        raw = parsed.hostname or raw
    return raw.rstrip("/")


def resolve_shopify_credentials(
    *,
    store_domain: str | None = None,
    db: Session | None = None,
    key_dir: str | None = None,
) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None:
    """Resolve Shopify credentials with DB priority, env fallback.

    Args:
        store_domain: Shopify store domain (optional — uses first available if None).
        db: SQLAlchemy session (optional — acquires one if None).
        key_dir: Encryption key directory (optional).

    Returns:
        ShopifyLegacyCredentials, ShopifyClientCredentials, or None.
    """
    global _shopify_fallback_warned

    # Try DB first
    if db is not None:
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db, key_dir=key_dir)
        if store_domain:
            result = service.get_shopify_credentials(store_domain)
        else:
            result = service.get_first_shopify_credentials()

        if result is not None:
            # Filter out empty access_token (client_credentials_shopify without token)
            if isinstance(result, ShopifyClientCredentials) and not result.access_token:
                pass  # Fall through to env
            elif isinstance(result, ShopifyLegacyCredentials) and not result.access_token:
                pass  # Fall through to env
            else:
                return result

    # Env fallback
    env_token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    env_domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "").strip()
    if not env_token:
        return None

    # Domain-matched env fallback
    if store_domain:
        if not env_domain:
            return None
        requested = _normalize_domain_simple(store_domain)
        env_normalized = _normalize_domain_simple(env_domain)
        if requested != env_normalized:
            logger.warning(
                "Requested store %s but env has %s — skipping env fallback",
                requested, env_normalized,
            )
            return None

    if not _shopify_fallback_warned:
        logger.warning(
            "Shopify credentials resolved from env vars. "
            "Configure in Settings for persistent storage.",
        )
        _shopify_fallback_warned = True

    return ShopifyLegacyCredentials(
        access_token=env_token,
        store_domain=env_domain or (store_domain or ""),
    )
