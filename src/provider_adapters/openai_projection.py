from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.models import ToolContract


def to_openai_app_tool(tool: ToolContract) -> dict:
    descriptor = to_mcp_tool_descriptor(tool)
    if tool.ui_resource:
        descriptor["_meta"] = {"ui": {"resourceUri": tool.ui_resource}}
    return descriptor
