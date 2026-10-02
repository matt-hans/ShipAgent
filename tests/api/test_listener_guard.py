"""Direct-uvicorn bypass of the desktop non-loopback API-key gate (issue #48).

A process started as ``uvicorn src.api.main:app --host 0.0.0.0`` never passes
through a launcher, and the lifespan cannot see uvicorn's bind host. The
per-request guard therefore enforces the gate against the socket the request
actually arrived on (ASGI ``server``/``client`` scope values, not env metadata).
"""

import httpx
import pytest

from src.api.main import app

_STRONG_KEY = "k" * 64


def _client(server: tuple[str, int], client: tuple[str, int]) -> httpx.AsyncClient:
    # httpx's transport does not expose the ASGI server tuple; wrap the app.
    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            scope["server"] = server
        await app(scope, receive, send)

    transport = httpx.ASGITransport(app=wrapped, client=client)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_non_loopback_effective_bind_without_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    async with _client(("192.168.1.5", 8000), ("192.168.1.9", 50000)) as http:
        response = await http.get("/api/v1/jobs")
    assert response.status_code == 503
    assert "SHIPAGENT_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_non_loopback_client_over_wildcard_bind_without_key_is_rejected(
    monkeypatch,
):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    async with _client(("127.0.0.1", 8000), ("203.0.113.7", 50000)) as http:
        response = await http.get("/api/v1/jobs")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_weak_api_key_does_not_satisfy_guard(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", "short")
    async with _client(("192.168.1.5", 8000), ("192.168.1.9", 50000)) as http:
        response = await http.get("/api/v1/jobs")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_non_loopback_with_strong_key_falls_through_to_api_key_auth(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", _STRONG_KEY)
    async with _client(("192.168.1.5", 8000), ("192.168.1.9", 50000)) as http:
        response = await http.get("/api/v1/jobs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_loopback_without_key_is_not_blocked_by_guard(monkeypatch):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    async with _client(("127.0.0.1", 8000), ("127.0.0.1", 50000)) as http:
        response = await http.get("/health")
    assert response.status_code != 503


_PEERS = [
    pytest.param(("192.168.1.5", 8000), ("192.168.1.9", 50000), id="ipv4-lan"),
    pytest.param(("::", 8000), ("fe80::1%en0", 50000), id="ipv6-link-local"),
    pytest.param(
        ("::ffff:192.168.1.5", 8000), ("::ffff:192.168.1.9", 5), id="mapped-lan"
    ),
    pytest.param(
        ("127.0.0.1", 8000), ("::ffff:203.0.113.7", 5), id="mapped-remote-client"
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("server", "peer"), _PEERS)
@pytest.mark.parametrize("path", ["/health", "/readyz"])
async def test_keyless_non_loopback_probes_expose_only_binary_status(
    monkeypatch, server, peer, path
):
    """Keyless remote peers get a minimal probe, never diagnostics (CWE-200)."""
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    monkeypatch.setenv("UPS_CLIENT_ID", "CANARY-UPS-CLIENT")
    async with _client(server, peer) as http:
        response = await http.get(path)
    assert response.status_code != 503 or set(response.json()) == {"status"}
    assert set(response.json()) == {"status"}
    assert "CANARY" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server", "peer"),
    [
        (("127.0.0.1", 8000), ("127.0.0.1", 5)),
        (("::1", 8000), ("::1", 5)),
        (("::ffff:127.0.0.1", 8000), ("::ffff:127.0.0.1", 5)),
    ],
)
async def test_keyless_loopback_health_keeps_diagnostics(monkeypatch, server, peer):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    async with _client(server, peer) as http:
        response = await http.get("/health")
    assert response.status_code == 200
    assert "uptime_seconds" in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(("server", "peer"), _PEERS)
async def test_keyless_ipv6_and_mapped_peers_rejected_on_api(monkeypatch, server, peer):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    async with _client(server, peer) as http:
        response = await http.get("/api/v1/jobs")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_missing_client_scope_is_not_treated_as_remote(monkeypatch):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)

    async def wrapped(scope, receive, send):
        scope["client"] = None
        scope["server"] = ("127.0.0.1", 8000)
        await app(scope, receive, send)

    transport = httpx.ASGITransport(app=wrapped)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        response = await http.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_strong_key_remote_health_is_binary_without_header(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_API_KEY", _STRONG_KEY)
    async with _client(("192.168.1.5", 8000), ("192.168.1.9", 5)) as http:
        anon = await http.get("/health")
        authed = await http.get("/health", headers={"X-API-Key": _STRONG_KEY})
    assert anon.json() == {"status": "healthy"}
    assert "uptime_seconds" in authed.json()
