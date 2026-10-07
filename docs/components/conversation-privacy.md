# Local conversation privacy boundaries

The shared conversation service follows [ADR 0007](../adr/0007-origin-based-provider-redaction.md).
Provider adapters translate protocol messages; they do not determine shipping authority or data visibility.

## Provider requests

- System prompts contain source type, row count and closed schema metadata. Imported column samples, file paths and saved-contact identities/locations are not included
- Only authored user/assistant text resumes a conversation. Local artifact metadata/content is excluded from model history, even if stored with an assistant role
- Authored addresses may remain in conversation text. Labeled credentials and structured credential/raw-payload objects are projected out, including JSON objects or arrays following diagnostic text
- Tool handlers receive deep copies of model arguments. Local address enrichment cannot mutate original function-call arguments or provider continuation history
- The original model-authored rate/transit function-call configuration remains protocol content. Actual enriched carrier requests, responses, credentials and label bytes never become tool results
- Provider-private reasoning/signature continuation is adapter-owned protocol state, not text, artifact, or audit output

## Saved contacts and permitted echoes

`preview_interactive_shipment` accepts either an exact `ship_to_handle` or the existing explicit recipient fields. The trusted handler resolves the contact locally before validation/rating. Mixed handle/address input is rejected; prefix matches never select a shipment recipient. Preview details and local job rows remain available to the operator.

Contact tool results expose found/match/count status. A saved contact's name or handle may be echoed only when that exact field matches the current provider input; sibling local fields and model-supplied origin flags do not gain visibility. Tracking supplied in the current provider flow is returned in full. Local batch/history tool results remain aggregate-only; no local tracking number is promoted to current-flow origin.

## Owner artifacts and audit

The owner-facing artifact projection retains recipient detail and existing local label-download references. It removes operational credentials, label/document bytes, raw carrier payloads and private provider state. Artifact storage and legacy read/export boundaries independently apply the projection; ordinary job and label storage is unchanged.

Audit payloads apply stricter PII/operational redaction, including nested JSON-encoded diagnostic payloads. Existing audit hashes are retained; legacy read projection does not rewrite stored history. Failure logs record fixed reasons, stable codes and exception classes rather than exception bodies. Generic MCP audit events record the error category and retry counts, not raw carrier response text.

## Text streaming tradeoff

Text publication waits for each completed provider text block. The service then emits the existing `agent_message_delta` followed by `agent_message` events using the projected text. This intentionally delays token-by-token display until a block completes; tool and progress events remain live.

The guard stores only a character count, avoiding a second raw buffer; adapters still assemble completed text internally. Blocks are limited to 65,536 characters. Oversized or unfinished blocks fail with a fixed safe error. Cancellation and provider errors discard partial text rather than flushing it. The shared service also applies this publication rule to compatibility agents.

## Verification

`tests/services/test_conversation_privacy_acceptance.py` constructs the actual `ensure_agent`/prompt path and serializes requests through scripted, Anthropic, OpenAI and Gemini providers over mock transports. Deterministic gateways and temporary databases verify local contact previews without purchases.

`tests/services/test_conversation_privacy_boundaries.py` independently exercises public events, artifact persistence/legacy exports, audit storage/reads, real UPS/MCP clients over fake transports, nested argument mutation, JSON-encoded secrets and interrupted/split/oversized text blocks. Fixtures use synthetic data only. Adapter continuation and confirmation behavior remain covered by the existing runtime/workflow suites.

## Request-owned stream cleanup

The runtime closes each provider iterator in a `finally` path. OpenAI and Gemini adapters also close their owned SDK iterator. Since the installed Gemini SDK does not reliably cascade generator closure to its HTTP response, the Gemini adapter uses the supported `HttpOptions.httpx_async_client` option and a response hook to capture and close only the current request's responses. A `ContextVar` isolates simultaneous requests; the shared HTTP/SDK client is never closed by request cleanup.

Custom SDK-client injection remains supported. When injecting an actual Gemini SDK client, pass its paired `http_client` to enable HTTP response capture; arbitrary test/client implementations still own their transport beneath the closed SDK iterator. Hooks never log requests, headers, bodies or URLs. This is a narrow prerequisite of privacy size/error termination; broader provider switching and live interruption ownership remain issue #38.
