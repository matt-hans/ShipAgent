# Provider-Neutral Conversation Runtime Design

## Status

Approved for planning.

## Goal

Address the current PR review findings while defining the Phase 0 path for
removing the Claude Agent SDK from ShipAgent's core runtime.

This design has two linked scopes:

- Immediate PR cleanup: remove hard Anthropic SDK packaging/install coupling,
  add direct fail-closed tests, and prevent runtime/model provider mismatches.
- Phase 0 runtime design: port Claude SDK-owned conversation semantics into
  provider-neutral ShipAgent services so Claude support eventually runs through
  the same model-provider contract as OpenAI and Gemini.

## Context

ShipAgent is moving toward a hosted marketplace product and a local desktop
runtime that share a provider-neutral workflow spine. The current local
conversation path already has an adapter boundary in
`src/services/conversation_agent.py`, but the implementation still carries
Claude-specific assumptions:

- `pyproject.toml` requires the Anthropic Python SDK even though active code no
  longer imports it.
- `shipagent-core.spec` force-bundles `anthropic`.
- OpenAI and Gemini fail-closed behavior is only indirectly covered.
- `SHIPAGENT_AGENT_RUNTIME=claude` can override an OpenAI/Gemini-prefixed model
  and route it toward the Claude SDK adapter if the SDK is installed.
- Claude SDK still owns streaming event translation, SDK MCP tool wrapping,
  hook/policy checks, session memory, interrupt behavior, usage/error shape, and
  adapter lifecycle.

This design supersedes the older Claude-SDK-first orchestration plan in
`docs/plans/2026-02-12-claude-sdk-orchestration-redesign-design.md` for future
runtime work. The Claude SDK can remain temporarily as an optional compatibility
adapter, but it is not the long-term orchestration architecture.

## Non-Goals

- Do not remove every `claude_agent_sdk` import in the immediate PR cleanup.
- Do not implement OpenAI, Gemini, or Anthropic Messages adapters in the review
  patch.
- Do not change the Angular/Tauri conversation API, SSE event names, or user
  workflow in this phase.
- Do not move shipping business logic into provider-specific adapters.
- Do not expose raw row-level shipping data to any model provider.

## Immediate PR Cleanup

The current PR should make the provider gate fail closed before any provider SDK
adapter is imported.

### Dependency Cleanup

Remove `anthropic>=0.42.0` from required dependencies in `pyproject.toml`.
Remove the `anthropic` PyInstaller hidden import from `shipagent-core.spec`.

Do not add a new optional dependency extra in this cleanup unless active code
actually needs it. Future Anthropic support should use the normalized
model-provider HTTP adapter. If a future adapter chooses to use a vendor SDK, it
must live behind an optional provider extra and remain absent from the core
packaged runtime.

### Runtime And Model Matching

`src/services/conversation_agent.py` remains the provider gatekeeper.

Model provider inference stays prefix-based for this patch:

- `openai:*` maps to `openai`
- `gemini:*` maps to `gemini`
- `anthropic:*` and `claude-*` map to `anthropic`
- unprefixed models have no inferred provider

Runtime resolution should enforce these rules:

- `runtime=auto` with `openai:*` or `gemini:*` returns
  `UnavailableConversationAgent`.
- `runtime=openai` returns `UnavailableConversationAgent` until an OpenAI
  adapter exists.
- `runtime=gemini` returns `UnavailableConversationAgent` until a Gemini adapter
  exists.
- `runtime=claude`, `claude_sdk`, or `anthropic` may only continue toward the
  Claude SDK compatibility adapter when the model is unprefixed or inferred as
  Anthropic.
- `runtime=claude`, `claude_sdk`, or `anthropic` with `openai:*` or `gemini:*`
  returns `UnavailableConversationAgent` without importing or constructing the
  Claude SDK adapter.
- If the selected runtime is Claude-compatible but `claude_agent_sdk` is not
  available, return `UnavailableConversationAgent` with a clear optional-adapter
  message.
- Unknown runtimes return `UnavailableConversationAgent`.

This preserves the current safe user experience: unsupported providers are
visible and blocked rather than silently routed through the wrong adapter.

### Immediate Tests

Add focused tests in `tests/services/test_conversation_agent.py`.

Required cases:

- `model="openai:default"` and `runtime=auto` returns
  `UnavailableConversationAgent`.
- `model="gemini:default"` and `runtime=auto` returns
  `UnavailableConversationAgent`.
- `runtime=openai` returns `UnavailableConversationAgent`.
- `runtime=gemini` returns `UnavailableConversationAgent`.
- `runtime=claude` plus `model="openai:default"` returns
  `UnavailableConversationAgent` even when `is_claude_sdk_available()` is true.
- `runtime=claude` plus `model="gemini:default"` returns
  `UnavailableConversationAgent` even when `is_claude_sdk_available()` is true.
- `runtime=claude` plus an Anthropic/Claude model returns unavailable when the
  Claude SDK is absent.

Extend `tests/test_claude_sdk_optional.py` to assert:

- required install does not include `anthropic>=`
- PyInstaller hidden imports do not force-bundle `anthropic`
- existing `claude-agent-sdk` absence checks continue to pass

Use these narrow checks first:

```bash
pytest tests/test_claude_sdk_optional.py tests/services/test_conversation_agent.py -v
pytest tests/services/test_conversation_handler.py tests/services/test_conversation_handler_resume.py tests/api/test_conversations.py -v
```

Broaden to the PR's backend validation set after the targeted checks pass.

## Phase 0 Runtime Architecture

Phase 0 moves conversation semantics out of the Claude SDK adapter and into
provider-neutral services.

The local conversation API should stay stable:

```text
FastAPI conversation route
  -> AgentSessionManager
  -> ConversationRuntimeSession
  -> ModelProviderClient
  -> LocalToolDispatcher
  -> deterministic workflow services
  -> existing SSE event contract
```

### ModelProviderClient

`ModelProviderClient` is a small internal interface for provider HTTP adapters.
It normalizes:

- provider messages
- system/developer instructions
- tool declarations
- streamed text deltas
- tool call requests
- final text responses
- provider-safe errors
- usage metadata

OpenAI, Anthropic Messages API, and Gemini adapters implement this interface.
Adapters only translate protocol details. They must not own shipping behavior,
filtering, mapping, confirmation policy, carrier calls, retry behavior, row data
handling, or audit decisions.

### WorkflowToolCatalog

The existing deterministic tool definitions should be exposed through a neutral
catalog instead of Claude SDK `SdkMcpTool` wrappers.

Each tool definition should include:

- name
- description
- input schema
- output shape expectations where available
- side-effect class
- confirmation policy
- Python handler

This catalog can reuse existing handler modules under
`src/orchestrator/agent/tools/` during migration, but the long-term namespace
should reflect workflow ownership rather than Claude-agent ownership.

### LocalToolDispatcher

`LocalToolDispatcher` invokes Python handlers directly. It accepts normalized
tool-call requests from the runtime session, applies policy checks, executes the
handler, normalizes the result, emits audit events, and returns provider-safe
tool results back to the model runtime.

It replaces the local need for a Claude SDK in-process MCP server.

### RuntimePolicyEngine

`RuntimePolicyEngine` ports the current Claude hook behavior into provider-
neutral code.

It must enforce:

- no direct carrier shipment creation from model tool calls
- preview before execution
- explicit confirmation before money/state-changing operations
- no raw SQL keys in filter tools
- structural validation for filter intents and filter specs
- safe error detection and redaction-aware audit logging
- mode-specific behavior for interactive versus batch sessions

Policy decisions should be unit-tested without provider SDK classes.

### ConversationRuntimeSession

`ConversationRuntimeSession` owns the model turn loop for local conversation
sessions.

Responsibilities:

- hold session-scoped runtime state
- build provider-safe prompts and tool declarations
- keep the current SSE event contract stable
- translate provider text deltas to `agent_message_delta`
- translate completed text to `agent_message`
- translate tool calls to `tool_call`
- dispatch tools and feed normalized results back to the provider
- track usage and assistant turn count
- support interruption and shutdown
- avoid placing row-level order data in model prompts

The runtime should not depend on provider-native session memory. Persisted
conversation history and session state remain ShipAgent-owned.

## Data Safety

The model remains a configuration engine, not a data pipe.

Provider prompts may contain schemas, counts, redacted summaries, opaque IDs,
workflow state, tool schemas, and user instructions. They must not contain raw
order rows, full addresses, labels, credentials, carrier request bodies, or raw
UPS responses.

Tool handlers and workflow services remain responsible for applying filters,
mapping columns, generating previews, storing approvals, executing shipments,
and preserving audit state.

## Phase 0 Test Strategy

Add shared contract tests for all model-provider adapters:

- text-only response
- streamed text deltas
- tool-call request
- multiple tool calls
- provider error normalization
- usage metadata normalization
- cancellation/interruption behavior where supported

Add fake-provider runtime tests:

- user message streams text through existing SSE events
- tool call dispatch emits `tool_call`
- dispatcher result is fed back to the model
- tool errors emit sanitized `error`
- complete assistant messages are stored once
- no row-level data appears in model-bound messages

Port current hook tests to `RuntimePolicyEngine` tests:

- direct UPS shipment creation is denied
- pickup scheduling and cancellation require orchestrator wrappers
- tracking/location/landed-cost direct calls are denied when they bypass UI
  artifact emission
- raw SQL keys are denied for filter tools
- filter intent and filter spec structural checks remain enforced

Add migration guard tests:

- active non-test source imports no `claude_agent_sdk` after Phase 0 completes
- required install has no `claude-agent-sdk` or `anthropic` dependency
- PyInstaller hidden imports do not include Claude SDK or Anthropic SDK
- local conversation route passes through a fake normalized provider runtime

## Migration Sequence

1. Land immediate PR cleanup and tests.
2. Extract neutral tool catalog from current Claude SDK tool wrapping.
3. Extract policy checks from Claude hooks into `RuntimePolicyEngine`.
4. Build `LocalToolDispatcher` over existing deterministic handlers.
5. Define `ModelProviderClient` and implement a fake provider for tests.
6. Implement `ConversationRuntimeSession` using the fake provider.
7. Add OpenAI, Anthropic Messages API, and Gemini HTTP adapters behind the
   normalized provider contract.
8. Switch local conversation creation from Claude SDK compatibility adapter to
   `ConversationRuntimeSession`.
9. Remove active `claude_agent_sdk` imports, mocks, startup assumptions, and
   Claude-only model defaults.
10. Keep or delete the optional Claude SDK compatibility adapter based on usage;
    it must not be in core dependencies or package hidden imports.

## Acceptance Criteria

Immediate PR cleanup is done when:

- required install and packaged runtime do not include `anthropic`
- required install and packaged runtime do not include `claude-agent-sdk`
- OpenAI/Gemini selected models fail closed until their adapters exist
- explicit runtime/model mismatches fail closed
- Claude SDK unavailable behavior is directly tested
- existing conversation handler and API tests still pass

Phase 0 is done when:

- local conversation uses `ConversationRuntimeSession` and direct Python tool
  dispatch
- OpenAI, Anthropic Messages API, and Gemini use shared provider adapter tests
- Claude SDK does not own streaming, tool registration, policy checks, sessions,
  usage, errors, or interrupt behavior
- active non-test source outside an optional compatibility adapter has no
  `claude_agent_sdk` imports
- the Angular/Tauri conversation and SSE contract remains stable
- no row-level shipping data is sent to model-provider prompts

## Risks And Mitigations

The main risk is reimplementing a broad agent framework instead of moving
ShipAgent workflows behind clear interfaces. Keep the runtime small: provider
adapters translate model protocols, the dispatcher executes deterministic tools,
and workflow services own shipping decisions.

Another risk is breaking the frontend by changing SSE events. Treat SSE names
and payload shapes as compatibility contracts and test them with a fake
provider before switching real providers.

The final risk is preserving Claude SDK behavior as hidden architecture. Keep
the compatibility adapter optional and temporary, and make the provider-neutral
runtime the default once fake-provider and first real-provider tests pass.
