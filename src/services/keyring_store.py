"""Secure credential storage using the system keychain.

Uses the `keyring` library which maps to:
  macOS: Keychain Services (user login keychain)
  Windows: Windows Credential Manager (future)
  Linux: Secret Service API (future)

All credentials are stored under the service name 'com.shipagent.app'.

Set SHIPAGENT_KEYRING_DISABLED=1 to skip keychain access entirely
(env-var-only mode). Useful for dev when credentials live in .env.
"""

import logging
import os

import keyring

logger = logging.getLogger(__name__)

SERVICE_NAME = "com.shipagent.app"

# Credentials managed by this store (immutable — used for membership checks)
MANAGED_CREDENTIALS = frozenset({
    "ANTHROPIC_API_KEY",
    "UPS_CLIENT_ID",
    "UPS_CLIENT_SECRET",
    "SHOPIFY_ACCESS_TOKEN",
    "FILTER_TOKEN_SECRET",
    "SHIPAGENT_API_KEY",
})


def _keyring_disabled() -> bool:
    """Return True when keychain access is disabled via env var."""
    return os.environ.get("SHIPAGENT_KEYRING_DISABLED", "").strip() in ("1", "true", "yes")


class KeyringStore:
    """Thin wrapper around keyring for credential CRUD."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service = service_name

    def get(self, key: str) -> str | None:
        """Retrieve a credential value. Returns None if not set."""
        if _keyring_disabled():
            return None
        try:
            return keyring.get_password(self._service, key)
        except Exception:
            logger.warning("Keyring read failed for %s", key, exc_info=True)
            return None

    def set(self, key: str, value: str) -> None:
        """Store a credential value in keyring and sync to os.environ.

        Syncing to os.environ ensures the runtime credential resolver
        (which checks keyring → env) can find keyring-stored credentials
        without requiring a restart.
        """
        if not _keyring_disabled():
            try:
                keyring.set_password(self._service, key, value)
                logger.info("Stored credential: %s", key)
            except Exception:
                logger.warning("Keyring write failed for %s", key, exc_info=True)
                raise
        # Sync to process environment so runtime resolvers pick it up immediately
        os.environ[key] = value

    def delete(self, key: str) -> None:
        """Remove a credential from keyring and os.environ.

        Always cleans up os.environ regardless of keyring outcome
        to prevent state desync between the two stores.
        """
        if not _keyring_disabled():
            try:
                keyring.delete_password(self._service, key)
                logger.info("Deleted credential: %s", key)
            except keyring.errors.PasswordDeleteError:
                logger.debug("Credential %s not found for deletion", key)
            except Exception:
                logger.warning("Keyring delete failed for %s", key, exc_info=True)
        # Always clean up env regardless of keyring outcome
        os.environ.pop(key, None)

    def has(self, key: str) -> bool:
        """Check if a credential is set."""
        return self.get(key) is not None

    def get_all_status(self) -> dict[str, bool]:
        """Return status of all managed credentials.

        Checks both keyring and env for each key. If the keyring backend
        is completely unavailable (e.g. locked keychain), falls back to
        env-only checks to avoid N failing I/O roundtrips.
        """
        # Probe keyring health with one call; if it fails, skip keyring entirely
        keyring_available = not _keyring_disabled()
        if keyring_available:
            try:
                keyring.get_password(self._service, "__probe__")
            except Exception:
                keyring_available = False
                logger.debug("Keyring unavailable for status check; using env only")

        result: dict[str, bool] = {}
        for key in MANAGED_CREDENTIALS:
            if keyring_available:
                result[key] = (self.get(key) is not None) or bool(
                    os.environ.get(key, "").strip()
                )
            else:
                result[key] = bool(os.environ.get(key, "").strip())
        return result

    def load_all_to_env(self) -> int:
        """Load all keyring credentials into os.environ (startup sync).

        Only sets env vars that are not already set, so explicit env
        configuration always takes priority.

        Returns:
            Number of credentials loaded from keyring.
        """
        loaded = 0
        skipped_env = 0
        for key in MANAGED_CREDENTIALS:
            if os.environ.get(key, "").strip():
                skipped_env += 1
                continue  # Env already set, don't override
            value = self.get(key)
            if value:
                os.environ[key] = value
                loaded += 1
                logger.debug("Loaded %s from keyring into env", key)
        if skipped_env:
            logger.debug(
                "Skipped %d credentials already set in env", skipped_env
            )
        return loaded
