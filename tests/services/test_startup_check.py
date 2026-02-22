"""Tests for startup decryptability check."""

import base64
import logging
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderConnection


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


class TestStartupCheck:

    def test_check_all_preserves_configured_status(self, db_session, key_dir):
        """check_all does NOT promote status to 'connected' on successful decrypt."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        results = service.check_all()
        assert results["ups:test"] == "ok"
        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"

    def test_check_all_recovers_needs_reconnect(self, db_session, key_dir):
        """Successful decrypt recovers needs_reconnect -> configured."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status("ups:test", "needs_reconnect",
                              error_code="DECRYPT_FAILED", error_message="old failure")
        service.check_all()
        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"
        assert conn["last_error_code"] is None
        assert conn["error_message"] is None

    def test_check_all_preserves_error_status(self, db_session, key_dir):
        """Successful decrypt does NOT clear error status (only needs_reconnect)."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status("ups:test", "error",
                              error_code="AUTH_FAILED", error_message="bad creds")
        service.check_all()
        conn = service.get_connection("ups:test")
        assert conn["status"] == "error"
        assert conn["last_error_code"] == "AUTH_FAILED"

    def test_check_all_does_not_modify_environ(self, db_session, key_dir):
        """check_all() does NOT write to os.environ."""
        from src.services.connection_service import ConnectionService

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "env_test", "client_secret": "env_sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.check_all()
        assert os.environ.get("UPS_CLIENT_ID") is None
        assert os.environ.get("UPS_CLIENT_SECRET") is None

    def test_check_all_empty_db(self, db_session, key_dir):
        """check_all() on empty DB returns empty dict."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        assert service.check_all() == {}

    def test_check_all_decrypt_failure_marks_needs_reconnect(self, db_session, key_dir):
        """Decrypt failure marks row as needs_reconnect with DECRYPT_FAILED."""
        from src.services.connection_service import ConnectionService

        row = ProviderConnection(
            connection_key="ups:test", provider="ups", display_name="Bad",
            auth_mode="client_credentials", environment="test",
            status="configured", encrypted_credentials="not_valid",
        )
        db_session.add(row)
        db_session.commit()
        service = ConnectionService(db=db_session, key_dir=key_dir)
        results = service.check_all()
        assert results["ups:test"] == "error"
        conn = service.get_connection("ups:test")
        assert conn["status"] == "needs_reconnect"
        assert conn["last_error_code"] == "DECRYPT_FAILED"

    def test_check_all_wrong_key_marks_needs_reconnect(self, db_session, key_dir):
        """Key change between save and check_all marks needs_reconnect."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        # Use a different key directory to simulate key loss
        other_key_dir = str(key_dir) + "_other"
        os.makedirs(other_key_dir, exist_ok=True)
        service2 = ConnectionService(db=db_session, key_dir=other_key_dir)
        results = service2.check_all()
        assert results["ups:test"] == "error"
        conn = service2.get_connection("ups:test")
        assert conn["status"] == "needs_reconnect"

    def test_check_all_logs_key_mismatch_hint(self, db_session, key_dir, caplog):
        """When rows are marked needs_reconnect, a key-mismatch hint is logged."""
        from src.services.connection_service import ConnectionService

        row = ProviderConnection(
            connection_key="ups:test", provider="ups", display_name="Bad",
            auth_mode="client_credentials", environment="test",
            status="configured", encrypted_credentials="not_valid",
        )
        db_session.add(row)
        db_session.commit()
        service = ConnectionService(db=db_session, key_dir=key_dir)
        with caplog.at_level(logging.WARNING):
            service.check_all()
        assert any("could not be decrypted" in msg or "encryption key" in msg
                    for msg in caplog.messages)

    def test_check_all_skips_disconnected_rows(self, db_session, key_dir):
        """check_all() skips disconnected rows entirely."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        results = service.check_all()
        assert "ups:test" not in results
        conn = service.get_connection("ups:test")
        assert conn["status"] == "disconnected"

    def test_check_all_sanitizes_error_message(self, db_session, key_dir):
        """Decrypt failure error_message is sanitized before DB persistence."""
        from src.services.connection_service import ConnectionService

        row = ProviderConnection(
            connection_key="ups:test", provider="ups", display_name="Bad",
            auth_mode="client_credentials", environment="test",
            status="configured", encrypted_credentials="token=secret_value_here",
        )
        db_session.add(row)
        db_session.commit()
        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.check_all()
        conn = service.get_connection("ups:test")
        if conn["error_message"]:
            assert "secret_value_here" not in conn["error_message"]

    def test_check_all_handles_malformed_row(self, db_session, key_dir):
        """check_all() marks rows with missing core fields as INVALID_ROW."""
        from src.services.connection_service import ConnectionService

        row = ProviderConnection(
            connection_key="ups:broken", provider="ups", display_name="Broken",
            auth_mode="", environment="test",
            status="configured", encrypted_credentials="blob",
        )
        db_session.add(row)
        db_session.commit()
        service = ConnectionService(db=db_session, key_dir=key_dir)
        results = service.check_all()
        assert results["ups:broken"] == "error"
        conn = service.get_connection("ups:broken")
        assert conn["status"] == "needs_reconnect"
        assert conn["last_error_code"] == "INVALID_ROW"

    def test_bad_base64_key_is_fatal(self):
        """Invalid base64 in SHIPAGENT_CREDENTIAL_KEY raises ValueError."""
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = "not-valid-base64!!!"
        try:
            from src.services.credential_encryption import get_or_create_key
            with pytest.raises(ValueError, match="[Ii]nvalid.*base64"):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)

    def test_wrong_length_key_is_fatal(self):
        """Wrong-length key in SHIPAGENT_CREDENTIAL_KEY raises ValueError."""
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(b"short").decode()
        try:
            from src.services.credential_encryption import get_or_create_key
            with pytest.raises(ValueError, match="invalid length"):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)
