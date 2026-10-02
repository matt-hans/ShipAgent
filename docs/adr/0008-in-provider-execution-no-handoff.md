# ADR 0008: Provider-Led Execution; Workflow Handoff Rejected

## Status

Accepted

## Decision

Preview, execution, tracking, and label download remain provider-led. General
cross-device workflow handoff — transferring workflow ownership, confirmation,
or execution to another client — is rejected.

Claude is the exception only for approval proof: `prepare_*` may return an
opaque, short-lived Approval Request for an Auth0-protected ShipAgent web page
to record an explicit approve/reject gesture. That page cannot execute the
shipment; after approval, Claude continues the workflow using a one-time
server-side Execution Grant referenced by the opaque Approval Request. No
execution credential is exposed to Claude. This is an approval handoff, not a
workflow handoff. OpenAI uses its widget gesture without this handoff. Desktop
prompts and deep links are optional navigation conveniences, not authorization
requirements.

The approval page never starts execution. The user returns to Claude after
approval, and Claude continues the provider-led workflow by calling the
idempotent execute tool.

Approval credentials never appear in `shipagent://` deep links. The desktop
relay remains an intermediary execution target; a future SaaS worker implements
the same `ExecutionTarget` protocol (ADR 0002) without changing provider
contracts.
