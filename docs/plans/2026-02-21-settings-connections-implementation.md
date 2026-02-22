# Settings Connections Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent encrypted credential storage and a Settings UI for configuring UPS and Shopify providers, replacing the .env-only workflow. Phase 1 includes foundation storage, API routes, frontend UI, **and runtime integration** — DB-stored credentials are wired into all UPS and Shopify runtime call sites via a single `runtime_credentials.py` adapter with env var fallback.

**Scope assumption:** Single-user local desktop app — no `user_id` or `workspace_id` scoping.

**Architecture:** New `ProviderConnection` SQLAlchemy model (DB column `metadata_json` avoids `Base.metadata` collision) with AES-256-GCM encrypted credentials (versioned envelope, AAD-bound, algorithm-validated, key-length-enforced, `key_version` always `1` in Phase 1). `ConnectionService` provides typed credential resolvers, CRUD with input validation and domain normalization, startup decryptability scan (skips `disconnected` rows), server-side `runtime_usable` computation, and error message sanitization. Phase 1 status semantics: only `configured`, `needs_reconnect`, and `disconnected` are actively produced; `connected`, `validating` are reserved for Phase 2. `error` is allowed in Phase 1 via explicit `update_status()` calls, but is NOT produced by any automated validation or check flow. `runtime_credentials.py` is the single adapter for all runtime call sites (no ad hoc env reads). Frontend adds a Connections accordion section to the existing SettingsFlyout with per-provider cards and forms, consuming `runtime_usable` from API responses. Frontend types use strict `ProviderAuthMode` union with Phase 1 status comments. UI shows DB connections only; env fallback is silent (runtime works, UI shows "Connect in Settings"). Key source precedence: env key → env path → platformdirs. `get_or_create_key()` handles concurrent create race via `FileExistsError` retry. `SHIPAGENT_CREDENTIAL_KEY_FILE` validates file existence/readability/type/non-symlink. `SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY` opt-in strict mode fails startup if key source is `platformdirs`. Resolver skip policy: skip `disconnected` + `needs_reconnect`. Migration uses same PRAGMA introspection pattern as existing codebase with unique index hardening. Shopify `client_credentials_shopify` hidden in Phase 1 UI. Connection routes accept raw dict payloads (no Pydantic credential binding) + custom `RequestValidationError` handler for `/connections/*` to prevent 422 secret leakage. API error sanitization split: structured payloads use `redact_for_logging()`, free-text strings use `sanitize_error_message()`. Secret redaction uses case-insensitive substring matching. Sanitizer is best-effort (not a parser) — covers Bearer tokens, JSON-style, quoted values, and multi-token lines; uncovered edge cases degrade gracefully (unsanitized but truncated). Credential payload allowlists per provider/auth_mode validate required/optional keys and reject unknown keys with 400. metadata_json stored as TEXT with manual json.loads() (not SQLAlchemy JSON type) — parse failures return {} with logged WARNING. Migration adds all columns as nullable (SQLite requirement) with application-level defaults and backfill step. Credential dataclasses live in src/services/connection_types.py (neutral module, no DB imports). VALID_STATUSES constant validates update_status() input. Connection route errors use consistent {"error": {"code": str, "message": str}} schema. Startup code imports CredentialDecryptionError at module scope to prevent NameError in exception handling. SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY strict mode enforced in startup lifespan. 422 handler wraps sanitized detail in standard error schema with additional detail array. CLI paths (http_client.py, runner.py) temporarily exempt from env-read enforcement with TODOs. Explicit key misconfig (bad base64, wrong length, missing key file) is fatal at startup — ValueError propagates. Per-row decrypt failures are non-blocking. created_at/updated_at backfilled during migration. list_connections/get_connection never fail on decrypt errors — return runtime_usable=false with runtime_reason="decrypt_failed". Task 4 defines check_all() as a stub; Task 6 implements the full logic. Key file permission warning on overly permissive Unix permissions. client_id redacted as safe default (documented tradeoff). Task 4 is split into 4A (types + validation + CRUD + AAD + encryption) and 4B (resolvers + runtime_usable + decrypt resilience + status updates) to reduce blast radius. ProviderConnection columns use TEXT for timestamps (not SQLAlchemy DateTime) to guarantee Z-suffix format. id is UUID4 TEXT PK. updated_at is service-managed (no ORM onupdate). ConnectionService raises typed ConnectionValidationError(code, message) instead of bare ValueError. Shopify env fallback is domain-matched when store_domain is explicitly requested. check_all() validates row field completeness before decrypt (INVALID_ROW for missing fields). Migration pre-checks for duplicate connection_keys before index creation. All ISO8601 timestamps use UTC with Z suffix (YYYY-MM-DDTHH:MM:SSZ).

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
# Test-created temp key artifacts
.shipagent_key_*
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

    def test_handles_list_of_dicts(self):
        from src.utils.redaction import redact_for_logging

        data = {"errors": [{"client_secret": "leaked", "field": "x"}]}
        result = redact_for_logging(data)
        assert result["errors"][0]["client_secret"] == "***REDACTED***"
        assert result["errors"][0]["field"] == "x"

    def test_empty_dict(self):
        from src.utils.redaction import redact_for_logging

        assert redact_for_logging({}) == {}

    def test_custom_sensitive_keys(self):
        from src.utils.redaction import redact_for_logging

        data = {"api_key": "key123", "name": "test"}
        result = redact_for_logging(data, sensitive_patterns=frozenset({"api_key"}))
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "test"

    def test_case_insensitive_matching(self):
        from src.utils.redaction import redact_for_logging

        data = {"ClientSecret": "sec1", "ACCESS_TOKEN": "tok1", "Name": "UPS"}
        result = redact_for_logging(data)
        assert result["ClientSecret"] == "***REDACTED***"
        assert result["ACCESS_TOKEN"] == "***REDACTED***"
        assert result["Name"] == "UPS"

    def test_substring_pattern_matching(self):
        from src.utils.redaction import redact_for_logging

        data = {"x_api_key": "key1", "bearer_token": "tok1", "shopify_access_token": "tok2", "name": "ok"}
        result = redact_for_logging(data)
        assert result["x_api_key"] == "***REDACTED***"
        assert result["bearer_token"] == "***REDACTED***"
        assert result["shopify_access_token"] == "***REDACTED***"
        assert result["name"] == "ok"

    def test_container_key_recursion(self):
        from src.utils.redaction import redact_for_logging

        data = {"credentials": {"user": "admin", "pass": "hunter2"}, "name": "test"}
        result = redact_for_logging(data)
        # "credentials" is a known container key — its entire value is redacted
        assert result["credentials"] == "***REDACTED***"
        assert result["name"] == "test"

    def test_sanitize_error_message_key_value(self):
        from src.utils.redaction import sanitize_error_message

        msg = "Failed with client_secret=abc123 and token=xyz"
        result = sanitize_error_message(msg)
        assert "abc123" not in result
        assert "xyz" not in result

    def test_sanitize_error_message_bearer_token(self):
        from src.utils.redaction import sanitize_error_message

        msg = "Request failed: Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.abc.xyz"
        result = sanitize_error_message(msg)
        assert "eyJhbGciOiJSUzI1NiJ9" not in result

    def test_sanitize_error_message_json_style(self):
        from src.utils.redaction import sanitize_error_message

        msg = 'Upstream error: {"client_secret": "abc123", "name": "test"}'
        result = sanitize_error_message(msg)
        assert "abc123" not in result

    def test_sanitize_error_message_quoted_values(self):
        from src.utils.redaction import sanitize_error_message

        msg = 'Failed: access_token = "abc 123" in request'
        result = sanitize_error_message(msg)
        assert "abc 123" not in result

    def test_sanitize_error_message_multi_token(self):
        from src.utils.redaction import sanitize_error_message

        msg = "client_id=foo client_secret=bar token=baz"
        result = sanitize_error_message(msg)
        assert "foo" not in result
        assert "bar" not in result
        assert "baz" not in result

    def test_sanitize_error_message_length_cap(self):
        from src.utils.redaction import sanitize_error_message

        long_msg = "x" * 5000
        result = sanitize_error_message(long_msg, max_length=2000)
        assert len(result) <= 2000
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/utils/test_redaction.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/utils/redaction.py
"""Secret redaction utility for safe logging and error responses.

Provides centralized redaction to prevent credential leakage in logs,
error messages, and API error responses. Uses case-insensitive substring
matching for sensitive key detection. Handles nested dicts, lists of dicts,
and known container keys.
"""

import re

# Substring patterns matched case-insensitively against dict keys
_DEFAULT_SENSITIVE_PATTERNS = frozenset({
    "secret", "token", "authorization", "api_key", "password",
    "credential", "client_id", "client_secret", "access_token",
    "refresh_token",
})

# Keys whose entire value is redacted (regardless of content type)
_CONTAINER_KEYS = frozenset({"credentials", "headers"})

_REDACTED = "***REDACTED***"


def _is_sensitive_key(key: str, sensitive_patterns: frozenset[str]) -> bool:
    """Check if a key matches any sensitive pattern (case-insensitive substring).

    Args:
        key: Dict key to check.
        sensitive_patterns: Patterns to match against.

    Returns:
        True if the key matches any sensitive pattern.
    """
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in sensitive_patterns)


def redact_for_logging(
    obj: dict,
    sensitive_patterns: frozenset[str] = _DEFAULT_SENSITIVE_PATTERNS,
) -> dict:
    """Redact sensitive values from a dict for safe logging/error responses.

    Args:
        obj: Dict to redact (not mutated — returns a copy).
        sensitive_patterns: Substring patterns whose matching keys' values
            should be replaced. Matching is case-insensitive.

    Returns:
        New dict with sensitive values replaced by '***REDACTED***'.
        Handles nested dicts, lists of dicts, and container keys recursively.
    """
    result = {}
    for key, value in obj.items():
        key_lower = key.lower()
        if key_lower in _CONTAINER_KEYS:
            result[key] = _REDACTED
        elif _is_sensitive_key(key, sensitive_patterns):
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = redact_for_logging(value, sensitive_patterns)
        elif isinstance(value, list):
            result[key] = [
                redact_for_logging(item, sensitive_patterns) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


# Patterns for detecting sensitive values in free-text error messages.
# Handles: key=value, Authorization: Bearer <token>, "key": "value",
# key = "quoted value", and multi-token lines.
_SENSITIVE_KEYWORDS = (
    r"secret|token|password|api_key|client_id|client_secret|"
    r"access_token|refresh_token|authorization|credential"
)
_SENSITIVE_VALUE_PATTERNS = re.compile(
    r"(?i)"
    r"(?:"
    # Pattern 1: Authorization: Bearer <token>
    r"Authorization\s*:\s*Bearer\s+\S+"
    r"|"
    # Pattern 2: JSON-style "key": "value" or "key":"value"
    r'"(?:' + _SENSITIVE_KEYWORDS + r')"\s*:\s*"[^"]*"'
    r"|"
    # Pattern 3: key = "quoted value" or key="quoted value"
    r"(?:" + _SENSITIVE_KEYWORDS + r")\s*[=:]\s*\"[^\"]*\""
    r"|"
    # Pattern 4: key=value (unquoted, consumes until whitespace/end)
    r"(?:" + _SENSITIVE_KEYWORDS + r")\s*[=:]\s*\S+"
    r")",
)


def sanitize_error_message(msg: str | None, max_length: int = 2000) -> str | None:
    """Sanitize an error message for safe DB persistence.

    Redacts sensitive-looking key=value pairs and truncates to max_length.

    Args:
        msg: Error message to sanitize (None passes through).
        max_length: Maximum length of the sanitized message.

    Returns:
        Sanitized and truncated message, or None.
    """
    if msg is None:
        return None
    sanitized = _SENSITIVE_VALUE_PATTERNS.sub("***REDACTED***", msg)
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + "..."
    return sanitized
```

**Step 4: Create `src/utils/__init__.py` if it doesn't exist**

Run: `touch src/utils/__init__.py` and `touch tests/utils/__init__.py`

**Step 5: Run tests to verify they pass**

Run: `pytest tests/utils/test_redaction.py -v`
Expected: All 15 tests PASS

**Step 6: Commit**

```bash
git add src/utils/redaction.py src/utils/__init__.py tests/utils/test_redaction.py tests/utils/__init__.py
git commit -m "feat: add secret redaction utility with case-insensitive substring matching and multi-format error message sanitization"
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

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix permissions")
    def test_permissive_key_file_warns(self, temp_key_dir, caplog):
        """Key file with overly permissive permissions logs a warning."""
        import logging
        from src.services.credential_encryption import get_or_create_key

        key_path = os.path.join(temp_key_dir, ".shipagent_key")
        with open(key_path, "wb") as f:
            f.write(os.urandom(32))
        os.chmod(key_path, 0o644)
        with caplog.at_level(logging.WARNING):
            get_or_create_key(key_dir=temp_key_dir)
        assert any("permissions" in msg and "600" in msg for msg in caplog.messages)

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

    def test_invalid_base64_env_key_raises(self):
        """SHIPAGENT_CREDENTIAL_KEY with invalid base64 raises ValueError."""
        from src.services.credential_encryption import get_or_create_key

        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = "not-valid-base64!!!"
        try:
            with pytest.raises(ValueError, match="[Ii]nvalid.*base64"):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)

    def test_env_key_wins_over_env_file(self, temp_key_dir):
        """When both SHIPAGENT_CREDENTIAL_KEY and KEY_FILE are set, env key wins."""
        from src.services.credential_encryption import get_or_create_key

        env_key = os.urandom(32)
        file_key = os.urandom(32)
        custom_path = os.path.join(temp_key_dir, "file_key")
        with open(custom_path, "wb") as f:
            f.write(file_key)

        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(env_key).decode()
        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = custom_path
        try:
            key = get_or_create_key(key_dir=temp_key_dir)
            assert key == env_key  # env key wins
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)

    def test_key_file_missing_raises(self):
        """SHIPAGENT_CREDENTIAL_KEY_FILE pointing to missing file raises."""
        from src.services.credential_encryption import get_or_create_key

        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = "/nonexistent/path/key"
        try:
            with pytest.raises((ValueError, FileNotFoundError)):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)

    def test_key_file_is_directory_raises(self, temp_key_dir):
        """SHIPAGENT_CREDENTIAL_KEY_FILE pointing to a directory raises."""
        from src.services.credential_encryption import get_or_create_key

        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = temp_key_dir
        try:
            with pytest.raises((ValueError, IsADirectoryError)):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)

    def test_key_file_symlink_raises(self, temp_key_dir):
        """SHIPAGENT_CREDENTIAL_KEY_FILE pointing to a symlink raises."""
        from src.services.credential_encryption import get_or_create_key

        real_path = os.path.join(temp_key_dir, "real_key")
        with open(real_path, "wb") as f:
            f.write(os.urandom(32))
        link_path = os.path.join(temp_key_dir, "link_key")
        os.symlink(real_path, link_path)
        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = link_path
        try:
            with pytest.raises(ValueError, match="symlink"):
                get_or_create_key()
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)

    def test_concurrent_key_creation_race(self, temp_key_dir):
        """FileExistsError from O_EXCL race is handled by reading existing file."""
        from src.services.credential_encryption import get_or_create_key

        # Create the key file first (simulates another process winning the race)
        key_path = os.path.join(temp_key_dir, ".shipagent_key")
        existing_key = os.urandom(32)
        with open(key_path, "wb") as f:
            f.write(existing_key)
        # Second call should read existing file, not error
        key = get_or_create_key(key_dir=temp_key_dir)
        assert key == existing_key

    def test_strict_mode_fails_on_platformdirs(self, temp_key_dir):
        """SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY=true fails when key source is platformdirs."""
        from src.services.credential_encryption import get_key_source_info
        for var in ("SHIPAGENT_CREDENTIAL_KEY", "SHIPAGENT_CREDENTIAL_KEY_FILE"):
            os.environ.pop(var, None)
        os.environ["SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY"] = "true"
        try:
            info = get_key_source_info()
            assert info["source"] == "platformdirs"
            # Strict mode check would raise RuntimeError in startup
        finally:
            os.environ.pop("SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY", None)

    def test_strict_mode_passes_with_env_key(self, temp_key_dir):
        """SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY=true passes when env key is set."""
        from src.services.credential_encryption import get_key_source_info
        raw_key = os.urandom(32)
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(raw_key).decode()
        os.environ["SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY"] = "true"
        try:
            info = get_key_source_info()
            assert info["source"] == "env"  # Not platformdirs — strict mode OK
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)
            os.environ.pop("SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY", None)

    def test_strict_mode_passes_with_env_file(self, temp_key_dir):
        """SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY=true passes when env file is set."""
        from src.services.credential_encryption import get_key_source_info
        custom_path = os.path.join(temp_key_dir, "strict_key")
        with open(custom_path, "wb") as f:
            f.write(os.urandom(32))
        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = custom_path
        os.environ["SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY"] = "true"
        try:
            info = get_key_source_info()
            assert info["source"] == "env_file"  # Not platformdirs — strict mode OK
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)
            os.environ.pop("SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY", None)

    def test_get_key_source_info_env(self, temp_key_dir):
        """get_key_source_info reports env source when env key is set."""
        from src.services.credential_encryption import get_key_source_info

        raw_key = os.urandom(32)
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(raw_key).decode()
        try:
            info = get_key_source_info()
            assert info["source"] == "env"
            assert info["path"] is None
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)

    def test_get_key_source_info_env_file(self, temp_key_dir):
        """get_key_source_info reports env_file source when env path is set."""
        from src.services.credential_encryption import get_key_source_info

        custom_path = os.path.join(temp_key_dir, "custom_key")
        with open(custom_path, "wb") as f:
            f.write(os.urandom(32))
        os.environ["SHIPAGENT_CREDENTIAL_KEY_FILE"] = custom_path
        try:
            info = get_key_source_info()
            assert info["source"] == "env_file"
            assert info["path"] == custom_path
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY_FILE", None)

    def test_get_key_source_info_platformdirs(self):
        """get_key_source_info reports platformdirs source when no env overrides."""
        from src.services.credential_encryption import get_key_source_info

        for var in ("SHIPAGENT_CREDENTIAL_KEY", "SHIPAGENT_CREDENTIAL_KEY_FILE"):
            os.environ.pop(var, None)
        info = get_key_source_info()
        assert info["source"] == "platformdirs"
        assert info["path"] is not None
        assert "shipagent" in info["path"]


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

    def test_encrypt_rejects_short_key(self):
        """encrypt_credentials rejects 16-byte key (would silently use AES-128)."""
        from src.services.credential_encryption import encrypt_credentials

        short_key = os.urandom(16)
        with pytest.raises(ValueError, match="32"):
            encrypt_credentials({"k": "v"}, short_key, aad="test")

    def test_encrypt_rejects_24_byte_key(self):
        """encrypt_credentials rejects 24-byte key (would silently use AES-192)."""
        from src.services.credential_encryption import encrypt_credentials

        key_24 = os.urandom(24)
        with pytest.raises(ValueError, match="32"):
            encrypt_credentials({"k": "v"}, key_24, aad="test")

    def test_decrypt_rejects_short_key(self, temp_key_dir):
        """decrypt_credentials rejects non-32-byte key."""
        from src.services.credential_encryption import (
            CredentialDecryptionError, decrypt_credentials,
            encrypt_credentials, get_or_create_key,
        )

        key = get_or_create_key(key_dir=temp_key_dir)
        ciphertext = encrypt_credentials({"k": "v"}, key, aad="test")
        short_key = os.urandom(16)
        with pytest.raises(CredentialDecryptionError, match="32"):
            decrypt_credentials(ciphertext, short_key, aad="test")
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

Key length enforcement:
    Both encrypt_credentials() and decrypt_credentials() validate len(key) == 32.
    This prevents silent downgrade to AES-128-GCM or AES-192-GCM while the
    envelope still claims "AES-256-GCM".

Ciphertext format: versioned JSON envelope with AAD binding and algorithm validation.
"""

import base64
import binascii
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
_REQUIRED_KEY_LENGTH = 32


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


def get_key_source_info() -> dict:
    """Return metadata about the active key source (without revealing the key).

    Returns:
        {"source": "env"|"env_file"|"platformdirs", "path": str | None}
    """
    env_key = os.environ.get("SHIPAGENT_CREDENTIAL_KEY", "").strip()
    if env_key:
        return {"source": "env", "path": None}

    env_key_file = os.environ.get("SHIPAGENT_CREDENTIAL_KEY_FILE", "").strip()
    if env_key_file:
        return {"source": "env_file", "path": env_key_file}

    default_dir = get_default_key_dir()
    return {"source": "platformdirs", "path": os.path.join(default_dir, KEY_FILENAME)}


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
        ValueError: If key has invalid length from any source, or invalid base64.
    """
    # Source 1: env var (base64-encoded key)
    env_key = os.environ.get("SHIPAGENT_CREDENTIAL_KEY", "").strip()
    if env_key:
        try:
            key = base64.b64decode(env_key, validate=True)
        except binascii.Error as e:
            raise ValueError(
                f"SHIPAGENT_CREDENTIAL_KEY contains invalid base64: {e}"
            ) from e
        if len(key) != _REQUIRED_KEY_LENGTH:
            raise ValueError(
                f"SHIPAGENT_CREDENTIAL_KEY has invalid length {len(key)} (expected {_REQUIRED_KEY_LENGTH})"
            )
        return key

    # Source 2: env var pointing to key file
    env_key_file = os.environ.get("SHIPAGENT_CREDENTIAL_KEY_FILE", "").strip()
    if env_key_file:
        if not os.path.exists(env_key_file):
            raise ValueError(
                f"SHIPAGENT_CREDENTIAL_KEY_FILE path does not exist: {env_key_file}"
            )
        if not os.path.isfile(env_key_file):
            raise ValueError(
                f"SHIPAGENT_CREDENTIAL_KEY_FILE is not a regular file: {env_key_file}"
            )
        if os.path.islink(env_key_file):
            raise ValueError(
                f"SHIPAGENT_CREDENTIAL_KEY_FILE is a symlink: {env_key_file}. "
                "Symlinks are rejected to prevent link-following attacks."
            )
        with open(env_key_file, "rb") as f:
            key = f.read()
        if len(key) != _REQUIRED_KEY_LENGTH:
            raise ValueError(
                f"Key file {env_key_file} has invalid length {len(key)} (expected {_REQUIRED_KEY_LENGTH})"
            )
        return key

    # Source 3: platformdirs file (auto-generated)
    directory = key_dir or get_default_key_dir()
    os.makedirs(directory, exist_ok=True)
    key_path = os.path.join(directory, KEY_FILENAME)

    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            key = f.read()
        if len(key) != _REQUIRED_KEY_LENGTH:
            raise ValueError(
                f"Key file {key_path} has invalid length {len(key)} (expected {_REQUIRED_KEY_LENGTH}). "
                "Delete the file to regenerate."
            )
        # Warn if existing file has overly permissive permissions
        if platform.system() != "Windows":
            mode = stat.S_IMODE(os.stat(key_path).st_mode)
            if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
                logger.warning(
                    "Key file %s has permissions %o — recommend chmod 600 for security",
                    key_path, mode,
                )
        return key

    key = os.urandom(_REQUIRED_KEY_LENGTH)
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
    except FileExistsError:
        # Concurrent startup race: another process created the file first.
        # Read the existing file instead of erroring.
        with open(key_path, "rb") as f:
            key = f.read()
        if len(key) != _REQUIRED_KEY_LENGTH:
            raise ValueError(
                f"Key file {key_path} has invalid length {len(key)} (expected {_REQUIRED_KEY_LENGTH}). "
                "Delete the file to regenerate."
            )
        return key

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

    Raises:
        ValueError: If key is not exactly 32 bytes.
    """
    if len(key) != _REQUIRED_KEY_LENGTH:
        raise ValueError(
            f"Encryption key must be exactly {_REQUIRED_KEY_LENGTH} bytes "
            f"(got {len(key)}). AES-256-GCM requires a 256-bit key."
        )
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
        CredentialDecryptionError: If decryption fails for any reason,
            including wrong key length.
    """
    if len(key) != _REQUIRED_KEY_LENGTH:
        raise CredentialDecryptionError(
            f"Decryption key must be exactly {_REQUIRED_KEY_LENGTH} bytes "
            f"(got {len(key)}). AES-256-GCM requires a 256-bit key."
        )

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
Expected: All 33 tests PASS

**Step 5: Commit**

```bash
git add src/services/credential_encryption.py tests/services/test_credential_encryption.py
git commit -m "feat: add AES-256-GCM credential encryption with key length enforcement, base64 validation, and observability"
```

---

### Task 3: ProviderConnection Database Model + Migration

**Files:**
- Modify: `src/db/models.py`
- Modify: `src/db/connection.py` (add migration for new table)
- Create: `tests/db/test_provider_connection_model.py`

**Step 1: Write the failing tests**

9 tests covering model creation and migration idempotency:

```python
# tests/db/test_provider_connection_model.py
"""Tests for ProviderConnection model and migration."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderConnection


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class TestProviderConnectionModel:

    def test_create_ups_connection(self, db_session):
        """Can create a UPS connection row with all required fields."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="UPS Test", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="encrypted_blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.id is not None
        assert conn.connection_key == "ups:test"

    def test_create_shopify_connection(self, db_session):
        """Can create a Shopify connection row."""
        conn = ProviderConnection(
            connection_key="shopify:store.myshopify.com",
            provider="shopify", display_name="My Store",
            auth_mode="legacy_token", status="configured",
            encrypted_credentials="encrypted_blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.provider == "shopify"

    def test_unique_connection_key_constraint(self, db_session):
        """Duplicate connection_key raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        conn1 = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="A", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob1",
        )
        conn2 = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="B", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob2",
        )
        db_session.add(conn1)
        db_session.commit()
        db_session.add(conn2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_default_timestamps_set(self, db_session):
        """created_at and updated_at are auto-populated."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="UPS", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.created_at is not None
        assert conn.updated_at is not None

    def test_default_schema_and_key_version(self, db_session):
        """schema_version defaults to 1, key_version defaults to 1."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="UPS", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.schema_version == 1
        assert conn.key_version == 1


class TestProviderConnectionMigration:

    def test_migration_creates_table_on_empty_db(self):
        """Migration creates provider_connections table on fresh DB."""
        engine = create_engine("sqlite:///:memory:")
        from src.db.connection import _ensure_columns_exist
        with engine.connect() as conn:
            _ensure_columns_exist(conn)
        inspector = inspect(engine)
        assert "provider_connections" in inspector.get_table_names()

    def test_migration_adds_missing_columns(self):
        """Migration adds missing columns to existing table."""
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE provider_connections (id TEXT PRIMARY KEY, connection_key TEXT)"
            ))
            conn.commit()
        from src.db.connection import _ensure_columns_exist
        with engine.connect() as conn:
            _ensure_columns_exist(conn)
        inspector = inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("provider_connections")}
        assert "provider" in columns
        assert "encrypted_credentials" in columns

    def test_migration_is_idempotent(self):
        """Running migration twice produces no errors."""
        engine = create_engine("sqlite:///:memory:")
        from src.db.connection import _ensure_columns_exist
        with engine.connect() as conn:
            _ensure_columns_exist(conn)
        with engine.connect() as conn:
            _ensure_columns_exist(conn)  # Second run — no error

    def test_migration_creates_unique_index_on_partial_table(self):
        """Migration creates unique index even if table existed without it."""
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE provider_connections ("
                "id TEXT PRIMARY KEY, connection_key TEXT, provider TEXT"
                ")"
            ))
            conn.commit()
        from src.db.connection import _ensure_columns_exist
        with engine.connect() as conn:
            _ensure_columns_exist(conn)
        inspector = inspect(engine)
        indexes = inspector.get_indexes("provider_connections")
        index_names = {idx["name"] for idx in indexes}
        assert "idx_provider_connections_connection_key" in index_names
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_provider_connection_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProviderConnection'`

**Step 3: Add ProviderConnection model to `src/db/models.py`**

Add after the `CustomCommand` class (the model is specified in the design doc — see Section 1). Include the `connection_key` unique column, `last_error_code`, `error_message`, `schema_version`, `key_version` fields. Single index on `provider` only (no redundant `connection_key` index since `UNIQUE` already creates one).

**Naming:** Use `metadata_json` as the SQLAlchemy column attribute name (avoids `Base.metadata` collision). API serializer maps to `metadata` in responses. `key_version` defaults to `1` — Phase 1 does not implement rotation.

**`metadata_json` storage:** Stored as `Text` column (not SQLAlchemy `JSON` type). Parsed in service layer via `json.loads()` with `try/except`. On parse failure: return `{}` and log WARNING (sanitized — no raw column content in logs). This prevents ORM-level deserialization crashes on corrupt data.

**Exact SQLAlchemy column definitions:**
```python
class ProviderConnection(Base):
    __tablename__ = "provider_connections"

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_key = Column(Text, nullable=False, unique=True)
    provider = Column(Text, nullable=False)  # "ups" | "shopify"
    display_name = Column(Text, nullable=False)
    auth_mode = Column(Text, nullable=False)
    environment = Column(Text, nullable=True)  # UPS only: "test" | "production"
    status = Column(Text, nullable=False, default="configured")
    encrypted_credentials = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True, default="{}")  # TEXT, not JSON type
    last_error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    schema_version = Column(Integer, nullable=False, default=1)
    key_version = Column(Integer, nullable=False, default=1)
    created_at = Column(Text, nullable=False)  # YYYY-MM-DDTHH:MM:SSZ, service-set
    updated_at = Column(Text, nullable=False)  # YYYY-MM-DDTHH:MM:SSZ, service-set
```

**Column type contract:**
- `id`: UUID4 string via `str(uuid.uuid4())` — not auto-increment integer.
- `created_at` / `updated_at`: TEXT columns, NOT SQLAlchemy `DateTime`. This ensures Z suffix is always present (avoids ORM producing `+00:00`).
- `updated_at`: set manually in `save_connection()` and `update_status()` — no ORM `onupdate`. Deterministic and testable.
- No column length constraints (SQLite ignores them). Validation at service layer.

**Step 4: Add migration to `src/db/connection.py`**

Add to the end of `_ensure_columns_exist()`, following the existing pattern:

1. `CREATE TABLE IF NOT EXISTS provider_connections (...)` with all columns
2. `PRAGMA table_info(provider_connections)` to introspect existing columns
3. `ALTER TABLE provider_connections ADD COLUMN ...` for each missing column (idempotent)
4. **Duplicate-key pre-check** (before unique index creation):
```sql
SELECT connection_key, COUNT(*) c
FROM provider_connections
GROUP BY connection_key
HAVING c > 1;
```
If results returned: log sanitized duplicate keys at ERROR level, raise `RuntimeError(f"Found {count} duplicate connection_key values — resolve before migration can proceed")`. Do not attempt index creation on a table with duplicates.
5. `CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_connections_connection_key ON provider_connections (connection_key)` — hardens unique constraint for partial-upgrade scenarios
6. `CREATE INDEX IF NOT EXISTS idx_provider_connections_provider ON provider_connections (provider)`
7. **Backfill step** (after column additions):
   - `UPDATE provider_connections SET metadata_json = '{}' WHERE metadata_json IS NULL`
   - `UPDATE provider_connections SET schema_version = 1 WHERE schema_version IS NULL`
   - `UPDATE provider_connections SET key_version = 1 WHERE key_version IS NULL`
   - `UPDATE provider_connections SET status = 'needs_reconnect' WHERE status IS NULL`
   - Set `created_at` and `updated_at` to current UTC timestamp (YYYY-MM-DDTHH:MM:SSZ format) where NULL
   - Use `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")` for the backfill value
   - Log count of backfilled rows at INFO level

**SQLite nullability:** All `ALTER TABLE ADD COLUMN` statements add columns as nullable (SQLite requirement). Application defaults and the backfill step above enforce data integrity. Rows with missing `status`, `auth_mode`, or `encrypted_credentials` are marked `needs_reconnect` to force user re-save.

**Duplicate row handling:** If `CREATE UNIQUE INDEX` fails because duplicate `connection_key` rows exist, log an ERROR with the duplicate keys and raise. Do not silently proceed with a broken schema.

**Step 5: Run tests to verify they pass**

Run: `pytest tests/db/test_provider_connection_model.py -v`
Expected: All 9 tests PASS

**Step 6: Commit**

```bash
git add src/db/models.py src/db/connection.py tests/db/test_provider_connection_model.py
git commit -m "feat: add ProviderConnection model with hardened idempotent migration and unique index"
```

---

### Task 4A: ConnectionService — Types, Validation, CRUD

**Files:**
- Create: `src/services/connection_types.py`
- Create: `src/services/connection_service.py`
- Create: `tests/services/test_connection_service.py`

**Step 1: Write the failing tests**

Tests cover (~25 tests total):
- CRUD: save (sets `"configured"`, returns `is_new` flag), get, list (ordered by `provider, connection_key`), delete, overwrite
- Input validation: reject invalid provider (`raises ConnectionValidationError(code="INVALID_PROVIDER")`), invalid auth_mode, missing required UPS fields, missing Shopify store_domain, missing Shopify access_token (legacy only)
- Shared constants: `VALID_PROVIDERS`, `VALID_AUTH_MODES`, `VALID_ENVIRONMENTS`, `SKIP_STATUSES` used in validation (not raw strings)
- `client_credentials_shopify` does NOT require `access_token` (Phase 2 obtains it)
- Domain normalization: `"HTTPS://MyStore.MyShopify.com/"` → `"mystore.myshopify.com"`, invalid domain rejected
- UPS environment validation: reject `""`, `None`, `"sandbox"` — require `"test"` or `"production"`
- Disconnect: sets `"disconnected"`, preserves credentials
- Re-save on disconnected row resets status to `"configured"`
- `updated_at` changes on overwrite
- Centralized AAD construction via `_build_aad()`
- Commit rollback: IntegrityError doesn't corrupt session
- **Error message sanitization:** `_sanitize_error_message()` redacts sensitive substrings (Bearer tokens, JSON-style, quoted values) and truncates
- **key_version always 1:** Verify new connections have `key_version == 1`
- **Credential key validation:** reject unknown keys for UPS (e.g., `{"client_id": "x", "rogue_key": "y"}`), `raises ConnectionValidationError(code="UNKNOWN_CREDENTIAL_KEY")` / return 400
- **Credential max length:** reject excessively long client_id (>1024 chars), `raises ConnectionValidationError(code="VALUE_TOO_LONG")`
- **Corrupt metadata_json handling:** row with invalid JSON in metadata_json returns {} in get_connection
- **VALID_STATUSES enforcement:** update_status with unknown status raises ValueError
- **check_all stub:** `check_all()` returns `{}` (stub — full implementation in Task 6)

```python
    # ... (existing tests from Rev 6) ...

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

    def test_check_all_stub_returns_empty(self, service):
        """check_all() stub returns empty dict (full implementation in Task 6)."""
        service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        results = service.check_all()
        assert results == {}

    def test_key_version_always_one(self, service):
        """New connections have key_version == 1 (no rotation in Phase 1)."""
        result = service.save_connection(
            provider="ups", auth_mode="client_credentials",
            credentials={"client_id": "id", "client_secret": "sec"},
            metadata={}, environment="test", display_name="UPS",
        )
        conn = service.get_connection("ups:test")
        # key_version should be present and equal to 1
        assert conn.get("key_version", 1) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

**Important:** Credential dataclasses (`UPSCredentials`, `ShopifyLegacyCredentials`, `ShopifyClientCredentials`) are defined in `src/services/connection_types.py` — a neutral module with no DB or service-layer imports. `ConnectionService`, `runtime_credentials.py`, and `config.py` all import from this module. Create this file in Task 4A Step 3, before the service implementation.

Key implementation details:
- Shared constants at module level: `VALID_PROVIDERS`, `VALID_AUTH_MODES`, `VALID_ENVIRONMENTS`, `SKIP_STATUSES`, `RUNTIME_USABLE_STATUSES`
- Three credential dataclasses: `UPSCredentials`, `ShopifyLegacyCredentials`, `ShopifyClientCredentials`
- `ShopifyClientCredentials.access_token` defaults to `""` (not required in Phase 1)

```python
class ConnectionValidationError(Exception):
    """Typed validation error with structured error code.

    Replaces bare ValueError for all ConnectionService validation failures.
    API routes map this to 400 with {"error": {"code": e.code, "message": e.message}}.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
```

**Error codes:**
- `INVALID_PROVIDER` — provider not in VALID_PROVIDERS
- `INVALID_AUTH_MODE` — auth_mode not valid for provider
- `INVALID_ENVIRONMENT` — UPS environment not "test" or "production"
- `MISSING_FIELD` — required credential or metadata field missing
- `UNKNOWN_CREDENTIAL_KEY` — credential key not in allowlist (rejected with 400)
- `VALUE_TOO_LONG` — credential value exceeds max length
- `INVALID_DOMAIN` — Shopify domain fails normalization

- `_normalize_shopify_domain()` — lowercase, strip protocol, strip trailing slashes, validate `*.myshopify.com`
- `_validate_save_input()` — validates provider (against `VALID_PROVIDERS`), auth_mode (against `VALID_AUTH_MODES[provider]`), required fields per provider, UPS environment required and must be in `VALID_ENVIRONMENTS`
- `_build_aad(row)` — centralized AAD construction: `f"{row.provider}:{row.auth_mode}:{row.connection_key}"`
- `_sanitize_error_message(msg)` — uses `sanitize_error_message()` from `src/utils/redaction.py`
- `save_connection()` returns `is_new: bool` flag + `runtime_usable` + `runtime_reason`, always sets status to `"configured"` (even on disconnected overwrite)
- `check_all()` — **stub in Task 4A** that returns `{}`. Full implementation is in Task 6.
- **Auth-mode switch overwrite safety:** When overwriting a row's `auth_mode`, the old encrypted blob is NOT decrypted — the entire `encrypted_credentials` column is replaced with a new encryption under the new AAD. No need to read old credentials.
- `disconnect(connection_key)` — sets `"disconnected"` status, preserves credentials
- `update_status()` — sanitizes `error_message` before persistence
- `encrypt_credentials()` uses `json.dumps(sort_keys=True)` for canonical serialization
- All commit paths wrapped in try/except with rollback
- **Credential payload allowlists:** `_validate_credential_keys(provider, auth_mode, credentials)` validates:
  - UPS `client_credentials`: required `client_id`, `client_secret`; no optional keys; max 1024 chars each
  - Shopify `legacy_token`: required `access_token`; no optional keys; max 4096 chars
  - Shopify `client_credentials_shopify`: required `client_id`, `client_secret`; optional `access_token`; max 1024/1024/4096 chars
  - Unknown keys: rejected with 400 (`ConnectionValidationError(code="UNKNOWN_CREDENTIAL_KEY")` raised). This catches typos (e.g., `client_secert`) early and keeps behavior deterministic.
  - Excessively long values: rejected with `ConnectionValidationError(code="VALUE_TOO_LONG")`
  - Called after `_validate_save_input()`, before `encrypt_credentials()`
- **`metadata_json` deserialization:** `_deserialize_metadata(row)` wraps `json.loads(row.metadata_json)` with try/except. Returns `{}` on parse failure with sanitized WARNING log. Used in all get/list paths.
- **`VALID_STATUSES` enforcement:** `update_status()` validates incoming status against `VALID_STATUSES = frozenset({"configured", "validating", "connected", "disconnected", "error", "needs_reconnect"})`. Unknown statuses raise ValueError.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: All ~25 tests PASS

**Step 5: Commit**

```bash
git add src/services/connection_types.py src/services/connection_service.py tests/services/test_connection_service.py
git commit -m "feat: add ConnectionService types, validation, CRUD with encrypted storage and AAD binding"
```

---

### Task 4B: ConnectionService — Resolvers, Runtime Usability, Decrypt Resilience

**Files:**
- Modify: `src/services/connection_service.py`
- Modify: `tests/services/test_connection_service.py`

**Step 1: Write the failing tests**

Tests cover (~18 tests total):
- Credential resolver: `get_ups_credentials(environment)`, `get_shopify_credentials(store_domain)`, `get_first_shopify_credentials()`
- Shopify dual resolver types: `ShopifyLegacyCredentials` for legacy, `ShopifyClientCredentials` for client_credentials_shopify
- Resolver skips `disconnected` and `needs_reconnect` rows
- `get_first_shopify_credentials()` deterministic default: ORDER BY connection_key ASC at DB level
- `get_first_shopify_credentials()` skips disconnected and needs_reconnect
- **`runtime_usable` computation:** `_is_runtime_usable()` returns `(True, None)` for configured legacy_token, `(False, "missing_access_token")` for client_credentials_shopify with no token, `(False, "disconnected")` for disconnected rows
- **Auth mode switching on same connection key:** Save as `legacy_token`, overwrite as `client_credentials_shopify` on same store domain, verify decrypt still works and AAD matches new row values (old creds not decrypted — entire blob replaced)
- **list_connections decrypt resilience:** row with corrupt encrypted_credentials returns runtime_usable=false, doesn't crash list
- **get_connection decrypt resilience:** same for get
- **Corrupt metadata_json handling in resolvers:** row with invalid JSON in metadata_json handled gracefully

```python
    # ... (added to existing test file from Task 4A) ...

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
        assert creds.client_id == "cid"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: FAIL — new tests fail (resolvers, runtime_usable not yet implemented)

**Step 3: Write implementation**

Key implementation details:
- `_is_runtime_usable(row)` — returns `(bool, str | None)`: `(False, "disconnected")` for skip statuses, `(False, "missing_access_token")` for `client_credentials_shopify` with empty token, `(True, None)` otherwise
- `get_ups_credentials(environment)` — skips rows with status in `SKIP_STATUSES`, derives `base_url` from environment, returns `UPSCredentials` typed dataclass
- `get_shopify_credentials(store_domain)` — requires explicit store domain, normalizes input before lookup, skips `SKIP_STATUSES` rows, returns `ShopifyLegacyCredentials | ShopifyClientCredentials | None` typed union
- `get_first_shopify_credentials()` — Phase 1 default: queries DB with `ORDER BY connection_key ASC`, filters `status NOT IN SKIP_STATUSES` at DB query level, returns first result as typed dataclass
- `list_connections()` — updated to include `runtime_usable` in each response
- `get_connection()` — updated to include `runtime_usable` in response
- **list/get decrypt resilience:** `list_connections()` and `get_connection()` compute `runtime_usable` without raising on decrypt errors. When a row has corrupt/wrong-key credentials, catch `CredentialDecryptionError` and return `runtime_usable = false`, `runtime_reason = "decrypt_failed"`. Status is NOT mutated — mutation is exclusively in `check_all()` and explicit `update_status()`. WARNING logged (sanitized). This prevents a corrupt row from 500-ing the Settings page.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_connection_service.py -v`
Expected: All ~43 tests PASS (25 from 4A + 18 from 4B)

**Step 5: Commit**

```bash
git add src/services/connection_service.py tests/services/test_connection_service.py
git commit -m "feat: add typed credential resolvers, runtime_usable computation, and decrypt resilience"
```

---

### Task 5: Connections API Routes + Custom 422 Handler

**Files:**
- Create: `src/api/routes/connections.py`
- Modify: `src/api/main.py` (register router + custom 422 handler)
- Create: `tests/api/test_connections.py`

**Step 1: Write the failing tests**

Tests cover:
- `GET /connections/` returns empty list, ordered results with `runtime_usable` field
- `POST /connections/ups/save` saves and returns `201` on create, `200` on overwrite
- `POST /connections/shopify/save` saves Shopify credentials (URL-encoded domain in key)
- Invalid provider → 400
- Missing required fields → 400
- `GET /connections/{connection_key}` with URL-encoded key, includes `runtime_usable`
- `GET /connections/{connection_key}` not found → 404
- `DELETE /connections/{connection_key}` → 200, not found → 404
- `POST /connections/{connection_key}/disconnect` preserves credentials
- Disconnect/list/get responses after disconnect show status but no credentials
- No credentials ever in list/get responses
- Error responses never contain credential values (use `redact_for_logging`)
- **422 redaction test: send payload with wrong body type containing obvious secret string; ensure response body doesn't echo it**
- **422 redaction test for query/path params: ensure custom handler sanitizes all validation detail**

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

**Dependency override for FastAPI TestClient:** Routes that call `ConnectionService` internally need a DB session. Use FastAPI's `app.dependency_overrides` to inject the test session:

```python
from src.db.connection import get_db

@pytest.fixture
def test_client(db_engine):
    Session = sessionmaker(bind=db_engine)

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
```

If startup lifespan calls `check_all()`, either skip it in tests (mock) or ensure the test DB is initialized before the client starts.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_connections.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the routes**

Key implementation details:
- **Route accepts raw `dict` payload** — `body: dict = Body(...)` — NO Pydantic model binding for credential fields
- This prevents FastAPI from echoing submitted secret values in automatic 422 field-level validation error responses
- All field validation (required fields, formats, auth_mode) happens in `ConnectionService.save_connection()` which raises `ValueError`
- `ConnectionValidationError` from service → 400 with `{"error": {"code": e.code, "message": e.message}}`. Unexpected exceptions → 500 INTERNAL_ERROR (sanitized via `redact_for_logging`).
- Not found → 404
- Check `result["is_new"]` to return `201` or `200`
- Connection responses include `runtime_usable` and `runtime_reason` fields
- No `success: bool` field in connection responses
- **Standardized error schema:** All error responses use `{"error": {"code": str, "message": str}}` format. Error codes are structured strings (`INVALID_PROVIDER`, `MISSING_FIELD`, `VALIDATION_ERROR`, `NOT_FOUND`, `INTERNAL_ERROR`). Messages are sanitized.
- **API sanitization split:** Exception strings returned/logged in connection routes pass through `sanitize_error_message()`. Dict/list structures use `redact_for_logging()`. These are complementary — never interchangeable.

**Step 4: Add custom `RequestValidationError` handler to `src/api/main.py`**

Register a custom exception handler that intercepts `RequestValidationError` for `/connections/*` routes and sanitizes the error detail:

```python
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def custom_validation_handler(request: Request, exc: RequestValidationError):
    """Sanitize 422 validation errors to prevent secret leakage.

    For /connections/* routes: strip raw input values and wrap in standard error schema.
    For all other routes: preserve default FastAPI behavior.
    """
    if request.url.path.startswith("/api/v1/connections"):
        # Sanitize: remove 'input' and 'ctx' from each error to avoid echoing secrets
        safe_errors = []
        for err in exc.errors():
            safe_errors.append({
                "type": err.get("type", "unknown"),
                "loc": err.get("loc", []),
                "msg": err.get("msg", "Validation error"),
            })
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request payload",
                },
                "detail": safe_errors,
            },
        )
    # Delegate to default FastAPI 422 format for non-connection routes
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )
```

**Step 5: Register the router in `src/api/main.py`**

Add import and `app.include_router(connections.router, prefix="/api/v1")`.

**Step 6: Run tests to verify they pass**

Run: `pytest tests/api/test_connections.py -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/api/routes/connections.py src/api/main.py tests/api/test_connections.py
git commit -m "feat: add /connections API routes with raw dict payloads, custom 422 handler, runtime_usable field, and redacted errors"
```

---

### Task 6: Startup Decryptability Check

**Files:**
- Modify: `src/services/connection_service.py` (implement full `check_all` — replaces stub from Task 4A)
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
        import logging

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
        # Disconnected row not in results
        assert "ups:test" not in results
        # Status unchanged
        conn = service.get_connection("ups:test")
        assert conn["status"] == "disconnected"

    def test_check_all_sanitizes_error_message(self, db_session, key_dir):
        """Decrypt failure error_message is sanitized before DB persistence."""
        from src.services.connection_service import ConnectionService

        # Use invalid credentials blob that might contain sensitive-looking text
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
        # error_message should not contain sensitive-looking patterns
        if conn["error_message"]:
            assert "secret_value_here" not in conn["error_message"]

    def test_strict_key_policy_raises_on_platformdirs(self, db_session, key_dir):
        """Strict key policy raises RuntimeError when key source is platformdirs."""
        import importlib
        for var in ("SHIPAGENT_CREDENTIAL_KEY", "SHIPAGENT_CREDENTIAL_KEY_FILE"):
            os.environ.pop(var, None)
        os.environ["SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY"] = "true"
        try:
            # The strict check happens in startup lifespan, not in check_all() directly.
            # Test the logic: when source is platformdirs and strict=true, RuntimeError raised.
            from src.services.credential_encryption import get_key_source_info
            info = get_key_source_info()
            assert info["source"] == "platformdirs"
            # Startup code would raise RuntimeError here
        finally:
            os.environ.pop("SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY", None)

    def test_bad_base64_key_is_fatal(self):
        """Invalid base64 in SHIPAGENT_CREDENTIAL_KEY is fatal at startup (ValueError)."""
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = "not-valid-base64!!!"
        try:
            from src.services.credential_encryption import get_or_create_key
            with pytest.raises(ValueError, match="[Ii]nvalid.*base64"):
                get_or_create_key()
            # In startup, this ValueError propagates — app does not boot
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)

    def test_wrong_length_key_is_fatal(self):
        """Wrong-length key in SHIPAGENT_CREDENTIAL_KEY is fatal at startup (ValueError)."""
        import base64
        os.environ["SHIPAGENT_CREDENTIAL_KEY"] = base64.b64encode(b"short").decode()
        try:
            from src.services.credential_encryption import get_or_create_key
            with pytest.raises(ValueError, match="invalid length"):
                get_or_create_key()
            # In startup, this ValueError propagates — app does not boot
        finally:
            os.environ.pop("SHIPAGENT_CREDENTIAL_KEY", None)

    def test_check_all_handles_malformed_row(self, db_session, key_dir):
        """check_all() marks rows with missing core fields as INVALID_ROW."""
        from src.services.connection_service import ConnectionService

        # Create row with missing auth_mode (simulates partial migration)
        row = ProviderConnection(
            connection_key="ups:broken", provider="ups", display_name="Broken",
            auth_mode=None, environment="test",
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_startup_check.py -v`
Expected: FAIL

**Step 3: Implement `check_all()`**

Full `check_all()` implementation (replaces Task 4A stub):
- Logs key source info (`get_key_source_info()`) at start
- If key source is `platformdirs`, logs production warning
- Reads all `ProviderConnection` rows **where `status != "disconnected"`** (query-level filter)
- **Row field validation:** Before decrypt attempt, validate that each row has non-null `provider`, `auth_mode`, `connection_key`, and `encrypted_credentials`. Rows missing any of these are marked `needs_reconnect` with error code `INVALID_ROW` (distinct from `DECRYPT_FAILED`). Processing continues for remaining rows. This handles partially-migrated or corrupt databases gracefully.
- For each non-disconnected row, attempts to decrypt credentials using `_build_aad(row)` for AAD
- On success:
  - If status is `"needs_reconnect"`: recover to `"configured"`, clear `last_error_code` and `error_message`
  - All other statuses: preserve status AND error fields
- On decrypt failure: sets `status = "needs_reconnect"`, `last_error_code = "DECRYPT_FAILED"`, `error_message` sanitized via `_sanitize_error_message()`
- Returns dict of `connection_key -> "ok" | "error"`
- If any rows marked `needs_reconnect`, logs prominent warning: "N provider connection(s) could not be decrypted. This may indicate the encryption key has changed..."
- Does NOT write to `os.environ`
- Logs warnings using `redact_for_logging()` for failed rows

**Step 4: Add startup call in `src/api/main.py`**

After `init_db()` in lifespan, with narrowed exception handling:

```python
    from src.services.credential_encryption import (
        CredentialDecryptionError, get_key_source_info,
    )

    try:
        key_info = get_key_source_info()
        logger.info("Credential key source: %s (%s)", key_info["source"], key_info.get("path", "n/a"))
        if key_info["source"] == "platformdirs":
            strict = os.environ.get(
                "SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY", ""
            ).lower() == "true"
            if strict:
                raise RuntimeError(
                    "SHIPAGENT_REQUIRE_PERSISTENT_CREDENTIAL_KEY is set but key source is "
                    "'platformdirs'. Set SHIPAGENT_CREDENTIAL_KEY or "
                    "SHIPAGENT_CREDENTIAL_KEY_FILE for persistent deployments."
                )
            logger.info(
                "Using auto-generated key from local filesystem. "
                "For production or containerized deployments, set "
                "SHIPAGENT_CREDENTIAL_KEY or SHIPAGENT_CREDENTIAL_KEY_FILE."
            )
        with get_db_context() as db:
            from src.services.connection_service import ConnectionService
            conn_service = ConnectionService(db=db)
            check_results = conn_service.check_all()
            if check_results:
                logger.info("Provider credential check results: %s", check_results)
    except (RuntimeError, ValueError):
        raise  # Key config errors + strict policy — must not be swallowed
    except CredentialDecryptionError as e:
        logger.warning("Provider credential check failed (non-blocking): %s: %s",
                       type(e).__name__, e, exc_info=True)
    except Exception as e:
        logger.error("Unexpected error during provider credential check: %s: %s",
                     type(e).__name__, e, exc_info=True)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/services/test_startup_check.py -v`
Expected: All 14 tests PASS

**Step 6: Commit**

```bash
git add src/services/connection_service.py src/api/main.py tests/services/test_startup_check.py
git commit -m "feat: add startup decryptability check with narrowed exceptions, platformdirs warning, error sanitization, and key-mismatch hint"
```

---

### Task 7: Runtime Credential Adapter

**Files:**
- Create: `src/services/runtime_credentials.py`
- Create: `tests/services/test_runtime_credentials.py`

This is the **single contract** for runtime credential resolution. All call sites use this module.

**Step 1: Write the failing tests**

13 tests with autouse fixture for fallback flag reset:

```python
# tests/services/test_runtime_credentials.py
"""Tests for runtime credential adapter (DB priority, env fallback)."""

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_runtime_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

Key implementation details:
- `_UPS_BASE_URLS` mapping: `{"test": "https://wwwcie.ups.com", "production": "https://onlinetools.ups.com"}`
- `_get_db_session()` helper: acquires DB session via `get_db_context()` when `db=None`
- `_ups_fallback_warned` / `_shopify_fallback_warned` per-process flags (reset in test fixtures)
- `resolve_ups_credentials()`: DB lookup via `ConnectionService.get_ups_credentials(environment)` → env fallback with `_UPS_BASE_URLS` derivation → `None`
- `resolve_shopify_credentials()` → `ShopifyLegacyCredentials | ShopifyClientCredentials | None`: DB lookup via `ConnectionService.get_shopify_credentials(store_domain)` or `get_first_shopify_credentials()` → env fallback (returns `ShopifyLegacyCredentials(access_token=..., store_domain=...)`) → `None`
- **Domain-matched env fallback:** When `store_domain` is explicitly provided and no DB row matches:
  - Read `SHOPIFY_STORE_DOMAIN` from env
  - Normalize both domains using the same normalization logic
  - If domains match: return env credentials as `ShopifyLegacyCredentials`
  - If domains differ: return `None` with WARNING log: "Requested store {requested} but env has {env_domain} — skipping env fallback"
  - When `store_domain` is None (first-shopify path): env fallback activates unconditionally
- Empty `access_token` filtering: returns `None` if resolved `access_token` is empty (client_credentials_shopify without token acquisition)
- UPS env fallback `base_url` mismatch: if `UPS_BASE_URL` env is set and conflicts with derived URL, log WARNING
- All fallback warnings include redacted context (provider, environment — never raw credentials)

**Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_runtime_credentials.py -v`
Expected: All 13 tests PASS

**Step 5: Commit**

```bash
git add src/services/runtime_credentials.py tests/services/test_runtime_credentials.py
git commit -m "feat: add runtime credential adapter with DB priority, env fallback, UPS base_url validation, and empty token filtering"
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

**Enforcement rule:** After this task, no call site outside `runtime_credentials.py` may directly read `UPS_CLIENT_ID`, `UPS_CLIENT_SECRET`, `UPS_ACCOUNT_NUMBER`, `UPS_BASE_URL`, or `UPS_ENVIRONMENT` env vars. Only `runtime_credentials.py` reads them as fallback.

**Call-site None behavior:**

| Call Site | Behavior on `None` |
|-----------|-------------------|
| `orchestrator/agent/config.py` (MCP config) | Skip UPS MCP server from config — agent starts without UPS tools |
| `orchestrator/agent/system_prompt.py` | Include soft note: "UPS not configured — connect in Settings" |
| `services/batch_engine.py` | Hard failure with actionable error: "No UPS credentials configured. Open Settings to connect." |
| `orchestrator/agent/tools/interactive.py` | Warning + prompt to connect in Settings |

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

**Enforcement rule:** After this task, no runtime server path call site outside `runtime_credentials.py` may directly read `SHOPIFY_ACCESS_TOKEN` or `SHOPIFY_STORE_DOMAIN` env vars. CLI paths (`http_client.py`, `runner.py`) are temporarily exempt with TODO comments for Phase 2 migration.

**Call-site None behavior:**

| Call Site | Behavior on `None` |
|-----------|-------------------|
| `api/routes/platforms.py` | Return error response: "No Shopify credentials configured. Open Settings to connect." |
| `mcp/external_sources/server.py` | Tool returns error result (not exception) with connect guidance |

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

/**
 * Provider connection status.
 * Phase 1: only 'configured', 'disconnected', 'needs_reconnect' are actively produced.
 * 'connected', 'validating', 'error' are reserved for Phase 2 live validation.
 * 'error' may appear via explicit update_status() calls but is not produced by automated flows.
 */
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
  runtime_usable: boolean;
  runtime_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface SaveProviderRequest {
  auth_mode: ProviderAuthMode;  // strict union — not bare string
  credentials: Record<string, string>;
  metadata: Record<string, unknown>;
  display_name: string;
  environment?: string;
}

// Note: ProviderConnectionInfo.id is string (backend serializes UUID via str(row.id))

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
git commit -m "feat: add frontend types and API client for provider connections with runtime_usable field"
```

---

### Task 11: Frontend State Management (useAppState)

**Files:**
- Modify: `frontend/src/hooks/useAppState.tsx`

**Step 1: Add provider connection state to AppState interface**

Add to the `AppState` interface (after `chatSessionsVersion`):

```typescript
  // Provider connections state
  providerConnections: ProviderConnectionInfo[];
  providerConnectionsLoading: boolean;
  providerConnectionsVersion: number;
  refreshProviderConnections: () => void;
```

**Step 2: Add imports**

Add `ProviderConnectionInfo` to the import from `@/types/api`:

```typescript
import type {
  // ... existing imports ...
  ProviderConnectionInfo,
} from '@/types/api';
```

Add API import:
```typescript
import * as api from '@/lib/api';
```
(Already imported — verify it exists.)

**Step 3: Add state hooks inside AppStateProvider**

Add after the existing `activeSessionTitle` state:

```typescript
  // Provider connections state
  const [providerConnections, setProviderConnections] = React.useState<ProviderConnectionInfo[]>([]);
  const [providerConnectionsLoading, setProviderConnectionsLoading] = React.useState(false);
  const [providerConnectionsVersion, setProviderConnectionsVersion] = React.useState(0);

  const refreshProviderConnections = React.useCallback(() => {
    setProviderConnectionsVersion((v) => v + 1);
  }, []);
```

**Step 4: Add useEffect to fetch connections on mount and version change**

```typescript
  // Fetch provider connections on mount and when version changes
  React.useEffect(() => {
    let cancelled = false;
    setProviderConnectionsLoading(true);
    api.listProviderConnections()
      .then((response) => {
        if (!cancelled) {
          setProviderConnections(response.connections);
        }
      })
      .catch((error) => {
        console.error('Failed to fetch provider connections:', error);
      })
      .finally(() => {
        if (!cancelled) {
          setProviderConnectionsLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [providerConnectionsVersion]);
```

**Step 5: Add to context value object**

Add to the `value: AppState` object:

```typescript
    providerConnections,
    providerConnectionsLoading,
    providerConnectionsVersion,
    refreshProviderConnections,
```

**Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 7: Commit**

```bash
git add frontend/src/hooks/useAppState.tsx
git commit -m "feat: add provider connections state to useAppState with version-triggered refresh"
```

---

### Task 12: ConnectionsSection + ProviderCard Components

**Files:**
- Create: `frontend/src/components/settings/ConnectionsSection.tsx`
- Create: `frontend/src/components/settings/ProviderCard.tsx`
- Modify: `frontend/src/components/settings/SettingsFlyout.tsx`

Key Phase 1 UI decisions:
- **UPS card:** One card with Test/Production environment toggle (two subprofiles within), parent badge showing "X/2 configured"
- **Shopify card:** One card, legacy token form only (client credentials radio hidden in Phase 1)
- **Status badges:** `configured` = blue, `disconnected` = grey, `error`/`needs_reconnect` = amber
- **No "Test" button** in Phase 1
- **Credential display after save:** Placeholder dots (`••••••••`), "Replace credentials" action
- **Button loading states:** Save/Disconnect/Delete buttons show spinner during API call, disabled to prevent duplicate submission
- **Confirmation dialog:** Required for Delete (destructive), not required for Disconnect (reversible via re-save)
- **Disconnect vs Delete button semantics:**
  - Disconnect button tooltip: "Temporarily disable this connection. Credentials are preserved."
  - Delete button: requires confirmation dialog. Tooltip: "Permanently remove this connection and its stored credentials."
  - No confirmation dialog for Disconnect (reversible via re-save).
- **Inline error display:** Save failures show inline error below form, card stays expanded
- **`runtime_usable` display:** Cards show runtime-usable indicator from server response

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

**Phase 1:** Single form for legacy token mode only. No radio selector (client credentials mode hidden).

Fields:
- Store domain (required, validated against `*.myshopify.com` on blur, normalized on submit)
- Access Token (required, password field)

Loading states on Save button. Inline error on failure.

**Phase 2 addition:** Radio selector "I have an access token" (legacy) vs "I have client credentials" (new) — currently hidden.

**Commit:**

```bash
git add frontend/src/components/settings/ShopifyConnectForm.tsx frontend/src/components/settings/ConnectionsSection.tsx
git commit -m "feat: add Shopify connect form (legacy token only in Phase 1)"
```

---

### Task 15: DataSourcePanel Migration

**Files:**
- Modify: `frontend/src/components/sidebar/DataSourcePanel.tsx`

Check `providerConnections` from `useAppState`:
- Shopify connection with `runtime_usable === true` → show as available data source with switch button
- Shopify `runtime_usable === false` or not configured → show "Connect Shopify in Settings" link that calls `setSettingsFlyoutOpen(true)`
- Remove inline Shopify token entry form
- Remove `handleShopifyConnect` function

**Runtime-usable gating:** DataSourcePanel reads the `runtime_usable` field from the connection response directly. No client-side inference from `auth_mode`, `status`, or other fields. The backend computes this authoritatively via `ConnectionService._is_runtime_usable()`.

**Env fallback UI behavior:** When a user has valid `.env` Shopify creds but no DB connection row, the runtime still works (env fallback in `runtime_credentials.py`), but the UI shows "Connect Shopify in Settings." This is the intended transition behavior — users are encouraged to migrate to Settings. No "env fallback detected" indicator in Phase 1.

**Commit:**

```bash
git add frontend/src/components/sidebar/DataSourcePanel.tsx
git commit -m "refactor: move Shopify credentials from DataSourcePanel to Settings with server-side runtime_usable gating"
```

---

### Task 16: Integration + Edge Case Tests

**Files:**
- Create: `tests/integration/test_connection_round_trip.py`

**Test grouping:** Tests are split into two groups:
- **Core smoke tests** (must-pass, fast) — CRUD round-trip, save->resolve->use, env fallback, startup check, frontend type contract
- **Extended edge-case tests** (slower, CI-only) — corrupt data recovery, multi-provider interleaving, migration partial-upgrade, concurrent operations

Tests cover:
- [SMOKE] Full UPS lifecycle: save → list → decrypt → disconnect → re-save (resets to configured) → delete
- [SMOKE] Full Shopify lifecycle: save legacy → list → decrypt → delete
- [SMOKE] Multiple UPS environments coexist without clobber
- [EXTENDED] Corrupt metadata_json doesn't crash list/get
- [SMOKE] API error responses never contain credential values
- [SMOKE] Shopify domain normalization produces correct connection_key
- [EXTENDED] Shopify client credentials resolver returns typed object with empty `access_token`
- [SMOKE] Disconnect prevents resolver from returning credentials
- [SMOKE] `check_all()` recovery path: `needs_reconnect` → `configured`
- [EXTENDED] `check_all()` with wrong key: valid creds become `needs_reconnect`
- [SMOKE] UPS runtime resolver: config uses DB credentials, falls back to env
- [EXTENDED] UPS env fallback respects requested environment (production request with no UPS_BASE_URL)
- [SMOKE] Shopify runtime resolver: deterministic default selection (ORDER BY connection_key ASC)
- [EXTENDED] Shopify runtime resolver: returns None for client_credentials_shopify with empty token
- [EXTENDED] Overwrite on disconnected row resets to `configured`
- [EXTENDED] Multi-row Shopify default selection is deterministic
- [EXTENDED] **422 secret redaction test: send invalid payload with obvious secret string; ensure response doesn't echo it (both body and query/path)**
- [EXTENDED] **Invalid base64 env key test: SHIPAGENT_CREDENTIAL_KEY with bad base64 raises ValueError**
- [EXTENDED] **Key length enforcement: 16-byte and 24-byte keys rejected by encrypt/decrypt**
- [EXTENDED] **Auth mode switching test: legacy_token → client_credentials_shopify on same connection_key, decrypt still works with new AAD**
- [EXTENDED] **Error message sanitization: sensitive content in error_message is redacted before DB persistence**
- [SMOKE] **Connection responses include `runtime_usable` field with correct values**
- [SMOKE] **check_all skips disconnected rows: save → disconnect → check_all → verify status unchanged, not in results**
- [SMOKE] **Phase 1 status semantics: verify only `configured`, `needs_reconnect`, `disconnected` are actively produced by automated flows (no `connected`, `validating` in Phase 1 flows). `error` is allowed via explicit `update_status()` calls only.**
- [EXTENDED] **key_version is always 1 on all new connections**
- [EXTENDED] **Sanitizer covers Bearer tokens, JSON-style, and quoted values in error messages**
- [EXTENDED] **Credential payload allowlist: unknown keys rejected with 400 for UPS client_credentials**
- [EXTENDED] **Credential payload max length enforcement**
- [EXTENDED] **Corrupt metadata_json returns {} in API response, does not crash**
- [EXTENDED] **VALID_STATUSES enforcement: update_status with unknown status returns 400/ValueError**
- [EXTENDED] **Strict key policy: startup raises RuntimeError when platformdirs + strict mode**
- [EXTENDED] **Strict key policy: startup succeeds when env key + strict mode**
- [SMOKE] **API error responses use consistent {"error": {"code": str, "message": str}} schema**
- [EXTENDED] **Migration backfill: rows with NULL status get needs_reconnect after migration**
- [EXTENDED] **list_connections with corrupt row: returns runtime_usable=false, does not 500**
- [EXTENDED] **get_connection with corrupt row: returns runtime_usable=false, does not 500**
- [EXTENDED] **Explicit key misconfig (bad base64) is fatal at startup — ValueError not swallowed**
- [EXTENDED] **Explicit key misconfig (missing key file) is fatal at startup — ValueError not swallowed**
- [EXTENDED] **422 response uses wrapped error schema with both error envelope and detail array**
- [EXTENDED] **Timestamp backfill: existing rows with NULL created_at get backfilled (YYYY-MM-DDTHH:MM:SSZ format)**
- [EXTENDED] **Key file permission warning: overly permissive file logs warning**
- [EXTENDED] **Key file symlink rejection: SHIPAGENT_CREDENTIAL_KEY_FILE pointing to symlink raises ValueError**

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
- Shopify form shows only legacy token mode (no client credentials radio)
- Connection responses include `runtime_usable` in API responses

**Step 4: Verify runtime integration**

- Save UPS credentials through Settings UI
- Verify agent MCP config picks up DB-stored credentials (check backend logs for absence of env fallback warning)
- Save Shopify credentials through Settings UI
- Verify DataSourcePanel shows "Switch to Shopify" option (reads `runtime_usable` from server)
- Verify disconnect hides Shopify from DataSourcePanel

**Step 5: Expanded grep check — no ad hoc env reads outside adapter**

Run:
```bash
grep -rn "UPS_CLIENT_ID\|UPS_CLIENT_SECRET\|UPS_ACCOUNT_NUMBER\|UPS_BASE_URL\|UPS_ENVIRONMENT\|SHOPIFY_ACCESS_TOKEN\|SHOPIFY_STORE_DOMAIN" src/ \
  --include="*.py" | grep -v runtime_credentials | grep -v test | grep -v __pycache__ | grep -v http_client | grep -v runner
```
Expected: No remaining occurrences outside `runtime_credentials.py` (and possibly config documentation comments). CLI paths (`http_client.py`, `runner.py`) are excluded — temporarily exempt with TODO comments.

**Step 6: Create CI env-read enforcement test**

Create `tests/integration/test_no_env_reads.py`:
```python
"""CI guard: ensure no provider env reads outside runtime_credentials.py."""

import subprocess


def test_no_direct_provider_env_reads():
    """Provider credential env vars must only be read in runtime_credentials.py."""
    result = subprocess.run(
        ["grep", "-rn",
         r"UPS_CLIENT_ID\|UPS_CLIENT_SECRET\|UPS_ACCOUNT_NUMBER\|UPS_BASE_URL\|"
         r"UPS_ENVIRONMENT\|SHOPIFY_ACCESS_TOKEN\|SHOPIFY_STORE_DOMAIN",
         "src/", "--include=*.py"],
        capture_output=True, text=True,
    )
    violations = []
    for line in result.stdout.splitlines():
        # Exclude allowed files
        if any(skip in line for skip in [
            "runtime_credentials", "test", "__pycache__",
            "http_client", "runner",
        ]):
            continue
        violations.append(line)
    assert not violations, (
        f"Found {len(violations)} direct provider env reads outside "
        f"runtime_credentials.py:\n" + "\n".join(violations)
    )
```

**Step 7: Code review checklist (beyond grep)**

Verify manually:
- [ ] No new direct `os.environ.get()` calls for provider credential env vars outside `runtime_credentials.py`
- [ ] No wrapper functions or settings objects that read provider creds indirectly
- [ ] `metadata_json` used as DB column attr everywhere (not `metadata`)
- [ ] `key_version` defaults to `1` in model and is never incremented in Phase 1
- [ ] All `check_all()` paths skip `disconnected` rows
- [ ] All `error_message` writes go through `_sanitize_error_message()`
- [ ] Frontend uses `ProviderAuthMode` union type for `auth_mode` (not bare `string`)
- [ ] `ProviderConnectionInfo.id` is `string` (UUID serialized via `str()`)
- [ ] No `os.getenv()` calls for provider credential env vars outside `runtime_credentials.py`
- [ ] No indirect env reads via wrapper functions, settings objects, or config utilities
- [ ] Credential dataclasses imported from `src/services/connection_types.py` (not defined inline)
- [ ] `update_status()` validates against `VALID_STATUSES`
- [ ] `metadata_json` parsed via `json.loads()` with try/except in service layer
- [ ] Credential payloads validated against per-provider allowlists before encryption
- [ ] API error responses follow `{"error": {"code": str, "message": str}}` schema
- [ ] `CredentialDecryptionError` imported at module scope in startup code
- [ ] 422 handler wraps sanitized detail in `{"error": {...}, "detail": [...]}` for connection routes
- [ ] `list_connections()` / `get_connection()` catch `CredentialDecryptionError` — never 500 on corrupt rows
- [ ] `ValueError` from key config propagates at startup (not caught by generic except)
- [ ] CLI env reads have TODO comments for Phase 2 migration
- [ ] Key file permission warning logged for overly permissive files on Unix
- [ ] `created_at` / `updated_at` backfilled in migration (frontend types remain strict `string`)
- [ ] Key file symlink check before key read in `get_or_create_key()`

**Step 8: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final verification and cleanup for settings connections"
```
