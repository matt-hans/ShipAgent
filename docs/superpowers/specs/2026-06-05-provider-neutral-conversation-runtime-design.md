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
hooks, and sessions:

- <https://code.claude.com/docs/en/agent-sdk/streaming-output>
- <https://code.claude.com/docs/en/agent-sdk/agent-loop>
- <https://code.claude.com/docs/en/agent-sdk/python>
- <https://code.claude.com/docs/en/agent-sdk/mcp>
- <https://code.claude.com/docs/en/agent-sdk/hooks>
- <https://code.claude.com/docs/en/agent-sdk/sessions>

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

### Resolved Phase 0 Decisions

#### Conversation Ownership

`src/services/conversation_handler.py` is the sole owner of per-turn
conversation semantics. Agent rebuild, source resolution, transient assistant
text suppression, artifact persistence, audit run lifecycle, model resolution,
and message streaming move into this service path.

`src/api/routes/conversations.py` remains the HTTP/SSE adapter. It is
responsible for request validation, user-message persistence, SSE queueing,
keepalive `ping`, and terminal `done` emission. It must not keep a parallel
agent lifecycle, `_ensure_agent`, or message-processing flow.

#### Tool Catalog Compatibility

The neutral `WorkflowToolCatalog` freezes current ShipAgent wrapper tool names
and mode exposure as the Phase 0 compatibility contract. The first migration
step builds catalog metadata and handler references around the existing
`src/orchestrator/agent/tools/` handlers, with inventory tests proving every
batch and interactive tool is present in the expected mode.

Handler modules may move to a neutral namespace only after fake-provider parity
tests prove the runtime, dispatcher, policy, artifact, and persistence behavior
matches the existing Claude SDK path.

#### UPS Capability Exposure

Phase 0 removes provider-facing `mcp__ups__*` tool exposure categorically,
including direct tools that the current Claude SDK path may allow, such as
`mcp__ups__rate_shipment`. Direct UPS MCP exposure is an SDK implementation
shortcut, not a ShipAgent product contract.

Retained UPS capabilities must be exposed through ShipAgent wrapper tools in the
neutral catalog. Each wrapper must carry policy, confirmation requirements where
applicable, frontend artifact emission, audit metadata, and model-safe result
projection. If a current direct UPS MCP capability is still needed, add an
explicit wrapper before switching runtimes. Otherwise list it as Intentional
Non-Parity and add a migration guard proving the raw provider-facing tool is
unavailable.

#### Model-Bound Tool Result Projection

`LocalToolDispatcher` is the final enforcement point for model-bound data
safety. Reused handlers may continue returning richer payloads for frontend
artifacts, audit, or compatibility/debug paths, but every result fed back to a
model provider must be projected into a compact provider-safe shape.

Provider-bound tool results may include counts, schema details, redacted
summaries, public workflow status, sanitized errors, and opaque identifiers such
as `fetch_id`, `job_id`, `artifact_id`, and confirmation tokens. They must strip
or replace raw rows, row samples, full addresses, carrier request/response
bodies, labels, credentials, label/document URLs, and uploaded document bytes.
`include_rows=True` must not cause raw rows to reach provider messages in Phase
0.

Phase 0 tests must fail if any provider-bound tool result contains raw row data,
full addresses, carrier payloads, labels, credentials, or document bytes.

#### Provider Adapter Boundary

`ModelProviderClient` exposes only normalized provider events, normalized final
results, provider-safe errors, and provider capability metadata. Provider
adapters translate protocol-specific details into `ProviderStreamEvent`,
`ProviderToolCall`, `ProviderToolResult`, and `ProviderFinalResult` shapes, and
report capabilities such as streaming text, streaming tool arguments, stable
tool-call IDs, parallel tool calls, usage/cost metadata, provider session IDs,
and cancellation support.

`ConversationRuntimeSession` owns the agent loop, ShipAgent-owned history,
tool-result continuation, retry/turn control, policy dispatch, stop/interrupt
behavior, and all shipping decisions. Provider adapters must not own
conversation memory, workflow decisions, tool dispatch, policy checks, retry
loops, or shipping behavior.

#### Parallel Tool Calls

`ConversationRuntimeSession` accepts multiple provider tool calls in one turn and
preserves provider call IDs when available. Dispatch is sequential by default so
side-effecting shipping workflows, confirmation gates, artifact emission, and
audit events remain deterministic.

Parallel dispatch may be enabled only for catalog entries explicitly marked
read-only and idempotent, such as status or schema lookups. Money-changing,
state-changing, artifact-emitting, confirmation-gated, or non-idempotent tools
must be serialized even if the provider supports parallel tool calls. Tests must
prove each provider call receives the correct corresponding tool result and that
audit/event order is stable for serialized tools.

#### Interrupt And Late Event Suppression

Neutral interrupt handling uses a per-turn generation token. Route cancellation
marks the active turn interrupted, requests provider cancellation when the
provider reports cancellation support, and invalidates that turn's event token.

Any late provider deltas, tool calls, tool results, or artifact callbacks from an
invalidated turn must be ignored before they can reach session history, audit
state, or the SSE queue. The next user message starts with a fresh token and
must not receive stale events from the interrupted turn.

Session deletion cancels message tasks, stops runtime resources, detaches
callbacks, invalidates active turn tokens, and prevents late events from entering
the SSE queue for the deleted session.

#### Session Memory And Resume

ShipAgent-owned persisted conversation history and bounded runtime state are the
only source of resume/session memory. Each provider turn is built from ShipAgent
persistence and provider-safe runtime context, not from Claude, OpenAI, Gemini,
or Anthropic provider-native session memory.

Provider session or conversation IDs may be retained when available, but only as
audit and diagnostic metadata. They must not be required for continuity and must
not allow hidden provider state to bypass ShipAgent history construction,
policy, or data-safety projection.

#### Result Metadata And SSE Stability

Provider result metadata is persisted to audit and diagnostics in normalized
form, including `provider`, `model`, `session_id`, `stop_reason`,
`result_subtype`, `num_turns`, `usage`, `total_cost_usd`, and
`raw_usage_provider` when supplied by the provider.

This metadata is not added to live frontend SSE payloads by default. The
existing live event contract remains stable: `agent_message_delta`,
`agent_message`, `tool_call`, existing artifact events, `error`, route-owned
`ping`, and route-owned terminal `done`. Metadata may enter SSE only through an
explicit frontend contract update and matching tests in the same change.

#### Policy Denial Shape

`RuntimePolicyEngine` preserves the current Claude hook denial payload shape as
the canonical policy decision record: `hookEventName`,
`permissionDecision="deny"`, and `permissionDecisionReason`. This retains audit
and test parity with the Claude SDK hook path.

`LocalToolDispatcher` translates policy denials into normalized errored
`ProviderToolResult` instances for the model, using a sanitized human-readable
reason and no raw provider, tool, handler, carrier, or row payload.

#### Artifact Persistence And Replay

Artifact persistence remains limited to the existing persistable artifact set:
`preview_ready`, `pickup_result`, `location_result`, `landed_cost_result`,
`paperless_result`, `tracking_result`, and `contact_saved`.

Persisted artifact metadata keeps the current mapping:
`preview_ready -> batchPreview`, `pickup_result -> pickup`,
`location_result -> location`, `landed_cost_result -> landedCost`,
`paperless_result -> paperless`, `tracking_result -> tracking`, and
`contact_saved -> contactSaved`. Live artifact events and persisted replay
metadata must continue to normalize to the shapes the Angular conversation and
domain-card code already expects.

Non-persisted live events such as `preview_partial`, `pickup_preview`, and
`paperless_upload_prompt` remain live-only unless a deliberate frontend replay
contract update is added with matching tests. Fake-provider tests must prove an
artifact is persisted once and replay metadata matches the live frontend
expectations.

#### Internal Service Failure Boundary

When a model successfully requests a ShipAgent wrapper tool, internal gateway or
MCP failures are represented as sanitized tool failures rather than
provider/runtime failures. This includes UPS, data source, Shopify, Amazon,
document, contact, and other internal workflow service outages.

`LocalToolDispatcher` emits the same user-visible artifact/error shape that the
current tool path would emit where applicable, records audit failure metadata,
and returns an errored provider-safe `ProviderToolResult` to the model. Live
provider/runtime `error` events are reserved for model-provider failures,
runtime exceptions, cancellation failures, and unrecoverable loop errors.

#### Prompt And Context Ownership

Prompt construction remains a ShipAgent service concern. ShipAgent-owned
prompt/context builders produce provider-safe system/developer instructions,
including data-source summaries, source signatures, schema information,
contacts, bounded resume context, mode instructions, and safety rules.

Provider adapters may format these instructions for their provider API, but they
must not inject shipping workflow policy, carrier behavior, row data,
provider-specific business defaults, or hidden model-specific shipping
instructions.

#### Fake Provider Runtime Gate

No real provider adapter becomes the default until a fake-provider
`ConversationRuntimeSession` test suite covers the current SSE, tool dispatch,
artifact, policy, resume, interruption, result-metadata, and data-safety parity
surface. The fake provider is the deterministic acceptance gate for moving
conversation semantics out of the Claude SDK path.

OpenAI, Anthropic Messages API, and Gemini adapters are added only behind the
same normalized provider contract after the fake-provider runtime semantics are
proven.

#### Claude SDK Compatibility Adapter

After Phase 0 switches local conversation to `ConversationRuntimeSession`, the
Claude SDK compatibility adapter may remain only as an optional isolated
fallback for rollback or comparison. It must sit behind an explicit optional
runtime, remain excluded from required installation and packaged hidden imports,
and must not be used by tests as the canonical conversation path.

Once Phase 0 is accepted, active non-test source outside the optional
compatibility adapter must not import `claude_agent_sdk`, and the adapter must
not own shared streaming, tool registration, policy, session memory, interrupt,
usage, error, or shipping workflow semantics.

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

The provider contract should be expressed as typed ShipAgent runtime objects,
not provider SDK classes:

- `ProviderInputMessage`: role, content parts, optional tool results, and
  provider-safe metadata.
- `ProviderSystemInstruction`: system/developer instructions after ShipAgent
  data-safety projection.
- `ProviderToolDeclaration`: tool name, description, input schema, and
  provider-specific projection hints.
- `ProviderStreamEvent`: one of text delta, text block complete, tool call
  started, tool call arguments delta where supported, tool call complete, result
  metadata, provider error, or stream complete.
- `ProviderToolCall`: stable call id when available, tool name, parsed input,
  raw argument text when parsing fails, and provider metadata.
- `ProviderToolResult`: call id, safe content for the model, optional structured
  payload, error flag, and sanitized error details.
- `ProviderFinalResult`: final assistant text, metadata, error status, and any
  provider result fields listed above.

Adapters are responsible for provider-specific mechanics such as OpenAI response
items, Anthropic Messages content blocks, Gemini function calls, streaming
argument deltas, and provider error envelopes. `ConversationRuntimeSession` is
responsible for the agent loop and never imports provider-native message classes.

Provider capability differences must be explicit. Each adapter reports whether
it supports streaming text, streaming tool arguments, parallel tool calls,
cancellation, usage/cost metadata, stable tool-call ids, and provider session
ids. The runtime may degrade gracefully, but tests must prove the observable
ShipAgent SSE contract remains stable for providers with weaker capabilities.

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
- mode exposure: batch, interactive, or both
- model-result projection policy
- frontend artifact events emitted by the handler
- audit phase/event metadata
- timeout and cancellation behavior
- idempotency/retry class
- internal service dependencies
- Python handler

This catalog can reuse existing handler modules under
`src/orchestrator/agent/tools/` during migration, but the long-term namespace
should reflect workflow ownership rather than Claude-agent ownership.

The catalog inventory must account for every current ShipAgent wrapper tool.
Current batch-mode tools:

- `get_source_info`
- `get_schema`
- `ship_command_pipeline`
- `fetch_rows`
- `resolve_filter_intent`
- `confirm_filter_interpretation`
- `get_job_status`
- `batch_execute`
- `get_platform_status`
- `connect_shopify`
- `connect_amazon`
- `schedule_pickup`
- `cancel_pickup`
- `rate_pickup`
- `get_pickup_status`
- `find_locations`
- `get_service_center_facilities`
- `request_document_upload`
- `upload_paperless_document`
- `push_document_to_shipment`
- `delete_paperless_document`
- `resolve_contact`
- `save_contact`
- `list_contacts`
- `delete_contact`
- `track_package`
- `get_landed_cost`

Current interactive-mode tools:

- `get_job_status`
- `get_platform_status`
- `schedule_pickup`
- `cancel_pickup`
- `rate_pickup`
- `get_pickup_status`
- `find_locations`
- `get_service_center_facilities`
- `request_document_upload`
- `upload_paperless_document`
- `push_document_to_shipment`
- `delete_paperless_document`
- `resolve_contact`
- `save_contact`
- `list_contacts`
- `delete_contact`
- `track_package`
- `get_landed_cost`
- `preview_interactive_shipment`

Phase 0 is incomplete if any listed capability is missing, silently renamed, or
exposed in the wrong mode without an explicit Intentional Non-Parity entry and a
test proving the new behavior.

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

Tool dispatch has two output channels and they must stay separate:

- frontend/audit output: rich, sanitized events such as `preview_ready`,
  `pickup_result`, `tracking_result`, and decision-audit records
- model-bound output: compact, provider-safe tool results that never include raw
  rows, labels, credentials, full addresses, carrier request bodies, raw UPS
  responses, or uploaded document bytes

This split is required because some current handlers emit rich UI artifacts while
returning slim model payloads, and some current handlers still return row samples.
The neutral dispatcher owns the final model-bound projection even when a reused
handler returns more data than the provider should see.

Dispatch order is part of parity:

1. Normalize and parse provider tool-call input.
2. Emit/record the `tool_call` event with the same payload keys the frontend
   already consumes: `tool_name`, `tool_input`, and optional `tool_use_id`.
3. Reject unknown or disallowed tools before handler execution.
4. Run pre-dispatch policy checks.
5. Execute the handler with the session bridge/runtime context.
6. Persist any emitted artifact events once.
7. Run post-dispatch audit/error detection.
8. Project the handler result into a safe provider tool result.
9. Feed that result back into the provider turn loop.

The current backend does not emit a live `tool_result` SSE event in the normal
conversation path even though the frontend type union includes it. Phase 0 should
not introduce `tool_result` as a new live event unless the frontend handler and
tests are updated in the same change. For 1:1 parity, active tool chips may
continue clearing on `done`.

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

The runtime turn loop must be deterministic and provider-neutral:

1. Resolve current session state, mode, model, source signature, contacts, and
   prompt context through ShipAgent services.
2. Build provider-safe system instructions and history messages from ShipAgent
   persistence, not from provider-native session memory.
3. Declare the catalog tools enabled for the current mode.
4. Start provider streaming for the user turn.
5. Translate provider text deltas into `agent_message_delta`.
6. Accumulate completed text blocks and emit/store `agent_message` according to
   existing buffering rules.
7. Translate provider tool calls into `tool_call`, dispatch them, and feed
   projected tool results back to the provider.
8. Continue the provider loop until a normalized final result arrives or the turn
   is interrupted/cancelled.
9. Record result metadata, audit events, run status, and last turn count.
10. Let the route/service emit `done` exactly once after processing completes.

The runtime must preserve the current transient chat suppression behavior:

- when `AGENT_HIDE_TRANSIENT_CHAT` is enabled and an artifact event appears, do
  not persist or emit transient assistant text for that turn
- when no artifact appears, emit and persist only the final buffered assistant
  text
- artifact events are persisted once using the existing metadata mapping

This behavior is currently route-owned; after consolidation it should live in the
canonical conversation service or a small helper with fake-provider tests.

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
| Provider init/system messages and MCP status discovery | Claude SDK `SystemMessage` and MCP lifecycle | `ConversationRuntimeSession` plus dispatcher/service status | Preserve user-safe visibility, not provider-native message class | init/status metadata captured without leaking raw provider objects |
| Text streaming from partial message events to `agent_message_delta` | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve SSE shape | fake provider streams multiple deltas |
| Complete assistant text to `agent_message` | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve SSE shape and history write behavior | streamed and non-streamed text stored once |
| Tool call event emission and stream/assistant dedupe by tool id | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve dedupe semantics | duplicate provider tool id emits one `tool_call` |
| Missing tool id fallback to complete assistant message | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve | missing id still emits one canonical tool call |
| Streaming tool argument deltas | Claude `StreamEvent` raw event payloads | `ModelProviderClient` and runtime parser | Preserve final parsed tool input, not raw delta shape | partial argument chunks become one tool call with parsed input |
| Result errors to `error` events | `src/orchestrator/agent/client.py` | `ConversationRuntimeSession` | Preserve with sanitized provider-safe text | provider result error emits one sanitized error |
| `num_turns` and last turn count | Claude `ResultMessage` and adapter state | `ConversationRuntimeSession` | Preserve normalized turn count | final result updates `last_turn_count` |
| `total_cost_usd`, `usage`, `session_id`, `subtype`, `stop_reason` | Claude `ResultMessage` | `ModelProviderClient` result metadata | Preserve when provider supplies it | adapter contract tests include all fields |
| In-process orchestrator MCP tool registration | `create_sdk_mcp_server` in `client.py` | `WorkflowToolCatalog` and `LocalToolDispatcher` | Preserve capability, change mechanism | catalog exposes same ShipAgent tools |
| Optional UPS stdio MCP tool exposure to model | Claude `mcp_servers["ups"]` and allowed tools | Internal workflow services and UPS clients | Intentionally changed | direct `mcp__ups__*` provider calls unavailable; wrappers still work |
| Allowed tool wildcard matching | Claude options | `WorkflowToolCatalog` plus policy engine | Preserve effective allow list, not wildcard implementation | unknown tool denied; known wrapper allowed |
| PreToolUse hook denials | `src/orchestrator/agent/hooks.py` | `RuntimePolicyEngine` | Preserve denial result shape | policy tests port current hook cases |
| PostToolUse audit/error detection | `src/orchestrator/agent/hooks.py` | `RuntimePolicyEngine` and dispatcher | Preserve | every dispatched tool logs audit and detects errors |
| Session continuation | Claude SDK internal session memory | ShipAgent-owned persisted history and runtime state | Intentionally changed | resumed session builds provider messages from ShipAgent history |
| Prompt resume context injection | `build_system_prompt(... prior_conversation=...)` and Claude session memory | canonical conversation service | Preserve effective context, change owner | resumed DB session gets bounded prior messages and no duplicates |
| Tool-result continuation | Claude SDK agent loop | `ConversationRuntimeSession` | Preserve loop behavior | model receives projected tool results and can call another tool before final text |
| Interrupt and drain | `ClaudeSDKClient.interrupt()` | `ConversationRuntimeSession` | Preserve observable behavior | interrupt, drain, next-message ordering tests |
| Lifecycle errors for already-started/not-started agents | `OrchestrationAgent` | `ConversationRuntimeSession` | Preserve user-safe behavior | start twice, stop before start, process before start tests |
| MCP connection status/failure | Claude MCP client lifecycle | dispatcher/workflow service status results | Preserve user-visible safe failure | unavailable UPS returns safe tool/error events |
| Transient assistant text suppression around artifacts | FastAPI conversation route | canonical conversation service | Preserve | artifact turn suppresses transient text; non-artifact turn keeps final text |
| Artifact event persistence | FastAPI conversation route | canonical conversation service | Preserve | live artifact and persisted replay metadata match frontend expectations |
| SSE keepalive and terminal event | FastAPI event generator | FastAPI route/SSE adapter | Preserve | `ping` emitted on idle timeout and `done` emitted once per turn |

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
- Live `tool_result` SSE emission is not added by default. It is typed in the
  frontend but not currently handled by the live SSE mapper. Adding it requires a
  deliberate frontend contract update.

## Data Safety

The model remains a configuration engine, not a data pipe.

Provider prompts may contain schemas, counts, redacted summaries, opaque IDs,
workflow state, tool schemas, and user instructions. They must not contain raw
order rows, full addresses, labels, credentials, carrier request bodies, or raw
UPS responses.

This is an intentional behavior change from the current Claude SDK path where
some tool responses can expose `sample_rows` or full rows to the model. Phase 0
must close that gap rather than treat it as parity.

The phrase "model prompts" includes every message sent to a provider, not just
the initial user/system prompt. Tool results fed back into the model are
model-bound messages and must obey the same safety rules.

Allowed model-bound data:

- source type, row counts, column names, schema fingerprints, and source
  signatures
- redacted summaries and aggregate counts
- opaque handles such as `fetch_id`, `job_id`, `artifact_id`, and confirmation
  tokens
- filter intent/spec metadata needed for deterministic services
- preview totals and warning counts without full addresses or labels
- short, sanitized error messages and public ShipAgent error codes

Disallowed model-bound data:

- raw order rows, even as samples
- full names plus full addresses or phone numbers
- label image/PDF data or label download URLs that reveal shipment details
- credentials, credential references that can be used outside ShipAgent, and
  environment variable values
- carrier request/response bodies
- raw SQL or provider platform payloads
- uploaded document bytes or base64 content

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
- artifact turns suppress transient assistant text when configured
- non-artifact turns emit only the final buffered assistant message
- artifact event persistence is idempotent and replay metadata matches the live
  frontend event shape
- `done` is emitted once per turn and `ping` behavior remains route-owned
- `tool_result` is not emitted unless frontend support is intentionally added

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
- every current ShipAgent wrapper tool appears in the neutral catalog with the
  expected mode exposure
- every model-bound tool result passes the data-safety projection test
- direct `mcp__ups__*` provider-facing calls are unavailable
- existing frontend shared SSE event type names remain unchanged

Add provider adapter contract tests for capability differences:

- provider with no streaming still emits a final `agent_message`
- provider with no stable tool-call id still emits one canonical `tool_call`
- provider with parallel tool calls dispatches each call and associates each
  result with the right provider call id when available
- provider with cancellation support stops streaming promptly
- provider without cancellation support suppresses stale events from the
  cancelled turn before processing the next turn
- provider error envelopes normalize to safe ShipAgent errors without leaking raw
  provider payloads

## Migration Sequence

1. Land immediate PR cleanup and tests.
2. Consolidate the FastAPI conversation route onto
   `src/services/conversation_handler.py` so one service path owns agent
   lifecycle and message processing.
3. Extract neutral tool catalog from current Claude SDK tool wrapping.
4. Add catalog inventory tests for all current batch and interactive tools.
5. Extract policy checks from Claude hooks into `RuntimePolicyEngine`.
6. Build `LocalToolDispatcher` over existing deterministic handlers, including
   model-bound result projection.
7. Define `ModelProviderClient` and implement a fake provider for tests.
8. Implement `ConversationRuntimeSession` using the fake provider.
9. Add OpenAI, Anthropic Messages API, and Gemini HTTP adapters behind the
   normalized provider contract.
10. Switch local conversation creation from Claude SDK compatibility adapter to
   `ConversationRuntimeSession`.
11. Remove active `claude_agent_sdk` imports, mocks, startup assumptions, and
   Claude-only model defaults.
12. Keep or delete the optional Claude SDK compatibility adapter based on usage;
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
- no row-level shipping data is sent in any model-bound provider message,
  including tool results
- result metadata, interruption, tool-call dedupe, policy denial shape, and
  internal MCP failure behavior are covered by parity tests
- the neutral catalog accounts for every current wrapper tool by name and mode
- transient assistant text suppression, artifact persistence, `done`, and `ping`
  behavior are covered by fake-provider tests

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
