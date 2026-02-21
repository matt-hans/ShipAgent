# Settings Connections Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent encrypted credential storage and a Settings UI for configuring UPS and Shopify providers, replacing the .env-only workflow. Phase 1 includes foundation storage, API routes, frontend UI, **and runtime integration** — DB-stored credentials are wired into all UPS and Shopify runtime call sites via a single `runtime_credentials.py` adapter with env var fallback.

**Architecture:** New `ProviderConnection` SQLAlchemy model with AES-256-GCM encrypted credentials (versioned envelope, AAD-bound, algorithm-validated). `ConnectionService` provides typed credential resolvers, CRUD with input validation and domain normalization, and a startup decryptability scan. `runtime_credentials.py` is the single adapter for all runtime call sites (no ad hoc env reads). Frontend adds a Connections accordion section to the existing SettingsFlyout with per-provider cards and forms. Key source precedence: env key → env path → platformdirs. Resolver skip policy: skip `disconnected` + `needs_reconnect`. Migration uses same PRAGMA introspection pattern as existing codebase.

**Tech Stack:** Python `cryptography` (AES-256-GCM), `platformdirs` (key storage), SQLAlchemy, FastAPI, React + TypeScript + Tailwind

---

### Task 0: Dependencies and Gitignore

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml`

**Step 1: Add to .gitignore**

```
# Encryption key for provider credentials
.shipagent_key
```

**Step 2: Add dependencies to `pyproject.toml`**

Add `cryptography>=42.0.0` and `platformdirs>=4.0.0` to the `dependencies` list.

**Step 3: Install dependencies**

Run: `pip install -e ".[dev]"` (or `pip install cryptography>=42.0.0 platformdirs>=4.0.0`)

**Step 4: Verify import works**

Run: `python -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; from platformdirs import user_data_dir; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add .gitignore pyproject.toml
git commit -m "chore: add cryptography and platformdirs dependencies, gitignore key file"
```

---

### Task 1: Secret Redaction Utility

**Files:**
- Create: `src/utils/redaction.py`
- Create: `tests/utils/test_redaction.py`

**Step 1: Write the failing tests**

```python
# tests/utils/test_redaction.py
"""Tests for secret redaction utility."""

import pytest


class TestRedactForLogging:

    def test_redacts_sensitive_keys(self):
        from src.utils.redaction import redact_for_logging

        data = {"client_id": "secret123", "name": "UPS", "client_secret": "sec456"}
        result = redact_for_logging(data)
        assert result["client_id"] == "***REDACTED***"
        assert result["client_secret"] == "***REDACTED***"
        assert result["name"] == "UPS"

    def test_preserves_non_sensitive(self):
        from src.utils.redaction import redact_for_logging

        data = {"provider": "ups", "environment": "test", "status": "configured"}
        result = redact_for_logging(data)
        assert result == data

    def test_handles_nested_dict(self):
        from src.utils.redaction import redact_for_logging

        data = {"outer": {"access_token": "tok123", "name": "Store"}}
        result = redact_for_logging(data)
        assert result["outer"]["access_token"] == "***REDACTED***"
        assert result["outer"]["name"] == "Store"

    def test_empty_dict(self):
        from src.utils.redaction import redact_for_logging

        assert redact_for_logging({}) == {}

    def test_custom_sensitive_keys(self):
        from src.utils.redaction import redact_for_logging

        data = {"api_key": "key123", "name": "test"}
        result = redact_for_logging(data, sensitive_keys=frozenset({"api_key"}))
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "test"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/utils/test_redaction.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/utils/redaction.py
"""Secret redaction utility for safe logging and error responses.

Provides centralized redaction to prevent credential leakage in logs,
error messages, and API error responses.
"""

_DEFAULT_SENSITIVE_KEYS = frozenset({
    "client_id", "client_secret", "access_token", "refresh_token",
    "password", "secret", "api_key", "token",
})

_REDACTED = "***REDACTED***"


def redact_for_logging(
    obj: dict,
    sensitive_keys: frozenset[str] = _DEFAULT_SENSITIVE_KEYS,
) -> dict:
    """Redact sensitive values from a dict for safe logging/error responses.

    Args:
        obj: Dict to redact (not mutated — returns a copy).
        sensitive_keys: Keys whose values should be replaced.

    Returns:
        New dict with sensitive values replaced by '***REDACTED***'.
    """
    result = {}
    for key, value in obj.items():
        if key in sensitive_keys:
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = redact_for_logging(value, sensitive_keys)
        else:
            result[key] = value
    return result
```

**Step 4: Create `src/utils/__init__.py` if it doesn't exist**

Run: `touch src/utils/__init__.py` and `touch tests/utils/__init__.py`

**Step 5: Run tests to verify they pass**

Run: `pytest tests/utils/test_redaction.py -v`
Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add src/utils/redaction.py src/utils/__init__.py tests/utils/test_redaction.py tests/utils/__init__.py
git commit -m "feat: add secret redaction utility for safe logging"
```

---

### Task 2: Credential Encryption Module

**Files:**
- Create: `src/services/credential_encryption.py`
- Create: `tests/services/test_credential_encryption.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_credential_encryption.py
"""Tests for AES-256-GCM credential encryption with versioned envelope."""

import base64
import json
import os
import platform
import stat

import pytest


@pytest.fixture
def temp_key_dir(tmp_path):
    """Provide a temporary directory for key file storage."""
    return str(tmp_path)


class TestKeyManagement:
    """Tests for encryption key file lifecycle."""

    def test_get_or_create_key_creates_file(self, temp_key_dir):
        """First call creates key file and returns 32-byte key."""
        from src.services.credential_encryption import get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        assert len(key) == 32
        key_path = os.path.join(temp_key_dir, ".shipagent_key")
        assert os.path.exists(key_path)

    def test_get_or_create_key_is_idempotent(self, temp_key_dir):
        """Repeated calls return the same key."""
        from src.services.credential_encryption import get_or_create_key

        key1 = get_or_create_key(key_dir=temp_key_dir)
        key2 = get_or_create_key(key_dir=temp_key_dir)
        assert key1 == key2

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix permissions")
    def test_key_file_has_restricted_permissions(self, temp_key_dir):
        """Key file should be owner-read-write only (0600) on Unix."""
        from src.services.credential_encryption import get_or_create_key

        get_or_create_key(key_dir=temp_key_dir)
        key_path = os.path.join(temp_key_dir, ".shipagent_key")
        mode = os.stat(key_path).st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_invalid_key_length_raises(self, temp_key_dir):
        """Key file with wrong length raises ValueError."""
        from src.services.credential_encryption import get_or_create_key

        key_path = os.path.join(temp_key_dir, ".shipagent_key")
        with open(key_path, "wb") as f:
            f.write(b"too_short")
        with pytest.raises(ValueError, match="invalid length"):
            get_or_create_key(key_dir=temp_key_dir)

    def test_default_key_dir_uses_platformdirs(self):
        """Default key directory uses platformdirs.user_data_dir."""
        from src.services.credential_encryption import get_default_key_dir

        key_dir = get_default_key_dir()
        assert "shipagent" in key_dir

    def test_env_key_takes_precedence(self, temp_key_dir):
        """SHIPAGENT_CREDENTIAL_KEY env var overrides file-based key."""
        from src.services.credential_encryption import get_or_create_key

        raw_key = os.urandom(32)
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(raw_key).decode()
        try:
            key = get_or_create_key(key_dir=temp_key_dir)
            assert key == raw_key
            # File should NOT be created when env key is used
            key_path = os.path.join(temp_key_dir, ".shipagent_key")
            assert not os.path.exists(key_path)
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)

    def test_env_key_file_takes_precedence_over_platformdirs(self, temp_key_dir):
        """SHIPAGENT_CREDENTIAL_KEY_FILE env var overrides platformdirs."""
        from src.services.credential_encryption import get_or_create_key

        # Write a key to a custom path
        custom_key = os.urandom(32)
        custom_path = os.path.join(temp_key_dir, "custom_key")
        with open(custom_path, "wb") as f:
            f.write(custom_key)

        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = custom_path
        try:
            key = get_or_create_key(key_dir=temp_key_dir)
            assert key == custom_key
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)

    def test_invalid_env_key_length_raises(self):
        """SHIPAGENT_CREDENTIAL_KEY with wrong length raises ValueError."""
        from src.services.credential_encryption import get_or_create_key

        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(b"short").decode()
        try:
            with pytest.raises(ValueError, match="invalid length"):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)


class TestEncryptDecrypt:
    """Tests for AES-256-GCM encrypt/decrypt with versioned envelope."""

    def test_round_trip(self, temp_key_dir):
        """Encrypt then decrypt returns original data."""
        from src.services.credential_encryption import (
            decrypt_credentials, encrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        plaintext = {"client_id": "test_id", "client_secret": "test_secret"}
        aad = "ups:client_credentials:ups:test"
        ciphertext = encrypt_credentials(plaintext, key, aad=aad)
        result = decrypt_credentials(ciphertext, key, aad=aad)
        assert result == plaintext

    def test_envelope_format(self, temp_key_dir):
        """Ciphertext is a valid JSON envelope with version and algorithm."""
        from src.services.credential_encryption import encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"k": "v"}, key, aad="test:aad")
        envelope = json.loads(ciphertext)
        assert envelope["v"] == 1
        assert envelope["alg"] == "AES-256-GCM"
        assert "nonce" in envelope
        assert "ct" in envelope

    def test_different_nonce_each_call(self, temp_key_dir):
        """Each encryption produces different ciphertext (unique nonce)."""
        from src.services.credential_encryption import encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        plaintext = {"token": "abc123"}
        ct1 = encrypt_credentials(plaintext, key, aad="test")
        ct2 = encrypt_credentials(plaintext, key, aad="test")
        assert ct1 != ct2

    def test_wrong_key_fails(self, temp_key_dir):
        """Decryption with wrong key raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials,
            encrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"secret": "data"}, key, aad="test")
        wrong_key = os.urandom(32)
        with pytest.raises(CredentialDecryptionError):
            decrypt_credentials(ciphertext, wrong_key, aad="test")

    def test_wrong_aad_fails(self, temp_key_dir):
        """Decryption with wrong AAD raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials,
            encrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"k": "v"}, key, aad="ups:test")
        with pytest.raises(CredentialDecryptionError):
            decrypt_credentials(ciphertext, key, aad="shopify:other")

    def test_tampered_ciphertext_fails(self, temp_key_dir):
        """Tampered ciphertext raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials,
            encrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"key": "val"}, key, aad="test")
        envelope = json.loads(ciphertext)
        raw_ct = base64.b64decode(envelope["ct"])
        tampered = raw_ct[:-1] + bytes([raw_ct[-1] ^ 0xFF])
        envelope["ct"] = base64.b64encode(tampered).decode()
        with pytest.raises(CredentialDecryptionError):
            decrypt_credentials(json.dumps(envelope), key, aad="test")

    def test_empty_dict_round_trip(self, temp_key_dir):
        """Empty credentials dict encrypts and decrypts cleanly."""
        from src.services.credential_encryption import (
            decrypt_credentials, encrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({}, key, aad="test")
        assert decrypt_credentials(ciphertext, key, aad="test") == {}

    def test_corrupt_envelope_json_raises(self, temp_key_dir):
        """Non-JSON ciphertext raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        with pytest.raises(CredentialDecryptionError):
            decrypt_credentials("not_valid_json{{{", key, aad="test")

    def test_unsupported_version_raises(self, temp_key_dir):
        """Envelope with unknown version raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        envelope = json.dumps({"v": 99, "alg": "AES-256-GCM", "nonce": "AA==", "ct": "BB=="})
        with pytest.raises(CredentialDecryptionError, match="Unsupported envelope version"):
            decrypt_credentials(envelope, key, aad="test")

    def test_wrong_algorithm_raises(self, temp_key_dir):
        """Envelope with unknown algorithm raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        envelope = json.dumps({"v": 1, "alg": "ChaCha20-Poly1305", "nonce": "AA==", "ct": "BB=="})
        with pytest.raises(CredentialDecryptionError, match="Unsupported algorithm"):
            decrypt_credentials(envelope, key, aad="test")

    def test_decrypted_payload_must_be_dict(self, temp_key_dir):
        """Decrypted payload that is not a dict raises CredentialDecryptionError."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials, get_or_create_key,
        )
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = get_or_create_key(key_dir=temp_key_dir)
        # Manually encrypt a JSON array (not a dict)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext = json.dumps(["not", "a", "dict"]).encode("utf-8")
        aad_bytes = b"test"
        ct = aesgcm.encrypt(nonce, plaintext, aad_bytes)
        envelope = json.dumps({
            "v": 1,
            "alg": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ct": base64.b64encode(ct).decode("ascii"),
        })
        with pytest.raises(CredentialDecryptionError, match="not a dict"):
            decrypt_credentials(envelope, key, aad="test")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_credential_encryption.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.credential_encryption'`

**Step 3: Write implementation**

```python
# src/services/credential_encryption.py
"""AES-256-GCM credential encryption for persistent provider storage.

Provides encrypt/decrypt for JSON credential blobs and key file management.

Key source precedence:
    1. SHIPAGENT_CREDENTIAL_KEY env var (base64-encoded 32-byte key)
    2. SHIPAGENT_CREDENTIAL_KEY_FILE env var (path to raw key file)
    3. platformdirs local file (auto-generated on first use)

Ciphertext format: versioned JSON envelope with AAD binding and algorithm validation.
"""

import base64
import json
import logging
import os
import platform
import stat

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

KEY_FILENAME = ".shipagent_key"
_CURRENT_VERSION = 1
_ALGORITHM = "AES-256-GCM"


class CredentialDecryptionError(Exception):
    """Raised when credential decryption fails for any reason."""


def get_default_key_dir() -> str:
    """Return the platform-appropriate app-data directory for key storage.

    Uses platformdirs to resolve per-user, per-platform paths:
    - macOS: ~/Library/Application Support/shipagent
    - Linux: ~/.local/share/shipagent
    - Windows: C:\\Users\\<user>\\AppData\\Local\\shipagent

    Returns:
        Directory path string.
    """
    from platformdirs import user_data_dir

    return user_data_dir("shipagent", ensure_exists=True)


def get_or_create_key(key_dir: str | None = None) -> bytes:
    """Load or generate the 32-byte AES-256 encryption key.

    Key source precedence:
        1. SHIPAGENT_CREDENTIAL_KEY env var (base64-encoded)
        2. SHIPAGENT_CREDENTIAL_KEY_FILE env var (path to file)
        3. File in key_dir (or platformdirs default), auto-generated if missing

    Args:
        key_dir: Directory for the key file (source 3 only).
                 Defaults to platformdirs app-data.

    Returns:
        32-byte encryption key.

    Raises:
        ValueError: If key has invalid length from any source.
    """
    # Source 1: env var (base64-encoded key)
    env_key = os.environ.get("SHIPAGENT_CREDENTIAL_KEY", "").strip()
    if env_key:
        key = base64.b64decode(env_key)
        if len(key) != 32:
            raise ValueError(
                f"SHIPAGENT_CREDENTIAL_KEY has invalid length {len(key)} (expected 32)"
            )
        return key

    # Source 2: env var pointing to key file
    env_key_file = os.environ.get("SHIPAGENT_CREDENTIAL_KEY_FILE", "").strip()
    if env_key_file:
        with open(env_key_file, "rb") as f:
            key = f.read()
        if len(key) != 32:
            raise ValueError(
                f"Key file {env_key_file} has invalid length {len(key)} (expected 32)"
            )
        return key

    # Source 3: platformdirs file (auto-generated)
    directory = key_dir or get_default_key_dir()
    os.makedirs(directory, exist_ok=True)
    key_path = os.path.join(directory, KEY_FILENAME)

    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            key = f.read()
        if len(key) != 32:
            raise ValueError(
                f"Key file {key_path} has invalid length {len(key)} (expected 32). "
                "Delete the file to regenerate."
            )
        return key

    key = os.urandom(32)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)

    if platform.system() != "Windows":
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

    logger.info("Generated new encryption key at %s", key_path)
    return key


def encrypt_credentials(credentials: dict, key: bytes, aad: str = "") -> str:
    """Encrypt a credentials dict to a versioned JSON envelope string.

    Args:
        credentials: Dict of credential key-value pairs.
        key: 32-byte AES-256 key.
        aad: Additional authenticated data (e.g., 'provider:auth_mode:connection_key').

    Returns:
        JSON string envelope: {"v":1, "alg":"AES-256-GCM", "nonce":"<b64>", "ct":"<b64>"}.
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = json.dumps(credentials, sort_keys=True).encode("utf-8")
    aad_bytes = aad.encode("utf-8") if aad else None
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad_bytes)
    envelope = {
        "v": _CURRENT_VERSION,
        "alg": _ALGORITHM,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope)


def decrypt_credentials(encrypted: str, key: bytes, aad: str = "") -> dict:
    """Decrypt a versioned JSON envelope string back to a credentials dict.

    Args:
        encrypted: JSON envelope string from encrypt_credentials.
        key: 32-byte AES-256 key.
        aad: Additional authenticated data (must match what was used for encryption).

    Returns:
        Decrypted credentials dict.

    Raises:
        CredentialDecryptionError: If decryption fails for any reason.
    """
    try:
        envelope = json.loads(encrypted)
    except (json.JSONDecodeError, TypeError) as e:
        raise CredentialDecryptionError(f"Invalid envelope format: {e}") from e

    version = envelope.get("v")
    if version != _CURRENT_VERSION:
        raise CredentialDecryptionError(
            f"Unsupported envelope version {version} (expected {_CURRENT_VERSION})"
        )

    alg = envelope.get("alg")
    if alg != _ALGORITHM:
        raise CredentialDecryptionError(
            f"Unsupported algorithm '{alg}' (expected '{_ALGORITHM}')"
        )

    try:
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ct"], validate=True)
    except (KeyError, Exception) as e:
        raise CredentialDecryptionError(f"Malformed envelope fields: {e}") from e

    if len(nonce) != 12:
        raise CredentialDecryptionError(
            f"Invalid nonce length {len(nonce)} (expected 12)"
        )

    try:
        aesgcm = AESGCM(key)
        aad_bytes = aad.encode("utf-8") if aad else None
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad_bytes)
        result = json.loads(plaintext.decode("utf-8"))
        if not isinstance(result, dict):
            raise CredentialDecryptionError(
                f"Decrypted payload is not a dict (got {type(result).__name__})"
            )
        return result
    except CredentialDecryptionError:
        raise
    except Exception as e:
        raise CredentialDecryptionError(f"Decryption failed: {e}") from e
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_credential_encryption.py -v`
Expected: All 17 tests PASS

**Step 5: Commit**

```bash
git add src/services/credential_encryption.py tests/services/test_credential_encryption.py
git commit -m "feat: add AES-256-GCM credential encryption with key source precedence and versioned envelope"
```

---

### Task 3: ProviderConnection Database Model + Migration

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/connection.py` (add migration for new table)
- Create: `tests/db/test_provider_connection_model.py`

**Step 1: Write the failing tests**

```python
# tests/db/test_provider_connection_model.py
"""Tests for ProviderConnection ORM model."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, ProviderConnection


@pytest.fixture
def db_session():
    """Create an in-memory SQLite DB with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class TestProviderConnectionModel:
    """Tests for ProviderConnection CRUD."""

    def test_create_ups_connection(self, db_session: Session):
        """Can create a UPS provider connection with connection_key."""
        conn = ProviderConnection(
            connection_key="ups:test",
            provider="ups",
            display_name="UPS (Test)",
            auth_mode="client_credentials",
            environment="test",
            status="configured",
            encrypted_credentials='{"v":1}',
            metadata_json='{"account_number": "123456"}',
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).first()
        assert result is not None
        assert result.connection_key == "ups:test"
        assert result.provider == "ups"
        assert result.status == "configured"
        assert result.schema_version == 1
        assert result.key_version == 1
        assert result.id is not None

    def test_create_shopify_connection(self, db_session: Session):
        """Can create a Shopify provider connection."""
        conn = ProviderConnection(
            connection_key="shopify:mystore.myshopify.com",
            provider="shopify",
            display_name="My Store",
            auth_mode="legacy_token",
            status="configured",
            encrypted_credentials='{"v":1}',
            metadata_json='{"store_domain": "mystore.myshopify.com"}',
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).filter_by(provider="shopify").first()
        assert result is not None
        assert result.connection_key == "shopify:mystore.myshopify.com"
        assert result.environment is None

    def test_unique_constraint_connection_key(self, db_session: Session):
        """Cannot create two connections with the same connection_key."""
        conn1 = ProviderConnection(
            connection_key="ups:test", provider="ups", display_name="UPS 1",
            auth_mode="client_credentials", environment="test", status="configured",
            encrypted_credentials="blob1",
        )
        conn2 = ProviderConnection(
            connection_key="ups:test", provider="ups", display_name="UPS 2",
            auth_mode="client_credentials", environment="test", status="configured",
            encrypted_credentials="blob2",
        )
        db_session.add(conn1)
        db_session.commit()
        db_session.add(conn2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_default_timestamps(self, db_session: Session):
        """created_at and updated_at are auto-populated."""
        conn = ProviderConnection(
            connection_key="ups:production", provider="ups", display_name="UPS",
            auth_mode="client_credentials", environment="production",
            status="configured", encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).first()
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_default_schema_and_key_version(self, db_session: Session):
        """schema_version and key_version default to 1."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups", display_name="UPS",
            auth_mode="client_credentials", environment="test",
            status="configured", encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).first()
        assert result.schema_version == 1
        assert result.key_version == 1


class TestProviderConnectionMigration:
    """Tests for idempotent table/column migration."""

    def test_migration_creates_table_on_empty_db(self):
        """Migration creates provider_connections on fresh DB."""
        from src.db.connection import _ensure_columns_exist

        engine = create_engine("sqlite:///:memory:")
        # Create other tables first (jobs, etc.) via metadata
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='provider_connections'"
            ))
            assert result.fetchone() is not None

    def test_migration_adds_missing_columns(self):
        """Migration adds columns to an existing table with partial schema."""
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            # Create a minimal table missing some columns
            conn.execute(text("""
                CREATE TABLE provider_connections (
                    id VARCHAR(36) PRIMARY KEY,
                    connection_key VARCHAR(255) NOT NULL UNIQUE,
                    provider VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'configured',
                    encrypted_credentials TEXT NOT NULL
                )
            """))
        # Run migration — should add missing columns
        from src.db.connection import _ensure_columns_exist
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
            result = conn.execute(text("PRAGMA table_info(provider_connections)"))
            columns = {row[1] for row in result.fetchall()}
            assert "display_name" in columns
            assert "auth_mode" in columns
            assert "schema_version" in columns
            assert "key_version" in columns
            assert "last_error_code" in columns

    def test_migration_is_idempotent(self):
        """Running migration twice doesn't error."""
        from src.db.connection import _ensure_columns_exist

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
        with engine.begin() as conn:
            _ensure_columns_exist(conn)  # Should not raise
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_provider_connection_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProviderConnection'`

**Step 3: Add ProviderConnection model to `src/db/models.py`**

Add after the `CustomCommand` class (the model is specified in the design doc — see Section 1). Include the `connection_key` unique column, `last_error_code`, `error_message`, `schema_version`, `key_version` fields. Single index on `provider` only (no redundant `connection_key` index since `UNIQUE` already creates one).

**Step 4: Add migration to `src/db/connection.py`**

Add to the end of `_ensure_columns_exist()`, following the existing pattern:

1. `CREATE TABLE IF NOT EXISTS provider_connections (...)` with all columns
2. `PRAGMA table_info(provider_connections)` to introspect existing columns
3. `ALTER TABLE provider_connections ADD COLUMN ...` for each missing column (idempotent)
4. `CREATE INDEX IF NOT EXISTS idx_provider_connections_provider ON provider_connections (provider)`

This handles fresh installs, existing installs with older schema, and partial upgrades.

**Step 5: Run tests to verify they pass**

Run: `pytest tests/db/test_provider_connection_model.py -v`
Expected: All 8 tests PASS

**Step 6: Commit**

```bash
git add src/db/models.py src/db/connection.py tests/db/test_provider_connection_model.py
git commit -m "feat: add ProviderConnection model with hardened idempotent migration"
```

---

### Task 4: ConnectionService Backend

**Files:**
- Create: `src/services/connection_service.py`
- Create: `tests/services/test_connection_service.py`

**Step 1: Write the failing tests**

Tests cover:
- CRUD: save (sets `"configured"`, returns `is_new` flag), get, list (ordered by `provider, connection_key`), delete, overwrite
- Credential resolver: `get_ups_credentials(environment)`, `get_shopify_credentials(store_domain)`
- Shopify dual resolver types: `ShopifyLegacyCredentials` for legacy, `ShopifyClientCredentials` for client_credentials_shopify
- Input validation: reject invalid provider, invalid auth_mode, missing required UPS fields, missing Shopify store_domain, missing Shopify access_token (legacy only)
- `client_credentials_shopify` does NOT require `access_token` (Phase 2 obtains it)
- Domain normalization: `"HTTPS://MyStore.MyShopify.com/"` → `"mystore.myshopify.com"`, invalid domain rejected
- UPS environment validation: reject `""`, `None`, `"sandbox"` — require `"test"` or `"production"`
- Disconnect: sets `"disconnected"`, preserves credentials
- Re-save on disconnected row resets status to `"configured"`
- Resolver skips `disconnected` and `needs_reconnect` rows
- Centralized AAD construction via `_build_aad()`
- Commit rollback: IntegrityError doesn't corrupt session

```python
# tests/services/test_connection_service.py
"""Tests for ConnectionService — provider connection lifecycle."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, ProviderConnection


@pytest.fixture
def db_session():
    """In-memory SQLite DB for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def key_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def service(db_session, key_dir):
    from src.services.connection_service import ConnectionService
    return ConnectionService(db=db_session, key_dir=key_dir)


class TestConnectionServiceCRUD:

    def test_save_ups_sets_configured_status(self, service):
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_secret"},
            metadata={"account_number": "123456"},
            environment="test", display_name="UPS (Test)",
        )
        assert result["status"] == "configured"
        assert result["connection_key"] == "ups:test"

    def test_save_returns_is_new_true_on_create(self, service):
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        assert result["is_new"] is True

    def test_save_returns_is_new_false_on_overwrite(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS Updated",
        )
        assert result["is_new"] is False

    def test_list_connections_ordered(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="production", display_name="UPS Prod",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok1"},
            metadata={"store_domain": "store.myshopify.com"},
            display_name="Shopify",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        connections = service.list_connections()
        keys = [c["connection_key"] for c in connections]
        assert keys == ["shopify:store.myshopify.com", "ups:production", "ups:test"]

    def test_get_never_exposes_credentials(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "secret_id", "client_secret": "secret_val"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = service.get_connection("ups:test")
        conn_str = str(conn)
        assert "secret_id" not in conn_str
        assert "secret_val" not in conn_str
        assert "encrypted_credentials" not in conn_str

    def test_delete_returns_false_for_nonexistent(self, service):
        assert service.delete_connection("ups:test") is False

    def test_save_overwrites_existing(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "old", "client_secret": "old"},
            metadata={}, environment="test", display_name="UPS Old",
        )
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "new", "client_secret": "new"},
            metadata={}, environment="test", display_name="UPS New",
        )
        conn = service.get_connection("ups:test")
        assert conn["display_name"] == "UPS New"
        assert len(service.list_connections()) == 1

    def test_disconnect_sets_status(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        assert service.disconnect("ups:test") is True
        conn = service.get_connection("ups:test")
        assert conn["status"] == "disconnected"

    def test_disconnect_nonexistent_returns_false(self, service):
        assert service.disconnect("ups:nonexistent") is False

    def test_resave_on_disconnected_resets_to_configured(self, service):
        """Re-saving credentials on a disconnected row resets to configured."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS Reconnected",
        )
        assert result["status"] == "configured"
        assert result["is_new"] is False

    def test_updated_at_changes_on_overwrite(self, service):
        """updated_at is refreshed on overwrite."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        first = service.get_connection("ups:test")
        import time; time.sleep(0.01)  # Ensure timestamp differs
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id2", "client_secret": "sec2"},
            metadata={}, environment="test", display_name="UPS v2",
        )
        second = service.get_connection("ups:test")
        assert second["updated_at"] >= first["updated_at"]


class TestCredentialResolver:

    def test_get_ups_credentials_test(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "my_id", "client_secret": "my_sec"},
            metadata={"account_number": "ACC1"},
            environment="test", display_name="UPS",
        )
        creds = service.get_ups_credentials("test")
        assert creds is not None
        assert creds.client_id == "my_id"
        assert creds.client_secret == "my_sec"
        assert creds.account_number == "ACC1"
        assert creds.environment == "test"
        assert "wwwcie" in creds.base_url

    def test_get_ups_credentials_production(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "prod_id", "client_secret": "prod_sec"},
            metadata={"account_number": "ACC1"},
            environment="production", display_name="UPS Prod",
        )
        creds = service.get_ups_credentials("production")
        assert "onlinetools.ups.com" in creds.base_url

    def test_get_ups_credentials_not_found(self, service):
        assert service.get_ups_credentials("test") is None

    def test_get_ups_credentials_skips_disconnected(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        assert service.get_ups_credentials("test") is None

    def test_get_ups_credentials_skips_needs_reconnect(self, service):
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status("ups:test", "needs_reconnect",
                              error_code="DECRYPT_FAILED", error_message="bad")
        assert service.get_ups_credentials("test") is None

    def test_get_shopify_legacy_credentials(self, service):
        from src.services.connection_service import ShopifyLegacyCredentials
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_abc"},
            metadata={"store_domain": "mystore.myshopify.com"},
            display_name="My Store",
        )
        creds = service.get_shopify_credentials("mystore.myshopify.com")
        assert isinstance(creds, ShopifyLegacyCredentials)
        assert creds.access_token == "shpat_abc"
        assert creds.store_domain == "mystore.myshopify.com"

    def test_get_shopify_client_credentials(self, service):
        from src.services.connection_service import ShopifyClientCredentials
        service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "store2.myshopify.com"},
            display_name="Store 2",
        )
        creds = service.get_shopify_credentials("store2.myshopify.com")
        assert isinstance(creds, ShopifyClientCredentials)
        assert creds.client_id == "cid"
        assert creds.client_secret == "csec"
        assert creds.access_token == ""  # Not required in Phase 1

    def test_get_shopify_credentials_not_found(self, service):
        assert service.get_shopify_credentials("nonexistent.myshopify.com") is None

    def test_get_shopify_credentials_skips_disconnected(self, service):
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        service.disconnect("shopify:s.myshopify.com")
        assert service.get_shopify_credentials("s.myshopify.com") is None

    def test_get_shopify_credentials_skips_needs_reconnect(self, service):
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        service.update_status("shopify:s.myshopify.com", "needs_reconnect",
                              error_code="DECRYPT_FAILED", error_message="bad")
        assert service.get_shopify_credentials("s.myshopify.com") is None


class TestInputValidation:

    def test_reject_invalid_provider(self, service):
        with pytest.raises(ValueError, match="Invalid provider"):
            service.save_connection(
                provider="fedex", auth_mode="token",
                credentials={}, metadata={}, display_name="FedEx",
            )

    def test_reject_invalid_ups_auth_mode(self, service):
        with pytest.raises(ValueError, match="Invalid auth_mode"):
            service.save_connection(
                provider="ups", auth_mode="oauth_loopback",
                credentials={}, metadata={}, environment="test", display_name="UPS",
            )

    def test_ups_requires_client_id(self, service):
        with pytest.raises(ValueError, match="client_id"):
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "", "client_secret": "sec"},
                metadata={}, environment="test", display_name="UPS",
            )

    def test_ups_requires_environment(self, service):
        with pytest.raises(ValueError, match="environment"):
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment=None, display_name="UPS",
            )

    def test_ups_rejects_invalid_environment(self, service):
        with pytest.raises(ValueError, match="environment"):
            service.save_connection(
                provider="ups", auth_mode="client_credentials",
                credentials={"client_id": "id", "client_secret": "sec"},
                metadata={}, environment="sandbox", display_name="UPS",
            )

    def test_shopify_requires_store_domain(self, service):
        with pytest.raises(ValueError, match="store_domain"):
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": "tok"}, metadata={},
                display_name="Store",
            )

    def test_shopify_rejects_invalid_domain(self, service):
        with pytest.raises(ValueError, match="myshopify.com"):
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={"access_token": "tok"},
                metadata={"store_domain": "notshopify.example.com"},
                display_name="Store",
            )

    def test_shopify_normalizes_domain(self, service):
        result = service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "HTTPS://MyStore.MyShopify.com/"},
            display_name="Store",
        )
        assert result["connection_key"] == "shopify:mystore.myshopify.com"
        meta = result["metadata"]
        assert meta["store_domain"] == "mystore.myshopify.com"

    def test_shopify_legacy_requires_access_token(self, service):
        with pytest.raises(ValueError, match="access_token"):
            service.save_connection(
                provider="shopify", auth_mode="legacy_token",
                credentials={}, metadata={"store_domain": "x.myshopify.com"},
                display_name="Store",
            )

    def test_shopify_client_credentials_requires_client_id(self, service):
        with pytest.raises(ValueError, match="client_id"):
            service.save_connection(
                provider="shopify", auth_mode="client_credentials_shopify",
                credentials={}, metadata={"store_domain": "x.myshopify.com"},
                display_name="Store",
            )

    def test_shopify_client_credentials_does_not_require_access_token(self, service):
        result = service.save_connection(
            provider="shopify", auth_mode="client_credentials_shopify",
            credentials={"client_id": "cid", "client_secret": "csec"},
            metadata={"store_domain": "x.myshopify.com"},
            display_name="Store",
        )
        assert result["status"] == "configured"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Key implementation details:
- Three credential dataclasses: `UPSCredentials`, `ShopifyLegacyCredentials`, `ShopifyClientCredentials`
- `ShopifyClientCredentials.access_token` defaults to `""` (not required in Phase 1)
- `_normalize_shopify_domain()` — lowercase, strip protocol, strip trailing slashes, validate `*.myshopify.com`
- `_validate_save_input()` — validates provider, auth_mode, required fields per provider, UPS environment required and must be `"test"` or `"production"`
- `_build_aad(row)` — centralized AAD construction: `f"{row.provider}:{row.auth_mode}:{row.connection_key}"`
- `save_connection()` returns `is_new: bool` flag, always sets status to `"configured"` (even on disconnected overwrite)
- `disconnect(connection_key)` — sets `"disconnected"` status, preserves credentials
- `get_ups_credentials(environment)` — skips `disconnected` and `needs_reconnect` rows
- `get_shopify_credentials(store_domain)` — requires explicit store domain, normalizes input before lookup, skips `disconnected` and `needs_reconnect` rows, returns typed union
- `list_connections()` — orders by `(provider, connection_key)` for deterministic results
- `encrypt_credentials()` uses `json.dumps(sort_keys=True)` for canonical serialization
- All commit paths wrapped in try/except with rollback

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: All 30 tests PASS

**Step 5: Commit**

```bash
git add src/services/connection_service.py tests/services/test_connection_service.py
git commit -m "feat: add ConnectionService with typed resolvers, skip-status policy, and centralized AAD"
```

---

### Task 5: Connections API Routes

**Files:**
- Create: `src/api/routes/connections.py`
- Modify: `src/api/main.py` (register router)
- Create: `tests/api/test_connections.py`

**Step 1: Write the failing tests**

Tests cover:
- `GET /connections/` returns empty list, ordered results
- `POST /connections/ups/save` saves and returns `201` on create, `200` on overwrite
- `POST /connections/shopify/save` saves Shopify credentials (URL-encoded domain in key)
- Invalid provider → 400
- Missing required fields → 400
- `GET /connections/{connection_key}` with URL-encoded key
- `GET /connections/{connection_key}` not found → 404
- `DELETE /connections/{connection_key}` → 200, not found → 404
- `POST /connections/{connection_key}/disconnect` preserves credentials
- Disconnect/list/get responses after disconnect show status but no credentials
- No credentials ever in list/get responses
- Error responses never contain credential values (use `redact_for_logging`)

**API test fixture:** Use `StaticPool` for in-memory SQLite:

```python
from sqlalchemy.pool import StaticPool

@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_connections.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the routes**

Key implementation details:
- Route: `POST /{provider}/save` (not `/connect`)
- Check `result["is_new"]` to return `201` or `200`
- All error paths raise `HTTPException` with proper status codes
- `ValueError` from service → 400
- Not found → 404
- 500 uses `redact_for_logging()` — never raw exception strings or credential values
- No `success: bool` field in connection responses
- Ensure Pydantic field validators don't echo submitted secrets in 422 responses

**Step 4: Register the router in `src/api/main.py`**

Add import and `app.include_router(connections.router, prefix="/api/v1")`.

**Step 5: Run tests to verify they pass**

Run: `pytest tests/api/test_connections.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/api/routes/connections.py src/api/main.py tests/api/test_connections.py
git commit -m "feat: add /connections API routes with 201/200 save semantics and redacted errors"
```

---

### Task 6: Startup Decryptability Check

**Files:**
- Modify: `src/services/connection_service.py` (add `check_all`)
- Modify: `src/api/main.py` (call on startup)
- Create: `tests/services/test_startup_check.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_startup_check.py
"""Tests for startup decryptability check."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderConnection


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def key_dir(tmp_path):
    return str(tmp_path)


class TestStartupCheck:

    def test_check_all_preserves_configured_status(self, db_session, key_dir):
        """check_all does NOT promote status to 'connected' on successful decrypt."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={"account_number": "ACC"},
            environment="test", display_name="UPS Test",
        )
        results = service.check_all()
        assert results["ups:test"] == "ok"
        conn = service.get_connection("ups:test")
        assert conn["status"] == "configured"

    def test_check_all_recovers_needs_reconnect(self, db_session, key_dir):
        """Successful decrypt recovers needs_reconnect → configured."""
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
        from src.services.connection_service import ConnectionService
        service = ConnectionService(db=db_session, key_dir=key_dir)
        assert service.check_all() == {}

    def test_check_all_decrypt_failure_marks_needs_reconnect(self, db_session, key_dir):
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
        import shutil

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_startup_check.py -v`
Expected: FAIL

**Step 3: Implement `check_all()`**

`check_all()` implementation:
- Reads all `ProviderConnection` rows
- For each row, attempts to decrypt credentials using `_build_aad(row)` for AAD
- On success:
  - If status is `"needs_reconnect"`: recover to `"configured"`, clear `last_error_code` and `error_message`
  - All other statuses: preserve status AND error fields
- On decrypt failure: sets `status = "needs_reconnect"`, `last_error_code = "DECRYPT_FAILED"`
- Returns dict of `connection_key -> "ok" | "error"`
- Does NOT write to `os.environ`
- Logs warnings using `redact_for_logging()` for failed rows

**Step 4: Add startup call in `src/api/main.py`**

After `init_db()` in lifespan:

```python
    try:
        with get_db_context() as db:
            from src.services.connection_service import ConnectionService
            conn_service = ConnectionService(db=db)
            check_results = conn_service.check_all()
            if check_results:
                logger.info("Provider credential check results: %s", check_results)
    except Exception as e:
        logger.warning("Provider credential check failed (non-blocking): %s", e)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/services/test_startup_check.py -v`
Expected: All 7 tests PASS

**Step 6: Commit**

```bash
git add src/services/connection_service.py src/api/main.py tests/services/test_startup_check.py
git commit -m "feat: add startup decryptability check with needs_reconnect recovery and wrong-key detection"
```

---

### Task 7: Runtime Credential Adapter

**Files:**
- Create: `src/services/runtime_credentials.py`
- Create: `tests/services/test_runtime_credentials.py`

This is the **single contract** for runtime credential resolution. All call sites use this module.

**Step 1: Write the failing tests**

```python
# tests/services/test_runtime_credentials.py
"""Tests for runtime credential adapter."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def key_dir(tmp_path):
    return str(tmp_path)


class TestResolveUPSCredentials:

    def test_returns_db_credentials(self, db_session, key_dir):
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "db_id", "client_secret": "db_sec"},
            metadata={"account_number": "ACC"}, environment="test",
            display_name="UPS",
        )
        creds = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert creds is not None
        assert creds.client_id == "db_id"

    def test_falls_back_to_env(self, db_session, key_dir):
        from src.services.runtime_credentials import resolve_ups_credentials

        os.environ["UPS_CLIENT_ID"] = "env_id"
        os.environ["UPS_CLIENT_SECRET"] = "env_sec"
        try:
            creds = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
            assert creds is not None
            assert creds.client_id == "env_id"
        finally:
            os.environ.pop("UPS_CLIENT_ID", None)
            os.environ.pop("UPS_CLIENT_SECRET", None)

    def test_returns_none_when_neither(self, db_session, key_dir):
        from src.services.runtime_credentials import resolve_ups_credentials

        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        creds = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert creds is None

    def test_skips_disconnected(self, db_session, key_dir):
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_ups_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.disconnect("ups:test")
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET"):
            os.environ.pop(var, None)
        creds = resolve_ups_credentials(environment="test", db=db_session, key_dir=key_dir)
        assert creds is None


class TestResolveShopifyCredentials:

    def test_returns_db_credentials(self, db_session, key_dir):
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "shpat_db"},
            metadata={"store_domain": "mystore.myshopify.com"},
            display_name="My Store",
        )
        result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
        assert result is not None
        assert result["access_token"] == "shpat_db"
        assert result["store_domain"] == "mystore.myshopify.com"

    def test_falls_back_to_env(self, db_session, key_dir):
        from src.services.runtime_credentials import resolve_shopify_credentials

        os.environ["SHOPIFY_ACCESS_TOKEN"] = "env_tok"
        os.environ["SHOPIFY_STORE_DOMAIN"] = "env.myshopify.com"
        try:
            result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
            assert result is not None
            assert result["access_token"] == "env_tok"
        finally:
            os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
            os.environ.pop("SHOPIFY_STORE_DOMAIN", None)

    def test_returns_none_when_neither(self, db_session, key_dir):
        from src.services.runtime_credentials import resolve_shopify_credentials

        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)
        result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
        assert result is None

    def test_skips_disconnected(self, db_session, key_dir):
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok"},
            metadata={"store_domain": "s.myshopify.com"},
            display_name="Store",
        )
        service.disconnect("shopify:s.myshopify.com")
        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)
        result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
        assert result is None

    def test_deterministic_default_selection(self, db_session, key_dir):
        """Without explicit store_domain, picks first by connection_key ASC."""
        from src.services.connection_service import ConnectionService
        from src.services.runtime_credentials import resolve_shopify_credentials

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok_z"},
            metadata={"store_domain": "zstore.myshopify.com"},
            display_name="Z Store",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok_a"},
            metadata={"store_domain": "astore.myshopify.com"},
            display_name="A Store",
        )
        result = resolve_shopify_credentials(db=db_session, key_dir=key_dir)
        assert result["store_domain"] == "astore.myshopify.com"  # a < z
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_runtime_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/services/runtime_credentials.py
"""Runtime credential adapter — single contract for all credential resolution.

All runtime call sites use this module instead of ad hoc os.environ reads.
DB-stored credentials take priority over env vars.

Fallback warnings are logged at most once per process lifetime to avoid noise.
"""

import logging
import os

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_ups_fallback_warned = False
_shopify_fallback_warned = False


def resolve_ups_credentials(
    environment: str | None = None,
    db: Session | None = None,
    key_dir: str | None = None,
):
    """Resolve UPS credentials: DB-stored (priority) → env var (fallback).

    Args:
        environment: "test" or "production". Defaults to UPS_ENVIRONMENT env or "test".
        db: SQLAlchemy session. If None, attempts to create one.
        key_dir: Key directory override (testing).

    Returns:
        UPSCredentials if available, None if neither source configured.
    """
    global _ups_fallback_warned
    from src.services.connection_service import UPSCredentials

    env = environment or os.environ.get("UPS_ENVIRONMENT", "test")

    # Try DB-stored credentials first
    if db is not None:
        try:
            from src.services.connection_service import ConnectionService
            service = ConnectionService(db=db, key_dir=key_dir)
            creds = service.get_ups_credentials(env)
            if creds is not None:
                return creds
        except Exception as e:
            logger.warning(
                "Failed to resolve UPS credentials from DB (environment=%s): %s",
                env, type(e).__name__,
            )

    # Fallback to env vars
    client_id = os.environ.get("UPS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("UPS_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        if not _ups_fallback_warned:
            logger.warning(
                "Using UPS credentials from environment variables "
                "(no DB-stored credentials for environment=%s). "
                "Save credentials in Settings for persistent storage.", env,
            )
            _ups_fallback_warned = True
        base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
        derived_env = "test" if "wwwcie" in base_url else "production"
        return UPSCredentials(
            client_id=client_id,
            client_secret=client_secret,
            account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
            environment=derived_env,
            base_url=base_url,
        )

    return None


def resolve_shopify_credentials(
    store_domain: str | None = None,
    db: Session | None = None,
    key_dir: str | None = None,
) -> dict | None:
    """Resolve Shopify credentials: DB-stored (priority) → env var (fallback).

    Args:
        store_domain: Explicit domain. If None, picks first available DB connection
                      ordered by connection_key ASC (Phase 1 single-store default).
        db: SQLAlchemy session. If None, attempts to create one.
        key_dir: Key directory override (testing).

    Returns:
        Dict with 'access_token' and 'store_domain', or None.
    """
    global _shopify_fallback_warned

    # Try DB-stored credentials first
    if db is not None:
        try:
            from src.services.connection_service import ConnectionService
            service = ConnectionService(db=db, key_dir=key_dir)
            if store_domain:
                creds = service.get_shopify_credentials(store_domain)
            else:
                # Phase 1 default: first non-skipped Shopify connection
                # Deterministic via ORDER BY connection_key ASC in list_connections
                creds = service.get_first_shopify_credentials()
            if creds is not None:
                return {
                    "access_token": getattr(creds, "access_token", ""),
                    "store_domain": creds.store_domain,
                }
        except Exception as e:
            logger.warning(
                "Failed to resolve Shopify credentials from DB: %s",
                type(e).__name__,
            )

    # Fallback to env vars
    access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "").strip()
    if access_token and domain:
        if not _shopify_fallback_warned:
            logger.warning(
                "Using Shopify credentials from environment variables. "
                "Save credentials in Settings for persistent storage.",
            )
            _shopify_fallback_warned = True
        return {"access_token": access_token, "store_domain": domain}

    return None
```

Note: `get_first_shopify_credentials()` is a new method added to `ConnectionService` that returns the first non-skipped Shopify connection ordered by `connection_key ASC`. This ensures deterministic Phase 1 default selection.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_runtime_credentials.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add src/services/runtime_credentials.py tests/services/test_runtime_credentials.py
git commit -m "feat: add runtime credential adapter with DB priority, env fallback, and safe logging"
```

---

### Task 8: UPS Runtime Call Site Integration

**Files:**
- Modify: `src/orchestrator/agent/config.py` (accept `UPSCredentials` parameter)
- Modify: `src/orchestrator/agent/client.py` (call `resolve_ups_credentials()`)
- Modify: `src/services/batch_executor.py` (accept `UPSCredentials` parameter)
- Modify: `src/services/gateway_provider.py` (accept `UPSCredentials` parameter)
- Modify: `src/orchestrator/agent/tools/pipeline.py` (use `resolve_ups_credentials()`)
- Modify: `src/orchestrator/agent/tools/interactive.py` (use `resolve_ups_credentials()`)
- Create: `tests/services/test_ups_call_site_integration.py`

**Step 1: Write the failing tests**

Tests for `get_ups_mcp_config(credentials=...)`, `create_mcp_servers_config(ups_credentials=...)`, and env fallback behavior.

**Step 2: Run tests to verify they fail**

**Step 3: Implement changes**

1. **`config.py:get_ups_mcp_config()`** — add `credentials: UPSCredentials | None = None`. When provided, use typed values instead of env vars.
2. **`config.py:create_mcp_servers_config()`** — add `ups_credentials: UPSCredentials | None = None`, pass to `get_ups_mcp_config()`.
3. **`client.py:_create_options()`** — call `resolve_ups_credentials()` before creating MCP config. Log warning (redacted) if no credentials available.
4. **`batch_executor.py:execute_batch()`** — add optional `ups_credentials` param.
5. **`gateway_provider.py:_build_ups_gateway()`** — add optional `ups_credentials` param.
6. **`tools/pipeline.py`** — call `resolve_ups_credentials()` for `account_number`.
7. **`tools/interactive.py`** — call `resolve_ups_credentials()` for `account_number`.

**Step 4: Run tests + verify no regressions**

Run: `pytest tests/services/test_ups_call_site_integration.py tests/orchestrator/agent/ -v -k "not stream and not sse"`

**Step 5: Commit**

```bash
git add src/orchestrator/agent/config.py src/orchestrator/agent/client.py src/services/batch_executor.py src/services/gateway_provider.py src/orchestrator/agent/tools/pipeline.py src/orchestrator/agent/tools/interactive.py tests/services/test_ups_call_site_integration.py
git commit -m "feat: wire UPS runtime call sites to runtime_credentials adapter"
```

---

### Task 9: Shopify Runtime Call Site Integration

**Files:**
- Modify: `src/orchestrator/agent/tools/data.py`
- Modify: `src/orchestrator/agent/system_prompt.py`
- Modify: `src/services/batch_executor.py`
- Modify: `src/api/routes/platforms.py`
- Create: `tests/services/test_shopify_call_site_integration.py`

**Step 1: Write the failing tests**

Tests for `resolve_shopify_credentials()` usage at each call site: DB credentials used, env fallback, None handling.

**Step 2: Run tests to verify they fail**

**Step 3: Implement changes**

1. **`tools/data.py:connect_shopify_tool()`** — call `resolve_shopify_credentials()` first.
2. **`tools/data.py:get_platform_status_tool()`** — same pattern.
3. **`system_prompt.py:build_system_prompt()`** — check `resolve_shopify_credentials()` for Shopify config detection.
4. **`batch_executor.py:get_shipper_for_job()`** — use `resolve_shopify_credentials()`.
5. **`platforms.py:get_shopify_env_status()`** — check DB credentials first.

**CLI paths (`http_client.py`, `runner.py`):** Phase 1 leaves as env-only. Add TODO comment for Phase 2.

**Step 4: Run tests + verify no regressions**

Run: `pytest tests/services/test_shopify_call_site_integration.py tests/orchestrator/ tests/api/routes/ -v -k "not stream and not sse"`

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/data.py src/orchestrator/agent/system_prompt.py src/services/batch_executor.py src/api/routes/platforms.py tests/services/test_shopify_call_site_integration.py
git commit -m "feat: wire Shopify runtime call sites to runtime_credentials adapter"
```

---

### Task 10: Frontend Types and API Client

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add TypeScript types to `frontend/src/types/api.ts`**

```typescript
// === Provider Connection Types ===

export type ProviderType = 'ups' | 'shopify';

export type ProviderConnectionStatus =
  | 'configured'
  | 'validating'
  | 'connected'
  | 'disconnected'
  | 'error'
  | 'needs_reconnect';

export type ProviderAuthMode = 'client_credentials' | 'legacy_token' | 'client_credentials_shopify';

export interface ProviderConnectionInfo {
  id: string;
  connection_key: string;
  provider: ProviderType;
  display_name: string;
  auth_mode: ProviderAuthMode;
  environment: string | null;
  status: ProviderConnectionStatus;
  metadata: Record<string, unknown>;
  last_validated_at: string | null;
  last_error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SaveProviderRequest {
  auth_mode: string;
  credentials: Record<string, string>;
  metadata: Record<string, unknown>;
  display_name: string;
  environment?: string;
}

export interface ProviderConnectionListResponse {
  connections: ProviderConnectionInfo[];
  count: number;
}
```

**Step 2: Add API functions to `frontend/src/lib/api.ts`**

All `connectionKey` values passed through `encodeURIComponent()`. Function names match route semantics (`saveProviderCredentials` for `/save`).

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat: add frontend types and API client for provider connections"
```

---

### Task 11: Frontend State Management (useAppState)

Same as prior revision — add `providerConnections`, `providerConnectionsLoading`, `providerConnectionsVersion`, `refreshProviderConnections()` to `useAppState`. Import `ProviderConnectionInfo` type. Add cleanup flag for unmount safety.

**Commit:**

```bash
git add frontend/src/hooks/useAppState.tsx
git commit -m "feat: add provider connections state to useAppState"
```

---

### Task 12: ConnectionsSection + ProviderCard Components

**Files:**
- Create: `frontend/src/components/settings/ConnectionsSection.tsx`
- Create: `frontend/src/components/settings/ProviderCard.tsx`
- Modify: `frontend/src/components/settings/SettingsFlyout.tsx`

Key Phase 1 UI decisions:
- **UPS card:** One card with Test/Production environment toggle (two subprofiles within), parent badge showing "X/2 configured"
- **Shopify card:** One card, single store only
- **Status badges:** `configured` = blue, `disconnected` = grey, `error`/`needs_reconnect` = amber
- **No "Test" button** in Phase 1
- **Credential display after save:** Placeholder dots (`••••••••`), "Replace credentials" action
- **Button loading states:** Save/Disconnect/Delete buttons show spinner during API call, disabled to prevent duplicate submission
- **Confirmation dialog:** Required for Delete (destructive), not required for Disconnect (reversible via re-save)
- **Inline error display:** Save failures show inline error below form, card stays expanded

**Commit:**

```bash
git add frontend/src/components/settings/ConnectionsSection.tsx frontend/src/components/settings/ProviderCard.tsx frontend/src/components/settings/SettingsFlyout.tsx
git commit -m "feat: add ConnectionsSection and ProviderCard to Settings flyout"
```

---

### Task 13: UPSConnectForm Component

**Files:**
- Create: `frontend/src/components/settings/UPSConnectForm.tsx`

Fields: Client ID, Client Secret, Account Number (optional), Environment (tab toggle: Test / Production, **no default — required selection**). Each environment submits as its own `connection_key`.

After save: form collapses, shows `••••••••` placeholders with "Replace credentials" action.
Loading states on Save button. Inline error on failure.

**Commit:**

```bash
git add frontend/src/components/settings/UPSConnectForm.tsx frontend/src/components/settings/ConnectionsSection.tsx
git commit -m "feat: add UPS credential form with two-environment tab toggle"
```

---

### Task 14: ShopifyConnectForm Component

**Files:**
- Create: `frontend/src/components/settings/ShopifyConnectForm.tsx`

Radio selector: "I have an access token" (legacy) vs "I have client credentials" (new).

- Legacy mode: shows `access_token` field (required)
- Client credentials mode: shows `client_id` + `client_secret` fields (no `access_token` — Phase 2)

Store domain validated against `*.myshopify.com` on blur. Loading states on Save. Inline errors.

**Commit:**

```bash
git add frontend/src/components/settings/ShopifyConnectForm.tsx frontend/src/components/settings/ConnectionsSection.tsx
git commit -m "feat: add Shopify connect form with auth mode selector"
```

---

### Task 15: DataSourcePanel Migration

**Files:**
- Modify: `frontend/src/components/sidebar/DataSourcePanel.tsx`

Check `providerConnections` from `useAppState`:
- Shopify `configured` or `connected` → show as available data source with switch button
- Shopify `disconnected`, `error`, `needs_reconnect`, or not configured → show "Connect Shopify in Settings" link that calls `setSettingsFlyoutOpen(true)`
- Remove inline Shopify token entry form
- Remove `handleShopifyConnect` function

**Commit:**

```bash
git add frontend/src/components/sidebar/DataSourcePanel.tsx
git commit -m "refactor: move Shopify credentials from DataSourcePanel to Settings"
```

---

### Task 16: Integration + Edge Case Tests

**Files:**
- Create: `tests/integration/test_connection_round_trip.py`

Tests cover:
- Full UPS lifecycle: save → list → decrypt → disconnect → re-save (resets to configured) → delete
- Full Shopify lifecycle: save legacy → list → decrypt → delete
- Multiple UPS environments coexist without clobber
- Corrupt metadata_json doesn't crash list/get
- API error responses never contain credential values
- Shopify domain normalization produces correct connection_key
- Shopify client credentials resolver returns typed object with empty `access_token`
- Disconnect prevents resolver from returning credentials
- `check_all()` recovery path: `needs_reconnect` → `configured`
- `check_all()` with wrong key: valid creds become `needs_reconnect`
- UPS runtime resolver: config uses DB credentials, falls back to env
- Shopify runtime resolver: deterministic default selection (ORDER BY connection_key ASC)
- Overwrite on disconnected row resets to `configured`
- Multi-row Shopify default selection is deterministic

**Commit:**

```bash
git add tests/integration/test_connection_round_trip.py
git commit -m "test: add integration and edge case tests for connection lifecycle"
```

---

### Task 17: Final Verification + TypeScript Check

**Step 1: Run full backend test suite (excluding known hangs)**

Run: `pytest -k "not stream and not sse and not progress and not test_stream_endpoint_exists" -v --tb=short`
Expected: All existing tests still pass, new tests pass

**Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Run frontend dev server and verify UI**

Run: `cd frontend && npm run dev`
Verify:
- Settings flyout → Connections section renders with UPS and Shopify cards
- UPS two-environment tabs work (Test/Production)
- Save flow works for both providers
- `••••••••` placeholders shown after save
- Loading spinners on Save/Disconnect/Delete buttons
- Delete confirmation dialog
- Inline error messages on save failure
- Shopify auth mode selector works

**Step 4: Verify runtime integration**

- Save UPS credentials through Settings UI
- Verify agent MCP config picks up DB-stored credentials (check backend logs for absence of env fallback warning)
- Save Shopify credentials through Settings UI
- Verify DataSourcePanel shows "Switch to Shopify" option
- Verify disconnect hides Shopify from DataSourcePanel

**Step 5: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final verification and cleanup for settings connections"
```
