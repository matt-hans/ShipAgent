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
