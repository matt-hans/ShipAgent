import pytest

from src.control_plane.relay.protocol import (
    RelayVersionMetadata,
    build_handshake_claims,
    verify_handshake_signature,
)
from src.services.relay_key_service import RelayKeyService


class InMemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_generate_or_load_keypair_reloads_stored_keypair() -> None:
    store = InMemoryStore()
    service = RelayKeyService(store)

    generated = service.generate_or_load_keypair()
    reloaded = RelayKeyService(store).load_keypair()

    assert reloaded is not None
    assert reloaded.public_key_pem == generated.public_key_pem
    assert reloaded.fingerprint == generated.fingerprint
    assert generated.fingerprint.startswith("sha256:")


def test_stage_keypair_rotation_does_not_replace_active_keypair() -> None:
    store = InMemoryStore()
    service = RelayKeyService(store)
    original = service.generate_or_load_keypair()

    staged = service.stage_keypair_rotation()
    reloaded = service.load_keypair()
    reloaded_staged = service.load_staged_keypair_rotation()

    assert reloaded is not None
    assert reloaded.public_key_pem == original.public_key_pem
    assert reloaded.fingerprint == original.fingerprint
    assert reloaded_staged is not None
    assert reloaded_staged.public_key_pem == staged.public_key_pem
    assert reloaded_staged.fingerprint == staged.fingerprint
    assert staged.fingerprint != original.fingerprint


def test_rotate_keypair_alias_stages_key_without_replacing_active_keypair() -> None:
    service = RelayKeyService(InMemoryStore())
    original = service.generate_or_load_keypair()

    staged = service.rotate_keypair()
    reloaded = service.load_keypair()

    assert reloaded is not None
    assert reloaded.public_key_pem == original.public_key_pem
    assert service.load_staged_keypair_rotation() == staged


def test_commit_keypair_rotation_promotes_staged_keypair() -> None:
    service = RelayKeyService(InMemoryStore())
    original = service.generate_or_load_keypair()
    staged = service.stage_keypair_rotation()

    committed = service.commit_staged_keypair_rotation()
    reloaded = service.load_keypair()

    assert committed.public_key_pem == staged.public_key_pem
    assert reloaded is not None
    assert reloaded.public_key_pem == staged.public_key_pem
    assert reloaded.fingerprint != original.fingerprint
    assert service.load_staged_keypair_rotation() is None


def test_discard_keypair_rotation_keeps_active_keypair() -> None:
    service = RelayKeyService(InMemoryStore())
    original = service.generate_or_load_keypair()

    staged = service.stage_keypair_rotation()
    service.discard_staged_keypair_rotation()
    reloaded = service.load_keypair()

    assert staged.fingerprint != original.fingerprint
    assert reloaded is not None
    assert reloaded.public_key_pem == original.public_key_pem
    assert service.load_staged_keypair_rotation() is None


def test_commit_keypair_rotation_requires_staged_keypair() -> None:
    service = RelayKeyService(InMemoryStore())
    service.generate_or_load_keypair()

    with pytest.raises(ValueError, match="no staged relay key rotation"):
        service.commit_staged_keypair_rotation()


def test_registration_payload_excludes_private_key_material() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()

    payload = service.public_registration_payload(device_name="Warehouse Mac")

    assert payload == {
        "device_name": "Warehouse Mac",
        "public_key_pem": keypair.public_key_pem,
    }
    assert "account_id" not in payload
    assert "fingerprint" not in payload
    assert "private_key" not in payload
    assert "private_key_pem" not in payload


def test_keypair_repr_excludes_private_key_material() -> None:
    keypair = RelayKeyService(InMemoryStore()).generate_or_load_keypair()

    rendered = repr(keypair)

    assert "private_key_pem" not in rendered
    assert keypair.private_key_pem not in rendered


def test_sign_handshake_claims_can_be_verified_with_public_key() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()
    claims = build_handshake_claims(
        device_id="device-1",
        account_id="acct-1",
        relay_session_id="session-1",
        nonce="nonce-1",
        version=RelayVersionMetadata(
            shipagent_core_version="1.0.0",
            registry_contract_version="registry-v1",
            ups_boundary_contract_version="ups-v1",
        ),
    )

    signed = service.sign_handshake_claims(claims)

    assert signed.claims == claims
    verify_handshake_signature(signed, keypair.public_key_pem)
