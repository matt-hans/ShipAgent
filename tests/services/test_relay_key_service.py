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

    assert reloaded == generated
    assert generated.fingerprint.startswith("sha256:")


def test_rotate_keypair_replaces_stored_keypair() -> None:
    store = InMemoryStore()
    service = RelayKeyService(store)
    original = service.generate_or_load_keypair()

    rotated = service.rotate_keypair()
    reloaded = service.load_keypair()

    assert rotated == reloaded
    assert rotated.fingerprint != original.fingerprint


def test_registration_payload_excludes_private_key_material() -> None:
    service = RelayKeyService(InMemoryStore())
    keypair = service.generate_or_load_keypair()

    payload = service.public_registration_payload(
        account_id="account-123",
        device_name="Warehouse Mac",
    )

    assert payload == {
        "account_id": "account-123",
        "device_name": "Warehouse Mac",
        "public_key_pem": keypair.public_key_pem,
        "fingerprint": keypair.fingerprint,
    }
    assert "private_key" not in payload
    assert "private_key_pem" not in payload
