import re
from copy import deepcopy

from src.registry.models import SideEffectClass, ToolContract

EXTERNAL_AUTH_SCOPE_PREFIXES = (
    "accounts:",
    "address:",
    "stores:",
    "shipments:",
    "tracking:",
    "pickups:",
)
EXTERNAL_BEHAVIOR_TERMS = (
    "carrier",
    "commerce",
    "pickup",
    "rate",
    "store",
    "tracking",
    "ups",
    "label",
)


def has_external_reach(tool: ToolContract) -> bool:
    if any(
        scope.startswith(EXTERNAL_AUTH_SCOPE_PREFIXES) for scope in tool.auth_scopes
    ):
        return True

    searchable_text = " ".join((tool.name, tool.title, tool.description)).lower()
    searchable_text = searchable_text.replace("_", " ")
    return any(
        re.search(rf"\b{re.escape(term)}s?\b", searchable_text)
        for term in EXTERNAL_BEHAVIOR_TERMS
    )


def to_mcp_tool_descriptor(tool: ToolContract) -> dict:
    read_only = tool.side_effect in {SideEffectClass.read, SideEffectClass.estimate}
    destructive = tool.side_effect == SideEffectClass.destructive
    open_world = has_external_reach(tool)
    return {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "inputSchema": deepcopy(tool.input_schema),
        "outputSchema": deepcopy(tool.output_schema),
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "openWorldHint": open_world,
        },
    }
