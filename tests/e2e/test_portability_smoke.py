import json
from pathlib import Path


def test_generated_artifacts_cover_first_wave_providers():
    root = Path("generated/provider_artifacts")

    expected = [
        "registry.json",
        "generic_mcp_tools.json",
        "openai_apps_public_tools.json",
        "claude_remote_mcp_public_tools.json",
        "microsoft_openapi_operations.json",
        "gemini_functions.json",
    ]
    for name in expected:
        assert (root / name).exists(), name


def test_relay_execution_tools_are_projected_safely():
    root = Path("generated/provider_artifacts")
    generic = json.loads((root / "generic_mcp_tools.json").read_text())
    openai_public = json.loads((root / "openai_apps_public_tools.json").read_text())

    generic_names = {tool["name"] for tool in generic}
    openai_names = {tool["name"] for tool in openai_public}

    assert generic_names == {"get_shipagent_status"}
    assert "execute_shipments" not in generic_names

    if "execute_shipments" in openai_names:
        public_tool = next(
            tool for tool in openai_public if tool["name"] == "execute_shipments"
        )
        assert public_tool["annotations"]["openWorldHint"] is True
