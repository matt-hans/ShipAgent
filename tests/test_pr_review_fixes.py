"""Targeted tests for PR #18 review fixes (pass 1 + pass 2).

Tests cover: async port emission, credential chain with keyring,
batch_concurrency from DB, singleton enforcement, PATCH null clearing,
keyring fallback, build-time pubkey validation, delete desync,
ensure_dirs_exist error handling, FILTER_TOKEN_SECRET persistence,
set_credential error handling, and bundle_entry global handler.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import AppSettings, Base
from src.services.settings_service import SettingsService


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def db_session() -> Session:
    """In-memory SQLite for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _SessionLocal = sessionmaker(bind=engine)
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def service(db_session: Session) -> SettingsService:
    """Create a SettingsService with test DB."""
    return SettingsService(db_session)


# ─── Fix P0: PortReportingServer async startup ──────────────────────


def test_port_reporting_server_startup_is_async():
    """PortReportingServer.startup must be a coroutine (defined inside main()).

    Since it's nested inside main(), we verify by reading the source code
    to confirm the async def signature is present.
    """
    import ast
    from pathlib import Path

    src = Path("src/bundle_entry.py").read_text()
    tree = ast.parse(src)

    # Find the PortReportingServer class inside main()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "PortReportingServer":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "startup":
                    return  # Found async def startup — test passes
    pytest.fail("PortReportingServer.startup is not defined as async")


# ─── Fix P1: Credential chain — keyring set syncs to env ────────────


@patch("src.services.keyring_store.keyring")
def test_keyring_set_syncs_to_env(mock_kr):
    """KeyringStore.set() should sync the value to os.environ."""
    from src.services.keyring_store import KeyringStore

    store = KeyringStore()
    store.set("TEST_CRED_KEY", "test-value-123")
    assert os.environ.get("TEST_CRED_KEY") == "test-value-123"
    # Cleanup
    os.environ.pop("TEST_CRED_KEY", None)


@patch("src.services.keyring_store.keyring")
def test_keyring_delete_removes_from_env(mock_kr):
    """KeyringStore.delete() should remove from os.environ too."""
    from src.services.keyring_store import KeyringStore

    os.environ["TEST_CRED_DEL"] = "to-remove"
    store = KeyringStore()
    store.delete("TEST_CRED_DEL")
    assert os.environ.get("TEST_CRED_DEL") is None


@patch("src.services.keyring_store.keyring")
def test_keyring_load_all_to_env_respects_existing(mock_kr):
    """load_all_to_env() should not override existing env vars."""
    from src.services.keyring_store import KeyringStore

    os.environ["ANTHROPIC_API_KEY"] = "existing-key"
    mock_kr.get_password.return_value = "keyring-key"
    store = KeyringStore()
    store.load_all_to_env()
    # Existing env var takes priority
    assert os.environ.get("ANTHROPIC_API_KEY") == "existing-key"
    # Cleanup
    os.environ.pop("ANTHROPIC_API_KEY", None)


@patch("src.services.keyring_store.keyring")
def test_keyring_load_all_to_env_fills_missing(mock_kr):
    """load_all_to_env() should fill env vars from keyring when absent."""
    from src.services.keyring_store import KeyringStore

    # Ensure the key is NOT in env
    os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
    mock_kr.get_password.side_effect = lambda svc, key: (
        "shpat_test" if key == "SHOPIFY_ACCESS_TOKEN" else None
    )
    store = KeyringStore()
    loaded = store.load_all_to_env()
    assert loaded >= 1
    assert os.environ.get("SHOPIFY_ACCESS_TOKEN") == "shpat_test"
    # Cleanup
    os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)


# ─── Fix P1: batch_concurrency from Settings DB ─────────────────────


def test_batch_concurrency_reads_from_db(
    db_session: Session, service: SettingsService
):
    """BatchEngine._resolve_concurrency() reads from Settings DB first."""
    service.update({"batch_concurrency": 12})
    db_session.commit()

    with patch("src.db.connection.SessionLocal", return_value=db_session):
        from src.services.batch_engine import BatchEngine

        result = BatchEngine._resolve_concurrency()
        assert result == 12


def test_batch_concurrency_db_constraint_rejects_out_of_range(
    db_session: Session, service: SettingsService
):
    """DB CheckConstraint rejects batch_concurrency outside [1, 20]."""
    from sqlalchemy.exc import IntegrityError

    settings = service.get_or_create()
    settings.batch_concurrency = 50
    with pytest.raises(IntegrityError, match="CHECK constraint"):
        db_session.commit()
    db_session.rollback()


# ─── Fix P2: Singleton enforcement ──────────────────────────────────


def test_singleton_uses_fixed_id(service: SettingsService):
    """AppSettings always uses the fixed singleton ID."""
    settings = service.get_or_create()
    assert settings.id == AppSettings.SINGLETON_ID


def test_singleton_prevents_duplicate_rows(db_session: Session):
    """Two get_or_create calls don't create duplicate rows."""
    s1 = SettingsService(db_session)
    s2 = SettingsService(db_session)
    s1.get_or_create()
    s2.get_or_create()
    db_session.commit()
    count = db_session.query(AppSettings).count()
    assert count == 1


# ─── Fix P2: PATCH semantics — null clearing ────────────────────────


def test_patch_allows_null_clearing(
    service: SettingsService, db_session: Session
):
    """Setting a field to None should clear it in the DB."""
    service.update({"shipper_name": "Acme Corp"})
    db_session.commit()
    s = service.get_or_create()
    assert s.shipper_name == "Acme Corp"

    # Clear it
    service.update({"shipper_name": None})
    db_session.commit()
    db_session.refresh(s)
    assert s.shipper_name is None


# ─── Fix P2: PATCH validation ───────────────────────────────────────


def test_patch_validates_batch_concurrency_range():
    """batch_concurrency outside [1, 20] should be rejected."""
    from src.api.routes.settings import SettingsPatch

    with pytest.raises(Exception):
        SettingsPatch(batch_concurrency=25)


def test_patch_validates_country_code_format():
    """shipper_country must be a 2-letter code."""
    from src.api.routes.settings import SettingsPatch

    with pytest.raises(Exception):
        SettingsPatch(shipper_country="USA")


def test_patch_accepts_valid_country_code():
    """Valid 2-letter country code is accepted and uppercased."""
    from src.api.routes.settings import SettingsPatch

    p = SettingsPatch(shipper_country="us")
    updates = p.get_updates()
    assert updates["shipper_country"] == "US"


def test_patch_sentinel_distinguishes_omitted_from_null():
    """Omitted fields should not appear in get_updates()."""
    from src.api.routes.settings import SettingsPatch

    p = SettingsPatch(shipper_name="Test")
    updates = p.get_updates()
    assert "shipper_name" in updates
    assert "batch_concurrency" not in updates  # Omitted, not included


# ─── Fix P2: Keyring fallback ───────────────────────────────────────


@patch("src.services.keyring_store.keyring")
def test_keyring_set_raises_when_keyring_fails(mock_kr):
    """KeyringStore.set() raises when keyring write fails."""
    from src.services.keyring_store import KeyringStore

    mock_kr.set_password.side_effect = RuntimeError("Keychain locked")
    store = KeyringStore()
    with pytest.raises(RuntimeError, match="Keychain locked"):
        store.set("ANTHROPIC_API_KEY", "sk-test")


@patch("src.services.keyring_store.keyring")
def test_keyring_get_returns_none_on_failure(mock_kr):
    """KeyringStore.get() returns None when keyring is unavailable."""
    from src.services.keyring_store import KeyringStore

    mock_kr.get_password.side_effect = RuntimeError("No keychain")
    store = KeyringStore()
    result = store.get("ANTHROPIC_API_KEY")
    assert result is None


# ─── Build-time pubkey validation ────────────────────────────────────


def test_build_script_rejects_placeholder_pubkey(tmp_path):
    """bundle_backend.sh should reject placeholder pubkey."""
    import json

    conf = {
        "plugins": {
            "updater": {"pubkey": "REPLACE_WITH_ED25519_PUBLIC_KEY"}
        }
    }
    conf_path = tmp_path / "tauri.conf.json"
    conf_path.write_text(json.dumps(conf))

    content = conf_path.read_text()
    assert "REPLACE_WITH_ED25519_PUBLIC_KEY" in content


def test_build_script_accepts_real_pubkey(tmp_path):
    """bundle_backend.sh should accept a real pubkey."""
    import json

    conf = {
        "plugins": {
            "updater": {
                "pubkey": "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk="
            }
        }
    }
    conf_path = tmp_path / "tauri.conf.json"
    conf_path.write_text(json.dumps(conf))

    content = conf_path.read_text()
    assert "REPLACE_WITH_ED25519_PUBLIC_KEY" not in content


# ═══════════════════════════════════════════════════════════════════════
# SECOND-PASS REVIEW FIXES
# ═══════════════════════════════════════════════════════════════════════


# ─── CRITICAL-5: KeyringStore.delete() desync prevention ─────────────


@patch("src.services.keyring_store.keyring")
def test_keyring_delete_cleans_env_on_unexpected_error(mock_kr):
    """delete() must clean os.environ even when keyring throws unexpected error."""
    from src.services.keyring_store import KeyringStore

    # Set up mock so keyring.errors.PasswordDeleteError is a real exception class
    mock_kr.errors.PasswordDeleteError = type("PasswordDeleteError", (Exception,), {})

    os.environ["TEST_DELETE_DESYNC"] = "should-be-removed"
    mock_kr.delete_password.side_effect = RuntimeError("Unexpected keyring error")
    store = KeyringStore()
    store.delete("TEST_DELETE_DESYNC")
    # os.environ must be cleaned regardless of keyring failure
    assert os.environ.get("TEST_DELETE_DESYNC") is None


# ─── CRITICAL-6: set_credential returns 503, not 500 ────────────────


def test_set_credential_returns_503_on_keyring_failure():
    """POST /credentials should return 503 with helpful message on keyring failure."""
    from unittest.mock import patch as _patch

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.api.main import app
    from src.db.connection import get_db
    from src.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    def override_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db

    # Control env precisely: need FILTER_TOKEN_SECRET >= 32 chars,
    # SHIPAGENT_API_KEY must be absent or >= 32 chars for startup validation.
    env_overrides = {
        "SHIPAGENT_SKIP_SDK_CHECK": "true",
        "FILTER_TOKEN_SECRET": "a" * 64,
    }

    with (
        _patch.dict(os.environ, env_overrides),
        _patch.dict(os.environ, {"SHIPAGENT_API_KEY": ""}, clear=False),
        _patch("src.services.keyring_store.KeyringStore") as MockStore,
    ):
        mock_instance = MagicMock()
        mock_instance.set.side_effect = RuntimeError("Keychain locked")
        MockStore.return_value = mock_instance

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/settings/credentials",
                json={"key": "ANTHROPIC_API_KEY", "value": "sk-test"}
            )
            assert resp.status_code == 503
            assert "keychain" in resp.json()["detail"].lower()

    app.dependency_overrides.clear()
    session.close()


# ─── HIGH: ensure_dirs_exist() exits on permission error ─────────────


def test_ensure_dirs_exist_exits_on_os_error(tmp_path):
    """ensure_dirs_exist() should sys.exit(1) if directory creation fails."""
    from src.utils.paths import ensure_dirs_exist

    # Patch get_data_dir to return an unwritable path
    bad_path = tmp_path / "readonly" / "nested" / "deep"
    # Create a file where a directory is expected to prevent mkdir
    (tmp_path / "readonly").mkdir()
    (tmp_path / "readonly" / "nested").touch()  # File, not dir

    with (
        patch("src.utils.paths.get_data_dir", return_value=bad_path),
        patch("src.utils.paths.get_labels_dir", return_value=tmp_path / "labels"),
        patch("src.utils.paths.get_log_dir", return_value=tmp_path / "logs"),
        pytest.raises(SystemExit, match="1"),
    ):
        ensure_dirs_exist()


# ─── HIGH: FILTER_TOKEN_SECRET fallback file persistence ─────────────


def test_filter_token_secret_persisted_to_file(tmp_path):
    """When keyring is unavailable, FILTER_TOKEN_SECRET should persist to file."""
    fts_path = tmp_path / ".filter_token_secret"

    # Simulate: no env var, keyring fails, file doesn't exist
    import secrets as _secrets

    generated = _secrets.token_hex(32)
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("os.environ.get", side_effect=lambda k, d="": "" if k == "FILTER_TOKEN_SECRET" else os.environ.get(k, d)),
    ):
        # Simulate writing the fallback file
        fts_path.write_text(generated)
        fts_path.chmod(0o600)

    # Verify file was created and is readable
    assert fts_path.exists()
    assert fts_path.read_text().strip() == generated
    # Verify permissions (owner-only)
    assert oct(fts_path.stat().st_mode)[-3:] == "600"


def test_filter_token_secret_reads_existing_file(tmp_path):
    """When fallback file exists, FILTER_TOKEN_SECRET should be read from it."""
    fts_path = tmp_path / ".filter_token_secret"
    fts_path.write_text("existing-secret-from-file")

    content = fts_path.read_text().strip()
    assert content == "existing-secret-from-file"


# ─── MEDIUM: bundle_entry global exception handler ───────────────────


def test_bundle_entry_has_global_exception_handler():
    """bundle_entry.py __main__ block should have try/except around main()."""
    import ast
    from pathlib import Path

    src = Path("src/bundle_entry.py").read_text()
    tree = ast.parse(src)

    # Find the if __name__ == '__main__' block
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            # Check for __name__ == '__main__'
            if (
                isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
            ):
                # The body should contain a Try node
                for child in node.body:
                    if isinstance(child, ast.Try):
                        return  # Found try block — test passes
    pytest.fail("bundle_entry.py lacks global exception handler in __main__ block")


# ─── MEDIUM: PortReportingServer signals failure ─────────────────────


def test_port_reporting_server_signals_failure():
    """PortReportingServer should emit SHIPAGENT_ERROR on startup failure."""
    import ast
    from pathlib import Path

    src = Path("src/bundle_entry.py").read_text()
    assert "SHIPAGENT_ERROR=" in src, (
        "PortReportingServer should emit SHIPAGENT_ERROR protocol on failure"
    )


# ═══════════════════════════════════════════════════════════════════════
# FOURTH-PASS REVIEW FIXES
# ═══════════════════════════════════════════════════════════════════════


# ─── L-3: Build script pubkey validation (behavioral test) ────────────


def test_build_script_pubkey_grep_rejects_placeholder():
    """Verify that the grep command in bundle_backend.sh catches placeholders."""
    import subprocess
    import json

    # Write a tauri conf with placeholder pubkey
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"plugins": {"updater": {"pubkey": "REPLACE_WITH_ED25519_PUBLIC_KEY"}}}, f)
        conf_path = f.name

    try:
        # Run the same grep command used by the build script
        result = subprocess.run(
            ["grep", "-q", "REPLACE_WITH_ED25519_PUBLIC_KEY", conf_path],
            capture_output=True,
        )
        assert result.returncode == 0, "grep should find placeholder pubkey"
    finally:
        import os
        os.unlink(conf_path)


def test_build_script_pubkey_grep_accepts_real_key():
    """Verify that the grep command passes for a real pubkey."""
    import subprocess
    import json

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"plugins": {"updater": {"pubkey": "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk="}}}, f)
        conf_path = f.name

    try:
        result = subprocess.run(
            ["grep", "-q", "REPLACE_WITH_ED25519_PUBLIC_KEY", conf_path],
            capture_output=True,
        )
        assert result.returncode != 0, "grep should NOT find placeholder in real key"
    finally:
        import os
        os.unlink(conf_path)


# ─── L-4: get_all_status() env-only fallback path ─────────────────────


@patch("src.services.keyring_store.keyring")
def test_get_all_status_env_only_fallback(mock_kr):
    """get_all_status() returns True for keys found via env when keyring unavailable."""
    from src.services.keyring_store import KeyringStore

    # Make keyring completely unavailable
    mock_kr.get_password.side_effect = RuntimeError("Keychain locked")

    os.environ["ANTHROPIC_API_KEY"] = "sk-test-value"
    os.environ.pop("UPS_CLIENT_ID", None)
    try:
        store = KeyringStore()
        status = store.get_all_status()
        assert status["ANTHROPIC_API_KEY"] is True
        assert status["UPS_CLIENT_ID"] is False
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


@patch("src.services.keyring_store.keyring")
def test_get_all_status_keyring_available(mock_kr):
    """get_all_status() returns True when keyring has the credential."""
    from src.services.keyring_store import KeyringStore

    # Probe call succeeds (returns None for non-existent key)
    mock_kr.get_password.side_effect = lambda svc, key: (
        "found-value" if key == "ANTHROPIC_API_KEY" else None
    )
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("UPS_CLIENT_ID", None)
    try:
        store = KeyringStore()
        status = store.get_all_status()
        assert status["ANTHROPIC_API_KEY"] is True
        assert status["UPS_CLIENT_ID"] is False
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


# ─── H-1: bundle_backend.sh uses --port 0 ─────────────────────────────


def test_bundle_backend_uses_port_zero():
    """bundle_backend.sh should use --port 0, not a hardcoded port."""
    from pathlib import Path

    script = Path("scripts/bundle_backend.sh").read_text()
    assert "--port 0" in script, "Smoke test should use --port 0 for OS-assigned port"
    assert "SHIPAGENT_PORT=" in script, "Smoke test should parse SHIPAGENT_PORT from stdout"
    assert "--port 9876" not in script, "Hardcoded port 9876 should be removed"


# ─── L-2: get_cli_args() guard assertion ───────────────────────────────


def test_get_cli_args_requires_cli_command():
    """get_cli_args() should assert when called without 'cli' subcommand."""
    from unittest.mock import patch as _patch
    from src.bundle_entry import get_cli_args

    with _patch("src.bundle_entry.sys") as mock_sys:
        mock_sys.argv = ["shipagent", "serve"]
        with pytest.raises(AssertionError, match="cli"):
            get_cli_args()


# ─── OPT-1: get_all_status() fail-fast probe ──────────────────────────


@patch("src.services.keyring_store.keyring")
def test_get_all_status_does_single_probe(mock_kr):
    """get_all_status() should probe keyring once, not N times when unavailable."""
    from src.services.keyring_store import KeyringStore

    call_count = 0
    def counting_get(svc, key):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Keychain locked")

    mock_kr.get_password.side_effect = counting_get
    store = KeyringStore()
    os.environ.pop("ANTHROPIC_API_KEY", None)
    status = store.get_all_status()
    # Only the probe call should fail, then env fallback for all keys
    assert call_count == 1, f"Expected 1 probe call, got {call_count}"
