"""Runtime credential adapter — single contract for credential resolution.

All call sites use this module to resolve provider credentials at runtime.
Resolution order: DB (encrypted) → env var fallback → None.

When ``db`` is not passed, the resolver auto-acquires a short-lived
session via ``SessionLocal`` so that call sites outside request scope
(agent tools, gateway provider, batch executor) still read DB credentials.
"""

import logging
import os
from urllib.parse import urlparse

from sqlalchemy.exc import OperationalError
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

# Per-process flags to avoid spamming warnings.
_ups_fallback_warned: bool = False
_shopify_fallback_warned: bool = False
_ups_dual_env_warned: bool = False


def _try_db_ups(db: Session, key_dir: str | None, environment: str) -> UPSCredentials | None:
    """Attempt to resolve UPS credentials from the DB."""
    from src.services.connection_service import ConnectionService

    service = ConnectionService(db=db, key_dir=key_dir)
    return service.get_ups_credentials(environment)


def _derive_preferred_env() -> str:
    """Derive the preferred UPS environment from UPS_BASE_URL env var.

    Returns 'test' if UPS_BASE_URL contains 'wwwcie', otherwise 'production'.
    """
    env_base_url = os.environ.get("UPS_BASE_URL", "").strip()
    if "wwwcie" in env_base_url:
        return "test"
    return "production"


def _db_lookup_ups(
    db: Session, key_dir: str | None, environment: str | None,
) -> UPSCredentials | None:
    """Run UPS DB lookup logic on a given session.

    When environment is None, uses the preferred env first, then the
    alternate. Logs a warning when both environments have credentials.
    """
    preferred = _derive_preferred_env()

    if environment is not None:
        return _try_db_ups(db, key_dir, environment)

    # Auto-select: try preferred env first, then alternate
    first_env = preferred
    second_env = "test" if preferred == "production" else "production"

    result = _try_db_ups(db, key_dir, first_env)
    alt_result = _try_db_ups(db, key_dir, second_env)

    if result is not None and alt_result is not None:
        global _ups_dual_env_warned
        if not _ups_dual_env_warned:
            logger.warning(
                "UPS credentials found for both '%s' and '%s' environments. "
                "Auto-selected '%s' (derived from UPS_BASE_URL). "
                "Pass environment= explicitly to override.",
                first_env, second_env, first_env,
            )
            _ups_dual_env_warned = True
        return result

    if result is not None:
        return result
    return alt_result


def resolve_ups_credentials(
    *,
    environment: str | None = None,
    db: Session | None = None,
    key_dir: str | None = None,
) -> UPSCredentials | None:
    """Resolve UPS credentials with DB priority, env fallback.

    Args:
        environment: 'test' or 'production'. When None, auto-selects using
            the UPS_BASE_URL env var to determine preferred environment.
            Logs a warning if both test and production credentials exist.
        db: SQLAlchemy session. When None a short-lived session is
            auto-acquired so DB credentials are always checked.
        key_dir: Encryption key directory (optional).

    Returns:
        UPSCredentials or None if unavailable.
    """
    global _ups_fallback_warned

    # --- DB lookup (auto-acquire session when not provided) ---
    if db is not None:
        result = _db_lookup_ups(db, key_dir, environment)
        if result is not None:
            return result
    else:
        try:
            from src.db.connection import SessionLocal

            auto_db = SessionLocal()
            try:
                result = _db_lookup_ups(auto_db, key_dir, environment)
                if result is not None:
                    return result
            finally:
                auto_db.close()
        except (ImportError, OperationalError) as exc:
            logger.warning(
                "Auto-acquire DB session failed (%s); proceeding to env fallback",
                type(exc).__name__,
            )
        except Exception:
            logger.warning(
                "Unexpected error auto-acquiring DB session; proceeding to env fallback",
                exc_info=True,
            )

    # --- Env fallback ---
    resolved_env = environment or _derive_preferred_env()

    client_id = os.environ.get("UPS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("UPS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    if not _ups_fallback_warned:
        logger.warning(
            "UPS credentials resolved from env vars (provider=ups, env=%s). "
            "Configure in Settings for persistent storage.",
            resolved_env,
        )
        _ups_fallback_warned = True

    base_url = _UPS_BASE_URLS.get(resolved_env, _UPS_BASE_URLS["production"])

    # Check for UPS_BASE_URL mismatch
    env_base_url = os.environ.get("UPS_BASE_URL", "").strip()
    if env_base_url and env_base_url != base_url:
        logger.warning(
            "UPS base URL mismatch: UPS_BASE_URL=%s but environment=%s implies %s",
            env_base_url, resolved_env, base_url,
        )

    return UPSCredentials(
        client_id=client_id,
        client_secret=client_secret,
        environment=resolved_env,
        base_url=base_url,
        account_number=os.environ.get("UPS_ACCOUNT_NUMBER", "").strip(),
    )


def _normalize_domain_simple(raw: str) -> str:
    """Normalize a domain string for comparison (lowercase, strip protocol/slash)."""
    raw = raw.strip().lower()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        raw = parsed.hostname or raw
    return raw.rstrip("/")


def _try_db_shopify(
    db: Session, key_dir: str | None, store_domain: str | None,
) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None:
    """Attempt to resolve Shopify credentials from the DB."""
    from src.services.connection_service import ConnectionService

    service = ConnectionService(db=db, key_dir=key_dir)
    if store_domain:
        result = service.get_shopify_credentials(store_domain)
    else:
        result = service.get_first_shopify_credentials()

    if result is not None:
        # Filter out empty access_token (client_credentials_shopify without token)
        if isinstance(result, ShopifyClientCredentials) and not result.access_token:
            return None
        if isinstance(result, ShopifyLegacyCredentials) and not result.access_token:
            return None
        return result
    return None


def resolve_shopify_credentials(
    *,
    store_domain: str | None = None,
    db: Session | None = None,
    key_dir: str | None = None,
) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None:
    """Resolve Shopify credentials with DB priority, env fallback.

    Args:
        store_domain: Shopify store domain (optional — uses first available if None).
        db: SQLAlchemy session. When None a short-lived session is
            auto-acquired so DB credentials are always checked.
        key_dir: Encryption key directory (optional).

    Returns:
        ShopifyLegacyCredentials, ShopifyClientCredentials, or None.
    """
    global _shopify_fallback_warned

    # --- DB lookup (auto-acquire session when not provided) ---
    if db is not None:
        result = _try_db_shopify(db, key_dir, store_domain)
        if result is not None:
            return result
    else:
        try:
            from src.db.connection import SessionLocal

            auto_db = SessionLocal()
            try:
                result = _try_db_shopify(auto_db, key_dir, store_domain)
                if result is not None:
                    return result
            finally:
                auto_db.close()
        except (ImportError, OperationalError) as exc:
            logger.warning(
                "Auto-acquire DB session failed (%s); proceeding to env fallback",
                type(exc).__name__,
            )
        except Exception:
            logger.warning(
                "Unexpected error auto-acquiring DB session; proceeding to env fallback",
                exc_info=True,
            )

    # --- Env fallback ---
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
