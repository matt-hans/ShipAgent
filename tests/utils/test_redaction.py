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
