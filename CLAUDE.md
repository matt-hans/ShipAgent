# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Vision

**ShipAgent** is an AI-native shipping automation platform. The goal is to build the most robust shipping agent ever — a system where a conversational AI agent is the primary orchestrator of all operations, with MCP servers as the connectivity layer and deterministic tools as the execution layer.

**Everything flows through the agent.** The agent interprets intent, coordinates services, manages workflows, and drives every operation from data import to label generation. There is no "dumb API" path — every user interaction is an agent-driven conversation.

### Development Philosophy

**Agent-First Architecture:** The `OrchestrationAgent` (Claude Agent SDK) is the brain. All new features MUST integrate through the agent's tool system. Never build standalone API endpoints that bypass the agent loop. The agent decides what to do; tools execute deterministically.

**MCP as Connectivity Layer:** External systems (UPS APIs, data sources, e-commerce platforms) are accessed exclusively through MCP servers over stdio transport. MCP provides a universal protocol for the agent to discover and invoke capabilities. New integrations MUST be built as MCP servers or MCP clients, never as direct SDK imports.

**Deterministic Tool Execution:** The LLM acts as a *Configuration Engine*, not a *Data Pipe*. It interprets user intent and generates transformation rules (SQL filters, column mappings, service selections), but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly. Tools validate inputs, enforce business rules, and produce auditable results.

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

## Project Status

**Current Phase:** 7 - Web Interface (core chat UI operational, interactive shipping mode complete)
**Phases 1-6:** COMPLETE (State DB, Data Source MCP, Error Handling, NL Engine, Agent Integration, Batch Execution)
**SDK Orchestration Redesign:** COMPLETE — Claude SDK is the sole orchestration path via `/api/v1/conversations/` endpoints
**Interactive Shipping:** COMPLETE — ad-hoc single-shipment creation with preview gate and auto-populated shipper config
**International Shipping:** IN PLANNING — design document for CA/MX phase exists, implementation pending
**Test Count:** 1013+ test functions across 81 test files
**UPS MCP Hybrid:** COMPLETE — agent uses ups-mcp as stdio MCP server for interactive tools; BatchEngine uses UPSMCPClient (programmatic MCP over stdio) for deterministic batch execution

## Key Capabilities (Implemented)

- Natural language batch + interactive ad-hoc shipment creation
- Data sources: CSV, Excel, PostgreSQL/MySQL, Shopify (env auto-detect)
- UPS: shipping, rating, address validation, tracking, label recovery, time-in-transit (all via MCP)
- Concurrent batch execution with per-row audit, SSE progress, crash recovery
- LLM-generated column mappings + NL filter generation (AND/OR, person name disambiguation)
- Mandatory preview gate with cost estimates; refinement flow without restart
- Write-back tracking numbers to source; saved sources with one-click reconnect
- Continuous chat flow; agent prewarm; dual batch/interactive modes

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
| **Agent Tools** | Python (4 modules) | Deterministic execution layer — data ops, pipeline ops, interactive ops |
| **Agent Hooks** | Pre/PostToolUse | Validation + audit — enforce business rules before/after tool execution |
| **Agent Session Manager** | Python | Per-conversation lifecycle — session isolation, agent persistence, prewarm |
| **Data Source MCP** | FastMCP + DuckDB (stdio) | Data connectivity — CSV, Excel, DB, EDI abstracted behind SQL interface |
| **UPS MCP** | `ups-mcp` local fork (stdio) | Carrier connectivity — 7 UPS tools (ship, rate, track, validate, void, recover, transit) |
| **UPS MCP Client** | MCPClient (stdio) | Programmatic batch connectivity — deterministic UPS calls for high-volume execution |
| **External Sources MCP** | FastMCP (stdio) | Platform connectivity — Shopify, WooCommerce, SAP, Oracle |
| **Batch Engine** | Python | Batch execution — concurrent preview/execute with per-row state tracking |
| **Gateway Provider** | Python singletons | MCP lifecycle — process-global singleton factory for all MCP clients |
| **State Database** | SQLite + SQLAlchemy | Persistence — jobs, rows, audit logs, saved sources |
| **FastAPI Backend** | Python + FastAPI | HTTP layer — REST API, SSE streaming, SPA serving |
| **Browser UI** | React + Vite + TypeScript | Presentation — agent-driven chat, preview cards, progress, labels |

### Agent Tool Architecture

The agent's tools are split into 4 modules by concern:

| Module | File | Tools | Purpose |
|--------|------|-------|---------|
| **Core** | `tools/core.py` | `EventEmitterBridge`, helpers | Shared infrastructure — event emission, row caching, bridge binding |
| **Data** | `tools/data.py` | `get_source_info`, `get_schema`, `fetch_rows`, `validate_filter_syntax`, `connect_shopify`, `get_platform_status` | Data source operations — querying, filtering, platform integration |
| **Pipeline** | `tools/pipeline.py` | `ship_command_pipeline`, `create_job`, `add_rows_to_job`, `batch_preview`, `batch_execute`, `get_job_status` | Batch shipping workflow — the core pipeline from command to labels |
| **Interactive** | `tools/interactive.py` | `preview_interactive_shipment` | Ad-hoc single-shipment creation (interactive mode only) |

Tool registration: `get_all_tool_definitions()` in `tools/__init__.py` assembles all definitions. In interactive mode, only status tools + `preview_interactive_shipment` are exposed; batch/data tools are hidden.

### Agent Hook System

Pre/PostToolUse hooks enforce business rules without modifying the agent flow:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `create_shipping_hook()` | `mcp__ups__create_shipment` | Mode-aware enforcement — blocks direct shipment creation in BOTH modes (batch must use pipeline; interactive must use preview tool) |
| `validate_void_shipment` | `mcp__ups__void_shipment` | Requires tracking number or shipment ID |
| `validate_pre_tool` | All tools (fallback) | Routes to specific validators by tool name |
| `log_post_tool` | All tools (post) | Audit logging to stderr |
| `detect_error_response` | All tools (post) | Error detection and warning |

### Agent Intelligence Architecture

The agent's reasoning ability comes from its dynamically constructed system prompt (`system_prompt.py`). Understanding this is critical — the system prompt IS the agent's domain expertise.

**Prompt Structure** (assembled per-message by `build_system_prompt()`):

| Section | Source | Purpose |
|---------|--------|---------|
| Identity | Static | "You are ShipAgent, an AI shipping assistant..." |
| Service Code Table | `ServiceCode` enum + `SERVICE_ALIASES` | Complete UPS service catalog so agent resolves "Ground" → code `03` |
| Connected Data Source | `DataSourceInfo` (live) | Column names, types, nullability, row count — refreshed every message |
| Filter Generation Rules | Static (mode-aware) | SQL WHERE clause generation: person name disambiguation, status/date/tag/weight handling |
| Workflow | Static (mode-aware) | Step-by-step instructions: fast path (`ship_command_pipeline`) vs fallback path |
| Safety Rules | Static (mode-aware) | Mandatory preview, no auto-execution, error reporting format |
| Tool Usage | Static (mode-aware) | Which tools to prefer, when to use LLM vs deterministic execution |

**Mode Awareness:** The entire prompt changes based on `interactive_shipping` flag:
- **Batch mode**: Full schema, SQL filter rules, batch workflow, data source safety rules
- **Interactive mode**: Schema suppressed, conversational collection flow, ad-hoc preview workflow
- **No source**: Shopify auto-detect (if env configured) or prompt user to connect

**Self-Correction:** When Jinja2 mapping templates fail UPS schema validation, the system tracks correction attempts (max 3 via `CorrectionResult` in `correction.py`). After exhaustion, the user gets options: fix source data, manual template fix, skip failing rows, or abort.

**Key Intelligence Patterns:**
- Person name queries → `customer_name ILIKE '%X%' OR ship_to_name ILIKE '%X%'` (disambiguation)
- Status queries → substring match on composite `status` field OR exact match on `financial_status`/`fulfillment_status`
- Tag queries → `tags LIKE '%VIP%'` (comma-separated field)
- Weight queries → automatic gram conversion (`1 lb = 453.592g`)
- Ambiguous commands → agent asks clarifying questions (never guesses)
- Straightforward commands → single `ship_command_pipeline` call (fast path avoids 5-tool chain)

### Data Flow (Agent-Driven Conversation)

1. **Session**: Frontend creates conversation session via `POST /conversations/` → `AgentSessionManager` allocates session + optional prewarm
2. **Message**: User sends message via `POST /conversations/{id}/messages` → stored in history, triggers background agent processing
3. **Agent Loop**: `OrchestrationAgent.process_message_stream()` runs SDK agent loop — events streamed via SSE queue
4. **Tool Calls**: Agent calls deterministic tools — events appear as `ToolCallChip` components in UI
5. **Fast Path**: For straightforward shipping commands, `ship_command_pipeline` handles fetch → job → rows → preview in one call
6. **Preview**: Preview data sent as SSE `preview_ready` event → `PreviewCard` rendered with Confirm/Cancel/Refine buttons
7. **Approval Gate**: User must confirm preview before execution (mandatory — agent NEVER auto-executes)
8. **Execution**: `confirmJob()` triggers backend batch execution → `ProgressDisplay` streams per-row progress via SSE
9. **Completion**: `CompletionArtifact` card appears in chat with label access, job saved to sidebar history
10. **Write-Back**: Tracking numbers written back to source data, job marked complete
11. **Continue**: User types next command in same session — agent retains conversation context

### Dual Shipping Modes

| Mode | Toggle | Agent Behavior | Tools Available |
|------|--------|---------------|-----------------|
| **Batch** (default) | Off | Data-source-driven — filter rows, preview costs, execute batch | All tools (data, pipeline, status) |
| **Interactive** | On | Conversational — collect recipient details, preview single shipment | `preview_interactive_shipment`, `get_job_status`, `get_platform_status` only |

Mode switching resets the conversation session (deletes old session, creates new one with opposite flag).

### Agent Safety Model

Safety is enforced at three layers — structural, behavioral, and procedural:

**Structural (compile-time):**
- Tool registry filtering: `get_all_tool_definitions(interactive_shipping=True)` returns only 3 tools; batch/data tools physically absent from the agent's toolset
- Session isolation: each conversation gets its own `AgentSession` with independent history and agent instance
- Gateway singletons: MCP client lifecycles managed centrally, not per-request

**Behavioral (runtime hooks):**
- `create_shipping_hook()`: Closure-based mode enforcement — `mcp__ups__create_shipment` is denied in BOTH modes (batch must use pipeline; interactive must use preview tool)
- `validate_void_shipment`: Requires tracking number before allowing void
- `validate_pre_tool`: Routes all tool calls through validation dispatch
- `detect_error_response` + `log_post_tool`: Post-execution audit trail on stderr

**Procedural (agent prompt rules):**
- Mandatory preview before any execution — the agent is instructed to NEVER auto-execute
- Frontend `confirmJob()` is the only path to batch execution — the agent cannot trigger it
- Ambiguous commands trigger clarifying questions, never guesses
- Error responses include E-XXXX codes with suggested remediation

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
│   ├── errors.py               # Shared error types (UPSServiceError)
│   ├── mcp_client.py           # Generic async MCP client with retry + exponential backoff
│   ├── ups_mcp_client.py       # UPSMCPClient — async UPS via MCP stdio (batch path)
│   ├── ups_specs.py            # UPS MCP OpenAPI spec path helpers
│   ├── batch_engine.py         # BatchEngine — unified preview + execution with concurrency
│   ├── column_mapping.py       # ColumnMappingService — source → UPS field mapping
│   ├── ups_payload_builder.py  # Builds UPS API payloads from mapped data
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
│   │   ├── models.py           # Pydantic models (SchemaColumn, ImportResult, RowData)
│   │   ├── utils.py            # Row checksum (SHA-256) + date parsing utilities
│   │   ├── adapters/           # Source adapters (pluggable)
│   │   │   ├── base.py         # BaseSourceAdapter interface
│   │   │   ├── csv_adapter.py  # CSV file adapter
│   │   │   ├── excel_adapter.py # Excel (.xlsx) adapter
│   │   │   ├── db_adapter.py   # PostgreSQL/MySQL database adapter
│   │   │   └── edi_adapter.py  # EDI (X12/EDIFACT) adapter
│   │   ├── tools/              # MCP tool implementations
│   │   │   ├── import_tools.py # Data import tools
│   │   │   ├── schema_tools.py # Schema inspection tools
│   │   │   ├── query_tools.py  # SQL query tools
│   │   │   ├── checksum_tools.py # Row checksum tools
│   │   │   ├── writeback_tools.py # Write-back tools (tracking → source)
│   │   │   ├── source_info_tools.py # Source metadata + record import + clear
│   │   │   └── edi_tools.py    # EDI-specific tools
│   │   └── edi/                # EDI parsing module
│   │       ├── models.py       # EDI data models
│   │       ├── x12_parser.py   # ANSI X12 parser
│   │       └── edifact_parser.py # UN/EDIFACT parser
│   └── external_sources/       # External platform MCP
│       ├── server.py           # External sources MCP server
│       ├── tools.py            # Platform MCP tools
│       ├── models.py           # PlatformType, ConnectionStatus, ExternalOrder models
│       └── clients/            # Shopify, SAP, Oracle, WooCommerce clients
│           ├── base.py         # BasePlatformClient interface
│           ├── shopify.py      # Shopify Admin API client
│           ├── woocommerce.py  # WooCommerce REST API client
│           ├── sap.py          # SAP OData client
│           └── oracle.py       # Oracle Database client
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
    │   ├── tools/              # Deterministic SDK tools (split by concern)
    │   │   ├── __init__.py     # Tool registry — get_all_tool_definitions()
    │   │   ├── core.py         # EventEmitterBridge, row cache, bridge binding helpers
    │   │   ├── data.py         # Data source + platform tool handlers
    │   │   ├── pipeline.py     # Batch pipeline tool handlers (ship_command_pipeline fast path)
    │   │   └── interactive.py  # Interactive shipment tool handler (preview_interactive_shipment)
    │   ├── config.py           # MCP server configuration factory (Data, External, UPS)
    │   └── hooks.py            # Pre/PostToolUse validation hooks (mode enforcement, audit)
    └── batch/                  # Batch orchestration
        ├── events.py           # BatchEventObserver protocol
        ├── models.py           # Batch state models
        ├── modes.py            # Preview/execute modes
        ├── recovery.py         # Crash recovery logic
        └── sse_observer.py     # SSE streaming observer

frontend/
├── src/
│   ├── main.tsx                    # React entry point
│   ├── App.tsx                     # Root component (AppStateProvider + layout)
│   ├── index.css                   # Design system (OKLCH colors, typography, animations)
│   ├── components/
│   │   ├── CommandCenter.tsx       # Main chat UI — agent event orchestration, preview/progress/completion
│   │   ├── command-center/
│   │   │   ├── messages.tsx        # SystemMessage, UserMessage, WelcomeMessage, ActiveSourceBanner, InteractiveModeBanner, SettingsPopover, TypingIndicator
│   │   │   ├── PreviewCard.tsx     # Batch + interactive preview with expandable rows, cost estimates, warnings, refinement
│   │   │   ├── ProgressDisplay.tsx # Live batch execution progress with per-row failure tracking
│   │   │   ├── CompletionArtifact.tsx # Inline card for completed batches (status-colored border, label access)
│   │   │   └── ToolCallChip.tsx    # Collapsible chip showing active agent tool calls
│   │   ├── JobDetailPanel.tsx      # Full job detail view (from sidebar click)
│   │   ├── LabelPreview.tsx        # PDF label viewer modal (react-pdf)
│   │   ├── RecentSourcesModal.tsx  # Saved sources browser (search, filter, reconnect, bulk delete)
│   │   ├── sidebar/
│   │   │   ├── DataSourcePanel.tsx # Data source switching, file upload, DB connection, Shopify
│   │   │   ├── JobHistoryPanel.tsx # Job list with search, filters, delete, printer access
│   │   │   └── dataSourceMappers.ts # Column-to-ColumnMetadata mapping helpers
│   │   ├── ui/                     # shadcn/ui primitives + consolidated icons
│   │   │   ├── ShipAgentLogo.tsx   # Custom logo components
│   │   │   ├── icons.tsx           # Consolidated SVG icon components (25+ icons)
│   │   │   ├── brand-icons.tsx     # Platform brand icons (Shopify, DataSource)
│   │   │   ├── button.tsx, input.tsx, card.tsx, progress.tsx, switch.tsx
│   │   │   ├── dialog.tsx, alert.tsx, scroll-area.tsx
│   │   │   └── ...
│   │   └── layout/
│   │       ├── Sidebar.tsx         # Sidebar shell (collapsible)
│   │       └── Header.tsx          # App header with logo + interactive shipping toggle
│   ├── hooks/
│   │   ├── useAppState.tsx         # Global state context (conversation, jobs, data source, interactive mode)
│   │   ├── useConversation.ts      # Agent SSE conversation lifecycle (session + events + mode management)
│   │   ├── useJobProgress.ts       # Real-time SSE progress tracking
│   │   ├── useSSE.ts              # Generic EventSource hook
│   │   └── useExternalSources.ts   # Shopify/platform connection management
│   ├── lib/
│   │   ├── api.ts                  # REST client (all /api/v1 endpoints)
│   │   └── utils.ts               # Tailwind class merging (cn), formatCurrency, formatRelativeTime, formatTimeAgo
│   └── types/
│       └── api.ts                  # TypeScript types mirroring Pydantic schemas
└── package.json
```

## Key Services

### OrchestrationAgent (`src/orchestrator/agent/client.py`)

The primary orchestrator. Uses Claude Agent SDK with persistent sessions. Manages MCP server lifecycle (Data Source, UPS), routes tool calls through validation hooks, and streams events via SSE. The agent maintains conversation context across messages within the same session — no manual history passing needed.

Key features:
- `process_message_stream()` — yields SSE-compatible event dicts (agent_message_delta, tool_call, error)
- `StreamEvent` support — real-time token-by-token streaming when SDK supports it
- `interrupt()` — graceful cancellation of in-progress responses
- MCP servers: `orchestrator` (in-process tools) + `ups` (stdio child process)
- Default model: `AGENT_MODEL` env → `ANTHROPIC_MODEL` env → Claude Haiku 4.5

### UPS MCP Server (local fork: `matt-hans/ups-mcp`)

Runs as a stdio child process via `.venv/bin/python3 -m ups_mcp`, providing the agent with interactive access to 7 UPS tools. Installed as editable package from pinned commit.

| MCP Tool | Purpose |
|----------|---------|
| `rate_shipment` | Get shipping rate or compare rates across services |
| `create_shipment` | Create shipment with label generation |
| `void_shipment` | Cancel an existing shipment |
| `validate_address` | Validate U.S. and Puerto Rico addresses |
| `track_package` | Track shipment status and delivery estimates |
| `recover_label` | Recover previously generated shipping labels |
| `get_time_in_transit` | Estimate delivery timeframes |

### UPSMCPClient (`src/services/ups_mcp_client.py`)

Async UPS client communicating via MCP stdio protocol — the batch execution path. Built on the generic `MCPClient` with UPS-specific response normalization and error translation. Includes retry with exponential backoff for transient UPS errors.

| Method | Purpose |
|--------|---------|
| `get_rate()` | Get shipping cost estimate (batch preview) |
| `create_shipment()` | Create shipment, returns tracking number + label (batch execute) |
| `void_shipment()` | Cancel a shipment |
| `validate_address()` | Validate/correct addresses |

### MCPClient (`src/services/mcp_client.py`)

Generic async MCP client with connection lifecycle, JSON parsing, retry with exponential backoff. Base class for `UPSMCPClient`, `DataSourceMCPClient`, `ExternalSourcesMCPClient`.

### Gateway Provider (`src/services/gateway_provider.py`)

Process-global singleton factory for MCP clients. Double-checked locking. `get_data_gateway()`, `get_external_sources_client()`, `shutdown_gateways()` (FastAPI lifespan hook).

### BatchEngine (`src/services/batch_engine.py`)

Unified preview + execution with concurrent `asyncio.gather` + semaphore (`BATCH_CONCURRENCY` env, default 5). Per-row state writes for crash recovery. SSE events for real-time progress.

### AgentSessionManager (`src/services/agent_session_manager.py`)

Per-conversation agent sessions. Each gets isolated history, persistent `OrchestrationAgent`, `agent_source_hash` for change detection (agent rebuilt on source/mode change), `asyncio.Lock` for serialization, optional prewarm.

### UPSPayloadBuilder (`src/services/ups_payload_builder.py`)

Builds UPS API payloads from column-mapped data. Key details: `Packaging` (not `PackagingType`), `ShipmentCharge` as array, no shipment-level ReferenceNumber (Ground rejects it).

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
# Agent tools (deterministic — no LLM calls)
pytest tests/orchestrator/agent/ -v

# System prompt generation
pytest tests/orchestrator/agent/test_system_prompt.py -v

# Hooks (pre/post tool validation)
pytest tests/orchestrator/agent/test_hooks.py -v

# Batch engine (preview + execution paths)
pytest tests/services/test_batch_engine.py -v

# UPS MCP client (programmatic MCP calls)
pytest tests/services/test_ups_mcp_client.py -v

# Column mapping + payload builder
pytest tests/services/test_column_mapping.py tests/services/test_ups_payload_builder.py -v

# Logistics filters (Jinja2 template filters)
pytest tests/orchestrator/test_logistics_filters.py -v
```

## Key Conventions

### Error Codes

Format: `E-XXXX` with category prefixes:
- `E-1xxx`: Data errors
- `E-2xxx`: Validation errors
- `E-3xxx`: UPS API errors
- `E-4xxx`: System errors
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
- CSS classes: `card-premium`, `btn-primary`, `btn-secondary`, `badge-*`
- Icons: `ui/icons.tsx` (general), `ui/brand-icons.tsx` (platform logos)
- shadcn/ui primitives in `components/ui/`
- Labels stored on disk, paths in `JobRow.label_path`; `order_data` as JSON text in `JobRow.order_data`

## Known Issues

- SSE/streaming tests may hang — use `pytest -k "not stream and not sse and not progress"`
- After backend restart, Shopify connection lost (in-memory) — call `GET /api/v1/platforms/shopify/env-status`
- EDI adapter test collection errors (10 tests, unrelated to core features)

## UPS API Lessons

These are hard-won fixes — do not revert:
- `Packaging` not `PackagingType` for the package type key
- `ShipmentCharge` must be an array `[{...}]`, not a single object
- ReferenceNumber at shipment level is rejected for Ground domestic (omitted entirely)
- Filter evaluator handles compound AND/OR WHERE clauses with parenthesis-depth-aware splitting
- Person name queries generate `customer_name = 'X' OR ship_to_name = 'X'` for disambiguation
- UPS `_translate_error` was swallowing error details — ensure raw_str fallback when ups_message is empty

## Extension Points

All extensions MUST integrate through the agent's tool/MCP architecture:

- **New Carrier (e.g., FedEx, USPS)**: Build as an MCP server (stdio), add MCP client wrapper following `UPSMCPClient` pattern, register carrier tools in the agent's tool registry
- **New Data Source Adapter**: Implement `BaseSourceAdapter` in `src/mcp/data_source/adapters/`, register in the Data Source MCP server
- **New Platform Integration**: Add client in `src/mcp/external_sources/clients/`, register in External Sources MCP server
- **New Agent Tool**: Add handler in appropriate tool module (`data.py`, `pipeline.py`, `interactive.py`), register in `tools/__init__.py`
- **New Batch Capability**: Extend `BatchEngine` with new execution mode, expose via pipeline tool
- **Template Filters**: Register in Filter Registry for custom Jinja2 logistics filters
- **Observers**: Subscribe to BatchEngine SSE events for notifications/webhooks

## Roadmap (Agent Capabilities)

Each roadmap item adds new intelligence or connectivity to the agent:

| Priority | Capability | Agent Impact | Status |
|----------|-----------|-------------|--------|
| **P0** | International Shipping (CA/MX) | Agent learns customs rules, commodity classification, duty/tax estimation. New `international_rules.py` provides lane-driven requirements. Payload builder gains international enrichment stage. | Design complete, 17 tasks planned across 6 phases |
| **P1** | Multi-Carrier (FedEx, USPS) | New MCP servers per carrier. Agent gains carrier comparison intelligence — "ship cheapest" becomes multi-carrier rate shopping. New tool: `compare_carriers`. | Not started |
| **P1** | Address Book | Persistent shipper/recipient profiles. Agent can reference "ship to John's usual address" via new `resolve_address` tool. | Not started |
| **P2** | Google Sheets Integration | New data source adapter in `adapters/`. Agent gains cloud-native data connectivity. | Not started |
| **P2** | Webhook Notifications | Batch completion alerts via external endpoints. Agent gains `notify_webhook` tool for post-execution actions. | Not started |
| **P3** | Smart Routing | Agent recommends optimal carrier+service based on destination, weight, deadline, cost. Requires multi-carrier foundation. | Not started |

## Boundaries

ShipAgent is a **shipping orchestration agent**, not a general commerce platform. These boundaries are intentional — they keep the agent focused and the architecture clean:

- **Read-only for orders**: The agent reads from data sources and platforms but never modifies source orders (except write-back of tracking numbers)
- **No inventory management**: Out of scope — shipping is the domain, not warehouse management
- **No payment processing**: Shipping costs are billed to the UPS account, not processed by ShipAgent
- **No customer communication**: The agent doesn't send emails/SMS to end customers — that's the platform's job
- **UPS only (for now)**: Multi-carrier is on the roadmap but MVP is UPS-only via the `ups-mcp` server
