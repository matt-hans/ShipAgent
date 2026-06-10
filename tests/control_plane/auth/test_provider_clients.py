import pytest

from src.control_plane.auth.provider_clients import ProviderClientRegistry


def test_known_client_resolves_surface():
    registry = ProviderClientRegistry(
        {"chatgpt-client": "chatgpt", "claude-client": "claude_ai"}
    )
    assert registry.surface_for("chatgpt-client") == "chatgpt"


def test_unknown_client_fails_closed():
    registry = ProviderClientRegistry({"chatgpt-client": "chatgpt"})
    with pytest.raises(PermissionError, match="authorized provider client"):
        registry.surface_for("unknown")
