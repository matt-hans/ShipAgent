# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**Current Phase:** 7 - Web Interface (in progress, core chat UI operational)
**Phases 1-6:** COMPLETE (State DB, Data Source MCP, Error Handling, NL Engine, Agent Integration, Batch Execution)
**Test Count:** 777 tests (746 unit + 31 integration)
**UPS MCP Pivot:** COMPLETE — direct Python import replaces subprocess MCP model

## Project Overview

**ShipAgent** is a natural language interface for batch shipment processing. Users describe what they want to ship in plain English ("Ship all California orders from today's spreadsheet using UPS Ground"), and the system handles parsing intent, extracting data, validating against carrier schemas, and executing shipments with full audit trails.

**Core Design Principle:** The LLM acts as a *Configuration Engine*, not a *Data Pipe*. It interprets user intent and generates transformation rules, but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly.

## Key Capabilities (Implemented)

- Natural language commands for shipment creation
- Data source support: CSV, Excel (.xlsx), PostgreSQL/MySQL databases, Shopify (via env auto-detect)
- UPS API coverage: shipping, rating, address validation (via direct `ups-mcp` ToolManager import)
- Deterministic batch execution with per-row audit logging and SSE real-time progress
- Column mapping with LLM-generated source-to-payload field mappings
- Preview mode with cost estimates before execution
- Crash recovery (resume interrupted batches)
- Write-back tracking numbers to source data
- Chat-based UI with CompletionArtifact cards for completed batches (inline label access)
- Continuous chat flow — multiple commands in same conversation without page reload
- NL filter generation with AND/OR compound clause parsing and person name disambiguation

## Architecture

Uses a hybrid architecture: **Model Context Protocol (MCP)** for data source abstraction, **direct Python import** for UPS operations, and **FastAPI + React** for the web interface.

### System Components

```
User → Browser UI (React) → FastAPI REST API → Orchestration Agent → Services → External APIs
                                    ↓                                    ↓
                              State Database                    Data Source MCP (stdio)
```

| Container | Technology | Purpose |
|-----------|------------|---------|
| **FastAPI Backend** | Python + FastAPI + SQLAlchemy | REST API, job management, SSE progress streaming |
| **Orchestration Agent** | Python + Claude Agent SDK | Interprets intent, coordinates services, runs batch execution |
| **Data Source MCP** | Python + FastMCP + DuckDB | Abstracts data sources (CSV, Excel, DB) behind SQL interface |
| **UPS Service** | Python + `ups-mcp` ToolManager | Direct Python import for UPS shipping, rating, address validation |
| **Batch Engine** | Python | Unified preview + execution with per-row state tracking |
| **State Database** | SQLite | Job state, transaction journal, audit logs for crash recovery |
| **Browser UI** | React + Vite + TypeScript + shadcn/ui | Chat interface, job history, label preview |

### Communication Patterns

- **Browser ↔ Backend**: REST API (`/api/v1/`) + SSE for real-time progress
- **Agent ↔ Data Source MCP**: stdio transport (child process)
- **Agent ↔ Anthropic API**: HTTPS via Claude Agent SDK
- **Backend ↔ State DB**: SQLite via SQLAlchemy
- **UPSService ↔ UPS API**: Direct Python import (`ups-mcp` ToolManager) with OAuth 2.0

### Data Flow (Batch Processing)

1. **Command**: User types NL command in chat → FastAPI → Orchestration Agent
2. **Intent Parsing**: LLM generates SQL filter + column mapping from natural language
3. **Data Extraction**: Filtered data loaded via Data Source MCP or Shopify client, checksums computed
4. **Preview**: BatchEngine rates each row via UPSService, cost estimates shown in PreviewCard
5. **Approval Gate**: User reviews preview (row count, cost, shipment samples) and confirms
6. **Execution**: Each row processed via BatchEngine with per-row state writes + SSE progress streaming
7. **Completion**: CompletionArtifact card appears in chat with label access, job saved to history
8. **Write-Back**: Tracking numbers written back to source, job marked complete

## Source Structure

```
src/
├── api/                        # FastAPI REST API
│   ├── routes/                 # Endpoint modules
│   │   ├── jobs.py             # Job CRUD
│   │   ├── preview.py          # Batch preview (rewritten for BatchEngine)
│   │   ├── progress.py         # Real-time SSE streaming
│   │   ├── commands.py         # NL command processing
│   │   ├── labels.py           # Label generation/download/merge
│   │   ├── logs.py             # Audit log endpoints
│   │   └── platforms.py        # Shopify, SAP, Oracle, WooCommerce
│   ├── main.py                 # App factory with lifespan events
│   └── schemas.py              # Pydantic request/response models
├── db/                         # Database layer
│   ├── models.py               # SQLAlchemy models (Job, JobRow, AuditLog)
│   └── connection.py           # Session management
├── errors/                     # Error handling
│   ├── registry.py             # E-XXXX error code registry
│   ├── ups_translation.py      # UPS error → ShipAgent error mapping
│   └── formatter.py            # Error message formatting
├── services/                   # Business logic (core services)
│   ├── ups_service.py          # UPSService — wraps ups-mcp ToolManager
│   ├── batch_engine.py         # BatchEngine — unified preview + execution
│   ├── column_mapping.py       # ColumnMappingService — source → UPS field mapping
│   ├── ups_payload_builder.py  # Builds UPS API payloads from mapped data
│   ├── command_processor.py    # Command routing, filter evaluation, Shopify integration
│   ├── job_service.py          # Job state machine, row tracking
│   └── audit_service.py        # Audit logging with redaction
├── mcp/
│   ├── data_source/            # Data Source MCP server
│   │   ├── server.py           # FastMCP server
│   │   ├── adapters/           # CSV, Excel, Database, EDI adapters
│   │   └── tools/              # Import, schema, query, checksum, writeback tools
│   ├── ups/                    # UPS OpenAPI specifications
│   │   └── specs/              # Rating.yaml, Shipping.yaml, TimeInTransit.yaml
│   └── external_sources/       # External platform MCP
│       └── clients/            # Shopify, SAP, Oracle, WooCommerce clients
└── orchestrator/               # Orchestration layer
    ├── nl_engine/              # NL parsing, filter generation, elicitation
    │   ├── engine.py           # Main NL processing engine
    │   ├── intent_parser.py    # NL → ShippingIntent
    │   ├── filter_generator.py # NL → SQL WHERE clause (schema-grounded)
    │   ├── elicitation.py      # User clarification flows
    │   └── config.py           # Model configuration
    ├── filters/                # Jinja2 logistics filter library
    │   └── logistics.py        # truncate_address, format_us_zip, convert_weight, etc.
    ├── models/                 # Data models (intent, filter, mapping, elicitation)
    ├── agent/                  # Claude Agent SDK integration
    │   ├── client.py           # Agent client
    │   ├── config.py           # Agent configuration
    │   ├── tools.py            # Tool definitions
    │   └── hooks.py            # Lifecycle hooks
    └── batch/                  # Batch orchestration
        ├── events.py           # Batch execution events
        ├── models.py           # Batch state models
        ├── modes.py            # Preview/execute modes
        ├── recovery.py         # Crash recovery
        └── sse_observer.py     # SSE streaming observer

frontend/
├── src/
│   ├── components/
│   │   ├── CommandCenter.tsx       # Main chat UI (messages, preview, progress, artifacts)
│   │   ├── JobDetailPanel.tsx      # Full job detail view (from sidebar click)
│   │   ├── LabelPreview.tsx        # PDF label viewer modal (react-pdf)
│   │   ├── DataSourceManager.tsx   # Data source connection UI
│   │   └── layout/
│   │       ├── Sidebar.tsx         # Data sources + Job History sidebar
│   │       └── Header.tsx          # App header
│   ├── hooks/
│   │   ├── useAppState.tsx         # Global state context (conversation, jobs, data source)
│   │   ├── useJobProgress.ts       # Real-time SSE progress tracking
│   │   ├── useSSE.ts              # Generic EventSource hook
│   │   └── useExternalSources.ts   # Shopify/platform connection management
│   ├── lib/
│   │   └── api.ts                  # REST client (all /api/v1 endpoints)
│   └── types/
│       └── api.ts                  # TypeScript types mirroring Pydantic schemas
└── package.json
```

## Key Services

### UPSService (`src/services/ups_service.py`)

Wraps `ups-mcp` ToolManager for direct Python calls to UPS APIs. Handles OAuth 2.0 authentication, response normalization, and error translation.

| Method | Purpose |
|--------|---------|
| `rate_shipment()` | Get shipping cost estimate |
| `create_shipment()` | Create shipment, returns tracking number + label |
| `void_shipment()` | Cancel a shipment |
| `validate_address()` | Validate/correct addresses |

### BatchEngine (`src/services/batch_engine.py`)

Unified engine for both preview (rating) and execution (shipping). Processes rows sequentially with per-row state writes for crash recovery. Emits SSE events for real-time progress.

### ColumnMappingService (`src/services/column_mapping.py`)

Maps source data columns to UPS payload fields. The LLM generates mapping rules; deterministic code applies them to actual data.

### UPSPayloadBuilder (`src/services/ups_payload_builder.py`)

Builds OpenAPI-validated UPS API payloads from column-mapped data. Key details:
- Uses `Packaging` (not `PackagingType`) as the package type key
- `ShipmentCharge` must be an array, not a single object
- ReferenceNumber at shipment level is omitted (UPS Ground rejects it)

### CommandProcessor (`src/services/command_processor.py`)

Routes NL commands, evaluates SQL WHERE clause filters against in-memory order data, handles Shopify order integration. Supports compound AND/OR clause parsing with parenthesis-depth-aware splitting.

## Frontend Architecture

### Chat Flow (CommandCenter.tsx)

The main UI is a conversational chat interface:

1. **User types command** → UserMessage appears right-aligned
2. **Processing** → TypingIndicator shown, input disabled
3. **Preview** → PreviewCard with shipment samples, cost estimate, Confirm/Cancel buttons
4. **Execution** → ProgressDisplay with live progress bar, stats via SSE
5. **Completion** → ProgressDisplay replaced by CompletionArtifact (compact card with "View Labels" button)
6. **Ready for next** → Input re-enables, user can type another command immediately

### Key Components

| Component | Purpose |
|-----------|---------|
| `CommandCenter` | Main chat: messages, preview cards, progress, completion artifacts |
| `CompletionArtifact` | Compact inline card for completed batches (green/amber/red border) |
| `PreviewCard` | Shipment preview with expandable rows and Confirm/Cancel |
| `ProgressDisplay` | Live batch execution progress (SSE-powered) |
| `LabelPreview` | PDF modal viewer (react-pdf), opens as overlay |
| `JobDetailPanel` | Full job detail view (triggered from sidebar click) |
| `Sidebar` | Data source connections + searchable/filterable Job History |

### State Management

- `useAppState` context: conversation history, active job, data source, processing state
- `ConversationMessage` metadata: `action` field routes to different renderers (`preview`, `execute`, `complete`, `error`, `elicit`)
- `useJobProgress` + `useSSE`: real-time SSE events for batch progress
- `jobListVersion` counter triggers sidebar job list refresh

## API Endpoints

All endpoints use `/api/v1/` prefix.

| Route | Method | Purpose |
|-------|--------|---------|
| `/commands/` | POST | Process NL shipping command |
| `/jobs/` | GET | List all jobs |
| `/jobs/{id}` | GET | Get job details |
| `/jobs/{id}/preview` | GET | Get batch preview data |
| `/jobs/{id}/preview/confirm` | POST | Confirm batch execution |
| `/jobs/{id}/progress/stream` | GET | SSE stream for real-time progress |
| `/jobs/{id}/labels/merged` | GET | Download merged PDF labels |
| `/jobs/{id}/labels/{tracking}` | GET | Download individual label |
| `/jobs/{id}/logs` | GET | Get audit logs |
| `/platforms/shopify/env-status` | GET | Check Shopify connection (auto-detect from env) |
| `/platforms/shopify/orders` | GET | Fetch Shopify orders |

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
- Icons are inline SVG components (no external icon library)
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

- **Data Adapters**: Implement `BaseSourceAdapter` (read, write_back, get_metadata)
- **Carrier Services**: Follow UPSService pattern wrapping carrier SDK/API clients
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
