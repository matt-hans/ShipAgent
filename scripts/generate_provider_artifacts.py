#!/usr/bin/env python
import json
from pathlib import Path

from src.provider_adapters.export_filter import exportable_tools
from src.provider_adapters.gemini_projection import to_gemini_function
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.provider_adapters.microsoft_projection import to_openapi_operation
from src.provider_adapters.openai_projection import to_openai_app_tool
from src.registry.catalog import load_registry
from src.registry.export import write_registry_snapshot
from src.registry.models import ProviderExport

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated" / "provider_artifacts"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    registry = load_registry()
    write_registry_snapshot(OUT / "registry.json", registry)
    write_json(
        OUT / "generic_mcp_tools.json",
        [
            to_mcp_tool_descriptor(tool)
            for tool in exportable_tools(ProviderExport.generic_mcp)
        ],
    )
    write_json(
        OUT / "openai_apps_tools.json",
        [to_openai_app_tool(tool) for tool in exportable_tools(ProviderExport.openai)],
    )
    write_json(
        OUT / "microsoft_openapi_operations.json",
        [
            to_openapi_operation(tool)
            for tool in exportable_tools(ProviderExport.microsoft)
        ],
    )
    write_json(
        OUT / "gemini_functions.json",
        [to_gemini_function(tool) for tool in exportable_tools(ProviderExport.gemini)],
    )


if __name__ == "__main__":
    main()
