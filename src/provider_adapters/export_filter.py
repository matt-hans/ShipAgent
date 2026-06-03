from collections.abc import Iterable

from src.registry.catalog import public_tools
from src.registry.models import ProviderExport, ToolContract, ToolVisibility


def exportable_tools(
    provider: ProviderExport, tools: Iterable[ToolContract] | None = None
) -> list[ToolContract]:
    candidates = public_tools() if tools is None else tools
    return [
        tool
        for tool in candidates
        if tool.visibility == ToolVisibility.public
        and tool.provider_export_enabled
        and tool.implementation_status == "implemented"
        and tool.hosted_readiness == "ready"
        and tool.tenant_safe is True
        and provider in tool.provider_exports
    ]
