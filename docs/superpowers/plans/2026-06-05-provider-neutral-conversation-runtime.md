# Provider-Neutral Conversation Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 0 provider-neutral local conversation runtime core from `docs/superpowers/specs/2026-06-05-provider-neutral-conversation-runtime-design.md`, using a fake provider as the deterministic acceptance gate before real provider adapters become default.

**Architecture:** Consolidate conversation ownership into `src/services/conversation_handler.py`, then add a provider-neutral runtime package under `src/services/conversation_runtime/`. The runtime owns provider-normalized messages, tool catalog projection, policy checks, direct Python tool dispatch, fake-provider loop tests, interruption tokens, artifact persistence, and SSE parity. Real OpenAI, Anthropic Messages, and Gemini HTTP adapters are separate provider-specific plans after this fake-provider gate passes.

**Tech Stack:** Python 3.12+, FastAPI/SSE, pytest, pytest-asyncio, dataclasses, Protocols, existing ShipAgent services, existing `src/orchestrator/agent/tools/` handlers, existing `DecisionAuditService`, existing conversation persistence service.

---

## Source Of Truth

Authoritative design:

```text
docs/superpowers/specs/2026-06-05-provider-neutral-conversation-runtime-design.md
```

This plan covers Phase 0 core runtime semantics only:

- canonical service-owned conversation handling
- normalized provider runtime types
- fake provider contract
- neutral workflow tool catalog
- runtime policy engine
- local tool dispatcher with model-safe projection
- `ConversationRuntimeSession` using the fake provider
- route delegation and lifecycle behavior
- migration guards proving Claude SDK isolation remains intact

This plan does not implement real OpenAI, Anthropic Messages, or Gemini HTTP adapters. Those adapters depend on current provider API details and should each receive a child implementation plan after this fake-provider runtime gate is green.

## Current Repo State

Relevant existing source:

```text
src/services/conversation_agent.py
src/services/conversation_handler.py
src/services/agent_session_manager.py
src/api/routes/conversations.py
src/orchestrator/agent/client.py
src/orchestrator/agent/hooks.py
src/orchestrator/agent/system_prompt.py
src/orchestrator/agent/tools/__init__.py
src/orchestrator/agent/tools/core.py
src/orchestrator/agent/tools/data.py
src/orchestrator/agent/tools/pipeline.py
```

Relevant existing tests:

```text
tests/test_claude_sdk_optional.py
tests/services/test_conversation_agent.py
tests/services/test_conversation_handler.py
tests/services/test_conversation_handler_resume.py
tests/api/test_conversations.py
tests/orchestrator/agent/test_filter_hooks.py
tests/orchestrator/agent/test_hooks.py
tests/orchestrator/agent/test_tool_definitions_filter.py
tests/orchestrator/agent/test_client_enhanced.py
```

Important current behavior:

- `src/api/routes/conversations.py` still owns `_ensure_agent()` and `_process_agent_message()`.
- `src/services/conversation_handler.py` has a thinner canonical path but does not yet own transient suppression, artifact persistence, model resolution, source signature audit, or route parity behavior.
- Current tool definitions live in `src/orchestrator/agent/tools/__init__.py` and use `EventEmitterBridge` from `src/orchestrator/agent/tools/core.py`.
- `fetch_rows_tool()` can return `sample_rows` and `rows` when `include_rows=True`; the neutral dispatcher must strip those from model-bound tool results.
- Current Claude hook behavior lives in `src/orchestrator/agent/hooks.py`; Phase 0 should port behavior to neutral policy code rather than import Claude hook modules from active runtime source.

## Target File Structure

Create:

```text
src/services/conversation_runtime/
  __init__.py
  fake_provider.py
  dispatcher.py
  models.py
  policy.py
  runtime_session.py
  tool_catalog.py

tests/services/conversation_runtime/
  test_dispatcher.py
  test_fake_provider.py
  test_models.py
  test_policy.py
  test_runtime_session.py
  test_tool_catalog.py
```

Modify:

```text
src/services/conversation_agent.py
src/services/conversation_handler.py
src/services/agent_session_manager.py
src/api/routes/conversations.py
tests/services/test_conversation_agent.py
tests/services/test_conversation_handler.py
tests/api/test_conversations.py
tests/test_claude_sdk_optional.py
```

Do not modify in this plan:

```text
generated/provider_artifacts/
shipagent-frontend/
src/registry/
src/provider_adapters/
pyproject.toml
shipagent-core.spec
```

Real provider adapters and frontend contract changes are separate plans.

---

## Task 1: Move Route-Owned Turn Semantics Into `conversation_handler`

**Files:**

- Modify: `src/services/conversation_handler.py`
- Modify: `src/api/routes/conversations.py`
- Modify: `tests/services/test_conversation_handler.py`
- Modify: `tests/api/test_conversations.py`

- [ ] **Step 1: Add service tests for transient assistant suppression**

Add these tests to `tests/services/test_conversation_handler.py`.

```python
@pytest.mark.asyncio
async def test_process_message_suppresses_transient_messages_when_artifact_emitted(monkeypatch):
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

    class FakeAgent:
        last_turn_count = 0

        def __init__(self):
            self.emitter_bridge = MagicMock(callback=None)

        async def process_message_stream(self, _content):
            if self.emitter_bridge.callback:
                self.emitter_bridge.callback(
                    "preview_ready",
                    {"job_id": "job-1", "total_rows": 1, "preview_rows": []},
                )
            yield {"event": "agent_message", "data": {"text": "draft"}}
            yield {"event": "agent_message", "data": {"text": "final"}}

    session = MagicMock()
    session.session_id = "svc-suppress"
    session.agent = FakeAgent()
    session.agent_source_hash = _make_test_session_hash()
    session.lock = asyncio.Lock()
    session.confirmed_resolutions = {}
    session.interactive_shipping = False
    emitted: list[dict] = []

    with (
        patch("src.services.conversation_handler.get_data_gateway", new_callable=AsyncMock) as mock_gw,
        patch(_CONTACTS_PATCH, return_value=[]),
        patch("src.services.conversation_handler._persist_artifact_message") as persist_artifact,
        patch("src.services.conversation_handler._persist_assistant_message") as persist_assistant,
    ):
        mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
        async for event in process_message(
            session,
            "Ship all orders",
            emit_callback=lambda event_type, data: emitted.append({"event": event_type, "data": data}),
        ):
            emitted.append(event)

    assert [event["event"] for event in emitted] == ["preview_ready"]
    persist_artifact.assert_called_once_with("svc-suppress", "preview_ready", {"job_id": "job-1", "total_rows": 1, "preview_rows": []})
    persist_assistant.assert_not_called()
    session.add_message.assert_not_called()
```

- [ ] **Step 2: Add service tests for final assistant text when no artifact appears**

Add this test to `tests/services/test_conversation_handler.py`.

```python
@pytest.mark.asyncio
async def test_process_message_keeps_final_buffered_message_when_no_artifact(monkeypatch):
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

    class FakeAgent:
        last_turn_count = 0

        def __init__(self):
            self.emitter_bridge = MagicMock(callback=None)

        async def process_message_stream(self, _content):
            yield {"event": "agent_message", "data": {"text": "draft"}}
            yield {"event": "agent_message", "data": {"text": "final answer"}}

    session = MagicMock()
    session.session_id = "svc-final"
    session.agent = FakeAgent()
    session.agent_source_hash = _make_test_session_hash()
    session.lock = asyncio.Lock()
    session.confirmed_resolutions = {}
    session.interactive_shipping = False

    with (
        patch("src.services.conversation_handler.get_data_gateway", new_callable=AsyncMock) as mock_gw,
        patch(_CONTACTS_PATCH, return_value=[]),
        patch("src.services.conversation_handler._persist_assistant_message") as persist_assistant,
    ):
        mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
        events = [event async for event in process_message(session, "hello")]

    assert events == [{"event": "agent_message", "data": {"text": "final answer"}}]
    session.add_message.assert_called_once_with("assistant", "final answer")
    persist_assistant.assert_called_once_with("svc-final", "final answer")
```

- [ ] **Step 3: Run the new service tests and verify they fail**

Run:

```bash
pytest tests/services/test_conversation_handler.py -k "suppresses_transient or keeps_final_buffered" -v
```

Expected: both tests fail because `process_message()` currently yields both assistant messages and does not own artifact persistence.

- [ ] **Step 4: Move artifact constants and persistence helpers into `conversation_handler`**

Add this code to `src/services/conversation_handler.py` below `compute_source_hash()`.

```python
_LIVE_ARTIFACT_EVENTS: set[str] = {
    "preview_partial",
    "preview_ready",
    "pickup_preview",
    "pickup_result",
    "location_result",
    "landed_cost_result",
    "paperless_upload_prompt",
    "paperless_result",
    "tracking_result",
    "contact_saved",
}

_PERSISTABLE_ARTIFACTS: set[str] = {
    "preview_ready",
    "pickup_result",
    "location_result",
    "landed_cost_result",
    "paperless_result",
    "tracking_result",
    "contact_saved",
}

_ARTIFACT_METADATA_KEY: dict[str, str] = {
    "preview_ready": "batchPreview",
    "pickup_result": "pickup",
    "location_result": "location",
    "landed_cost_result": "landedCost",
    "paperless_result": "paperless",
    "tracking_result": "tracking",
    "contact_saved": "contactSaved",
}


def _hide_transient_chat_enabled() -> bool:
    import os

    raw = os.environ.get("AGENT_HIDE_TRANSIENT_CHAT", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _persist_assistant_message(session_id: str, text: str) -> None:
    try:
        from src.db.connection import get_db_context
        from src.services.conversation_persistence_service import ConversationPersistenceService

        with get_db_context() as db:
            ConversationPersistenceService(db).save_message(session_id, "assistant", text)
    except Exception as exc:
        logger.error("Failed to persist assistant msg for %s: %s", session_id, exc)


def _persist_artifact_message(session_id: str, event_type: str, data: dict[str, Any]) -> None:
    metadata_key = _ARTIFACT_METADATA_KEY.get(event_type, event_type)
    metadata = {"action": event_type, metadata_key: data}
    try:
        from src.db.connection import get_db_context
        from src.services.conversation_persistence_service import ConversationPersistenceService

        with get_db_context() as db:
            ConversationPersistenceService(db).save_message(
                session_id,
                role="assistant",
                content="",
                message_type="system_artifact",
                metadata=metadata,
            )
    except Exception as exc:
        logger.error("Failed to persist artifact %s for %s: %s", event_type, session_id, exc)
```

- [ ] **Step 5: Update `process_message()` to own artifact persistence and transient buffering**

Replace the body inside `try: async with session.lock:` in `src/services/conversation_handler.py` with this structure.

```python
        async with session.lock:
            try:
                gw = await get_data_gateway()
                source_info = await gw.get_source_info_typed()
            except Exception:
                source_info = None

            await ensure_agent(session, source_info, interactive_shipping)

            persisted_events: set[str] = set()
            hide_transient_chat = _hide_transient_chat_enabled()
            artifact_emitted = False
            buffered_agent_messages: list[str] = []

            def _service_emit(event_type: str, data: dict[str, Any]) -> None:
                nonlocal artifact_emitted
                if hide_transient_chat and event_type in _LIVE_ARTIFACT_EVENTS:
                    artifact_emitted = True
                if event_type in _PERSISTABLE_ARTIFACTS and event_type not in persisted_events:
                    persisted_events.add(event_type)
                    _persist_artifact_message(session.session_id, event_type, data)
                if emit_callback is not None:
                    emit_callback(event_type, data)

            if emit_callback:
                session.agent.emitter_bridge.callback = _service_emit
            if hasattr(session.agent, "emitter_bridge"):
                session.agent.emitter_bridge.last_user_message = content
                session.agent.emitter_bridge.confirmed_resolutions = session.confirmed_resolutions

            try:
                async for event in session.agent.process_message_stream(content):
                    event_type = event.get("event")
                    data = event.get("data", {})
                    if isinstance(event_type, str) and event_type in _LIVE_ARTIFACT_EVENTS:
                        if hide_transient_chat:
                            artifact_emitted = True
                        if event_type in _PERSISTABLE_ARTIFACTS and event_type not in persisted_events:
                            persisted_events.add(event_type)
                            _persist_artifact_message(session.session_id, event_type, data)

                    if event_type == "agent_message":
                        text = data.get("text", "")
                        if hide_transient_chat:
                            if text:
                                buffered_agent_messages.append(text)
                            continue
                        if text:
                            session.add_message("assistant", text)
                            _persist_assistant_message(session.session_id, text)
                    elif event_type == "error":
                        run_status = AgentDecisionRunStatus.failed
                    elif event_type == "preview_ready":
                        event_job_id = data.get("job_id")
                        if isinstance(event_job_id, str) and event_job_id:
                            set_decision_job_id(event_job_id)
                            DecisionAuditService.set_run_job_id(get_decision_run_id(), event_job_id)

                    yield event

                if hide_transient_chat and not artifact_emitted and buffered_agent_messages:
                    final_text = buffered_agent_messages[-1]
                    if final_text:
                        session.add_message("assistant", final_text)
                        _persist_assistant_message(session.session_id, final_text)
                        yield {"event": "agent_message", "data": {"text": final_text}}
            finally:
                if emit_callback:
                    session.agent.emitter_bridge.callback = None
```

- [ ] **Step 6: Run service tests and verify they pass**

Run:

```bash
pytest tests/services/test_conversation_handler.py -k "suppresses_transient or keeps_final_buffered" -v
```

Expected: both tests pass.

- [ ] **Step 7: Replace route-private message processing with service delegation**

In `src/api/routes/conversations.py`, keep `_schedule_agent_message()` and `_event_generator()` route-owned, but change `_process_agent_message()` so it delegates to `conversation_handler.process_message()` and emits `done` once.

```python
async def _process_agent_message(
    session_id: str,
    content: str,
    run_id: str | None = None,
) -> None:
    queue = _get_event_queue(session_id)
    session = _session_manager.get_or_create_session(session_id)

    if session.terminating:
        DecisionAuditService.complete_run(run_id, status=AgentDecisionRunStatus.cancelled)
        await queue.put({"event": "done", "data": {}})
        return

    from src.services.conversation_handler import process_message

    try:
        def _emit_sync(event_type: str, data: dict[str, Any]) -> None:
            queue.put_nowait({"event": event_type, "data": data})

        async for event in process_message(
            session,
            content,
            interactive_shipping=session.interactive_shipping,
            emit_callback=_emit_sync,
        ):
            await queue.put(event)
    except Exception as exc:
        logger.error("Agent processing failed for session %s: %s", session_id, exc)
        await queue.put({"event": "error", "data": {"message": sanitize_error_message(str(exc))}})
    finally:
        await queue.put({"event": "done", "data": {}})
```

- [ ] **Step 8: Remove duplicate route helpers**

Delete these route-local helpers from `src/api/routes/conversations.py` after service tests are passing:

```text
_compute_source_hash
_build_source_signature
_ensure_agent
_persist_session_context
_persist_assistant_message
_persist_artifact_message
_PERSISTABLE_ARTIFACTS
_ARTIFACT_METADATA_KEY
```

Update imports to remove `create_conversation_agent`, `BatchEngine`, `is_batch_shipping_request`, `is_confirmation_response`, `is_shipping_request`, `set_decision_job_id`, `reset_decision_job_id`, and `reset_decision_run_id` if they are unused after deletion.

- [ ] **Step 9: Update route tests to patch service delegation**

Change route tests that patch `src.api.routes.conversations._ensure_agent` to patch the service path instead.

```python
with patch(
    "src.services.conversation_handler.ensure_agent",
    new=AsyncMock(side_effect=_fake_ensure_agent),
):
    await conversations._process_agent_message(session_id, "Ship all orders")
```

For tests whose purpose was route-private `_ensure_agent`, move the assertion into `tests/services/test_conversation_handler.py` and delete the route-level duplicate.

- [ ] **Step 10: Run route and service conversation tests**

Run:

```bash
pytest tests/services/test_conversation_handler.py tests/services/test_conversation_handler_resume.py tests/api/test_conversations.py -v
```

Expected: all tests pass. If failures mention route-private `_ensure_agent`, the test still targets deleted route internals and must be moved to the service test file.

- [ ] **Step 11: Commit**

```bash
git add src/services/conversation_handler.py src/api/routes/conversations.py tests/services/test_conversation_handler.py tests/api/test_conversations.py
git commit -m "refactor: consolidate conversation turn handling in service"
```

## Task 2: Add Provider-Neutral Runtime Models And Fake Provider

**Files:**

- Create: `src/services/conversation_runtime/__init__.py`
- Create: `src/services/conversation_runtime/models.py`
- Create: `src/services/conversation_runtime/fake_provider.py`
- Create: `tests/services/conversation_runtime/test_models.py`
- Create: `tests/services/conversation_runtime/test_fake_provider.py`

- [ ] **Step 1: Create runtime package and model tests**

Create the directory:

```bash
mkdir -p src/services/conversation_runtime tests/services/conversation_runtime
```

Add `tests/services/conversation_runtime/test_models.py`.

```python
from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderFinalResult,
    ProviderResultMetadata,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
    ProviderToolResult,
)


def test_provider_capabilities_default_to_weakest_common_contract():
    caps = ProviderCapabilities(provider="fake", model="fake-model")

    assert caps.supports_streaming_text is False
    assert caps.supports_streaming_tool_arguments is False
    assert caps.supports_parallel_tool_calls is False
    assert caps.supports_cancellation is False
    assert caps.supports_usage_metadata is False
    assert caps.supports_stable_tool_call_ids is False
    assert caps.supports_provider_session_ids is False


def test_provider_tool_result_safe_payload_shape():
    result = ProviderToolResult(
        call_id="call-1",
        tool_name="fetch_rows",
        content="Fetched 10 rows. Use fetch_id to continue.",
        structured_payload={"fetch_id": "fetch-1", "total_count": 10},
        is_error=False,
    )

    assert result.call_id == "call-1"
    assert result.structured_payload == {"fetch_id": "fetch-1", "total_count": 10}


def test_provider_final_result_keeps_normalized_metadata():
    metadata = ProviderResultMetadata(
        provider="fake",
        model="fake-model",
        session_id="provider-session",
        stop_reason="end_turn",
        result_subtype="success",
        num_turns=2,
        usage={"input_tokens": 10, "output_tokens": 5},
        total_cost_usd=0.01,
        raw_usage_provider={"input_tokens": 10, "output_tokens": 5},
    )
    final = ProviderFinalResult(text="Done", metadata=metadata)

    assert final.metadata.session_id == "provider-session"
    assert final.metadata.num_turns == 2
    assert final.metadata.total_cost_usd == 0.01


def test_tool_call_event_carries_parsed_input_and_raw_arguments():
    call = ProviderToolCall(
        call_id="tool-1",
        tool_name="ship_command_pipeline",
        parsed_input={"all_rows": True},
        raw_arguments='{"all_rows": true}',
    )
    event = ProviderStreamEvent(
        type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
        tool_call=call,
    )

    assert event.tool_call is call
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
pytest tests/services/conversation_runtime/test_models.py -v
```

Expected: import failure because `src/services/conversation_runtime/models.py` does not exist.

- [ ] **Step 3: Add runtime model types**

Create `src/services/conversation_runtime/models.py`.

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

ProviderRole = Literal["system", "developer", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ProviderContentPart:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass(frozen=True)
class ProviderInputMessage:
    role: ProviderRole
    content: list[ProviderContentPart]
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSystemInstruction:
    content: str
    instruction_type: Literal["system", "developer"] = "system"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderToolDeclaration:
    name: str
    description: str
    input_schema: dict[str, Any]
    projection_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str | None
    tool_name: str
    parsed_input: dict[str, Any]
    raw_arguments: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderToolResult:
    call_id: str | None
    tool_name: str
    content: str
    structured_payload: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    sanitized_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResultMetadata:
    provider: str
    model: str
    session_id: str | None = None
    stop_reason: str | None = None
    result_subtype: str | None = None
    num_turns: int | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    total_cost_usd: float | None = None
    raw_usage_provider: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderFinalResult:
    text: str
    metadata: ProviderResultMetadata
    is_error: bool = False
    sanitized_error: str | None = None


class ProviderStreamEventType(StrEnum):
    TEXT_DELTA = "text_delta"
    TEXT_BLOCK_COMPLETE = "text_block_complete"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_ARGUMENTS_DELTA = "tool_arguments_delta"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    RESULT_METADATA = "result_metadata"
    PROVIDER_ERROR = "provider_error"
    STREAM_COMPLETE = "stream_complete"


@dataclass(frozen=True)
class ProviderStreamEvent:
    type: ProviderStreamEventType
    text: str | None = None
    tool_call: ProviderToolCall | None = None
    metadata: ProviderResultMetadata | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    model: str
    supports_streaming_text: bool = False
    supports_streaming_tool_arguments: bool = False
    supports_parallel_tool_calls: bool = False
    supports_cancellation: bool = False
    supports_usage_metadata: bool = False
    supports_stable_tool_call_ids: bool = False
    supports_provider_session_ids: bool = False


class ModelProviderClient(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities:
        ...

    async def stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]:
        ...

    async def cancel(self) -> None:
        ...
```

- [ ] **Step 4: Add package exports**

Create `src/services/conversation_runtime/__init__.py`.

```python
"""Provider-neutral local conversation runtime."""

from src.services.conversation_runtime.models import (
    ModelProviderClient,
    ProviderCapabilities,
    ProviderContentPart,
    ProviderFinalResult,
    ProviderInputMessage,
    ProviderResultMetadata,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
    ProviderToolDeclaration,
    ProviderToolResult,
)

__all__ = [
    "ModelProviderClient",
    "ProviderCapabilities",
    "ProviderContentPart",
    "ProviderFinalResult",
    "ProviderInputMessage",
    "ProviderResultMetadata",
    "ProviderStreamEvent",
    "ProviderStreamEventType",
    "ProviderSystemInstruction",
    "ProviderToolCall",
    "ProviderToolDeclaration",
    "ProviderToolResult",
]
```

- [ ] **Step 5: Add fake provider tests**

Create `tests/services/conversation_runtime/test_fake_provider.py`.

```python
import pytest

from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderContentPart,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
)


@pytest.mark.asyncio
async def test_fake_provider_streams_scripted_events():
    client = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="Hel"),
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="lo"),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ]
    )

    events = [
        event
        async for event in client.stream_turn(
            messages=[ProviderInputMessage(role="user", content=[ProviderContentPart(text="Hi")])],
            system_instructions=[],
            tools=[],
        )
    ]

    assert [event.text for event in events if event.text] == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_fake_provider_advances_one_script_batch_per_turn():
    client = FakeProviderClient(
        script=[
            [ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="first")],
            [ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="second")],
        ]
    )

    first = [event async for event in client.stream_turn(messages=[], system_instructions=[], tools=[])]
    second = [event async for event in client.stream_turn(messages=[], system_instructions=[], tools=[])]

    assert first[0].text == "first"
    assert second[0].text == "second"


@pytest.mark.asyncio
async def test_fake_provider_records_messages_and_tool_declarations():
    call = ProviderToolCall(call_id="call-1", tool_name="get_schema", parsed_input={})
    client = FakeProviderClient(
        script=[
            [ProviderStreamEvent(type=ProviderStreamEventType.TOOL_CALL_COMPLETE, tool_call=call)],
        ]
    )

    await anext(client.stream_turn(messages=[], system_instructions=[], tools=[]))

    assert len(client.requests) == 1
    assert client.requests[0]["messages"] == []
    assert client.requests[0]["tools"] == []
```

- [ ] **Step 6: Add fake provider implementation**

Create `src/services/conversation_runtime/fake_provider.py`.

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderSystemInstruction,
    ProviderToolDeclaration,
)


class FakeProviderClient:
    """Scripted provider used for runtime contract tests."""

    def __init__(
        self,
        *,
        script: list[list[ProviderStreamEvent]],
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._script = list(script)
        self._capabilities = capabilities or ProviderCapabilities(
            provider="fake",
            model="fake-model",
            supports_streaming_text=True,
            supports_stable_tool_call_ids=True,
            supports_usage_metadata=True,
        )
        self.requests: list[dict[str, Any]] = []
        self.cancelled = False

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def stream_turn(
        self,
        *,
        messages: list[ProviderInputMessage],
        system_instructions: list[ProviderSystemInstruction],
        tools: list[ProviderToolDeclaration],
    ) -> AsyncIterator[ProviderStreamEvent]:
        self.requests.append(
            {
                "messages": messages,
                "system_instructions": system_instructions,
                "tools": tools,
            }
        )
        events = self._script.pop(0) if self._script else []
        for event in events:
            yield event

    async def cancel(self) -> None:
        self.cancelled = True
```

- [ ] **Step 7: Run runtime model and fake provider tests**

Run:

```bash
pytest tests/services/conversation_runtime/test_models.py tests/services/conversation_runtime/test_fake_provider.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/services/conversation_runtime tests/services/conversation_runtime
git commit -m "feat: add provider-neutral runtime model contract"
```

## Task 3: Build Neutral Workflow Tool Catalog

**Files:**

- Create: `src/services/conversation_runtime/tool_catalog.py`
- Create: `tests/services/conversation_runtime/test_tool_catalog.py`

- [ ] **Step 1: Add catalog inventory tests**

Create `tests/services/conversation_runtime/test_tool_catalog.py`.

```python
from src.services.conversation_runtime.tool_catalog import (
    ToolMode,
    WorkflowToolCatalog,
)


EXPECTED_BATCH_TOOLS = {
    "get_source_info",
    "get_schema",
    "ship_command_pipeline",
    "fetch_rows",
    "resolve_filter_intent",
    "confirm_filter_interpretation",
    "get_job_status",
    "batch_execute",
    "get_platform_status",
    "connect_shopify",
    "connect_amazon",
    "schedule_pickup",
    "cancel_pickup",
    "rate_pickup",
    "get_pickup_status",
    "find_locations",
    "get_service_center_facilities",
    "request_document_upload",
    "upload_paperless_document",
    "push_document_to_shipment",
    "delete_paperless_document",
    "resolve_contact",
    "save_contact",
    "list_contacts",
    "delete_contact",
    "track_package",
    "get_landed_cost",
}

EXPECTED_INTERACTIVE_TOOLS = {
    "get_job_status",
    "get_platform_status",
    "schedule_pickup",
    "cancel_pickup",
    "rate_pickup",
    "get_pickup_status",
    "find_locations",
    "get_service_center_facilities",
    "request_document_upload",
    "upload_paperless_document",
    "push_document_to_shipment",
    "delete_paperless_document",
    "resolve_contact",
    "save_contact",
    "list_contacts",
    "delete_contact",
    "track_package",
    "get_landed_cost",
    "preview_interactive_shipment",
}


def test_batch_catalog_exposes_current_batch_tool_names():
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    assert {tool.name for tool in catalog.tools} == EXPECTED_BATCH_TOOLS


def test_interactive_catalog_exposes_current_interactive_tool_names():
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=True)

    assert {tool.name for tool in catalog.tools} == EXPECTED_INTERACTIVE_TOOLS


def test_catalog_never_exposes_raw_ups_mcp_tools():
    for interactive in (False, True):
        catalog = WorkflowToolCatalog.for_mode(interactive_shipping=interactive)
        names = {tool.name for tool in catalog.tools}

        assert not any(name.startswith("mcp__ups__") for name in names)


def test_tool_declarations_have_provider_safe_shape():
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)
    declarations = catalog.provider_declarations()

    fetch_rows = next(item for item in declarations if item.name == "fetch_rows")
    assert fetch_rows.input_schema["type"] == "object"
    assert fetch_rows.projection_hints["model_result_projection"] == "strip_rows"


def test_side_effecting_tools_are_not_parallelizable():
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    assert catalog.get("batch_execute").allow_parallel is False
    assert catalog.get("schedule_pickup").allow_parallel is False
    assert catalog.get("get_schema").allow_parallel is True
    assert catalog.get("get_job_status").mode in {ToolMode.BATCH, ToolMode.BOTH}
```

- [ ] **Step 2: Run catalog tests and verify they fail**

Run:

```bash
pytest tests/services/conversation_runtime/test_tool_catalog.py -v
```

Expected: import failure because `tool_catalog.py` does not exist.

- [ ] **Step 3: Add catalog implementation**

Create `src/services/conversation_runtime/tool_catalog.py`.

```python
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
    "preview_interactive_shipment": ("preview_ready",),
    "schedule_pickup": ("pickup_preview", "pickup_result"),
    "cancel_pickup": ("pickup_result",),
    "rate_pickup": ("pickup_preview",),
    "find_locations": ("location_result",),
    "get_service_center_facilities": ("location_result",),
    "request_document_upload": ("paperless_upload_prompt",),
    "upload_paperless_document": ("paperless_result",),
    "push_document_to_shipment": ("paperless_result",),
    "delete_paperless_document": ("paperless_result",),
    "save_contact": ("contact_saved",),
    "track_package": ("tracking_result",),
    "get_landed_cost": ("landed_cost_result",),
}

_CONFIRMATION_REQUIRED = {
    "batch_execute",
    "schedule_pickup",
    "cancel_pickup",
    "preview_interactive_shipment",
}

_STRIP_ROWS = {"fetch_rows", "ship_command_pipeline", "preview_interactive_shipment"}


def _mode_for(name: str) -> ToolMode:
    if name in _BATCH_ONLY:
        return ToolMode.BATCH
    if name in _INTERACTIVE_ONLY:
        return ToolMode.INTERACTIVE
    return ToolMode.BOTH


def _side_effect_for(name: str) -> SideEffectClass:
    if name in {"batch_execute", "schedule_pickup", "cancel_pickup"}:
        return SideEffectClass.MONEY_CHANGING
    if name in {"connect_shopify", "connect_amazon", "save_contact", "delete_contact", "upload_paperless_document", "push_document_to_shipment", "delete_paperless_document"}:
        return SideEffectClass.STATE_CHANGING
    if name in _ARTIFACT_EVENTS:
        return SideEffectClass.ARTIFACT
    return SideEffectClass.READ_ONLY


class WorkflowToolCatalog:
    def __init__(self, tools: list[WorkflowToolDefinition]) -> None:
        self.tools = tools
        self._by_name = {tool.name: tool for tool in tools}

    @classmethod
    def for_mode(cls, *, interactive_shipping: bool, bridge: EventEmitterBridge | None = None) -> "WorkflowToolCatalog":
        bridge = bridge or EventEmitterBridge()
        definitions = get_all_tool_definitions(
            event_bridge=bridge,
            interactive_shipping=interactive_shipping,
        )
        tools = []
        for definition in definitions:
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
                    model_result_projection="strip_rows" if name in _STRIP_ROWS else "default_safe",
                    artifact_events=_ARTIFACT_EVENTS.get(name, ()),
                    allow_parallel=side_effect_class == SideEffectClass.READ_ONLY and name in {"get_source_info", "get_schema", "get_job_status", "get_platform_status", "list_contacts"},
                    retry_class="read" if side_effect_class == SideEffectClass.READ_ONLY else "none",
                )
            )
        return cls(tools)

    def get(self, name: str) -> WorkflowToolDefinition:
        return self._by_name[name]

    def has(self, name: str) -> bool:
        return name in self._by_name

    def provider_declarations(self) -> list[ProviderToolDeclaration]:
        return [tool.provider_declaration() for tool in self.tools]
```

- [ ] **Step 4: Run catalog tests**

Run:

```bash
pytest tests/services/conversation_runtime/test_tool_catalog.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/services/conversation_runtime/tool_catalog.py tests/services/conversation_runtime/test_tool_catalog.py
git commit -m "feat: add neutral workflow tool catalog"
```

## Task 4: Port Claude Hook Behavior Into `RuntimePolicyEngine`

**Files:**

- Create: `src/services/conversation_runtime/policy.py`
- Create: `tests/services/conversation_runtime/test_policy.py`

- [ ] **Step 1: Add policy tests for denial shape and filter ordering**

Create `tests/services/conversation_runtime/test_policy.py`.

```python
import pytest

from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine


def _decision(result):
    return result.payload.get("hookSpecificOutput", {})


@pytest.mark.asyncio
async def test_denies_raw_sql_before_filter_structure_check():
    engine = RuntimePolicyEngine(interactive_shipping=False)
    call = ProviderToolCall(
        call_id="call-1",
        tool_name="ship_command_pipeline",
        parsed_input={"filter_spec": {"where_clause": "state='CA'"}},
    )

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert _decision(result)["permissionDecision"] == "deny"
    assert "where_clause" in _decision(result)["permissionDecisionReason"]


@pytest.mark.asyncio
async def test_denies_filter_spec_without_root():
    engine = RuntimePolicyEngine(interactive_shipping=False)
    call = ProviderToolCall(
        call_id="call-2",
        tool_name="ship_command_pipeline",
        parsed_input={"filter_spec": {"status": "RESOLVED"}},
    )

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert _decision(result)["hookEventName"] == "PreToolUse"
    assert _decision(result)["permissionDecision"] == "deny"
    assert "root" in _decision(result)["permissionDecisionReason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "expected_text"),
    [
        ("mcp__ups__create_shipment", "preview_interactive_shipment"),
        ("mcp__ups__schedule_pickup", "schedule_pickup"),
        ("mcp__ups__cancel_pickup", "cancel_pickup"),
        ("mcp__ups__track_package", "track_package"),
        ("mcp__ups__find_locations", "find_locations"),
        ("mcp__ups__get_service_center_facilities", "get_service_center_facilities"),
        ("mcp__ups__get_landed_cost_quote", "get_landed_cost"),
    ],
)
async def test_denies_direct_ups_tools(tool_name, expected_text):
    engine = RuntimePolicyEngine(interactive_shipping=True)
    call = ProviderToolCall(call_id="call-3", tool_name=tool_name, parsed_input={})

    result = await engine.check_pre_tool(call)

    assert result.allowed is False
    assert expected_text in _decision(result)["permissionDecisionReason"]


def test_post_tool_error_detection_for_dict_and_string():
    engine = RuntimePolicyEngine(interactive_shipping=False)

    assert engine.detect_error_response({"isError": True}) is True
    assert engine.detect_error_response({"error": "bad"}) is True
    assert engine.detect_error_response("UPS error: unavailable") is True
    assert engine.detect_error_response({"ok": True}) is False
```

- [ ] **Step 2: Run policy tests and verify they fail**

Run:

```bash
pytest tests/services/conversation_runtime/test_policy.py -v
```

Expected: import failure because `policy.py` does not exist.

- [ ] **Step 3: Add policy implementation**

Create `src/services/conversation_runtime/policy.py`.

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.orchestrator.models.filter_spec import FilterOperator
from src.services.conversation_runtime.models import ProviderToolCall


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str | None:
        return self.payload.get("hookSpecificOutput", {}).get("permissionDecisionReason")


def _deny(reason: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        payload={
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
    )


def _find_banned_keys_recursive(obj: Any, banned: frozenset[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        found.update(banned & set(obj.keys()))
        for value in obj.values():
            found.update(_find_banned_keys_recursive(value, banned))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_find_banned_keys_recursive(item, banned))
    return found


class RuntimePolicyEngine:
    _FILTER_TOOLS = frozenset({"resolve_filter_intent", "ship_command_pipeline", "fetch_rows"})
    _BANNED_SQL_KEYS = frozenset({"where_clause", "sql", "query", "raw_sql"})

    def __init__(self, *, interactive_shipping: bool) -> None:
        self.interactive_shipping = interactive_shipping

    async def check_pre_tool(self, call: ProviderToolCall) -> PolicyDecision:
        raw_sql = self._deny_raw_sql(call)
        if raw_sql is not None:
            return raw_sql

        filter_structure = self._validate_filter_structure(call)
        if filter_structure is not None:
            return filter_structure

        direct_ups = self._deny_direct_ups(call)
        if direct_ups is not None:
            return direct_ups

        return PolicyDecision(allowed=True)

    def _deny_raw_sql(self, call: ProviderToolCall) -> PolicyDecision | None:
        if call.tool_name not in self._FILTER_TOOLS:
            return None
        found = _find_banned_keys_recursive(call.parsed_input, self._BANNED_SQL_KEYS)
        if not found:
            return None
        return _deny(
            f"Raw SQL keys {sorted(found)} are not allowed in {call.tool_name}. "
            "Use resolve_filter_intent to create a filter_spec instead."
        )

    def _validate_filter_structure(self, call: ProviderToolCall) -> PolicyDecision | None:
        if call.tool_name == "resolve_filter_intent":
            intent = call.parsed_input.get("intent")
            if not isinstance(intent, dict):
                return None
            valid_ops = {op.value for op in FilterOperator}

            def check_node(node: Any) -> str | None:
                if not isinstance(node, dict):
                    return None
                if "operator" in node and node["operator"] not in valid_ops:
                    return f"Invalid operator {node['operator']!r}. Valid: {sorted(valid_ops)}."
                for child in node.get("conditions", []) if isinstance(node.get("conditions"), list) else []:
                    error = check_node(child)
                    if error:
                        return error
                return None

            error = check_node(intent.get("root"))
            if error:
                return _deny(f"FilterIntent validation failed: {error}")

        if call.tool_name in {"ship_command_pipeline", "fetch_rows"}:
            if call.parsed_input.get("all_rows"):
                return None
            filter_spec = call.parsed_input.get("filter_spec")
            if isinstance(filter_spec, dict) and "root" not in filter_spec:
                return _deny(
                    "filter_spec must contain a 'root' field. "
                    "Use resolve_filter_intent to create a valid filter_spec."
                )
        return None

    def _deny_direct_ups(self, call: ProviderToolCall) -> PolicyDecision | None:
        reasons = {
            "mcp__ups__create_shipment": "Direct shipment creation is not allowed in interactive mode. Use the preview_interactive_shipment tool instead.",
            "mcp__ups__void_shipment": "Direct mcp__ups__void_shipment is not allowed. Use a ShipAgent wrapper that enforces preview and confirmation.",
            "mcp__ups__schedule_pickup": "Direct mcp__ups__schedule_pickup is not allowed. Use the schedule_pickup orchestrator tool instead, which enforces user confirmation before committing.",
            "mcp__ups__cancel_pickup": "Direct mcp__ups__cancel_pickup is not allowed. Use the cancel_pickup orchestrator tool instead, which enforces user confirmation before committing.",
            "mcp__ups__track_package": "Direct mcp__ups__track_package is not allowed. Use the track_package orchestrator tool instead, which emits tracking result events for the UI.",
            "mcp__ups__find_locations": "Direct mcp__ups__find_locations is not allowed. Use the find_locations orchestrator tool instead, which emits location result events for the UI.",
            "mcp__ups__get_service_center_facilities": "Direct mcp__ups__get_service_center_facilities is not allowed. Use the get_service_center_facilities orchestrator tool instead, which emits location result events for the UI.",
            "mcp__ups__get_landed_cost_quote": "Direct mcp__ups__get_landed_cost_quote is not allowed. Use the get_landed_cost orchestrator tool instead, which emits landed cost result events for the UI.",
        }
        reason = reasons.get(call.tool_name)
        return _deny(reason) if reason else None

    def detect_error_response(self, response: Any) -> bool:
        if isinstance(response, dict):
            return bool(response.get("error") or response.get("isError"))
        if isinstance(response, str):
            lowered = response.lower()
            return "error" in lowered or "failed" in lowered or "exception" in lowered
        return False

    def serialize_response(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        return json.dumps(response, default=str)
```

- [ ] **Step 4: Run policy tests**

Run:

```bash
pytest tests/services/conversation_runtime/test_policy.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Add migration guard against active runtime importing Claude hook module**

Add this test to `tests/test_claude_sdk_optional.py`.

```python
def test_conversation_runtime_package_does_not_import_claude_sdk_or_hooks():
    runtime_dir = PROJECT_ROOT / "src" / "services" / "conversation_runtime"
    source = "\n".join(path.read_text() for path in runtime_dir.glob("*.py"))

    assert "claude_agent_sdk" not in source
    assert "src.orchestrator.agent.hooks" not in source
```

- [ ] **Step 6: Run optional SDK and policy tests**

Run:

```bash
pytest tests/test_claude_sdk_optional.py tests/services/conversation_runtime/test_policy.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/services/conversation_runtime/policy.py tests/services/conversation_runtime/test_policy.py tests/test_claude_sdk_optional.py
git commit -m "feat: add provider-neutral runtime policy engine"
```

## Task 5: Add `LocalToolDispatcher` With Model-Safe Projection

**Files:**

- Create: `src/services/conversation_runtime/dispatcher.py`
- Create: `tests/services/conversation_runtime/test_dispatcher.py`

- [ ] **Step 1: Add dispatcher tests**

Create `tests/services/conversation_runtime/test_dispatcher.py`.

```python
import pytest

from src.services.conversation_runtime.dispatcher import LocalToolDispatcher
from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine


class FakeTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-1","total_count":2,"returned_count":2,"sample_rows":[{"name":"Jane","address":"1 Main"}],"rows":[{"name":"Jane","address":"1 Main"}]}',
                }
            ],
        }


class FakeCatalog:
    def __init__(self):
        self.tool = FakeTool()

    def has(self, name):
        return name == "fetch_rows"

    def get(self, name):
        return self.tool


@pytest.mark.asyncio
async def test_dispatcher_strips_rows_from_provider_result():
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event_type, _data: None,
    )
    result = await dispatcher.dispatch(
        ProviderToolCall(call_id="call-1", tool_name="fetch_rows", parsed_input={"all_rows": True, "include_rows": True})
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1", "total_count": 2, "returned_count": 2}
    assert "sample_rows" not in result.content
    assert "1 Main" not in result.content


@pytest.mark.asyncio
async def test_dispatcher_denies_unknown_tool_before_handler_execution():
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event_type, _data: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(call_id="call-2", tool_name="mcp__ups__rate_shipment", parsed_input={})
    )

    assert result.is_error is True
    assert "not available" in result.content


@pytest.mark.asyncio
async def test_dispatcher_turns_policy_denial_into_provider_tool_error():
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event_type, _data: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(call_id="call-3", tool_name="fetch_rows", parsed_input={"sql": "SELECT * FROM orders"})
    )

    assert result.is_error is True
    assert result.sanitized_error is not None
    assert "Raw SQL" in result.sanitized_error
```

- [ ] **Step 2: Run dispatcher tests and verify they fail**

Run:

```bash
pytest tests/services/conversation_runtime/test_dispatcher.py -v
```

Expected: import failure because `dispatcher.py` does not exist.

- [ ] **Step 3: Add dispatcher implementation**

Create `src/services/conversation_runtime/dispatcher.py`.

```python
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.services.conversation_runtime.models import ProviderToolCall, ProviderToolResult
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.utils.redaction import sanitize_error_message


_DROP_MODEL_KEYS = {
    "rows",
    "sample_rows",
    "preview_rows",
    "labels",
    "label",
    "label_url",
    "label_download_url",
    "credentials",
    "request_body",
    "response_body",
    "raw_response",
    "file_content_base64",
    "document_bytes",
}


class LocalToolDispatcher:
    def __init__(
        self,
        *,
        catalog: Any,
        policy: RuntimePolicyEngine,
        emit_frontend: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._catalog = catalog
        self._policy = policy
        self._emit_frontend = emit_frontend

    async def dispatch(self, call: ProviderToolCall) -> ProviderToolResult:
        if not self._catalog.has(call.tool_name):
            message = f"Tool {call.tool_name!r} is not available in this conversation mode."
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=message,
                is_error=True,
                sanitized_error=message,
            )

        decision = await self._policy.check_pre_tool(call)
        if not decision.allowed:
            message = sanitize_error_message(decision.reason or "Tool call denied by policy.")
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=message,
                is_error=True,
                sanitized_error=message,
                metadata={"policy_decision": decision.payload},
            )

        tool = self._catalog.get(call.tool_name)
        try:
            raw_result = await tool.handler(call.parsed_input)
        except Exception as exc:
            message = sanitize_error_message(str(exc))
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=message,
                is_error=True,
                sanitized_error=message,
            )

        is_error = self._policy.detect_error_response(raw_result)
        payload = self._extract_payload(raw_result)
        safe_payload = self._project_payload(payload)
        content = self._summarize_payload(call.tool_name, safe_payload, is_error=is_error)
        return ProviderToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            content=content,
            structured_payload=safe_payload if isinstance(safe_payload, dict) else {"result": safe_payload},
            is_error=is_error,
            sanitized_error=content if is_error else None,
        )

    def _extract_payload(self, raw_result: Any) -> Any:
        if not isinstance(raw_result, dict):
            return raw_result
        content = raw_result.get("content")
        if isinstance(content, list) and content:
            text = content[0].get("text") if isinstance(content[0], dict) else None
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return raw_result

    def _project_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, nested in value.items():
                if key in _DROP_MODEL_KEYS:
                    continue
                result[key] = self._project_payload(nested)
            return result
        if isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value):
                return {"count": len(value)}
            return value[:10]
        return value

    def _summarize_payload(self, tool_name: str, payload: Any, *, is_error: bool) -> str:
        if is_error:
            return sanitize_error_message(json.dumps(payload, default=str))
        if isinstance(payload, dict):
            keys = ", ".join(sorted(payload.keys()))
            return f"{tool_name} completed. Provider-safe fields: {keys}."
        return f"{tool_name} completed."
```

- [ ] **Step 4: Run dispatcher tests**

Run:

```bash
pytest tests/services/conversation_runtime/test_dispatcher.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/services/conversation_runtime/dispatcher.py tests/services/conversation_runtime/test_dispatcher.py
git commit -m "feat: add local tool dispatcher with safe projection"
```

## Task 6: Implement `ConversationRuntimeSession` With Fake Provider

**Files:**

- Create: `src/services/conversation_runtime/runtime_session.py`
- Create: `tests/services/conversation_runtime/test_runtime_session.py`

- [ ] **Step 1: Add runtime session tests for text streaming and storage shape**

Create `tests/services/conversation_runtime/test_runtime_session.py`.

```python
import pytest

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderResultMetadata,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
)
from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession


@pytest.mark.asyncio
async def test_runtime_streams_text_delta_and_complete_message():
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="Hel"),
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="lo"),
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="Hello"),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-text",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Hi")]

    assert events == [
        {"event": "agent_message_delta", "data": {"text": "Hel"}},
        {"event": "agent_message_delta", "data": {"text": "lo"}},
        {"event": "agent_message", "data": {"text": "Hello"}},
    ]
    assert runtime.last_turn_count == 1


@pytest.mark.asyncio
async def test_runtime_dispatches_tool_and_feeds_result_back_to_provider():
    call = ProviderToolCall(call_id="tool-1", tool_name="get_schema", parsed_input={})
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TOOL_CALL_COMPLETE, tool_call=call),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="Schema ready."),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-tool",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Show schema")]

    assert [event["event"] for event in events] == ["tool_call", "agent_message"]
    assert provider.requests[1]["messages"][-1].role == "tool"
    assert provider.requests[1]["messages"][-1].tool_call_id == "tool-1"


@pytest.mark.asyncio
async def test_runtime_captures_result_metadata_without_sse_leak():
    metadata = ProviderResultMetadata(
        provider="fake",
        model="fake-model",
        session_id="provider-session",
        stop_reason="end_turn",
        result_subtype="success",
        num_turns=3,
        usage={"input_tokens": 1},
        total_cost_usd=0.001,
    )
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(type=ProviderStreamEventType.RESULT_METADATA, metadata=metadata),
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="Done"),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-metadata",
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream("Hi")]

    assert events == [{"event": "agent_message", "data": {"text": "Done"}}]
    assert runtime.last_result_metadata == metadata
    assert runtime.last_turn_count == 3
```

- [ ] **Step 2: Run runtime tests and verify they fail**

Run:

```bash
pytest tests/services/conversation_runtime/test_runtime_session.py -v
```

Expected: import failure because `runtime_session.py` does not exist.

- [ ] **Step 3: Add runtime session implementation**

Create `src/services/conversation_runtime/runtime_session.py`.

```python
from __future__ import annotations

import itertools
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.services.conversation_runtime.dispatcher import LocalToolDispatcher
from src.services.conversation_runtime.models import (
    ModelProviderClient,
    ProviderContentPart,
    ProviderInputMessage,
    ProviderResultMetadata,
    ProviderStreamEventType,
    ProviderSystemInstruction,
    ProviderToolCall,
)
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.services.conversation_runtime.tool_catalog import WorkflowToolCatalog

logger = logging.getLogger(__name__)


class ConversationRuntimeSession:
    def __init__(
        self,
        *,
        provider: ModelProviderClient,
        system_prompt: str | None,
        interactive_shipping: bool,
        session_id: str | None,
        max_turns: int = 50,
    ) -> None:
        self._provider = provider
        self._system_prompt = system_prompt or ""
        self._interactive_shipping = interactive_shipping
        self._max_turns = max_turns
        self._started = False
        self._last_turn_count = 0
        self._turn_generation = itertools.count(1)
        self._active_generation = 0
        self._interrupted_generations: set[int] = set()
        self.last_result_metadata: ProviderResultMetadata | None = None
        self.emitter_bridge = EventEmitterBridge()
        self.emitter_bridge.session_id = session_id

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("Agent already started.")
        self._started = True

    async def stop(self, timeout: float = 5.0) -> None:
        self._started = False
        self._interrupted_generations.add(self._active_generation)
        self.emitter_bridge.callback = None

    async def process_command(self, user_input: str) -> str:
        parts: list[str] = []
        async for event in self.process_message_stream(user_input):
            if event.get("event") == "agent_message":
                parts.append(event.get("data", {}).get("text", ""))
        return "".join(parts)

    async def process_message_stream(self, user_input: str) -> AsyncIterator[dict[str, Any]]:
        if not self._started:
            raise RuntimeError("Agent not started. Call start() first.")

        generation = next(self._turn_generation)
        self._active_generation = generation
        self._last_turn_count = 0
        messages: list[ProviderInputMessage] = [
            ProviderInputMessage(role="user", content=[ProviderContentPart(text=user_input)])
        ]
        catalog = WorkflowToolCatalog.for_mode(
            interactive_shipping=self._interactive_shipping,
            bridge=self.emitter_bridge,
        )
        dispatcher = LocalToolDispatcher(
            catalog=catalog,
            policy=RuntimePolicyEngine(interactive_shipping=self._interactive_shipping),
            emit_frontend=lambda event_type, data: self._emit_bridge_event(generation, event_type, data),
        )
        system_instructions = [ProviderSystemInstruction(content=self._system_prompt)]

        for _provider_turn in range(self._max_turns):
            tool_calls: list[ProviderToolCall] = []
            async for event in self._provider.stream_turn(
                messages=messages,
                system_instructions=system_instructions,
                tools=catalog.provider_declarations(),
            ):
                if self._is_generation_interrupted(generation):
                    return

                if event.type == ProviderStreamEventType.TEXT_DELTA and event.text:
                    yield {"event": "agent_message_delta", "data": {"text": event.text}}
                elif event.type == ProviderStreamEventType.TEXT_BLOCK_COMPLETE and event.text:
                    self._last_turn_count += 1
                    yield {"event": "agent_message", "data": {"text": event.text}}
                elif event.type == ProviderStreamEventType.TOOL_CALL_COMPLETE and event.tool_call:
                    tool_calls.append(event.tool_call)
                elif event.type == ProviderStreamEventType.RESULT_METADATA and event.metadata:
                    self.last_result_metadata = event.metadata
                    if event.metadata.num_turns is not None:
                        self._last_turn_count = event.metadata.num_turns
                elif event.type == ProviderStreamEventType.PROVIDER_ERROR:
                    message = event.error_message or "Provider error"
                    yield {"event": "error", "data": {"message": message}}
                    return
                elif event.type == ProviderStreamEventType.STREAM_COMPLETE:
                    break

            if not tool_calls:
                return

            for call in tool_calls:
                if self._is_generation_interrupted(generation):
                    return
                result = await dispatcher.dispatch(call)
                if self._is_generation_interrupted(generation):
                    return
                messages.append(
                    ProviderInputMessage(
                        role="tool",
                        content=[ProviderContentPart(text=result.content)],
                        tool_call_id=result.call_id,
                        metadata={
                            "tool_name": result.tool_name,
                            "structured_payload": result.structured_payload,
                            "is_error": result.is_error,
                        },
                    )
                )
                yield {
                    "event": "tool_call",
                    "data": {
                        "tool_name": call.tool_name,
                        "tool_input": call.parsed_input,
                        "tool_use_id": call.call_id,
                    },
                }

        yield {"event": "error", "data": {"message": "Conversation exceeded the maximum provider turn count."}}

    async def interrupt(self) -> None:
        self._interrupted_generations.add(self._active_generation)
        if self._provider.capabilities.supports_cancellation:
            try:
                await self._provider.cancel()
            except Exception as exc:
                logger.warning("Provider cancel failed: %s", exc)

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def last_turn_count(self) -> int:
        return self._last_turn_count

    def _is_generation_interrupted(self, generation: int) -> bool:
        return generation in self._interrupted_generations

    def _emit_bridge_event(self, generation: int, event_type: str, data: dict[str, Any]) -> None:
        if self._is_generation_interrupted(generation):
            return
        if self.emitter_bridge.callback is not None:
            self.emitter_bridge.callback(event_type, data)
```

- [ ] **Step 4: Run runtime session tests**

Run:

```bash
pytest tests/services/conversation_runtime/test_runtime_session.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Add interruption test**

Append this test to `tests/services/conversation_runtime/test_runtime_session.py`.

```python
@pytest.mark.asyncio
async def test_interrupt_drops_late_events_from_old_generation():
    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="stale"),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="fresh"),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ]
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="runtime-interrupt",
    )
    await runtime.start()

    stream = runtime.process_message_stream("first")
    await runtime.interrupt()
    stale_events = [event async for event in stream]
    fresh_events = [event async for event in runtime.process_message_stream("second")]

    assert stale_events == []
    assert fresh_events == [{"event": "agent_message", "data": {"text": "fresh"}}]
```

- [ ] **Step 6: Run interruption test**

Run:

```bash
pytest tests/services/conversation_runtime/test_runtime_session.py::test_interrupt_drops_late_events_from_old_generation -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/services/conversation_runtime/runtime_session.py tests/services/conversation_runtime/test_runtime_session.py
git commit -m "feat: add fake-provider conversation runtime session"
```

## Task 7: Wire Fake Runtime Through `create_conversation_agent`

**Files:**

- Modify: `src/services/conversation_agent.py`
- Modify: `tests/services/test_conversation_agent.py`

- [ ] **Step 1: Add factory tests for fake runtime**

Add to `tests/services/test_conversation_agent.py`.

```python
def test_fake_runtime_creates_conversation_runtime_session(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "fake")

    agent = create_conversation_agent(
        system_prompt="system",
        model="fake:default",
        interactive_shipping=False,
        session_id="fake-session",
    )

    assert agent.__class__.__name__ == "ConversationRuntimeSession"
    assert agent.emitter_bridge.session_id == "fake-session"
```

- [ ] **Step 2: Run factory test and verify it fails**

Run:

```bash
pytest tests/services/test_conversation_agent.py::test_fake_runtime_creates_conversation_runtime_session -v
```

Expected: failure because `runtime=fake` currently returns `UnavailableConversationAgent`.

- [ ] **Step 3: Add fake runtime branch**

In `src/services/conversation_agent.py`, add this branch before the Claude-compatible branch.

```python
    if runtime == "fake":
        from src.services.conversation_runtime.fake_provider import FakeProviderClient
        from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession

        return ConversationRuntimeSession(
            provider=FakeProviderClient(script=[]),
            system_prompt=system_prompt,
            interactive_shipping=interactive_shipping,
            session_id=session_id,
            max_turns=max_turns,
        )
```

- [ ] **Step 4: Run factory tests**

Run:

```bash
pytest tests/services/test_conversation_agent.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/services/conversation_agent.py tests/services/test_conversation_agent.py
git commit -m "feat: wire fake provider runtime factory"
```

## Task 8: Add Fake-Provider Conversation Handler Parity Tests

**Files:**

- Modify: `tests/services/test_conversation_handler.py`
- Modify: `src/services/conversation_handler.py`

- [ ] **Step 1: Add service tests proving fake runtime is production path compatible**

Add to `tests/services/test_conversation_handler.py`.

```python
@pytest.mark.asyncio
async def test_process_message_with_fake_runtime_streams_sse_contract(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "fake")

    from src.services.conversation_runtime.fake_provider import FakeProviderClient
    from src.services.conversation_runtime.models import ProviderStreamEvent, ProviderStreamEventType
    from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession

    provider = FakeProviderClient(
        script=[
            [
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_DELTA, text="A"),
                ProviderStreamEvent(type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE, text="Answer"),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ]
        ]
    )
    session = MagicMock()
    session.session_id = "handler-fake"
    session.agent = ConversationRuntimeSession(
        provider=provider,
        system_prompt="system",
        interactive_shipping=False,
        session_id="handler-fake",
    )
    await session.agent.start()
    session.agent_source_hash = _make_test_session_hash()
    session.lock = asyncio.Lock()
    session.confirmed_resolutions = {}
    session.interactive_shipping = False

    with (
        patch("src.services.conversation_handler.get_data_gateway", new_callable=AsyncMock) as mock_gw,
        patch(_CONTACTS_PATCH, return_value=[]),
    ):
        mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
        events = [event async for event in process_message(session, "hello")]

    assert [event["event"] for event in events] == ["agent_message_delta", "agent_message"]
```

- [ ] **Step 2: Run fake handler parity test**

Run:

```bash
pytest tests/services/test_conversation_handler.py::test_process_message_with_fake_runtime_streams_sse_contract -v
```

Expected: pass. If it fails because `ensure_agent()` rebuilds the fake runtime, set `session.agent_source_hash` to the current expected hash with `_make_test_session_hash()`.

- [ ] **Step 3: Add artifact persistence parity test with fake runtime**

Add to `tests/services/test_conversation_handler.py`.

```python
@pytest.mark.asyncio
async def test_fake_runtime_artifact_callback_persists_once(monkeypatch):
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "true")

    class FakeAgent:
        last_turn_count = 0

        def __init__(self):
            self.emitter_bridge = MagicMock(callback=None)

        async def process_message_stream(self, _content):
            self.emitter_bridge.callback("tracking_result", {"tracking_number": "1Z999"})
            yield {"event": "tracking_result", "data": {"tracking_number": "1Z999"}}

    session = MagicMock()
    session.session_id = "artifact-once"
    session.agent = FakeAgent()
    session.agent_source_hash = _make_test_session_hash()
    session.lock = asyncio.Lock()
    session.confirmed_resolutions = {}
    session.interactive_shipping = False
    emitted: list[dict] = []

    with (
        patch("src.services.conversation_handler.get_data_gateway", new_callable=AsyncMock) as mock_gw,
        patch(_CONTACTS_PATCH, return_value=[]),
        patch("src.services.conversation_handler._persist_artifact_message") as persist_artifact,
    ):
        mock_gw.return_value.get_source_info_typed = AsyncMock(return_value=None)
        async for event in process_message(
            session,
            "track 1Z999",
            emit_callback=lambda event_type, data: emitted.append({"event": event_type, "data": data}),
        ):
            emitted.append(event)

    assert [event["event"] for event in emitted] == ["tracking_result", "tracking_result"]
    persist_artifact.assert_called_once_with("artifact-once", "tracking_result", {"tracking_number": "1Z999"})
```

- [ ] **Step 4: Run artifact persistence test**

Run:

```bash
pytest tests/services/test_conversation_handler.py::test_fake_runtime_artifact_callback_persists_once -v
```

Expected: pass.

- [ ] **Step 5: Run conversation handler suite**

Run:

```bash
pytest tests/services/test_conversation_handler.py tests/services/test_conversation_handler_resume.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/services/test_conversation_handler.py src/services/conversation_handler.py
git commit -m "test: cover fake provider conversation handler parity"
```

## Task 9: Add Session Generation Tokens To `AgentSession`

**Files:**

- Modify: `src/services/agent_session_manager.py`
- Modify: `tests/services/test_agent_session_manager.py`
- Modify: `src/api/routes/conversations.py`

- [ ] **Step 1: Add session token tests**

Add to `tests/services/test_agent_session_manager.py`.

```python
def test_session_generation_token_increments_and_invalidates_old_token():
    session = AgentSession("token-session")

    first = session.begin_turn_generation()
    second = session.begin_turn_generation()

    assert first != second
    assert session.is_turn_generation_active(first) is False
    assert session.is_turn_generation_active(second) is True


def test_session_cancel_invalidates_active_turn_generation():
    session = AgentSession("cancel-token")
    token = session.begin_turn_generation()

    session.invalidate_active_turn_generation()

    assert session.is_turn_generation_active(token) is False
```

- [ ] **Step 2: Run token tests and verify they fail**

Run:

```bash
pytest tests/services/test_agent_session_manager.py -k "generation_token or cancel_invalidates" -v
```

Expected: methods do not exist.

- [ ] **Step 3: Add generation state to `AgentSession`**

Add fields in `AgentSession.__init__()` in `src/services/agent_session_manager.py`.

```python
        self._turn_generation = 0
        self._invalid_turn_generations: set[int] = set()
```

Add methods to `AgentSession`.

```python
    def begin_turn_generation(self) -> int:
        self._turn_generation += 1
        self._invalid_turn_generations.add(self._turn_generation - 1)
        return self._turn_generation

    def invalidate_active_turn_generation(self) -> None:
        self._invalid_turn_generations.add(self._turn_generation)

    def is_turn_generation_active(self, generation: int) -> bool:
        return generation == self._turn_generation and generation not in self._invalid_turn_generations
```

- [ ] **Step 4: Run session manager token tests**

Run:

```bash
pytest tests/services/test_agent_session_manager.py -k "generation_token or cancel_invalidates" -v
```

Expected: both tests pass.

- [ ] **Step 5: Invalidate turn generation on route teardown**

In `src/api/routes/conversations.py`, update `_teardown_session()` so the active turn token is invalidated before message task cancellation.

```python
async def _teardown_session(session_id: str) -> None:
    session = _session_manager.get_session(session_id)
    if session is not None:
        session.terminating = True
        session.invalidate_active_turn_generation()
    await _session_manager.cancel_session_message_tasks(session_id)
    await _session_manager.cancel_session_prewarm_task(session_id)
    await _session_manager.stop_session_agent(session_id)
    _session_manager.remove_session(session_id)
    _event_queues.pop(session_id, None)
```

- [ ] **Step 6: Run route deletion tests**

Run:

```bash
pytest tests/api/test_conversations.py -k "delete or teardown or terminating" -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/services/agent_session_manager.py src/api/routes/conversations.py tests/services/test_agent_session_manager.py
git commit -m "feat: add conversation turn generation tokens"
```

## Task 10: Strengthen Migration Guards

**Files:**

- Modify: `tests/test_claude_sdk_optional.py`
- Modify: `tests/services/test_conversation_agent.py`

- [ ] **Step 1: Add active-source Claude SDK guard**

Add this test to `tests/test_claude_sdk_optional.py`.

```python
def test_active_non_compat_source_does_not_import_claude_agent_sdk_after_runtime_split():
    source_roots = [PROJECT_ROOT / "src" / "services"]
    combined = []
    for root in source_roots:
        for path in root.rglob("*.py"):
            if path.name == "__pycache__":
                continue
            combined.append(path.read_text())
    source = "\n".join(combined)

    assert "claude_agent_sdk" not in source
```

- [ ] **Step 2: Run guard and verify it passes**

Run:

```bash
pytest tests/test_claude_sdk_optional.py::test_active_non_compat_source_does_not_import_claude_agent_sdk_after_runtime_split -v
```

Expected: pass because service code does not import `claude_agent_sdk`.

- [ ] **Step 3: Add direct UPS provider-facing guard**

Add this test to `tests/services/test_conversation_agent.py`.

```python
def test_provider_neutral_runtime_does_not_expose_raw_ups_mcp_tool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHIPAGENT_AGENT_RUNTIME", "fake")

    from src.services.conversation_runtime.tool_catalog import WorkflowToolCatalog

    for interactive in (False, True):
        catalog = WorkflowToolCatalog.for_mode(interactive_shipping=interactive)
        assert all(not tool.name.startswith("mcp__ups__") for tool in catalog.tools)
```

- [ ] **Step 4: Run guards**

Run:

```bash
pytest tests/test_claude_sdk_optional.py tests/services/test_conversation_agent.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_claude_sdk_optional.py tests/services/test_conversation_agent.py
git commit -m "test: guard provider-neutral runtime boundaries"
```

## Task 11: Run Core Runtime Acceptance Set

**Files:**

- No source changes expected.

- [ ] **Step 1: Run runtime package tests**

Run:

```bash
pytest tests/services/conversation_runtime -v
```

Expected: all tests pass.

- [ ] **Step 2: Run conversation service and API tests**

Run:

```bash
pytest tests/services/test_conversation_agent.py tests/services/test_conversation_handler.py tests/services/test_conversation_handler_resume.py tests/api/test_conversations.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run Claude optional dependency tests**

Run:

```bash
pytest tests/test_claude_sdk_optional.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Run backend validation subset**

Run:

```bash
pytest -k "not stream and not sse and not progress" -v
ruff check src/ tests/
```

Expected: pytest selected suite passes and ruff reports no errors.

- [ ] **Step 5: Commit final test-only fixes if any were needed**

If Step 4 required only test or formatting fixes, commit those exact files.

```bash
git add src tests
git commit -m "test: verify provider-neutral conversation runtime core"
```

## Task 12: Write Provider Adapter Child Plans

**Files:**

- Create: `docs/superpowers/plans/2026-06-05-openai-conversation-provider-adapter.md`
- Create: `docs/superpowers/plans/2026-06-05-anthropic-messages-conversation-provider-adapter.md`
- Create: `docs/superpowers/plans/2026-06-05-gemini-conversation-provider-adapter.md`

- [ ] **Step 1: Confirm core gate is green before writing adapter plans**

Run:

```bash
pytest tests/services/conversation_runtime tests/services/test_conversation_handler.py tests/services/test_conversation_agent.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Create provider-specific implementation plans using current provider docs**

Each child plan must start from the shared `ModelProviderClient` contract and cover only provider protocol translation:

```text
OpenAI child plan:
- provider client file under src/services/conversation_runtime/providers/openai.py
- official OpenAI Responses API docs checked at planning time
- text streaming, function/tool calls, argument deltas, usage, response ids, cancellation
- no shipping behavior

Anthropic Messages child plan:
- provider client file under src/services/conversation_runtime/providers/anthropic_messages.py
- official Anthropic Messages API docs checked at planning time
- text blocks, tool use blocks, usage, stop reason, request cancellation
- no Claude Agent SDK dependency

Gemini child plan:
- provider client file under src/services/conversation_runtime/providers/gemini.py
- official Gemini API docs checked at planning time
- function calls, non-streaming fallback, usage metadata, cancellation limits
- no shipping behavior
```

- [ ] **Step 3: Commit child plans**

```bash
git add docs/superpowers/plans/2026-06-05-openai-conversation-provider-adapter.md docs/superpowers/plans/2026-06-05-anthropic-messages-conversation-provider-adapter.md docs/superpowers/plans/2026-06-05-gemini-conversation-provider-adapter.md
git commit -m "docs: plan provider conversation adapters"
```

---

## Self-Review Checklist

- [ ] Spec coverage: every resolved Phase 0 decision has a task in this plan.
- [ ] Placeholder scan: the plan contains no forbidden placeholder strings or vague edge-case instructions.
- [ ] Type consistency: `ProviderToolCall`, `ProviderToolResult`, `ProviderStreamEvent`, and `ConversationRuntimeSession` names match across tasks.
- [ ] Test sequencing: every code task starts with failing tests and ends with targeted validation.
- [ ] Safety: no task sends raw rows, labels, credentials, carrier payloads, or document bytes into provider-bound messages.
- [ ] Runtime boundary: no task imports `claude_agent_sdk` under `src/services/conversation_runtime/`.
- [ ] Frontend stability: no task adds live `tool_result` SSE or changes Angular shared types.

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-06-05-provider-neutral-conversation-runtime.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.
