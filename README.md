# ShipAgent

**AI-Powered Natural Language Shipping Automation**

ShipAgent is an AI-powered shipping platform that lets you describe shipments in plain English and handles the rest — from single-package ad-hoc shipments to batch processing hundreds of orders. Simply say *"Ship all California orders from today's spreadsheet using UPS Ground"* and ShipAgent parses your intent, extracts data, validates against carrier schemas, and executes shipments with full audit trails.

Available as a native desktop app (macOS/Windows/Linux) or Docker deployment.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Angular 21](https://img.shields.io/badge/angular-21-red.svg)](https://angular.dev/)
[![Tauri v2](https://img.shields.io/badge/tauri-v2-blue.svg)](https://v2.tauri.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

---

## Features

### Core Shipping
- **Natural Language Commands** — Describe what you want to ship in plain English
- **Batch Processing** — Process hundreds of shipments with per-row audit logging
- **Single Shipment Mode** — Interactive one-off shipment creation with real-time preview
- **Preview & Confirm** — Review cost estimates and shipment details before execution
- **Crash Recovery** — Resume interrupted batches from exactly where they stopped

### Desktop App
- **Native Desktop** — Tauri v2 desktop app for macOS
- **Auto-Updater** — Ed25519-signed updates via GitHub Releases
- **Onboarding Wizard** — 3-step setup: Anthropic API key, UPS credentials, shipper address
- **Settings Flyout** — Connections, shipment behavior, address book, custom commands

### Data Sources
- **CSV & Excel** — Upload flat files with automatic sheet detection
- **JSON** — Flat arrays and nested structures with 50MB guard
- **XML** — XXE-safe parsing via defusedxml
- **Fixed-Width** — Auto-sniff column positions from sample data
- **SQL Databases** — Connect to PostgreSQL/MySQL via connection string
- **EDI 850** — Parse ANSI X12 and EDIFACT purchase orders
- **Shopify** — Pull unfulfilled orders directly from your store
- **WooCommerce** — Connect to WooCommerce REST API
- **SAP Business One** — Fetch sales orders from SAP B1 Service Layer
- **Oracle** — Query Oracle Fusion Cloud/ERP order data

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

### Address Book
- **Contact Management** — Create, search, and manage shipping contacts
- **@Handle Resolution** — Use `@acme` in natural language commands to auto-fill recipient details
- **MRU Contacts** — Most-recently-used contacts for quick access

### Chat & Conversations
- **Persistent Chat Sessions** — DB-backed conversation history with session sidebar
- **Auto-Generated Titles** — Session titles from first user message
- **Custom Slash Commands** — User-defined `/command` shortcuts
- **Export** — Download conversation history as JSON
- **Merged PDF Labels** — All labels for a job combined into a single PDF

### Security
- **Credential Storage** — System keychain integration (macOS Keychain / Linux Secret Service)
- **Encrypted Connections** — AES-256-GCM encrypted provider credentials in database
- **API Key Auth** — Optional `X-API-Key` protection for all `/api/*` endpoints
- **Rate Limiting** — Auth failure rate limiting (10 failures per 5-minute window per IP)
- **Key Strength Validation** — Minimum 32-character API key enforcement
- **Error Sanitization** — Internal error details stripped from API responses

---

## Architecture

ShipAgent uses the **Model Context Protocol (MCP)** to separate concerns into independent servers exposed through a canonical workflow/tool backbone and provider runtime adapters.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Desktop App (Tauri v2)                              │
│                    OR Browser UI (Angular 21 + Nx + Native Federation)      │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     FastAPI REST + SSE Gateway                              │
│     (Conversations, Jobs, Preview, Progress, Labels, Platforms,            │
│      Settings, Contacts, Commands, Connections)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Orchestration Agent                                   │
│         (Python workflow services + Claude SDK adapter + canonical tools)   │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐    │
│  │ Pipeline  │ │Interactive│ │  Pickup   │ │  Docs /   │ │ Tracking  │    │
│  │ (Batch)   │ │ (Single)  │ │ Schedule  │ │ Paperless │ │           │    │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘    │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐   │
│  │ Filter    │ │  Column   │ │ Int'l     │ │ Contacts  │ │  Data     │   │
│  │ Compiler  │ │  Mapping  │ │ Rules     │ │ @handle   │ │  Sources  │   │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
     │                    │                    │                    │
     ▼                    ▼                    ▼                    ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ Data Source   │  │ External     │  │ UPS MCP      │  │ State Database   │
│ MCP Server   │  │ Sources MCP  │  │ Client       │  │ (SQLite)         │
│ (FastMCP)    │  │ (FastMCP)    │  │ (stdio)      │  │                  │
│              │  │              │  │              │  │ • Job state      │
│ • CSV/Excel  │  │ • Shopify    │  │ • Ship/Rate  │  │ • Audit logs     │
│ • JSON/XML   │  │ • WooCommerce│  │ • Track      │  │ • Decision audit │
│ • Fixed-Width│  │ • SAP B1     │  │ • Pickup     │  │ • Conversations  │
│ • Database   │  │ • Oracle     │  │ • Paperless  │  │ • Contacts       │
│ • EDI 850    │  │              │  │ • Locator    │  │ • Connections    │
│ • Commodities│  │              │  │ • Landed Cost│  │ • Settings       │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘
     │                    │                │
     ▼                    ▼                ▼
┌──────────┐     ┌───────────────┐   ┌──────────────┐
│  DuckDB  │     │ Platform APIs │   │  UPS API     │
└──────────┘     └───────────────┘   │  (OAuth 2.0) │
                                     └──────────────┘
```

### Core Design Principle

The LLM acts as a **Configuration Engine**, not a **Data Pipe**. It interprets user intent and generates transformation rules (SQL filters, column mappings), but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly.

### Provider Portability Direction

ShipAgent is moving toward a canonical workflow/tool registry. Public app-store surfaces such as OpenAI Apps SDK, Anthropic Connectors/MCPB, Microsoft Copilot plugins, Gemini function declarations, and generic MCP clients should be generated from that registry. Desktop/Tauri remains a local/private deployment path, but most hosted app-store users should not need to install the desktop app.

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| **Desktop App** | Tauri v2 (Rust), tauri-plugin-shell, tauri-plugin-updater (Ed25519) |
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy, SQLite |
| **Bundling** | PyInstaller (one-folder), `bundle_entry.py` subcommand dispatch |
| **Runtime Adapter** | Claude Agent SDK adapter, Anthropic API, extensible provider adapters |
| **MCP Protocol** | FastMCP v2 (servers), `mcp` (stdio clients) |
| **Credentials** | `keyring` (macOS Keychain / Linux Secret Service), `cryptography` (AES-256-GCM) |
| **Data Processing** | DuckDB, openpyxl, xmltodict, defusedxml, pydifact (EDI) |
| **UPS Integration** | ups-mcp v2 (18 tools: shipping, tracking, pickup, locator, paperless, landed cost) |
| **Template Engine** | Jinja2 with custom logistics filters |
| **Frontend** | Angular 21, Nx, Native Federation, NgRx SignalStores |
| **CLI** | Typer + Rich + HTTPX |
| **Filter Engine** | sqlglot (SQL transpilation and validation) |
| **PDF** | pypdf (merging), ng2-pdf-viewer (browser rendering) |

---

## Getting Started

### Prerequisites

- **Desktop App**: Download from [Releases](https://github.com/yourusername/shipagent/releases) (no dependencies needed), or
- **Docker**: Docker + Docker Compose v2, or
- **Local Dev**: Python 3.12+, Node.js 18+ (for frontend)
- UPS Developer Account (for API credentials)

### Desktop App (Recommended)

1. Download the latest release for your platform
2. Launch ShipAgent — the onboarding wizard guides you through setup:
   - Step 1: Enter your Anthropic API key
   - Step 2: Enter UPS credentials (optional, can configure later)
   - Step 3: Set shipper address (optional, can configure later)
3. Start shipping

### Quick Start (Docker)

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
# SHIPAGENT_API_KEY=your_api_key              # Protect /api/* with X-API-Key (min 32 chars)
# ALLOWED_ORIGINS=http://localhost:4200        # CORS allowlist
# SHIPAGENT_TRUST_PROXY=true                  # Trust X-Forwarded-For header

# =============================================================================
# Optional — Credential Encryption
# =============================================================================
# SHIPAGENT_CREDENTIAL_KEY=base64-encoded-key # AES-256-GCM key for provider credentials
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
   cd shipagent-frontend
   npm install
   cd ..
   ```

3. **Start backend + frontend**
   ```bash
   ./scripts/start-backend.sh
   cd shipagent-frontend && npx nx serve shell
   ```
   Open [http://localhost:4200](http://localhost:4200)

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

1. **Connect a Data Source** — Upload CSV/Excel/JSON/XML, enter a database connection string, or connect to Shopify/WooCommerce/SAP/Oracle
2. **Describe Your Shipment** — Type a natural language command (use `@handles` for saved contacts)
3. **Review the Preview** — See matching shipments, estimated costs, and any warnings
4. **Execute and Track** — Watch real-time SSE progress, download labels as ZIP or merged PDF, tracking numbers auto-written back

### Example Commands

| Command | What it does |
|---------|--------------|
| `Ship all CA orders via Ground` | Filter by state, use UPS Ground |
| `Ship orders from today with Next Day Air` | Filter by date, use express service |
| `Ship unfulfilled Shopify orders` | Pull from Shopify, ship pending |
| `Create shipments for orders over $50` | Filter by order value |
| `Ship this package to @acme` | Single shipment using saved contact |
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
| `GET` | `/api/v1/conversations` | List conversation sessions (paginated) |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a message to the agent |
| `GET` | `/api/v1/conversations/{id}/messages` | Get conversation message history |
| `GET` | `/api/v1/conversations/{id}/stream` | SSE event stream for real-time updates |
| `PATCH` | `/api/v1/conversations/{id}` | Rename a conversation session |
| `DELETE` | `/api/v1/conversations/{id}` | Delete a conversation session |
| `GET` | `/api/v1/conversations/{id}/export` | Export conversation as JSON |
| `POST` | `/api/v1/conversations/{id}/documents` | Upload customs/trade document |
| **Data Sources** |||
| `POST` | `/api/v1/data-sources/upload` | Upload CSV/Excel/JSON/XML file |
| `POST` | `/api/v1/data-sources/import` | Import from connection string |
| `GET` | `/api/v1/data-sources/status` | Get active data source info |
| `POST` | `/api/v1/data-sources/disconnect` | Disconnect active data source |
| **Platforms** |||
| `POST` | `/api/v1/platforms/{platform}/connect` | Connect to external platform |
| `GET` | `/api/v1/platforms/shopify/env-status` | Auto-reconnect Shopify after restart |
| `GET` | `/api/v1/platforms/{platform}/orders` | Fetch platform orders |
| **Jobs** |||
| `GET` | `/api/v1/jobs` | List all jobs with pagination |
| `GET` | `/api/v1/jobs/{id}` | Get job details |
| `PATCH` | `/api/v1/jobs/{id}/status` | Update job status |
| **Preview & Execution** |||
| `GET` | `/api/v1/jobs/{id}/preview` | Get batch preview |
| `POST` | `/api/v1/jobs/{id}/confirm` | Confirm and execute batch |
| **Progress** |||
| `GET` | `/api/v1/jobs/{id}/progress` | Get current progress |
| `GET` | `/api/v1/jobs/{id}/progress/stream` | SSE progress stream |
| **Labels** |||
| `GET` | `/api/v1/jobs/{id}/labels` | List labels for a job |
| `GET` | `/api/v1/jobs/{id}/labels/zip` | Download all labels as ZIP |
| `GET` | `/api/v1/jobs/{id}/labels/merged` | Download all labels as merged PDF |
| `GET` | `/api/v1/labels/{tracking}` | Download individual label |
| **Saved Sources** |||
| `GET` | `/api/v1/saved-sources` | List saved data sources |
| `POST` | `/api/v1/saved-sources/reconnect` | Reconnect a saved source |
| `DELETE` | `/api/v1/saved-sources/{id}` | Delete a saved source |
| **Connections** |||
| `GET` | `/api/v1/connections` | List provider connections |
| `POST` | `/api/v1/connections/{provider}/save` | Save encrypted provider credentials |
| `POST` | `/api/v1/connections/{key}/validate` | Validate connection (live API call) |
| `POST` | `/api/v1/connections/{key}/disconnect` | Disconnect a provider |
| `DELETE` | `/api/v1/connections/{key}` | Delete stored connection |
| **Settings** |||
| `GET` | `/api/v1/settings` | Get application settings |
| `PATCH` | `/api/v1/settings` | Update settings (partial) |
| `GET` | `/api/v1/settings/credentials/status` | Get credential status (keyring probe) |
| `POST` | `/api/v1/settings/credentials` | Store credential in system keychain |
| `POST` | `/api/v1/settings/onboarding/complete` | Mark onboarding as complete |
| **Contacts** |||
| `GET` | `/api/v1/contacts` | List all contacts |
| `POST` | `/api/v1/contacts` | Create a contact |
| `PATCH` | `/api/v1/contacts/{id}` | Update a contact |
| `DELETE` | `/api/v1/contacts/{id}` | Delete a contact |
| `GET` | `/api/v1/contacts/by-handle/{handle}` | Look up contact by @handle |
| **Commands** |||
| `GET` | `/api/v1/commands` | List custom slash commands |
| `POST` | `/api/v1/commands` | Create a custom command |
| `PATCH` | `/api/v1/commands/{id}` | Update a custom command |
| `DELETE` | `/api/v1/commands/{id}` | Delete a custom command |
| **Audit** |||
| `GET` | `/api/v1/agent-audit/runs` | List agent decision audit runs |
| `GET` | `/api/v1/agent-audit/runs/{id}` | Get audit run details |
| `GET` | `/api/v1/agent-audit/runs/{id}/events` | Get events for an audit run |
| `GET` | `/api/v1/agent-audit/runs/{id}/timeline` | Get audit run timeline |
| `GET` | `/api/v1/agent-audit/export` | Export audit data |
| `DELETE` | `/api/v1/agent-audit/runs` | Prune old audit runs |
| **Health** |||
| `GET` | `/health` | Liveness check with system metrics |
| `GET` | `/readyz` | Dependency-aware readiness probe |

### MCP Tools

#### Data Source MCP (20+ tools)

| Tool | Description |
|------|-------------|
| `import_file` | Universal format router (CSV, Excel, JSON, XML, fixed-width) |
| `import_csv` | Import data from CSV file |
| `import_excel` | Import data from Excel file |
| `import_database` | Import data from SQL database |
| `import_records` | Import flat dicts (for platform orders) |
| `sniff_file` | Peek at a file to infer fixed-width column positions |
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
# Run all tests (~2800 across 200+ files)
pytest

# Skip known hanging tests
pytest -k "not test_stream_endpoint_exists"

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
cd shipagent-frontend

# Development server with HMR
npx nx serve shell

# Production build
npx nx run-many -t build --all --configuration=production

# Type check
npx nx run-many -t typecheck --all
```

### Build & Packaging

```bash
# Bundle Python backend (PyInstaller one-folder build)
./scripts/bundle_backend.sh

# Build Tauri desktop app (requires bundled backend)
cd src-tauri && cargo tauri build

# Dev mode (Tauri + hot-reload)
cargo tauri dev

# Sync versions across pyproject.toml, tauri.conf.json, package.json
./scripts/bump-version.sh 1.2.3

# Generate Ed25519 updater keypair
./scripts/generate-updater-key.sh
```

---

## Project Structure

```
shipagent/
├── src/
│   ├── api/                        # FastAPI REST + SSE gateway
│   │   ├── main.py                 # App factory, lifespan, SPA serving
│   │   ├── middleware/             # API key auth + rate limiting middleware
│   │   ├── routes/
│   │   │   ├── conversations.py    # SSE agent conversations + chat persistence
│   │   │   ├── data_sources.py     # File upload, import, disconnect, schema
│   │   │   ├── jobs.py             # Job CRUD + status
│   │   │   ├── labels.py           # Label download (individual, merged PDF, ZIP)
│   │   │   ├── logs.py             # Job audit logs
│   │   │   ├── platforms.py        # External platform connect/validate
│   │   │   ├── preview.py          # Batch preview + confirm
│   │   │   ├── progress.py         # SSE progress streaming
│   │   │   ├── saved_data_sources.py # Saved source persistence
│   │   │   ├── agent_audit.py      # Decision audit REST API
│   │   │   ├── settings.py         # Settings + credentials + onboarding
│   │   │   ├── contacts.py         # Address book CRUD + @handle lookup
│   │   │   ├── commands.py         # Custom slash commands CRUD
│   │   │   └── connections.py      # Provider connection management
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
│   │   ├── models.py               # SQLAlchemy models (Job, JobRow, AuditLog, Contact,
│   │   │                           #   ProviderConnection, CustomCommand, ConversationSession,
│   │   │                           #   ConversationMessage, AppSettings, SavedDataSource)
│   │   └── connection.py           # Session + init_db
│   ├── errors/                     # Error handling
│   │   ├── registry.py             # E-XXXX error code registry
│   │   ├── ups_translation.py      # UPS error mapping
│   │   └── formatter.py            # Error message formatting
│   ├── services/                   # Business logic
│   │   ├── ups_constants.py        # Canonical UPS field limits, packaging codes, defaults
│   │   ├── ups_service_codes.py    # Canonical ServiceCode enum + aliases
│   │   ├── international_rules.py  # Lane-driven compliance rules
│   │   ├── batch_engine.py         # Batch execution engine (concurrent preview + execute)
│   │   ├── batch_executor.py       # Concurrent execution pool
│   │   ├── job_service.py          # Job state machine
│   │   ├── audit_service.py        # Audit logging with redaction
│   │   ├── decision_audit_service.py # Agent decision audit ledger
│   │   ├── ups_mcp_client.py       # Async UPS MCP client (15 methods)
│   │   ├── ups_payload_builder.py  # UPS payload construction from canonical constants
│   │   ├── column_mapping.py       # LLM column mapping
│   │   ├── data_source_gateway.py  # Data source abstraction
│   │   ├── data_source_mcp_client.py # Async Data Source MCP client
│   │   ├── external_sources_mcp_client.py # External Sources MCP client
│   │   ├── gateway_provider.py     # Centralized singleton factory for MCP clients
│   │   ├── agent_session_manager.py # Per-conversation agent session lifecycle
│   │   ├── conversation_handler.py # Conversation handling
│   │   ├── conversation_persistence_service.py # DB-backed session/message CRUD
│   │   ├── label_storage.py        # Label persistence + staging
│   │   ├── write_back_utils.py     # Atomic CSV/Excel write-back
│   │   ├── saved_data_source_service.py # Saved source CRUD
│   │   ├── keyring_store.py        # System keychain wrapper (macOS Keychain)
│   │   ├── settings_service.py     # AppSettings DB singleton CRUD
│   │   ├── contact_service.py      # Contact (address book) CRUD + @handle resolution
│   │   ├── custom_command_service.py # Custom slash commands CRUD
│   │   ├── credential_encryption.py # AES-256-GCM provider credential encryption
│   │   ├── connection_service.py   # Provider connection management
│   │   └── connection_types.py     # Provider credential types + allowlists
│   ├── utils/                      # Cross-cutting utilities
│   │   ├── paths.py                # Production file path resolver (platformdirs)
│   │   ├── runtime.py              # Bundle detection: is_bundled(), get_resource_dir()
│   │   └── redaction.py            # Error message sanitization
│   ├── bundle_entry.py             # PyInstaller entry point (serve/mcp-data/mcp-ups/cli)
│   ├── mcp/
│   │   ├── data_source/            # Data Source MCP server
│   │   │   ├── server.py           # FastMCP server
│   │   │   ├── adapters/           # CSV, Excel, JSON, XML, Fixed-Width, DB, EDI adapters
│   │   │   ├── tools/              # 20+ MCP tool implementations
│   │   │   ├── utils.py            # flatten_record, type inference, DuckDB loading
│   │   │   ├── edi/                # X12 + EDIFACT parsers
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
│       │   ├── client.py           # OrchestrationAgent (conversation mgmt)
│       │   ├── config.py           # Agent config + MCP server setup
│       │   ├── hooks.py            # Pre/PostToolUse validation hooks
│       │   ├── system_prompt.py    # Dynamic system prompt builder
│       │   └── tools/              # 30+ agent tool handlers
│       │       ├── core.py         # EventEmitterBridge, helpers
│       │       ├── data.py         # Data source + filter tools
│       │       ├── pipeline.py     # Batch pipeline (ship, confirm, landed cost)
│       │       ├── interactive.py  # Single shipment preview/create
│       │       ├── pickup.py       # Pickup + locator tools
│       │       ├── documents.py    # Paperless document tools
│       │       ├── tracking.py     # Package tracking
│       │       └── contacts.py     # Address book tools (@handle resolution)
│       ├── filter_compiler.py      # SQL filter compilation
│       ├── filter_resolver.py      # Filter resolution pipeline
│       ├── models/                 # Domain models
│       ├── batch/                  # Batch orchestration (events, recovery, SSE)
│       └── filters/                # Jinja2 logistics filters
├── shipagent-frontend/             # Angular 21 + Nx + Native Federation workspace
│   ├── apps/
│   │   ├── shell/                  # Host app, layout, header, Tauri update checks
│   │   ├── chat-remote/            # Chat UI, previews, progress, completion artifacts
│   │   ├── sidebar-remote/         # Data sources, job history, chat sessions
│   │   ├── settings-remote/        # Onboarding, settings, connections, address book
│   │   └── domain-remote/          # Pickup, tracking, paperless, landed cost cards
│   ├── libs/
│   │   ├── shared/api/             # HttpClient API service
│   │   ├── shared/sse/             # EventSource wrapper with NgZone integration
│   │   ├── shared/state/           # NgRx SignalStores
│   │   ├── shared/types/           # TypeScript interfaces
│   │   └── shared/ui/              # Angular UI components, icons, pipes, directives
│   ├── federation.manifest.json    # Native Federation remote URLs
│   ├── nx.json                     # Nx workspace config
│   └── package.json                # Frontend scripts and dependencies
├── src-tauri/                      # Tauri v2 desktop wrapper (Rust)
│   ├── src/main.rs                 # Sidecar lifecycle (spawn, port discovery, timeout)
│   ├── tauri.conf.json             # Bundle config, CSP, auto-updater (Ed25519)
│   ├── Cargo.toml                  # Rust deps (tauri v2, shell plugin, updater plugin)
│   ├── entitlements.plist          # macOS code-signing entitlements
│   └── capabilities/              # Tauri permission grants
├── tests/                          # Test suite (~2800 tests across 200+ files)
│   ├── api/                        # API endpoint tests
│   ├── cli/                        # CLI command tests
│   ├── mcp/                        # MCP tool tests
│   ├── orchestrator/               # Orchestration tests
│   ├── services/                   # Service layer tests
│   ├── integration/                # Integration tests
│   ├── db/                         # Database tests
│   ├── errors/                     # Error handling tests
│   ├── unit/                       # Unit tests
│   ├── helpers/                    # Test utilities + MCP test client
│   └── fixtures/                   # Test fixtures
├── scripts/
│   ├── shipagent                   # CLI wrapper for Docker host
│   ├── start-backend.sh            # Local backend startup
│   ├── restart.sh                  # Restart script
│   ├── backup.sh                   # Database backup
│   ├── restore.sh                  # Database restore
│   ├── bundle_backend.sh           # PyInstaller build + smoke test
│   ├── bump-version.sh             # Sync version across all manifests
│   └── generate-updater-key.sh     # Ed25519 updater keypair generation
├── docs/                           # Documentation
├── Dockerfile                      # Production container
├── docker-compose.yml              # Development compose
├── docker-compose.prod.yml         # Production compose
├── shipagent-core.spec             # PyInstaller spec file
└── pyproject.toml                  # Python project metadata
```

---

## Error Codes

ShipAgent uses structured error codes for debugging:

| Range | Category |
|-------|----------|
| `E-1xxx` | Data errors (import, schema, validation) |
| `E-2xxx` | Validation errors (address, weight, dimensions, MCP elicitation) |
| `E-3xxx` | UPS API errors (rate, ship, auth, paperless, pickup, locator) |
| `E-4xxx` | System errors (database, MCP, timeout, user cancellation, safety gates) |
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
- **Credentials**: System keychain for API keys; AES-256-GCM for provider connection details

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
1. Create `<carrier>_constants.py` + `<carrier>_service_codes.py` in `src/services/`
2. Build an MCP server (stdio) wrapping the carrier's API
3. Implement `rate_shipment()`, `create_shipment()`, `void_shipment()`, `validate_address()`
4. Handle OAuth/authentication
5. Return standardized response format with error translation

---

## Roadmap

- [x] Phase 1: Core Infrastructure (API, Database, Errors)
- [x] Phase 2: Data Source MCP (CSV, Excel, Database)
- [x] Phase 3: UPS MCP Integration (Ship, Rate, Validate)
- [x] Phase 4: NL Engine (Intent Parsing, Filter Compilation, Column Mapping)
- [x] Phase 5: Agent Orchestration (Claude Agent SDK, 25+ Tools)
- [x] Phase 6: Batch Execution Engine (Preview, Confirm, Recovery)
- [x] Phase 7: Web Interface (SSE Streaming, Label Preview)
- [x] Phase 8: CLI Suite (Daemon, Job Control, REPL, Watchdog)
- [x] Phase 9: External Platforms (Shopify, WooCommerce, SAP, Oracle)
- [x] Phase 10: International Shipping (Rules Engine, Commodities, Paperless)
- [x] Phase 11: UPS Extended APIs (Pickup, Tracking, Locator, Landed Cost)
- [x] Phase 12: Decision Audit Ledger
- [x] Phase 13: Chat Persistence & Universal Data Ingestion (JSON, XML, Fixed-Width)
- [x] Phase 14: Address Book, Custom Commands, Settings UI
- [x] Phase 15: Production Packaging (Tauri v2, PyInstaller, Keyring, Onboarding, Auto-Updater)
- [x] Phase 16: Connection Management & Security Hardening

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

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [Anthropic Claude](https://www.anthropic.com/) — AI orchestration via Agent SDK
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP specification
- [UPS Developer Kit](https://developer.ups.com/) — Shipping APIs
- [Tauri](https://v2.tauri.app/) — Desktop app framework
- [FastAPI](https://fastapi.tiangolo.com/) — API framework
- [DuckDB](https://duckdb.org/) — In-process SQL engine
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Typer](https://typer.tiangolo.com/) — CLI framework
- [shadcn/ui](https://ui.shadcn.com/) — UI component library
