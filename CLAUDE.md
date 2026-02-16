# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Vision

**ShipAgent** is an AI-native shipping automation platform. The goal is to build the most robust shipping agent ever — a system where a conversational AI agent is the **sole orchestrator** of all operations, with MCP servers as the connectivity layer and deterministic tools as the execution layer.

**The Claude Agent SDK is the backbone of the entire system.** The `OrchestrationAgent` is not a feature — it is the operating model. Every user interaction is an agent-driven conversation. Every capability is an agent tool. Every external system is accessed through MCP. There is no "dumb API" path, no standalone service logic, no orchestration outside the agent loop. If the agent can't do it, it doesn't belong in the system.

### Development Philosophy

**Agent-First Architecture:** The `OrchestrationAgent` (Claude Agent SDK) is the brain and the backbone. All new features MUST integrate through the agent's tool system. Never build standalone API endpoints that bypass the agent loop. The agent decides what to do; tools execute deterministically. The SDK manages conversation state, tool dispatch, MCP server lifecycles, and streaming — do not reimplement any of these concerns outside the SDK.

**MCP as Connectivity Layer:** External systems (UPS APIs, data sources, e-commerce platforms) are accessed exclusively through MCP servers over stdio transport. MCP provides a universal protocol for the agent to discover and invoke capabilities. New integrations MUST be built as MCP servers or MCP clients, never as direct SDK imports.

**Deterministic Tool Execution:** The LLM acts as a *Configuration Engine*, not a *Data Pipe*. It interprets user intent and generates transformation rules (SQL filters, column mappings, service selections), but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly. Tools validate inputs, enforce business rules, and produce auditable results.

**Canonical Data Models:** All integration constants, defaults, and domain enums live in dedicated canonical modules — never scattered as magic numbers across the codebase. When adding a new carrier, platform, or data source, define its constants in a single canonical module and import everywhere. This makes the system maintainable, testable, and auditable. See [Canonical Data Models](#canonical-data-models) for the current inventory.

**No Work Outside the Agentic Process:** Every capability — data import, filtering, preview, execution, tracking, label recovery — is an agent tool. If it can't be expressed as a tool the agent calls, it doesn't belong in the system. This discipline ensures the agent remains the single source of truth for all operations.

### Agent Design Invariants

These rules are non-negotiable. Violating them creates architectural debt that undermines the agent:

1. **No business logic in API routes.** Routes are thin HTTP adapters. They create sessions, forward messages, and stream events. All decision-making happens inside the agent loop or deterministic tools.
2. **No direct UPS calls outside MCP.** All UPS operations — interactive and batch — go through MCP servers (stdio transport). Never import UPS libraries directly. The `UPSService` class was deleted for this reason.
3. **No LLM calls outside the agent.** The `OrchestrationAgent` is the sole consumer of the Anthropic API. Services, tools, and routes never call the LLM directly. If something needs LLM reasoning, it must be the agent's job.
4. **No tool that skips the approval gate.** Every path that creates shipments or spends money must route through a preview step with mandatory user confirmation. The agent NEVER auto-executes.
5. **No global mutable state for MCP clients.** All MCP client lifecycles are managed through `gateway_provider.py` singletons with proper async locking. Never create ad-hoc MCP connections.
6. **No mode leakage.** Batch tools are hidden from the interactive agent; interactive tools are hidden from the batch agent. Mode enforcement is structural (tool registry filtering) + behavioral (hooks that deny cross-mode calls).
7. **No row data through the LLM.** The agent generates transformation rules (SQL filters, service selections, column mappings). Deterministic tools apply those rules to actual data. The LLM never sees or processes individual shipment rows.
8. **No scattered data definitions.** All carrier constants, service codes, packaging types, field limits, and integration defaults MUST live in their canonical module (`ups_constants.py`, `ups_service_codes.py`, etc.). Never hardcode magic numbers, default values, or enum definitions in tools, routes, or payload builders. Import from the canonical source — one definition, many consumers.

## Project Status

**Current Phase:** 7 - Web Interface (core chat UI operational, interactive shipping mode complete)
**Phases 1-6:** COMPLETE (State DB, Data Source MCP, Error Handling, NL Engine, Agent Integration, Batch Execution)
**SDK Orchestration Redesign:** COMPLETE — Claude SDK is the sole orchestration path via `/api/v1/conversations/` endpoints
**Interactive Shipping:** COMPLETE — ad-hoc single-shipment creation with preview gate and auto-populated shipper config
**International Shipping:** COMPLETE — US→CA/MX lane validation, commodity handling, customs forms, batch + interactive integration. Gated by `INTERNATIONAL_ENABLED_LANES` env var.
**Test Count:** 1320 test functions across 77 test files
**UPS MCP v2 Integration:** COMPLETE — 18 UPS tools (7 original + 11 new) across 6 domains. Agent uses ups-mcp as stdio MCP server with v2 tools available in both batch and interactive modes; BatchEngine uses UPSMCPClient (programmatic MCP over stdio). New tools: pickup (6), paperless (3), locator (1), landed cost (1). Frontend: domain-colored cards (pickup/purple, locator/teal, paperless/amber, landed-cost/indigo, tracking/blue).

## Architecture

### Core Principle: Agent → Tools → MCP → Services

The architecture follows a strict hierarchy:

1. **Agent (OrchestrationAgent)** — The brain. Interprets user intent, plans operations, calls tools.
2. **Tools (orchestrator/agent/tools/)** — Deterministic handlers. Execute specific operations, emit events, enforce business rules.
3. **MCP Servers** — Connectivity. Abstract external systems behind a uniform protocol.
4. **Services** — Business logic. State management, payload building, batch processing.

Nothing bypasses this chain. The frontend talks to the agent through SSE conversations. The agent talks to the world through tools and MCP.

```
User → Browser UI (React) → FastAPI REST API → Conversation SSE Route
                                                       ↓
                                              AgentSessionManager
                                                       ↓
                                              OrchestrationAgent (Claude SDK)
                                               ↓              ↓
                                    Orchestrator Tools    UPS MCP (stdio)
                                         ↓
                              ┌──────────┼──────────┐
                              ↓          ↓          ↓
                    DataSourceMCPClient  BatchEngine  ExternalSourcesMCPClient
                    (MCP stdio)         (UPSMCPClient) (MCP stdio)
                              ↓          ↓          ↓
                         Data Source   UPS MCP    External Sources
                         MCP Server   Server     MCP Server
```

### System Components

| Component | Technology | Role in Agent Architecture |
|-----------|------------|---------------------------|
| **OrchestrationAgent** | Claude Agent SDK | Primary orchestrator — interprets intent, coordinates all operations via deterministic tools |
| **Agent Tools** | Python (9 modules) | Deterministic execution layer — data ops, pipeline ops, interactive ops, pickup, locator, paperless, landed cost, tracking |
| **Agent Hooks** | Pre/PostToolUse | Validation + audit — enforce business rules before/after tool execution |
| **Agent Session Manager** | Python | Per-conversation lifecycle — session isolation, agent persistence, prewarm |
| **Data Source MCP** | FastMCP + DuckDB (stdio) | Data connectivity — CSV, Excel, DB, EDI abstracted behind SQL interface |
| **UPS MCP** | `ups-mcp` local fork (stdio) | Carrier connectivity — 18 UPS tools across 6 domains (shipping, rating, tracking, pickup, locator, paperless, landed cost) |
| **UPS MCP Client** | MCPClient (stdio) | Programmatic batch connectivity — deterministic UPS calls for high-volume execution |
| **External Sources MCP** | FastMCP (stdio) | Platform connectivity — Shopify, WooCommerce, SAP, Oracle |
| **Batch Engine** | Python | Batch execution — concurrent preview/execute with per-row state tracking |
| **Gateway Provider** | Python singletons | MCP lifecycle — process-global singleton factory for all MCP clients |
| **State Database** | SQLite + SQLAlchemy | Persistence — jobs, rows, audit logs, saved sources |
| **FastAPI Backend** | Python + FastAPI | HTTP layer — REST API, SSE streaming, SPA serving |
| **Browser UI** | React + Vite + TypeScript | Presentation — agent-driven chat, preview cards, progress, labels |

### Agent Tool Architecture

The agent's tools are split into 9 modules by concern:

| Module | File | Tools | Purpose |
|--------|------|-------|---------|
| **Core** | `tools/core.py` | `EventEmitterBridge`, helpers | Shared infrastructure — event emission, row caching, bridge binding |
| **Data** | `tools/data.py` | `get_source_info`, `get_schema`, `fetch_rows`, `validate_filter_syntax`, `connect_shopify`, `get_platform_status` | Data source operations — querying, filtering, platform integration |
| **Pipeline** | `tools/pipeline.py` | `ship_command_pipeline`, `create_job`, `add_rows_to_job`, `batch_preview`, `batch_execute`, `get_job_status` | Batch shipping workflow — the core pipeline from command to labels |
| **Interactive** | `tools/interactive.py` | `preview_interactive_shipment` | Ad-hoc single-shipment creation (interactive mode only) |
| **Pickup** | `tools/pickup.py` | `schedule_pickup_tool`, `cancel_pickup_tool`, `rate_pickup_tool`, `get_pickup_status_tool`, `get_political_divisions_tool`, `get_service_center_facilities_tool` | UPS pickup operations — schedule, cancel, rate, status, reference lookups |
| **Locator** | `tools/locator.py` | `find_locations_tool` | UPS location search — Access Points, retail stores, service centers |
| **Paperless** | `tools/paperless.py` | `upload_document_tool`, `push_document_tool`, `delete_document_tool` | Paperless customs — upload, attach, delete trade documents |
| **Landed Cost** | `tools/landed_cost.py` | `get_landed_cost_tool` | International landed cost — duties, taxes, fees estimation |
| **Tracking** | `tools/tracking.py` | `track_package_tool` | UPS tracking — track package with mismatch detection |

Tool registration: `get_all_tool_definitions()` in `tools/__init__.py` assembles all definitions. In interactive mode, only status tools + `preview_interactive_shipment` are exposed; batch/data/v2 tools are hidden. V2 tools (pickup, locator, paperless, landed cost, tracking) are available in both batch and interactive modes via the orchestrator registry and MCP auto-discovery.

### Agent Hook System

Pre/PostToolUse hooks enforce business rules without modifying the agent flow:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `create_shipping_hook()` | `mcp__ups__create_shipment` | Mode-aware enforcement — blocks direct shipment creation in BOTH modes (batch must use pipeline; interactive must use preview tool) |
| `validate_void_shipment` | `mcp__ups__void_shipment` | Requires tracking number or shipment ID |
| `schedule_pickup_hook()` | `mcp__ups__schedule_pickup` | Safety gate — pickup is a financial commitment, requires confirmation context |
| `cancel_pickup_hook()` | `mcp__ups__cancel_pickup` | Safety gate — pickup cancellation is irreversible |
| `validate_track_package` | `mcp__ups__track_package` | Forces orchestrator wrapper for tracking event emission |
| `validate_pre_tool` | All tools (fallback) | Routes to specific validators by tool name |
| `log_post_tool` | All tools (post) | Audit logging to stderr |
| `detect_error_response` | All tools (post) | Error detection and warning |

### Agent Intelligence Architecture

The agent's reasoning comes from its dynamically constructed system prompt (`system_prompt.py`), assembled per-message by `build_system_prompt()`. The prompt includes: identity, service code table (from canonical `ServiceCode` enum), live data source schema, mode-aware filter rules, workflow instructions, and safety rules. The entire prompt changes based on the `interactive_shipping` flag — batch mode includes SQL filter rules; interactive mode suppresses schema and uses conversational collection.

**Self-Correction:** Jinja2 mapping failures trigger up to 3 correction attempts (`CorrectionResult` in `correction.py`). After exhaustion, user gets options: fix source data, manual template fix, skip rows, or abort.

### Data Flow

`POST /conversations/` → `POST /conversations/{id}/messages` → `OrchestrationAgent.process_message_stream()` → SSE events (deltas, tool calls) → `PreviewCard` → **mandatory user confirmation** → `confirmJob()` → `BatchEngine` execution → `CompletionArtifact` with labels → write-back tracking numbers. Fast path: `ship_command_pipeline` handles the entire flow in one tool call.

### Dual Shipping Modes

| Mode | Toggle | Agent Behavior | Tools Available |
|------|--------|---------------|-----------------|
| **Batch** (default) | Off | Data-source-driven — filter rows, preview costs, execute batch | All tools (data, pipeline, status) |
| **Interactive** | On | Conversational — collect recipient details, preview single shipment | `preview_interactive_shipment`, `get_job_status`, `get_platform_status` only |

Mode switching resets the conversation session (deletes old session, creates new one with opposite flag).

### Agent Safety Model

Three layers: **Structural** (tool registry filtering hides tools by mode; session isolation; gateway singletons), **Behavioral** (hooks: `create_shipping_hook()` denies direct `create_shipment` in both modes; `validate_void_shipment` requires tracking number; `detect_error_response` + `log_post_tool` for audit), **Procedural** (mandatory preview before execution; `confirmJob()` is the only execution path; ambiguous commands trigger clarification; E-XXXX error codes).

### Canonical Data Models

All integration constants, enums, and defaults are centralized in dedicated modules. This is a hard architectural rule — no magic numbers or scattered definitions anywhere in the codebase.

| Module | Location | What It Owns |
|--------|----------|-------------|
| **UPS Constants** | `src/services/ups_constants.py` | Field limits, packaging codes (`PackagingCode` enum + 34 aliases), default weights/dimensions, label specs, unit conversions, international form defaults, supported shipping lanes |
| **UPS Service Codes** | `src/services/ups_service_codes.py` | `ServiceCode` enum (12 values), `SERVICE_ALIASES` (40+ human-readable names), domestic/international service sets, resolver functions (`resolve_service_code()`, `translate_service_name()`) |
| **International Rules** | `src/services/international_rules.py` | Lane-driven compliance engine — `RequirementSet` per lane (US-CA, US-MX), customs/commodity validation, service compatibility checks |
| **Orchestrator Models** | `src/orchestrator/models/` | `ShippingIntent`, `FilterCriteria`, `FieldMapping`, `MappingTemplate`, `SQLFilterResult`, `CorrectionResult` — all Pydantic models for agent reasoning |
| **External Order Schema** | `src/mcp/external_sources/models.py` | `ExternalOrder` (normalized across Shopify/WooCommerce/SAP/Oracle), `PlatformType`, `ConnectionStatus` |
| **Data Source Schema** | `src/mcp/data_source/models.py` | `SchemaColumn`, `ImportResult`, `RowData` — discovered (not hardcoded) per-source metadata |

**Pattern for new integrations:** When adding a new carrier (e.g., FedEx), create `src/services/fedex_constants.py` and `src/services/fedex_service_codes.py` following the UPS pattern. All consumers import from the canonical module. The agent's system prompt dynamically generates service catalogs from these modules — never from hardcoded strings in prompts.

### MCP Gateway Architecture

Two distinct MCP paths — **Agent MCP** (interactive, SDK-managed) and **Programmatic MCP** (batch + data, gateway-managed via `gateway_provider.py` singletons):

| MCP Server | Spawned By | Lifecycle | Path |
|------------|------------|-----------|------|
| **UPS MCP** (agent) | `OrchestrationAgent` (SDK) | Per agent session | Interactive — agent calls tools directly |
| **UPS MCP** (batch) | `UPSMCPClient` context manager | Per batch job | Batch — `BatchEngine` uses programmatic client |
| **Data Source MCP** | `DataSourceMCPClient` singleton | Process-global, lazy init | Agent tools call `get_data_gateway()` |
| **External Sources MCP** | `ExternalSourcesMCPClient` singleton | Process-global, lazy init | Agent tools call `get_external_sources_client()` |

All clients inherit from `MCPClient` (base) with retry + exponential backoff. Gateway singletons use double-checked locking with `asyncio.Lock`, disconnected via `shutdown_gateways()` in `src/api/main.py`.

**UPS retry strategy (batch):** Non-mutating ops: 2 retries, 0.2s exponential backoff. Mutating ops: 0 retries (prevent duplicates). Transport failures: reconnect + 1 replay (non-mutating only).

## Source Structure

```
src/
├── api/                        # FastAPI REST API (HTTP layer only — no business logic)
│   ├── routes/                 # Endpoint modules
│   │   ├── conversations.py    # Agent-driven SSE conversation (PRIMARY — all user interaction flows here)
│   │   ├── data_sources.py     # Local data source import/upload/disconnect/schema
│   │   ├── jobs.py             # Job CRUD + status + rows + summary
│   │   ├── preview.py          # Batch preview + confirm (triggers BatchEngine execution)
│   │   ├── progress.py         # Real-time SSE streaming + progress polling
│   │   ├── labels.py           # Label download (individual, merged PDF, ZIP)
│   │   ├── logs.py             # Audit log endpoints (list, errors, export)
│   │   ├── platforms.py        # Shopify, SAP, Oracle, WooCommerce
│   │   └── saved_data_sources.py # Saved source CRUD + reconnect
│   ├── main.py                 # App factory with lifespan events + SPA serving
│   ├── schemas.py              # Pydantic request/response models
│   └── schemas_conversations.py # Conversation endpoint schemas
├── db/                         # Database layer
│   ├── models.py               # SQLAlchemy models (Job, JobRow, AuditLog, SavedDataSource)
│   └── connection.py           # Session management
├── errors/                     # Error handling
│   ├── registry.py             # E-XXXX error code registry
│   ├── ups_translation.py      # UPS error → ShipAgent error mapping
│   └── formatter.py            # Error message formatting
├── services/                   # Business logic (core services — called by agent tools)
│   ├── ups_constants.py        # ⭐ CANONICAL — UPS field limits, packaging codes, defaults, units
│   ├── ups_service_codes.py    # ⭐ CANONICAL — ServiceCode enum, aliases, resolvers
│   ├── international_rules.py  # ⭐ CANONICAL — Lane-driven compliance (customs, commodities)
│   ├── errors.py               # Shared error types (UPSServiceError)
│   ├── mcp_client.py           # Generic async MCP client with retry + exponential backoff
│   ├── ups_mcp_client.py       # UPSMCPClient — async UPS via MCP stdio (batch path)
│   ├── ups_specs.py            # UPS MCP OpenAPI spec path helpers
│   ├── batch_engine.py         # BatchEngine — unified preview + execution with concurrency
│   ├── column_mapping.py       # ColumnMappingService — source → UPS field mapping
│   ├── ups_payload_builder.py  # Builds UPS API payloads from canonical constants + mapped data
│   ├── agent_session_manager.py # Per-conversation agent session lifecycle
│   ├── job_service.py          # Job state machine, row tracking
│   ├── audit_service.py        # Audit logging with redaction
│   ├── data_source_service.py  # Data source import + auto-save hooks (legacy — prefer MCP gateway)
│   ├── data_source_gateway.py  # DataSourceGateway protocol + typed adapter
│   ├── data_source_mcp_client.py # DataSourceMCPClient — async data source via MCP stdio
│   ├── external_sources_mcp_client.py # ExternalSourcesMCPClient — async platform via MCP stdio
│   ├── gateway_provider.py     # Centralized singleton factory for MCP client gateways
│   ├── saved_data_source_service.py # Saved source CRUD (list, upsert, delete, reconnect)
│   └── write_back_utils.py     # Atomic CSV/Excel write-back utilities
├── mcp/
│   ├── data_source/            # Data Source MCP server (DuckDB-backed SQL interface)
│   │   ├── server.py           # FastMCP server with stdio transport
│   │   ├── models.py           # Canonical: SchemaColumn, ImportResult, RowData
│   │   ├── adapters/           # Pluggable: base.py, csv, excel, db, edi adapters
│   │   ├── tools/              # import, schema, query, checksum, commodity, writeback, edi tools
│   │   └── edi/                # X12 + EDIFACT parsers
│   └── external_sources/       # External platform MCP
│       ├── server.py, tools.py # Platform MCP server + tools
│       ├── models.py           # Canonical: ExternalOrder, PlatformType, ConnectionStatus
│       └── clients/            # Shopify, WooCommerce, SAP, Oracle adapters
└── orchestrator/               # Orchestration layer (AGENT IS PRIMARY)
    ├── filters/                # Jinja2 logistics filter library
    │   └── logistics.py        # truncate_address, format_us_zip, convert_weight, etc.
    ├── models/                 # Data models
    │   ├── intent.py           # ServiceCode enum + SERVICE_ALIASES mapping
    │   ├── filter.py           # NL filter models
    │   ├── mapping.py          # Column mapping models
    │   ├── elicitation.py      # Elicitation models
    │   └── correction.py       # Self-correction loop tracking (max 3 attempts)
    ├── agent/                  # Claude Agent SDK integration (PRIMARY ORCHESTRATION PATH)
    │   ├── client.py           # OrchestrationAgent — SDK agent with streaming + MCP coordination
    │   ├── system_prompt.py    # Dynamic system prompt builder (domain knowledge + data schema)
    │   ├── tools/              # Deterministic SDK tools (split by concern — 9 modules)
    │   │   ├── __init__.py     # Tool registry — get_all_tool_definitions()
    │   │   ├── core.py         # EventEmitterBridge, row cache, bridge binding helpers
    │   │   ├── data.py         # Data source + platform tool handlers
    │   │   ├── pipeline.py     # Batch pipeline tool handlers (ship_command_pipeline fast path)
    │   │   ├── interactive.py  # Interactive shipment tool handler (preview_interactive_shipment)
    │   │   ├── pickup.py       # UPS pickup operations (schedule, cancel, rate, status, divisions, facilities)
    │   │   ├── locator.py      # UPS location search (find_locations_tool)
    │   │   ├── paperless.py    # Paperless customs (upload, push, delete document tools)
    │   │   ├── landed_cost.py  # Landed cost estimation (get_landed_cost_tool)
    │   │   └── tracking.py     # UPS package tracking (track_package_tool)
    │   ├── config.py           # MCP server configuration factory (Data, External, UPS)
    │   └── hooks.py            # Pre/PostToolUse validation hooks (mode enforcement, audit)
    └── batch/                  # Batch orchestration
        ├── events.py           # BatchEventObserver protocol
        ├── models.py           # Batch state models
        ├── modes.py            # Preview/execute modes
        ├── recovery.py         # Crash recovery logic
        └── sse_observer.py     # SSE streaming observer

frontend/src/
├── App.tsx, main.tsx, index.css    # Entry point + design system (OKLCH, DM Sans, Instrument Serif)
├── components/
│   ├── CommandCenter.tsx           # Main chat UI — SSE event orchestration, preview/progress/completion
│   ├── command-center/             # PreviewCard, ProgressDisplay, CompletionArtifact, ToolCallChip, messages, PickupCard, LocationCard, LandedCostCard, PaperlessCard, TrackingCard
│   ├── sidebar/                    # DataSourcePanel, JobHistoryPanel
│   ├── ui/                         # shadcn/ui primitives + icons.tsx + brand-icons.tsx
│   └── layout/                     # Sidebar, Header (with interactive shipping toggle)
├── hooks/
│   ├── useAppState.tsx             # Global state context (conversation, jobs, data source, mode)
│   ├── useConversation.ts          # Agent SSE lifecycle (session + events + mode switching)
│   └── useJobProgress.ts, useSSE.ts, useExternalSources.ts
├── lib/api.ts                      # REST client (all /api/v1 endpoints)
└── types/api.ts                    # TypeScript types mirroring Pydantic schemas
```

## Key Services

### OrchestrationAgent (`src/orchestrator/agent/client.py`)

**The system backbone.** The `OrchestrationAgent` is not a component of the system — it IS the system. The Claude Agent SDK manages the entire operational lifecycle: conversation state, tool dispatch, MCP server processes, validation hooks, streaming output, and error recovery. Every user interaction, every shipping operation, every data query flows through the SDK agent loop. Nothing orchestrates outside it.

Key features:
- `process_message_stream()` — yields SSE-compatible event dicts (agent_message_delta, tool_call, error)
- `StreamEvent` support — real-time token-by-token streaming when SDK supports it
- `interrupt()` — graceful cancellation of in-progress responses
- MCP servers: `orchestrator` (in-process tools) + `ups` (stdio child process)
- Default model: `AGENT_MODEL` env → `ANTHROPIC_MODEL` env → Claude Haiku 4.5
- Hooks: `create_hook_matchers()` — PreToolUse/PostToolUse validation and audit (see [SDK #265 workaround](#known-issues))

### UPS MCP Server (local fork: `matt-hans/ups-mcp`)

Stdio child process (`.venv/bin/python3 -m ups_mcp`), editable install from pinned commit. 18 tools across 6 domains:
- **Shipping**: `rate_shipment`, `create_shipment`, `void_shipment`, `recover_label`
- **Address/Transit**: `validate_address`, `track_package`, `get_time_in_transit`
- **Landed Cost**: `get_landed_cost_quote`
- **Paperless**: `upload_paperless_document`, `push_document_to_shipment`, `delete_paperless_document`
- **Locator**: `find_locations`
- **Pickup**: `rate_pickup`, `schedule_pickup`, `cancel_pickup`, `get_pickup_status`, `get_political_divisions`, `get_service_center_facilities`

**Tool availability:** V2 tools (pickup, locator, paperless, landed cost, tracking) are registered in the orchestrator and available in both batch and interactive modes via MCP auto-discovery and the tool registry.

### BatchEngine (`src/services/batch_engine.py`)

Unified preview + execution with concurrent `asyncio.gather` + semaphore (`BATCH_CONCURRENCY` env, default 5). Per-row state writes for crash recovery. SSE events for real-time progress. Integrated write-back to CSV/Excel sources and external platforms for tracking number persistence.

### AgentSessionManager (`src/services/agent_session_manager.py`)

Per-conversation agent sessions. Each gets isolated history, persistent `OrchestrationAgent`, `agent_source_hash` for change detection (agent rebuilt on source/mode change), `asyncio.Lock` for serialization, optional prewarm.

### UPSPayloadBuilder (`src/services/ups_payload_builder.py`)

Builds UPS API payloads from column-mapped data + canonical constants (`ups_constants.py`). All field limits, defaults, packaging codes, and label specs are imported — never inline. See [UPS API Lessons](#ups-api-lessons) for hard-won fixes.

## Frontend Architecture

The UI is an agent-driven chat interface. `useConversation` hook manages session lifecycle and SSE event streaming. `useAppState` context holds conversation, jobs, data source, and mode state (`interactiveShipping` persisted to localStorage).

**Chat flow**: User types command → SSE events stream (deltas, tool calls) → PreviewCard renders with Confirm/Cancel/Refine → ProgressDisplay streams per-row execution → CompletionArtifact card with label access → input re-enables for next command.

**Key patterns**: `ConversationMessage.action` routes to renderers (`preview`, `execute`, `complete`, `error`). `jobListVersion` counter triggers sidebar refresh. `isToggleLocked` prevents mode toggle during processing.

## API Endpoints

All endpoints use `/api/v1/` prefix. See route files in `src/api/routes/` for full details.

**Primary agent path** (conversations.py): `POST /conversations/` (create session) → `POST /conversations/{id}/messages` (send to agent) → `GET /conversations/{id}/stream` (SSE events) → `DELETE /conversations/{id}` (cleanup)

**Jobs** (jobs.py): CRUD on `/jobs/`, status via `PATCH /jobs/{id}/status`, preview via `GET /jobs/{id}/preview`, confirm via `POST /jobs/{id}/confirm`, SSE progress via `GET /jobs/{id}/progress/stream`

**Labels** (labels.py): Individual `GET /labels/{tracking}`, merged PDF `GET /jobs/{id}/labels/merged`, ZIP `GET /jobs/{id}/labels/zip`

**Data Sources** (data_sources.py): `POST /data-sources/import`, `POST /data-sources/upload`, `GET /data-sources/status`, `POST /data-sources/disconnect`

**Saved Sources** (saved_data_sources.py): `GET /saved-sources`, `POST /saved-sources/reconnect`, `DELETE /saved-sources/{id}`, `POST /saved-sources/bulk-delete`

**Platforms** (platforms.py): `POST /platforms/{platform}/connect`, `GET /platforms/shopify/env-status` (auto-reconnect after restart), `GET /platforms/{platform}/orders`

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, SQLite |
| Agent Framework | Claude Agent SDK (`claude-agent-sdk>=0.1.22`), Anthropic API |
| MCP Protocol | FastMCP v2 (servers), `mcp` (stdio clients) |
| Data Processing | DuckDB (in-memory analytics), openpyxl (Excel) |
| UPS Integration | `ups-mcp` local fork (pinned commit, editable install via pip) |
| NL Processing | sqlglot (SQL generation/validation), Jinja2 (logistics filters) |
| Real-time | SSE via `sse-starlette` |
| PDF | `pypdf` (merging), `react-pdf` + `pdfjs-dist` (browser rendering) |
| Frontend | React, Vite, TypeScript, Tailwind CSS v4, shadcn/ui |

## Common Commands

### Backend

```bash
# Start backend with all env vars (Shopify, Anthropic, UPS)
./scripts/start-backend.sh

# Or manually:
set -a && source .env && set +a && uvicorn src.api.main:app --reload --port 8000

# After backend restart, reconnect Shopify:
curl http://localhost:8000/api/v1/platforms/shopify/env-status
```

### Tests

```bash
# Run all tests
pytest

# Skip known hanging tests
pytest -k "not test_stream_endpoint_exists"

# Avoid tests that may hang (SSE/streaming)
pytest -k "not stream and not sse and not progress"

# Run specific test file
pytest tests/services/test_ups_payload_builder.py -v

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Type checking
mypy src/

# Linting
ruff check src/ tests/
ruff format src/ tests/
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # Development server (port 5173)
npm run build        # Production build
npx tsc --noEmit     # Type check
```

### Agent Testing

```bash
pytest tests/orchestrator/agent/ -v        # Agent tools + hooks + system prompt
pytest tests/services/test_batch_engine.py -v  # Batch preview + execution
pytest tests/services/test_ups_mcp_client.py -v  # UPS MCP client
pytest tests/services/test_ups_payload_builder.py -v  # Payload builder + constants
```

## Key Conventions

### Error Codes

Format: `E-XXXX` with category prefixes:
- `E-1xxx`: Data errors
- `E-2xxx`: Validation errors (includes E-2020–E-2025 for MCP elicitation errors)
- `E-3xxx`: UPS API errors (includes E-3006–E-3009 for paperless/pickup/locator errors)
- `E-4xxx`: System errors (includes E-4001–E-4002, E-4011–E-4012 for user cancellation and safety gates)
- `E-5xxx`: Authentication errors

### Currency

All costs stored as **integers in cents** to avoid floating-point precision issues.

### Timestamps

All timestamps stored as **ISO8601 strings** for SQLite compatibility.

### API Versioning

All REST endpoints use `/api/v1/` prefix.

### Enums

All enums inherit from both `str` and `Enum` for JSON serialization.

### Frontend Patterns

- Design system in `index.css`: OKLCH colors, DM Sans / Instrument Serif / JetBrains Mono typography
- CSS classes: `card-premium`, `btn-primary`, `btn-secondary`, `badge-*`, `card-domain-*`
- Domain colors (OKLCH): shipping/green(145), pickup/purple(300), locator/teal(185), paperless/amber(85), landed-cost/indigo(265), tracking/blue(230)
- Icons: `ui/icons.tsx` (general), `ui/brand-icons.tsx` (platform logos)
- shadcn/ui primitives in `components/ui/`
- Labels stored on disk, paths in `JobRow.label_path`; `order_data` as JSON text in `JobRow.order_data`

## Known Issues

- SSE/streaming tests may hang — use `pytest -k "not stream and not sse and not progress"`
- After backend restart, Shopify connection lost (in-memory) — call `GET /api/v1/platforms/shopify/env-status`
- EDI adapter test collection errors (10 tests, unrelated to core features)
- **Claude Agent SDK bug [#265](https://github.com/anthropics/claude-agent-sdk-python/issues/265)**: PreToolUse hook denials generate a synthetic "API Error: 400 due to tool use concurrency issues" message. Hooks remain active; the misleading error is suppressed in the chat UI (`CommandCenter.tsx:161`). Remove the filter when the SDK fix ships.

## UPS API Lessons

These are hard-won fixes — do not revert:
- `Packaging` not `PackagingType` for the package type key
- `ShipmentCharge` must be an array `[{...}]`, not a single object
- ReferenceNumber at shipment level is rejected for Ground domestic (omitted entirely)
- Filter evaluator handles compound AND/OR WHERE clauses with parenthesis-depth-aware splitting
- Person name queries generate `customer_name = 'X' OR ship_to_name = 'X'` for disambiguation
- UPS `_translate_error` was swallowing error details — ensure raw_str fallback when ups_message is empty

## Extension Points

All extensions MUST integrate through agent tools/MCP and follow canonical data model patterns:

- **New Carrier**: Create `<carrier>_constants.py` + `<carrier>_service_codes.py` in `src/services/`, build MCP server (stdio), add client wrapper, register tools. Never hardcode constants.
- **New Data Source**: Implement `BaseSourceAdapter` in `src/mcp/data_source/adapters/`. Must produce `ImportResult` with `SchemaColumn`.
- **New Platform**: Add client in `src/mcp/external_sources/clients/`. Must normalize to `ExternalOrder`.
- **New Agent Tool**: Add handler in appropriate tool module, register in `tools/__init__.py`. Import constants from canonical modules.
- **New Batch Capability**: Extend `BatchEngine`, expose via pipeline tool.
- **Filters/Observers**: Register Jinja2 filters in Filter Registry; subscribe to BatchEngine SSE events.

## Roadmap (Agent Capabilities)

- **P0 — International Shipping (CA/MX)**: COMPLETE — lane validation, commodity tools, customs forms, payload builder enrichment, batch + interactive.
- **P1 — Multi-Carrier (FedEx, USPS)**: New MCP servers per carrier, `compare_carriers` tool. Not started.
- **P1 — Address Book**: Persistent profiles, `resolve_address` tool. Not started.
- **P2 — Google Sheets, Webhooks**: New adapters/tools. Not started.
- **P3 — Smart Routing**: Optimal carrier+service recommendation. Requires multi-carrier. Not started.

## Boundaries

Shipping orchestration only — read-only for orders (except tracking write-back), no inventory management, no payment processing, no customer communication, UPS-only (multi-carrier on roadmap).
