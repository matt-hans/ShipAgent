## Responsibility

The Conversation Runtime component owns user-message execution across provider runtimes. `src/services/agent_session_manager.py` tracks process-local `AgentSession` instances with per-session locks, active agents, turn generation guards, mode flags, prewarm/message tasks, and idle reaping. `src/services/conversation_handler.py` is the canonical message path used by HTTP routes and the CLI runner: it resolves current data-source context, starts decision audit runs, rebuilds agents when context changes, streams model/tool events, persists assistant text and artifacts, and completes audit state.

`src/services/conversation_agent.py` selects a protocol adapter behind the
`ConversationAgent` boundary. Anthropic/OpenAI/Gemini/fake providers all use
`src/services/conversation_runtime/runtime_session.py`. The runtime owns the
loop, catalog, neutral policy and local deterministic dispatch. No SDK client or
hook compatibility path remains. See [configuration and migration](../runtime/sdk-free-runtime.md).


Evidence: `tests/services/test_conversation_agent.py`, `tests/services/test_conversation_handler.py`, `tests/services/test_conversation_handler_resume.py`, `tests/services/test_agent_session_manager.py`, `tests/services/conversation_runtime/test_runtime_session.py`, `tests/services/conversation_runtime/test_dispatcher.py`, `tests/packaging/test_sdk_free_runtime.py`, and API conversation tests.

## Read Variables

- User message content, conversation session IDs, interactive/batch mode flags, in-memory `AgentSession` fields, prior conversation records, and current turn generation.
- Current data-source info and column samples from `get_data_gateway()`, plus source signatures, row counts, column names, and schema fingerprints.
- MRU contacts from `ContactService`, settings `agent_model` from `SettingsService`, and runtime/provider environment variables such as `SHIPAGENT_AGENT_RUNTIME`, `OPENAI_API_KEY`, and `GEMINI_API_KEY`.
- Provider stream events, provider result metadata, provider tool calls, and tool result metadata.
- Attachment/artifact events, decision audit context variables, and `AGENT_HIDE_TRANSIENT_CHAT`.

## Write Variables

- In-memory session state: `session.agent`, `agent_source_hash`, `interactive_shipping`, `confirmed_resolutions`, turn generations, prewarm tasks, and message task sets.
- `ConversationRuntimeSession` provider history, active generation, interrupt markers, last result metadata, and event bridge callbacks.
- Streamed event dictionaries: `agent_message_delta`, `agent_message`, `tool_call`, artifacts such as `preview_ready`, `pickup_result`, `tracking_result`, `paperless_result`, and terminal/error events.
- Persistent assistant messages and system artifact messages through `ConversationPersistenceService`.
- Decision audit runs/events and job IDs through `DecisionAuditService`.
- Provider tool result messages with sanitized content and structured payload summaries.

## Conditional Loops

- `ensure_agent()` rebuilds an agent when source hash, interactive mode, or prompt contacts change; otherwise it reuses the existing runtime.
- Runtime selection branches to fake, OpenAI, Gemini, Anthropic, mismatch errors, or unavailable-agent responses based on `SHIPAGENT_AGENT_RUNTIME` and model prefixes.
- `process_message()` serializes each session with an async lock, cancels inactive turn generations, switches interactive sessions to batch mode when needed, and hides transient chat text when artifacts are emitted.
- `ConversationRuntimeSession` loops up to `max_turns`, streaming provider text, collecting provider output items and tool calls, de-duplicating tool call IDs, executing local tools, appending tool result messages, and stopping when no tool calls remain.
- Interrupt handling marks active generations interrupted and calls provider cancellation when supported.

## Mermaid (internal flow)

```mermaid
flowchart TD
    Message[User message] -->|read session| Manager[AgentSessionManager]
    Manager -->|lock and turn guard| Handler[conversation_handler.process_message]
    Handler -->|read source/settings/contacts| Prompt[System prompt context]
    Handler -->|select or rebuild| AgentFactory[create_conversation_agent]
    AgentFactory -->|Anthropic/OpenAI/Gemini/fake| Neutral[ConversationRuntimeSession]
    Neutral -->|read provider events| Provider[ModelProviderClient]
    Neutral -->|write tool calls| Dispatcher[LocalToolDispatcher]
    Dispatcher -->|write frontend artifacts| Bridge[EventEmitterBridge]
    Handler -->|write history and artifacts| Persistence[ConversationPersistenceService]
    Handler -->|write run ledger| Audit[DecisionAuditService]
```
