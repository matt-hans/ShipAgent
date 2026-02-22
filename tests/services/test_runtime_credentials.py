"""Tests for runtime credential adapter (DB priority, env fallback)."""

import logging
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


@pytest.fixture
def db_session():
    """Provide in-memory DB session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
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
    runtime_credentials._ups_dual_env_warned = False
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


class TestResolverAutoAcquiresDB:
    """Tests for the critical path: resolver called without db= parameter.

    This is how all real call sites invoke the resolver — without passing
    a DB session. The resolver must auto-acquire a session from SessionLocal
    to read DB-stored credentials.
    """

    def test_ups_resolver_no_db_reads_from_database(self, db_session, key_dir):
        """UPS resolver auto-acquires DB session and reads credentials."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        # Save credentials to DB
        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "auto_id", "client_secret": "auto_sec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )

        # Clear env vars so only DB can provide creds
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)

        # Patch SessionLocal to return our test session
        mock_session_factory = sessionmaker(bind=db_session.get_bind())
        with patch("src.db.connection.SessionLocal", mock_session_factory):
            result = resolve_ups_credentials(environment="production", key_dir=key_dir)

        assert result is not None
        assert result.client_id == "auto_id"
        assert result.client_secret == "auto_sec"

    def test_shopify_resolver_no_db_reads_from_database(self, db_session, key_dir):
        """Shopify resolver auto-acquires DB session and reads credentials."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        # Save credentials to DB
        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "auto_tok"},
            metadata={"store_domain": "auto.myshopify.com"}, display_name="Auto",
        )

        # Clear env vars
        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)

        mock_session_factory = sessionmaker(bind=db_session.get_bind())
        with patch("src.db.connection.SessionLocal", mock_session_factory):
            result = resolve_shopify_credentials(key_dir=key_dir)

        assert result is not None
        assert result.access_token == "auto_tok"
        assert result.store_domain == "auto.myshopify.com"

    def test_ups_auto_db_falls_back_to_env_when_no_db_rows(self, db_session, key_dir):
        """When DB has no rows, auto-acquire still falls back to env."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            mock_session_factory = sessionmaker(bind=db_session.get_bind())
            with patch("src.db.connection.SessionLocal", mock_session_factory):
                result = resolve_ups_credentials(environment="test", key_dir=key_dir)
            assert result is not None
            assert result.client_id == "env_id"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_ups_auto_db_graceful_on_session_failure(self, key_dir):
        """When SessionLocal fails, falls back to env vars gracefully."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            def broken_session():
                raise RuntimeError("DB unavailable")

            with patch("src.db.connection.SessionLocal", broken_session):
                result = resolve_ups_credentials(environment="test", key_dir=key_dir)
            assert result is not None
            assert result.client_id == "env_id"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_ups_environment_none_discovers_stored_env(self, db_session, key_dir):
        """When environment=None, resolver discovers stored connections."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)

        mock_session_factory = sessionmaker(bind=db_session.get_bind())
        with patch("src.db.connection.SessionLocal", mock_session_factory):
            result = resolve_ups_credentials(key_dir=key_dir)

        assert result is not None
        assert result.environment == "test"
        assert result.client_id == "test_id"


class TestUPSAccountNumberFlow:
    """Tests for consistent UPS account number resolution."""

    def test_account_number_stored_in_credentials(self, db_session, key_dir):
        """Account number in credentials is returned by resolver."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec", "account_number": "123456"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert result is not None
        assert result.account_number == "123456"

    def test_account_number_from_metadata_fallback(self, db_session, key_dir):
        """Account number in metadata is returned when not in credentials."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={"account_number": "654321"}, environment="test", display_name="UPS Test",
        )
        result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert result is not None
        assert result.account_number == "654321"

    def test_account_number_env_fallback(self, key_dir):
        """Account number falls back to env when not in DB."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "id"
        os.environ["UPS_CLIENT_SECRET"] = "sec"
        os.environ["UPS_ACCOUNT_NUMBER"] = "ENV999"
        try:
            result = resolve_ups_credentials(environment="test")
            assert result is not None
            # Env fallback populates account_number from env
            assert result.account_number == "ENV999"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)
            os.environ.pop("UPS_ACCOUNT_NUMBER", None)

    def test_account_number_in_allowlist(self):
        """Account number is accepted by credential allowlist validation."""
        from src.services.connection_service import _validate_credential_keys

        # Should not raise
        _validate_credential_keys("ups", "client_credentials", {
            "client_id": "id", "client_secret": "sec", "account_number": "123456",
        })

    def test_account_number_max_length(self):
        """Account number exceeding max length is rejected."""
        from src.services.connection_service import _validate_credential_keys
        from src.services.connection_types import ConnectionValidationError

        with pytest.raises(ConnectionValidationError, match="VALUE_TOO_LONG"):
            _validate_credential_keys("ups", "client_credentials", {
                "client_id": "id", "client_secret": "sec",
                "account_number": "X" * 11,  # Max is 10
            })


class TestResponseContractAlignment:
    """Tests ensuring backend response matches frontend ProviderConnectionInfo type."""

    def test_response_includes_id_field(self, db_session, key_dir):
        """Response dict includes 'id' field matching DB row id."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        connections = service.list_connections()
        assert len(connections) == 1
        assert "id" in connections[0]
        assert connections[0]["id"] is not None
        assert len(connections[0]["id"]) > 0  # UUID string

    def test_response_includes_last_validated_at(self, db_session, key_dir):
        """Response dict includes 'last_validated_at' (null for now)."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        connections = service.list_connections()
        assert "last_validated_at" in connections[0]
        assert connections[0]["last_validated_at"] is None


class TestShopifyPayloadContract:
    """Tests ensuring Shopify form payload shape matches backend expectations."""

    def test_store_domain_must_be_in_metadata(self, db_session, key_dir):
        """Backend requires store_domain in metadata, not credentials."""
        from src.services.connection_service import ConnectionService
        from src.services.connection_types import ConnectionValidationError

        service = ConnectionService(db=db_session, key_dir=key_dir)

        # store_domain only in credentials (not metadata) should fail
        with pytest.raises(ConnectionValidationError):
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": "tok", "store_domain": "s.myshopify.com"},
                metadata={},  # Missing store_domain here
                display_name="Store",
            )

    def test_empty_metadata_fails_for_shopify(self, db_session, key_dir):
        """Shopify without store_domain in metadata is rejected."""
        from src.services.connection_service import ConnectionService
        from src.services.connection_types import ConnectionValidationError

        service = ConnectionService(db=db_session, key_dir=key_dir)
        with pytest.raises(ConnectionValidationError, match="store_domain is required"):
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": "tok"},
                metadata={},
                display_name="Store",
            )

    def test_correct_payload_shape_succeeds(self, db_session, key_dir):
        """Correct payload with store_domain in metadata succeeds."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "correct.myshopify.com"},
            display_name="Store",
        )
        assert result["is_new"] is True
        assert result["runtime_usable"] is True


class TestEnvironmentSelectionSafety:
    """Tests for safe environment auto-selection when both envs are configured."""

    def test_both_envs_logs_warning(self, db_session, key_dir, caplog):
        """Warning is logged when both test and production credentials exist."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "prod_id", "client_secret": "prod_sec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_BASE_URL"):
            os.environ.pop(var, None)

        with caplog.at_level(logging.WARNING):
            result = resolve_ups_credentials(environment=None, db=db_session, key_dir=key_dir)

        assert result is not None
        assert any("both" in msg.lower() for msg in caplog.messages)

    def test_both_envs_respects_base_url_hint(self, db_session, key_dir):
        """Auto-selection uses UPS_BASE_URL to pick the preferred environment."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "prod_id", "client_secret": "prod_sec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        # Set UPS_BASE_URL to CIE → should prefer test
        os.environ["UPS_BASE_URL"] = "https://wwwcie.ups.com"
        try:
            result = resolve_ups_credentials(environment=None, db=db_session, key_dir=key_dir)
            assert result is not None
            assert result.environment == "test"
            assert result.client_id == "test_id"
        finally:
            os.environ.pop("UPS_BASE_URL", None)

    def test_explicit_env_skips_auto_selection(self, db_session, key_dir, caplog):
        """Explicit environment= bypasses auto-selection and warning."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "prod_id", "client_secret": "prod_sec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        with caplog.at_level(logging.WARNING):
            result = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)

        assert result is not None
        assert result.environment == "test"
        # No "both" warning when explicit
        assert not any("both" in msg.lower() for msg in caplog.messages)

    def test_single_env_no_warning(self, db_session, key_dir, caplog):
        """No warning when only one environment is configured."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)

        with caplog.at_level(logging.WARNING):
            result = resolve_ups_credentials(environment=None, db=db_session, key_dir=key_dir)

        assert result is not None
        assert result.environment == "test"
        assert not any("both" in msg.lower() for msg in caplog.messages)


class TestNarrowedExceptionHandling:
    """Tests for narrowed exception handling in auto-acquire paths."""

    def test_operational_error_falls_back_with_warning(self, key_dir, caplog):
        """OperationalError from SessionLocal falls back to env with warning."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            def broken_session():
                raise OperationalError("select 1", {}, Exception("db locked"))

            with caplog.at_level(logging.WARNING):
                with patch("src.db.connection.SessionLocal", broken_session):
                    result = resolve_ups_credentials(environment="test", key_dir=key_dir)

            assert result is not None
            assert result.client_id == "env_id"
            assert any("auto-acquire" in msg.lower() for msg in caplog.messages)
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_import_error_falls_back_with_warning(self, key_dir, caplog):
        """ImportError from SessionLocal falls back to env with warning."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            def broken_session():
                raise ImportError("No module named src.db.connection")

            with caplog.at_level(logging.WARNING):
                with patch("src.db.connection.SessionLocal", broken_session):
                    result = resolve_ups_credentials(environment="test", key_dir=key_dir)

            assert result is not None
            assert result.client_id == "env_id"
            assert any("auto-acquire" in msg.lower() for msg in caplog.messages)
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_unexpected_error_falls_back_with_exc_info(self, key_dir, caplog):
        """Unexpected exceptions fall back to env with exc_info logged."""
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            def broken_session():
                raise ValueError("something unexpected")

            with caplog.at_level(logging.WARNING):
                with patch("src.db.connection.SessionLocal", broken_session):
                    result = resolve_ups_credentials(environment="test", key_dir=key_dir)

            assert result is not None
            assert result.client_id == "env_id"
            assert any("unexpected" in msg.lower() for msg in caplog.messages)
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)


class TestDualEnvWarningGuard:
    """Tests that the dual-env warning only fires once per process."""

    def test_dual_env_warning_fires_only_once(self, db_session, key_dir, caplog):
        """Repeated resolve calls with both envs only warn once."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "prod_id", "client_secret": "prod_sec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_BASE_URL"):
            os.environ.pop(var, None)

        with caplog.at_level(logging.WARNING):
            resolve_ups_credentials(environment=None, db=db_session, key_dir=key_dir)
            resolve_ups_credentials(environment=None, db=db_session, key_dir=key_dir)
            resolve_ups_credentials(environment=None, db=db_session, key_dir=key_dir)

        both_warnings = [m for m in caplog.messages if "both" in m.lower()]
        assert len(both_warnings) == 1
