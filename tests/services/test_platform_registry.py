# tests/services/test_platform_registry.py
"""Tests for PlatformRegistry service."""
import os
import tempfile
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, PlatformSyncState
from src.services.platform_models import (
    PlatformConfig,
    PlatformError,
    PlatformErrorCode,
    CapabilityManifest,
)
from src.services.platform_registry import (
    PlatformRegistry,
    PLATFORM_CONFIGS,
    SECRET_TO_AUTH_PARAM,
    keyring_key,
)


@pytest.fixture
def db_path(tmp_path):
    """Use a temp file DB (not :memory:) so sessions see the same data."""
    return str(tmp_path / "test_registry.db")


@pytest.fixture
def session_factory(db_path):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture
def registry(session_factory):
    return PlatformRegistry(session_factory)


class TestStaticConfig:
    def test_get_config_exists(self, registry):
        config = registry.get_config("shopify")
        assert config is not None
        assert config.platform_id == "shopify"
        assert config.display_name == "Shopify"

    def test_get_config_not_found(self, registry):
        assert registry.get_config("nonexistent") is None

    def test_list_configs_enabled_only(self, registry):
        configs = registry.list_configs(enabled_only=True)
        assert all(c.enabled for c in configs)

    def test_list_configs_all(self, registry):
        configs = registry.list_configs(enabled_only=False)
        assert len(configs) >= 1  # at least shopify

    def test_platform_configs_has_shopify(self):
        assert "shopify" in PLATFORM_CONFIGS
        shopify = PLATFORM_CONFIGS["shopify"]
        assert shopify.contract_version == "1.0"


class TestDynamicState:
    def test_get_state_returns_none_when_missing(self, registry):
        state = registry.get_state("shopify", "primary")
        assert state is None

    def test_update_state_creates_if_missing(self, registry, session_factory):
        state = registry.update_state(
            "shopify", "primary",
            connection_status="connected",
            account_label="test-store.myshopify.com",
        )
        assert state.connection_status == "connected"
        assert state.account_label == "test-store.myshopify.com"

        # Verify via separate session (proves data persisted)
        with session_factory() as s:
            loaded = s.get(PlatformSyncState, ("shopify", "primary"))
            assert loaded is not None

    def test_update_state_updates_existing(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.update_state("shopify", "primary", connection_status="degraded")

        state = registry.get_state("shopify", "primary")
        assert state.connection_status == "degraded"

    def test_record_sync_checkpoint(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_sync_checkpoint(
            "shopify", "primary",
            resume_cursor="cursor_abc",
            watermark=None,
            row_count=50,
        )
        state = registry.get_state("shopify", "primary")
        assert state.resume_cursor == "cursor_abc"
        assert state.last_completed_watermark is None  # not advanced mid-sync

    def test_record_sync_completion_clears_cursor_advances_watermark(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_sync_checkpoint(
            "shopify", "primary",
            resume_cursor=None,  # cleared
            watermark="2026-02-28T12:00:00Z",  # advanced
            row_count=150,
        )
        state = registry.get_state("shopify", "primary")
        assert state.resume_cursor is None
        assert state.last_completed_watermark == "2026-02-28T12:00:00Z"
        assert state.last_sync_row_count == 150

    def test_record_health_check_ok(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_health_check("shopify", "primary", ok=True)
        state = registry.get_state("shopify", "primary")
        assert state.last_health_ok is True
        assert state.last_health_check_at is not None

    def test_record_health_check_failure(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.record_health_check(
            "shopify", "primary", ok=False,
            error_code="UPSTREAM_ERROR", error_message="503 from Shopify",
        )
        state = registry.get_state("shopify", "primary")
        assert state.last_health_ok is False
        assert state.last_error_code == "UPSTREAM_ERROR"

    def test_record_capabilities(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        manifest = {"supports": ["orders.list"], "limits": {}, "paging": {}}
        registry.record_capabilities("shopify", "primary", manifest, "abc123", "1.0")
        state = registry.get_state("shopify", "primary")
        assert state.capabilities_hash == "abc123"
        assert state.capabilities_contract_version == "1.0"

    def test_list_states(self, registry):
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.update_state("amazon", "us_store", connection_status="disconnected")
        states = registry.list_states()
        assert len(states) == 2


class TestCredentialRefNamespacing:
    """Verify credentials are checked with namespaced keys: {platform}:{ref}:{key}."""

    @patch("src.services.platform_registry.KeyringStore")
    def test_has_credentials_checks_namespaced_keys(self, mock_keyring_cls, registry):
        mock_keyring = MagicMock()
        calls = []
        def has_side_effect(key):
            calls.append(key)
            return True
        mock_keyring.has.side_effect = has_side_effect
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")
        summaries = registry.get_platforms_summary()

        # Verify keys are namespaced as shopify:primary:ACCESS_TOKEN etc.
        shopify_calls = [c for c in calls if c.startswith("shopify:primary:")]
        assert len(shopify_calls) > 0
        assert "shopify:primary:ACCESS_TOKEN" in shopify_calls


class TestPlatformSummary:
    @patch("src.services.platform_registry.KeyringStore")
    def test_get_platforms_summary(self, mock_keyring_cls, registry):
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")

        summaries = registry.get_platforms_summary()
        shopify_summaries = [s for s in summaries if s.platform_id == "shopify"]
        assert len(shopify_summaries) >= 1
        assert shopify_summaries[0].has_credentials is True


class TestResolveAuthArgs:
    """Test resolve_auth_args credential resolution for auth.connect."""

    @patch("src.services.platform_registry.KeyringStore")
    def test_dummy_returns_only_credential_ref(self, mock_ks_cls, registry):
        """Dummy has no required secrets, so result is just credential_ref."""
        mock_ks = MagicMock()
        mock_ks_cls.return_value = mock_ks
        args = registry.resolve_auth_args("dummy", "test")
        assert args == {"credential_ref": "test"}

    @patch("src.services.platform_registry.KeyringStore")
    def test_shopify_resolves_all_secrets(self, mock_ks_cls, registry):
        """Shopify requires ACCESS_TOKEN and STORE_DOMAIN."""
        mock_ks = MagicMock()
        mock_ks.get.side_effect = lambda key: {
            "shopify:primary:ACCESS_TOKEN": "shpat_xxx",
            "shopify:primary:STORE_DOMAIN": "test-store.myshopify.com",
        }.get(key)
        mock_ks_cls.return_value = mock_ks

        args = registry.resolve_auth_args("shopify", "primary")
        assert args["credential_ref"] == "primary"
        assert args["access_token"] == "shpat_xxx"
        assert args["store_domain"] == "test-store.myshopify.com"

    @patch("src.services.platform_registry.KeyringStore")
    def test_amazon_resolves_sp_api_secrets(self, mock_ks_cls, registry):
        """Amazon maps SP_API_* keyring keys to auth.connect param names."""
        mock_ks = MagicMock()
        mock_ks.get.side_effect = lambda key: {
            "amazon:primary:SP_API_CLIENT_ID": "amzn1.app.xxx",
            "amazon:primary:SP_API_CLIENT_SECRET": "secret123",
            "amazon:primary:SP_API_REFRESH_TOKEN": "Atzr|refresh",
            "amazon:primary:MARKETPLACE_ID": "ATVPDKIKX0DER",
        }.get(key)
        mock_ks_cls.return_value = mock_ks

        args = registry.resolve_auth_args("amazon", "primary")
        assert args["client_id"] == "amzn1.app.xxx"
        assert args["client_secret"] == "secret123"
        assert args["refresh_token"] == "Atzr|refresh"
        assert args["marketplace_id"] == "ATVPDKIKX0DER"

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_missing_secret_raises_auth_required(self, mock_ks_cls, mock_resolve, registry):
        """Missing credentials in both keyring and DB raises AUTH_REQUIRED."""
        mock_ks = MagicMock()
        mock_ks.get.return_value = None  # All keyring keys missing
        mock_ks_cls.return_value = mock_ks
        mock_resolve.return_value = None  # DB also empty

        with pytest.raises(PlatformError) as exc_info:
            registry.resolve_auth_args("shopify", "primary")
        assert exc_info.value.error_code == PlatformErrorCode.AUTH_REQUIRED
        assert "ACCESS_TOKEN" in exc_info.value.message

    def test_unknown_platform_raises(self, registry):
        """Unknown platform raises PlatformError."""
        with pytest.raises(PlatformError) as exc_info:
            registry.resolve_auth_args("nonexistent", "primary")
        assert exc_info.value.error_code == PlatformErrorCode.INVALID_ARGUMENT

    def test_secret_to_auth_param_covers_all_platforms(self):
        """Every platform in PLATFORM_CONFIGS has a SECRET_TO_AUTH_PARAM entry."""
        for pid in PLATFORM_CONFIGS:
            assert pid in SECRET_TO_AUTH_PARAM, f"Missing mapping for {pid}"

    def test_secret_to_auth_param_covers_all_keys(self):
        """Every required_secret_key has a mapping in SECRET_TO_AUTH_PARAM."""
        for pid, config in PLATFORM_CONFIGS.items():
            mapping = SECRET_TO_AUTH_PARAM[pid]
            for key in config.required_secret_keys:
                assert key in mapping, (
                    f"Missing mapping for {pid}/{key}"
                )


class TestDBFallbackCredentials:
    """Test credential resolution from ConnectionService encrypted DB."""

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_shopify_falls_back_to_db(self, mock_ks_cls, mock_resolve, registry):
        """Shopify credentials resolved from DB when keyring is empty."""
        from src.services.connection_types import ShopifyLegacyCredentials

        # Keyring returns nothing
        mock_ks = MagicMock()
        mock_ks.get.return_value = None
        mock_ks_cls.return_value = mock_ks

        # DB returns credentials
        mock_resolve.return_value = ShopifyLegacyCredentials(
            access_token="shpat_from_db",
            store_domain="db-store.myshopify.com",
        )

        args = registry.resolve_auth_args("shopify", "primary")
        assert args["credential_ref"] == "primary"
        assert args["access_token"] == "shpat_from_db"
        assert args["store_domain"] == "db-store.myshopify.com"

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_keyring_takes_priority_over_db(self, mock_ks_cls, mock_resolve, registry):
        """Keyring credentials used when available, DB not consulted."""
        from src.services.connection_types import ShopifyLegacyCredentials

        # Keyring has credentials
        mock_ks = MagicMock()
        mock_ks.get.side_effect = lambda key: {
            "shopify:primary:ACCESS_TOKEN": "shpat_keyring",
            "shopify:primary:STORE_DOMAIN": "keyring-store.myshopify.com",
        }.get(key)
        mock_ks_cls.return_value = mock_ks

        # DB also has credentials (should not be used)
        mock_resolve.return_value = ShopifyLegacyCredentials(
            access_token="shpat_db",
            store_domain="db-store.myshopify.com",
        )

        args = registry.resolve_auth_args("shopify", "primary")
        assert args["access_token"] == "shpat_keyring"
        assert args["store_domain"] == "keyring-store.myshopify.com"
        mock_resolve.assert_not_called()

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_has_credentials_true_from_db(self, mock_ks_cls, mock_resolve, registry):
        """has_credentials returns True when DB has credentials but keyring is empty."""
        from src.services.connection_types import ShopifyLegacyCredentials

        mock_ks = MagicMock()
        mock_ks.has.return_value = False  # Keyring empty
        mock_ks_cls.return_value = mock_ks

        mock_resolve.return_value = ShopifyLegacyCredentials(
            access_token="shpat_db",
            store_domain="db-store.myshopify.com",
        )

        registry.update_state("shopify", "primary", connection_status="connected")
        summaries = registry.get_platforms_summary()
        shopify_summaries = [s for s in summaries if s.platform_id == "shopify"]
        assert len(shopify_summaries) >= 1
        assert shopify_summaries[0].has_credentials is True

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_shopify_client_credentials_from_db(self, mock_ks_cls, mock_resolve, registry):
        """ShopifyClientCredentials access_token is extracted correctly."""
        from src.services.connection_types import ShopifyClientCredentials

        mock_ks = MagicMock()
        mock_ks.get.return_value = None
        mock_ks_cls.return_value = mock_ks

        mock_resolve.return_value = ShopifyClientCredentials(
            client_id="client_id_xxx",
            client_secret="client_secret_xxx",
            store_domain="client-store.myshopify.com",
            access_token="shpat_client",
        )

        args = registry.resolve_auth_args("shopify", "primary")
        assert args["access_token"] == "shpat_client"
        assert args["store_domain"] == "client-store.myshopify.com"

    @patch("src.services.platform_registry.KeyringStore")
    def test_amazon_no_db_fallback_raises(self, mock_ks_cls, registry):
        """Amazon has no DB fallback yet — raises AUTH_REQUIRED when keyring empty."""
        mock_ks = MagicMock()
        mock_ks.get.return_value = None
        mock_ks_cls.return_value = mock_ks

        with pytest.raises(PlatformError) as exc_info:
            registry.resolve_auth_args("amazon", "primary")
        assert exc_info.value.error_code == PlatformErrorCode.AUTH_REQUIRED

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_shopify_db_fallback_uses_store_domain_from_state(
        self, mock_ks_cls, mock_resolve, registry,
    ):
        """Multi-store: DB fallback passes account_label as store_domain."""
        from src.services.connection_types import ShopifyLegacyCredentials

        mock_ks = MagicMock()
        mock_ks.get.return_value = None
        mock_ks_cls.return_value = mock_ks

        # State has account_label set from a previous auth.connect
        registry.update_state(
            "shopify", "secondary",
            connection_status="connected",
            account_label="secondary-store.myshopify.com",
        )

        mock_resolve.return_value = ShopifyLegacyCredentials(
            access_token="shpat_secondary",
            store_domain="secondary-store.myshopify.com",
        )

        args = registry.resolve_auth_args("shopify", "secondary")
        assert args["store_domain"] == "secondary-store.myshopify.com"
        assert args["access_token"] == "shpat_secondary"

        # Verify resolve_shopify_credentials was called with store_domain
        mock_resolve.assert_called_once_with(
            store_domain="secondary-store.myshopify.com",
        )

    @patch("src.services.platform_registry.resolve_shopify_credentials")
    @patch("src.services.platform_registry.KeyringStore")
    def test_shopify_db_fallback_no_state_uses_first_available(
        self, mock_ks_cls, mock_resolve, registry,
    ):
        """When no state exists, DB fallback uses first available (store_domain=None)."""
        from src.services.connection_types import ShopifyLegacyCredentials

        mock_ks = MagicMock()
        mock_ks.get.return_value = None
        mock_ks_cls.return_value = mock_ks

        # No state exists for this credential_ref
        mock_resolve.return_value = ShopifyLegacyCredentials(
            access_token="shpat_first",
            store_domain="first-store.myshopify.com",
        )

        args = registry.resolve_auth_args("shopify", "new_ref")
        assert args["access_token"] == "shpat_first"

        # Verify resolve_shopify_credentials was called without store_domain
        mock_resolve.assert_called_once_with(store_domain=None)
