# LLM App Store Portability Design

Date: 2026-06-02

## Purpose

ShipAgent should become one technical codebase that can ship through multiple AI-native app ecosystems without becoming separate products for each provider. The goal is technical portability first: shared core workflow logic, shared schemas, shared safety policy, and generated provider-specific distribution packages.

The selected approach is **Canonical Platform Core**:

- ShipAgent's backbone becomes the canonical workflow/tool layer.
- Claude Agent SDK, OpenAI Apps SDK, Microsoft Copilot, Gemini function calling, generic MCP clients, and desktop/Tauri become runtimes or distribution adapters.
- The separate UPS MCP dependency remains an internal carrier module. External app-store surfaces expose ShipAgent workflow tools, not raw carrier primitives.

## Current Context

The existing repo is a Tauri desktop app with a Python/FastAPI backend, Angular/Nx frontend, Claude Agent SDK orchestration, local stdio MCP servers, and an external UPS MCP dependency.

The current architecture documents say the Claude Agent SDK is the backbone. That must change for provider portability. The new rule is:

> ShipAgent's backbone is the canonical workflow/tool layer. LLM providers are runtimes and distribution adapters.

Known current issues to fold into the migration:

- Release packaging still references stale `frontend/` paths while the actual frontend directory is `shipagent-frontend/`.
- Bundled MCP subcommands import `main()` functions that the local MCP server modules do not define.
- Public MCP tools currently lack complete titles, annotations, and provider-ready metadata.
- README frontend stack references are stale in places.
- Local `.venv` currently uses Python 3.14 even though the project target is Python 3.12+.

## Provider Docs Basis

This design is based on current official/provider documentation checked during brainstorming:

- OpenAI Apps SDK: ChatGPT apps are exposed through an MCP server, with optional iframe-rendered web components and tool-to-resource metadata.
- OpenAI Apps SDK MCP server docs: app tools/resources use registered tool descriptors, schemas, structured content, and UI resource URIs.
- MCP Apps: interactive MCP UI resources can render in compliant clients such as Claude and ChatGPT, with graceful fallback when a client lacks UI support.
- Anthropic Connectors: submission paths include remote MCP servers, desktop MCP bundles, MCP Apps, and plugins, with directory review requirements.
- Microsoft 365 Copilot: declarative agents/plugins can call MCP servers or REST APIs with OpenAPI descriptions; consequential operations need confirmation metadata.
- Gemini API: portable non-MCP support is function declarations/tool calls, with the application executing tools and sending results back.

References:

- https://developers.openai.com/apps-sdk/quickstart
- https://developers.openai.com/apps-sdk/build/mcp-server
- https://developers.openai.com/apps-sdk/deploy/submission
- https://developers.openai.com/apps-sdk/app-submission-guidelines
- https://apps.extensions.modelcontextprotocol.io/
- https://claude.com/docs/connectors/building/submission
- https://claude.com/docs/connectors/building/mcpb
- https://learn.microsoft.com/en-us/copilot/plugins/overview
- https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/overview-api-plugins
- https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api-plugin-confirmation-prompts
- https://ai.google.dev/gemini-api/docs/function-calling

## Architecture

ShipAgent should be organized into four layers.

### 1. Canonical Registry

Checked-in schema files define every public and private tool. The registry is the source of truth for provider outputs, docs, tests, and review assets.

Each registry entry includes:

- tool name, title, and model-facing description
- input schema and output schema
- visibility: `public`, `private`, `desktop_only`, `dev_only`
- availability: `hosted`, `local`, or both
- side-effect class: `read`, `estimate`, `write`, `purchase`, `external_mutation`, `destructive`
- confirmation policy and confirmation copy
- auth scopes, such as `orders:read`, `shipments:create`, `tracking:write`
- provider export targets: OpenAI, Anthropic, Microsoft, Gemini, generic MCP
- UI resource binding for embedded widgets
- audit level: `none`, `basic`, `full`, `regulated`
- result sensitivity: `public`, `business`, `confidential`, `credential_redacted`
- rate limits and idempotency requirements
- hosted/local storage requirements

### 2. Workflow Services

Provider-neutral services implement actual product behavior. They are callable from hosted MCP, local MCPB/stdio, REST/OpenAPI, CLI, desktop, tests, and future provider runtimes.

Core services include:

- account/store connection
- order ingestion and normalization
- file upload ingestion
- data schema discovery and mapping
- shipment preview
- rate shopping
- confirmation token generation/validation
- shipment creation
- tracking
- pickup scheduling/canceling
- voiding
- write-back to connected systems
- label storage and signed links
- job recovery
- decision and execution audit

Workflow services must not depend on OpenAI, Anthropic, Gemini, Microsoft, or Claude runtime APIs. Provider-specific reasoning can call these services, but the services remain deterministic and portable.

### 3. Internal Connectivity Modules

The UPS MCP dependency remains internal. ShipAgent calls it for carrier primitives and schema validation, but public provider apps see canonical ShipAgent workflows.

This pattern applies to future integrations:

- carrier MCPs: UPS, FedEx, USPS, DHL
- commerce platforms: Shopify, Amazon, WooCommerce
- ERP/data systems: SAP, Oracle, custom databases

Internal connectivity modules may expose private tools for desktop, testing, or trusted deployments. They are not directly exported to public marketplaces by default.

### 4. Provider Adapters

Provider adapters translate the canonical registry and workflow services into provider-specific artifacts.

Adapters contain:

- transport handling
- auth handoff
- provider-specific manifest generation
- schema translation
- UI resource binding
- response shaping
- review/package asset generation

Adapters do not contain shipping workflow logic.

## Public Hosted Product

Most users should not need the desktop app. Hosted mode is the primary app-store product.

Provider app-store users should be able to:

- connect UPS and commerce/store accounts through OAuth/account linking
- upload/import orders
- preview shipment batches
- compare rates
- create labels after confirmation
- track packages
- schedule pickups
- void shipments
- write tracking back to connected cloud systems
- view job status and audit summaries
- download labels through expiring links

Users must not paste carrier, store, or platform API secrets into chat transcripts. Public app-store surfaces use account linking and OAuth flows. Local desktop/dev mode can keep keyring/env credential fallback.

## Tool Catalog

The catalog is two-tiered.

### Public Hosted Marketplace Catalog

This is the feature-complete app-store product surface:

- `connect_account`
- `connect_store`
- `upload_or_import_orders`
- `preview_shipments`
- `rate_shipment`
- `create_shipments`
- `track_package`
- `schedule_pickup`
- `void_shipment`
- `write_back_tracking`
- `get_job_status`
- `get_label_links`
- `get_audit_summary`

These tools map to business workflows and are suitable for marketplace review.

### Desktop/Private Catalog

This catalog supports local OS affordances, private deployments, tests, and advanced operations:

- arbitrary local file-path reads without upload
- watch folders
- direct write-back to local CSV/Excel files
- local keyring/env credential mode
- local printer or label-printer integration
- raw UPS MCP primitives
- low-level data tools such as schema/query/import primitives
- correction/mapping/filter internals
- debug/admin/audit tools

Private catalog tools are not required for the normal hosted product.

## Hosted Mode And Auth

Hosted mode needs a multi-tenant backend with:

- tenant/user accounts
- OAuth/account linking for UPS, Shopify, Amazon, WooCommerce, and future providers
- encrypted credential storage scoped by tenant/provider
- auth scopes mapped from the canonical registry
- job/session/audit ownership checks
- public HTTPS MCP endpoint
- REST/OpenAPI endpoints generated from registry metadata
- upload-based file ingestion
- label storage with expiring signed links
- provider-safe audit summaries

Desktop/local mode can keep local filesystem workflows, keyring credentials, and private network/offline assumptions. Hosted OAuth is the default for public provider apps.

## Confirmation And Safety

Confirmation gates are platform-independent.

Any operation that purchases labels, schedules pickups, voids shipments, writes tracking, mutates connected platforms, or has destructive side effects must produce a structured preview/confirmation object first.

The confirmation object includes:

- operation type
- estimated cost
- affected orders/shipments
- destination and service summary
- carrier/account summary
- write-back targets
- irreversible or billable effects
- idempotency key
- confirmation token
- expiration
- human-readable confirmation copy

Provider adapters render this through their native mechanisms:

- embedded MCP Apps/OpenAI widget where supported
- Anthropic MCP App/connector UI where supported
- Microsoft OpenAPI confirmation metadata and prompt copy
- Gemini structured response plus hosted confirmation link
- generic MCP text plus structured content fallback

## Provider Outputs

### OpenAI

Generate an Apps SDK-compatible MCP surface with registered tools and UI resources. Tool descriptors include titles, schemas, structured outputs, UI resource metadata, and safety metadata derived from the registry.

### Anthropic

Generate remote MCP connector descriptors, desktop MCPB package metadata, MCP Apps resources where supported, and directory review assets. Tools include titles, annotations, clear descriptions, privacy policy links, support contacts, and test instructions.

### Microsoft Copilot

Generate OpenAPI specs and plugin/declarative-agent manifests. Where Microsoft supports MCP actions, generate MCP descriptors too. Canonical side-effect metadata maps to confirmation behavior such as consequential-operation metadata and confirmation copy.

### Gemini / Direct API Tools

Generate function declarations from canonical schemas. Gemini-style adapters prioritize strict input/output schemas, confirmation tokens, structured responses, and hosted web links for previews and labels because it is less aligned with shared embedded app UI.

### Generic MCP

Expose a plain MCP server for compliant clients. If the client supports MCP Apps, attach UI resources. If not, return concise text and structured content.

## Shared UI Layer

Build one hosted widget/UI layer for provider app-store surfaces.

Widgets cover:

- order import/upload status
- batch preview
- address correction choices
- rate comparison table
- final purchase confirmation
- pickup scheduling form
- tracking cards
- label download/print links
- audit summary

The widget layer should be implemented as small embeddable MCP Apps/OpenAI-compatible resources. It receives `structuredContent` from canonical tools and can call follow-up tools through the host where supported.

Fallback behavior:

- rich UI client: render embedded widget
- MCP client without UI: return structured content plus concise text
- Gemini/direct function calling: return structured content plus hosted preview/confirmation URL
- Microsoft OpenAPI: use confirmation prompts and hosted preview links where native embedded UI is not enough

The current Angular/Tauri desktop UI remains useful, but it is not the provider-app UI. It can consume the same hosted APIs and registry metadata later.

## Migration Plan

This should be a phased refactor, not a rewrite.

### Phase 1: Architecture Contract

Update project guidance and architecture docs:

- replace Claude-first backbone language with provider-neutral workflow/tool layer language
- document provider adapters as runtime/distribution surfaces
- document UPS MCP as an internal carrier dependency

### Phase 2: Canonical Registry

Add registry files for the public hosted catalog and private/internal catalog. Include enough metadata to generate MCP descriptors, OpenAPI specs, function declarations, manifests, docs, and test fixtures.

### Phase 3: Workflow Services

Extract business logic currently embedded in Claude-agent tools and route handlers into provider-neutral services. Existing FastAPI routes, Claude tools, CLI, and desktop UI should call those services.

### Phase 4: UPS MCP Internal Wrapper

Formalize a ShipAgent carrier gateway around the external UPS MCP dependency. Normalize UPS results/errors into canonical ShipAgent result models. Keep raw UPS primitives private unless explicitly enabled for trusted deployments.

### Phase 5: Provider Generators

Generate:

- OpenAI Apps SDK MCP descriptors/resources
- Anthropic remote MCP/MCPB/MCP Apps artifacts
- Microsoft OpenAPI and plugin/declarative-agent manifests
- Gemini function declarations
- generic MCP descriptors
- submission checklists and docs snippets

### Phase 6: Hosted Auth And Storage

Add tenant-aware OAuth/account linking, credential storage, upload ingestion, label storage, signed links, and ownership checks.

### Phase 7: Shared Widgets

Build embeddable widgets for preview, confirmation, rates, tracking, pickup, and labels.

### Phase 8: Desktop Compatibility

Keep Tauri/local mode functional by routing it through the same workflow services and registry. Preserve local filesystem, keyring, watch folder, and printer capabilities as desktop/private features.

## Testing And Readiness

Core tests:

- canonical registry validates
- every public tool has title, description, input/output schemas, side-effect class, auth scopes, confirmation policy, audit policy, and provider export rules
- every side-effecting tool has preview/confirmation coverage
- workflow services run without provider runtime dependencies
- UPS MCP adapter contract tests normalize carrier calls and errors
- tenant isolation covers jobs, files, credentials, labels, and audit records

Generated artifact tests:

- OpenAI Apps SDK descriptors and UI resources validate
- Anthropic remote MCP/MCPB manifests validate
- Microsoft OpenAPI and plugin/declarative-agent manifests validate
- Gemini function declarations validate
- generic MCP server lists expected tools and annotations
- provider package snapshots catch metadata drift

End-to-end readiness tests:

- hosted OAuth account linking
- file upload/import
- preview to confirm to create-label flow
- label download through expiring links
- tracking write-back to a connected store
- fallback behavior for no-UI clients
- security/privacy docs and review assets generated from registry metadata

## Non-Goals

- Do not make the desktop app required for normal hosted app-store usage.
- Do not expose raw UPS MCP primitives directly in public marketplace apps by default.
- Do not build separate provider-specific products with duplicated shipping logic.
- Do not force all providers into identical UI behavior; use shared widgets where possible and structured fallback where needed.
- Do not hide Claude as an internal required orchestrator for OpenAI/Gemini/Microsoft surfaces.

## Success Criteria

The design is successful when:

- a single registry entry can generate provider outputs for OpenAI, Anthropic, Microsoft, Gemini, and generic MCP
- public app-store users can complete core shipping workflows without desktop installation
- desktop/local mode keeps local OS-only capabilities without forking core logic
- provider adapters contain no shipping business logic
- side-effecting tools have uniform confirmation and audit semantics
- UPS MCP remains reusable internally while ShipAgent presents canonical workflow tools externally
- generated artifacts are testable before submission to any provider ecosystem

