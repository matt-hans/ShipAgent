"""Tests for validate_filter_config() startup validation."""

import pytest

from src.orchestrator.filter_config import validate_filter_config
from src.orchestrator.filter_resolver import FilterConfigError


class TestValidateFilterConfig:
    """Verify startup-time secret validation."""

    def test_raises_when_missing(self, monkeypatch):
        """Raises FilterConfigError when FILTER_TOKEN_SECRET is not set."""
        monkeypatch.delenv("FILTER_TOKEN_SECRET", raising=False)
        with pytest.raises(FilterConfigError, match="required"):
            validate_filter_config()

    def test_raises_when_too_short(self, monkeypatch):
        """Raises FilterConfigError when secret is < 32 chars."""
        monkeypatch.setenv("FILTER_TOKEN_SECRET", "short")
        with pytest.raises(FilterConfigError, match="at least 32"):
            validate_filter_config()

    def test_succeeds_when_valid(self, monkeypatch):
        """No error when secret is >= 32 chars."""
        monkeypatch.setenv("FILTER_TOKEN_SECRET", "a" * 32)
        validate_filter_config()  # Should not raise
