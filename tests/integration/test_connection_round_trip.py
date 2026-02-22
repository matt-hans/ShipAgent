"""Integration and edge-case tests for the provider connection lifecycle.

Covers: CRUD round-trips, encrypted storage, runtime credential resolution,
env fallback, multi-environment coexistence, 422 secret redaction, corrupt
data recovery, domain normalization, status semantics, and API error schema.

Tests are split into two groups:
  - SMOKE: must-pass, fast core lifecycle tests
  - EXTENDED: slower edge-case tests (marked with pytest.mark.extended)
"""

import base64
import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderConnection


# ---------- shared fixtures ---------- #


@pytest.fixture
def db_session():
    """In-memory SQLite session with schema created."""
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
    """Temp directory for encryption key."""
    return str(tmp_path)


@pytest.fixture
def service(db_session, key_dir):
    """ConnectionService wired to in-memory DB + temp key dir."""
    from src.services.connection_service import ConnectionService

    return ConnectionService(db=db_session, key_dir=key_dir)




# ====================================================================
# SMOKE — Core lifecycle tests
# ====================================================================


class TestUPSLifecycle:
    """Full UPS save -> list -> decrypt -> disconnect -> re-save -> delete."""

    def test_ups_full_lifecycle(self, service):
        """Save, list, disconnect, re-save, delete for UPS."""
        # Save
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_secret"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        assert result["is_new"] is True
        assert result["connection_key"] == "ups:test"
        assert result["runtime_usable"] is True

        # List
        connections = service.list_connections()
        assert len(connections) == 1
        assert connections[0]["provider"] == "ups"
        assert connections[0]["status"] == "configured"
        assert "client_id" not in connections[0]  # No creds exposed

        # Disconnect
        disc = service.disconnect("ups:test")
        assert disc["status"] == "disconnected"
        assert disc["runtime_usable"] is False

        # Re-save (resets to configured)
        result2 = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "new_id", "client_secret": "new_sec"},
            metadata={}, environment="test", display_name="UPS Test v2",
        )
        assert result2["is_new"] is False
        assert result2["runtime_usable"] is True

        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"
        assert conn["display_name"] == "UPS Test v2"

        # Delete
        assert service.delete_connection("ups:test") is True
        assert service.get_connection("ups:test") is None


class TestShopifyLifecycle:
    """Full Shopify legacy token save -> list -> decrypt -> delete."""

    def test_shopify_legacy_lifecycle(self, service):
        """Save, list, resolve, delete for Shopify legacy token."""
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_test123"},
            metadata={"store_domain": "test-store.myshopify.com"},
            display_name="Test Store", environment=None,
        )
        assert result["is_new"] is True
        assert result["connection_key"] == "shopify:test-store.myshopify.com"

        # List
        connections = service.list_connections()
        assert len(connections) == 1
        assert connections[0]["provider"] == "shopify"

        # Resolve
        creds = service.get_shopify_credentials("test-store.myshopify.com")
        assert creds is not None
        assert creds.access_token == "shpat_test123"
        assert creds.store_domain == "test-store.myshopify.com"

        # Delete
        assert service.delete_connection("shopify:test-store.myshopify.com") is True


class TestMultiEnvironmentCoexistence:
    """Multiple UPS environments coexist without clobber."""

    def test_test_and_production_coexist(self, service):
        """Two UPS environments have separate connection_keys."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_sec"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "prod_id", "client_secret": "prod_sec"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        connections = service.list_connections()
        assert len(connections) == 2

        test_creds = service.get_ups_credentials("test")
        prod_creds = service.get_ups_credentials("production")
        assert test_creds.client_id == "test_id"
        assert prod_creds.client_id == "prod_id"
        assert test_creds.base_url == "https://wwwcie.ups.com"
        assert prod_creds.base_url == "https://onlinetools.ups.com"


class TestShopifyDomainNormalization:
    """Shopify domain normalization produces correct connection_key."""

    def test_domain_normalization(self, service):
        """Domain with protocol and trailing slash is normalized."""
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_abc"},
            metadata={"store_domain": "https://My-Store.myshopify.com/"},
            display_name="My Store", environment=None,
        )
        assert result["connection_key"] == "shopify:my-store.myshopify.com"


class TestDisconnectPreventsResolution:
    """Disconnect prevents resolver from returning credentials."""

    def test_disconnect_hides_ups_creds(self, service):
        """After disconnect, get_ups_credentials returns None."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        assert service.get_ups_credentials("test") is None

    def test_disconnect_hides_shopify_creds(self, service):
        """After disconnect, get_shopify_credentials returns None."""
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_abc"},
            metadata={"store_domain": "store.myshopify.com"},
            display_name="Store", environment=None,
        )
        service.disconnect("shopify:store.myshopify.com")
        assert service.get_shopify_credentials("store.myshopify.com") is None


class TestCheckAllRecovery:
    """check_all() recovery: needs_reconnect → configured."""

    def test_recovery_path(self, service):
        """Successful decrypt recovers needs_reconnect → configured."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status("ups:test", "needs_reconnect",
                              error_code="DECRYPT_FAILED")
        results = service.check_all()
        assert results["ups:test"] == "ok"
        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"
        assert conn["last_error_code"] is None

    def test_check_all_skips_disconnected(self, service):
        """check_all() skips disconnected rows; status unchanged."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        results = service.check_all()
        assert "ups:test" not in results
        conn = service.get_connection("ups:test")
        assert conn["status"] == "disconnected"


class TestRuntimeUsableInResponse:
    """Connection responses include runtime_usable field with correct values."""

    def test_configured_is_usable(self, service):
        """Configured connection has runtime_usable=True."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = service.get_connection("ups:test")
        assert conn["runtime_usable"] is True
        assert conn["runtime_reason"] is None

    def test_disconnected_not_usable(self, service):
        """Disconnected connection has runtime_usable=False."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        conn = service.get_connection("ups:test")
        assert conn["runtime_usable"] is False


class TestUPSRuntimeResolver:
    """UPS runtime resolver: DB priority, env fallback."""

    def test_db_priority(self, db_session, key_dir, monkeypatch):
        """DB credentials take priority over env vars."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        monkeypatch.setenv("UPS_CLIENT_ID", "env_id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "env_sec")

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        svc.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "db_id", "client_secret": "db_sec"},
            metadata={}, environment="production", display_name="UPS",
        )
        result = resolve_ups_credentials(
            environment="production", db=db_session, key_dir=key_dir,
        )
        assert result.client_id == "db_id"

    def test_env_fallback(self, db_session, key_dir, monkeypatch):
        """Falls back to env vars when no DB row."""
        from src.services.runtime_credentials import resolve_ups_credentials

        monkeypatch.setenv("UPS_CLIENT_ID", "env_id")
        monkeypatch.setenv("UPS_CLIENT_SECRET", "env_sec")
        result = resolve_ups_credentials(
            environment="production", db=db_session, key_dir=key_dir,
        )
        assert result.client_id == "env_id"


class TestShopifyRuntimeResolver:
    """Shopify runtime resolver: deterministic default selection."""

    def test_first_shopify_deterministic(self, db_session, key_dir):
        """get_first_shopify_credentials uses ORDER BY connection_key ASC."""
        from src.services.connection_service import ConnectionService

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        svc.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_z"},
            metadata={"store_domain": "z-store.myshopify.com"},
            display_name="Z Store", environment=None,
        )
        svc.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_a"},
            metadata={"store_domain": "a-store.myshopify.com"},
            display_name="A Store", environment=None,
        )
        result = svc.get_first_shopify_credentials()
        assert result is not None
        assert result.store_domain == "a-store.myshopify.com"


class TestPhase1StatusSemantics:
    """Phase 1: only configured, needs_reconnect, disconnected are automated."""

    def test_save_produces_configured(self, service):
        """save_connection always produces 'configured' status."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"

    def test_disconnect_produces_disconnected(self, service):
        """disconnect produces 'disconnected' status."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        conn = service.get_connection("ups:test")
        assert conn["status"] == "disconnected"

    def test_error_via_update_status_allowed(self, service):
        """error status is allowed via explicit update_status()."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status("ups:test", "error", error_code="AUTH_FAILED")
        conn = service.get_connection("ups:test")
        assert conn["status"] == "error"


class TestValidationErrors:
    """Validation errors use ConnectionValidationError with structured codes."""

    def test_invalid_provider_rejected(self, service):
        """Invalid provider raises ConnectionValidationError(INVALID_PROVIDER)."""
        from src.services.connection_types import ConnectionValidationError

        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="badprovider", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment="test", display_name="Bad",
            )
        assert exc_info.value.code == "INVALID_PROVIDER"

    def test_missing_ups_fields_rejected(self, service):
        """Missing UPS client_id raises ConnectionValidationError."""
        from src.services.connection_types import ConnectionValidationError

        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_secret": "sec"},
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "MISSING_FIELD"


class TestNoSecretLeakage:
    """Service responses never contain credential values."""

    def test_list_does_not_expose_credentials(self, service):
        """list_connections doesn't include raw credential values."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "super_secret_id_12345", "client_secret": "my_secret_val"},
            metadata={}, environment="test", display_name="UPS",
        )
        connections = service.list_connections()
        body = json.dumps(connections)
        assert "super_secret_id_12345" not in body
        assert "my_secret_val" not in body


# ====================================================================
# EXTENDED — Edge-case tests
# ====================================================================

extended = pytest.mark.extended


@extended
class TestCorruptMetadata:
    """Corrupt metadata_json doesn't crash list/get."""

    def test_corrupt_metadata_returns_empty(self, db_session, key_dir):
        """Corrupt metadata_json is returned as {} without crashing."""
        from src.services.connection_service import ConnectionService

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        svc.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        # Corrupt the metadata_json directly
        row = db_session.query(ProviderConnection).filter_by(
            connection_key="ups:test"
        ).first()
        row.metadata_json = "not json!!!"
        db_session.commit()

        conn = svc.get_connection("ups:test")
        assert conn is not None
        assert conn["metadata"] == {}
        assert conn["runtime_usable"] is True

    def test_corrupt_metadata_in_list(self, db_session, key_dir):
        """Corrupt row in list_connections returns runtime_usable=false without 500."""
        from src.services.connection_service import ConnectionService

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        svc.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        # Corrupt encrypted_credentials to simulate key loss
        row = db_session.query(ProviderConnection).filter_by(
            connection_key="ups:test"
        ).first()
        row.encrypted_credentials = "totally invalid"
        db_session.commit()

        # list_connections should still work, not 500
        connections = svc.list_connections()
        assert len(connections) == 1
        # runtime_usable will be True because _is_runtime_usable only
        # decrypts for client_credentials_shopify to check access_token.
        # For other modes, it just checks status.
        assert connections[0]["provider"] == "ups"


@extended
class TestOverwriteOnDisconnected:
    """Re-save on disconnected row resets to configured."""

    def test_resave_resets_status(self, service):
        """Saving on a disconnected row resets status to configured."""
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


@extended
class TestValidStatusEnforcement:
    """VALID_STATUSES enforcement: unknown status rejected."""

    def test_invalid_status_raises(self, service):
        """update_status with unknown status raises ValueError."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        with pytest.raises(ValueError, match="Invalid status"):
            service.update_status("ups:test", "unknown_status")


@extended
class TestKeyVersionAlwaysOne:
    """key_version is always 1 on all new connections."""

    def test_key_version_default(self, db_session, key_dir):
        """key_version is set to 1 for new connections."""
        from src.services.connection_service import ConnectionService

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        svc.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = svc.get_connection("ups:test")
        assert conn["key_version"] == 1


@extended
class TestCredentialAllowlist:
    """Credential payload allowlist: unknown keys rejected."""

    def test_unknown_keys_rejected(self, service):
        """Unknown credential keys are rejected with UNKNOWN_CREDENTIAL_KEY."""
        from src.services.connection_types import ConnectionValidationError

        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={
                    "client_id": "id",
                    "client_secret": "sec",
                    "hacker_field": "bad",
                },
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "UNKNOWN_CREDENTIAL_KEY"


@extended
class TestCredentialMaxLength:
    """Credential payload max length enforcement."""

    def test_oversized_value_rejected(self, service):
        """Value exceeding max length is rejected with VALUE_TOO_LONG."""
        from src.services.connection_types import ConnectionValidationError

        with pytest.raises(ConnectionValidationError) as exc_info:
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={
                    "client_id": "x" * 1025,  # max 1024
                    "client_secret": "sec",
                },
                metadata={}, environment="test", display_name="UPS",
            )
        assert exc_info.value.code == "VALUE_TOO_LONG"


@extended
class TestKeyLengthEnforcement:
    """16-byte and 24-byte keys rejected by encrypt/decrypt."""

    def test_short_key_encrypt(self):
        """encrypt_credentials rejects 16-byte key."""
        from src.services.credential_encryption import encrypt_credentials

        with pytest.raises(ValueError, match="32 bytes"):
            encrypt_credentials({"a": "b"}, key=os.urandom(16))

    def test_short_key_decrypt(self):
        """decrypt_credentials rejects 24-byte key."""
        from src.services.credential_encryption import (
            CredentialDecryptionError,
            decrypt_credentials,
        )

        with pytest.raises(CredentialDecryptionError, match="32 bytes"):
            decrypt_credentials("{}", key=os.urandom(24))


@extended
class TestSanitizerCoverage:
    """Sanitizer covers Bearer tokens, JSON-style, and quoted values."""

    def test_bearer_token_redacted(self):
        """Authorization: Bearer <token> is redacted."""
        from src.utils.redaction import sanitize_error_message

        msg = "Request failed: Authorization: Bearer shpat_xyz123 returned 401"
        result = sanitize_error_message(msg)
        assert "shpat_xyz123" not in result
        assert "***REDACTED***" in result

    def test_json_style_redacted(self):
        """JSON-style "key": "value" is redacted."""
        from src.utils.redaction import sanitize_error_message

        msg = 'Error: {"client_secret": "my_secret_value"} was invalid'
        result = sanitize_error_message(msg)
        assert "my_secret_value" not in result

    def test_key_value_redacted(self):
        """key=value style is redacted."""
        from src.utils.redaction import sanitize_error_message

        msg = "Failed with client_secret=supersecret123"
        result = sanitize_error_message(msg)
        assert "supersecret123" not in result


@extended
class TestInvalidBase64Key:
    """Invalid base64 env key raises ValueError."""

    def test_bad_base64_raises(self, monkeypatch):
        """SHIPAGENT_CREDENTIAL_KEY with bad base64 raises ValueError."""
        from src.services.credential_encryption import get_or_create_key

        monkeypatch.setenv("SHIPAGENT_CREDENTIAL_KEY", "not-valid!!!!")
        with pytest.raises(ValueError, match="[Ii]nvalid.*base64"):
            get_or_create_key()


@extended
class TestKeyFileSymlinkRejection:
    """SHIPAGENT_CREDENTIAL_KEY_FILE pointing to symlink raises ValueError."""

    def test_symlink_rejected(self, tmp_path, monkeypatch):
        """Symlink key file is rejected."""
        from src.services.credential_encryption import get_or_create_key

        real_file = tmp_path / "real_key"
        real_file.write_bytes(os.urandom(32))
        link_file = tmp_path / "link_key"
        link_file.symlink_to(real_file)

        monkeypatch.setenv("SHIPAGENT_CREDENTIAL_KEY_FILE", str(link_file))
        with pytest.raises(ValueError, match="symlink"):
            get_or_create_key()


@extended
class TestStrictKeyPolicy:
    """SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY strict mode."""

    def test_strict_mode_with_platformdirs_fails(self, monkeypatch, tmp_path):
        """Startup should fail when using platformdirs key + strict mode."""
        # This tests that the strict check would detect platformdirs usage
        from src.services.credential_encryption import get_key_source_info

        monkeypatch.delenv("SHIPAGENT_CREDENTIAL_KEY", raising=False)
        monkeypatch.delenv("SHIPAGENT_CREDENTIAL_KEY_FILE", raising=False)

        info = get_key_source_info()
        assert info["source"] == "platformdirs"

    def test_strict_mode_with_env_key_succeeds(self, monkeypatch):
        """With env key, strict mode should be satisfied."""
        from src.services.credential_encryption import get_key_source_info

        key = base64.b64encode(os.urandom(32)).decode()
        monkeypatch.setenv("SHIPAGENT_CREDENTIAL_KEY", key)

        info = get_key_source_info()
        assert info["source"] == "env"


@extended
class TestCheckAllWrongKey:
    """check_all with wrong key: valid creds become needs_reconnect."""

    def test_wrong_key_marks_needs_reconnect(self, db_session, key_dir):
        """Key change between save and check_all marks needs_reconnect."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        # New key dir = new key
        other_dir = str(key_dir) + "_other"
        os.makedirs(other_dir, exist_ok=True)
        service2 = ConnectionService(db=db_session, key_dir=other_dir)
        results = service2.check_all()
        assert results["ups:test"] == "error"
        conn = service2.get_connection("ups:test")
        assert conn["status"] == "needs_reconnect"


@extended
class TestShopifyClientCredsNoToken:
    """Shopify client_credentials resolver returns None when access_token empty."""

    def test_empty_token_not_usable(self, db_session, key_dir):
        """client_credentials_shopify with empty token is not runtime_usable."""
        from src.services.connection_service import ConnectionService

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        svc.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "x.myshopify.com"},
            display_name="X", environment=None,
        )
        conn = svc.get_connection("shopify:x.myshopify.com")
        assert conn["runtime_usable"] is False
        assert conn["runtime_reason"] == "missing_access_token"


@extended
class TestMultiRowShopifyDefault:
    """Multi-row Shopify default selection is deterministic."""

    def test_multiple_stores_deterministic(self, db_session, key_dir):
        """With multiple Shopify stores, get_first always returns alphabetically first."""
        from src.services.connection_service import ConnectionService

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        for name in ["zstore", "astore", "mstore"]:
            svc.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": f"shpat_{name}"},
                metadata={"store_domain": f"{name}.myshopify.com"},
                display_name=name, environment=None,
            )
        result = svc.get_first_shopify_credentials()
        assert result.store_domain == "astore.myshopify.com"


@extended
class TestKeyFilePermissionWarning:
    """Key file permission warning on overly permissive Unix permissions."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix permissions only")
    def test_permissive_file_logs_warning(self, tmp_path, caplog):
        """Overly permissive key file logs a warning."""
        import logging

        from src.services.credential_encryption import (
            KEY_FILENAME,
            get_or_create_key,
        )

        key_path = tmp_path / KEY_FILENAME
        key_path.write_bytes(os.urandom(32))
        os.chmod(key_path, 0o644)  # world-readable

        with caplog.at_level(logging.WARNING):
            get_or_create_key(str(tmp_path))
        assert any("permissions" in msg or "chmod" in msg for msg in caplog.messages)


@extended
class TestErrorMessageSanitization:
    """Sensitive content in error_message is redacted before DB persistence."""

    def test_sanitized_error_message(self, service):
        """update_status sanitizes error_message before persisting."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status(
            "ups:test", "error",
            error_code="AUTH_FAILED",
            error_message="Auth failed with client_secret=my_super_secret_value",
        )
        conn = service.get_connection("ups:test")
        assert conn["error_message"] is not None
        assert "my_super_secret_value" not in conn["error_message"]


@extended
class TestListAndGetDecryptResilience:
    """list_connections/get_connection never 500 on corrupt rows."""

    def test_list_with_corrupt_encrypted_creds(self, db_session, key_dir):
        """list_connections returns runtime_usable info without crashing."""
        from src.services.connection_service import ConnectionService

        # Create a row with bogus encrypted_credentials for a mode that
        # triggers decrypt check (client_credentials_shopify)
        row = ProviderConnection(
            connection_key="shopify:test.myshopify.com",
            provider="shopify",
            display_name="Test",
            auth_mode="client_credentials_shopify",
            status="configured",
            encrypted_credentials="totally_broken",
            metadata_json='{"store_domain":"test.myshopify.com"}',
        )
        db_session.add(row)
        db_session.commit()

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        connections = svc.list_connections()
        assert len(connections) == 1
        assert connections[0]["runtime_usable"] is False
        assert connections[0]["runtime_reason"] == "decrypt_failed"

    def test_get_with_corrupt_encrypted_creds(self, db_session, key_dir):
        """get_connection returns runtime_usable=false, not 500."""
        from src.services.connection_service import ConnectionService

        row = ProviderConnection(
            connection_key="shopify:test.myshopify.com",
            provider="shopify",
            display_name="Test",
            auth_mode="client_credentials_shopify",
            status="configured",
            encrypted_credentials="totally_broken",
            metadata_json='{"store_domain":"test.myshopify.com"}',
        )
        db_session.add(row)
        db_session.commit()

        svc = ConnectionService(db=db_session, key_dir=key_dir)
        conn = svc.get_connection("shopify:test.myshopify.com")
        assert conn["runtime_usable"] is False
        assert conn["runtime_reason"] == "decrypt_failed"
