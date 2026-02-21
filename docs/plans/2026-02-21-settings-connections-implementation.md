# Settings Connections Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent encrypted credential storage and a Settings UI for connecting UPS and Shopify providers, replacing the .env-only workflow.

**Architecture:** New `ProviderConnection` SQLAlchemy model with AES-256-GCM encrypted credentials. `ConnectionService` handles CRUD, validation, and auto-reconnect on startup. Frontend adds a Connections accordion section to the existing SettingsFlyout with per-provider cards and forms.

**Tech Stack:** Python `cryptography` (AES-256-GCM), SQLAlchemy, FastAPI, React + TypeScript + Tailwind

---

### Task 1: Credential Encryption Module

**Files:**
- Create: `src/services/credential_encryption.py`
- Create: `tests/services/test_credential_encryption.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_credential_encryption.py
"""Tests for AES-256-GCM credential encryption."""

import json
import os
import stat
import tempfile

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

    def test_key_file_has_restricted_permissions(self, temp_key_dir):
        """Key file should be owner-read-write only (0600)."""
        from src.services.credential_encryption import get_or_create_key

        get_or_create_key(key_dir=temp_key_dir)
        key_path = os.path.join(temp_key_dir, ".shipagent_key")
        mode = os.stat(key_path).st_mode
        assert stat.S_IMODE(mode) == 0o600


class TestEncryptDecrypt:
    """Tests for AES-256-GCM encrypt/decrypt round-trip."""

    def test_round_trip(self, temp_key_dir):
        """Encrypt then decrypt returns original data."""
        from src.services.credential_encryption import decrypt_credentials, encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        plaintext = {"client_id": "test_id", "client_secret": "test_secret"}
        ciphertext = encrypt_credentials(plaintext, key)
        result = decrypt_credentials(ciphertext, key)
        assert result == plaintext

    def test_different_nonce_each_call(self, temp_key_dir):
        """Each encryption produces different ciphertext (unique nonce)."""
        from src.services.credential_encryption import encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        plaintext = {"token": "abc123"}
        ct1 = encrypt_credentials(plaintext, key)
        ct2 = encrypt_credentials(plaintext, key)
        assert ct1 != ct2

    def test_wrong_key_fails(self, temp_key_dir):
        """Decryption with wrong key raises an error."""
        from src.services.credential_encryption import decrypt_credentials, encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"secret": "data"}, key)
        wrong_key = os.urandom(32)
        with pytest.raises(Exception):
            decrypt_credentials(ciphertext, wrong_key)

    def test_tampered_ciphertext_fails(self, temp_key_dir):
        """Tampered ciphertext raises authentication error."""
        import base64

        from src.services.credential_encryption import decrypt_credentials, encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"key": "val"}, key)
        raw = base64.b64decode(ciphertext)
        tampered = raw[:-1] + bytes([raw[-1] ^ 0xFF])
        tampered_b64 = base64.b64encode(tampered).decode()
        with pytest.raises(Exception):
            decrypt_credentials(tampered_b64, key)

    def test_empty_dict_round_trip(self, temp_key_dir):
        """Empty credentials dict encrypts and decrypts cleanly."""
        from src.services.credential_encryption import decrypt_credentials, encrypt_credentials, get_or_create_key

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({}, key)
        assert decrypt_credentials(ciphertext, key) == {}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_credential_encryption.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.credential_encryption'`

**Step 3: Write implementation**

```python
# src/services/credential_encryption.py
"""AES-256-GCM credential encryption for persistent provider storage.

Provides encrypt/decrypt for JSON credential blobs and key file management.
The encryption key is stored in a .shipagent_key file with 0600 permissions.

Format: nonce (12 bytes) || ciphertext || tag (16 bytes) → base64 encoded.
"""

import base64
import json
import logging
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

KEY_FILENAME = ".shipagent_key"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_or_create_key(key_dir: str | None = None) -> bytes:
    """Load or generate the 32-byte AES-256 encryption key.

    Creates the key file with 0600 permissions if it doesn't exist.

    Args:
        key_dir: Directory for the key file. Defaults to project root.

    Returns:
        32-byte encryption key.
    """
    directory = key_dir or str(_PROJECT_ROOT)
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

    logger.info("Generated new encryption key at %s", key_path)
    return key


def encrypt_credentials(credentials: dict, key: bytes) -> str:
    """Encrypt a credentials dict to a base64-encoded ciphertext string.

    Args:
        credentials: Dict of credential key-value pairs.
        key: 32-byte AES-256 key.

    Returns:
        Base64-encoded string: nonce (12B) || ciphertext || tag (16B).
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = json.dumps(credentials).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_credentials(encrypted: str, key: bytes) -> dict:
    """Decrypt a base64-encoded ciphertext string back to a credentials dict.

    Args:
        encrypted: Base64-encoded string from encrypt_credentials.
        key: 32-byte AES-256 key.

    Returns:
        Decrypted credentials dict.

    Raises:
        cryptography.exceptions.InvalidTag: If key is wrong or data is tampered.
    """
    raw = base64.b64decode(encrypted)
    nonce = raw[:12]
    ciphertext = raw[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_credential_encryption.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/services/credential_encryption.py tests/services/test_credential_encryption.py
git commit -m "feat: add AES-256-GCM credential encryption module"
```

---

### Task 2: ProviderConnection Database Model

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/connection.py` (add migration for new table)
- Create: `tests/db/test_provider_connection_model.py`

**Step 1: Write the failing test**

```python
# tests/db/test_provider_connection_model.py
"""Tests for ProviderConnection ORM model."""

import pytest
from sqlalchemy import create_engine
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
        """Can create a UPS provider connection."""
        conn = ProviderConnection(
            provider="ups",
            display_name="UPS (Test)",
            auth_mode="client_credentials",
            environment="test",
            status="connected",
            encrypted_credentials="encrypted_blob_here",
            metadata_json='{"account_number": "123456"}',
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).first()
        assert result is not None
        assert result.provider == "ups"
        assert result.display_name == "UPS (Test)"
        assert result.environment == "test"
        assert result.status == "connected"
        assert result.id is not None

    def test_create_shopify_connection(self, db_session: Session):
        """Can create a Shopify provider connection."""
        conn = ProviderConnection(
            provider="shopify",
            display_name="My Store",
            auth_mode="legacy_token",
            status="connected",
            encrypted_credentials="encrypted_blob_here",
            metadata_json='{"store_domain": "mystore.myshopify.com"}',
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).filter_by(provider="shopify").first()
        assert result is not None
        assert result.auth_mode == "legacy_token"
        assert result.environment is None

    def test_unique_constraint_provider_environment(self, db_session: Session):
        """Cannot create two connections for the same provider+environment."""
        from sqlalchemy.exc import IntegrityError

        conn1 = ProviderConnection(
            provider="ups", display_name="UPS 1", auth_mode="client_credentials",
            environment="test", status="connected", encrypted_credentials="blob1",
        )
        conn2 = ProviderConnection(
            provider="ups", display_name="UPS 2", auth_mode="client_credentials",
            environment="test", status="connected", encrypted_credentials="blob2",
        )
        db_session.add(conn1)
        db_session.commit()
        db_session.add(conn2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_default_timestamps(self, db_session: Session):
        """created_at and updated_at are auto-populated."""
        conn = ProviderConnection(
            provider="ups", display_name="UPS", auth_mode="client_credentials",
            environment="production", status="disconnected", encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()

        result = db_session.query(ProviderConnection).first()
        assert result.created_at is not None
        assert result.updated_at is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_provider_connection_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProviderConnection'`

**Step 3: Add ProviderConnection model to `src/db/models.py`**

Add after the `CustomCommand` class (around line 692):

```python
class ProviderConnection(Base):
    """Persistent provider connection with encrypted credentials.

    Stores connection metadata and AES-256-GCM encrypted credential
    blobs for UPS and Shopify providers. Secrets are never stored
    in plaintext.

    Attributes:
        provider: Provider identifier ('ups' or 'shopify').
        display_name: Human-readable label (e.g., 'UPS Production').
        auth_mode: Authentication mode ('client_credentials', 'legacy_token',
            'client_credentials_shopify').
        environment: UPS environment ('test' or 'production'). Null for Shopify.
        status: Connection status ('connected', 'disconnected', 'error',
            'needs_reconnect').
        encrypted_credentials: AES-256-GCM encrypted JSON blob (base64).
        metadata_json: Non-secret metadata (account number, store domain, scopes).
        last_validated_at: ISO8601 timestamp of last successful validation.
        error_message: Last error message for diagnostics.
    """

    __tablename__ = "provider_connections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    environment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="disconnected"
    )
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_validated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso, onupdate=utc_now_iso
    )

    __table_args__ = (
        UniqueConstraint("provider", "environment", name="uq_provider_environment"),
        Index("idx_provider_connections_provider", "provider"),
    )

    def __repr__(self) -> str:
        return f"<ProviderConnection(provider={self.provider!r}, env={self.environment!r}, status={self.status!r})>"
```

**Step 4: Add migration to `src/db/connection.py`**

Add to the end of `_ensure_columns_exist()` function:

```python
    # provider_connections table migration (idempotent CREATE TABLE IF NOT EXISTS)
    for ddl in [
        """
        CREATE TABLE IF NOT EXISTS provider_connections (
            id VARCHAR(36) PRIMARY KEY,
            provider VARCHAR(20) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            auth_mode VARCHAR(50) NOT NULL,
            environment VARCHAR(20),
            status VARCHAR(20) NOT NULL DEFAULT 'disconnected',
            encrypted_credentials TEXT NOT NULL,
            metadata_json TEXT,
            last_validated_at VARCHAR(50),
            error_message TEXT,
            created_at VARCHAR(50) NOT NULL,
            updated_at VARCHAR(50) NOT NULL,
            UNIQUE(provider, environment)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_provider_connections_provider ON provider_connections (provider)",
    ]:
        try:
            conn.execute(text(ddl))
        except OperationalError as e:
            log.warning("provider_connections migration step failed: %s", e)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/db/test_provider_connection_model.py -v`
Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add src/db/models.py src/db/connection.py tests/db/test_provider_connection_model.py
git commit -m "feat: add ProviderConnection model with encrypted credentials"
```

---

### Task 3: ConnectionService Backend

**Files:**
- Create: `src/services/connection_service.py`
- Create: `tests/services/test_connection_service.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_connection_service.py
"""Tests for ConnectionService — provider connection lifecycle."""

import json
import os

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
    """Temporary key directory."""
    return str(tmp_path)


@pytest.fixture
def service(db_session, key_dir):
    """ConnectionService instance with test DB and key."""
    from src.services.connection_service import ConnectionService
    return ConnectionService(db=db_session, key_dir=key_dir)


class TestConnectionServiceCRUD:
    """Tests for basic CRUD operations."""

    def test_save_and_get_ups_connection(self, service):
        """Save UPS credentials and retrieve them."""
        result = service.save_connection(
            provider="ups",
            auth_mode="client_credentials",
            credentials={"client_id": "test_id", "client_secret": "test_secret"},
            metadata={"account_number": "123456", "environment": "test"},
            environment="test",
            display_name="UPS (Test)",
        )
        assert result["provider"] == "ups"
        assert result["status"] == "disconnected"

        conn = service.get_connection("ups", environment="test")
        assert conn is not None
        assert conn["provider"] == "ups"
        assert conn["display_name"] == "UPS (Test)"
        # Credentials must NOT be in the response
        assert "credentials" not in conn

    def test_save_shopify_legacy_token(self, service):
        """Save Shopify legacy token connection."""
        result = service.save_connection(
            provider="shopify",
            auth_mode="legacy_token",
            credentials={"access_token": "shpat_test123"},
            metadata={"store_domain": "mystore.myshopify.com"},
            display_name="My Store",
        )
        assert result["provider"] == "shopify"

    def test_list_connections(self, service):
        """List returns all saved connections without credentials."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id1", "client_secret": "sec1"},
            metadata={}, environment="test", display_name="UPS Test",
        )
        service.save_connection(
            provider="shopify", auth_mode="legacy_token",
            credentials={"access_token": "tok1"},
            metadata={"store_domain": "store.myshopify.com"},
            display_name="Shopify",
        )
        connections = service.list_connections()
        assert len(connections) == 2
        providers = {c["provider"] for c in connections}
        assert providers == {"ups", "shopify"}

    def test_delete_connection(self, service):
        """Delete removes connection from DB."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "x", "client_secret": "y"},
            metadata={}, environment="test", display_name="UPS",
        )
        deleted = service.delete_connection("ups", environment="test")
        assert deleted is True
        assert service.get_connection("ups", environment="test") is None

    def test_delete_nonexistent_returns_false(self, service):
        """Delete returns False for non-existent connection."""
        assert service.delete_connection("ups", environment="test") is False

    def test_save_overwrites_existing(self, service):
        """Saving same provider+env overwrites credentials."""
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
        conn = service.get_connection("ups", environment="test")
        assert conn["display_name"] == "UPS New"

    def test_get_decrypted_credentials(self, service):
        """Internal method returns decrypted credentials for connecting."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "my_id", "client_secret": "my_secret"},
            metadata={"account_number": "999"}, environment="test",
            display_name="UPS",
        )
        creds = service.get_decrypted_credentials("ups", environment="test")
        assert creds == {"client_id": "my_id", "client_secret": "my_secret"}

    def test_update_status(self, service):
        """Can update connection status and error message."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "x", "client_secret": "y"},
            metadata={}, environment="test", display_name="UPS",
        )
        service.update_status("ups", "connected", environment="test")
        conn = service.get_connection("ups", environment="test")
        assert conn["status"] == "connected"

        service.update_status("ups", "error", environment="test", error_message="Auth failed")
        conn = service.get_connection("ups", environment="test")
        assert conn["status"] == "error"
        assert conn["error_message"] == "Auth failed"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/services/connection_service.py
"""Service for managing persistent provider connections.

Handles encrypted credential CRUD, validation, and auto-reconnect.
Sits above MCP clients — does not replace them.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.db.models import ProviderConnection
from src.services.credential_encryption import (
    decrypt_credentials,
    encrypt_credentials,
    get_or_create_key,
)

logger = logging.getLogger(__name__)


class ConnectionService:
    """Manages provider connection lifecycle with encrypted persistence.

    Args:
        db: SQLAlchemy session.
        key_dir: Directory containing the encryption key file.
    """

    def __init__(self, db: Session, key_dir: str | None = None):
        self._db = db
        self._key = get_or_create_key(key_dir=key_dir)

    def list_connections(self) -> list[dict]:
        """List all saved connections without credentials."""
        rows = self._db.query(ProviderConnection).all()
        return [self._to_response(row) for row in rows]

    def get_connection(
        self, provider: str, environment: str | None = None
    ) -> dict | None:
        """Get a single connection by provider and optional environment."""
        row = self._find(provider, environment)
        if row is None:
            return None
        return self._to_response(row)

    def save_connection(
        self,
        provider: str,
        auth_mode: str,
        credentials: dict,
        metadata: dict,
        display_name: str,
        environment: str | None = None,
    ) -> dict:
        """Encrypt and persist a provider connection.

        Overwrites existing connection for the same provider+environment.

        Args:
            provider: Provider identifier ('ups' or 'shopify').
            auth_mode: Authentication mode string.
            credentials: Secret credentials to encrypt.
            metadata: Non-secret metadata dict.
            display_name: Human-readable connection label.
            environment: UPS environment (nullable for Shopify).

        Returns:
            Connection response dict (no credentials).
        """
        encrypted = encrypt_credentials(credentials, self._key)
        now = datetime.now(UTC).isoformat()

        existing = self._find(provider, environment)
        if existing:
            existing.display_name = display_name
            existing.auth_mode = auth_mode
            existing.encrypted_credentials = encrypted
            existing.metadata_json = json.dumps(metadata) if metadata else None
            existing.updated_at = now
            self._db.commit()
            return self._to_response(existing)

        row = ProviderConnection(
            provider=provider,
            display_name=display_name,
            auth_mode=auth_mode,
            environment=environment,
            status="disconnected",
            encrypted_credentials=encrypted,
            metadata_json=json.dumps(metadata) if metadata else None,
            created_at=now,
            updated_at=now,
        )
        self._db.add(row)
        self._db.commit()
        return self._to_response(row)

    def delete_connection(
        self, provider: str, environment: str | None = None
    ) -> bool:
        """Delete a connection and wipe its encrypted credentials."""
        row = self._find(provider, environment)
        if row is None:
            return False
        self._db.delete(row)
        self._db.commit()
        return True

    def get_decrypted_credentials(
        self, provider: str, environment: str | None = None
    ) -> dict | None:
        """Decrypt and return credentials for internal use.

        Not exposed via API — used by auto-reconnect and validation.
        """
        row = self._find(provider, environment)
        if row is None:
            return None
        return decrypt_credentials(row.encrypted_credentials, self._key)

    def update_status(
        self,
        provider: str,
        status: str,
        environment: str | None = None,
        error_message: str | None = None,
        last_validated_at: str | None = None,
    ) -> None:
        """Update connection status and optional error/validation fields."""
        row = self._find(provider, environment)
        if row is None:
            return
        row.status = status
        row.error_message = error_message
        row.updated_at = datetime.now(UTC).isoformat()
        if last_validated_at:
            row.last_validated_at = last_validated_at
        elif status == "connected":
            row.last_validated_at = datetime.now(UTC).isoformat()
        self._db.commit()

    def _find(
        self, provider: str, environment: str | None = None
    ) -> ProviderConnection | None:
        """Find a connection row by provider and environment."""
        query = self._db.query(ProviderConnection).filter_by(provider=provider)
        if environment is not None:
            query = query.filter_by(environment=environment)
        else:
            query = query.filter(ProviderConnection.environment.is_(None))
        return query.first()

    def _to_response(self, row: ProviderConnection) -> dict:
        """Convert a DB row to a response dict (no credentials)."""
        metadata = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "id": row.id,
            "provider": row.provider,
            "display_name": row.display_name,
            "auth_mode": row.auth_mode,
            "environment": row.environment,
            "status": row.status,
            "metadata": metadata,
            "last_validated_at": row.last_validated_at,
            "error_message": row.error_message,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add src/services/connection_service.py tests/services/test_connection_service.py
git commit -m "feat: add ConnectionService for encrypted provider credential CRUD"
```

---

### Task 4: Connections API Routes

**Files:**
- Create: `src/api/routes/connections.py`
- Modify: `src/api/main.py` (register router)
- Create: `tests/api/test_connections.py`

**Step 1: Write the failing tests**

```python
# tests/api/test_connections.py
"""Tests for /api/v1/connections routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


@pytest.fixture
def test_app(tmp_path):
    """Create a test FastAPI app with in-memory DB."""
    import os
    os.environ["SHIPAGENT_SKIP_SDK_CHECK"] = "true"
    os.environ["FILTER_TOKEN_SECRET"] = "a" * 32

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    from src.api.routes.connections import router, get_connection_service
    from src.services.connection_service import ConnectionService
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_service():
        db = TestSession()
        try:
            yield ConnectionService(db=db, key_dir=str(tmp_path))
        finally:
            db.close()

    app.dependency_overrides[get_connection_service] = override_service
    return TestClient(app)


class TestConnectionsAPI:
    """Tests for connection endpoints."""

    def test_list_empty(self, test_app):
        """GET /connections/ returns empty list initially."""
        resp = test_app.get("/api/v1/connections/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connections"] == []
        assert data["count"] == 0

    def test_save_ups_connection(self, test_app):
        """POST /connections/ups/connect saves and returns status."""
        resp = test_app.post("/api/v1/connections/ups/connect", json={
            "auth_mode": "client_credentials",
            "credentials": {"client_id": "test", "client_secret": "secret"},
            "metadata": {"account_number": "123", "environment": "test"},
            "display_name": "UPS Test",
            "environment": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["provider"] == "ups"

    def test_save_shopify_connection(self, test_app):
        """POST /connections/shopify/connect saves Shopify credentials."""
        resp = test_app.post("/api/v1/connections/shopify/connect", json={
            "auth_mode": "legacy_token",
            "credentials": {"access_token": "shpat_test"},
            "metadata": {"store_domain": "store.myshopify.com"},
            "display_name": "My Store",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_get_connection(self, test_app):
        """GET /connections/ups returns saved connection without secrets."""
        test_app.post("/api/v1/connections/ups/connect", json={
            "auth_mode": "client_credentials",
            "credentials": {"client_id": "id", "client_secret": "sec"},
            "metadata": {"environment": "test"},
            "display_name": "UPS",
            "environment": "test",
        })
        resp = test_app.get("/api/v1/connections/ups?environment=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "ups"
        assert "credentials" not in data
        assert "encrypted_credentials" not in data

    def test_delete_connection(self, test_app):
        """DELETE /connections/ups removes credentials."""
        test_app.post("/api/v1/connections/ups/connect", json={
            "auth_mode": "client_credentials",
            "credentials": {"client_id": "x", "client_secret": "y"},
            "metadata": {}, "display_name": "UPS", "environment": "test",
        })
        resp = test_app.delete("/api/v1/connections/ups?environment=test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = test_app.get("/api/v1/connections/ups?environment=test")
        assert resp.status_code == 404

    def test_no_credentials_in_list(self, test_app):
        """GET /connections/ never exposes credential data."""
        test_app.post("/api/v1/connections/ups/connect", json={
            "auth_mode": "client_credentials",
            "credentials": {"client_id": "secret_id", "client_secret": "secret_key"},
            "metadata": {}, "display_name": "UPS", "environment": "test",
        })
        resp = test_app.get("/api/v1/connections/")
        data = resp.json()
        for conn in data["connections"]:
            assert "credentials" not in conn
            assert "encrypted_credentials" not in conn
            assert "client_id" not in str(conn)
            assert "client_secret" not in str(conn)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_connections.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the routes**

```python
# src/api/routes/connections.py
"""FastAPI routes for provider connection management.

Provides REST endpoints for saving, listing, testing, and deleting
encrypted provider connections (UPS, Shopify).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.connection import get_db
from src.services.connection_service import ConnectionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


# --- Dependency ---

def get_connection_service(db: Session = Depends(get_db)) -> ConnectionService:
    """Provide a ConnectionService instance for route handlers."""
    return ConnectionService(db=db)


# --- Request/Response Schemas ---

class ConnectProviderRequest(BaseModel):
    """Request body for saving a provider connection."""

    auth_mode: str = Field(..., description="Authentication mode")
    credentials: dict[str, Any] = Field(..., description="Secret credentials to encrypt")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Non-secret metadata")
    display_name: str = Field(..., description="Human-readable connection label")
    environment: str | None = Field(None, description="Environment (test/production, UPS only)")


class ConnectProviderResponse(BaseModel):
    """Response from provider connection save."""

    success: bool
    provider: str
    status: str
    display_name: str
    error: str | None = None


class ConnectionResponse(BaseModel):
    """Single connection details (no credentials)."""

    id: str
    provider: str
    display_name: str
    auth_mode: str
    environment: str | None
    status: str
    metadata: dict[str, Any]
    last_validated_at: str | None
    error_message: str | None
    created_at: str
    updated_at: str


class ListConnectionsResponse(BaseModel):
    """Response listing all provider connections."""

    connections: list[ConnectionResponse]
    count: int


# --- Routes ---

@router.get("/", response_model=ListConnectionsResponse)
def list_connections(
    service: ConnectionService = Depends(get_connection_service),
) -> ListConnectionsResponse:
    """List all saved provider connections (no credentials exposed)."""
    connections = service.list_connections()
    return ListConnectionsResponse(
        connections=[ConnectionResponse(**c) for c in connections],
        count=len(connections),
    )


@router.get("/{provider}", response_model=ConnectionResponse)
def get_connection(
    provider: str,
    environment: str | None = None,
    service: ConnectionService = Depends(get_connection_service),
):
    """Get a single provider connection by provider and optional environment."""
    conn = service.get_connection(provider, environment=environment)
    if conn is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No connection found for {provider}")
    return ConnectionResponse(**conn)


@router.post("/{provider}/connect", response_model=ConnectProviderResponse)
def connect_provider(
    provider: str,
    request: ConnectProviderRequest,
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectProviderResponse:
    """Save and connect a provider (encrypt + persist)."""
    try:
        result = service.save_connection(
            provider=provider,
            auth_mode=request.auth_mode,
            credentials=request.credentials,
            metadata=request.metadata,
            display_name=request.display_name,
            environment=request.environment,
        )
        return ConnectProviderResponse(
            success=True,
            provider=provider,
            status=result["status"],
            display_name=result["display_name"],
        )
    except Exception as e:
        logger.exception("Failed to save connection for %s", provider)
        return ConnectProviderResponse(
            success=False,
            provider=provider,
            status="error",
            display_name=request.display_name,
            error=str(e),
        )


@router.post("/{provider}/disconnect")
def disconnect_provider(
    provider: str,
    environment: str | None = None,
    service: ConnectionService = Depends(get_connection_service),
) -> dict:
    """Disconnect a provider but keep saved credentials."""
    service.update_status(provider, "disconnected", environment=environment)
    return {"success": True, "provider": provider, "status": "disconnected"}


@router.delete("/{provider}")
def delete_connection(
    provider: str,
    environment: str | None = None,
    service: ConnectionService = Depends(get_connection_service),
) -> dict:
    """Delete a provider connection and wipe encrypted credentials."""
    deleted = service.delete_connection(provider, environment=environment)
    return {"success": deleted, "provider": provider}
```

**Step 4: Register the router in `src/api/main.py`**

Add import at line 50 (with the other route imports):

```python
from src.api.routes import (
    ...existing imports...,
    connections,
)
```

Add router registration after line 566 (after the commands router):

```python
app.include_router(connections.router, prefix="/api/v1")
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/api/test_connections.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add src/api/routes/connections.py src/api/main.py tests/api/test_connections.py
git commit -m "feat: add /connections API routes for provider credential management"
```

---

### Task 5: Auto-Reconnect on Startup + UPS Config Integration

**Files:**
- Modify: `src/services/connection_service.py` (add `auto_reconnect_all`)
- Modify: `src/api/main.py` (call on startup)
- Modify: `src/orchestrator/agent/config.py` (read from ConnectionService first)
- Create: `tests/services/test_auto_reconnect.py`

**Step 1: Write the failing test**

```python
# tests/services/test_auto_reconnect.py
"""Tests for auto-reconnect on startup."""

import json
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


class TestAutoReconnect:
    """Tests for startup auto-reconnect logic."""

    def test_auto_reconnect_sets_ups_env_vars(self, db_session, key_dir):
        """Auto-reconnect writes UPS credentials to os.environ."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        service.save_connection(
            provider="ups",
            auth_mode="client_credentials",
            credentials={"client_id": "env_test_id", "client_secret": "env_test_secret"},
            metadata={"account_number": "ACC123", "environment": "test"},
            environment="test",
            display_name="UPS Test",
        )

        # Clear env vars to prove auto_reconnect sets them
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ACCOUNT_NUMBER"):
            os.environ.pop(var, None)

        results = service.auto_reconnect_all()
        assert "ups" in results

        assert os.environ.get("UPS_CLIENT_ID") == "env_test_id"
        assert os.environ.get("UPS_CLIENT_SECRET") == "env_test_secret"
        assert os.environ.get("UPS_ACCOUNT_NUMBER") == "ACC123"

        # Cleanup
        for var in ("UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "UPS_ACCOUNT_NUMBER"):
            os.environ.pop(var, None)

    def test_auto_reconnect_empty_db(self, db_session, key_dir):
        """Auto-reconnect with no saved connections returns empty dict."""
        from src.services.connection_service import ConnectionService

        service = ConnectionService(db=db_session, key_dir=key_dir)
        results = service.auto_reconnect_all()
        assert results == {}

    def test_auto_reconnect_corrupt_credentials(self, db_session, key_dir):
        """Auto-reconnect handles decryption failure gracefully."""
        from src.db.models import ProviderConnection
        from src.services.connection_service import ConnectionService

        # Insert a row with corrupted encrypted data
        row = ProviderConnection(
            provider="ups", display_name="Bad", auth_mode="client_credentials",
            environment="test", status="connected",
            encrypted_credentials="not_valid_base64_or_ciphertext",
        )
        db_session.add(row)
        db_session.commit()

        service = ConnectionService(db=db_session, key_dir=key_dir)
        results = service.auto_reconnect_all()
        assert results.get("ups") == "error"

        # Row should be marked needs_reconnect
        conn = service.get_connection("ups", environment="test")
        assert conn["status"] == "needs_reconnect"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_auto_reconnect.py -v`
Expected: FAIL — `AttributeError: 'ConnectionService' object has no attribute 'auto_reconnect_all'`

**Step 3: Add `auto_reconnect_all` to ConnectionService**

Add this method to `src/services/connection_service.py`:

```python
    def auto_reconnect_all(self) -> dict[str, str]:
        """Reconnect all saved providers on startup.

        For UPS: writes decrypted credentials to os.environ so existing
        MCP config paths work unchanged.
        For Shopify: returns metadata for the caller to trigger connect_platform.

        Returns:
            Dict mapping provider keys to status strings.
        """
        import os

        rows = self._db.query(ProviderConnection).all()
        results: dict[str, str] = {}

        for row in rows:
            key = f"{row.provider}:{row.environment}" if row.environment else row.provider
            try:
                creds = decrypt_credentials(row.encrypted_credentials, self._key)
                metadata = {}
                if row.metadata_json:
                    metadata = json.loads(row.metadata_json)

                if row.provider == "ups":
                    os.environ["UPS_CLIENT_ID"] = creds.get("client_id", "")
                    os.environ["UPS_CLIENT_SECRET"] = creds.get("client_secret", "")
                    account = metadata.get("account_number", "")
                    if account:
                        os.environ["UPS_ACCOUNT_NUMBER"] = account
                    env = metadata.get("environment", row.environment or "test")
                    base_url = (
                        "https://wwwcie.ups.com" if env == "test"
                        else "https://onlinetools.ups.com"
                    )
                    os.environ["UPS_BASE_URL"] = base_url
                    row.status = "connected"
                    row.last_validated_at = datetime.now(UTC).isoformat()
                    results[key] = "connected"

                elif row.provider == "shopify":
                    # Store in env for existing env-status fallback
                    if row.auth_mode == "legacy_token":
                        token = creds.get("access_token", "")
                        if token:
                            os.environ["SHOPIFY_ACCESS_TOKEN"] = token
                    domain = metadata.get("store_domain", "")
                    if domain:
                        os.environ["SHOPIFY_STORE_DOMAIN"] = domain
                    row.status = "connected"
                    row.last_validated_at = datetime.now(UTC).isoformat()
                    results[key] = "connected"

                else:
                    results[key] = "skipped"

                row.updated_at = datetime.now(UTC).isoformat()

            except Exception as e:
                logger.warning(
                    "Auto-reconnect failed for %s (%s): %s",
                    row.provider, row.environment, e,
                )
                row.status = "needs_reconnect"
                row.error_message = str(e)
                row.updated_at = datetime.now(UTC).isoformat()
                results[key] = "error"

        self._db.commit()
        return results
```

**Step 4: Add startup call in `src/api/main.py`**

Add to the `lifespan` function, after `init_db()` call (around line 443):

```python
    # Auto-reconnect saved provider connections
    try:
        with get_db_context() as db:
            from src.services.connection_service import ConnectionService
            conn_service = ConnectionService(db=db)
            reconnect_results = conn_service.auto_reconnect_all()
            if reconnect_results:
                logger.info("Provider auto-reconnect results: %s", reconnect_results)
    except Exception as e:
        logger.warning("Provider auto-reconnect failed (non-blocking): %s", e)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/services/test_auto_reconnect.py -v`
Expected: All 3 tests PASS

**Step 6: Commit**

```bash
git add src/services/connection_service.py src/api/main.py tests/services/test_auto_reconnect.py
git commit -m "feat: add auto-reconnect on startup for saved provider connections"
```

---

### Task 6: Add `.shipagent_key` to `.gitignore` and add `cryptography` dependency

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml` or `requirements.txt`

**Step 1: Add to .gitignore**

Add this line to `.gitignore`:

```
# Encryption key for provider credentials
.shipagent_key
```

**Step 2: Add cryptography dependency**

Check which dependency file is used (`pyproject.toml` or `requirements.txt`) and add `cryptography>=42.0.0`.

**Step 3: Install dependency**

Run: `pip install cryptography>=42.0.0`

**Step 4: Verify all backend tests pass**

Run: `pytest tests/services/test_credential_encryption.py tests/services/test_connection_service.py tests/services/test_auto_reconnect.py tests/api/test_connections.py tests/db/test_provider_connection_model.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add .gitignore pyproject.toml  # or requirements.txt
git commit -m "chore: add cryptography dependency and gitignore encryption key"
```

---

### Task 7: Frontend Types and API Client

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add TypeScript types to `frontend/src/types/api.ts`**

Add at the end of the file:

```typescript
// === Provider Connection Types ===

/** Provider identifiers for connection management. */
export type ProviderType = 'ups' | 'shopify';

/** Connection status for provider connections. */
export type ProviderConnectionStatus = 'connected' | 'disconnected' | 'error' | 'needs_reconnect';

/** Auth modes for provider connections. */
export type ProviderAuthMode = 'client_credentials' | 'legacy_token' | 'client_credentials_shopify';

/** Saved provider connection (no credentials). */
export interface ProviderConnectionInfo {
  id: string;
  provider: ProviderType;
  display_name: string;
  auth_mode: ProviderAuthMode;
  environment: string | null;
  status: ProviderConnectionStatus;
  metadata: Record<string, string>;
  last_validated_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/** Request to save a provider connection. */
export interface ConnectProviderRequest {
  auth_mode: string;
  credentials: Record<string, string>;
  metadata: Record<string, string>;
  display_name: string;
  environment?: string;
}

/** Response from saving a provider connection. */
export interface ConnectProviderResult {
  success: boolean;
  provider: string;
  status: string;
  display_name: string;
  error?: string;
}

/** Response from listing provider connections. */
export interface ProviderConnectionListResponse {
  connections: ProviderConnectionInfo[];
  count: number;
}
```

**Step 2: Add API functions to `frontend/src/lib/api.ts`**

Add before the closing of the file:

```typescript
// === Provider Connections API ===

import type {
  ProviderConnectionInfo,
  ProviderConnectionListResponse,
  ConnectProviderRequest,
  ConnectProviderResult,
} from '@/types/api';

/**
 * List all saved provider connections (no credentials exposed).
 */
export async function listProviderConnections(): Promise<ProviderConnectionListResponse> {
  const response = await fetch(`${API_BASE}/connections/`);
  return parseResponse<ProviderConnectionListResponse>(response);
}

/**
 * Get a single provider connection.
 */
export async function getProviderConnection(
  provider: string,
  environment?: string,
): Promise<ProviderConnectionInfo> {
  const params = environment ? `?environment=${environment}` : '';
  const response = await fetch(`${API_BASE}/connections/${provider}${params}`);
  return parseResponse<ProviderConnectionInfo>(response);
}

/**
 * Save and connect a provider (encrypt + persist).
 */
export async function connectProviderCredentials(
  provider: string,
  request: ConnectProviderRequest,
): Promise<ConnectProviderResult> {
  const response = await fetch(`${API_BASE}/connections/${provider}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  return parseResponse<ConnectProviderResult>(response);
}

/**
 * Disconnect a provider (keep saved credentials).
 */
export async function disconnectProviderCredentials(
  provider: string,
  environment?: string,
): Promise<{ success: boolean }> {
  const params = environment ? `?environment=${environment}` : '';
  const response = await fetch(`${API_BASE}/connections/${provider}/disconnect${params}`, {
    method: 'POST',
  });
  return parseResponse<{ success: boolean }>(response);
}

/**
 * Delete a provider connection and wipe encrypted credentials.
 */
export async function deleteProviderConnection(
  provider: string,
  environment?: string,
): Promise<{ success: boolean }> {
  const params = environment ? `?environment=${environment}` : '';
  const response = await fetch(`${API_BASE}/connections/${provider}${params}`, {
    method: 'DELETE',
  });
  return parseResponse<{ success: boolean }>(response);
}
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat: add frontend types and API client for provider connections"
```

---

### Task 8: Frontend State Management (useAppState)

**Files:**
- Modify: `frontend/src/hooks/useAppState.tsx`

**Step 1: Add connections state to useAppState**

Add to the context interface:

```typescript
providerConnections: ProviderConnectionInfo[];
providerConnectionsLoading: boolean;
refreshProviderConnections: () => void;
```

Add state and effect inside the provider:

```typescript
const [providerConnections, setProviderConnections] = React.useState<ProviderConnectionInfo[]>([]);
const [providerConnectionsLoading, setProviderConnectionsLoading] = React.useState(false);
const [providerConnectionsVersion, setProviderConnectionsVersion] = React.useState(0);

const refreshProviderConnections = React.useCallback(() => {
  setProviderConnectionsVersion(v => v + 1);
}, []);

React.useEffect(() => {
  let cancelled = false;
  setProviderConnectionsLoading(true);
  api.listProviderConnections()
    .then(data => {
      if (!cancelled) {
        setProviderConnections(data.connections);
      }
    })
    .catch(() => {
      if (!cancelled) setProviderConnections([]);
    })
    .finally(() => {
      if (!cancelled) setProviderConnectionsLoading(false);
    });
  return () => { cancelled = true; };
}, [providerConnectionsVersion]);
```

Add to the context value object.

Import `ProviderConnectionInfo` from `@/types/api`.

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useAppState.tsx
git commit -m "feat: add provider connections state to useAppState"
```

---

### Task 9: ConnectionsSection + ProviderCard Components

**Files:**
- Create: `frontend/src/components/settings/ConnectionsSection.tsx`
- Create: `frontend/src/components/settings/ProviderCard.tsx`
- Modify: `frontend/src/components/settings/SettingsFlyout.tsx`

**Step 1: Create ProviderCard component**

Build a reusable card that renders provider status, action buttons (Test, Disconnect, Remove), and an expandable form slot. Follows the design system in `index.css` — uses `card-premium` patterns, OKLCH domain colors, `cn()` utility from `@/lib/utils`.

Status badges: green for connected, grey for disconnected, amber for error/needs_reconnect. Action buttons use `btn-secondary` pattern. The card accepts `children` for the provider-specific form.

**Step 2: Create ConnectionsSection accordion**

Same pattern as `ShipmentBehaviourSection` — accordion header with icon, title "Connections", and a `{connected}/{total}` count badge. Maps over `providerConnections` from `useAppState` and renders a `ProviderCard` for each configured provider, plus cards for unconfigured providers.

**Step 3: Add to SettingsFlyout**

Insert `<ConnectionsSection>` as the first accordion section, above `ShipmentBehaviourSection`. Default open state to `'connections'` instead of `'shipment'`.

**Step 4: Verify it renders**

Run: `cd frontend && npm run dev`
Open Settings flyout — Connections section should appear with empty UPS and Shopify cards.

**Step 5: Commit**

```bash
git add frontend/src/components/settings/ConnectionsSection.tsx frontend/src/components/settings/ProviderCard.tsx frontend/src/components/settings/SettingsFlyout.tsx
git commit -m "feat: add ConnectionsSection and ProviderCard to Settings flyout"
```

---

### Task 10: UPSConnectForm Component

**Files:**
- Create: `frontend/src/components/settings/UPSConnectForm.tsx`

**Step 1: Build the UPS credential form**

Fields: Client ID (text, masked after save), Client Secret (password), Account Number (text, optional), Environment (toggle: Test/Production, default Test).

Form validation: Client ID and Client Secret required, non-empty. On submit: calls `connectProviderCredentials('ups', ...)`, shows inline loading state, calls `refreshProviderConnections()` on success, shows inline error on failure.

Use `cn()` for conditional classes. Follow existing form patterns from `AddressBookSection` or `CustomCommandsSection` for input styling.

**Step 2: Wire into ConnectionsSection**

Pass `<UPSConnectForm>` as children to the UPS `ProviderCard`.

**Step 3: Verify end-to-end**

Run backend + frontend. Open Settings → Connections → expand UPS → enter test credentials → submit → verify card shows "Connected" badge.

**Step 4: Commit**

```bash
git add frontend/src/components/settings/UPSConnectForm.tsx frontend/src/components/settings/ConnectionsSection.tsx
git commit -m "feat: add UPS credential form to Settings flyout"
```

---

### Task 11: ShopifyConnectForm Component

**Files:**
- Create: `frontend/src/components/settings/ShopifyConnectForm.tsx`

**Step 1: Build the Shopify form with auth mode selector**

Radio selector at top: "I have an access token" (legacy) vs "I have client credentials" (new). Switches between:
- Legacy: Store domain + Access Token fields
- Client credentials: Store domain + Client ID + Client Secret fields

Store domain validated against `*.myshopify.com` pattern on blur.

On submit: calls `connectProviderCredentials('shopify', ...)` with appropriate auth_mode.

**Step 2: Wire into ConnectionsSection**

Pass `<ShopifyConnectForm>` as children to the Shopify `ProviderCard`.

**Step 3: Verify end-to-end**

Run backend + frontend. Open Settings → Connections → expand Shopify → select auth mode → enter credentials → submit.

**Step 4: Commit**

```bash
git add frontend/src/components/settings/ShopifyConnectForm.tsx frontend/src/components/settings/ConnectionsSection.tsx
git commit -m "feat: add Shopify connect form with auth mode selector"
```

---

### Task 12: DataSourcePanel Migration

**Files:**
- Modify: `frontend/src/components/sidebar/DataSourcePanel.tsx`

**Step 1: Replace Shopify token form**

Remove the inline Shopify token entry form. Replace with:
- If Shopify is connected (check `providerConnections` from `useAppState`): show "Shopify" as available data source with switch button (existing behavior)
- If Shopify is NOT connected: show a subtle "Connect Shopify in Settings" link that calls `setSettingsFlyoutOpen(true)`

**Step 2: Keep existing local source logic unchanged**

CSV/Excel import, saved sources, and source switching all remain as-is.

**Step 3: Verify both paths**

- With Shopify connected: data source panel shows Shopify switch button
- Without Shopify connected: shows "Connect in Settings" link, clicking opens flyout

**Step 4: Commit**

```bash
git add frontend/src/components/sidebar/DataSourcePanel.tsx
git commit -m "refactor: move Shopify credentials from DataSourcePanel to Settings"
```

---

### Task 13: Integration Test — Full Round Trip

**Files:**
- Create: `tests/integration/test_connection_round_trip.py`

**Step 1: Write integration test**

```python
# tests/integration/test_connection_round_trip.py
"""Integration test: save → list → get → delete round trip."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.services.connection_service import ConnectionService


@pytest.fixture
def service(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield ConnectionService(db=db, key_dir=str(tmp_path))
    db.close()


def test_full_ups_lifecycle(service):
    """UPS: save → list → get_decrypted → update_status → delete."""
    # Save
    service.save_connection(
        provider="ups", auth_mode="client_credentials",
        credentials={"client_id": "real_id", "client_secret": "real_secret"},
        metadata={"account_number": "ACC", "environment": "test"},
        environment="test", display_name="UPS Test",
    )

    # List
    connections = service.list_connections()
    assert len(connections) == 1
    assert connections[0]["provider"] == "ups"

    # Decrypt
    creds = service.get_decrypted_credentials("ups", environment="test")
    assert creds["client_id"] == "real_id"
    assert creds["client_secret"] == "real_secret"

    # Update status
    service.update_status("ups", "connected", environment="test")
    conn = service.get_connection("ups", environment="test")
    assert conn["status"] == "connected"
    assert conn["last_validated_at"] is not None

    # Delete
    assert service.delete_connection("ups", environment="test") is True
    assert service.list_connections() == []


def test_full_shopify_lifecycle(service):
    """Shopify: save legacy token → list → decrypt → delete."""
    service.save_connection(
        provider="shopify", auth_mode="legacy_token",
        credentials={"access_token": "shpat_abc123"},
        metadata={"store_domain": "test.myshopify.com", "api_version": "2024-10"},
        display_name="Test Store",
    )

    connections = service.list_connections()
    assert len(connections) == 1
    assert connections[0]["auth_mode"] == "legacy_token"

    creds = service.get_decrypted_credentials("shopify")
    assert creds["access_token"] == "shpat_abc123"

    assert service.delete_connection("shopify") is True
```

**Step 2: Run all tests**

Run: `pytest tests/services/test_credential_encryption.py tests/services/test_connection_service.py tests/services/test_auto_reconnect.py tests/api/test_connections.py tests/db/test_provider_connection_model.py tests/integration/test_connection_round_trip.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_connection_round_trip.py
git commit -m "test: add integration test for provider connection lifecycle"
```

---

### Task 14: Final Verification + TypeScript Check

**Step 1: Run full backend test suite (excluding known hangs)**

Run: `pytest -k "not stream and not sse and not progress and not test_stream_endpoint_exists" -v --tb=short`
Expected: All existing tests still pass, new tests pass

**Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Run frontend dev server and verify UI**

Run: `cd frontend && npm run dev`
Verify: Settings flyout → Connections section renders with UPS and Shopify cards

**Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final verification and cleanup for settings connections"
```
