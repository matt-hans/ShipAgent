# ADR 0008: In-Provider Execution; Cross-Device Handoff Rejected

## Status

Accepted

## Decision

The full shipping experience — preview, confirmation, execution, tracking,
label download — happens inside the provider app (ChatGPT or Claude), gated by
ADR 0003's per-surface confirmation and one-time tokens. The proposed
cross-device handoff subsystem (handoff tokens, claim endpoints,
push-to-desktop, web fallback page) is rejected: with in-provider execution
there is nothing to hand off. Provider results may include a bare
`shipagent://` deep link carrying no tokens and no confirmation semantics. The
desktop relay is an intermediary execution target; a future SaaS worker
implements the same `ExecutionTarget` protocol (ADR 0002) without changing
provider contracts.
