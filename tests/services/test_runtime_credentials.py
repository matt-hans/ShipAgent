"""Tests for runtime credential adapter (DB priority, env fallback)."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


@pytest.fixture
def db_session():
    """Provide in-memory DB session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def key_dir(tmp_path):
    """Provide temp key directory."""
    return str(tmp_path)


@pytest.fixture(autouse=True)
def reset_fallback_flags():
    """Reset per-process fallback warning flags between tests."""
    from src.services import runtime_credentials

    runtime_credentials._ups_fallback_warned = False
    runtime_credentials._shopify_fallback_warned = False
    yield


class TestResolveUPSCredentials:

    def test_db_credentials_returned(self, db_session, key_dir):
        """DB-stored credentials are returned when available."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "db_id", "client_secret": "db_sec"},
            metadata={"account_number": "ACC"}, environment="test", display_name="UPS",
        )
        result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert result is not None
        assert result.client_id == "db_id"

    def test_env_fallback(self, db_session, key_dir):
        """Falls back to env vars when no DB row."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
            assert result is not None
            assert result.client_id == "env_id"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_none_when_neither(self, db_session, key_dir):
        """Returns None when no DB and no env vars."""
        from src.services.runtime_credentials import resolve_ups_credentials

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert result is None

    def test_skip_disconnected(self, db_session, key_dir):
        """Disconnected DB rows are skipped."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert result is None

    def test_env_fallback_base_url_derivation(self, db_session, key_dir):
        """Env fallback derives base_url from environment param."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "id"
        os.environ["UPS_CLIENT_SECRET"] = "sec"
        try:
            result = resolve_ups_credentials(environment="production", db=db_session, key_dir=key_dir)
            assert result.base_url == "https://onlinetools.ups.com"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_env_fallback_base_url_mismatch_warning(self, db_session, key_dir, caplog):
        """Warns when UPS_BASE_URL conflicts with derived environment URL."""
        import logging

        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "id"
        os.environ["UPS_CLIENT_SECRET"] = "sec"
        os.environ["UPS_BASE_URL"] = "https://wwwcie.ups.com"
        try:
            with caplog.at_level(logging.WARNING):
                resolve_ups_credentials(environment="production", db=db_session, key_dir=key_dir)
            assert any("mismatch" in msg.lower() for msg in caplog.messages)
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)
            os.environ.pop("UPS_BASE_URL", None)


class TestResolveShopifyCredentials:

    def test_shopify_db_credentials(self, db_session, key_dir):
        """DB-stored Shopify credentials are returned."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"}, display_name="Store",
        )
        result = resolve_shopify_credentials(store_domain="s.myshopify.com", db=db_session, key_dir=key_dir)
        assert result is not None
        assert result.access_token == "tok"

    def test_shopify_env_fallback(self, db_session, key_dir):
        """Falls back to env vars for Shopify."""
        from src.services.runtime_credentials import resolve_shopify_credentials

        os.environ["SHOPIFY_ACCESS_TOKEN"] = "env_tok"
        os.environ["SHOPIFY_STORE_DOMAIN"] = "env.myshopify.com"
        try:
            result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
            assert result is not None
            assert result.access_token == "env_tok"
        finally:
            os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
            os.environ.pop("SHOPIFY_STORE_DOMAIN", None)

    def test_shopify_none_when_neither(self, db_session, key_dir):
        """Returns None when no DB and no env vars."""
        from src.services.runtime_credentials import resolve_shopify_credentials

        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)
        result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
        assert result is None

    def test_shopify_deterministic_default(self, db_session, key_dir):
        """First Shopify connection by connection_key ASC is returned when no domain specified."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok_b"},
            metadata={"store_domain": "b.myshopify.com"}, display_name="B",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok_a"},
            metadata={"store_domain": "a.myshopify.com"}, display_name="A",
        )
        result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
        assert result.store_domain == "a.myshopify.com"  # ASC order

    def test_empty_access_token_returns_none(self, db_session, key_dir):
        """client_credentials_shopify with empty access_token returns None."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "s.myshopify.com"}, display_name="Store",
        )
        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)
        result = resolve_shopify_credentials(store_domain="s.myshopify.com", db=db_session, key_dir=key_dir)
        assert result is None  # empty access_token

    def test_shopify_env_fallback_domain_mismatch_returns_none(self, db_session, key_dir):
        """Env fallback skips when requested domain differs from env domain."""
        from src.services.runtime_credentials import resolve_shopify_credentials

        os.environ["SHOPIFY_ACCESS_TOKEN"] = "env_tok"
        os.environ["SHOPIFY_STORE_DOMAIN"] = "store-b.myshopify.com"
        try:
            result = resolve_shopify_credentials(
                store_domain="store-a.myshopify.com", db=db_session, key_dir=key_dir,
            )
            assert result is None  # Domain mismatch — no silent cross-store usage
        finally:
            os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
            os.environ.pop("SHOPIFY_STORE_DOMAIN", None)

    def test_shopify_env_fallback_domain_match_returns_creds(self, db_session, key_dir):
        """Env fallback works when requested domain matches env domain."""
        from src.services.runtime_credentials import resolve_shopify_credentials

        os.environ["SHOPIFY_ACCESS_TOKEN"] = "env_tok"
        os.environ["SHOPIFY_STORE_DOMAIN"] = "store-a.myshopify.com"
        try:
            result = resolve_shopify_credentials(
                store_domain="store-a.myshopify.com", db=db_session, key_dir=key_dir,
            )
            assert result is not None
            assert result.access_token == "env_tok"
        finally:
            os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
            os.environ.pop("SHOPIFY_STORE_DOMAIN", None)
