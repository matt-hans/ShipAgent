"""Tests for validate_filter_config() startup validation."""

import logging

from src.orchestrator.filter_config import validate_filter_config


class TestValidateFilterConfig:
    """Verify startup-time secret validation logs warnings instead of raising."""

    def test_warns_when_missing(self, monkeypatch, caplog):
        """Logs warning when FILTER_TOKEN_SECRET is not set."""
        monkeypatch.delenv("FILTER_TOKEN_SECRET", raising=False)
        with caplog.at_level(logging.WARNING):
            validate_filter_config()  # Should not raise
        assert "not set" in caplog.text

    def test_warns_when_too_short(self, monkeypatch, caplog):
        """Logs warning when secret is < 32 chars."""
        monkeypatch.setenv("FILTER_TOKEN_SECRET", "short")
        with caplog.at_level(logging.WARNING):
            validate_filter_config()  # Should not raise
        assert "shorter than" in caplog.text

    def test_succeeds_when_valid(self, monkeypatch):
        """No warning when secret is >= 32 chars."""
        monkeypatch.setenv("FILTER_TOKEN_SECRET", "a" * 32)
        validate_filter_config()  # Should not raise
