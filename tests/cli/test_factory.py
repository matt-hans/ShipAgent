"""Tests for the client factory."""

import pytest

from src.cli.factory import get_client


class TestGetClient:
    """Tests for client factory dispatch."""

    def test_standalone_returns_runner(self):
        """Standalone mode returns InProcessRunner."""
        client = get_client(standalone=True)
        from src.cli.runner import InProcessRunner
        assert isinstance(client, InProcessRunner)

    def test_http_returns_http_client(self):
        """Default mode returns HttpClient."""
        client = get_client(standalone=False)
        from src.cli.http_client import HttpClient
        assert isinstance(client, HttpClient)

    def test_http_with_custom_url(self):
        """HttpClient accepts custom base URL."""
        client = get_client(standalone=False, base_url="http://pi.local:9000")
        assert client._base_url == "http://pi.local:9000"
