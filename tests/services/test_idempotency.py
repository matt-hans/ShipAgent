"""Tests for idempotency key generation and validation."""

from src.services.idempotency import generate_idempotency_key


class TestIdempotencyKey:
    """Verify deterministic idempotency key generation."""

    def test_generate_key_format(self) -> None:
        """Key is '{job_id}:{row_number}:{row_checksum}'."""
        key = generate_idempotency_key("job-123", 5, "abc123hash")
        assert key == "job-123:5:abc123hash"

    def test_same_inputs_produce_same_key(self) -> None:
        """Deterministic: identical inputs always produce identical key."""
        k1 = generate_idempotency_key("j1", 1, "hash1")
        k2 = generate_idempotency_key("j1", 1, "hash1")
        assert k1 == k2

    def test_different_inputs_produce_different_keys(self) -> None:
        """Different row_number produces different key."""
        k1 = generate_idempotency_key("j1", 1, "hash1")
        k2 = generate_idempotency_key("j1", 2, "hash1")
        assert k1 != k2

    def test_different_checksum_produces_different_key(self) -> None:
        """Different row_checksum produces different key."""
        k1 = generate_idempotency_key("j1", 1, "hash1")
        k2 = generate_idempotency_key("j1", 1, "hash2")
        assert k1 != k2

    def test_key_fits_ups_transaction_reference(self) -> None:
        """UPS TransactionReference.CustomerContext max is 512 chars."""
        key = generate_idempotency_key("a" * 36, 99999, "b" * 64)
        assert len(key) <= 512
