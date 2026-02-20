# ShipAgent

**AI-Powered Natural Language Shipping Automation**

ShipAgent is an AI-powered shipping platform that lets you describe shipments in plain English and handles the rest — from single-package ad-hoc shipments to batch processing hundreds of orders. Simply say *"Ship all California orders from today's spreadsheet using UPS Ground"* and ShipAgent parses your intent, extracts data, validates against carrier schemas, and executes shipments with full audit trails.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/react-19-blue.svg)](https://react.dev/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

---

## Features

### Core Shipping
- **Natural Language Commands** — Describe what you want to ship in plain English
- **Batch Processing** — Process hundreds of shipments with per-row audit logging
- **Single Shipment Mode** — Interactive one-off shipment creation with real-time preview
- **Preview & Confirm** — Review cost estimates and shipment details before execution
- **Crash Recovery** — Resume interrupted batches from exactly where they stopped

### Current Data Sources
- **CSV & Excel** — Upload flat files with automatic sheet detection
- **SQL Databases** — Connect to PostgreSQL/MySQL via connection string
- **Shopify** — Pull unfulfilled orders directly from your store

### Future Data Sources
- **WooCommerce** — Connect to WooCommerce REST API
- **SAP Business One** — Fetch sales orders from SAP B1 Service Layer
- **Oracle** — Query Oracle Fusion Cloud/ERP order data
- **EDI** — Parse ANSI X12 EDI 850 purchase orders

### UPS Integration
- **Shipping** — Create shipments and generate labels (GIF/PNG/ZPL)
- **Rating** — Get rate quotes with Shop mode for multi-service comparison
- **Address Validation** — Verify and correct shipping addresses
- **Package Tracking** — Track shipments by tracking number
- **Pickup Scheduling** — Schedule, cancel, rate, and check status of pickups
- **Landed Cost** — Estimate duties, taxes, and fees for international shipments
- **Paperless Documents** — Upload, attach, and manage customs/trade documents
- **Location Finder** — Find nearby UPS Access Points, retail locations, and service centers

### International Shipping
- **Lane-Driven Rules Engine** — Automatic field requirements based on origin/destination/service
- **Commodity Management** — Import and manage commodity data for customs declarations
- **InternationalForms** — Auto-generate Commercial Invoices and Certificates of Origin
- **EU-to-EU Exemptions** — Automatic customs doc exemption for EU-internal Standard shipments

### Intelligence
- **LLM Column Mapping** — AI generates source-to-payload field mappings
- **Deterministic Filter Engine** — SQL-based row filtering with token-signed confirmations
- **Decision Audit Ledger** — Centralized, redacted log of every agent decision
- **Write-Back** — Automatically update tracking numbers in your source data

---

## Architecture

ShipAgent uses the **Model Context Protocol (MCP)** to separate concerns into independent servers orchestrated by a Claude Agent SDK-powered coordinator.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Browser UI                                    │
│                       (React + Vite + Tailwind CSS 4)                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     FastAPI REST + SSE Gateway                              │
│           (Conversations, Jobs, Preview, Progress, Labels, Platforms)       │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Orchestration Agent                                   │
│                 (Python + Claude Agent SDK + 25+ Tools)                     │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐    │
│  │ Pipeline  │ │Interactive│ │  Pickup   │ │  Docs /   │ │ Tracking  │    │
│  │ (Batch)   │ │ (Single)  │ │ Schedule  │ │ Paperless │ │           │    │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘    │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────────────────┐  │
│  │ Filter    │ │  Column   │ │ Int'l     │ │  Data Source Tools        │  │
│  │ Compiler  │ │  Mapping  │ │ Rules     │ │  (connect, query, write)  │  │
│  └───────────┘ └───────────┘ └───────────┘ └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
     │                    │                    │                    │
     ▼                    ▼                    ▼                    ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ Data Source   │  │ External     │  │ UPS MCP      │  │ State Database   │
│ MCP Server   │  │ Sources MCP  │  │ Client       │  │ (SQLite)         │
│ (FastMCP)    │  │ (FastMCP)    │  │ (stdio)      │  │                  │
│              │  │              │  │              │  │ • Job state      │
│ • CSV/Excel  │  │ • Shopify    │  │ • Ship/Rate  │  │ • Audit logs     │
│ • Database   │  │ • WooCommerce│  │ • Track      │  │ • Decision audit │
│ • EDI 850    │  │ • SAP B1     │  │ • Pickup     │  │ • Recovery       │
│ • Commodities│  │ • Oracle     │  │ • Paperless  │  │ • Saved sources  │
│              │  │              │  │ • Locator    │  │                  │
└──────────────┘  └──────────────┘  │ • Landed Cost│  └──────────────────┘
     │                    │         └──────────────┘
     ▼                    ▼                │
┌──────────┐     ┌───────────────┐         ▼
│  DuckDB  │     │ Platform APIs │   ┌──────────────┐
└──────────┘     └───────────────┘   │  UPS API     │
                                     │  (OAuth 2.0) │
                                     └──────────────┘
```

### Core Design Principle

The LLM acts as a **Configuration Engine**, not a **Data Pipe**. It interprets user intent and generates transformation rules (SQL filters, column mappings), but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly.

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| **Orchestration Agent** | Python 3.12+, Claude Agent SDK, FastAPI |
| **Data Processing** | DuckDB, openpyxl, pydifact (EDI) |
| **UPS Integration** | ups-mcp v2 (18 tools: shipping, tracking, pickup, locator, paperless, landed cost) |
| **Template Engine** | Jinja2 with custom logistics filters |
| **State Database** | SQLite + SQLAlchemy + aiosqlite |
| **Frontend** | React 19, Vite, Tailwind CSS 4, shadcn/ui |
| **CLI** | Typer + Rich + HTTPX |
| **Watchdog** | Hot-folder file monitoring with auto-import |
| **Filter Engine** | sqlglot (SQL transpilation and validation) |

---

## Getting Started

### Prerequisites

- Docker + Docker Compose v2 (recommended path), or
- Python 3.12 or higher
- Node.js 18 or higher (for frontend only)
- UPS Developer Account (for API credentials)

### Quick Start (Docker, Recommended)

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/shipagent.git
   cd shipagent
   ```

2. **Create env file**
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env` and set required credentials**
   - `ANTHROPIC_API_KEY`
   - `UPS_CLIENT_ID`
   - `UPS_CLIENT_SECRET`
   - `UPS_ACCOUNT_NUMBER`
   - `FILTER_TOKEN_SECRET` (required; 64 hex chars recommended)

4. **Start ShipAgent**
   ```bash
   docker compose up -d --build
   ```

5. **Open the app**
   - [http://localhost:8000](http://localhost:8000)

6. **Use CLI from host without pip**
   ```bash
   ./scripts/shipagent version
   ./scripts/shipagent job list
   ```

### Configuration

```bash
# =============================================================================
# Required
# =============================================================================
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
UPS_CLIENT_ID=your_client_id
UPS_CLIENT_SECRET=your_client_secret
UPS_ACCOUNT_NUMBER=your_account_number
FILTER_TOKEN_SECRET=replace-with-64-char-hex-secret   # openssl rand -hex 32

# =============================================================================
# Optional — Orchestration
# =============================================================================
AGENT_MODEL=claude-haiku-4-5-20251001         # Default model; also accepts ANTHROPIC_MODEL

# =============================================================================
# Optional — Batch Tuning
# =============================================================================
BATCH_PREVIEW_MAX_ROWS=50                     # Preview cap (0 = rate all rows)
BATCH_CONCURRENCY=5                           # Concurrent UPS calls

# =============================================================================
# Optional — Database
# =============================================================================
DATABASE_URL=sqlite:////app/data/shipagent.db # Docker default

# =============================================================================
# Optional — Shopify
# =============================================================================
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxx
SHOPIFY_STORE_DOMAIN=mystore.myshopify.com

# =============================================================================
# Optional — Decision Audit Ledger
# =============================================================================
AGENT_AUDIT_ENABLED=true
AGENT_AUDIT_JSONL_PATH=/app/data/agent-decision-log.jsonl
AGENT_AUDIT_RETENTION_DAYS=30
AGENT_AUDIT_MAX_PAYLOAD_BYTES=16384

# =============================================================================
# Optional — API Hardening
# =============================================================================
# SHIPAGENT_API_KEY=your_api_key              # Protect /api/* with X-API-Key
# ALLOWED_ORIGINS=http://localhost:5173        # CORS allowlist
```

### Local Dev (Without Docker)

1. **Set up Python environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

2. **Install frontend dependencies**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

3. **Start backend + frontend**
   ```bash
   ./scripts/start-backend.sh
   cd frontend && npm run dev
   ```
   Open [http://localhost:5173](http://localhost:5173)

### Runtime Policy

- ShipAgent is currently **local-first and single-worker**.
- Use one backend worker (`--workers 1`) while state is process-local.
- Startup warns by default unless you set `SHIPAGENT_ALLOW_MULTI_WORKER=true`.
- Liveness endpoint: `GET /health`
- Readiness endpoint: `GET /readyz`

### Docker Operations

```bash
# Stop/start
docker compose stop
docker compose up -d

# Create backup inside container volume
docker compose exec shipagent /app/scripts/backup.sh

# Restore from backup (run with service stopped, then start)
docker compose run --rm shipagent /app/scripts/restore.sh \
  /app/data/backups/shipagent_YYYYMMDD_HHMMSS.db \
  /app/data/backups/labels_YYYYMMDD_HHMMSS.tar.gz
```

---

## Usage

### Web Interface

1. **Connect a Data Source** — Upload CSV/Excel, enter a database connection string, or connect to Shopify/WooCommerce/SAP/Oracle
2. **Describe Your Shipment** — Type a natural language command
3. **Review the Preview** — See matching shipments, estimated costs, and any warnings
4. **Execute and Track** — Watch real-time SSE progress, download labels as ZIP, tracking numbers auto-written back

### Example Commands

| Command | What it does |
|---------|--------------|
| `Ship all CA orders via Ground` | Filter by state, use UPS Ground |
| `Ship orders from today with Next Day Air` | Filter by date, use express service |
| `Ship unfulfilled Shopify orders` | Pull from Shopify, ship pending |
| `Create shipments for orders over $50` | Filter by order value |
| `Ship this package to 123 Main St, Boston MA 02101` | Single interactive shipment |
| `Schedule a pickup for tomorrow at my warehouse` | Schedule UPS carrier pickup |
| `Track package 1Z999AA10123456784` | Get package tracking status |
| `Upload a commercial invoice for this shipment` | Attach paperless customs document |
| `What are the landed costs for shipping to Canada?` | Get duty/tax estimates |
| `Find the nearest UPS Access Point` | Locate nearby drop-off points |

---

## CLI

ShipAgent includes a full-featured CLI (installed as `shipagent` or via `./scripts/shipagent`):

```bash
# Daemon management
shipagent daemon start [--host 0.0.0.0] [--port 8000]
shipagent daemon stop
shipagent daemon status

# Job management
shipagent job list [--status pending] [--json]
shipagent job inspect <job_id> [--json]
shipagent job rows <job_id> [--json]
shipagent job approve <job_id>
shipagent job cancel <job_id>
shipagent job logs <job_id> [-f]       # -f for live streaming
shipagent job audit <job_id> [-n 200]

# File submission
shipagent submit <file> [-c "Ship all orders"] [--wait] [--auto-confirm]

# Interactive REPL
shipagent interact [--session <id>]

# Configuration
shipagent config show
shipagent config validate [--config path/to/config.yaml]

# Version info
shipagent version
```

---

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| **Conversations** |||
| `POST` | `/api/v1/conversations` | Create a new conversation session |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a message to the agent |
| `GET` | `/api/v1/conversations/{id}/stream` | SSE event stream for real-time updates |
| `GET` | `/api/v1/conversations/{id}/history` | Get conversation message history |
| `POST` | `/api/v1/conversations/{id}/documents` | Upload customs/trade document |
| **Data Sources** |||
| `POST` | `/api/v1/data-sources/upload` | Upload CSV/Excel file |
| `GET` | `/api/v1/data-sources/info` | Get active data source info |
| **Platforms** |||
| `POST` | `/api/v1/platforms/connect` | Connect to external platform |
| `POST` | `/api/v1/platforms/validate` | Validate platform credentials |
| `GET` | `/api/v1/platforms/status` | Get platform connection status |
| **Jobs** |||
| `GET` | `/api/v1/jobs` | List all jobs with pagination |
| `GET` | `/api/v1/jobs/{id}` | Get job details |
| **Preview & Execution** |||
| `GET` | `/api/v1/jobs/{id}/preview` | Get batch preview |
| `POST` | `/api/v1/jobs/{id}/confirm` | Confirm and execute batch |
| **Progress** |||
| `GET` | `/api/v1/jobs/{id}/progress` | Get current progress |
| `GET` | `/api/v1/jobs/{id}/progress/stream` | SSE progress stream |
| **Labels** |||
| `GET` | `/api/v1/jobs/{id}/labels` | List labels for a job |
| `GET` | `/api/v1/jobs/{id}/labels/zip` | Download all labels as ZIP |
| `GET` | `/api/v1/labels/{label_id}` | Download individual label |
| **Saved Sources** |||
| `GET` | `/api/v1/saved-data-sources` | List saved data sources |
| `POST` | `/api/v1/saved-data-sources` | Save a data source for reuse |
| **Audit** |||
| `GET` | `/api/v1/audit/runs` | List agent decision audit runs |
| `GET` | `/api/v1/audit/runs/{id}/events` | Get events for an audit run |
| **Health** |||
| `GET` | `/health` | Liveness check with system metrics |
| `GET` | `/readyz` | Dependency-aware readiness probe |

### MCP Tools

#### Data Source MCP (18+ tools)

| Tool | Description |
|------|-------------|
| `import_csv` | Import data from CSV file |
| `import_excel` | Import data from Excel file |
| `import_database` | Import data from SQL database |
| `import_records` | Import flat dicts (for platform orders) |
| `list_sheets` | List sheets in an Excel workbook |
| `list_tables` | List tables in a database |
| `get_schema` | Get source schema with column types |
| `override_column_type` | Override a column's DuckDB type |
| `get_row` | Get a specific row by number |
| `get_rows_by_filter` | Query rows with SQL WHERE clause |
| `query_data` | Execute arbitrary SQL query |
| `get_column_samples` | Sample distinct values per column |
| `get_source_info` | Get active source metadata + signature |
| `clear_source` | Disconnect active data source |
| `compute_checksums` | Generate SHA-256 for rows |
| `verify_checksum` | Verify row hasn't been modified |
| `import_commodities` | Import commodity data for international |
| `get_commodities_bulk` | Get commodities for multiple orders |
| `import_edi` | Parse EDI 850 purchase orders |

#### External Sources MCP (8 tools)

| Tool | Description |
|------|-------------|
| `connect_platform` | Connect to Shopify/WooCommerce/SAP/Oracle |
| `disconnect_platform` | Disconnect from a platform |
| `list_connections` | List all platform connections |
| `list_orders` | Fetch orders with optional filters |
| `get_order` | Get a single order by ID |
| `get_shop_info` | Get store/shop metadata |
| `validate_credentials` | Validate platform credentials |
| `update_tracking` | Write tracking numbers back to platform |

#### UPS MCP Client (15 methods)

| Method | Description |
|--------|-------------|
| `get_rate()` | Get rate quote (Rate/Shop/Shoptimeintransit modes) |
| `create_shipment()` | Create shipment and generate label |
| `void_shipment()` | Void an existing shipment |
| `validate_address()` | Validate and correct shipping address |
| `track_package()` | Track package by tracking number |
| `schedule_pickup()` | Schedule a UPS carrier pickup |
| `cancel_pickup()` | Cancel a scheduled pickup |
| `rate_pickup()` | Get pickup cost estimate |
| `get_pickup_status()` | Get pending pickup status |
| `get_landed_cost()` | Estimate duties, taxes, and fees |
| `upload_document()` | Upload customs document to Forms History |
| `push_document()` | Attach document to a shipment |
| `delete_document()` | Delete document from Forms History |
| `find_locations()` | Find nearby UPS locations |
| `get_service_center_facilities()` | Find UPS service center drop-offs |

---

## Development

### Common Commands

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/api/test_jobs.py -v

# Integration tests only
pytest -m integration

# Type checking
mypy src/

# Linting and formatting
ruff check src/ tests/
ruff format src/ tests/
```

### Frontend Development

```bash
cd frontend

# Development server with HMR
npm run dev

# Production build
npm run build

# Type check
npm run lint
```

---

## Project Structure

```
shipagent/
├── src/
│   ├── api/                        # FastAPI REST + SSE gateway
│   │   ├── main.py                 # App factory, lifespan, SPA serving
│   │   ├── middleware/             # API key auth middleware
│   │   ├── routes/
│   │   │   ├── conversations.py    # SSE agent conversations
│   │   │   ├── data_sources.py     # File upload, source info
│   │   │   ├── jobs.py             # Job CRUD
│   │   │   ├── labels.py           # Label download + ZIP
│   │   │   ├── logs.py             # Job audit logs
│   │   │   ├── platforms.py        # External platform connect/validate
│   │   │   ├── preview.py          # Batch preview endpoints
│   │   │   ├── progress.py         # SSE progress streaming
│   │   │   ├── saved_data_sources.py # Saved source persistence
│   │   │   └── agent_audit.py      # Decision audit REST API
│   │   ├── schemas.py              # Pydantic request/response models
│   │   └── schemas_conversations.py
│   ├── cli/                        # Typer CLI suite
│   │   ├── main.py                 # Command entry point
│   │   ├── daemon.py               # Daemon start/stop/status
│   │   ├── runner.py               # Job runner logic
│   │   ├── repl.py                 # Interactive REPL
│   │   ├── auto_confirm.py         # Auto-confirm rule engine
│   │   ├── watchdog_service.py     # Hot-folder file monitoring
│   │   ├── http_client.py          # API client for CLI
│   │   ├── config.py               # YAML config parser
│   │   ├── output.py               # Rich console formatting
│   │   └── protocol.py             # API protocol types
│   ├── db/                         # Database layer
│   │   ├── models.py               # SQLAlchemy models
│   │   └── connection.py           # Session + init_db
│   ├── errors/                     # Error handling
│   │   ├── codes.py                # E-XXXX error codes
│   │   └── ups_translator.py       # UPS error mapping
│   ├── services/                   # Business logic
│   │   ├── batch_engine.py         # Batch execution engine
│   │   ├── batch_executor.py       # Concurrent execution pool
│   │   ├── job_service.py          # Job state machine
│   │   ├── audit_service.py        # Audit logging
│   │   ├── decision_audit_service.py # Centralized agent decision audit
│   │   ├── ups_mcp_client.py       # Async UPS MCP client (15 methods)
│   │   ├── ups_payload_builder.py  # UPS payload construction
│   │   ├── ups_service_codes.py    # Canonical UPS service codes
│   │   ├── column_mapping.py       # LLM column mapping
│   │   ├── mapping_cache.py        # Column mapping cache
│   │   ├── international_rules.py  # International shipping rules engine
│   │   ├── data_source_gateway.py  # Data source abstraction
│   │   ├── data_source_mcp_client.py # Async Data Source MCP client
│   │   ├── external_sources_mcp_client.py # External Sources MCP client
│   │   ├── agent_session_manager.py # Agent session lifecycle
│   │   ├── conversation_handler.py # Conversation state
│   │   ├── label_storage.py        # Label persistence + staging
│   │   ├── write_back_utils.py     # Write-back helpers
│   │   ├── write_back_worker.py    # Async write-back worker
│   │   ├── saved_data_source_service.py # Saved source CRUD
│   │   ├── attachment_store.py     # Session-scoped file attachments
│   │   ├── filter_constants.py     # Shipper defaults + env config
│   │   ├── paperless_constants.py  # UPS Paperless file format constants
│   │   └── idempotency.py          # Idempotency key generation
│   ├── mcp/
│   │   ├── data_source/            # Data Source MCP server
│   │   │   ├── server.py           # FastMCP server
│   │   │   ├── adapters/           # CSV, Excel, DB, EDI adapters
│   │   │   ├── tools/              # 18+ MCP tool implementations
│   │   │   │   ├── import_tools.py
│   │   │   │   ├── query_tools.py
│   │   │   │   ├── schema_tools.py
│   │   │   │   ├── checksum_tools.py
│   │   │   │   ├── source_info_tools.py
│   │   │   │   ├── sample_tools.py
│   │   │   │   ├── commodity_tools.py
│   │   │   │   ├── edi_tools.py
│   │   │   │   └── writeback_tools.py
│   │   │   ├── edi/                # EDI 850 parser
│   │   │   └── models.py           # Data source models
│   │   └── external_sources/       # External platform MCP
│   │       ├── server.py           # FastMCP server
│   │       ├── tools.py            # 8 platform tools
│   │       ├── models.py           # Platform connection models
│   │       └── clients/            # Platform API clients
│   │           ├── shopify.py
│   │           ├── woocommerce.py
│   │           ├── sap.py
│   │           └── oracle.py
│   └── orchestrator/               # AI orchestration
│       ├── agent/                  # Claude Agent SDK
│       │   ├── client.py           # Agent client (conversation mgmt)
│       │   ├── config.py           # Agent config + MCP server setup
│       │   ├── hooks.py            # Agent lifecycle hooks
│       │   ├── system_prompt.py    # Dynamic system prompt builder
│       │   ├── intent_detection.py # Shipping intent classification
│       │   └── tools/              # 25+ agent tool handlers
│       │       ├── pipeline.py     # Batch pipeline (ship, confirm, landed cost)
│       │       ├── interactive.py  # Single shipment preview/create
│       │       ├── data.py         # Data source + filter tools
│       │       ├── pickup.py       # Pickup scheduling tools
│       │       ├── documents.py    # Paperless document tools
│       │       ├── tracking.py     # Package tracking
│       │       └── core.py         # Shared tool utilities
│       ├── filter_compiler.py      # SQL filter compilation
│       ├── filter_resolver.py      # Filter resolution pipeline
│       ├── models/                 # Domain models
│       │   ├── intent.py           # FilterIntent, ShippingIntent
│       │   ├── filter.py           # CompiledFilter
│       │   ├── filter_spec.py      # FilterSpec
│       │   ├── mapping.py          # ColumnMapping
│       │   ├── correction.py       # Filter corrections
│       │   └── elicitation.py      # Missing info elicitation
│       ├── batch/                  # Batch execution engine
│       │   ├── events.py           # Batch event types
│       │   ├── models.py           # Batch models
│       │   ├── modes.py            # Execution modes
│       │   ├── recovery.py         # Crash recovery
│       │   └── sse_observer.py     # SSE event observer
│       └── filters/                # Jinja2 logistics filters
├── frontend/                       # React web interface
│   └── src/
│       ├── App.tsx                 # Root component
│       ├── components/
│       │   ├── CommandCenter.tsx    # Main chat + command interface
│       │   ├── JobDetailPanel.tsx   # Job detail side panel
│       │   ├── LabelPreview.tsx     # Shipping label viewer
│       │   ├── RecentSourcesModal.tsx # Saved sources modal
│       │   ├── command-center/     # Chat subcomponents
│       │   ├── sidebar/            # Navigation sidebar
│       │   ├── layout/             # App layout
│       │   └── ui/                 # shadcn/ui components
│       ├── hooks/                  # React hooks (SSE, state, etc.)
│       ├── lib/                    # Utilities
│       └── types/                  # TypeScript types
├── tests/                          # Test suite
│   ├── api/                        # API endpoint tests
│   ├── cli/                        # CLI command tests
│   ├── mcp/                        # MCP tool tests
│   ├── orchestrator/               # Orchestration tests
│   ├── services/                   # Service layer tests
│   ├── integration/                # Integration tests
│   ├── db/                         # Database tests
│   ├── errors/                     # Error handling tests
│   ├── helpers/                    # Test utilities + MCP test client
│   └── fixtures/                   # Test fixtures
├── scripts/
│   ├── shipagent                   # CLI wrapper for Docker host
│   ├── start-backend.sh            # Local backend startup
│   ├── restart.sh                  # Restart script
│   ├── backup.sh                   # Database backup
│   └── restore.sh                  # Database restore
├── docs/                           # Documentation
├── Dockerfile                      # Production container
├── docker-compose.yml              # Development compose
├── docker-compose.prod.yml         # Production compose
└── pyproject.toml                  # Python project metadata
```

---

## Error Codes

ShipAgent uses structured error codes for debugging:

| Range | Category |
|-------|----------|
| `E-1xxx` | Data errors (import, schema, validation) |
| `E-2xxx` | Validation errors (address, weight, dimensions) |
| `E-3xxx` | UPS API errors (rate, ship, auth) |
| `E-4xxx` | System errors (database, MCP, timeout) |
| `E-5xxx` | Authentication errors (API keys, OAuth) |

---

## Conventions

- **Currency**: All costs stored as integers in cents
- **Timestamps**: ISO8601 strings for SQLite compatibility
- **API Versioning**: All endpoints use `/api/v1/` prefix
- **Enums**: Inherit from both `str` and `Enum` for JSON serialization
- **Row Identity**: `_source_row_num` column tracks row provenance across adapters
- **Filter Security**: Deterministic filters use HMAC-signed tokens for confirmation
- **International Rules**: Lane-based requirement sets versioned with effective dates

---

## Extending ShipAgent

### Adding a Data Adapter

Implement the `BaseSourceAdapter` interface:

```python
class MyAdapter(BaseSourceAdapter):
    async def read(self, config: dict) -> DataFrame: ...
    async def write_back(self, row_id: str, data: dict) -> bool: ...
    async def get_metadata(self) -> SourceMetadata: ...
```

### Adding an External Platform Client

Follow the `BaseExternalClient` pattern:

```python
class MyPlatformClient(BaseExternalClient):
    async def authenticate(self, credentials: dict) -> bool: ...
    async def list_orders(self, status=None, limit=100, offset=0) -> list[dict]: ...
    async def get_order(self, order_id: str) -> dict: ...
    async def update_tracking(self, order_id: str, tracking: str, carrier: str) -> bool: ...
```

### Adding a Carrier Service

Follow the UPSMCPClient pattern:
1. Create an async MCP client wrapping the carrier's API
2. Implement `rate_shipment()`, `create_shipment()`, `void_shipment()`, `validate_address()`
3. Handle OAuth/authentication
4. Return standardized response format with error translation

---

## Roadmap

- [x] Phase 1: Core Infrastructure (API, Database, Errors)
- [x] Phase 2: Data Source MCP (CSV, Excel, Database)
- [x] Phase 3: UPS MCP Integration (Ship, Rate, Validate)
- [x] Phase 4: NL Engine (Intent Parsing, Filter Compilation, Column Mapping)
- [x] Phase 5: Agent Orchestration (Claude Agent SDK, 25+ Tools)
- [x] Phase 6: Batch Execution Engine (Preview, Confirm, Recovery)
- [x] Phase 7: Web Interface (React, SSE Streaming, Label Preview)
- [x] Phase 8: CLI Suite (Daemon, Job Control, REPL, Watchdog)
- [x] Phase 9: External Platforms (Shopify, WooCommerce, SAP, Oracle)
- [x] Phase 10: International Shipping (Rules Engine, Commodities, Paperless)
- [x] Phase 11: UPS Extended APIs (Pickup, Tracking, Locator, Landed Cost)
- [x] Phase 12: Decision Audit Ledger

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please ensure:
- All tests pass (`pytest`)
- Code is formatted (`ruff format`)
- No linting errors (`ruff check`)
- Type hints are included

---

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [Anthropic Claude](https://www.anthropic.com/) — AI orchestration via Agent SDK
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP specification
- [UPS Developer Kit](https://developer.ups.com/) — Shipping APIs
- [FastAPI](https://fastapi.tiangolo.com/) — API framework
- [DuckDB](https://duckdb.org/) — In-process SQL engine
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Typer](https://typer.tiangolo.com/) — CLI framework
- [shadcn/ui](https://ui.shadcn.com/) — UI component library
