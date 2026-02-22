"""Secure credential storage using the system keychain.

Uses the `keyring` library which maps to:
  macOS: Keychain Access (Secure Enclave on Apple Silicon)
  Windows: Windows Credential Manager (future)
  Linux: Secret Service API (future)

All credentials are stored under the service name 'com.shipagent.app'.
"""

import logging

import keyring

logger = logging.getLogger(__name__)

SERVICE_NAME = "com.shipagent.app"

# Credentials managed by this store
MANAGED_CREDENTIALS = [
    "ANTHROPIC_API_KEY",
    "UPS_CLIENT_ID",
    "UPS_CLIENT_SECRET",
    "SHOPIFY_ACCESS_TOKEN",
    "FILTER_TOKEN_SECRET",
    "SHIPAGENT_API_KEY",
]


class KeyringStore:
    """Thin wrapper around keyring for credential CRUD."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service = service_name

    def get(self, key: str) -> str | None:
        """Retrieve a credential value. Returns None if not set."""
        try:
            return keyring.get_password(self._service, key)
        except Exception:
            logger.warning("Keyring read failed for %s", key, exc_info=True)
            return None

    def set(self, key: str, value: str) -> None:
        """Store a credential value."""
        keyring.set_password(self._service, key, value)
        logger.info("Stored credential: %s", key)

    def delete(self, key: str) -> None:
        """Remove a credential."""
        try:
            keyring.delete_password(self._service, key)
            logger.info("Deleted credential: %s", key)
        except keyring.errors.PasswordDeleteError:
            logger.debug("Credential %s not found for deletion", key)

    def has(self, key: str) -> bool:
        """Check if a credential is set."""
        return self.get(key) is not None

    def get_all_status(self) -> dict[str, bool]:
        """Return status of all managed credentials."""
        return {key: self.has(key) for key in MANAGED_CREDENTIALS}
