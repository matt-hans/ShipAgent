# Marketplace Production Readiness Design

## Goal

Make ShipAgent production-ready for an initial hosted marketplace release across
OpenAI Apps SDK, Anthropic remote MCP, and generic MCP clients.

The marketplace product is not the local desktop app embedded wholesale inside
MCP. The marketplace product is a hosted ShipAgent MCP App experience:

- ShipAgent core is a headless workflow engine.
- The hosted MCP server is the marketplace integration and app host.
- Focused UI resources render import, preview, rate, confirmation, label, and
  audit panels where the host supports MCP Apps or OpenAI Apps SDK widgets.
- Hosted fallback pages provide the same authenticated review/approval flows
  when a client only supports tool calls.
- The local desktop/Tauri app remains the local, admin, developer, and future
  self-host shell.

The first release is hosted SaaS first, with a clean path to self-hosted
packaging later. It supports the core shipping workflow:

- setup/status discovery
- UPS account connection
- Shopify connection
- file upload order batches
- Shopify order import
- shipment preview
- rate comparison
- explicit rate selection
- explicit approval and confirmation token issuance
- label creation
- job status
- expiring label links
- audit summary

Pickup scheduling, voiding, tracking write-back, Microsoft artifacts, and Gemini
artifacts remain follow-up catalog work unless they become mandatory for
marketplace review.

## Current State

The repository already has the right portability foundation:

- Public registry contracts in `src/registry/tools/public.py`
- Registry validation models in `src/registry/models.py`
- Provider projections in `src/provider_adapters/`
- Generated artifacts in `generated/provider_artifacts/`
- A hosted MCP server builder in `src/hosted_mcp/server.py`
- Hosted tenant/account/artifact/confirmation models in `src/db/models.py`
- One-time hosted confirmation tokens in `src/hosted/confirmation_service.py`
- A small provider-neutral preview service in `src/workflows/shipping.py`
- A minimal `shipagent-frontend/apps/provider-widget` bundle

The gaps are runtime and review readiness:

- Public hosted tools do not have production handler wiring.
- `public.py` currently exports providers and tools outside v1 scope.
- `hosted_readiness="ready"` is too easy to set and is used as an export gate.
- Public schemas expose hosted-unsafe fields such as `tenant_id`, raw shipment
  arrays, and overly thin result schemas.
- The local conversation runtime still depends on the Claude Agent SDK as the
  primary orchestration path.
- Backend startup, packaging, scripts, settings, and frontend onboarding still
  treat Anthropic/Claude as the required model provider instead of one provider
  behind a neutral contract.
- The app depends on model-vendor Python SDKs where provider HTTP adapters would
  be enough.
- OpenAI artifacts are tool descriptors, not complete Apps SDK bundles with
  registered resources, CSP, OAuth, widgets, fixtures, and review scripts.
- Anthropic export is not enabled and has no adapter or review bundle.
- Microsoft and Gemini artifacts are outside first-release scope.
- The shared widget layer is only a placeholder preview element.
- Hosted OAuth/account linking, tenant ownership enforcement, object storage,
  signed label links, KMS-backed encryption, durable queues, lifecycle policy,
  and end-to-end hosted workflows are incomplete.
- Real shipping behavior is still split across local FastAPI routes, Claude
  agent tools, and desktop-oriented services.

## Product Framing

### Primary Product

The hosted marketplace product is:

```text
MCP tools
+ focused MCP App/OpenAI widget resources
+ hosted ShipAgent workflow services
+ hosted auth, storage, jobs, artifacts, and audit
```

The local app remains:

```text
Local ShipAgent app
= desktop/local workflow shell
+ developer/admin/self-host tooling
+ existing local REST, Job/JobRow, SSE, filesystem labels, desktop credentials
```

Do not embed the full local Angular shell or Tauri sidecar in the hosted MCP
server. Reuse UI components and DTOs where practical, but keep marketplace
widgets focused, standalone, and reviewable.

### Host Capability Matrix

OpenAI Apps SDK should receive the richest package: tools, resource templates,
CSP/widget domain metadata, OAuth/security scheme metadata, structured fixtures,
and developer-mode test scripts.

MCP Apps-capable clients should receive `ui://` resources and structured tool
results.

Anthropic remote MCP and generic MCP clients must not depend on rich UI support.
They get the same safe tool contracts, concise text, `structuredContent`, and
hosted URLs for upload, setup, preview, approval, labels, and audit views.

All critical safety transitions must be enforced by hosted services. Widgets and
hosted pages improve UX, but they do not replace server-side validation,
approval records, confirmation tokens, idempotency, or tenant checks.

### Local Runtime Convergence

The local desktop/Tauri app should converge on the same provider-neutral
workflow spine as the hosted marketplace product. It should keep the existing
FastAPI routes, conversation API, and SSE event contract stable for the Angular
frontend, but the internals should stop depending on Claude SDK sessions, Claude
SDK MCP wiring, or Claude-specific hooks.

This is a compatibility refactor, not a desktop deprecation. The Angular/Tauri
shell, local FastAPI sidecar, local credentials, local files, local SSE updates,
and user-selected model provider path must keep working while their internals
move onto the shared workflow spine.

Local conversation becomes another adapter over the canonical workflow engine:

- a model-provider adapter interprets the user's request and proposes a typed
  workflow plan or normalized tool call
- deterministic ShipAgent workflow services apply filters, mappings, previews,
  confirmations, and shipping operations
- direct Python dispatch invokes local workflow/tool handlers
- SSE events preserve the current frontend contract
- hosted MCP/generic MCP remains a separate public protocol surface

This convergence is the path for removing the Claude Agent SDK completely,
rather than building a new generic runtime that recreates Claude SDK behavior in
parallel with the hosted marketplace work.

## External Marketplace Requirements

### Shared MCP Requirements

The hosted surface should be a remote MCP server over Streamable HTTP. It must
list tools, support tool calls, return schema-valid `structuredContent`, serve UI
resources where supported, and apply authorization on every protected call.

The public server exposes ShipAgent workflow tools, not raw carrier tools.

### OpenAI Apps SDK

OpenAI Apps SDK apps are MCP servers plus UI resources. The first release must
provide:

- registered app tools with titles, descriptions, schemas, annotations, and
  security schemes
- registered app resources for widgets using `ui://...` resource URIs
- `structuredContent` matching declared output schemas
- tool result `_meta` for widget-only data that must not reach the model
- widget resource metadata including CSP and app domain settings
- OAuth-compatible authentication and per-call token validation
- developer-mode testing with tool scan and write-action confirmation checks
- privacy, safety, and support material for app submission

### Anthropic Remote MCP

Anthropic directory readiness requires:

- a working, fully tested HTTPS remote MCP server
- OAuth 2.0 when authentication is required
- safety annotations for all tools
- production deployment, not beta-only infrastructure
- published docs, privacy policy, and support contact
- provisioned test account with sample data
- at least three realistic usage examples
- successful testing from Claude surfaces and MCP tooling

Anthropic API remote MCP should be treated as tool-call first. Do not require
inline UI rendering for the Anthropic path.

### Generic MCP

Generic MCP clients should get the same tool contracts and structured results.
If a client supports MCP Apps/UI resources, attach widgets. If not, return
concise text plus structured content and hosted URLs for previews, approval,
labels, and audit summaries.

## First-Release Public Tool Surface

Production-exported hosted tools are exactly:

- `get_setup_status`
- `connect_carrier_account`
- `connect_store`
- `upload_or_import_orders`
- `preview_shipments`
- `compare_rates`
- `select_rate`
- `confirm_shipment_preview`
- `create_shipments`
- `get_job_status`
- `get_label_links`
- `get_audit_summary`

Keep these tools in the registry but mark them not production-exportable for v1:

- `track_package`
- `schedule_pickup`
- `void_shipment`
- `write_back_tracking`

First-release provider exports are exactly:

- OpenAI Apps SDK
- Anthropic remote MCP
- generic MCP

Microsoft and Gemini remain registered for future projection work but are not
production exports for this release.

## Architecture

ShipAgent should build a public hosted MCP gateway in this repository.

```text
OpenAI / Claude / MCP client
  -> ShipAgent hosted MCP gateway
  -> marketplace auth, tenant identity, tool registry, widgets/fallback URLs
  -> provider-neutral hosted workflow services
  -> hosted state, queue, object storage, KMS, and audit storage
  -> internal adapters: UPS MCP, Shopify, file ingestion
```

Hosted marketplace calls do not require a second internal ShipAgent LLM. The
external client model can propose typed tool arguments, filters, mappings, and
shipment preferences, but ShipAgent workflow services deterministically validate
and apply those inputs. UPS rating, address validation, shipment creation, label
persistence, audit, and status updates run through deterministic services and
internal adapters, not through another model-planning loop.

The actual UPS MCP server is a separate repository. This repository owns:

- the hosted ShipAgent workflow contracts
- the internal UPS adapter interface expected by hosted workflows
- capability/version checks against the external UPS MCP server
- readiness tests that fail if the connected UPS MCP server cannot satisfy the
  hosted v1 contract

The UPS MCP repository owns UPS endpoint coverage, request/response details,
UPS auth behavior, UPS idempotency pass-through, and UPS-specific normalization.
Public marketplace tools in this repository never expose raw UPS MCP primitives.

The private UPS MCP hop is a carrier integration boundary, not an additional
model or public app surface. ShipAgent could technically call UPS APIs directly,
but doing so would pull carrier-specific protocol details, auth behavior,
normalization, retry/idempotency semantics, and raw response handling into the
hosted workflow engine. Keeping UPS behind a private MCP contract lets ShipAgent
fail readiness explicitly, reuse the UPS integration repository, and keep public
marketplace tools carrier-agnostic.

Provider-specific code should be packaging and protocol translation only.
Shipping business logic belongs in provider-neutral ShipAgent workflow services.

## Components

### Hosted MCP Gateway

Owns the public remote MCP endpoint.

Responsibilities:

- Streamable HTTP MCP transport
- tool and resource registration from the registry
- structured result envelopes
- provider-safe error mapping
- OAuth challenge behavior
- request context extraction
- tenant and scope enforcement
- no unbound public tools in production
- output schema validation
- widget/resource registration and CSP metadata
- fail-closed production startup checks

The gateway must not mirror full handler results into both text and
`structuredContent`. Hosted results must pass through transcript-safe result
envelopes.

### Hosted Auth

Owns marketplace identity and account-linking state.

Responsibilities:

- bearer/OAuth token validation
- tenant resolution from `{provider_host, provider_subject}`
- OAuth/OIDC protected-resource metadata
- scope checks on every tool call
- account-link initiation and callback handling
- admin-seeded account eligibility for reviewer/demo/private-beta tenants
- reviewer/demo tenant controls
- per-tenant quotas and rate limits
- proper auth challenges for auth failures

Production marketplace use requires customer-owned UPS and Shopify connections.
Admin-seeded credentials are allowed only for private beta, reviewer, and demo
tenants. Normal tenants fail with a `connect_account` next action if they lack
their own connection.

MCP tools must never accept UPS or Shopify credentials. They return status plus
short-lived hosted links for account linking, setup, profile collection, upload,
or approval.

### Hosted Storage

Production hosted storage requires:

- managed relational DB with real migrations
- durable object storage for uploads and labels
- durable async queue/worker for imports and label creation
- managed secrets/KMS
- logs, metrics, correlation IDs, and alerts

SQLite, local filesystem, `Base.metadata.create_all`, and single-worker local
backend behavior remain local development and desktop paths only.

Hosted storage owns tenant-scoped records for:

- tenants
- connected accounts
- origin/shipper profiles
- uploaded artifacts
- order batches
- immutable order batch rows
- preview configurations
- previews and preview versions
- rate options and selected rates
- address validation records
- approval requests
- confirmation token records
- jobs and job rows
- label artifacts
- audit summaries and audit event material
- quota/usage ledgers
- retention/lifecycle state

Every hosted repository read/write must require `tenant_id`. Cross-tenant IDs
must fail in tests.

### Hosted Encryption

Hosted connected-account tokens and executable row payloads require a
`HostedEncryptionService` backed by production KMS or equivalent managed secrets
infrastructure.

Every encrypted envelope should store:

- algorithm
- key ID
- key version
- nonce
- ciphertext
- AAD metadata or AAD hash

Executable canonical payloads for hosted order batch rows should be encrypted
with AAD bound to:

- `tenant_id`
- `order_batch_id`
- `batch_row_id`
- `row_checksum`
- `schema_signature`
- `normalizer_version`

Hosted readiness fails closed if KMS is unavailable, key IDs are missing,
rotation config is invalid, or decrypt probes fail.

Keep `src/services/credential_encryption.py` for desktop/local credentials.

### Hosted Workflows

Provider-neutral services own the hosted core flow:

- setup/status discovery
- account linking
- upload/import
- preview
- rate comparison
- rate selection
- approval request and confirmation token issuance
- shipment creation enqueue
- job polling
- label link retrieval
- audit summary retrieval

These services are callable from the hosted MCP gateway and, where safe, from
hosted HTTP/widget pages. They must not depend on OpenAI, Anthropic, Gemini,
Microsoft, Claude, or desktop/Tauri runtime APIs.

### Hosted Widgets And Pages

Build a standalone marketplace widget bundle separate from the Angular shell.

First-release widgets:

- `order_import_status`
- `shipment_preview`
- `rate_comparison`
- `confirmation`
- `label_links`
- `audit_summary`

Widgets consume `structuredContent`, widget-only `_meta`, and opaque follow-up
tool IDs/URLs. They must not require desktop shell state.

Hosted fallback pages are required for flows that need user interaction when a
client lacks widget support:

- upload/session handoff
- account linking
- origin profile setup
- address correction/selection
- shipment approval
- labels and audit viewing

Possession of a hosted URL alone must not authorize action or reveal detailed
data. Pages require marketplace/OAuth session continuity or hosted login/handoff
that resolves to the same tenant, and approval POSTs require CSRF protection.

### Provider Adapters

Provider adapters should generate:

- OpenAI Apps SDK tool descriptors, resources, CSP/widget metadata, OAuth and
  security metadata, fixture structured outputs, and developer-mode checklists
- Anthropic remote MCP/directory metadata, examples, docs/privacy/support links,
  and test account instructions
- generic MCP descriptor snapshots and MCP inspector fixtures
- provider drift tests that compare generated artifacts to registry/DTO sources

Microsoft and Gemini remain later adapter targets for this spec.

### Model Provider HTTP Adapters

Local and self-hosted model access should use small internal HTTP adapters, not
vendor SDK packages. The first supported local model providers are:

- OpenAI
- Anthropic Messages API
- Gemini

Each adapter translates between provider-specific HTTP payloads and ShipAgent's
normalized model contract:

- messages
- system/developer instructions
- tool declarations
- tool call requests
- streamed text deltas
- final text responses
- provider-safe errors
- usage metadata where available

Adapters must not own shipping behavior, filtering, mapping, confirmation,
carrier calls, retry policy, row data handling, or audit decisions. They only
translate model protocol details. Provider API keys are stored as provider-keyed
credentials; `ANTHROPIC_API_KEY` may remain as a migrated Anthropic credential
name, but it is not a global application prerequisite.

The following dependencies and assumptions should be removed from required and
packaged runtime paths:

- `claude-agent-sdk`
- `claude_agent_sdk` imports
- Claude SDK startup validation
- Claude SDK hidden imports in packaging
- Claude model defaults as the only model choices
- Anthropic SDK dependency usage

The backend must start without Claude SDK installed. Anthropic support continues
only through the same HTTP model-provider contract used by OpenAI and Gemini.

## Data Flow

1. User enables ShipAgent in ChatGPT, Claude, or a generic MCP client.
2. Client connects to the hosted ShipAgent MCP endpoint.
3. ShipAgent validates the provider token and resolves the hosted tenant.
4. User calls `get_setup_status`.
5. User connects UPS and Shopify, or a private-beta/reviewer/demo tenant selects
   an eligible seeded demo account.
6. User uploads a file through a hosted upload page/resource or requests a
   Shopify import with closed filters.
7. `upload_or_import_orders` validates tenant/account/artifact scope, computes
   the import idempotency key, and returns an existing batch or enqueues a
   durable import job.
8. Import workers validate files or page Shopify deterministically, normalize
   rows, encrypt executable payloads, persist redacted summaries, and freeze an
   immutable order batch.
9. User asks to ship orders.
10. `preview_shipments` validates tenant-owned `order_batch_id`,
    `connected_account_id`, `origin_profile_id`, and a closed shipment plan.
11. Hosted preview applies deterministic mapping/filter/package/service config,
    validates configured international lanes, validates addresses where
    supported, calls UPS rating through the internal adapter, stores preview
    version state, and returns transcript-safe summaries plus widget hints.
12. `compare_rates` optionally rate-shops selected scope and returns rate option
    summaries with opaque `rate_option_id`s.
13. `select_rate` explicitly persists the chosen rate option into a new preview
    version or CAS-updated draft state.
14. Preview/selection returns confirmation-ready state with a
    `confirmation_request_id`, short-lived `confirmation_url`, and widget-only
    approval challenge where supported.
15. The user approves in a widget or hosted page. The server records approval
    state bound to tenant, preview version, selected-rate checksum, purchase
    scope, lane policy, spend ceiling, expiry, and approval proof hash.
16. `confirm_shipment_preview` consumes the approved server-side proof and mints
    a one-time confirmation token.
17. `create_shipments` accepts only the confirmation token, validates tenant and
    scopes, consumes the token, CASes the preview/job to running, enqueues
    execution, and returns `{job_id, status}`.
18. Hosted workers process rows with row-level idempotency and CAS, create labels
    through UPS MCP, persist label artifacts, update audit/usage ledgers, and
    mark rows completed or needing review.
19. `get_job_status`, `get_label_links`, and `get_audit_summary` provide
    transcript-safe follow-up state.

Row-level order data must not be placed in model prompts. The model may see
counts, costs, warning categories, opaque IDs, service summaries, redacted
destination summaries, confirmation state, widget hints, and hosted URLs.
ShipAgent workers must not call a second internal model to process row-level
shipping data or decide UPS execution steps.

## Hosted Public Contracts

### Public Inputs

Public hosted tool inputs must never accept:

- `tenant_id`
- UPS/Shopify credentials
- local file paths
- multipart bytes
- row arrays
- full addresses or origin profile fields
- raw shipment payloads
- service choices at `create_shipments` time

Hosted production must not expose public exploratory row/sample tools. Local/dev
or internal/admin tooling may inspect rows for debugging, but public MCP tools
must use deterministic filters over stored rows and return only transcript-safe
aggregates, opaque IDs, warning categories, redacted summaries, widget hints, and
next actions.

Public inputs use opaque IDs:

- `artifact_id`
- `connected_account_id`
- `origin_profile_id`
- `order_batch_id`
- `preview_id`
- `preview_version`
- `rate_option_id`
- `confirmation_request_id`
- `approval_token` or equivalent approval proof
- `confirmation_token`
- `job_id`

Handlers enforce that every ID belongs to the authenticated tenant.

### Public Outputs

Public hosted results must include only transcript-safe information:

- `ok`
- counts
- totals and cost summaries
- warning categories
- opaque IDs
- service summaries
- redacted destination summaries
- status/phase
- timestamps
- next actions
- widget hints
- hosted URLs where needed

Public hosted results must not include:

- full `order_data`
- row samples
- sample rows
- raw labels
- base64/PDF bytes
- `label_path`
- `s3://` URIs
- full addresses
- emails or phone numbers
- raw row payloads
- raw UPS request/response bodies
- raw audit details
- exception strings, stack traces, or local paths

This includes apparently small samples: a single row can contain names,
addresses, phone numbers, order IDs, customs data, or business-sensitive values.
Hosted public outputs should prove the filter/config result through counts,
redacted summaries, and server-side persisted preview state instead.

### Hosted Error Envelope

Domain failures return schema-valid errors:

```json
{
  "ok": false,
  "error": {
    "code": "E-3004",
    "category": "ups_api",
    "message": "Service is not available for the selected shipment scope.",
    "retryable": false,
    "next_action": "compare_rates",
    "correlation_id": "..."
  }
}
```

Use protocol/auth errors only for auth challenges and malformed MCP calls.
Do not expose exception strings, validation payloads, raw UPS responses, stack
traces, local paths, or raw details.

## Hosted State And Invariants

### Setup And Accounts

`get_setup_status()` is read-only and returns transcript-safe setup state:

- connected UPS accounts
- connected Shopify stores
- eligible demo accounts
- available origin profiles
- missing setup steps
- quotas
- hosted setup URLs

It returns opaque IDs and redacted labels only. It never returns addresses,
credentials, account numbers, store tokens, or full profile data.

`connect_carrier_account` and `connect_store` initiate or inspect hosted account
linking. They return status plus short-lived `link_url` values. They do not
accept credential payloads.

Origin profile creation/editing stays out of public MCP v1. Hosted pages collect
and validate origin address/contact PII. Public tools only list/select opaque
`origin_profile_id`s or report that one is needed.

### Uploads And Imports

File bytes and upload targets stay out of MCP tool arguments.

Hosted upload resources/pages issue short-lived upload targets. The client
uploads bytes directly to object storage. ShipAgent validates:

- checksum
- size limit
- MIME sniffing
- extension allowlist
- parser preflight
- malware scan
- artifact expiry

Uploaded artifacts start as `pending_upload` or `quarantined`, and only become
`validated` after all checks pass. `upload_or_import_orders` rejects unscanned,
scan-failed, expired, checksum-mismatched, or type-mismatched artifacts.

`upload_or_import_orders` is durable and idempotent. It validates scope, computes
the import idempotency key, and either returns an existing completed
`order_batch_id` or enqueues an `order_import` job.

For Shopify imports, require closed filters such as:

- `created_at_min`
- `created_at_max`
- fulfillment status
- financial status
- max order cap

The worker pages deterministically and persists source metadata:

- store/domain hash
- Shopify API version
- filter hash
- page cursors or high-water marks
- fetched count
- provider order IDs/checksums
- importer version

### Immutable Order Batches

Hosted imports create immutable `order_batch` and `order_batch_rows` records.
Re-importing returns the existing batch for the same idempotency key or creates
a new batch/version. It never updates rows in place.

The import idempotency key includes:

- tenant
- source artifact/account
- source filters
- import options
- content/source checksum
- schema signature
- normalizer version

Hosted order rows store:

- stable `batch_row_id`
- source row number or source order ID
- row checksum
- schema signature
- normalizer version
- import/mapping metadata
- encrypted executable canonical shipping payload
- redacted summary for public/widget output

Raw source data is minimized, encrypted if retained, and governed by retention
policy. It is not the default execution or transcript surface.

### Preview Configuration

`preview_shipments` accepts a closed shipment plan shape. The model may propose
filters, mappings, package defaults, and preferences, but deterministic hosted
code validates and applies them to stored batch rows.

Preview configuration is persisted as an immutable tenant-scoped DTO with:

- normalized mapping config
- filter config and compiled hashes
- package defaults
- service defaults/preferences
- schema signature
- normalizer version
- config hash
- mapping/filter hashes
- mapping trace or summary

Any mapping/filter/package/service change creates a new preview version or
CAS-updates an allowed draft field before confirmation.

### Preview Versions And Eligibility

Hosted previews have explicit statuses:

- `draft`
- `rated`
- `pending_confirmation`
- `running`
- `completed`
- `expired`
- `cancelled`

Each preview version/checksum binds:

- order batch and row checksums
- preview configuration hash
- UPS connected account
- origin profile
- package/service choices
- rate results and totals
- selected rate decisions
- purchase scope
- address validation state
- lane policy and customs validation hash
- rate payload hashes

Hosted preview separates row eligibility from rating:

- `eligible`
- `excluded_by_filter`
- `invalid`
- `rate_failed`
- `needs_review`

Confirmation is possible only for a persisted purchase scope hash such as
`all_eligible` or an opaque saved row selection. It must fail if the selected
scope includes invalid or unrated rows. The system must never silently drop rows
from an "all" request.

### Address Validation

For each eligible row, hosted preview runs deterministic address validation
where the lane/provider supports it and persists `AddressValidationRecord` with:

- `valid`
- `corrected`
- `ambiguous`
- `invalid`
- `unsupported`

The record stores candidate hashes and redacted summaries. Invalid or ambiguous
rows are excluded from `all_eligible` confirmation until the user resolves them
through an authenticated hosted page/widget flow.

Auto-applied corrections must be bound into the preview payload hash and
approval record so execution cannot ship to an address variant the user did not
approve.

### International Scope

Hosted v1 supports international shipping only for configured, review-tested
lanes. Each enabled lane needs a `HostedLanePolicy` or equivalent config:

- supported services
- required fields
- customs/commodity validation version
- duties/taxes handling
- allowed origin profiles/accounts
- max spend/tolerance rules
- fixture coverage
- widget summary redaction

`INTERNATIONAL_ENABLED_LANES=*` remains local/private-beta only and fails hosted
production readiness.

The UPS MCP `international_charges` capability is necessary but not sufficient
to enable hosted international shipping. It proves normalized charge shape
support only. Hosted production must fail closed for any origin/destination lane
that is not explicitly allowlisted with a reviewed lane policy and passing
fixture coverage.

Public outputs may summarize international state, for example "3 international
rows, 1 missing commodity code, estimated duties/taxes $X". They must not expose
commodity descriptions, HS codes, full commercial invoice details, full
addresses, phone numbers, or raw customs payloads.

`confirm_shipment_preview` binds the lane policy version and customs validation
hash into the approval record and confirmation token.

### Rate Comparison And Selection

`preview_shipments` produces a default purchasable preview quickly using the
requested/default service.

`compare_rates(preview_id, scope, service_codes?)` is explicit and read-only. It
uses UPS Shop mode through the internal UPS adapter and returns rate options plus
opaque `rate_option_id`s.

`select_rate(preview_id, preview_version, rate_option_id, scope)` is
tenant-checked, write-audited, non-purchase, and explicit. It persists the
selected option into a new preview version or CAS-updated draft state before
confirmation.

After token issuance, `create_shipments` accepts only `confirmation_token`. It
does not accept connected account IDs, account numbers, credentials, service
codes, rate choices, origin data, or shipment payloads.

### Approval And Confirmation

Preview/selection returns a confirmation-ready state:

- `preview_id`
- `preview_version`
- totals
- selected service summary
- `confirmation_request_id`
- expiry
- `confirmation_url`
- widget hints

It does not return a usable confirmation token.

Add a hosted approval request table separate from `ConfirmationRecord`.
`HostedApprovalRequest` tracks:

- `pending`
- `approved`
- `consumed`
- `expired`
- `cancelled`

It binds:

- tenant ID
- preview ID
- preview version
- selected-rate checksum
- purchase scope hash
- lane policy/version
- operation
- authorized total cents
- authorized currency
- authorized row count
- max authorized row cents
- tolerance policy
- expiry
- approval actor
- approval proof hash

The model-visible `confirmation_request_id` is not sufficient to mint a token.
`confirm_shipment_preview` requires an opaque approval proof delivered through
widget-only metadata or generated by the hosted confirmation page after
authenticated user approval.

`confirm_shipment_preview` transactionally CASes `approved -> consumed` and
creates the one-time `ConfirmationRecord` token for `create_shipments`.

The confirmation token binds:

- tenant ID
- operation
- preview ID
- preview version
- selected-rate checksum
- purchase scope hash
- spend ceiling fields
- expiry

### Shipment Execution

`create_shipments` validates tenant/scope, consumes the one-time token, CASes the
preview/job from `pending_confirmation` to `running`, enqueues execution, and
returns `{job_id, status}`.

Hosted execution happens in durable workers, not inline in the MCP request.

Each hosted job row CASes from `pending -> in_flight` with:

```text
hosted_idempotency_key = hosted_job_id + preview_row_id + row_checksum
```

This state is committed before calling UPS.
Hosted worker/execution code owns exact idempotency key construction and
verification. It must verify the key matches the committed
`hosted_job_id:preview_row_id:row_checksum` context before crossing the UPS
boundary. The UPS boundary contract only requires the normalized response to
echo a non-empty `idempotencyKey`.

For each eligible preview row, persist a canonical `rate_payload_hash` and
redacted payload summary derived from:

- encrypted row payload
- origin profile
- UPS account binding
- package defaults
- selected service
- international enrichment
- deterministic normalization rules

At execution, rebuild the create/rate-equivalent payload from stored inputs and
compare the hash before any UPS create call. If the hash differs, stop before
UPS and require a new preview/version.

The worker also enforces authorized spend ceilings. If actual UPS charges exceed
the approved per-row or total tolerance, do not silently purchase beyond the
user's approval. Depending on where the discrepancy is detected, fail pre-UPS,
stop remaining rows, or mark post-UPS discrepancies `needs_review`.

After the UPS boundary, rows can only become `completed` or `needs_review`,
never retried as plain `pending` unless a deterministic pre-UPS validation failed
before any carrier call.

Hosted workers can run internal reconciliation using stored UPS shipment fields
and idempotency keys, but public MCP v1 exposes no retry-row, resolve-row, or
tracking-number lookup surface.

### Job Status

`get_job_status(job_id)` is the canonical marketplace polling mechanism for both
import jobs and shipment jobs. It returns tenant-checked, transcript-safe
summaries:

- status
- phase
- row counts by state
- total/label counts
- cost totals
- warning categories
- retry/review counts
- timestamps
- next actions
- widget hints
- opaque follow-up IDs

It does not expose row payloads, order data, label paths, tracking-number lookup,
or SSE dependencies.

### Labels

Hosted labels are backed by tenant-scoped artifact metadata and object storage.
Private carrier boundary responses may include label bytes only for hosted
workers to persist into object storage. Those bytes must be stripped before any
model-visible `structuredContent`, widget payload, job status, audit summary, or
label link response.
The UPS boundary validates label response shape only. Hosted workers/artifact
services own base64 decoding, size limits, content-type sniffing, malware
scanning, tenant-scoped object storage, and signed-link publication.

`get_label_links(job_id)` verifies tenant/job ownership and returns only:

- opaque artifact IDs
- short-lived signed HTTPS download URLs
- expiry timestamps
- safe document metadata

It never returns local paths, `s3://` URIs, raw PDFs, base64 labels, or
tracking-number-based lookup.

### Audit Summary

`get_audit_summary(job_id)` verifies tenant/job ownership and returns a curated,
provider-safe summary:

- timeline milestones
- actor/tool names
- confirmation ID/hash references
- mapping/filter hashes
- row counts
- service selections
- cost totals
- warning categories
- label artifact IDs
- redacted side-effect outcomes

It must not return raw `AuditLog.details`, raw decision payloads, JSONL exports,
UPS request/response bodies, row payloads, addresses, or message text.

### Quotas And Abuse Controls

Hosted quotas are ledger-backed and tenant-scoped for:

- imports
- uploaded bytes
- rate calls
- label purchases
- international labels
- demo/reviewer labels
- total authorized spend

`preview_shipments` and `compare_rates` check or reserve rate-call budget.
`confirm_shipment_preview` verifies the approval fits remaining spend/label
quotas. The worker atomically consumes label/spend quota before each UPS create
call and releases or reconciles reservations on terminal failure.

Quota failures use the safe error envelope with category `quota` and next actions
such as `connect_account`, `reduce_scope`, or `contact_support`.

### Lifecycle And Retention

Add hosted policies and services for:

- account disconnect
- tenant deletion
- artifact expiration
- label retention
- order-batch retention
- audit retention
- provider review/demo cleanup

Deleting a tenant revokes connected accounts, deletes or expires hosted
artifacts, removes hosted batches/previews/jobs/labels, and retains only legally
necessary redacted audit metadata if required by policy.

Disconnecting a UPS/Shopify account revokes provider tokens and makes future
operations fail with `connect_account`. It does not merely hide credentials.

## UPS MCP Separate Repository Boundary

The external UPS MCP server must satisfy the hosted ShipAgent adapter contract.
This repository should define and test the expected contract, but the actual UPS
MCP changes happen in the UPS MCP repository.

Required UPS MCP capabilities for hosted v1:

- rate quote with `requestoption="Rate"`
- rate shopping with `requestoption="Shop"`
- address validation with normalized valid/ambiguous/invalid/candidate output
  when called in ShipAgent hosted response mode
- create shipment with a required deterministic idempotency key in ShipAgent
  hosted response mode
- idempotency metadata pass-through, distinct from any optional claim of true
  carrier-level idempotent create semantics
- normalized shipment response with shipment ID, tracking numbers, charges,
  label data metadata, and safe warnings when called in ShipAgent hosted
  response mode
- normalized charge breakdown for international/duties/taxes where applicable
  when called in ShipAgent hosted response mode
- international lane enablement only through explicit ShipAgent reviewed lane
  policy and passing fixtures; `international_charges` alone does not enable a
  lane
- stable error-code mapping for auth, rate limit, validation, service
  unavailability, address failure, customs failure, and ambiguous transport
- no unsafe retries for mutating shipment creation
- capability/version endpoint or equivalent self-description with
  `contract_version="hosted-v1"`
- explicit response format declaration including `shipagent_v1`
- shape-level validation of hosted-safe UPS error envelopes in
  `response_format="shipagent_v1"`

The external UPS MCP server may preserve raw UPS API payloads as its default
tool response format for existing local/dev users. ShipAgent hosted calls should
request an explicit hosted-normalized response mode, such as
`response_format="shipagent_v1"`, and the ShipAgent boundary validators should
evaluate that normalized mode.

Hosted-normalized success validators should require minimum normalized fields
while allowing extra normalized metadata. Public ShipAgent result DTOs are still
responsible for stripping hosted-unsafe fields before transcript or widget
output. Hosted-safe UPS error envelopes are different: they are closed shapes
because error leakage is safety-sensitive.

For `create_shipment` in hosted-normalized mode, ShipAgent passes a deterministic
`idempotency_key` such as `hosted_job_id:preview_row_id:row_checksum`. The UPS
MCP server must preserve that key in available transaction/correlation metadata
and return it in the normalized response. The capability declaration should use
`idempotency_metadata_passthrough` for this behavior. It should declare
`carrier_idempotent_create` only if true UPS-side idempotent create semantics
are proven.

The ShipAgent UPS boundary validator checks only that `idempotencyKey` is a
non-empty string. It does not validate the exact key format because the boundary
phase does not own hosted job IDs, preview row IDs, row checksums, or row state.
The later hosted worker/execution phase validates exact format and row-state
match.

For hosted-normalized domain failures, the UPS boundary should validate only the
safe envelope shape. Safe errors include code, category, message, retryability,
and correlation ID, and the error envelope must contain only those safe keys.
They must not include raw details, request payloads, stack traces, local paths,
credentials, or raw UPS response bodies.

This repository should add:

- `UpsAdapterCapabilities` or equivalent DTO
- startup/readiness check against the UPS MCP server
- tests that fail hosted readiness if required capabilities are missing
- hosted-v1 boundary fixtures for Rate, Shop, address validation, create
  shipment, and error mapping
- documentation of UPS MCP repo changes required for hosted v1

The ShipAgent-side boundary should be transport-neutral. The UPS boundary phase
defines the client protocol, readiness-only adapter, validators, and fixture
contract, and may use stdio-backed clients for local development and tests. It
does not add hosted operation methods for Rate, Shop, address validation, or
shipment creation. Hosted production must use a private remote UPS MCP client,
but that transport implementation, service-to-service auth, endpoint
configuration, network observability, per-tenant credential handoff, operation
call wiring, artifact persistence, and production startup integration belong to
later hosted runtime/auth/storage phases. Hosted production readiness remains
fail-closed until the private remote client exists and satisfies the boundary
checks.

The UPS boundary phase does not add hosted international lane fixtures. Those
fixtures are deferred until hosted lane policy and provider review gates exist:
Phase 6 defines the lane policy and per-lane fixture requirement, Phase 9 adds
end-to-end readiness/review automation, and Phase 10 tracks the UPS MCP
repository's international charge/customs fixture work.

Do not block this repository's planning on implementing the UPS MCP repo changes,
but do not mark hosted production ready until the external UPS MCP contract is
met.

## Testing And Readiness Gates

Production readiness requires automated gates.

### Registry Gates

- first-release export list exactly matches OpenAI + Anthropic + generic MCP
- production tool list exactly matches the v1 tool surface in this spec
- non-production tools remain registered but `hosted_readiness="not_ready"`
- every public tool has title, description, typed schemas, auth scopes,
  side-effect class, confirmation policy, audit policy, provider export rules,
  and UI binding where needed
- public write tools use explicit confirmation models, not a single overloaded
  boolean
- private/internal UPS primitives are not exported publicly
- generated artifacts are current

### Hosted MCP Gates

- production tool listing matches bound production handlers
- unbound public production tools fail tests
- tool annotations match behavior
- structured outputs validate against schemas
- safe result envelopes and error envelopes validate
- resources are registered and served
- OAuth challenge behavior works
- provider-safe errors are returned
- production startup fails closed on missing DB/object storage/queue/KMS/OAuth
  issuer/provider artifact registration/UPS MCP capabilities
- diagnostic `degraded` readiness never satisfies hosted production startup;
  production requires `status == "ready"`

### Model Provider Agnosticism Gates

- required install and packaged runtime contain no `claude-agent-sdk` dependency
- active source outside tests contains no `claude_agent_sdk` imports
- backend startup succeeds without Claude SDK installed
- local conversation API and SSE contract tests pass through a fake normalized
  model provider
- OpenAI, Anthropic Messages API, and Gemini HTTP adapters pass shared contract
  tests for message translation, tool calls, streaming deltas, final responses,
  safe errors, and usage metadata
- local runtime invokes workflow/tool handlers directly through Python dispatch,
  not through a Claude SDK MCP client loop
- settings and onboarding expose model-provider selection and provider-keyed
  credentials instead of requiring Anthropic as the only model provider
- no row-level order data is placed in model-provider prompts
- provider adapters contain no shipping business logic

### Workflow DTO Gates

- generated JSON schemas match Pydantic DTOs
- handler inputs and outputs use DTOs, not handwritten ad hoc schemas
- provider artifacts drift-test against DTOs
- widget fixtures use schema-valid structured outputs

### Workflow Gates

- upload session to validated artifact
- file upload/import to immutable order batch
- Shopify import with closed filters to immutable order batch
- preview to address validation to rate comparison
- rate selection
- approval request and user approval
- confirmation token issuance and one-time consumption
- async create-label job
- row-level idempotency and in-flight recovery
- expiring label links
- audit summary
- hosted import and shipment job polling

### Tenant Isolation Gates

- cross-tenant account access rejected
- cross-tenant artifact access rejected
- cross-tenant batch access rejected
- cross-tenant preview/job/label/audit access rejected
- repository read/write methods require `tenant_id`
- seeded demo credentials cannot leak to normal tenants

### Widget And Resource Gates

- every `ui://` binding has registered resource metadata
- CSP/widget domains validate for OpenAI
- widgets render representative `structuredContent`
- widgets handle partial and error states
- widgets call follow-up tools where supported
- widget-only data stays in `_meta` where supported
- fallback hosted pages work for clients without widget support
- screenshot/contract tests cover each widget
- transcript-visible data contains no secrets or raw PII

### Provider Review Gates

- OpenAI developer-mode tool scan succeeds
- OpenAI write-action confirmation behavior is verified
- OpenAI resource/CSP/widget domain metadata validates
- Claude remote MCP connection succeeds
- Anthropic submission checklist is generated and complete
- Anthropic examples/docs/privacy/support/test account instructions exist
- generic MCP inspector/test-client flow passes
- published docs include setup, auth, privacy, support, and at least three
  realistic examples
- provider review automation owns fixture freshness, review-age, and provenance
  checks; stale review evidence may produce diagnostic `degraded` readiness,
  which still fails hosted production startup

### UPS MCP Contract Gates

- required UPS MCP capabilities are reported
- Rate and Shop fixtures pass
- address validation fixtures pass
- create-shipment fixture passes with idempotency metadata
- international lane fixture passes for every hosted-enabled lane
- no international lane is hosted-enabled by capability declaration alone
- error mapping fixtures produce provider-safe ShipAgent errors
- mutating tool retry policy is compatible with hosted idempotency rules
- `degraded` UPS boundary readiness is diagnostic only and does not pass
  production startup

## Out Of Scope For This First Release

- Microsoft Copilot app package generation
- Gemini marketplace artifact/review bundle
- pickup scheduling
- void shipment
- tracking write-back
- broad multi-carrier support
- customer self-host installer
- migration of the full desktop Angular shell to hosted mode
- public row retry/resolve tools
- public exploratory row/sample tools
- public tracking-number lookup surface
- public origin-profile creation with full address fields
- MCP tool arguments carrying file bytes, local paths, credentials, row arrays,
  raw shipment payloads, or full addresses

These should remain compatible with the architecture but not block the first
OpenAI/Anthropic/generic MCP production release.

## Implementation Direction

The work should be staged in this repository before any production readiness
claim.

### Phase 0: Workflow Spine And Claude SDK Exit

- Define the canonical local/hosted workflow spine that both marketplace tools
  and local/Tauri conversation call.
- Add normalized model message, tool-call, stream-event, error, and usage DTOs.
- Add HTTP model-provider adapters for OpenAI, Anthropic Messages API, and
  Gemini using `httpx`, not provider SDKs.
- Add a direct Python workflow/tool dispatcher for local conversation runtime.
- Preserve the existing FastAPI conversation API and SSE event contract.
- Remove Claude Agent SDK imports, startup checks, package dependencies,
  packaging hidden imports, and Claude-only model defaults.
- Convert Anthropic credential handling from a global prerequisite to one
  provider-keyed model credential.
- Add provider-agnostic contract tests and fake-provider SSE tests.

### Phase 1: Registry, DTOs, And Artifact Contract

- Make the design authoritative for v1 export surface.
- Replace `requires_confirmation` as the public safety model with explicit
  confirmation policy values:
  - `none`
  - `oauth_consent`
  - `hosted_state_write`
  - `preview_token_issuer`
  - `strict_preview_token`
- Make `hosted_readiness="ready"` a strict production signal.
- Add typed hosted request/result DTOs and generate JSON schemas from them.
- Update OpenAI, Anthropic, and generic MCP projections.
- Add fail-closed registry/artifact drift tests.

### Phase 2: Hosted Models, Repositories, And Readiness

- Add tenant-scoped hosted DB models and migrations.
- Add repository methods that require `tenant_id` for all hosted reads/writes.
- Add hosted KMS/encryption service abstraction and readiness probes.
- Add object storage and queue abstractions with production readiness checks.
- Add lifecycle/retention services.
- Add tenant isolation tests.

### Phase 3: UPS MCP Boundary And External Contract

- Implement the ShipAgent-side hosted UPS boundary plan in
  `docs/superpowers/plans/2026-06-04-shipagent-ups-mcp-boundary.md`.
- Add capability DTOs, response validators, readiness checks, fixtures, and
  the standalone external UPS MCP contract document at
  `docs/integrations/ups-mcp-hosted-contract.md`.
- Define a transport-neutral UPS boundary client protocol; do not implement the
  hosted private remote MCP transport in this phase.
- Keep `HostedUpsBoundaryAdapter` readiness-only in this phase; hosted operation
  methods and `response_format="shipagent_v1"` call wiring belong to later
  hosted worker phases.
- Keep raw UPS MCP primitives private and unreachable from public provider
  adapters.
- Do not edit registry exports, public hosted tool projections, or generated
  provider artifacts in this phase; those belong to Phase 1.
- Fail hosted readiness when required UPS MCP capabilities are missing.
- Treat `degraded` UPS boundary readiness as non-production-ready; only
  `status == "ready"` may satisfy later hosted startup gates.

### Phase 4: Hosted Auth, Setup, Accounts, And Profiles

- Add hosted request context and OAuth/bearer validation.
- Resolve tenants from provider identity.
- Enforce registry auth scopes on every tool call.
- Add setup/status tool.
- Add account-link initiation/callback services.
- Add reviewer/demo/private-beta tenant controls.
- Add origin profile hosted page flow and selection surface.

### Phase 5: Hosted Import Pipeline

- Add hosted upload-session pages/resources.
- Add artifact validation/quarantine/scanning state machine.
- Add durable import jobs for uploaded files and Shopify.
- Add immutable order batches and encrypted row payloads.
- Add import idempotency and Shopify snapshot metadata.
- Add order import status widget.

### Phase 6: Hosted Preview, Address, International, And Rates

- Add preview configuration DTOs and hashing.
- Add preview/version state machine.
- Add address validation records and resolution flow.
- Add hosted lane policy for international v1 lanes.
- Require reviewed fixtures before any international lane becomes
  hosted-enabled.
- Add default preview rating.
- Add read-only `compare_rates`.
- Add explicit `select_rate`.
- Add shipment preview and rate comparison widgets.

### Phase 7: Approval, Confirmation, And Execution

- Add hosted approval request state separate from confirmation tokens.
- Add widget/page approval proof flow.
- Bind approval to preview version, selected-rate checksum, purchase scope, lane
  policy, spend ceiling, and expiry.
- Add strict confirmation token issuance/consumption.
- Add async shipment execution jobs and workers.
- Add row-level CAS/idempotency, payload hash checks, quota consumption, and
  needs-review recovery.

### Phase 8: Labels, Audit, Errors, And Public Status

- Add hosted label artifact metadata and signed URLs.
- Add transcript-safe job status for import and shipment jobs.
- Add curated audit summary service.
- Add safe hosted error mapping.
- Add label links and audit widgets.

### Phase 9: Provider Review Bundles And End-To-End Gates

- Generate full OpenAI Apps SDK bundle and review checklist.
- Generate Anthropic remote MCP/directory metadata and review materials.
- Generate generic MCP descriptor and inspector fixtures.
- Add end-to-end readiness suites across registry, workflow, tenant isolation,
  widgets, provider artifacts, and UPS MCP capability compatibility.
- Add fixture freshness/review-age/provenance checks that can emit diagnostic
  `degraded` readiness without passing hosted production startup.

### Phase 10: UPS MCP Repo Follow-Up

After this repository's adapter contract is explicit, open the corresponding
work in the UPS MCP repository:

- capability/version reporting
- Shop mode guarantees
- address validation normalization
- idempotency metadata pass-through
- create shipment response normalization
- international charge/customs fixtures
- explicit reviewed-lane allowlist compatibility
- safe error mapping
- mutating retry policy verification

This phase is tracked separately because the UPS MCP server is not owned by this
repository.

Each phase must keep local/Tauri behavior working and avoid moving UPS business
details into provider-specific runtime code.
