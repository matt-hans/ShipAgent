# Anthropic Messages Conversation Provider Adapter Plan

**Parent plan:** `docs/superpowers/plans/2026-06-05-provider-neutral-conversation-runtime.md`

**Goal:** Add an Anthropic Messages API adapter behind the provider-neutral `ModelProviderClient` contract without reintroducing the Claude Agent SDK or provider-owned shipping semantics.

**Official docs checked on 2026-06-05:**

- Anthropic Messages API reference: https://docs.claude.com/en/api/messages
- Anthropic streaming messages guide: https://docs.claude.com/en/api/messages-streaming
- Anthropic tool use overview: https://docs.claude.com/en/docs/tool-use
- Anthropic tool definition guide: https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use

## Scope

Create:

```text
src/services/conversation_runtime/providers/
  __init__.py
  anthropic_messages.py

tests/services/conversation_runtime/providers/
  test_anthropic_messages_provider.py
```

Do not import `claude_agent_sdk`. This adapter should use direct Messages API protocol translation only.

## Adapter Responsibilities

- Translate provider-neutral messages into Anthropic `messages` content arrays.
- Translate system/developer instructions into Anthropic-compatible top-level system content.
- Translate `ProviderToolDeclaration` into Anthropic client tool definitions using `name`, `description`, and `input_schema`.
- Stream `text_delta` blocks into `ProviderStreamEventType.TEXT_DELTA`.
- Accumulate `tool_use` blocks and `input_json_delta` fragments into one parsed `ProviderToolCall`.
- Normalize `stop_reason`, message IDs, model, and cumulative usage into `ProviderResultMetadata`.
- Preserve stable `tool_use.id` values as `ProviderToolCall.call_id`.
- Treat stream error events as provider errors with sanitized user-facing text.
- Expose cancellation only if the concrete HTTP client supports aborting the in-flight request; do not depend on Claude Agent SDK interrupt behavior.

## Tasks

1. Add `AnthropicMessagesProviderClient` and provider package scaffolding.
2. Add request mapping tests for text turns, seeded history, tool result blocks, and tool declarations.
3. Add stream parser tests for `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`, ping, and error events.
4. Add tool-use tests for stable IDs, missing/empty arguments, partial JSON assembly, multiple tool calls, and parallel tool call preservation as normalized calls.
5. Add metadata tests for usage, model, message ID, `stop_reason`, and provider errors.
6. Add migration guard tests proving active non-compat code still does not import `claude_agent_sdk`.

## Acceptance

- Anthropic Messages adapter tests pass with mocked HTTP/SSE responses.
- Existing fake-provider runtime suite remains green.
- No provider adapter code imports hooks, workflow services, carrier clients, or shipping tools.
- Claude Agent SDK remains optional and isolated to the compatibility adapter.
