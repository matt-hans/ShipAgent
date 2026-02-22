"""Tests for pickup confirmation token infrastructure (H-2, CWE-347).

Verifies that HMAC-signed confirmation tokens are issued by rate_pickup
and validated by schedule_pickup and cancel_pickup, preventing the LLM
from bypassing the confirmation step.
"""

import time

import pytest

from src.orchestrator.agent.tools.pickup import (
    _hash_pickup_details,
    _issue_pickup_token,
    _validate_pickup_token,
)


class TestPickupConfirmationTokens:
    """Tests for HMAC-signed pickup confirmation tokens."""

    def test_issue_and_validate_schedule_token(self):
        """Valid token issued for schedule action passes validation."""
        details = {"address_line": "123 Main St", "city": "New York"}
        details_hash = _hash_pickup_details(details)
        token = _issue_pickup_token("schedule", details_hash)
        error = _validate_pickup_token(token, "schedule", details_hash)
        assert error is None

    def test_issue_and_validate_cancel_token(self):
        """Valid token issued for cancel action passes validation."""
        details = {"cancel_by": "prn", "prn": "2929AYYB8T011"}
        details_hash = _hash_pickup_details(details)
        token = _issue_pickup_token("cancel", details_hash)
        error = _validate_pickup_token(token, "cancel", details_hash)
        assert error is None

    def test_wrong_action_rejected(self):
        """Token for 'schedule' rejected when used for 'cancel'."""
        details = {"address_line": "123 Main St"}
        details_hash = _hash_pickup_details(details)
        token = _issue_pickup_token("schedule", details_hash)
        error = _validate_pickup_token(token, "cancel", details_hash)
        assert error is not None
        assert "action mismatch" in error.lower()

    def test_tampered_token_rejected(self):
        """Tampered token is rejected with signature error."""
        details = {"address_line": "123 Main St"}
        details_hash = _hash_pickup_details(details)
        token = _issue_pickup_token("schedule", details_hash)
        # Tamper with token by flipping a character
        tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
        error = _validate_pickup_token(tampered, "schedule", details_hash)
        assert error is not None

    def test_expired_token_rejected(self, monkeypatch):
        """Expired token is rejected."""
        import src.orchestrator.agent.tools.pickup as pickup_mod

        # Issue token with 0-second TTL
        original_ttl = pickup_mod._PICKUP_TOKEN_TTL_SECONDS
        pickup_mod._PICKUP_TOKEN_TTL_SECONDS = 0
        try:
            details = {"address_line": "123 Main St"}
            details_hash = _hash_pickup_details(details)
            token = _issue_pickup_token("schedule", details_hash)
            # Small sleep to ensure expiry
            time.sleep(0.01)
            error = _validate_pickup_token(token, "schedule", details_hash)
            assert error is not None
            assert "expired" in error.lower()
        finally:
            pickup_mod._PICKUP_TOKEN_TTL_SECONDS = original_ttl

    def test_wrong_details_hash_rejected(self):
        """Token with mismatched details hash is rejected."""
        details1 = {"address_line": "123 Main St"}
        details2 = {"address_line": "456 Oak Ave"}
        hash1 = _hash_pickup_details(details1)
        hash2 = _hash_pickup_details(details2)
        token = _issue_pickup_token("schedule", hash1)
        error = _validate_pickup_token(token, "schedule", hash2)
        assert error is not None
        assert "details do not match" in error.lower()

    def test_malformed_token_rejected(self):
        """Non-base64 token is rejected."""
        error = _validate_pickup_token("not-a-token", "schedule", "hash")
        assert error is not None
        assert "malformed" in error.lower()

    def test_hash_is_deterministic(self):
        """Same details produce the same hash."""
        details = {"city": "Chicago", "address_line": "789 Elm St"}
        assert _hash_pickup_details(details) == _hash_pickup_details(details)

    def test_hash_differs_for_different_details(self):
        """Different details produce different hashes."""
        h1 = _hash_pickup_details({"city": "Chicago"})
        h2 = _hash_pickup_details({"city": "Denver"})
        assert h1 != h2
