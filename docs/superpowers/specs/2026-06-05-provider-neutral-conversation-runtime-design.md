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

The immediate cleanup is not satisfied until the repository state proves it.
Review checks must verify the actual files, not only the intended design:

- `pyproject.toml` must not require `anthropic>=`.
- `shipagent-core.spec` must not force-bundle `anthropic`.
- `tests/test_claude_sdk_optional.py` must check both Claude Agent SDK and
  Anthropic SDK core-runtime absence.
- `tests/services/test_conversation_agent.py` must exist and directly exercise
  provider/runtime fail-closed behavior.

This design supersedes the older Claude-SDK-first orchestration plan in
`docs/plans/2026-02-12-claude-sdk-orchestration-redesign-design.md` for future
runtime work. The Claude SDK can remain temporarily as an optional compatibility
adapter, but it is not the long-term orchestration architecture.

The parity sections are based on current ShipAgent code and the Claude Agent SDK
documentation areas for streaming output, agent loop results, MCP behavior,
hooks, and sessions.

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

Import order is part of the contract. The model/runtime mismatch check must
complete before importing `src.orchestrator.agent.client`, because that module is
the Claude SDK compatibility adapter boundary.

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

Before swapping runtimes, consolidate local conversation ownership. The
canonical path should be `src/services/conversation_handler.py`. The duplicate
agent lifecycle and message-processing flow in `src/api/routes/conversations.py`
should either delegate to the service or be reduced to HTTP/SSE concerns only.
Fake-provider tests must cover the production path, not a parallel path.

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
- stop reason
- provider session/conversation identifiers where available
- provider result subtype or completion status where available

OpenAI, Anthropic Messages API, and Gemini adapters implement this interface.
Adapters only translate protocol details. They must not own shipping behavior,
filtering, mapping, confirmation policy, carrier calls, retry behavior, row data
handling, or audit decisions.

Normalized result metadata should include these optional fields when providers
return them:

- `provider`
- `model`
- `session_id`
- `stop_reason`
- `result_subtype`
- `num_turns`
- `usage`
- `total_cost_usd`
- `raw_usage_provider`

The runtime may omit provider-specific fields from frontend SSE events, but it
must retain them for audit and diagnostics where the current Claude SDK path
already exposes them.

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

Direct external MCP exposure must be an explicit migration decision. The current
Claude SDK options mount:

- an in-process orchestrator MCP with `mcp__orchestrator__*`
- an optional UPS stdio MCP with `mcp__ups__*`

Phase 0 should preserve user-visible capabilities through ShipAgent-owned tool
names, not by exposing raw carrier MCP tools to providers. Direct
`mcp__ups__*` model calls are intentionally removed from the provider-facing
local runtime unless a tool is reintroduced through a ShipAgent wrapper with
policy and UI artifact emission. Local deterministic services may still call UPS
through internal MCP clients.

The dispatcher must represent internal MCP connection failures as normalized
tool errors with sanitized messages. If UPS connectivity is unavailable, the
model sees a safe tool result and the frontend receives the same error event
shape it receives today for agent/tool failures.

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

The port must preserve exact hook semantics unless listed in Intentional
Non-Parity:

- ordered matcher evaluation, with raw-SQL filter denials before structural
  filter checks
- specific direct UPS denial cases for shipment creation, voiding, pickup,
  tracking, locations, service centers, and landed cost where wrappers are
  required
- fallback pre-tool validation for all tools
- post-tool audit logging for every tool result
- error-response detection for dict and string responses
- denial payload shape equivalent to the current `hookSpecificOutput`
  structure: hook event name, `permissionDecision="deny"`, and human-readable
  `permissionDecisionReason`

Provider adapters do not get custom policy logic. They pass normalized tool-call
requests to the policy engine and consume its allow/deny result.

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

Interrupt behavior needs explicit parity tests. The current Claude SDK adapter
calls `ClaudeSDKClient.interrupt()`, and the SDK requires draining interrupted
messages before issuing the next query. The neutral runtime must define the same
observable behavior:

- route cancellation requests mark the active turn interrupted
- in-flight provider streams are cancelled when the provider supports it
- any buffered provider/tool messages are drained or discarded deterministically
  before the next user message starts
- the next user message cannot receive stale deltas or tool calls from the
  interrupted turn
- session deletion cancels message tasks, stops active runtime resources, and
  does not leak callbacks into later sessions

## Claude SDK Parity Matrix

Phase 0 must track each currently used Claude SDK behavior to an explicit
neutral owner.

| Current behavior | Current owner | Neutral owner | Decision | Required tests |
| --- | --- | --- | --- | --- |
| Text streaming from partial message events to `agent_message_delta` | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve SSE shape | fake provider streams multiple deltas |
| Complete assistant text to `agent_message` | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve SSE shape and history write behavior | streamed and non-streamed text stored once |
| Tool call event emission and stream/assistant dedupe by tool id | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve dedupe semantics | duplicate provider tool id emits one `tool_call` |
| Missing tool id fallback to complete assistant message | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve | missing id still emits one canonical tool call |
| Result errors to `error` events | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve with sanitized provider-safe text | provider result error emits one sanitized error |
| `num_turns` and last turn count | Claude `ResultMessage` and adapter state | `ConversationRuntimeSession` | Preserve normalized turn count | final result updates `last_turn_count` |
| `total_cost_usd`, `usage`, `session_id`, `subtype`, `stop_reason` | Claude `ResultMessage` | `ModelProviderClient` result metadata | Preserve when provider supplies it | adapter contract tests include all fields |
| In-process orchestrator MCP tool registration | `create_sdk_mcp_server` in `client.py` | `WorkflowToolCatalog` and `LocalToolDispatcher` | Preserve capability, change mechanism | catalog exposes same ShipAgent tools |
| Optional UPS stdio MCP tool exposure to model | Claude `mcp_servers["ups"]` and allowed tools | Internal workflow services and UPS clients | Intentionally changed | direct `mcp__ups__*` provider calls unavailable; wrappers still work |
| Allowed tool wildcard matching | Claude options | `WorkflowToolCatalog` plus policy engine | Preserve effective allow list, not wildcard implementation | unknown tool denied; known wrapper allowed |
| PreToolUse hook denials | `src/orchestrator/agent/hooks.py` | `RuntimePolicyEngine` | Preserve denial result shape | policy tests port current hook cases |
| PostToolUse audit/error detection | `src/orchestrator/agent/hooks.py` | `RuntimePolicyEngine` and dispatcher | Preserve | every dispatched tool logs audit and detects errors |
| Session continuation | Claude SDK internal session memory | ShipAgent-owned persisted history and runtime state | Intentionally changed | resumed session builds provider messages from ShipAgent history |
| Interrupt and drain | `ClaudeSDKClient.interrupt()` | `ConversationRuntimeSession` | Preserve observable behavior | interrupt, drain, next-message ordering tests |
| Lifecycle errors for already-started/not-started agents | `OrchestrationAgent` | `ConversationRuntimeSession` | Preserve user-safe behavior | start twice, stop before start, process before start tests |
| MCP connection status/failure | Claude MCP client lifecycle | dispatcher/workflow service status results | Preserve user-visible safe failure | unavailable UPS returns safe tool/error events |

## Intentional Non-Parity

The neutral runtime must not blindly clone all Claude SDK behavior.

- Raw row data returned to the model is not preserved. Current tools can return
  `sample_rows` and optional full `rows`; Phase 0 should replace model-bound row
  payloads with counts, schema, redacted summaries, opaque fetch IDs, and
  deterministic server-side state. If temporary compatibility requires samples,
  they must be feature-flagged, redacted, and explicitly removed before Phase 0
  acceptance.
- Direct provider-facing `mcp__ups__*` tools are not preserved. ShipAgent-owned
  wrappers preserve workflow capability while policy remains centralized.
- Claude SDK session memory is not preserved. ShipAgent-owned persisted history
  and runtime state become the source of truth.
- Claude project settings, Claude-only permission modes, and Claude-only model
  defaults are not preserved. Provider selection becomes explicit and
  provider-keyed.
- Claude SDK-specific event classes are not preserved. The stable contract is
  ShipAgent's normalized SSE and runtime event shape.

## Data Safety

The model remains a configuration engine, not a data pipe.

Provider prompts may contain schemas, counts, redacted summaries, opaque IDs,
workflow state, tool schemas, and user instructions. They must not contain raw
order rows, full addresses, labels, credentials, carrier request bodies, or raw
UPS responses.

This is an intentional behavior change from the current Claude SDK path where
some tool responses can expose `sample_rows` or full rows to the model. Phase 0
must close that gap rather than treat it as parity.

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
- stop reason and completion subtype normalization
- provider session id normalization
- cost metadata normalization when available
- cancellation/interruption behavior where supported

Add fake-provider runtime tests:

- user message streams text through existing SSE events
- tool call dispatch emits `tool_call`
- dispatcher result is fed back to the model
- tool errors emit sanitized `error`
- complete assistant messages are stored once
- no row-level data appears in model-bound messages
- duplicate tool call ids are deduped
- missing tool call ids fall back to the canonical complete event
- provider result metadata is captured for audit/diagnostics
- interrupt drains or discards stale buffered events before the next message
- session deletion cancels message tasks and detaches callbacks

Port current hook tests to `RuntimePolicyEngine` tests:

- direct UPS shipment creation is denied
- pickup scheduling and cancellation require orchestrator wrappers
- tracking/location/landed-cost direct calls are denied when they bypass UI
  artifact emission
- raw SQL keys are denied for filter tools
- filter intent and filter spec structural checks remain enforced
- matcher order is preserved
- fallback pre-tool validation is preserved
- denial payload shape is preserved
- post-tool audit and error detection are preserved

Add migration guard tests:

- active non-test source imports no `claude_agent_sdk` after Phase 0 completes
- required install has no `claude-agent-sdk` or `anthropic` dependency
- PyInstaller hidden imports do not include Claude SDK or Anthropic SDK
- local conversation route passes through a fake normalized provider runtime

## Migration Sequence

1. Land immediate PR cleanup and tests.
2. Consolidate the FastAPI conversation route onto
   `src/services/conversation_handler.py` so one service path owns agent
   lifecycle and message processing.
3. Extract neutral tool catalog from current Claude SDK tool wrapping.
4. Extract policy checks from Claude hooks into `RuntimePolicyEngine`.
5. Build `LocalToolDispatcher` over existing deterministic handlers.
6. Define `ModelProviderClient` and implement a fake provider for tests.
7. Implement `ConversationRuntimeSession` using the fake provider.
8. Add OpenAI, Anthropic Messages API, and Gemini HTTP adapters behind the
   normalized provider contract.
9. Switch local conversation creation from Claude SDK compatibility adapter to
   `ConversationRuntimeSession`.
10. Remove active `claude_agent_sdk` imports, mocks, startup assumptions, and
   Claude-only model defaults.
11. Keep or delete the optional Claude SDK compatibility adapter based on usage;
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
- local conversation message handling has one canonical service path covered by
  fake-provider tests
- OpenAI, Anthropic Messages API, and Gemini use shared provider adapter tests
- Claude SDK does not own streaming, tool registration, policy checks, sessions,
  usage, errors, or interrupt behavior
- active non-test source outside an optional compatibility adapter has no
  `claude_agent_sdk` imports
- the Angular/Tauri conversation and SSE contract remains stable
- no row-level shipping data is sent to model-provider prompts
- result metadata, interruption, tool-call dedupe, policy denial shape, and
  internal MCP failure behavior are covered by parity tests

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
