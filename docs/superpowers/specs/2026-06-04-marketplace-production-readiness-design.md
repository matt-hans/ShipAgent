# Marketplace Production Readiness Design

## Goal

Make ShipAgent production-ready for an initial hosted marketplace release across
OpenAI Apps SDK, Anthropic remote MCP, and generic MCP clients.

The first release is hosted SaaS first, with a clean path to self-hosted
packaging later. It supports the core shipping workflow, not the entire future
catalog:

- UPS account connection
- Shopify connection
- file upload order batches
- Shopify order import
- shipment preview
- rate comparison
- explicit confirmation
- label creation
- job status
- expiring label links
- audit summary

Pickup scheduling, voiding, and tracking write-back remain follow-up public
catalog work unless they are needed for marketplace review.

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
- OpenAI artifacts are tool descriptors, not a complete app with registered
  resources, OAuth, widgets, and review scripts.
- Anthropic export is intentionally not enabled yet.
- Microsoft and Gemini artifacts are outside the first release scope.
- The shared widget layer is only a placeholder preview element.
- Hosted OAuth/account linking, tenant ownership enforcement, object storage,
  signed label links, and end-to-end hosted workflows are incomplete.
- Real shipping behavior is still split across local FastAPI routes, Claude
  agent tools, and desktop-oriented services.

## External Marketplace Requirements

### Shared MCP Requirements

The hosted surface should be a remote MCP server over Streamable HTTP. It must
list tools, support tool calls, return `structuredContent`, serve UI resources
where supported, and apply authorization on every protected call.

The public server must expose ShipAgent workflow tools, not raw carrier tools.

### OpenAI Apps SDK

OpenAI Apps SDK apps are MCP servers plus UI resources. The first release must
provide:

- registered app tools with titles, descriptions, schemas, annotations, and
  security schemes
- registered app resources for widgets using `ui://...` resource URIs
- `structuredContent` matching declared output schemas
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

### Generic MCP

Generic MCP clients should get the same tool contracts and structured results.
If the client supports MCP Apps/UI resources, attach widgets. If not, return
concise text plus structured content and hosted URLs for previews, labels, and
audit summaries.

## Architecture

ShipAgent should build a public hosted MCP gateway in this repository.

```
OpenAI / Claude / MCP client
  -> ShipAgent hosted MCP gateway
  -> marketplace auth, tenant identity, tool registry, widgets
  -> provider-neutral workflow services
  -> hosted state and audit storage
  -> internal adapters: UPS MCP, Shopify, file ingestion
```

UPS MCP remains an internal carrier adapter. It should handle UPS endpoint
coverage, UPS auth/token behavior, UPS request/response validation, and UPS
error normalization. Public marketplace tools should never expose raw UPS MCP
primitives.

Provider-specific code should be packaging and protocol translation only.
Shipping business logic belongs in provider-neutral ShipAgent workflow services.

## Components

### Hosted MCP Gateway

Owns the public remote MCP endpoint.

Responsibilities:

- Streamable HTTP MCP transport
- tool and resource registration from the registry
- structured result envelopes
- provider-safe errors
- OAuth challenge behavior
- request context extraction
- tenant and scope enforcement
- no unbound public tools in production

### Hosted Auth

Owns marketplace identity and account-linking state.

Responsibilities:

- tenant resolution from provider host and subject
- OAuth/OIDC protected-resource metadata
- access token validation
- scope checks on every tool call
- account-link initiation and callback handling
- private-beta admin-seeded credential fallback
- reviewer/demo tenant controls

Production marketplace use requires real customer-owned UPS and Shopify
connections. Admin-seeded credentials are allowed only for private beta and
review/demo tenants.

### Hosted Storage

Use a simple managed app stack for the first release:

- FastAPI service
- managed Postgres
- object storage for uploads and labels
- managed secrets
- logs and metrics

SQLite/local filesystem remain local development and desktop paths only.

Hosted storage owns:

- tenants
- connected accounts
- order batches
- previews
- confirmation records
- jobs
- label artifacts
- audit records

Every row that belongs to a tenant must be tenant-scoped. Every read and write
must enforce ownership.

### Hosted Workflows

Provider-neutral services should own the core shipping flow:

- `connect_carrier_account`
- `connect_store`
- `upload_or_import_orders`
- `preview_shipments`
- `compare_rates`
- `create_shipments`
- `get_job_status`
- `get_label_links`
- `get_audit_summary`

These services should be callable from the hosted MCP gateway and, where useful,
from existing FastAPI/Tauri paths. They must not depend on OpenAI, Anthropic,
Gemini, Microsoft, or Claude runtime APIs.

### Hosted Widgets

Build a standalone marketplace widget bundle separate from the Angular shell.

First release widgets:

- order import/upload status
- shipment preview
- rate comparison
- final confirmation
- label links
- audit summary

Widgets consume `structuredContent` and call follow-up MCP tools where the host
supports it. They must not require the desktop shell.

### Provider Adapters

Provider adapters should generate:

- OpenAI Apps SDK tool descriptors and app resource metadata
- Anthropic remote MCP/directory metadata and review assets
- generic MCP descriptor snapshots
- test fixtures and submission checklists

Microsoft and Gemini remain later adapter targets for this spec. The registry
should keep enough metadata to add them without changing workflow services.

## Data Flow

1. User enables ShipAgent in ChatGPT, Claude, or a generic MCP client.
2. Client connects to the hosted ShipAgent MCP endpoint.
3. ShipAgent resolves tenant identity from provider/OAuth context.
4. User connects UPS and Shopify, or a private-beta/test tenant uses seeded
   credentials.
5. User uploads a file or imports Shopify orders.
6. ShipAgent stores an order batch and returns structured status plus a widget.
7. User asks to ship orders.
8. `preview_shipments` validates the batch, maps shipment payloads, calls UPS
   rating through the internal carrier adapter, stores preview and audit data,
   and returns `structuredContent` plus preview/rates UI.
9. User confirms in the provider UI.
10. `create_shipments` consumes a one-time confirmation token, creates labels
    through the workflow service and UPS MCP, stores label artifacts, records
    audit events, and returns job status plus label links.
11. `get_job_status`, `get_label_links`, and `get_audit_summary` provide
    follow-up state.

Row-level order data must not be placed in model prompts. The model may see
summaries, structured results, confirmation state, and widget-visible data
appropriate for user review.

## Error Handling And Safety

Every mutating or financial operation requires:

- stored preview state
- explicit user confirmation
- one-time confirmation token
- idempotency key
- audit entry

Hosted errors should be helpful and provider-safe:

- no stack traces
- no raw credential values
- no raw labels in transcript-visible content
- no local filesystem paths
- no full customer row payloads in model-visible messages

OAuth failures should return proper MCP/HTTP auth challenges where supported.
Scope checks happen on every tool call, not just during account linking.

Label links must be expiring, tenant-scoped, and backed by object storage.

Demo tenant use must be capped and rate-limited so review testing cannot create
uncontrolled shipments.

## Testing And Readiness Gates

Production readiness requires automated gates.

### Registry Gates

- every public tool has title, description, schemas, auth scopes, side-effect
  class, confirmation policy, audit policy, provider export rules, and UI binding
  where needed
- side-effecting tools require confirmation
- private/internal UPS primitives are not exported publicly
- generated artifacts are current

### Hosted MCP Gates

- tool listing matches bound production handlers
- unbound public tools fail tests
- tool annotations match behavior
- structured outputs validate against schemas
- resources are registered and served
- OAuth challenge behavior works
- provider-safe errors are returned

### Workflow Gates

- file upload/import to order batch
- Shopify import to order batch
- preview to rate comparison
- confirmation token issuance and consumption
- create-label job
- expiring label links
- audit summary
- idempotent retry behavior

### Tenant Isolation Gates

- cross-tenant account access rejected
- cross-tenant batch access rejected
- cross-tenant preview/job/label/audit access rejected
- seeded demo credentials cannot leak to normal tenants

### Widget Gates

- widgets render representative `structuredContent`
- widgets handle partial and error states
- widgets call follow-up tools where supported
- widget transcript-visible data contains no secrets
- widget CSP and domain metadata validate for OpenAI

### Provider Review Gates

- OpenAI developer-mode tool scan succeeds
- OpenAI write-action confirmation behavior is verified
- Claude remote MCP connection succeeds
- Anthropic submission checklist is generated and complete
- generic MCP inspector/test-client flow passes
- published docs include setup, auth, privacy, support, and at least three
  realistic examples

## Out Of Scope For This First Release

- Microsoft Copilot app package generation
- Gemini direct function-calling runtime
- pickup scheduling
- void shipment
- tracking write-back
- broad multi-carrier support
- customer self-host installer
- migration of the full desktop Angular shell to hosted mode

These should remain compatible with the architecture but not block the first
OpenAI/Anthropic/generic MCP production release.

## Implementation Direction

The work should be staged:

1. Correct registry readiness flags so only truly executable hosted tools export.
2. Build hosted workflow services for the core flow.
3. Wire a production hosted MCP server with real handlers and resources.
4. Add hosted auth, tenant storage, object storage, and confirmation flows.
5. Build standalone widgets.
6. Generate OpenAI, Anthropic, and generic MCP review artifacts.
7. Add end-to-end review and readiness test suites.

Each stage should keep local/Tauri behavior working and avoid moving UPS
business details into provider-specific runtime code.
