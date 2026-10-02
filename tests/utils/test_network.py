"""Tests for the canonical loopback host helper."""

import pytest

from src.utils.network import is_loopback_host


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1.2.3",
        "::1",
        "[::1]",
        "localhost",
        "LOCALHOST",
        "localhost.",
        " localhost ",
        "::ffff:127.0.0.1",
        "::1%lo0",
    ],
)
def test_loopback_hosts(host):
    assert is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "0.0.0.0",
        "::",
        "192.168.1.5",
        "example.com",
        "localhost.example.com",
        "127.0.0.1.evil.com",
        "::ffff:10.0.0.1",
    ],
)
def test_non_loopback_hosts(host):
    assert is_loopback_host(host) is False


def test_cli_and_relay_use_canonical_loopback_helper():
    """CLI HTTP client and relay transport accept the same loopback spellings."""
    from src.cli.http_client import _reject_insecure_credential_transport
    from src.cli.protocol import ShipAgentClientError
    from src.services.desktop_relay_client import WebSocketRelayTransport

    _reject_insecure_credential_transport("http://[::ffff:127.0.0.1]:8080")
    _reject_insecure_credential_transport("http://LOCALHOST:8080")
    with pytest.raises(ShipAgentClientError):
        _reject_insecure_credential_transport("http://0.0.0.0:8080")
    transport = WebSocketRelayTransport(
        allow_insecure_loopback=True, connect_factory=lambda *a, **k: object()
    )
    transport.connect("ws://LOCALHOST:9/relay")
    with pytest.raises(ValueError):
        transport.connect("ws://0.0.0.0:9/relay")
