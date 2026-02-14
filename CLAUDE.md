# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**Current Phase:** 7 - Web Interface (in progress, core chat UI operational)
**Phases 1-6:** COMPLETE (State DB, Data Source MCP, Error Handling, NL Engine, Agent Integration, Batch Execution)
**SDK Orchestration Redesign:** COMPLETE — Claude SDK is now the primary orchestration path via `/api/v1/conversations/` endpoints; legacy `/commands/` path deprecated
**Test Count:** 777+ tests (746 unit + 31 integration + new conversation tests)
**UPS MCP Hybrid:** COMPLETE — agent uses ups-mcp as stdio MCP server for interactive tools; BatchEngine uses UPSMCPClient (programmatic MCP over stdio) for deterministic batch execution

## Project Overview

**ShipAgent** is a natural language interface for batch shipment processing. Users describe what they want to ship in plain English ("Ship all California orders from today's spreadsheet using UPS Ground"), and the system handles parsing intent, extracting data, validating against carrier schemas, and executing shipments with full audit trails.

**Core Design Principle:** The LLM acts as a *Configuration Engine*, not a *Data Pipe*. It interprets user intent and generates transformation rules, but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly.

## Key Capabilities (Implemented)

- Natural language commands for shipment creation
- Data source support: CSV, Excel (.xlsx), PostgreSQL/MySQL databases, Shopify (via env auto-detect)
- UPS API coverage: shipping, rating, address validation, tracking, label recovery, time-in-transit (via `ups-mcp` MCP server for both interactive agent and batch paths)
- Deterministic batch execution with per-row audit logging and SSE real-time progress
- Column mapping with LLM-generated source-to-payload field mappings
- Preview mode with cost estimates before execution
- Crash recovery (resume interrupted batches)
- Write-back tracking numbers to source data
- Chat-based UI with CompletionArtifact cards for completed batches (inline label access)
- Continuous chat flow — multiple commands in same conversation without page reload
- NL filter generation with AND/OR compound clause parsing and person name disambiguation
- Saved data sources with one-click reconnect (CSV/Excel instant, database requires re-entering credentials)

## Architecture

Uses a hybrid architecture: **Claude Agent SDK** as the primary orchestration engine, **Model Context Protocol (MCP)** for data source abstraction and all UPS operations (both interactive and batch), and **FastAPI + React** for the web interface. The agent drives the entire command lifecycle through its SDK agent loop — intent parsing, filter generation, and tool orchestration are all handled within the agent's system prompt and deterministic tools.

### System Components

```
User → Browser UI (React) → FastAPI REST API → Conversation SSE Route → AgentSessionManager → OrchestrationAgent → Services
                                    ↓                    ↓                                          ↓
                              State Database        SSE Event Stream                       Data Source MCP (stdio)
```

| Container | Technology | Purpose |
|-----------|------------|---------|
| **FastAPI Backend** | Python + FastAPI + SQLAlchemy | REST API, job management, SSE conversation streaming |
| **Orchestration Agent** | Python + Claude Agent SDK | Primary orchestration — interprets intent, coordinates services via deterministic tools |
| **Agent Session Manager** | Python | Per-conversation agent session lifecycle, history isolation |
| **Data Source MCP** | Python + FastMCP + DuckDB | Abstracts data sources (CSV, Excel, DB) behind SQL interface |
| **UPS MCP** | `ups-mcp` via uvx (stdio) | Agent-accessible UPS tools: shipping, rating, tracking, address validation, label recovery, time-in-transit |
| **UPS MCP Client** | Python + `MCPClient` | Async programmatic MCP client for deterministic batch execution (shipping, rating) via stdio |
| **Batch Engine** | Python | Unified preview + execution with per-row state tracking |
| **State Database** | SQLite | Job state, transaction journal, audit logs for crash recovery |
| **Browser UI** | React + Vite + TypeScript + shadcn/ui | Chat interface, job history, label preview |

### Communication Patterns

- **Browser ↔ Backend**: REST API (`/api/v1/conversations/`) + SSE for agent event streaming
- **Conversation Route ↔ Agent**: `AgentSessionManager` manages per-session agent instances
- **Agent ↔ Data Source MCP**: stdio transport (child process)
- **Agent ↔ UPS MCP**: stdio transport (child process via uvx, interactive UPS operations)
- **Agent ↔ Anthropic API**: HTTPS via Claude Agent SDK
- **Backend ↔ State DB**: SQLite via SQLAlchemy
- **BatchEngine ↔ UPS MCP**: Programmatic MCP over stdio via `UPSMCPClient` → `MCPClient` for batch execution

### Data Flow (Agent-Driven Conversation)

1. **Session**: Frontend creates conversation session via `POST /conversations/` → `AgentSessionManager` allocates session
2. **Message**: User sends message via `POST /conversations/{id}/messages` → stored in history, triggers agent processing
3. **Agent Loop**: `OrchestrationAgent.process_message_stream()` runs SDK agent loop with unified system prompt
4. **Tool Calls**: Agent calls deterministic tools (`query_orders`, `preview_batch`, `execute_batch`, etc.) — events streamed via SSE
5. **Preview**: Agent calls `preview_batch` tool → `BatchEngine` rates rows → preview data sent as SSE event
6. **Approval Gate**: Agent asks for confirmation → user responds in conversation → agent proceeds
7. **Execution**: Agent calls `execute_batch` tool → per-row processing with SSE progress events
8. **Completion**: CompletionArtifact card appears in chat with label access, job saved to history
9. **Write-Back**: Tracking numbers written back to source, job marked complete

## Source Structure

```
src/
├── api/                        # FastAPI REST API
│   ├── routes/                 # Endpoint modules
│   │   ├── conversations.py    # Agent-driven SSE conversation (primary path)
│   │   ├── data_sources.py     # Local data source import/upload/disconnect/schema
│   │   ├── jobs.py             # Job CRUD + status + rows + summary
│   │   ├── preview.py          # Batch preview + confirm
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
├── services/                   # Business logic (core services)
│   ├── errors.py               # Shared error types (UPSServiceError)
│   ├── mcp_client.py           # Generic async MCP client with retry
│   ├── ups_mcp_client.py       # UPSMCPClient — async UPS via MCP stdio
│   ├── ups_specs.py            # UPS MCP OpenAPI spec path helpers
│   ├── batch_engine.py         # BatchEngine — unified preview + execution
│   ├── column_mapping.py       # ColumnMappingService — source → UPS field mapping
│   ├── ups_payload_builder.py  # Builds UPS API payloads from mapped data
│   ├── agent_session_manager.py # Per-conversation agent session lifecycle
│   ├── job_service.py          # Job state machine, row tracking
│   ├── audit_service.py        # Audit logging with redaction
│   ├── data_source_service.py  # Data source import + auto-save hooks
│   ├── data_source_gateway.py  # DataSourceGateway protocol + typed adapter
│   ├── data_source_mcp_client.py # DataSourceMCPClient — async data source via MCP stdio
│   ├── external_sources_mcp_client.py # ExternalSourcesMCPClient — async platform via MCP stdio
│   ├── gateway_provider.py     # Centralized singleton factory for MCP client gateways
│   ├── saved_data_source_service.py # Saved source CRUD (list, upsert, delete, reconnect)
│   └── write_back_utils.py     # Atomic CSV/Excel write-back utilities
├── mcp/
│   ├── data_source/            # Data Source MCP server
│   │   ├── server.py           # FastMCP server
│   │   ├── models.py           # Pydantic models (SchemaColumn, ImportResult, RowData)
│   │   ├── utils.py            # Row checksum (SHA-256) + date parsing utilities
│   │   ├── adapters/           # Source adapters
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
└── orchestrator/               # Orchestration layer
    ├── filters/                # Jinja2 logistics filter library
    │   └── logistics.py        # truncate_address, format_us_zip, convert_weight, etc.
    ├── models/                 # Data models
    │   ├── intent.py           # Intent parsing models
    │   ├── filter.py           # NL filter models
    │   ├── mapping.py          # Column mapping models
    │   ├── elicitation.py      # Elicitation models
    │   └── correction.py       # Self-correction loop tracking (max 3 attempts)
    ├── agent/                  # Claude Agent SDK integration (primary orchestration)
    │   ├── client.py           # OrchestrationAgent — SDK agent with streaming
    │   ├── system_prompt.py    # Unified system prompt builder (domain knowledge + tools)
    │   ├── tools_v2.py         # Temporary barrel re-exporting from tools/ (removal target: 2026-03-14)
    │   ├── tools/              # Deterministic SDK tools (split by concern)
    │   │   ├── __init__.py     # Tool registry — get_all_tool_definitions()
    │   │   ├── core.py         # Shared internals (EventEmitterBridge, UPS client cache, helpers)
    │   │   ├── data.py         # Data source + platform tool handlers
    │   │   ├── pipeline.py     # Batch pipeline tool handlers (create, preview, execute)
    │   │   └── interactive.py  # Interactive shipment tool handler
    │   ├── config.py           # Agent configuration
    │   └── hooks.py            # Lifecycle hooks
    └── batch/                  # Batch orchestration
        ├── events.py           # Batch execution events
        ├── models.py           # Batch state models
        ├── modes.py            # Preview/execute modes
        ├── recovery.py         # Crash recovery
        └── sse_observer.py     # SSE streaming observer

frontend/
├── src/
│   ├── main.tsx                    # React entry point
│   ├── App.tsx                     # Root component (AppStateProvider + layout)
│   ├── index.css                   # Design system (Tailwind theme, animations, component styles)
│   ├── components/
│   │   ├── CommandCenter.tsx       # Main chat UI (messages, preview, progress, artifacts)
│   │   ├── command-center/
│   │   │   ├── presentation.tsx    # Barrel re-exporting split modules (removal target: 2026-03-14)
│   │   │   ├── messages.tsx        # Message rendering (WelcomeMessage, ActiveSourceBanner, MessageBubble)
│   │   │   ├── PreviewCard.tsx     # Shipment preview with expandable rows, cost estimates
│   │   │   ├── ProgressDisplay.tsx # Live batch execution progress with per-row failures
│   │   │   ├── CompletionArtifact.tsx # Inline card for completed batches
│   │   │   └── ToolCallChip.tsx    # Collapsible chip showing active agent tool calls
│   │   ├── JobDetailPanel.tsx      # Full job detail view (from sidebar click)
│   │   ├── LabelPreview.tsx        # PDF label viewer modal (react-pdf)
│   │   ├── RecentSourcesModal.tsx  # Saved sources browser (search, filter, reconnect, bulk delete)
│   │   ├── sidebar/
│   │   │   ├── panels.tsx          # Barrel re-exporting split modules (removal target: 2026-03-14)
│   │   │   ├── DataSourcePanel.tsx # Data source switching, file upload, DB connection, Shopify
│   │   │   ├── JobHistoryPanel.tsx # Job list with search, filters, delete, printer access
│   │   │   └── dataSourceMappers.ts # Column-to-ColumnMetadata mapping helpers
│   │   ├── ui/                     # shadcn/ui primitives + consolidated icons
│   │   │   ├── ShipAgentLogo.tsx   # Custom logo components
│   │   │   ├── icons.tsx           # Consolidated SVG icon components
│   │   │   ├── brand-icons.tsx     # Platform brand icons (Shopify, SAP, Oracle, WooCommerce)
│   │   │   ├── button.tsx, input.tsx, card.tsx, progress.tsx
│   │   │   ├── dialog.tsx, alert.tsx, scroll-area.tsx
│   │   │   └── ...
│   │   └── layout/
│   │       ├── Sidebar.tsx         # Sidebar shell (delegates to sidebar/panels.tsx)
│   │       └── Header.tsx          # App header
│   ├── hooks/
│   │   ├── useAppState.tsx         # Global state context (conversation, jobs, data source)
│   │   ├── useConversation.ts      # Agent SSE conversation lifecycle (session + events)
│   │   ├── useJobProgress.ts       # Real-time SSE progress tracking
│   │   ├── useSSE.ts              # Generic EventSource hook
│   │   └── useExternalSources.ts   # Shopify/platform connection management
│   ├── lib/
│   │   ├── api.ts                  # REST client (all /api/v1 endpoints)
│   │   └── utils.ts               # Tailwind class merging utility (cn)
│   └── types/
│       └── api.ts                  # TypeScript types mirroring Pydantic schemas
└── package.json
```

## Key Services

### UPS MCP Server (external: `github.com/UPS-API/ups-mcp`)

Runs as a stdio child process (via uvx), providing the agent with interactive access to 7 UPS tools. The agent can call these directly for ad-hoc operations during conversation.

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

Async UPS client communicating via MCP stdio protocol. Replaces the deprecated `UPSService` for batch execution. Built on the generic `MCPClient` with UPS-specific response normalization and error translation. Includes retry with exponential backoff for transient UPS errors.

| Method | Purpose |
|--------|---------|
| `get_rate()` | Get shipping cost estimate (batch preview) |
| `create_shipment()` | Create shipment, returns tracking number + label (batch execute) |
| `void_shipment()` | Cancel a shipment |
| `validate_address()` | Validate/correct addresses |

### MCPClient (`src/services/mcp_client.py`)

Generic reusable async MCP client with connection lifecycle management, JSON response parsing, and configurable retry with exponential backoff. Used by `UPSMCPClient`, `DataSourceMCPClient`, and `ExternalSourcesMCPClient`.

### DataSourceGateway (`src/services/data_source_gateway.py`)

Protocol-based abstraction for data source operations. `DataSourceMCPClient` implements this protocol, providing import, schema inspection, query, and disconnect operations via MCP stdio transport. The `gateway_provider.py` module provides centralized singleton access.

### ExternalSourcesMCPClient (`src/services/external_sources_mcp_client.py`)

Async client for external platform operations (Shopify connect/disconnect, order fetching) via MCP stdio transport. Singleton managed by `gateway_provider.py`.

### BatchEngine (`src/services/batch_engine.py`)

Unified engine for both preview (rating) and execution (shipping). Processes rows sequentially with per-row state writes for crash recovery. Emits SSE events for real-time progress.

### ColumnMappingService (`src/services/column_mapping.py`)

Maps source data columns to UPS payload fields. The LLM generates mapping rules; deterministic code applies them to actual data.

### UPSPayloadBuilder (`src/services/ups_payload_builder.py`)

Builds OpenAPI-validated UPS API payloads from column-mapped data. Key details:
- Uses `Packaging` (not `PackagingType`) as the package type key
- `ShipmentCharge` must be an array, not a single object
- ReferenceNumber at shipment level is omitted (UPS Ground rejects it)

### AgentSessionManager (`src/services/agent_session_manager.py`)

Manages per-conversation agent sessions. Each conversation gets an isolated `AgentSession` with its own message history. Sessions are created lazily on first message and cleaned up on delete.

### SavedDataSourceService (`src/services/saved_data_source_service.py`)

Persists data source connection metadata for one-click reconnection. Auto-saved on every successful import (best-effort). Database credentials are NEVER stored — only display metadata (host, port, db_name). Upsert logic keyed by natural keys (file_path for CSV, file_path+sheet_name for Excel, host+db_name+query for databases).

| Method | Purpose |
|--------|---------|
| `list_sources()` | List all saved sources, ordered by last used |
| `save_or_update_csv()` | Upsert CSV source record |
| `save_or_update_excel()` | Upsert Excel source record |
| `save_or_update_database()` | Upsert database source record (no credentials) |
| `delete_source()` / `bulk_delete()` | Remove saved source records |
| `touch()` | Update `last_used_at` on reconnect |

## Frontend Architecture

### Chat Flow (CommandCenter.tsx)

The main UI is an agent-driven conversational chat interface powered by `useConversation` hook:

1. **User types command** → `useConversation.sendMessage()` creates session (first time) + sends to agent
2. **Agent Processing** → SSE events stream in: `agent_thinking`, `tool_call`, `tool_result`, `agent_message`
3. **Tool Call Chips** → Active tool calls shown as collapsible chips in the message area
4. **Preview** → PreviewCard with shipment samples, cost estimate, Confirm/Cancel buttons
5. **Execution** → ProgressDisplay with live progress bar, stats via SSE
6. **Completion** → CompletionArtifact card appears in chat with label access
7. **Ready for next** → Input re-enables, user can type another command in same session

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| `CommandCenter` | `CommandCenter.tsx` | Main chat: messages, preview cards, progress, completion artifacts |
| `CompletionArtifact` | `command-center/CompletionArtifact.tsx` | Inline card for completed batches (green/amber/red border, label access) |
| `PreviewCard` | `command-center/PreviewCard.tsx` | Shipment preview with expandable rows, cost estimates, warnings, Confirm/Cancel |
| `ProgressDisplay` | `command-center/ProgressDisplay.tsx` | Live batch execution progress with per-row failures |
| `ToolCallChip` | `command-center/ToolCallChip.tsx` | Collapsible chip showing active agent tool calls |
| `ActiveSourceBanner` | `command-center/messages.tsx` | Banner showing currently connected data source |
| `WelcomeMessage` | `command-center/messages.tsx` | Initial welcome with example commands |
| `LabelPreview` | `LabelPreview.tsx` | PDF modal viewer (react-pdf), opens as overlay |
| `JobDetailPanel` | `JobDetailPanel.tsx` | Full job detail view (triggered from sidebar click) |
| `RecentSourcesModal` | `RecentSourcesModal.tsx` | Saved source browser with search, type filters, one-click reconnect, bulk delete |
| `DataSourceSection` | `sidebar/DataSourcePanel.tsx` | Data source switching, file upload, DB connection, Shopify integration |
| `JobHistorySection` | `sidebar/JobHistoryPanel.tsx` | Job list with search, filters, delete, printer access |
| `Sidebar` | `layout/Sidebar.tsx` | Sidebar shell delegating to DataSourceSection + JobHistorySection |

### State Management

- `useAppState` context: conversation history, active job, data source, processing state, `conversationSessionId`
- `useConversation` hook: manages agent session lifecycle, SSE event streaming, session creation/deletion
- `ConversationMessage` metadata: `action` field routes to different renderers (`preview`, `execute`, `complete`, `error`, `elicit`)
- `useJobProgress` + `useSSE`: real-time SSE events for batch progress
- `jobListVersion` counter triggers sidebar job list refresh

## API Endpoints

All endpoints use `/api/v1/` prefix.

### Conversations

| Route | Method | Purpose |
|-------|--------|---------|
| `/conversations/` | POST | Create agent conversation session |
| `/conversations/{id}/messages` | POST | Send message to agent (202 accepted) |
| `/conversations/{id}/stream` | GET | SSE stream of agent events |
| `/conversations/{id}/history` | GET | Get conversation message history |
| `/conversations/{id}` | DELETE | Delete conversation session |

### Jobs

| Route | Method | Purpose |
|-------|--------|---------|
| `/jobs/` | POST | Create a job |
| `/jobs/` | GET | List all jobs |
| `/jobs/{id}` | GET | Get job details |
| `/jobs/{id}/status` | PATCH | Update job status |
| `/jobs/{id}` | DELETE | Delete job |
| `/jobs/{id}/rows` | GET | Get all rows for a job |
| `/jobs/{id}/summary` | GET | Get job summary with metrics |
| `/jobs/{id}/rows/skip` | PATCH | Mark rows as skipped |
| `/jobs/{id}/preview` | GET | Get batch preview data |
| `/jobs/{id}/confirm` | POST | Confirm batch execution |
| `/jobs/{id}/progress/stream` | GET | SSE stream for real-time progress |
| `/jobs/{id}/progress` | GET | Get current progress (non-SSE fallback) |

### Labels

| Route | Method | Purpose |
|-------|--------|---------|
| `/labels/{tracking_number}` | GET | Download label by tracking number |
| `/jobs/{id}/labels/merged` | GET | Download merged PDF labels |
| `/jobs/{id}/labels/zip` | GET | Download labels as ZIP |
| `/jobs/{id}/labels/{row_number}` | GET | Download label by row number |

### Logs

| Route | Method | Purpose |
|-------|--------|---------|
| `/jobs/{id}/logs` | GET | Get audit logs |
| `/jobs/{id}/logs/errors` | GET | Get recent error logs |
| `/jobs/{id}/logs/export` | GET | Export logs as plain text |

### Data Sources

| Route | Method | Purpose |
|-------|--------|---------|
| `/data-sources/import` | POST | Import CSV/Excel/Database |
| `/data-sources/upload` | POST | Upload CSV/Excel file |
| `/data-sources/status` | GET | Get current data source status |
| `/data-sources/disconnect` | POST | Disconnect current source |
| `/data-sources/schema` | GET | Get schema of current source |

### Saved Sources

| Route | Method | Purpose |
|-------|--------|---------|
| `/saved-sources` | GET | List all saved data sources (optional `source_type` filter) |
| `/saved-sources/{id}` | GET | Get single saved source |
| `/saved-sources/reconnect` | POST | Reconnect to saved source (one-click for files, requires connection_string for DBs) |
| `/saved-sources/{id}` | DELETE | Delete saved source |
| `/saved-sources/bulk-delete` | POST | Bulk delete saved sources |

### Platforms

| Route | Method | Purpose |
|-------|--------|---------|
| `/platforms/connections` | GET | List all configured platform connections |
| `/platforms/{platform}/connect` | POST | Connect to platform |
| `/platforms/{platform}/disconnect` | POST | Disconnect from platform |
| `/platforms/{platform}/test` | GET | Test platform connection |
| `/platforms/shopify/env-status` | GET | Check Shopify connection (auto-detect from env) |
| `/platforms/{platform}/orders` | GET | Fetch orders from platform |
| `/platforms/{platform}/orders/{id}` | GET | Get single order |
| `/platforms/{platform}/orders/{id}/tracking` | PUT | Update tracking on order |

### System

| Route | Method | Purpose |
|-------|--------|---------|
| `/health` | GET | Health check |
| `/api` | GET | API root with docs links |

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, SQLite |
| Agent Framework | Claude Agent SDK, Anthropic API |
| Data Processing | DuckDB, Pandas, openpyxl |
| UPS Integration | `ups-mcp` ToolManager (direct Python import, pinned commit) |
| NL Processing | sqlglot (SQL generation), Jinja2 (logistics filters) |
| Real-time | SSE via `sse-starlette` |
| PDF | `pypdf` (merging), `react-pdf` + `pdfjs-dist` (browser rendering) |
| Frontend | React, Vite, TypeScript, Tailwind CSS, shadcn/ui |

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

- CSS classes: `card-premium`, `btn-primary`, `btn-secondary`, `badge-*` (success/error/info/warning)
- Design system in `index.css`: OKLCH color space, custom animations, platform-specific colors (Shopify, WooCommerce, SAP, Oracle)
- Icons consolidated in `ui/icons.tsx` (general) and `ui/brand-icons.tsx` (platform logos)
- Presentation components split into individual files: `command-center/PreviewCard.tsx`, `ProgressDisplay.tsx`, `CompletionArtifact.tsx`, `ToolCallChip.tsx`, `messages.tsx`
- Sidebar panels split: `sidebar/DataSourcePanel.tsx` and `sidebar/JobHistoryPanel.tsx`
- shadcn/ui primitives in `components/ui/` (button, input, card, dialog, alert, progress, scroll-area)
- Job list refresh: `jobListVersion` counter + `refreshJobList()` in AppState
- Labels stored on disk, paths in `JobRow.label_path`
- `order_data` stored as JSON text in `JobRow.order_data` column

## Known Issues

- `zipstream-ng` ZIP endpoint tests fail due to `zipstream.ZipFile` attribute error (pre-existing)
- SSE test `test_stream_endpoint_exists` hangs indefinitely (skip with `-k`)
- EDI adapter test collection errors (10 tests, unrelated to core features)
- After backend restart, Shopify connection is lost (in-memory) — call GET `/api/v1/platforms/shopify/env-status` to reconnect
- UPS Ground rejects shipment-level ReferenceNumber (removed from payload builder)

## UPS API Lessons

These are hard-won fixes — do not revert:
- `Packaging` not `PackagingType` for the package type key
- `ShipmentCharge` must be an array `[{...}]`, not a single object
- ReferenceNumber at shipment level is rejected for Ground domestic (omitted entirely)
- Filter evaluator handles compound AND/OR WHERE clauses with parenthesis-depth-aware splitting
- Person name queries generate `customer_name = 'X' OR ship_to_name = 'X'` for disambiguation

## Extension Points

- **Data Adapters**: Implement `BaseSourceAdapter` in `src/mcp/data_source/adapters/` (read, write_back, get_metadata)
- **Carrier Services**: Follow `UPSMCPClient` pattern wrapping carrier MCP servers via `MCPClient`
- **Template Filters**: Register in Filter Registry for custom Jinja2 logistics filters
- **Observers**: Subscribe to BatchEngine SSE events for notifications/webhooks
- **Platform Clients**: Add new clients in `src/mcp/external_sources/clients/`

## Out of Scope (MVP)

- Order management (reads from external sources only)
- Inventory management
- Customer communication (email/SMS)
- Payment processing
- Multi-carrier routing (UPS only for MVP)
- Google Sheets integration (deferred to v2)
- International shipping with customs (deferred to v2)
