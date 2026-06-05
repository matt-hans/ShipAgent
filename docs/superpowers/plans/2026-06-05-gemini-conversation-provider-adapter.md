# Gemini Conversation Provider Adapter Plan

**Parent plan:** `docs/superpowers/plans/2026-06-05-provider-neutral-conversation-runtime.md`

**Goal:** Add a Gemini API adapter behind the provider-neutral `ModelProviderClient` contract, preserving ShipAgent-owned history, tool dispatch, policy, and model-bound data safety.

**Official docs checked on 2026-06-05:**

- Gemini API reference: https://ai.google.dev/api
- Gemini function calling guide: https://ai.google.dev/gemini-api/docs/function-calling
- Vertex AI Gemini function calling streaming notes: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling

## Scope

Create:

```text
src/services/conversation_runtime/providers/
  __init__.py
  gemini.py

tests/services/conversation_runtime/providers/
  test_gemini_provider.py
```

Use the Gemini REST/SDK protocol only for provider translation. Do not add Gemini-specific shipping defaults or direct workflow behavior.

## Adapter Responsibilities

- Translate `ProviderInputMessage` history into Gemini `contents` with `user` and `model` roles.
- Translate system/developer instructions into Gemini system instruction fields.
- Translate `ProviderToolDeclaration` into Gemini function declarations.
- Support both `generateContent` and `streamGenerateContent`, selecting streaming only when configured and supported.
- Normalize text parts into `TEXT_DELTA` and `TEXT_BLOCK_COMPLETE` events.
- Normalize function call parts into `ProviderToolCall`, preserving call identity where Gemini provides one and otherwise leaving `call_id=None`.
- Feed tool results back using Gemini function response parts through the next provider request.
- Normalize `usageMetadata`, finish reasons, model IDs, and any response/session identifiers into `ProviderResultMetadata`.
- Treat function-call argument streaming as optional capability; enable it only for models/API versions where docs show support.
- Expose cancellation limits honestly. If only client-side HTTP abort is available, report provider API cancellation as unsupported.

## Tasks

1. Add `GeminiProviderClient` and provider package scaffolding.
2. Add request mapping tests for text history, system instructions, tool declarations, and tool result continuations.
3. Add non-streaming response parser tests for text, function calls, finish reasons, safety/provider errors, and usage metadata.
4. Add streaming response parser tests for text chunks and function call parts.
5. Add optional function-argument streaming tests gated by capability metadata.
6. Add runtime selection tests for `SHIPAGENT_AGENT_RUNTIME=gemini`, including fail-closed behavior when credentials are missing.
7. Add data-safety regression tests proving provider-bound Gemini contents never include raw rows, labels, credentials, carrier payloads, or uploaded document bytes.

## Acceptance

- Gemini adapter contract tests pass with mocked API responses.
- Weak/non-streaming provider behavior remains covered by fake-provider runtime tests.
- Adapter code contains no shipping workflow logic and imports no carrier or tool handler modules.
- Existing frontend SSE event names remain unchanged.
