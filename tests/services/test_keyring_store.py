"""Tests for keyring credential store.

Uses a mock backend to avoid touching the real system keychain.
"""

from unittest.mock import patch

from src.services.keyring_store import KeyringStore


@patch("src.services.keyring_store.keyring")
def test_set_credential_stores_to_keyring(mock_kr):
    """Setting a credential calls keyring.set_password."""
    store = KeyringStore()
    store.set("ANTHROPIC_API_KEY", "sk-ant-test-key")
    mock_kr.set_password.assert_called_once_with(
        "com.shipagent.app", "ANTHROPIC_API_KEY", "sk-ant-test-key"
    )


@patch("src.services.keyring_store.keyring")
def test_get_credential_reads_from_keyring(mock_kr):
    """Getting a credential reads from keyring."""
    mock_kr.get_password.return_value = "sk-ant-test-key"
    store = KeyringStore()
    result = store.get("ANTHROPIC_API_KEY")
    assert result == "sk-ant-test-key"
    mock_kr.get_password.assert_called_once_with(
        "com.shipagent.app", "ANTHROPIC_API_KEY"
    )


@patch("src.services.keyring_store.keyring")
def test_get_credential_returns_none_when_absent(mock_kr):
    """Missing credential returns None."""
    mock_kr.get_password.return_value = None
    store = KeyringStore()
    assert store.get("NONEXISTENT") is None


@patch("src.services.keyring_store.keyring")
def test_has_credential(mock_kr):
    """has() returns True when credential exists."""
    mock_kr.get_password.return_value = "value"
    store = KeyringStore()
    assert store.has("ANTHROPIC_API_KEY") is True


@patch("src.services.keyring_store.keyring")
def test_delete_credential(mock_kr):
    """delete() removes credential from keyring."""
    store = KeyringStore()
    store.delete("ANTHROPIC_API_KEY")
    mock_kr.delete_password.assert_called_once_with(
        "com.shipagent.app", "ANTHROPIC_API_KEY"
    )


@patch("src.services.keyring_store.keyring")
def test_get_all_status(mock_kr):
    """get_all_status() returns dict of credential name to bool."""
    mock_kr.get_password.side_effect = lambda svc, key: "val" if key == "ANTHROPIC_API_KEY" else None
    store = KeyringStore()
    status = store.get_all_status()
    assert status["ANTHROPIC_API_KEY"] is True
    assert status["UPS_CLIENT_ID"] is False
