"""Reusable scripted-provider scenarios for the shared conversation service.

Drives ``conversation_handler.process_message`` end to end with a scripted
provider and records only externally observable behavior: streamed events,
persisted assistant messages and artifacts, the tool results the provider
received on its next turn, and gateway side-effect counts. Assertions should
use ``Observation`` fields rather than private runtime classes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.conversation_handler import process_message
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
)
from src.services.conversation_runtime.runtime_session import (
    ConversationRuntimeSession,
)
from src.services.conversation_runtime.tool_catalog import (
    SideEffectClass,
    ToolMode,
    WorkflowToolCatalog,
    WorkflowToolDefinition,
)

_CONTACTS_PATCH = "src.services.conversation_handler._get_mru_contacts_for_prompt"

ToolHandler = Callable[[dict[str, Any], Any], Awaitable[Any]]


def tool_call_turn(
    call_id: str, tool_name: str, parsed_input: dict[str, Any]
) -> list[ProviderStreamEvent]:
    return [
        ProviderStreamEvent(
            type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
            tool_call=ProviderToolCall(
                call_id=call_id, tool_name=tool_name, parsed_input=parsed_input
            ),
        ),
        ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
    ]


def text_turn(text: str) -> list[ProviderStreamEvent]:
    return [
        ProviderStreamEvent(
            type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text=text
        ),
        ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
    ]


@dataclass
class Observation:
    events: list[dict[str, Any]] = field(default_factory=list)
    persisted_messages: list[tuple[str, str]] = field(default_factory=list)
    persisted_artifacts: list[tuple[str, str, dict[str, Any]]] = field(
        default_factory=list
    )
    provider_requests: list[dict[str, Any]] = field(default_factory=list)
    handler_calls: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    data_gateway_acquisitions: int = 0
    ups_gateway_acquisitions: int = 0

    def event_names(self) -> list[str]:
        return [event["event"] for event in self.events]

    def tool_results_seen_by_provider(self) -> list[dict[str, Any]]:
        """Tool results as the provider saw them on its final request."""
        if not self.provider_requests:
            return []
        results: list[dict[str, Any]] = []
        for message in self.provider_requests[-1]["messages"]:
            if message.role != "tool":
                continue
            results.append(
                {
                    "call_id": message.tool_call_id,
                    "tool_name": message.metadata.get("tool_name"),
                    "is_error": message.metadata.get("is_error"),
                    "content": "".join(part.text for part in message.content),
                }
            )
        return results

    def everything_externally_visible(self) -> str:
        return json.dumps(
            {
                "events": self.events,
                "messages": self.persisted_messages,
                "artifacts": self.persisted_artifacts,
                "provider_tool_results": self.tool_results_seen_by_provider(),
            },
            default=str,
        )


async def run_scenario(
    *,
    script: list[list[ProviderStreamEvent]],
    user_message: str = "go",
    interactive: bool = False,
    spy_handlers: dict[str, ToolHandler] | None = None,
    exposed_dangerous_tools: dict[str, ToolHandler] | None = None,
    session_id: str = "acceptance",
    provider: Any | None = None,
) -> Observation:
    """Run one scripted turn through the shared conversation service.

    ``spy_handlers`` replace the named catalog tools' handlers (they receive
    ``(args, bridge)``) so tests can count and simulate side effects while the
    real policy gate and dispatcher still run in front of them.

    ``exposed_dangerous_tools`` additionally *register* tools that are absent
    from the real catalog (e.g. raw ``mcp__ups__*`` carrier tools) so they are
    declared to the provider and reachable by the dispatcher. Their handlers are
    spies, so a denial test fails meaningfully if policy stops blocking them:
    the spy would run and ``Observation.handler_calls`` would be non-empty.

    ``provider`` substitutes a concrete adapter (e.g. an Anthropic client over a
    mocked transport) for the scripted fake; ``script`` is then ignored and
    ``Observation.provider_requests`` stays empty (the transport records them).
    """
    observation = Observation()
    provider = provider or FakeProviderClient(script=script)
    agent = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=interactive,
        session_id=session_id,
    )
    await agent.start()

    session = MagicMock()
    session.session_id = session_id
    session.agent = agent
    contacts_hash = hashlib.sha256(
        json.dumps([], sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    session.agent_source_hash = (
        f"none|interactive={interactive}|contacts={contacts_hash}"
    )
    session.lock = asyncio.Lock()
    session.confirmed_resolutions = {}
    session.interactive_shipping = interactive

    real_for_mode = WorkflowToolCatalog.for_mode.__func__  # type: ignore[attr-defined]

    def spying_for_mode(cls: Any, *, interactive_shipping: bool, bridge: Any = None):
        catalog = real_for_mode(
            cls, interactive_shipping=interactive_shipping, bridge=bridge
        )
        extras = [
            WorkflowToolDefinition(
                name=name,
                description=f"Exposed dangerous tool {name} (spy)",
                input_schema={"type": "object"},
                handler=_spy,
                mode=ToolMode.BOTH,
                side_effect_class=SideEffectClass.MONEY_CHANGING,
            )
            for name, _spy in (exposed_dangerous_tools or {}).items()
        ]
        if extras:
            catalog = WorkflowToolCatalog([*catalog.tools, *extras])
        all_spies = {**(spy_handlers or {}), **(exposed_dangerous_tools or {})}
        for name, spy in all_spies.items():
            if not catalog.has(name):
                continue
            tool = catalog.get(name)

            async def handler(args: dict[str, Any], _name=name, _spy=spy) -> Any:
                observation.handler_calls.setdefault(_name, []).append(dict(args))
                return await _spy(args, bridge)

            object.__setattr__(tool, "handler", handler)
        return catalog

    async def count_data_gateway() -> Any:
        observation.data_gateway_acquisitions += 1
        return MagicMock()

    async def count_ups_gateway() -> Any:
        observation.ups_gateway_acquisitions += 1
        return MagicMock()

    with (
        patch(
            "src.services.conversation_handler.get_data_gateway",
            new_callable=AsyncMock,
        ) as handler_gateway,
        patch(_CONTACTS_PATCH, return_value=[]),
        patch(
            "src.services.conversation_handler._persist_assistant_message",
            side_effect=lambda sid, text: observation.persisted_messages.append(
                (sid, text)
            ),
        ),
        patch(
            "src.services.conversation_handler._persist_artifact_message",
            side_effect=lambda sid, kind, data: observation.persisted_artifacts.append(
                (sid, kind, data)
            ),
        ),
        patch.object(WorkflowToolCatalog, "for_mode", classmethod(spying_for_mode)),
        patch("src.orchestrator.agent.tools.data.get_data_gateway", count_data_gateway),
        patch("src.orchestrator.agent.tools.core.get_data_gateway", count_data_gateway),
        patch("src.services.gateway_provider.get_ups_gateway", count_ups_gateway),
    ):
        handler_gateway.return_value.get_source_info_typed = AsyncMock(
            return_value=None
        )
        async for event in process_message(
            session, user_message, interactive_shipping=interactive
        ):
            observation.events.append(event)

    observation.provider_requests = getattr(provider, "requests", [])
    return observation
