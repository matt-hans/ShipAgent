"""ConnectionService — CRUD, validation, encryption for provider connections.

Manages the lifecycle of provider connection credentials with AES-256-GCM
encryption and AAD binding. All credential fields are validated against
allowlists before encryption. Error messages are sanitized before persistence.
"""

import json
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import ProviderConnection
from src.services.connection_types import (
    CREDENTIAL_SCHEMAS,
    SKIP_STATUSES,
    VALID_AUTH_MODES,
    VALID_ENVIRONMENTS,
    VALID_PROVIDERS,
    VALID_STATUSES,
    ConnectionValidationError,
    ShopifyClientCredentials,
    ShopifyLegacyCredentials,
    UPSCredentials,
)
from src.services.credential_encryption import (
    CredentialDecryptionError,
    decrypt_credentials,
    encrypt_credentials,
    get_or_create_key,
)
from src.utils.redaction import sanitize_error_message

logger = logging.getLogger(__name__)

_UPS_BASE_URLS = {
    "test": "https://wwwcie.ups.com",
    "production": "https://onlinetools.ups.com",
}


def _utc_now_iso() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_shopify_domain(raw: str) -> str:
    """Normalize a Shopify store domain.

    Lowercases, strips protocol/trailing slashes, validates *.myshopify.com.

    Args:
        raw: Raw domain string (may include protocol).

    Returns:
        Normalized domain (e.g. 'mystore.myshopify.com').

    Raises:
        ConnectionValidationError: If domain is invalid.
    """
    if not raw or not raw.strip():
        raise ConnectionValidationError("INVALID_DOMAIN", "Store domain is required")

    domain = raw.strip().lower()

    # Strip protocol if present
    if "://" in domain:
        parsed = urlparse(domain)
        domain = parsed.hostname or ""

    # Strip trailing slashes and whitespace
    domain = domain.rstrip("/").strip()

    if not domain:
        raise ConnectionValidationError("INVALID_DOMAIN", "Store domain is empty after normalization")

    if not re.match(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$", domain):
        raise ConnectionValidationError(
            "INVALID_DOMAIN",
            f"Domain must match *.myshopify.com (got '{domain}')",
        )

    return domain


def _build_aad(row: ProviderConnection) -> str:
    """Build AAD string for AES-GCM encryption binding.

    Args:
        row: ProviderConnection ORM row.

    Returns:
        AAD string: 'provider:auth_mode:connection_key'.
    """
    return f"{row.provider}:{row.auth_mode}:{row.connection_key}"


def _build_connection_key(provider: str, auth_mode: str, environment: str | None = None,
                          metadata: dict | None = None) -> str:
    """Build a deterministic connection_key from provider + identity fields.

    Args:
        provider: Provider name.
        auth_mode: Auth mode.
        environment: UPS environment (test/production).
        metadata: Metadata dict (contains store_domain for Shopify).

    Returns:
        Connection key string.
    """
    if provider == "ups":
        return f"ups:{environment}"
    elif provider == "shopify":
        store_domain = (metadata or {}).get("store_domain", "unknown")
        return f"shopify:{store_domain}"
    return f"{provider}:{environment or 'default'}"


def _validate_credential_keys(provider: str, auth_mode: str, credentials: dict) -> None:
    """Validate credential keys against allowlist and enforce max lengths.

    Args:
        provider: Provider name.
        auth_mode: Auth mode string.
        credentials: Credential dict to validate.

    Raises:
        ConnectionValidationError: On unknown keys or oversized values.
    """
    schema_key = f"{provider}:{auth_mode}"
    schema = CREDENTIAL_SCHEMAS.get(schema_key)
    if schema is None:
        return  # No schema defined — skip validation

    allowed_keys = set(schema["required"].keys()) | set(schema["optional"].keys())
    unknown = set(credentials.keys()) - allowed_keys
    if unknown:
        raise ConnectionValidationError(
            "UNKNOWN_CREDENTIAL_KEY",
            f"Unknown credential keys: {sorted(unknown)}",
        )

    # Check max lengths
    all_limits = {**schema["required"], **schema["optional"]}
    for key, value in credentials.items():
        if key in all_limits and isinstance(value, str) and len(value) > all_limits[key]:
            raise ConnectionValidationError(
                "VALUE_TOO_LONG",
                f"Credential '{key}' exceeds max length {all_limits[key]}",
            )


def _deserialize_metadata(row: ProviderConnection) -> dict:
    """Safely deserialize metadata_json from a DB row.

    Args:
        row: ProviderConnection ORM row.

    Returns:
        Parsed dict, or {} on failure.
    """
    if not row.metadata_json:
        return {}
    try:
        result = json.loads(row.metadata_json)
        if isinstance(result, dict):
            return result
        return {}
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Corrupt metadata_json for connection %s — returning empty dict",
            row.connection_key,
        )
        return {}


class ConnectionService:
    """Manages provider connection CRUD with encrypted credential storage.

    All credential fields are validated, encrypted with AES-256-GCM + AAD,
    and stored in the provider_connections table. Error messages are sanitized
    before persistence to prevent credential leakage.

    Args:
        db: SQLAlchemy session.
        key_dir: Optional override for encryption key directory.
    """

    def __init__(self, db: Session, key_dir: str | None = None) -> None:
        self._db = db
        self._key = get_or_create_key(key_dir)

    def _validate_save_input(
        self, provider: str, auth_mode: str, credentials: dict,
        metadata: dict, environment: str | None, display_name: str,
    ) -> None:
        """Validate all inputs before save.

        Raises:
            ConnectionValidationError: On any validation failure.
        """
        if provider not in VALID_PROVIDERS:
            raise ConnectionValidationError(
                "INVALID_PROVIDER",
                f"Invalid provider '{provider}'. Must be one of: {sorted(VALID_PROVIDERS)}",
            )

        valid_modes = VALID_AUTH_MODES.get(provider, frozenset())
        if auth_mode not in valid_modes:
            raise ConnectionValidationError(
                "INVALID_AUTH_MODE",
                f"Invalid auth_mode '{auth_mode}' for {provider}. Must be one of: {sorted(valid_modes)}",
            )

        # UPS-specific validation
        if provider == "ups":
            if not environment or environment not in VALID_ENVIRONMENTS:
                raise ConnectionValidationError(
                    "INVALID_ENVIRONMENT",
                    f"UPS requires environment in {sorted(VALID_ENVIRONMENTS)} (got '{environment}')",
                )
            if not credentials.get("client_id"):
                raise ConnectionValidationError("MISSING_FIELD", "client_id is required for UPS")
            if not credentials.get("client_secret"):
                raise ConnectionValidationError("MISSING_FIELD", "client_secret is required for UPS")

        # Shopify-specific validation
        if provider == "shopify":
            store_domain = metadata.get("store_domain")
            if not store_domain:
                raise ConnectionValidationError("MISSING_FIELD", "store_domain is required for Shopify")
            # Normalize will raise if invalid
            _normalize_shopify_domain(store_domain)

            if auth_mode == "legacy_token" and not credentials.get("access_token"):
                raise ConnectionValidationError(
                    "MISSING_FIELD", "access_token is required for Shopify legacy_token"
                )

        # Credential key allowlist + length validation
        _validate_credential_keys(provider, auth_mode, credentials)

    def _is_runtime_usable(self, row: ProviderConnection) -> tuple[bool, str | None]:
        """Compute whether a connection is usable at runtime.

        Args:
            row: ProviderConnection ORM row.

        Returns:
            (usable, reason) tuple.
        """
        if row.status in SKIP_STATUSES:
            return False, row.status

        if row.auth_mode == "client_credentials_shopify":
            try:
                aad = _build_aad(row)
                creds = decrypt_credentials(row.encrypted_credentials, self._key, aad=aad)
                if not creds.get("access_token"):
                    return False, "missing_access_token"
            except CredentialDecryptionError:
                return False, "decrypt_failed"

        return True, None

    def _row_to_dict(self, row: ProviderConnection, include_runtime: bool = True) -> dict:
        """Convert a DB row to a response dict (no credentials exposed).

        Args:
            row: ProviderConnection ORM row.
            include_runtime: Whether to compute runtime_usable.

        Returns:
            Dict with connection metadata.
        """
        result = {
            "id": row.id,
            "connection_key": row.connection_key,
            "provider": row.provider,
            "display_name": row.display_name,
            "auth_mode": row.auth_mode,
            "environment": row.environment,
            "status": row.status,
            "metadata": _deserialize_metadata(row),
            "last_validated_at": None,
            "last_error_code": row.last_error_code,
            "error_message": row.error_message,
            "schema_version": row.schema_version,
            "key_version": row.key_version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

        if include_runtime:
            try:
                usable, reason = self._is_runtime_usable(row)
            except Exception:
                usable, reason = False, "decrypt_failed"
                logger.warning(
                    "Failed to compute runtime_usable for %s",
                    row.connection_key,
                )
            result["runtime_usable"] = usable
            result["runtime_reason"] = reason

        return result

    def save_connection(
        self, provider: str, auth_mode: str, credentials: dict,
        metadata: dict, display_name: str, environment: str | None = None,
    ) -> dict:
        """Save or overwrite a provider connection with encrypted credentials.

        Args:
            provider: Provider name ('ups' or 'shopify').
            auth_mode: Authentication mode.
            credentials: Credential key-value pairs (encrypted before storage).
            metadata: Non-secret metadata (e.g. store_domain).
            display_name: Human-readable display name.
            environment: UPS environment ('test' or 'production').

        Returns:
            Dict with is_new, connection_key, runtime_usable, runtime_reason, auth_mode.

        Raises:
            ConnectionValidationError: On invalid inputs.
        """
        self._validate_save_input(provider, auth_mode, credentials, metadata, environment, display_name)

        # Normalize Shopify domain in metadata
        if provider == "shopify" and metadata.get("store_domain"):
            metadata["store_domain"] = _normalize_shopify_domain(metadata["store_domain"])

        connection_key = _build_connection_key(provider, auth_mode, environment, metadata)

        # Build row for AAD computation
        existing = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()

        is_new = existing is None
        now = _utc_now_iso()

        if is_new:
            from src.db.models import generate_uuid
            row = ProviderConnection(
                id=generate_uuid(),
                connection_key=connection_key,
                provider=provider,
                display_name=display_name,
                auth_mode=auth_mode,
                environment=environment,
                status="configured",
                encrypted_credentials="",  # Placeholder — set below
                metadata_json=json.dumps(metadata, sort_keys=True),
                schema_version=1,
                key_version=1,
                created_at=now,
                updated_at=now,
            )
            self._db.add(row)
        else:
            row = existing
            row.display_name = display_name
            row.auth_mode = auth_mode
            row.environment = environment
            row.status = "configured"
            row.metadata_json = json.dumps(metadata, sort_keys=True)
            row.updated_at = now
            row.last_error_code = None
            row.error_message = None

        # Encrypt credentials with AAD
        aad = _build_aad(row)
        row.encrypted_credentials = encrypt_credentials(credentials, self._key, aad=aad)

        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            raise

        usable, reason = self._is_runtime_usable(row)

        return {
            "is_new": is_new,
            "connection_key": connection_key,
            "runtime_usable": usable,
            "runtime_reason": reason,
            "auth_mode": auth_mode,
        }

    def get_connection(self, connection_key: str) -> dict | None:
        """Get a single connection by key (no credentials exposed).

        Args:
            connection_key: Unique connection identifier.

        Returns:
            Connection dict or None if not found.
        """
        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_connections(self) -> list[dict]:
        """List all connections ordered by provider, connection_key.

        Returns:
            List of connection dicts (no credentials exposed).
        """
        rows = (
            self._db.query(ProviderConnection)
            .order_by(ProviderConnection.provider, ProviderConnection.connection_key)
            .all()
        )
        return [self._row_to_dict(row) for row in rows]

    def delete_connection(self, connection_key: str) -> bool:
        """Delete a connection by key.

        Args:
            connection_key: Unique connection identifier.

        Returns:
            True if deleted, False if not found.
        """
        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None:
            return False
        self._db.delete(row)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            raise
        return True

    def disconnect(self, connection_key: str) -> dict | None:
        """Set a connection to 'disconnected' status, preserving credentials.

        Args:
            connection_key: Unique connection identifier.

        Returns:
            Updated connection dict, or None if not found.
        """
        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None:
            return None

        row.status = "disconnected"
        row.updated_at = _utc_now_iso()
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            raise
        return self._row_to_dict(row)

    def update_status(
        self, connection_key: str, status: str,
        error_code: str | None = None, error_message: str | None = None,
    ) -> dict | None:
        """Update a connection's status with optional error info.

        Args:
            connection_key: Unique connection identifier.
            status: New status value (must be in VALID_STATUSES).
            error_code: Optional error code.
            error_message: Optional error message (sanitized before storage).

        Returns:
            Updated connection dict, or None if not found.

        Raises:
            ValueError: If status not in VALID_STATUSES.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}")

        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None:
            return None

        row.status = status
        row.last_error_code = error_code
        row.error_message = sanitize_error_message(error_message) if error_message else None
        row.updated_at = _utc_now_iso()
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            raise
        return self._row_to_dict(row)

    def check_all(self) -> dict:
        """Check all non-disconnected connections for decryptability.

        Attempts to decrypt each connection's credentials. On success, recovers
        needs_reconnect rows to configured. On failure, marks rows as
        needs_reconnect with DECRYPT_FAILED error code.

        Returns:
            Dict of connection_key -> "ok" | "error".
        """
        from src.services.credential_encryption import get_key_source_info

        key_info = get_key_source_info()
        logger.info("check_all: key source=%s", key_info["source"])

        rows = (
            self._db.query(ProviderConnection)
            .filter(~ProviderConnection.status.in_({"disconnected"}))
            .all()
        )
        if not rows:
            return {}

        results: dict[str, str] = {}
        error_count = 0

        for row in rows:
            # Validate row has required fields
            if not row.provider or not row.auth_mode or not row.connection_key or not row.encrypted_credentials:
                results[row.connection_key or "unknown"] = "error"
                row.status = "needs_reconnect"
                row.last_error_code = "INVALID_ROW"
                row.error_message = "Missing required fields (provider, auth_mode, or encrypted_credentials)"
                row.updated_at = _utc_now_iso()
                error_count += 1
                continue

            try:
                aad = _build_aad(row)
                decrypt_credentials(row.encrypted_credentials, self._key, aad=aad)
                results[row.connection_key] = "ok"
                # Recover needs_reconnect on successful decrypt
                if row.status == "needs_reconnect":
                    row.status = "configured"
                    row.last_error_code = None
                    row.error_message = None
                    row.updated_at = _utc_now_iso()
            except CredentialDecryptionError as e:
                results[row.connection_key] = "error"
                row.status = "needs_reconnect"
                row.last_error_code = "DECRYPT_FAILED"
                row.error_message = sanitize_error_message(str(e))
                row.updated_at = _utc_now_iso()
                error_count += 1
                logger.warning(
                    "Connection %s could not be decrypted: %s",
                    row.connection_key, sanitize_error_message(str(e)),
                )

        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()

        if error_count > 0:
            logger.warning(
                "%d provider connection(s) could not be decrypted. "
                "This may indicate the encryption key has changed. "
                "Re-enter credentials in Settings to fix.",
                error_count,
            )

        return results

    # --- Typed Credential Resolvers ---

    def get_ups_credentials(self, environment: str) -> UPSCredentials | None:
        """Resolve UPS credentials for a given environment.

        Skips rows with status in SKIP_STATUSES.

        Args:
            environment: 'test' or 'production'.

        Returns:
            UPSCredentials dataclass or None if not found/skipped.
        """
        connection_key = f"ups:{environment}"
        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None or row.status in SKIP_STATUSES:
            return None

        try:
            aad = _build_aad(row)
            creds = decrypt_credentials(row.encrypted_credentials, self._key, aad=aad)
        except CredentialDecryptionError:
            logger.warning("Failed to decrypt UPS credentials for %s", connection_key)
            return None

        base_url = _UPS_BASE_URLS.get(environment, _UPS_BASE_URLS["production"])
        metadata = _deserialize_metadata(row)
        return UPSCredentials(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            environment=environment,
            base_url=base_url,
            account_number=creds.get("account_number", "") or metadata.get("account_number", ""),
        )

    def get_shopify_credentials(
        self, store_domain: str
    ) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None:
        """Resolve Shopify credentials for a specific store domain.

        Normalizes input domain before lookup. Skips rows with status in SKIP_STATUSES.

        Args:
            store_domain: Store domain (e.g. 'mystore.myshopify.com').

        Returns:
            ShopifyLegacyCredentials or ShopifyClientCredentials or None.
        """
        try:
            normalized = _normalize_shopify_domain(store_domain)
        except ConnectionValidationError:
            return None

        connection_key = f"shopify:{normalized}"
        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None or row.status in SKIP_STATUSES:
            return None

        try:
            aad = _build_aad(row)
            creds = decrypt_credentials(row.encrypted_credentials, self._key, aad=aad)
        except CredentialDecryptionError:
            logger.warning("Failed to decrypt Shopify credentials for %s", connection_key)
            return None

        if row.auth_mode == "legacy_token":
            return ShopifyLegacyCredentials(
                access_token=creds["access_token"],
                store_domain=normalized,
            )
        else:
            return ShopifyClientCredentials(
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
                store_domain=normalized,
                access_token=creds.get("access_token", ""),
            )

    def get_first_shopify_credentials(
        self,
    ) -> ShopifyLegacyCredentials | ShopifyClientCredentials | None:
        """Resolve the first available Shopify connection (deterministic default).

        Queries DB with ORDER BY connection_key ASC, skips disconnected/needs_reconnect.

        Returns:
            ShopifyLegacyCredentials or ShopifyClientCredentials or None.
        """
        row = (
            self._db.query(ProviderConnection)
            .filter(
                ProviderConnection.provider == "shopify",
                ~ProviderConnection.status.in_(SKIP_STATUSES),
            )
            .order_by(ProviderConnection.connection_key)
            .first()
        )
        if row is None:
            return None

        metadata = _deserialize_metadata(row)
        store_domain = metadata.get("store_domain", "")

        try:
            aad = _build_aad(row)
            creds = decrypt_credentials(row.encrypted_credentials, self._key, aad=aad)
        except CredentialDecryptionError:
            logger.warning("Failed to decrypt Shopify credentials for %s", row.connection_key)
            return None

        if row.auth_mode == "legacy_token":
            return ShopifyLegacyCredentials(
                access_token=creds["access_token"],
                store_domain=store_domain,
            )
        else:
            return ShopifyClientCredentials(
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
                store_domain=store_domain,
                access_token=creds.get("access_token", ""),
            )

    # --- Live Credential Validation ---

    async def validate_connection(self, connection_key: str) -> dict:
        """Validate saved credentials against the real provider API.

        Decrypts stored credentials, makes a lightweight API call to verify
        they work, and updates the connection status to 'connected' on success
        or 'error' on failure.

        Args:
            connection_key: Unique connection identifier.

        Returns:
            Dict with 'valid', 'status', 'message', and optional 'details'.

        Raises:
            ConnectionValidationError: If connection not found or not validatable.
        """
        row = self._db.query(ProviderConnection).filter_by(
            connection_key=connection_key
        ).first()
        if row is None:
            raise ConnectionValidationError(
                "NOT_FOUND", f"Connection '{connection_key}' not found"
            )

        # Decrypt credentials
        try:
            aad = _build_aad(row)
            creds = decrypt_credentials(row.encrypted_credentials, self._key, aad=aad)
        except CredentialDecryptionError as e:
            self._update_validation_status(
                row, "needs_reconnect", "DECRYPT_FAILED", str(e)
            )
            return {
                "valid": False,
                "status": "needs_reconnect",
                "message": "Credentials could not be decrypted. Re-enter credentials.",
            }

        metadata = _deserialize_metadata(row)

        if row.provider == "shopify":
            return await self._validate_shopify(row, creds, metadata)
        elif row.provider == "ups":
            return await self._validate_ups(row, creds)
        else:
            return {
                "valid": False,
                "status": row.status,
                "message": f"Validation not supported for provider '{row.provider}'",
            }

    async def _validate_shopify(
        self, row: ProviderConnection, creds: dict, metadata: dict,
    ) -> dict:
        """Validate Shopify credentials by calling the shop.json endpoint.

        Args:
            row: ProviderConnection ORM row.
            creds: Decrypted credential dict.
            metadata: Deserialized metadata dict.

        Returns:
            Validation result dict.
        """
        import httpx

        store_domain = metadata.get("store_domain", "")
        access_token = creds.get("access_token", "")

        if not store_domain or not access_token:
            self._update_validation_status(
                row, "error", "MISSING_FIELD", "store_domain or access_token missing"
            )
            return {
                "valid": False,
                "status": "error",
                "message": "Incomplete credentials: store domain or access token is missing.",
            }

        # Normalize domain
        domain = store_domain.replace("https://", "").replace("http://", "").rstrip("/")
        api_url = f"https://{domain}/admin/api/2024-01/shop.json"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    api_url,
                    headers={
                        "X-Shopify-Access-Token": access_token,
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code == 200:
                shop_data = response.json().get("shop", {})
                shop_name = shop_data.get("name", domain)
                self._update_validation_status(row, "connected", None, None)
                return {
                    "valid": True,
                    "status": "connected",
                    "message": f"Successfully connected to Shopify store: {shop_name}",
                    "details": {"shop_name": shop_name, "domain": domain},
                }
            elif response.status_code == 401:
                self._update_validation_status(
                    row, "error", "AUTH_FAILED",
                    "Access token is invalid or has been revoked"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": "Authentication failed: access token is invalid or revoked. Check your Shopify Admin API access token.",
                }
            elif response.status_code == 403:
                self._update_validation_status(
                    row, "error", "PERMISSION_DENIED",
                    "Token lacks required scopes"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": "Permission denied: the access token lacks required API scopes.",
                }
            elif response.status_code == 404:
                self._update_validation_status(
                    row, "error", "STORE_NOT_FOUND",
                    f"Store '{domain}' not found"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": f"Store not found: '{domain}' does not exist or is unavailable.",
                }
            else:
                self._update_validation_status(
                    row, "error", "API_ERROR",
                    f"HTTP {response.status_code}"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": f"Shopify API returned HTTP {response.status_code}.",
                }
        except httpx.ConnectError:
            self._update_validation_status(
                row, "error", "DNS_ERROR",
                f"Cannot resolve '{domain}'"
            )
            return {
                "valid": False,
                "status": "error",
                "message": f"Cannot reach store: '{domain}' could not be resolved. Check the store domain.",
            }
        except httpx.TimeoutException:
            self._update_validation_status(
                row, "error", "TIMEOUT",
                "Connection timed out"
            )
            return {
                "valid": False,
                "status": "error",
                "message": "Connection timed out. Try again.",
            }
        except Exception as e:
            logger.warning("Shopify validation error: %s", e, exc_info=True)
            self._update_validation_status(
                row, "error", "VALIDATION_ERROR", str(e)
            )
            return {
                "valid": False,
                "status": "error",
                "message": f"Validation failed: {sanitize_error_message(str(e))}",
            }

    async def _validate_ups(self, row: ProviderConnection, creds: dict) -> dict:
        """Validate UPS credentials by requesting an OAuth token.

        Args:
            row: ProviderConnection ORM row.
            creds: Decrypted credential dict.

        Returns:
            Validation result dict.
        """
        import httpx

        client_id = creds.get("client_id", "")
        client_secret = creds.get("client_secret", "")
        environment = row.environment or "test"

        if not client_id or not client_secret:
            self._update_validation_status(
                row, "error", "MISSING_FIELD", "client_id or client_secret missing"
            )
            return {
                "valid": False,
                "status": "error",
                "message": "Incomplete credentials: Client ID or Client Secret is missing.",
            }

        base_url = _UPS_BASE_URLS.get(environment, _UPS_BASE_URLS["production"])
        token_url = f"{base_url}/security/v1/oauth/token"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    token_url,
                    data={"grant_type": "client_credentials"},
                    auth=(client_id, client_secret),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

            if response.status_code == 200:
                self._update_validation_status(row, "connected", None, None)
                return {
                    "valid": True,
                    "status": "connected",
                    "message": f"Successfully authenticated with UPS ({environment}).",
                    "details": {"environment": environment},
                }
            elif response.status_code == 401:
                self._update_validation_status(
                    row, "error", "AUTH_FAILED",
                    "Client credentials are invalid"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": "Authentication failed: Client ID or Client Secret is invalid.",
                }
            elif response.status_code == 403:
                self._update_validation_status(
                    row, "error", "PERMISSION_DENIED",
                    "Account lacks required permissions"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": "Permission denied: UPS account lacks required permissions.",
                }
            else:
                self._update_validation_status(
                    row, "error", "API_ERROR",
                    f"HTTP {response.status_code}"
                )
                return {
                    "valid": False,
                    "status": "error",
                    "message": f"UPS API returned HTTP {response.status_code}.",
                }
        except httpx.ConnectError:
            self._update_validation_status(
                row, "error", "CONNECT_ERROR",
                f"Cannot reach UPS ({environment})"
            )
            return {
                "valid": False,
                "status": "error",
                "message": f"Cannot reach UPS API ({environment}). Check your network connection.",
            }
        except httpx.TimeoutException:
            self._update_validation_status(
                row, "error", "TIMEOUT",
                "Connection timed out"
            )
            return {
                "valid": False,
                "status": "error",
                "message": "Connection timed out. Try again.",
            }
        except Exception as e:
            logger.warning("UPS validation error: %s", e, exc_info=True)
            self._update_validation_status(
                row, "error", "VALIDATION_ERROR", str(e)
            )
            return {
                "valid": False,
                "status": "error",
                "message": f"Validation failed: {sanitize_error_message(str(e))}",
            }

    def _update_validation_status(
        self, row: ProviderConnection, status: str,
        error_code: str | None, error_message: str | None,
    ) -> None:
        """Update a connection's status after validation.

        Args:
            row: ProviderConnection ORM row.
            status: New status value.
            error_code: Optional error code.
            error_message: Optional error message (sanitized before storage).
        """
        row.status = status
        row.last_error_code = error_code
        row.error_message = sanitize_error_message(error_message) if error_message else None
        row.updated_at = _utc_now_iso()
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
