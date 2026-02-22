"""Tests for ConnectionService — CRUD, validation, resolvers, runtime_usable."""

import json
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderConnection
from src.services.connection_service import ConnectionService
from src.services.connection_types import (
    ConnectionValidationError,
    ShopifyClientCredentials,
    ShopifyLegacyCredentials,
    UPSCredentials,
)


@pytest.fixture
def temp_key_dir(tmp_path):
    """Provide a temporary directory for encryption key storage."""
    return str(tmp_path)


@pytest.fixture
def db_session():
    """Provide an in-memory SQLAlchemy session with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def service(db_session, temp_key_dir):
    """Provide a ConnectionService with in-memory DB and temp key."""
    return ConnectionService(db_session, key_dir=temp_key_dir)


# ============================================================
# Task 4A: CRUD, Validation
# ============================================================


class TestConnectionServiceCRUD:

    def test_save_ups_connection(self, service):
        """Save a UPS connection and verify result."""
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        assert result["is_new"] is True
        assert result["connection_key"] == "ups:test"
        assert result["auth_mode"] == "client_credentials"

    def test_save_shopify_connection(self, service):
        """Save a Shopify legacy_token connection."""
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_abc123"},
            metadata={"store_domain": "mystore.myshopify.com"},
            display_name="My Store",
        )
        assert result["is_new"] is True
        assert result["connection_key"] == "shopify:mystore.myshopify.com"

    def test_get_connection(self, service):
        """Get a saved connection by key."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        conn = service.get_connection("ups:test")
        assert conn is not None
        assert conn["provider"] == "ups"
        assert conn["status"] == "configured"
        # Credentials must NOT be exposed
        assert "encrypted_credentials" not in conn
        assert "client_id" not in conn
        assert "client_secret" not in conn

    def test_get_connection_not_found(self, service):
        """Get returns None for missing key."""
        assert service.get_connection("ups:nonexistent") is None

    def test_list_connections_empty(self, service):
        """List returns empty list when no connections."""
        assert service.list_connections() == []

    def test_list_connections_ordered(self, service):
        """List returns connections ordered by provider, connection_key."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "alpha.myshopify.com"},
            display_name="Alpha Store",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS Test",
        )

        connections = service.list_connections()
        assert len(connections) == 3
        keys = [c["connection_key"] for c in connections]
        # Shopify first (alphabetically before ups), then ups sorted by key
        assert keys == [
            "shopify:alpha.myshopify.com",
            "ups:production",
            "ups:test",
        ]

    def test_list_connections_include_runtime_usable(self, service):
        """List includes runtime_usable field."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        connections = service.list_connections()
        assert "runtime_usable" in connections[0]

    def test_delete_connection(self, service):
        """Delete removes connection and returns True."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        assert service.delete_connection("ups:test") is True
        assert service.get_connection("ups:test") is None

    def test_delete_not_found(self, service):
        """Delete returns False for missing key."""
        assert service.delete_connection("ups:nonexistent") is False

    def test_overwrite_connection(self, service):
        """Overwriting returns is_new=False and updates fields."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS v1",
        )
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS v2",
        )
        assert result["is_new"] is False
        conn = service.get_connection("ups:test")
        assert conn["display_name"] == "UPS v2"

    def test_updated_at_changes_on_overwrite(self, service):
        """updated_at timestamp changes on overwrite."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn1 = service.get_connection("ups:test")
        ts1 = conn1["updated_at"]

        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS v2",
        )
        conn2 = service.get_connection("ups:test")
        # Timestamps are ISO strings — may be equal if same second
        assert conn2["updated_at"] is not None
        assert conn2["updated_at"] >= ts1


class TestConnectionServiceValidation:

    def test_invalid_provider(self, service):
        """Invalid provider raises ConnectionValidationError."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="fedex", auth_mode="client_credentials",
                credentials={}, metadata={}, environment="test",
                display_name="FedEx",
            )
        assert exc_info.value.code == "INVALID_PROVIDER"

    def test_invalid_auth_mode(self, service):
        """Invalid auth_mode raises ConnectionValidationError."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="oauth2",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "INVALID_AUTH_MODE"

    def test_missing_ups_client_id(self, service):
        """Missing client_id for UPS raises error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_secret": "sec"},
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "MISSING_FIELD"

    def test_missing_ups_client_secret(self, service):
        """Missing client_secret for UPS raises error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id"},
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "MISSING_FIELD"

    def test_missing_shopify_store_domain(self, service):
        """Missing store_domain for Shopify raises error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": "tok"},
                metadata={}, display_name="Store",
            )
        assert exc_info.value.code == "MISSING_FIELD"

    def test_missing_shopify_access_token_legacy(self, service):
        """Missing access_token for Shopify legacy_token raises error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={},
                metadata={"store_domain": "s.myshopify.com"},
                display_name="Store",
            )
        assert exc_info.value.code == "MISSING_FIELD"

    def test_client_credentials_shopify_no_access_token_ok(self, service):
        """client_credentials_shopify does NOT require access_token (Phase 2)."""
        result = service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        assert result["is_new"] is True

    def test_ups_environment_empty_rejected(self, service):
        """Empty UPS environment is rejected."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment="", display_name="UPS",
            )
        assert exc_info.value.code == "INVALID_ENVIRONMENT"

    def test_ups_environment_none_rejected(self, service):
        """None UPS environment is rejected."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment=None, display_name="UPS",
            )
        assert exc_info.value.code == "INVALID_ENVIRONMENT"

    def test_ups_environment_sandbox_rejected(self, service):
        """'sandbox' is not a valid UPS environment."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment="sandbox", display_name="UPS",
            )
        assert exc_info.value.code == "INVALID_ENVIRONMENT"

    def test_domain_normalization(self, service):
        """Shopify domain is normalized (lowercase, strip protocol/slashes)."""
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "HTTPS://MyStore.MyShopify.com/"},
            display_name="Store",
        )
        assert result["connection_key"] == "shopify:mystore.myshopify.com"

    def test_invalid_domain_rejected(self, service):
        """Invalid Shopify domain raises error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": "tok"},
                metadata={"store_domain": "not-a-shopify-domain.com"},
                display_name="Store",
            )
        assert exc_info.value.code == "INVALID_DOMAIN"

    def test_unknown_credential_key_rejected(self, service):
        """Unknown credential keys raise error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec", "rogue_key": "val"},
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "UNKNOWN_CREDENTIAL_KEY"

    def test_credential_max_length_rejected(self, service):
        """Excessively long credential value raises error."""
        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "x" * 2000, "client_secret": "sec"},
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "VALUE_TOO_LONG"


class TestConnectionServiceDisconnect:

    def test_disconnect_sets_status(self, service):
        """Disconnect sets status to 'disconnected'."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = service.disconnect("ups:test")
        assert conn is not None
        assert conn["status"] == "disconnected"

    def test_disconnect_preserves_credentials(self, service):
        """Disconnect doesn't delete the row — credentials preserved for reconnect."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        conn = service.get_connection("ups:test")
        assert conn is not None  # Row still exists

    def test_disconnect_not_found(self, service):
        """Disconnect returns None for missing key."""
        assert service.disconnect("ups:nonexistent") is None

    def test_resave_on_disconnected_resets_status(self, service):
        """Re-saving on a disconnected row resets status to 'configured'."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "new_id", "client_secret": "new_sec"},
            metadata={}, environment="test", display_name="UPS v2",
        )
        assert result["is_new"] is False
        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"


class TestConnectionServiceErrors:

    def test_sanitize_error_message(self, service):
        """Error messages are sanitized before DB persistence."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status(
            "ups:test", "error",
            error_code="AUTH_FAILED",
            error_message="token=secret123 failed with client_secret=abc",
        )
        conn = service.get_connection("ups:test")
        assert "secret123" not in (conn["error_message"] or "")
        assert "abc" not in (conn["error_message"] or "")

    def test_valid_statuses_enforcement(self, service):
        """update_status with unknown status raises ValueError."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        with pytest.raises(ValueError, match="Invalid status"):
            service.update_status("ups:test", "bogus_status")

    def test_corrupt_metadata_json_returns_empty(self, service, db_session):
        """Row with invalid metadata_json returns {} in get_connection."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        # Corrupt the metadata_json directly
        row = db_session.query(ProviderConnection).filter_by(
            connection_key="ups:test"
        ).first()
        row.metadata_json = "not valid json{{"
        db_session.commit()

        conn = service.get_connection("ups:test")
        assert conn["metadata"] == {}


class TestConnectionServiceStubs:

    def test_check_all_returns_ok_for_valid(self, service):
        """check_all() returns 'ok' for valid decryptable connection."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        results = service.check_all()
        assert results == {"ups:test": "ok"}

    def test_key_version_always_one(self, service):
        """New connections have key_version == 1."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = service.get_connection("ups:test")
        assert conn.get("key_version", 1) == 1


# ============================================================
# Task 4B: Resolvers, Runtime Usability, Decrypt Resilience
# ============================================================


class TestRuntimeUsable:

    def test_runtime_usable_configured_ups(self, service):
        """Configured UPS connection is runtime-usable."""
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        assert result["runtime_usable"] is True
        assert result["runtime_reason"] is None

    def test_runtime_usable_configured_legacy(self, service):
        """Configured legacy_token connection is runtime-usable."""
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        assert result["runtime_usable"] is True
        assert result["runtime_reason"] is None

    def test_runtime_usable_false_for_client_credentials_no_token(self, service):
        """client_credentials_shopify without token is NOT runtime-usable."""
        result = service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        assert result["runtime_usable"] is False
        assert result["runtime_reason"] == "missing_access_token"

    def test_runtime_usable_false_for_disconnected(self, service):
        """Disconnected connection is NOT runtime-usable."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        conn = service.get_connection("ups:test")
        assert conn["runtime_usable"] is False
        assert conn["runtime_reason"] == "disconnected"


class TestUPSResolver:

    def test_get_ups_credentials_returns_typed(self, service):
        """get_ups_credentials returns UPSCredentials dataclass."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "myid", "client_secret": "mysec"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        creds = service.get_ups_credentials("test")
        assert isinstance(creds, UPSCredentials)
        assert creds.client_id == "myid"
        assert creds.client_secret == "mysec"
        assert creds.environment == "test"
        assert creds.base_url == "https://wwwcie.ups.com"

    def test_get_ups_credentials_production(self, service):
        """Production environment returns production base URL."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "pid", "client_secret": "psec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        creds = service.get_ups_credentials("production")
        assert creds.base_url == "https://onlinetools.ups.com"

    def test_get_ups_credentials_not_found(self, service):
        """get_ups_credentials returns None when not found."""
        assert service.get_ups_credentials("test") is None

    def test_get_ups_credentials_skips_disconnected(self, service):
        """get_ups_credentials skips disconnected rows."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        assert service.get_ups_credentials("test") is None


class TestShopifyResolver:

    def test_get_shopify_credentials_legacy(self, service):
        """get_shopify_credentials returns ShopifyLegacyCredentials."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_abc"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        creds = service.get_shopify_credentials("s.myshopify.com")
        assert isinstance(creds, ShopifyLegacyCredentials)
        assert creds.access_token == "shpat_abc"
        assert creds.store_domain == "s.myshopify.com"

    def test_get_shopify_credentials_client(self, service):
        """get_shopify_credentials returns ShopifyClientCredentials."""
        service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec", "access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        creds = service.get_shopify_credentials("s.myshopify.com")
        assert isinstance(creds, ShopifyClientCredentials)
        assert creds.client_id == "cid"
        assert creds.access_token == "tok"

    def test_get_shopify_credentials_skips_disconnected(self, service):
        """get_shopify_credentials skips disconnected rows."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        service.disconnect("shopify:s.myshopify.com")
        assert service.get_shopify_credentials("s.myshopify.com") is None

    def test_get_shopify_credentials_not_found(self, service):
        """get_shopify_credentials returns None when not found."""
        assert service.get_shopify_credentials("unknown.myshopify.com") is None

    def test_get_first_shopify_credentials_deterministic(self, service):
        """get_first_shopify_credentials returns alphabetically first."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok2"},
            metadata={"store_domain": "zeta.myshopify.com"},
            display_name="Zeta",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok1"},
            metadata={"store_domain": "alpha.myshopify.com"},
            display_name="Alpha",
        )
        creds = service.get_first_shopify_credentials()
        assert isinstance(creds, ShopifyLegacyCredentials)
        assert creds.store_domain == "alpha.myshopify.com"

    def test_get_first_shopify_credentials_skips_disconnected(self, service):
        """get_first_shopify_credentials skips disconnected rows."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok1"},
            metadata={"store_domain": "alpha.myshopify.com"},
            display_name="Alpha",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok2"},
            metadata={"store_domain": "beta.myshopify.com"},
            display_name="Beta",
        )
        service.disconnect("shopify:alpha.myshopify.com")
        creds = service.get_first_shopify_credentials()
        assert creds.store_domain == "beta.myshopify.com"

    def test_get_first_shopify_credentials_none(self, service):
        """get_first_shopify_credentials returns None when no Shopify connections."""
        assert service.get_first_shopify_credentials() is None


class TestAuthModeSwitching:

    def test_auth_mode_switching_on_same_key(self, service):
        """Overwrite legacy_token with client_credentials_shopify on same key."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok1"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store v1",
        )
        result = service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store v2",
        )
        assert result["is_new"] is False
        assert result["auth_mode"] == "client_credentials_shopify"
        # Decrypt still works with updated AAD
        creds = service.get_shopify_credentials("s.myshopify.com")
        assert creds is not None
        assert isinstance(creds, ShopifyClientCredentials)
        assert creds.client_id == "cid"


class TestDecryptResilience:

    def test_list_connections_decrypt_resilience(self, service, db_session):
        """list_connections doesn't crash on corrupt encrypted_credentials."""
        # Use client_credentials_shopify which triggers decrypt in _is_runtime_usable
        service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        # Corrupt the encrypted_credentials directly
        row = db_session.query(ProviderConnection).filter_by(
            connection_key="shopify:s.myshopify.com"
        ).first()
        row.encrypted_credentials = "not-valid-json"
        db_session.commit()

        connections = service.list_connections()
        assert len(connections) == 1
        # Should NOT crash — runtime_usable should be false
        assert connections[0]["runtime_usable"] is False
        assert connections[0]["runtime_reason"] == "decrypt_failed"

    def test_get_connection_decrypt_resilience(self, service, db_session):
        """get_connection doesn't crash on corrupt encrypted_credentials."""
        service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        # Corrupt the encrypted_credentials
        row = db_session.query(ProviderConnection).filter_by(
            connection_key="shopify:s.myshopify.com"
        ).first()
        row.encrypted_credentials = "corrupt-data"
        db_session.commit()

        conn = service.get_connection("shopify:s.myshopify.com")
        assert conn is not None
        assert conn["runtime_usable"] is False
        assert conn["runtime_reason"] == "decrypt_failed"

    def test_corrupt_metadata_in_resolver(self, service, db_session):
        """Resolver handles corrupt metadata_json gracefully."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        # Corrupt metadata_json
        row = db_session.query(ProviderConnection).filter_by(
            connection_key="shopify:s.myshopify.com"
        ).first()
        row.metadata_json = "{{bad}}"
        db_session.commit()

        # get_first_shopify_credentials should still work
        creds = service.get_first_shopify_credentials()
        assert creds is not None
        # store_domain will be empty since metadata is corrupt
        assert creds.store_domain == ""
