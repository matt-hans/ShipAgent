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
from src.services.platform_models import PlatformConfig, CapabilityManifest
from src.services.platform_registry import PlatformRegistry, PLATFORM_CONFIGS


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
