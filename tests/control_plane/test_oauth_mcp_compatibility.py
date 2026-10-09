"""Offline resource discovery and authenticated MCP boundary contracts.

These use the actual HTTP app and synthetic identity boundaries. They do not
qualify Auth0 setup, consent, client registration or a real host product.
"""

import pytest
from fastapi.testclient import TestClient

from src.control_plane.app import create_control_plane_app
from src.control_plane.config import ControlPlaneSettings

ORIGIN = "https://mcp.example.test"
RESOURCE = f"{ORIGIN}/mcp"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
ISSUER = "https://identity.example.test/"
PUBLIC_SCOPES = [
    "shipagent.status",
    "shipagent.preview",
    "shipagent.execute",
    "shipagent.artifacts",
]


def settings(**changes):
    return ControlPlaneSettings(
        **{
            "public_base_url": ORIGIN,
            "auth0_issuer": ISSUER,
            "auth0_audience": RESOURCE,
            "database_url": "sqlite+aiosqlite:///:memory:",
            "redis_url": "redis://127.0.0.1:6379/0",
            **changes,
        }
    )


def test_discovery_names_exact_entered_mcp_resource_and_public_scopes():
    app = create_control_plane_app(settings=settings())
    with TestClient(app) as client:
        response = client.get(METADATA_PATH)
        root_alias = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json() == {
        "resource": RESOURCE,
        "authorization_servers": [ISSUER],
        "scopes_supported": PUBLIC_SCOPES,
        "bearer_methods_supported": ["header"],
    }
    assert root_alias.status_code == 200
    assert root_alias.json() == response.json()


@pytest.mark.parametrize("base", [ORIGIN, f"{ORIGIN}/", RESOURCE, f"{RESOURCE}/"])
def test_origin_and_endpoint_configuration_have_one_canonical_resource(base):
    app = create_control_plane_app(settings=settings(public_base_url=base))
    with TestClient(app) as client:
        assert client.get(METADATA_PATH).json()["resource"] == RESOURCE


@pytest.mark.parametrize(
    "base",
    [
        f"{ORIGIN}/other",
        f"{RESOURCE}/mcp",
        f"{ORIGIN}//mcp",
        f"{RESOURCE}?token=synthetic-canary",
        f"{RESOURCE}#fragment",
        "https://user:synthetic-canary@mcp.example.test",
        "http://mcp.example.test",
    ],
)
def test_ambiguous_or_unsafe_resource_configuration_fails_closed(base):
    with pytest.raises(ValueError, match="public MCP URL"):
        create_control_plane_app(settings=settings(public_base_url=base))


@pytest.mark.parametrize("audience", [ORIGIN, f"{RESOURCE}/", f"{ORIGIN}/other"])
def test_origin_or_wrong_path_audience_configuration_fails_closed(audience):
    with pytest.raises(ValueError, match="AUTH0_AUDIENCE.*canonical MCP resource"):
        create_control_plane_app(settings=settings(auth0_audience=audience))


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_missing_bearer_challenges_exact_resource_with_least_privilege(path):
    app = create_control_plane_app(settings=settings())
    with TestClient(app) as client:
        response = client.post(path, headers={"Host": "attacker.example"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{ORIGIN}{METADATA_PATH}", scope="shipagent.status"'
    )


def test_management_challenge_does_not_claim_workflow_scope_is_sufficient():
    app = create_control_plane_app(settings=settings())
    with TestClient(app) as client:
        response = client.post("/relay/devices")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{ORIGIN}{METADATA_PATH}"'
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{METADATA_PATH}/private"),
        ("GET", "/.well-known/oauth-protected-resource-private"),
        ("POST", METADATA_PATH),
    ],
)
def test_only_exact_metadata_get_routes_bypass_authorization(method, path):
    app = create_control_plane_app(settings=settings())

    @app.api_route(path, methods=[method])
    async def protected_probe():
        return {"private": True}

    with TestClient(app) as client:
        response = client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize(
    "metadata_url",
    [
        f"{ORIGIN}/.well-known/oauth-protected-resource",
        f"{ORIGIN}{METADATA_PATH}/other",
        f"{ORIGIN}{METADATA_PATH}?private=synthetic-canary",
        f"{ORIGIN}{METADATA_PATH}#fragment",
        f'https://mcp.example.test"{METADATA_PATH}',
        f"https://mcp.example.test\r\n{METADATA_PATH}",
        f"https://user:synthetic-canary@mcp.example.test{METADATA_PATH}",
        f"http://mcp.example.test{METADATA_PATH}",
    ],
)
def test_configured_tool_challenge_rejects_unsafe_metadata_url(metadata_url):
    from src.hosted_mcp.server import build_server

    with pytest.raises(ValueError, match="metadata URL"):
        build_server(oauth_resource_metadata_url=metadata_url)


@pytest.mark.parametrize(
    "scope", ["relay:device:manage", "shipments:execute", 'unsafe" scope']
)
def test_configured_oauth_server_rejects_internal_or_unknown_tool_scopes(scope):
    from src.hosted_mcp.server import build_server
    from src.registry.catalog import public_tools

    contract = next(
        tool for tool in public_tools() if tool.name == "get_shipagent_status"
    )
    with pytest.raises(ValueError, match="public OAuth scopes"):
        build_server(
            tools=[contract.model_copy(update={"auth_scopes": [scope]})],
            tool_handlers={contract.name: lambda context, arguments: {}},
            oauth_resource_metadata_url=f"{ORIGIN}{METADATA_PATH}",
        )


@pytest.mark.parametrize("entered_url", [ORIGIN, RESOURCE])
def test_metadata_checker_fetches_path_aware_document_for_entered_url(
    monkeypatch, entered_url
):
    import httpx

    from scripts.check_provider_oauth_metadata import check_metadata

    requests = []

    def serve(request):
        requests.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "resource": RESOURCE,
                "authorization_servers": [ISSUER],
                "scopes_supported": PUBLIC_SCOPES,
                "bearer_methods_supported": ["header"],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        monkeypatch.setattr(httpx, "get", client.get)
        assert check_metadata(entered_url)["resource"] == RESOURCE
    assert requests == [f"{ORIGIN}{METADATA_PATH}"]


@pytest.mark.parametrize(
    "base", [f"{ORIGIN}/other/../mcp", f"{ORIGIN}\r\n/mcp", f"{ORIGIN}\\mcp"]
)
def test_raw_public_url_is_validated_before_url_normalization(base):
    with pytest.raises(ValueError, match="public MCP URL"):
        settings(public_base_url=base)


def test_example_configuration_has_matching_resource_and_audience():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / ".env.example"
    values = dict(
        line.split("=", 1)
        for line in example.read_text().splitlines()
        if line.startswith(("SHIPAGENT_PUBLIC_BASE_URL=", "SHIPAGENT_AUTH0_AUDIENCE="))
    )
    create_control_plane_app(
        settings=settings(
            public_base_url=values["SHIPAGENT_PUBLIC_BASE_URL"],
            auth0_audience=values["SHIPAGENT_AUTH0_AUDIENCE"],
        )
    )
