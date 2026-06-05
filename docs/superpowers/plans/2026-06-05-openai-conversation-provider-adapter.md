# OpenAI Conversation Provider Adapter Plan

**Parent plan:** `docs/superpowers/plans/2026-06-05-provider-neutral-conversation-runtime.md`

**Goal:** Add an OpenAI Responses API adapter behind the existing provider-neutral `ModelProviderClient` contract without moving shipping behavior, tool policy, or tool dispatch into provider-specific code.

**Official docs checked on 2026-06-05:**

- OpenAI Responses API reference: https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI Responses streaming events reference: https://platform.openai.com/docs/api-reference/responses-streaming/response
- OpenAI tools guide: https://platform.openai.com/docs/guides/tools?api-mode=responses

## Scope

Create:

```text
src/services/conversation_runtime/providers/
  __init__.py
  openai.py

tests/services/conversation_runtime/providers/
  test_openai_provider.py
```

Modify only runtime selection and tests needed to instantiate this adapter behind an explicit runtime flag. Do not make OpenAI the default until the fake-provider gate and adapter contract tests are green.

## Adapter Responsibilities

- Translate `ProviderInputMessage` and `ProviderSystemInstruction` into Responses API `input` and instruction fields.
- Translate `ProviderToolDeclaration` into Responses API function tools with strict JSON schema parameters.
- Stream text deltas into `ProviderStreamEventType.TEXT_DELTA`.
- Assemble completed output text into `TEXT_BLOCK_COMPLETE`.
- Assemble function/custom tool call argument deltas into one parsed `ProviderToolCall`.
- Preserve OpenAI response item IDs or call IDs as `ProviderToolCall.call_id` where available.
- Normalize response metadata into `ProviderResultMetadata`, including provider, model, response ID, stop/status, usage, and raw usage payload.
- Implement cancellation only for Responses API operations that can be cancelled by API contract; otherwise expose `supports_cancellation=False`.

## Tasks

1. Add provider package scaffolding and an `OpenAIResponsesProviderClient`.
2. Add request mapping tests for system/developer instructions, user/assistant/tool history, tool declarations, and no row-level payload injection.
3. Add streaming parser tests for text deltas, completed text, function call argument deltas, function call completion, response completion, provider errors, and usage metadata.
4. Add continuation tests proving `ConversationRuntimeSession` feeds ShipAgent-projected tool results back through the adapter without provider-specific dispatch code.
5. Add cancellation tests for supported background response cancellation and document unsupported foreground cancellation as `supports_cancellation=False`.
6. Add runtime selection tests for `SHIPAGENT_AGENT_RUNTIME=openai`, including fail-closed behavior when credentials are absent.

## Acceptance

- OpenAI adapter contract tests pass without requiring shipping fixtures.
- Existing `tests/services/conversation_runtime` fake-provider suite remains green.
- The adapter imports no carrier, UPS, data-source, workflow, or shipping service modules.
- Model-bound messages contain only provider-safe ShipAgent history, instructions, tool schemas, and projected tool results.
