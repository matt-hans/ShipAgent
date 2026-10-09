"""Real in-process HTTP/MCP wire evidence with signed disposable identities.

No actual authorization server, model, carrier or ChatGPT/Claude client is used.
"""

import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fastmcp import FastMCP

from src.control_plane.app import _resolve_authorization as resolve_from_store
from src.control_plane.app import create_control_plane_app
from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import Auth0TokenVerifier
from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.execution_targets import LoopbackExecutionTarget
from src.control_plane.request_controls import RequestControls
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools
from tests.control_plane.test_oauth_mcp_compatibility import (
    ISSUER,
    METADATA_PATH,
    ORIGIN,
    RESOURCE,
    settings,
)

STATUS_ARGS = {"correlation_id": "sa_correlation_0123456789abcdef0123456789abcdef"}


class _RedisCounter:
    def __init__(self):
        self.counts = {}

    async def eval(self, script, keys, key, *args):
        assert keys == 1
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class _CountedTarget(LoopbackExecutionTarget):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def invoke(self, request):
        self.requests.append(request)
        return await super().invoke(request)


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(params=[False, True], ids=["production", "stateful-proof"])
def authenticated_app(monkeypatch, signing_key, request):
    if request.param:
        original_http_app = FastMCP.http_app

        def stateful_http_app(server, *args, **kwargs):
            kwargs["stateless_http"] = False
            return original_http_app(server, *args, **kwargs)

        monkeypatch.setattr(FastMCP, "http_app", stateful_http_app)

    class OfflineKeys:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=signing_key.public_key())

    monkeypatch.setattr(
        "src.control_plane.app._build_verifier",
        lambda issuer, audience: Auth0TokenVerifier(issuer, audience, OfflineKeys()),
    )

    async def resolve(config, principal, session_factory):
        surface = ProviderClientRegistry(config.auth0_provider_clients).surface_for(
            principal.client_id
        )
        return AuthorizationContext(
            account_id=f"synthetic-{principal.subject}",
            provider_connection_id=f"synthetic-{principal.client_id}-{principal.subject}",
            provider_surface=surface,
            subject=principal.subject,
            client_id=principal.client_id,
            scopes=principal.scopes,
            auth_time=principal.auth_time,
        )

    monkeypatch.setattr("src.control_plane.app._resolve_authorization", resolve)
    monkeypatch.setattr(
        "src.control_plane.app.RequestControls",
        lambda redis_client: RequestControls(redis_client, now_fn=lambda: 0),
    )
    target = _CountedTarget()
    app = create_control_plane_app(
        settings=settings(), redis_client=_RedisCounter(), execution_target=target
    )

    app.state.test_stateful_transport = request.param

    def token(**claims):
        now = int(time.time())
        return jwt.encode(
            {
                "sub": "synthetic-owner",
                "azp": "chatgpt-client",
                "iss": ISSUER,
                "aud": RESOURCE,
                "iat": now,
                "exp": now + 600,
                "scope": "shipagent.status",
                **claims,
            },
            signing_key,
            algorithm="RS256",
        )

    return app, target, token


def rpc(client, method, params=None, *, request_id=1):
    response = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )
    assert response.status_code == 200, response.text
    if response.headers.get("mcp-session-id"):
        client.headers["mcp-session-id"] = response.headers["mcp-session-id"]
    if response.headers["content-type"].startswith("text/event-stream"):
        records = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        return next(record for record in records if record.get("id") == request_id)
    return response.json()


def initialize(client, access_token):
    client.headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
        }
    )
    reply = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "synthetic-http-client", "version": "1"},
        },
    )
    assert "result" in reply
    notification = client.post(
        "/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert notification.status_code == 202


def test_http_tools_list_declares_scope_and_preserves_registry_contract(
    authenticated_app,
):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token())
        descriptors = rpc(client, "tools/list")["result"]["tools"]
    assert len(descriptors) == 1
    actual = descriptors[0]
    assert actual["name"] == "get_shipagent_status"
    expected = to_mcp_tool_descriptor(
        next(tool for tool in public_tools() if tool.name == actual["name"])
    )
    for field, value in expected.items():
        if field == "annotations":
            assert {key: actual[field][key] for key in value} == value
        else:
            assert actual[field] == value
    scheme = [{"type": "oauth2", "scopes": ["shipagent.status"]}]
    assert actual["securitySchemes"] == scheme
    assert actual["_meta"]["securitySchemes"] == scheme
    assert target.requests == []


def test_http_missing_tool_scope_returns_oauth_challenge_without_dispatch(
    authenticated_app,
):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token(scope="shipagent.preview"))
        result = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert result["isError"] is True
    assert result["_meta"]["mcp/www_authenticate"] == [
        f'Bearer resource_metadata="{ORIGIN}{METADATA_PATH}", '
        'error="insufficient_scope", error_description="Additional authorization is required", '
        'scope="shipagent.status"'
    ]
    assert target.requests == []


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": ORIGIN},
        {"aud": f"{RESOURCE}/"},
        {"aud": f"{ORIGIN}/other"},
        {"aud": "https://other.example.test/mcp"},
        {"iss": "https://other-issuer.example.test/"},
        {"exp": 1},
        {"nbf": 4102444800},
        {"azp": "unregistered-client"},
    ],
)
def test_signed_unacceptable_tokens_never_reach_mcp_or_target(
    authenticated_app, claims
):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        response = client.post(
            "/mcp/",
            headers={
                "Authorization": f"Bearer {token(**claims)}",
                "Accept": "application/json, text/event-stream",
                "X-Provider-Surface": "chatgpt",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"].startswith(
        f'Bearer resource_metadata="{ORIGIN}{METADATA_PATH}"'
    )
    assert target.requests == []


def test_signed_valid_token_and_mount_redirect_keep_exact_identity(authenticated_app):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token()}"},
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert response.headers["location"].endswith("/mcp/")
        initialize(client, token(azp="claude-client"))
        result = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert result.get("isError", False) is False
    assert result["structuredContent"]["status"] == "ready"
    assert len(target.requests) == 1
    assert (
        target.requests[0].provider_connection_id
        == "synthetic-claude-client-synthetic-owner"
    )
    assert target.requests[0].provider_surface == "claude_ai"


def test_status_polling_reuses_arguments_but_remains_connection_rate_limited(
    authenticated_app,
):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token())
        for request_id in range(2, 32):
            result = rpc(
                client,
                "tools/call",
                {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
                request_id=request_id,
            )["result"]
            assert result.get("isError", False) is False, result
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
            request_id=32,
        )["result"]
    assert denied["isError"] is True
    assert "mcp/www_authenticate" not in denied.get("_meta", {})
    assert len(target.requests) == 30
    assert all(
        request.tool_name == "get_shipagent_status" for request in target.requests
    )


def test_step_up_scope_retry_dispatches_once(authenticated_app):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token(scope="shipagent.preview"))
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
        assert denied["isError"] is True
        assert target.requests == []
        client.headers["Authorization"] = f"Bearer {token()}"
        accepted = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
            request_id=2,
        )["result"]
    assert accepted.get("isError", False) is False
    assert len(target.requests) == 1


def test_handler_cannot_forge_oauth_reauthentication(
    authenticated_app, monkeypatch, caplog
):
    from src.hosted_mcp.server import ToolAuthorizationError

    app, target, token = authenticated_app

    async def forged_handler(request):
        raise ToolAuthorizationError(
            code="insufficient_scope", message="synthetic-private-canary"
        )

    monkeypatch.setattr(target, "invoke", forged_handler)
    with TestClient(app) as client:
        initialize(client, token())
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert denied["isError"] is True
    assert "mcp/www_authenticate" not in denied.get("_meta", {})
    assert "synthetic-private-canary" not in json.dumps(denied)
    assert "synthetic-private-canary" not in caplog.text


def test_metadata_checker_denies_old_resource_and_leaked_scopes(monkeypatch):
    import httpx

    from scripts.check_provider_oauth_metadata import check_metadata

    for overrides in [
        {"resource": ORIGIN},
        {"scopes_supported": ["shipagent.status", "relay:device:manage"]},
    ]:

        def serve(request, overrides=overrides):
            return httpx.Response(
                200,
                json={
                    "resource": RESOURCE,
                    "authorization_servers": [ISSUER],
                    "scopes_supported": [
                        "shipagent.status",
                        "shipagent.preview",
                        "shipagent.execute",
                        "shipagent.artifacts",
                    ],
                    **overrides,
                },
            )

        with httpx.Client(transport=httpx.MockTransport(serve)) as client:
            monkeypatch.setattr(httpx, "get", client.get)
            with pytest.raises(RuntimeError, match="mismatch"):
                check_metadata(RESOURCE)


def test_unexported_mutation_cannot_be_called_by_authorized_status_client(
    authenticated_app,
):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token(scope="shipagent.status shipagent.execute"))
        denied = rpc(
            client,
            "tools/call",
            {"name": "execute_shipments", "arguments": {"approved": True}},
        )["result"]
    assert denied["isError"] is True
    assert "mcp/www_authenticate" not in denied.get("_meta", {})
    assert target.requests == []


def test_http_session_scope_downgrade_cannot_reuse_initial_authority(authenticated_app):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token())
        client.headers["Authorization"] = f"Bearer {token(scope='shipagent.preview')}"
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert denied["isError"] is True
    assert "mcp/www_authenticate" in denied["_meta"]
    assert target.requests == []


@pytest.mark.parametrize(
    "claims", [{"azp": "claude-client"}, {"sub": "second-synthetic-owner"}]
)
def test_http_session_does_not_reuse_initial_account_or_connection(
    authenticated_app, claims, monkeypatch
):
    app, target, token = authenticated_app
    original_invoke = target.invoke

    async def account_specific_status(request):
        result = await original_invoke(request)
        if request.provider_connection_id != "synthetic-chatgpt-client-synthetic-owner":
            result["status"] = "offline"
            result["executionTarget"]["state"] = "offline"
        return result

    monkeypatch.setattr(target, "invoke", account_specific_status)
    with TestClient(app) as client:
        initialize(client, token())
        initial = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
        assert initial["structuredContent"]["status"] == "ready"
        client.headers["Authorization"] = f"Bearer {token(**claims)}"
        result = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
            request_id=2,
        )["result"]
    assert result.get("isError", False) is False
    assert result["structuredContent"]["status"] == "offline"
    assert len(target.requests) == 2
    client_id = claims.get("azp", "chatgpt-client")
    subject = claims.get("sub", "synthetic-owner")
    assert target.requests[1].account_id == f"synthetic-{subject}"
    assert (
        target.requests[1].provider_connection_id == f"synthetic-{client_id}-{subject}"
    )


def test_production_http_has_no_transport_sessions_or_authenticated_sse_subscription(
    authenticated_app,
):
    app, target, token = authenticated_app
    if app.state.test_stateful_transport:
        pytest.skip("This assertion is for the production stateless transport only")
    with TestClient(app) as client:
        initialize(client, token())
        assert "mcp-session-id" not in client.headers
        client.headers["mcp-session-id"] = "forged-transport-session"
        result = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
        assert result.get("isError", False) is False
        response = client.get("/mcp/")
        assert response.status_code == 405
    assert len(target.requests) == 1


def test_unauthenticated_http_get_cannot_subscribe_even_with_session_header(
    authenticated_app,
):
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token())
        client.headers.pop("Authorization")
        response = client.get(
            "/mcp/",
            headers={
                "Mcp-Session-Id": client.headers.get("mcp-session-id", "forged-session")
            },
        )
    assert response.status_code == 401
    assert target.requests == []


def test_missing_current_http_state_cannot_use_inherited_authority(authenticated_app):
    from starlette.routing import Mount

    app, target, token = authenticated_app
    mount = next(
        route
        for route in app.routes
        if isinstance(route, Mount) and route.path == "/mcp"
    )
    original = mount.app

    async def missing_state(scope, receive, send):
        scope.get("state", {}).pop("authorization", None)
        await original(scope, receive, send)

    mount.app = missing_state
    with TestClient(app) as client:
        initialize(client, token())
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert denied["isError"] is True
    assert 'error="invalid_token"' in denied["_meta"]["mcp/www_authenticate"][0]
    assert target.requests == []


@pytest.mark.parametrize("revoke_account", [False, True], ids=["connection", "account"])
def test_server_revocation_blocks_next_valid_token_request(
    authenticated_app, monkeypatch, tmp_path, revoke_account
):
    import asyncio

    from sqlalchemy import create_engine, update

    from src.control_plane.db import build_session_factory
    from src.control_plane.models import (
        CloudAccount,
        ControlPlaneBase,
        ProviderConnection,
    )

    _, target, token = authenticated_app
    monkeypatch.setattr(
        "src.control_plane.app._resolve_authorization", resolve_from_store
    )
    database_path = tmp_path / "revocation.sqlite3"
    sync_engine = create_engine(f"sqlite:///{database_path}")
    ControlPlaneBase.metadata.create_all(sync_engine)
    database_url = f"sqlite+aiosqlite:///{database_path}"
    sessions = build_session_factory(database_url)
    app = create_control_plane_app(
        settings=settings(database_url=database_url),
        redis_client=_RedisCounter(),
        execution_target=target,
        db_session_factory=sessions,
    )
    try:
        with TestClient(app) as client:
            initialize(client, token())
            result = rpc(
                client,
                "tools/call",
                {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
            )["result"]
            assert result.get("isError", False) is False
            with sync_engine.begin() as connection:
                if revoke_account:
                    connection.execute(update(CloudAccount).values(suspended=True))
                else:
                    connection.execute(
                        update(ProviderConnection).values(status="revoked")
                    )
            denied = client.post(
                "/mcp/",
                json={
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "get_shipagent_status",
                        "arguments": STATUS_ARGS,
                    },
                },
            )
            assert denied.status_code == 401
            assert denied.json() == {"detail": "Unauthorized"}
        assert len(target.requests) == 1
    finally:
        sync_engine.dispose()
        asyncio.run(sessions.kw["bind"].dispose())


def test_missing_sdk_request_metadata_cannot_reuse_http_fallback(
    authenticated_app, monkeypatch
):
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    original = StreamableHTTPServerTransport._create_session_message

    def strip_request_metadata(transport, message, *args, **kwargs):
        wrapped = original(transport, message, *args, **kwargs)
        if getattr(message.root, "method", None) == "tools/call":
            wrapped.metadata.request_context = None
        return wrapped

    monkeypatch.setattr(
        StreamableHTTPServerTransport, "_create_session_message", strip_request_metadata
    )
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token())
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert denied["isError"] is True
    assert 'error="invalid_token"' in denied["_meta"]["mcp/www_authenticate"][0]
    assert target.requests == []


def test_unavailable_http_request_lookup_denies_inherited_authority(
    authenticated_app, monkeypatch
):
    def no_http_request():
        raise RuntimeError("No active HTTP request found.")

    monkeypatch.setattr("src.hosted_mcp.server.get_http_request", no_http_request)
    app, target, token = authenticated_app
    with TestClient(app) as client:
        initialize(client, token())
        denied = rpc(
            client,
            "tools/call",
            {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
        )["result"]
    assert denied["isError"] is True
    assert 'error="invalid_token"' in denied["_meta"]["mcp/www_authenticate"][0]
    assert target.requests == []


def test_loopback_socket_reauthorizes_each_mcp_message(authenticated_app, monkeypatch):
    import socket
    import threading

    import httpx
    import uvicorn

    app, target, token = authenticated_app
    original_invoke = target.invoke

    async def account_specific_status(request):
        result = await original_invoke(request)
        if request.provider_connection_id != "synthetic-chatgpt-client-synthetic-owner":
            result["status"] = "offline"
            result["executionTarget"]["state"] = "offline"
        return result

    monkeypatch.setattr(target, "invoke", account_specific_status)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            initialize(client, token())
            has_session = "mcp-session-id" in client.headers
            assert has_session is app.state.test_stateful_transport
            initial = rpc(
                client,
                "tools/call",
                {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
            )["result"]
            assert initial["structuredContent"]["status"] == "ready"
            client.headers["Authorization"] = (
                f"Bearer {token(scope='shipagent.preview')}"
            )
            denied = rpc(
                client,
                "tools/call",
                {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
                request_id=2,
            )["result"]
            assert denied["isError"] is True
            assert len(target.requests) == 1
            for request_id, claims in enumerate(
                [{"azp": "claude-client"}, {"sub": "second-synthetic-owner"}], 3
            ):
                client.headers["Authorization"] = f"Bearer {token(**claims)}"
                result = rpc(
                    client,
                    "tools/call",
                    {"name": "get_shipagent_status", "arguments": STATUS_ARGS},
                    request_id=request_id,
                )["result"]
                assert result["structuredContent"]["status"] == "offline"
                expected_client = claims.get("azp", "chatgpt-client")
                expected_subject = claims.get("sub", "synthetic-owner")
                assert (
                    target.requests[-1].provider_connection_id
                    == f"synthetic-{expected_client}-{expected_subject}"
                )
                assert target.requests[-1].account_id == f"synthetic-{expected_subject}"
            assert len(target.requests) == 3
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "owned loopback server did not stop"
