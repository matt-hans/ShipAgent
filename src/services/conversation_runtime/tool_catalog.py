from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.orchestrator.agent.tools import get_all_tool_definitions
from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.services.conversation_runtime.models import ProviderToolDeclaration


class ToolMode(StrEnum):
    BATCH = "batch"
    INTERACTIVE = "interactive"
    BOTH = "both"


class SideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    ARTIFACT = "artifact"
    STATE_CHANGING = "state_changing"
    MONEY_CHANGING = "money_changing"


_BATCH_ONLY = {
    "get_source_info",
    "get_schema",
    "ship_command_pipeline",
    "fetch_rows",
    "resolve_filter_intent",
    "confirm_filter_interpretation",
    "batch_execute",
    "connect_shopify",
    "connect_amazon",
}

_INTERACTIVE_ONLY = {"preview_interactive_shipment"}

_READ_ONLY = {
    "get_source_info",
    "get_schema",
    "fetch_rows",
    "resolve_filter_intent",
    "confirm_filter_interpretation",
    "get_job_status",
    "get_platform_status",
    "rate_shipment",
    "validate_address",
    "get_time_in_transit",
    "rate_pickup",
    "get_pickup_status",
    "find_locations",
    "get_service_center_facilities",
    "list_contacts",
    "track_package",
    "get_landed_cost",
}

_ARTIFACT_EVENTS: dict[str, tuple[str, ...]] = {
    "ship_command_pipeline": ("preview_partial", "preview_ready"),
    "preview_interactive_shipment": ("preview_partial", "preview_ready"),
    "schedule_pickup": ("pickup_result",),
    "cancel_pickup": ("pickup_result",),
    "rate_pickup": ("pickup_preview",),
    "get_pickup_status": ("pickup_result",),
    "find_locations": ("location_result",),
    "get_service_center_facilities": ("location_result",),
    "request_document_upload": ("paperless_upload_prompt",),
    "upload_paperless_document": ("paperless_result",),
    "push_document_to_shipment": ("paperless_result",),
    "delete_paperless_document": ("paperless_result",),
    "resolve_contact": ("contact_resolved",),
    "save_contact": ("contact_saved",),
    "delete_contact": ("contact_deleted",),
    "track_package": ("tracking_result",),
    "get_landed_cost": ("landed_cost_result",),
}

_CONFIRMATION_REQUIRED = {
    "batch_execute",
    "schedule_pickup",
    "cancel_pickup",
}

_STRIP_ROWS = {
    "fetch_rows",
    "ship_command_pipeline",
    "preview_interactive_shipment",
}

_PARALLEL_READ_ONLY = {
    "get_source_info",
    "get_schema",
    "get_job_status",
    "get_platform_status",
    "rate_shipment",
    "validate_address",
    "get_time_in_transit",
    "list_contacts",
}

_MONEY_CHANGING = {
    "batch_execute",
    "schedule_pickup",
    "cancel_pickup",
}

_STATE_CHANGING = {
    "connect_shopify",
    "connect_amazon",
    "resolve_contact",
    "save_contact",
    "delete_contact",
    "upload_paperless_document",
    "push_document_to_shipment",
    "delete_paperless_document",
}


def _mode_for(name: str) -> ToolMode:
    if name in _BATCH_ONLY:
        return ToolMode.BATCH
    if name in _INTERACTIVE_ONLY:
        return ToolMode.INTERACTIVE
    return ToolMode.BOTH


def _side_effect_for(name: str) -> SideEffectClass:
    if name in _MONEY_CHANGING:
        return SideEffectClass.MONEY_CHANGING
    if name in _STATE_CHANGING:
        return SideEffectClass.STATE_CHANGING
    if name in _ARTIFACT_EVENTS:
        return SideEffectClass.ARTIFACT
    if name in _READ_ONLY:
        return SideEffectClass.READ_ONLY
    raise ValueError(f"Missing workflow tool metadata for {name!r}")


@dataclass(frozen=True)
class WorkflowToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[Any]]
    mode: ToolMode
    side_effect_class: SideEffectClass
    confirmation_required: bool = False
    model_result_projection: str = "default_safe"
    artifact_events: tuple[str, ...] = ()
    allow_parallel: bool = False
    retry_class: str = "none"
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def provider_declaration(self) -> ProviderToolDeclaration:
        return ProviderToolDeclaration(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            projection_hints={
                "model_result_projection": self.model_result_projection,
                "side_effect_class": self.side_effect_class.value,
                "confirmation_required": self.confirmation_required,
            },
        )


class WorkflowToolCatalog:
    def __init__(self, tools: list[WorkflowToolDefinition]) -> None:
        self.tools = tools
        self._by_name = {tool.name: tool for tool in tools}

    @classmethod
    def for_mode(
        cls,
        *,
        interactive_shipping: bool,
        bridge: EventEmitterBridge | None = None,
    ) -> WorkflowToolCatalog:
        event_bridge = bridge or EventEmitterBridge()
        tool_definitions = get_all_tool_definitions(
            event_bridge=event_bridge,
            interactive_shipping=interactive_shipping,
        )
        tools: list[WorkflowToolDefinition] = []
        for definition in tool_definitions:
            name = definition["name"]
            side_effect_class = _side_effect_for(name)
            tools.append(
                WorkflowToolDefinition(
                    name=name,
                    description=definition["description"],
                    input_schema=definition["input_schema"],
                    handler=definition["handler"],
                    mode=_mode_for(name),
                    side_effect_class=side_effect_class,
                    confirmation_required=name in _CONFIRMATION_REQUIRED,
                    model_result_projection=(
                        "strip_rows" if name in _STRIP_ROWS else "default_safe"
                    ),
                    artifact_events=_ARTIFACT_EVENTS.get(name, ()),
                    allow_parallel=(
                        side_effect_class == SideEffectClass.READ_ONLY
                        and name in _PARALLEL_READ_ONLY
                    ),
                    retry_class=(
                        "read"
                        if side_effect_class == SideEffectClass.READ_ONLY
                        else "none"
                    ),
                    metadata={
                        "source": "src.orchestrator.agent.tools",
                        "source_tool_name": name,
                    },
                )
            )
        return cls(tools)

    def get(self, name: str) -> WorkflowToolDefinition:
        return self._by_name[name]

    def has(self, name: str) -> bool:
        return name in self._by_name

    def provider_declarations(self) -> list[ProviderToolDeclaration]:
        return [tool.provider_declaration() for tool in self.tools]
