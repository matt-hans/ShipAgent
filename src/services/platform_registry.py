# src/services/platform_registry.py
"""PlatformRegistry: static config + persisted dynamic state for platform integrations.

Extension point: add a PlatformConfig entry to PLATFORM_CONFIGS to register a new platform.

Session management: uses session_factory pattern. Every method creates its own
short-lived session to avoid shared-session-across-async-tasks bugs.

Credential keys: namespaced as {platform_id}:{credential_ref}:{key_name}
(e.g., shopify:primary:ACCESS_TOKEN) to support multi-profile.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import PlatformSyncState
from src.services.keyring_store import KeyringStore
from src.services.platform_models import (
    PlatformConfig,
    PlatformError,
    PlatformErrorCode,
    PlatformSummary,
)

logger = logging.getLogger(__name__)

# --- Static platform configs (the extension point) ---
# required_secret_keys are LOGICAL names, namespaced at runtime as
# {platform_id}:{credential_ref}:{key_name}

PLATFORM_CONFIGS: dict[str, PlatformConfig] = {
    "shopify": PlatformConfig(
        platform_id="shopify",
        display_name="Shopify",
        default_profile="primary",
        required_secret_keys=["ACCESS_TOKEN", "STORE_DOMAIN"],
        mcp_module="src.mcp.platforms.shopify.server",
        mcp_bundle_subcommand="mcp-shopify",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "amazon": PlatformConfig(
        platform_id="amazon",
        display_name="Amazon Seller Central",
        default_profile="primary",
        required_secret_keys=[
            "SP_API_REFRESH_TOKEN",
            "SP_API_CLIENT_ID",
            "SP_API_CLIENT_SECRET",
            "MARKETPLACE_ID",
        ],
        mcp_module="src.mcp.platforms.amazon.server",
        mcp_bundle_subcommand="mcp-amazon",
        contract_version="1.0",
        default_sync_overlap_seconds=600,
        enabled=True,
    ),
    "woocommerce": PlatformConfig(
        platform_id="woocommerce",
        display_name="WooCommerce",
        default_profile="primary",
        required_secret_keys=["CONSUMER_KEY", "CONSUMER_SECRET", "SITE_URL"],
        mcp_module="src.mcp.platforms.woocommerce.server",
        mcp_bundle_subcommand="mcp-woocommerce",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "sap": PlatformConfig(
        platform_id="sap",
        display_name="SAP Business One",
        default_profile="primary",
        required_secret_keys=["BASE_URL", "USERNAME", "PASSWORD", "CLIENT"],
        mcp_module="src.mcp.platforms.sap.server",
        mcp_bundle_subcommand="mcp-sap",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "oracle": PlatformConfig(
        platform_id="oracle",
        display_name="Oracle ERP",
        default_profile="primary",
        required_secret_keys=["HOST", "PORT", "SERVICE_NAME", "USER", "PASSWORD"],
        mcp_module="src.mcp.platforms.oracle.server",
        mcp_bundle_subcommand="mcp-oracle",
        contract_version="1.0",
        default_sync_overlap_seconds=300,
        enabled=True,
    ),
    "dummy": PlatformConfig(
        platform_id="dummy",
        display_name="Dummy (Test)",
        default_profile="test",
        required_secret_keys=[],
        mcp_module="src.mcp.platforms.dummy.server",
        mcp_bundle_subcommand="mcp-dummy",
        contract_version="1.0",
        default_sync_overlap_seconds=0,
        enabled=False,
    ),
}

# Maps keyring key names → auth.connect parameter names per platform.
# Keys not listed here fall through to key_name.lower().
SECRET_TO_AUTH_PARAM: dict[str, dict[str, str]] = {
    "shopify": {
        "ACCESS_TOKEN": "access_token",
        "STORE_DOMAIN": "store_domain",
    },
    "amazon": {
        "SP_API_CLIENT_ID": "client_id",
        "SP_API_CLIENT_SECRET": "client_secret",
        "SP_API_REFRESH_TOKEN": "refresh_token",
        "MARKETPLACE_ID": "marketplace_id",
    },
    "woocommerce": {
        "CONSUMER_KEY": "consumer_key",
        "CONSUMER_SECRET": "consumer_secret",
        "SITE_URL": "site_url",
    },
    "sap": {
        "BASE_URL": "base_url",
        "USERNAME": "username",
        "PASSWORD": "password",
        "CLIENT": "sap_client",
    },
    "oracle": {
        "HOST": "host",
        "PORT": "port",
        "SERVICE_NAME": "service_name",
        "USER": "user",
        "PASSWORD": "password",
    },
    "dummy": {},
}


CAPABILITIES_TTL_SECONDS = 3600  # 1 hour


def keyring_key(platform_id: str, credential_ref: str, key_name: str) -> str:
    """Build namespaced keyring key: {platform_id}:{credential_ref}:{key_name}."""
    return f"{platform_id}:{credential_ref}:{key_name}"


class PlatformRegistry:
    """Registry for platform integrations — static config + persisted dynamic state.

    Takes a session_factory (not a Session) — every method creates its own
    short-lived session to avoid cross-task session sharing bugs.
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    # --- Static config ---

    def get_config(self, platform_id: str) -> PlatformConfig | None:
        """Get static config for a platform."""
        return PLATFORM_CONFIGS.get(platform_id)

    def list_configs(self, enabled_only: bool = True) -> list[PlatformConfig]:
        """List all platform configs."""
        configs = list(PLATFORM_CONFIGS.values())
        if enabled_only:
            configs = [c for c in configs if c.enabled]
        return configs

    # --- Credential resolution ---

    def resolve_auth_args(
        self, platform_id: str, credential_ref: str,
    ) -> dict[str, str]:
        """Resolve auth.connect arguments from keyring secrets.

        Reads each required_secret_key from the keyring, maps it to the
        corresponding auth.connect parameter name, and returns the full
        argument dict ready to pass to the MCP tool.

        Args:
            platform_id: Platform identifier.
            credential_ref: Credential profile reference.

        Returns:
            Dict of auth.connect parameter names to secret values.

        Raises:
            PlatformError: If platform is unknown or a required secret is missing.
        """
        config = self.get_config(platform_id)
        if config is None:
            raise PlatformError(
                error_code=PlatformErrorCode.INVALID_ARGUMENT,
                message=f"Unknown platform: {platform_id}",
            )

        mapping = SECRET_TO_AUTH_PARAM.get(platform_id, {})
        ks = KeyringStore()
        args: dict[str, str] = {"credential_ref": credential_ref}

        for key_name in config.required_secret_keys:
            param_name = mapping.get(key_name, key_name.lower())
            value = ks.get(keyring_key(platform_id, credential_ref, key_name))
            if value is None:
                raise PlatformError(
                    error_code=PlatformErrorCode.AUTH_REQUIRED,
                    message=(
                        f"Missing credential: {key_name} for "
                        f"{platform_id}/{credential_ref}"
                    ),
                )
            args[param_name] = value

        return args

    # --- Dynamic state ---

    def get_state(self, platform_id: str, credential_ref: str) -> PlatformSyncState | None:
        """Get persisted dynamic state for a platform connection."""
        with self._session_factory() as session:
            state = session.get(PlatformSyncState, (platform_id, credential_ref))
            if state:
                session.expunge(state)
            return state

    def list_states(self) -> list[PlatformSyncState]:
        """List all platform sync states."""
        with self._session_factory() as session:
            states = session.query(PlatformSyncState).all()
            for s in states:
                session.expunge(s)
            return states

    def update_state(self, platform_id: str, credential_ref: str, **fields: Any) -> PlatformSyncState:
        """Update (or create) dynamic state for a platform connection."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            state = session.get(PlatformSyncState, (platform_id, credential_ref))
            if state is None:
                state = PlatformSyncState(
                    platform_id=platform_id,
                    credential_ref=credential_ref,
                    created_at=now,
                    updated_at=now,
                )
                session.add(state)

            for key, value in fields.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            state.updated_at = now
            session.commit()
            session.refresh(state)
            session.expunge(state)
            return state

    def record_sync_checkpoint(
        self,
        platform_id: str,
        credential_ref: str,
        resume_cursor: str | None,
        watermark: str | None,
        row_count: int,
    ) -> None:
        """Record sync progress. Clears resume_cursor and advances watermark on completion."""
        fields: dict[str, Any] = {
            "resume_cursor": resume_cursor,
            "last_sync_row_count": row_count,
        }
        if watermark is not None:
            fields["last_completed_watermark"] = watermark
            fields["last_sync_completed_at"] = datetime.now(timezone.utc)
        self.update_state(platform_id, credential_ref, **fields)

    def record_health_check(
        self,
        platform_id: str,
        credential_ref: str,
        ok: bool,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record result of a health check."""
        now = datetime.now(timezone.utc)
        fields: dict[str, Any] = {
            "last_health_check_at": now,
            "last_health_ok": ok,
        }
        if not ok:
            fields["last_error_code"] = error_code
            fields["last_error_message"] = error_message
            fields["last_error_at"] = now
        self.update_state(platform_id, credential_ref, **fields)

    def record_capabilities(
        self,
        platform_id: str,
        credential_ref: str,
        manifest: dict[str, Any],
        capabilities_hash: str,
        contract_version: str,
    ) -> None:
        """Cache a capabilities manifest."""
        self.update_state(
            platform_id, credential_ref,
            capabilities_json=json.dumps(manifest),
            capabilities_hash=capabilities_hash,
            capabilities_contract_version=contract_version,
            capabilities_fetched_at=datetime.now(timezone.utc),
        )

    # --- Active platform selection ---

    def set_platform_active(self, platform_id: str, credential_ref: str, active: bool) -> None:
        """Set whether a platform is active as a data source.

        Updates the is_active flag on the PlatformSyncState row.
        Creates the state row if it does not exist yet.

        Args:
            platform_id: Platform identifier.
            credential_ref: Credential profile reference.
            active: Whether the platform should be active.
        """
        self.update_state(platform_id, credential_ref, is_active=active)

    def get_active_platforms(self) -> list[PlatformSummary]:
        """Return summaries for platforms that are both enabled and active.

        Filters the full platform summary list to only those with
        is_active=True and an enabled static config.

        Returns:
            List of active PlatformSummary instances.
        """
        return [s for s in self.get_platforms_summary() if s.is_active and s.enabled]

    # --- Summary (agent/UI facing) ---

    def _check_credentials(
        self, keyring: KeyringStore, config: PlatformConfig, credential_ref: str,
    ) -> bool:
        """Check if all required credentials exist for a (platform, ref) profile."""
        return all(
            keyring.has(keyring_key(config.platform_id, credential_ref, k))
            for k in config.required_secret_keys
        )

    def get_platforms_summary(self) -> list[PlatformSummary]:
        """Join static config + dynamic state for all platforms."""
        keyring = KeyringStore()
        summaries: list[PlatformSummary] = []

        with self._session_factory() as session:
            for config in self.list_configs(enabled_only=True):
                states = (
                    session.query(PlatformSyncState)
                    .filter(PlatformSyncState.platform_id == config.platform_id)
                    .all()
                )

                if not states:
                    has_creds = self._check_credentials(keyring, config, config.default_profile)
                    summaries.append(PlatformSummary(
                        platform_id=config.platform_id,
                        display_name=config.display_name,
                        credential_ref=config.default_profile,
                        enabled=config.enabled,
                        connection_status="disconnected",
                        account_label=None,
                        last_sync_completed_at=None,
                        last_sync_row_count=None,
                        capabilities=None,
                        has_credentials=has_creds,
                        health_ok=None,
                        last_error=None,
                        contract_version_ok=True,
                        capabilities_stale=True,
                        is_active=False,
                    ))
                else:
                    for state in states:
                        caps = json.loads(state.capabilities_json).get("supports", []) if state.capabilities_json else None
                        cv_ok = state.capabilities_contract_version == config.contract_version if state.capabilities_contract_version else True
                        stale = True
                        if state.capabilities_fetched_at:
                            age = (datetime.now(timezone.utc) - state.capabilities_fetched_at).total_seconds()
                            stale = age > CAPABILITIES_TTL_SECONDS
                        has_creds = self._check_credentials(keyring, config, state.credential_ref)

                        summaries.append(PlatformSummary(
                            platform_id=config.platform_id,
                            display_name=config.display_name,
                            credential_ref=state.credential_ref,
                            enabled=config.enabled,
                            connection_status=state.connection_status,
                            account_label=state.account_label,
                            last_sync_completed_at=state.last_sync_completed_at,
                            last_sync_row_count=state.last_sync_row_count,
                            capabilities=caps,
                            has_credentials=has_creds,
                            health_ok=state.last_health_ok,
                            last_error=state.last_error_message,
                            contract_version_ok=cv_ok,
                            capabilities_stale=stale,
                            is_active=state.is_active,
                        ))

        return summaries
