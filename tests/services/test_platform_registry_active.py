# tests/services/test_platform_registry_active.py
"""Tests for PlatformRegistry active platform selection."""
import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, PlatformSyncState
from src.services.platform_registry import PlatformRegistry


@pytest.fixture
def db_path(tmp_path):
    """Use a temp file DB (not :memory:) so sessions see the same data."""
    return str(tmp_path / "test_registry_active.db")


@pytest.fixture
def session_factory(db_path):
    """Create a SQLAlchemy session factory bound to a fresh test DB."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture
def registry(session_factory):
    """Create a PlatformRegistry with the test session factory."""
    return PlatformRegistry(session_factory)


class TestSetPlatformActive:
    """Tests for set_platform_active and is_active column."""

    def test_set_platform_active_updates_db(self, registry, session_factory):
        """Setting a platform active persists the is_active flag to the DB."""
        # Create initial state
        registry.update_state("shopify", "primary", connection_status="connected")

        # Set active
        registry.set_platform_active("shopify", "primary", True)

        # Verify directly from DB
        with session_factory() as session:
            state = session.get(PlatformSyncState, ("shopify", "primary"))
            assert state is not None
            assert state.is_active is True

    def test_set_platform_inactive_updates_db(self, registry, session_factory):
        """Setting a platform inactive persists is_active=False to the DB."""
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.set_platform_active("shopify", "primary", True)
        registry.set_platform_active("shopify", "primary", False)

        with session_factory() as session:
            state = session.get(PlatformSyncState, ("shopify", "primary"))
            assert state is not None
            assert state.is_active is False

    def test_set_platform_active_creates_state_if_missing(self, registry, session_factory):
        """set_platform_active creates a PlatformSyncState row if none exists."""
        registry.set_platform_active("shopify", "primary", True)

        with session_factory() as session:
            state = session.get(PlatformSyncState, ("shopify", "primary"))
            assert state is not None
            assert state.is_active is True

    def test_default_is_active_is_false(self, registry, session_factory):
        """New PlatformSyncState rows default to is_active=False."""
        registry.update_state("shopify", "primary", connection_status="connected")

        with session_factory() as session:
            state = session.get(PlatformSyncState, ("shopify", "primary"))
            assert state is not None
            assert state.is_active is False


class TestGetActivePlatforms:
    """Tests for get_active_platforms filter method."""

    @patch("src.services.platform_registry.KeyringStore")
    def test_get_active_platforms_filters_inactive(self, mock_keyring_cls, registry):
        """get_active_platforms only returns platforms where is_active=True."""
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        # Create two platforms, only one active
        registry.update_state("shopify", "primary", connection_status="connected")
        registry.set_platform_active("shopify", "primary", True)

        registry.update_state("amazon", "primary", connection_status="connected")
        # amazon stays inactive (default)

        active = registry.get_active_platforms()
        active_ids = [s.platform_id for s in active]
        assert "shopify" in active_ids
        assert "amazon" not in active_ids

    @patch("src.services.platform_registry.KeyringStore")
    def test_get_active_platforms_returns_empty_when_none_active(
        self, mock_keyring_cls, registry,
    ):
        """get_active_platforms returns empty list when no platforms are active."""
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")

        active = registry.get_active_platforms()
        assert active == []

    @patch("src.services.platform_registry.KeyringStore")
    def test_get_active_platforms_returns_multiple(
        self, mock_keyring_cls, registry,
    ):
        """get_active_platforms can return multiple active platforms."""
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")
        registry.set_platform_active("shopify", "primary", True)

        registry.update_state("amazon", "primary", connection_status="connected")
        registry.set_platform_active("amazon", "primary", True)

        active = registry.get_active_platforms()
        active_ids = {s.platform_id for s in active}
        assert "shopify" in active_ids
        assert "amazon" in active_ids


class TestPlatformSummaryIsActive:
    """Tests that PlatformSummary includes is_active field."""

    @patch("src.services.platform_registry.KeyringStore")
    def test_summary_includes_is_active_true(self, mock_keyring_cls, registry):
        """PlatformSummary includes is_active=True when platform is active."""
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")
        registry.set_platform_active("shopify", "primary", True)

        summaries = registry.get_platforms_summary()
        shopify = [s for s in summaries if s.platform_id == "shopify"][0]
        assert shopify.is_active is True

    @patch("src.services.platform_registry.KeyringStore")
    def test_summary_includes_is_active_false(self, mock_keyring_cls, registry):
        """PlatformSummary includes is_active=False for inactive platforms."""
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = True
        mock_keyring_cls.return_value = mock_keyring

        registry.update_state("shopify", "primary", connection_status="connected")

        summaries = registry.get_platforms_summary()
        shopify = [s for s in summaries if s.platform_id == "shopify"][0]
        assert shopify.is_active is False

    @patch("src.services.platform_registry.KeyringStore")
    def test_summary_default_no_state_is_inactive(self, mock_keyring_cls, registry):
        """Platforms with no sync state show is_active=False in summary."""
        mock_keyring = MagicMock()
        mock_keyring.has.return_value = False
        mock_keyring_cls.return_value = mock_keyring

        summaries = registry.get_platforms_summary()
        # All platforms without state should have is_active=False
        for s in summaries:
            assert s.is_active is False
