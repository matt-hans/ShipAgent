"""Tests for error message sanitization (F-7, CWE-209).

Verifies that raw error messages containing credentials are redacted
before being sent to SSE clients or persisted in the database.
"""

from src.utils.redaction import sanitize_error_message


class TestErrorSanitization:
    """Tests for sanitize_error_message preventing credential leakage."""

    def test_sse_error_does_not_leak_credentials(self):
        """Error message with credential pattern is redacted."""
        raw = (
            "Connection failed: client_secret=sk-live-abc123 "
            "password=hunter2 host=ups.example.com"
        )
        sanitized = sanitize_error_message(raw)

        assert sanitized is not None
        assert "sk-live-abc123" not in sanitized
        assert "hunter2" not in sanitized
        assert "REDACTED" in sanitized
        # Non-sensitive parts preserved
        assert "Connection failed" in sanitized

    def test_batch_error_sanitized_in_db(self):
        """Background task error message is redacted before DB storage."""
        raw = (
            "Background task error: "
            'API returned {"client_id":"cid_123","token":"tok_secret"}'
        )
        sanitized = sanitize_error_message(raw)

        assert sanitized is not None
        assert "tok_secret" not in sanitized
        assert "cid_123" not in sanitized
        assert "REDACTED" in sanitized
