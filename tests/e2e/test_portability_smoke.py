import json
from pathlib import Path


def test_generated_artifacts_cover_first_wave_providers():
    root = Path("generated/provider_artifacts")

    expected = [
        "registry.json",
        "generic_mcp_tools.json",
        "openai_apps_tools.json",
        "microsoft_openapi_operations.json",
        "gemini_functions.json",
    ]
    for name in expected:
        assert (root / name).exists(), name


def test_create_shipments_requires_confirmation_everywhere():
    root = Path("generated/provider_artifacts")
    generic = json.loads((root / "generic_mcp_tools.json").read_text())
    microsoft = json.loads((root / "microsoft_openapi_operations.json").read_text())

    mcp_tool = next(tool for tool in generic if tool["name"] == "create_shipments")
    ms_op = next(op for op in microsoft if op["operationId"] == "create_shipments")

    assert mcp_tool["annotations"]["openWorldHint"] is True
    assert ms_op["x-openai-isConsequential"] is True
