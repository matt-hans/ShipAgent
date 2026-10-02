# Provider-neutral runtime convergence spec

Date: 2026-10-01. Status: Published, `ready-for-agent`.
Issue: [#30](https://github.com/matt-hans/ShipAgent/issues/30).
Scope: finish local conversation runtime convergence after reconciliation of
existing findings. The user confirmed the shared conversation service as the
primary acceptance boundary.

## Problem Statement

ShipAgent users can select multiple model providers, but Claude still uses a
separate agent framework. This makes behavior and operational requirements
depend on the chosen provider and prevents the application from being a fully
ShipAgent-owned runtime. Existing documentation mixes completed runtime work,
an unfinished Anthropic adapter, an optional SDK compatibility endpoint, and
the separate cloud connector roadmap. Developers lack one current completion
contract and an evidence-backed sequence for continuing safely.

## Solution

Give users the same shipping workflows and safety guarantees regardless of
model provider. ShipAgent owns orchestration; each provider supplies a protocol
adapter. Finish the Anthropic Messages adapter, route Claude through the shared
runtime, remove the Claude Agent SDK compatibility implementation and its
operational requirements, and preserve existing OpenAI/Gemini behavior.

Use the consolidated development roadmap to integrate existing findings first,
complete runtime convergence second, and then finish relay/connector workflows
through the accepted dependency gates. Anthropic remains supported. Removing
its agent framework does not remove its model adapter.

## User Stories

1. As a shipping operator, I want to choose Anthropic, OpenAI or Gemini, so that I can use my preferred model without changing shipping procedures.
2. As a shipping operator, I want equivalent batch workflows across providers, so that imported orders behave consistently.
3. As a shipping operator, I want equivalent interactive workflows across providers, so that single shipments use the same validation and preview rules.
4. As a shipping operator, I want priced previews before mutations, so that I can understand what I am authorizing.
5. As a shipping operator, I want execution to require explicit confirmation, so that model-selected calls cannot purchase shipments without approval.
6. As a shipping operator, I want cancellation to stop further work and stale responses, so that interrupted conversations remain understandable.
7. As a shipping operator, I want cancellation to preserve already accepted side effects, so that interrupted work does not create duplicate shipments.
8. As a shipping operator, I want consistent streamed messages and artifacts, so that provider changes do not break previews or progress.
9. As a shipping operator, I want conversation history preserved, so that I can resume work after session recreation.
10. As a shipping operator, I want a clear safe error when a provider is unavailable, so that I can correct configuration without unexpected fallback.
11. As a shipping operator, I want my imported shipment rows kept out of model prompts, so that changing models does not disclose customer data.
12. As a shipping operator, I want credentials, label bytes and raw carrier payloads excluded from model results, so that private operational data remains protected.
13. As a shipping operator, I want tracking, rates, pickups and document artifacts preserved, so that the migration retains existing supported capabilities.
14. As a CLI user, I want headless workflows to use the shared runtime, so that the CLI works with every configured provider.
15. As a desktop user, I want packaged startup without a Claude agent framework, so that my deployment does not depend on one provider's orchestration tools.
16. As an administrator, I want model selection validated against runtime and credentials, so that mismatches fail clearly and safely.
17. As an administrator, I want redacted audit events preserved, so that provider-independent decisions remain traceable.
18. As an administrator, I want provider changes to avoid altering in-flight approvals and purchases, so that runtime migration cannot grant execution authority.
19. As a developer, I want one normalized model-provider contract, so that adding a provider does not duplicate orchestration.
20. As a developer, I want shared tool definitions and handlers, so that provider adapters cannot fork shipping business logic.
21. As a developer, I want policy decisions expressed in ShipAgent terms, so that core contracts do not depend on Claude hook envelopes.
22. As a developer, I want stable tool-call identities and complete arguments, so that streamed calls execute once and receive matching results.
23. As a developer, I want provider continuation information retained privately, so that reasoning and tool-use continuations work without leaking protocol details into business code.
24. As a developer, I want deterministic conformance coverage, so that I can validate provider behavior without paid API calls or real shipments.
25. As a developer, I want an SDK-free installation and packaging gate, so that accidental framework coupling cannot return.
26. As a maintainer, I want existing findings preserved and reconciled, so that valuable local fixes are integrated before new work compounds divergence.
27. As a maintainer, I want completed milestones linked to evidence, so that plans and generated descriptors cannot be mistaken for working features.
28. As a maintainer, I want cloud connector milestones tracked separately, so that local runtime convergence can ship independently.

## Implementation Decisions

- Reconcile the existing findings branch against current main before treating it as the implementation baseline. Preserve local commits, review the combined change, and rerun relevant validation. This specification does not itself perform Git integration.
- Extend the existing conversation service, conversation agent boundary, normalized model-provider contract and runtime session. Do not introduce another agent loop, conversation owner, policy engine or shipping executor.
- The core owns turn limits, history, mode selection, tool dispatch and deduplication, interruption generations, error projection, audit and artifact persistence. API routes and CLI delegate to that ownership.
- Anthropic implements direct Messages protocol translation: system instructions, history, tool declarations/results, streamed text and tool-use blocks, partial argument assembly, usage/stop metadata, and transport cancellation. Match tool-use IDs to tool-result IDs and reject malformed calls before dispatch.
- OpenAI and Gemini retain their existing protocol continuation requirements. The core may carry opaque provider continuation items, but adapters interpret those items; business services do not.
- Preserve established Claude model names and the legacy Anthropic model configuration alias. Route Anthropic-prefixed and Claude-style models through the shared runtime. Recognized legacy Claude runtime selectors become documented deprecated aliases to the Anthropic adapter; they never re-enable the SDK. Unknown or mismatched configuration fails closed.
- Provider changes apply at a safe turn boundary and recreate or re-seed the session through existing lifecycle ownership. Do not mix a live provider stream or private continuation items across providers. Preserve the provider-neutral persisted transcript; do not reinterpret existing confirmations as new approval.
- Replace Claude hook-shaped policy decisions with provider-neutral allowed/denied results and stable safe reasons. Preserve existing denial behavior, including unsafe SQL and raw carrier calls. Model adapters do not authorize tools.
- Reuse the existing deterministic workflow handlers and gateway boundaries. Their current package names do not require wholesale relocation. Remove obsolete SDK wrappers/hooks after migrating any still-required behavior; retain shared prompt builders and handlers with neutral contracts.
- Keep the canonical public registry and local runtime tool catalog aligned through shared definitions and metadata. Their scopes may differ intentionally. Regenerate provider artifacts when canonical contracts change; never expose raw carrier tools to achieve parity.
- Preserve local preview and explicit confirmation behavior for all existing mutations. Public Approval Requests, Execution Grants, Exact Approved Purchase and Execution Target binding remain governed by accepted ADRs; they are not redesigned or fully implemented in this runtime slice.
- Audit prompt construction as well as tool results. Imported row values, recipient/address samples, label bytes, credentials and raw carrier payloads must not enter model-bound content. Schema metadata and deterministic aggregate configuration are allowed. Provider-originated content follows the accepted origin-based visibility policy on the relevant surface.
- Remove the Claude Agent SDK from production dependencies, startup probes, CLI diagnostics, PyInstaller collection and compatibility dispatch. Update the lockfile, examples and documentation together. Vendor HTTP clients may remain confined to provider adapters; no vendor agent framework owns the loop or policies.
- Use the existing adapter pattern rather than adding a plugin-loading framework. Adding another provider should require adapter translation, explicit selection/credential configuration and conformance coverage, without changing workflow services.
- Preserve HTTP/SSE and persisted artifact contracts. No persistence migration is planned for this runtime slice; any discovered schema change requires an explicit amendment and consumer validation.
- Update the development roadmap with merged evidence. This spec supersedes the older runtime/Anthropic plan only where it allowed the SDK compatibility adapter to remain as the final state. Accepted domain ADRs retain precedence.

Completion requires all three supported providers to use the same ShipAgent
runtime; Anthropic adapter contract and shared behavior tests to pass; no
production SDK imports, SDK wrappers or installation/package requirements to
remain; and API, CLI and desktop startup checks to succeed without that SDK.
Relevant shipping, confirmation, privacy, history and audit regressions must
remain green. No remaining functionality may depend on the removed path.

## Testing Decisions

- Primary acceptance seam: the existing conversation service's observable message/event and persistence boundary, with scripted providers and controlled deterministic workflow gateways. Use the same scenario assertions across providers rather than assertions about private classes or method sequences.
- Test externally observable preview/confirmation ordering, blocked unsafe calls, tool-result sanitization, history resumption, mode isolation, streaming completion, provider failure, cancellation, stale-generation suppression and duplicate tool-call handling. Assert shipment side-effect counts where execution is simulated.
- Supplement that one shared acceptance boundary with adapter protocol contract tests using mocked HTTP/SSE responses. These verify translation, not shipping behavior: fragmented JSON, multiple tool calls, stable IDs, tool-result ordering, malformed arguments, error events, usage, stop reasons and provider-private continuation.
- Add narrow API/SSE and CLI integration checks using existing entry points to prove they delegate correctly and preserve their public contracts. Do not duplicate every provider scenario at every layer.
- Reuse existing fake-provider runtime tests, conversation handler/resume tests, provider adapter tests, session lifecycle tests and workflow confirmation tests as prior art.
- Add an architecture and packaging gate: no active production import/reference to the Claude Agent SDK; install from updated dependency metadata in a clean environment; start and exercise API/CLI with that SDK absent; inspect and smoke-test packaged desktop startup. Source scans alone are insufficient.
- Assert privacy with synthetic canaries in imported data, credentials and carrier responses, inspecting provider-bound requests, persisted/public artifacts and redacted audit output at their applicable boundaries. Do not put real customer data into fixtures.
- Run targeted checks during slices, then relevant full backend suites, lint, artifact drift, affected frontend type/tests/build and desktop/package smoke checks. Use disposable migration databases for reconciliation changes. Previously passed main tests and historical findings reports do not prove the reconciled result.
- Live provider smoke tests are optional separately configured evidence; deterministic gates require no live purchases. An ambiguous or already accepted carrier operation is never automatically retried to make a test pass.

## Out of Scope

- Executing the findings merge or implementing the runtime as part of this specification-writing task.
- A fresh application rewrite, agent-framework replacement, new plugin infrastructure, or wholesale relocation of working shipping services.
- Removing Anthropic model support or banning thin vendor HTTP clients.
- Completing cloud connector Plans 2–10, Auth0 provisioning, OpenAI widget delivery, hosted approval pages, marketplace submission or deployment in this runtime milestone.
- Adding new carriers, commerce integrations or model providers beyond proving the existing adapter extension seam.
- Changing accepted approval, retention, redaction or relay-first Execution Target decisions.
- Breaking existing frontend/API contracts or silently migrating in-flight jobs.

## Further Notes

The consolidated roadmap is the current status/index document. The older
provider-neutral runtime design and OpenAI/Gemini/Anthropic adapter plans are
implementation references; the June 10 connector design and its ten June 30
plans remain the separate provider-product roadmap. The earlier hosted tenant
and upload/storage design is historical where later relay-first ADRs conflict.

The inspected baseline has a functioning shared OpenAI/Gemini runtime but a
separate Claude SDK path. Startup and desktop packaging still require the SDK,
CLI version reporting probes it, and policy denial envelopes retain Claude
hook terminology. These are concrete convergence tasks, not merely renaming.

Apply the project `ready-for-agent` label to the published implementation spec
after confirming its primary testing boundary. The label describes spec
readiness; it does not authorize production deployment or purchases.
