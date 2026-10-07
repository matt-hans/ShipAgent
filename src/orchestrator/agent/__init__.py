"""Shared prompt builders, deterministic tools and MCP gateway configuration.

Conversation orchestration is owned by ``src.services.conversation_runtime``.
This package retains the established shared workflow and prompt import paths.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["PROJECT_ROOT", "MCPServerConfig", "get_data_mcp_config"]
_EXPORT_MODULES = dict.fromkeys(__all__, "src.orchestrator.agent.config")


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
