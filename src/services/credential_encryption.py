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
