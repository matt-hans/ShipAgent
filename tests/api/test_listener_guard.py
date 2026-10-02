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
    transport = httpx.ASGITransport(app=app, client=client)

    async def _with_server(scope):
        scope["server"] = server

    # httpx's transport does not expose the ASGI server tuple; wrap the app.
    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            await _with_server(scope)
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


@pytest.mark.asyncio
async def test_health_probe_stays_reachable_non_loopback(monkeypatch):
    monkeypatch.delenv("SHIPAGENT_API_KEY", raising=False)
    async with _client(("192.168.1.5", 8000), ("192.168.1.9", 50000)) as http:
        response = await http.get("/health")
    assert response.status_code != 503
