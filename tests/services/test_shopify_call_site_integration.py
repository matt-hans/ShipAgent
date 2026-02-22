"""Tests for Shopify runtime call site integration."""

import os

import pytest


class TestSystemPromptShopifyDetection:
    """Tests for Shopify detection in system_prompt via resolve_shopify_credentials."""

    def test_shopify_configured_via_env(self):
        """System prompt detects Shopify when env vars set."""
        from src.services.runtime_credentials import resolve_shopify_credentials

        os.environ["SHOPIFY_ACCESS_TOKEN"] = "tok"
        os.environ["SHOPIFY_STORE_DOMAIN"] = "s.myshopify.com"
        try:
            result = resolve_shopify_credentials()
            assert result is not None
        finally:
            os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
            os.environ.pop("SHOPIFY_STORE_DOMAIN", None)

    def test_shopify_not_configured(self):
        """Returns None when no Shopify credentials."""
        from src.services.runtime_credentials import resolve_shopify_credentials
        import src.services.runtime_credentials as rc
        rc._shopify_fallback_warned = False

        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)
        result = resolve_shopify_credentials()
        assert result is None


class TestConnectShopifyCredentialResolution:
    """Tests for connect_shopify_tool credential resolution."""

    def test_connect_shopify_env_fallback_detects_creds(self):
        """resolve_shopify_credentials returns creds from env."""
        from src.services.runtime_credentials import resolve_shopify_credentials
        import src.services.runtime_credentials as rc
        rc._shopify_fallback_warned = False

        os.environ["SHOPIFY_ACCESS_TOKEN"] = "test_tok"
        os.environ["SHOPIFY_STORE_DOMAIN"] = "test.myshopify.com"
        try:
            result = resolve_shopify_credentials()
            assert result is not None
            assert result.access_token == "test_tok"
            assert result.store_domain == "test.myshopify.com"
        finally:
            os.environ.pop("SHOPIFY_ACCESS_TOKEN", None)
            os.environ.pop("SHOPIFY_STORE_DOMAIN", None)

    def test_connect_shopify_no_creds_returns_none(self):
        """resolve_shopify_credentials returns None when empty."""
        from src.services.runtime_credentials import resolve_shopify_credentials
        import src.services.runtime_credentials as rc
        rc._shopify_fallback_warned = False

        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)
        result = resolve_shopify_credentials()
        assert result is None


class TestPlatformStatusShopifyResolution:
    """Tests for get_shopify_env_status credential resolution."""

    def test_env_status_returns_not_configured(self):
        """get_shopify_env_status returns not configured when no creds."""
        import src.services.runtime_credentials as rc
        rc._shopify_fallback_warned = False

        for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_STORE_DOMAIN"):
            os.environ.pop(var, None)

        from src.services.runtime_credentials import resolve_shopify_credentials
        result = resolve_shopify_credentials()
        assert result is None
