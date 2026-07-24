from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.control_plane.relay.protocol import (
    RelayHandshakeClaims,
    RelayHandshakeToken,
    encode_handshake_jwt,
    relay_public_key_fingerprint,
)
from src.services.keyring_store import KeyringStore


class RelayKeyStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class RelayKeyPair:
    public_key_pem: str
    fingerprint: str
    private_key_pem: str = field(repr=False)


class RelayKeyService:
    def __init__(
        self,
        store: RelayKeyStore | None = None,
        key_name: str = "SHIPAGENT_RELAY_DEVICE_PRIVATE_KEY",
    ) -> None:
        self._store = store if store is not None else KeyringStore()
        self._key_name = key_name
        self._staged_key_name = f"{key_name}_PENDING_ROTATION"

    def load_keypair(self) -> RelayKeyPair | None:
        return self._load_keypair(self._key_name)

    def load_staged_keypair_rotation(self) -> RelayKeyPair | None:
        return self._load_keypair(self._staged_key_name)

    def _load_keypair(self, key_name: str) -> RelayKeyPair | None:
        private_key_pem = self._store.get(key_name)
        if private_key_pem is None:
            return None
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("stored relay key is not an Ed25519 private key")
        return self._keypair_from_private_key(private_key)

    def generate_or_load_keypair(self) -> RelayKeyPair:
        existing = self.load_keypair()
        if existing is not None:
            return existing
        private_key = Ed25519PrivateKey.generate()
        keypair = self._keypair_from_private_key(private_key)
        self._store.set(self._key_name, keypair.private_key_pem)
        return keypair

    def stage_keypair_rotation(self) -> RelayKeyPair:
        """Generate a pending key without replacing the active signing key."""

        private_key = Ed25519PrivateKey.generate()
        keypair = self._keypair_from_private_key(private_key)
        self._store.set(self._staged_key_name, keypair.private_key_pem)
        return keypair

    def rotate_keypair(self) -> RelayKeyPair:
        return self.stage_keypair_rotation()

    def commit_staged_keypair_rotation(self) -> RelayKeyPair:
        staged = self.load_staged_keypair_rotation()
        if staged is None:
            raise ValueError("no staged relay key rotation is available")
        self._store.set(self._key_name, staged.private_key_pem)
        self._store.delete(self._staged_key_name)
        return staged

    def discard_staged_keypair_rotation(self) -> None:
        self._store.delete(self._staged_key_name)

    def public_registration_payload(self, device_name: str) -> dict[str, str]:
        keypair = self.generate_or_load_keypair()
        return {
            "device_name": device_name,
            "public_key_pem": keypair.public_key_pem,
        }

    def sign_handshake_jwt(self, claims: RelayHandshakeClaims) -> RelayHandshakeToken:
        private_key_pem = self._store.get(self._key_name)
        if private_key_pem is None:
            raise ValueError("relay private key is not available")
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("stored relay key is not an Ed25519 private key")
        return encode_handshake_jwt(claims, private_key_pem)

    def sign_handshake_claims(
        self, claims: RelayHandshakeClaims
    ) -> RelayHandshakeToken:
        return self.sign_handshake_jwt(claims)

    def _keypair_from_private_key(self, private_key: Ed25519PrivateKey) -> RelayKeyPair:
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("utf-8")
        )
        return RelayKeyPair(
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            fingerprint=relay_public_key_fingerprint(public_key_pem),
        )
