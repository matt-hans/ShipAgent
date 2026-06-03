from src.registry.models import RegistrySchema, ToolContract, ToolVisibility
from src.registry.tools.private import PRIVATE_TOOLS
from src.registry.tools.public import PUBLIC_TOOLS


def all_tools() -> list[ToolContract]:
    return [*PUBLIC_TOOLS, *PRIVATE_TOOLS]


def public_tools() -> list[ToolContract]:
    return [tool for tool in all_tools() if tool.visibility == ToolVisibility.public]


def load_registry() -> RegistrySchema:
    return RegistrySchema(schema_version="1.0.0", tools=all_tools())
