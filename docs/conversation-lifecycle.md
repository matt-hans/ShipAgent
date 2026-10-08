# Conversation lifecycle and history ownership

The shared conversation service owns turn serialization, effective session mode,
assistant text persistence, and owner artifacts. API and CLI callers own user
ingress. Accepted user messages have an optional `conversation_turn_id` and a
queued/started state in existing message metadata. The service claims ingress
under the session lock. Later queued messages are not earlier model context.
Assistant text is linked to the claimed turn, allowing recreation to recover
logical authored order even when physical persistence order is user A, user B,
answer A, answer B. The UI/export retains every original record in sequence;
legacy records without this metadata remain compatible. Queued messages that
never started remain visible but are not automatically executed on recreation.

A rebuild snapshots the selected model, effective default model, and runtime at
the turn boundary. Source, contact, model/runtime, or mode changes replace the
agent. Failed/unavailable or superseded starts cannot be reused as a healthy
agent. A replacement receives authored user/assistant history, never persisted
owner artifacts or another provider's private continuation. All supported providers
receive neutral role messages once through `ConversationRuntimeSession`; the
Claude Agent SDK prompt-resume path has been removed. See the
[SDK-free runtime guide](runtime/sdk-free-runtime.md).

## History budget

Persisted history is not truncated. Shared-runtime model history retains the
most recent complete user turns within 30 protocol messages and 16,000 serialized
characters (the existing approximately 4,000-token resume budget). Trimming is
at a user-turn boundary, so tool calls/results and private continuation cannot
be orphaned. If the newest completed turn alone exceeds the budget, that whole
turn is omitted from model context. The next request explicitly says earlier
context was omitted and that missing context does not authorize execution or
retries. The active tool loop is never truncated between calls and results.
Interrupted/error turns retain completed authored text without unfinished tool
protocol; turn-limit exhaustion retains completed call/result pairs.

## Cancellation and accepted effects

Each provider request is iterated by its own bounded-queue task. Interruption can
cancel request opening or body streaming, closes request-owned resources, and
never closes a borrowed shared HTTP client. Generation-bound bridges prevent
late provider text or old handler artifacts from becoming a newer turn's output.
Stopping/removing sessions invalidates their generation and pending authority.

Canceling model transport does not undo a dispatched carrier operation. Completed
upload acknowledgements use a separate owner-only persistence callback even if
transient UI output has become stale. Cancellation or ambiguous failure during an
upload or explicitly confirmed auxiliary mutation records an unconfirmed owner
outcome, without rearming the consumed grant. Result cards display that outcome
as unconfirmed and tell the user to check status before requesting another action.
Conversation audit status distinguishes cancellation from completion.

All carrier mutations, including shipment creation and voiding, make one attempt.
An upstream/proxy 503 cannot prove non-acceptance and is not a mutation retry
permit. Existing read-only retry/reconnection behavior is retained. Persisted
prose, confirmation tokens, and provider changes cannot mint new execution
approval; priced preview/user confirmation and one-shot upload grants still own
that authority.
