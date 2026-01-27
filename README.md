# ShipAgent

**Natural Language Batch Shipment Processing**

ShipAgent is an AI-powered shipping automation platform that lets you describe shipments in plain English and handles the rest. Simply say *"Ship all California orders from today's spreadsheet using UPS Ground"* and ShipAgent parses your intent, extracts data, validates against carrier schemas, and executes shipments with full audit trails.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![TypeScript](https://img.shields.io/badge/typescript-5.x-blue.svg)](https://www.typescriptlang.org/)
[![React 19](https://img.shields.io/badge/react-19-blue.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Features

- **Natural Language Commands** - Describe what you want to ship in plain English
- **Multiple Data Sources** - Import from CSV, Excel (.xlsx), PostgreSQL/MySQL databases, or Shopify
- **UPS Integration** - Full API coverage for shipping, rating, and address validation
- **Batch Processing** - Process hundreds of shipments with per-row audit logging
- **Self-Correction** - LLM automatically fixes validation errors in mapping templates
- **Preview Mode** - Review cost estimates and shipment details before execution
- **Crash Recovery** - Resume interrupted batches from exactly where they stopped
- **Write-Back** - Automatically update tracking numbers in your source data

---

## Architecture

ShipAgent uses the **Model Context Protocol (MCP)** to separate concerns into independent servers orchestrated by a Claude Agent SDK-powered coordinator.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Browser UI                                      │
│                         (React + Vite + Tailwind)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Orchestration Agent                                  │
│              (Python + Claude Agent SDK + FastAPI + Jinja2)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ NL Parser   │  │ Filter Gen  │  │ Mapping Gen │  │ Validator   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
          │                                │                        │
          ▼                                ▼                        ▼
┌──────────────────┐         ┌──────────────────┐        ┌──────────────────┐
│  Data Source MCP │         │   UPS MCP        │        │  State Database  │
│  (Python/FastMCP)│         │  (TypeScript)    │        │    (SQLite)      │
│                  │         │                  │        │                  │
│  • CSV/Excel     │         │  • Shipping      │        │  • Job state     │
│  • Database      │         │  • Rating        │        │  • Audit logs    │
│  • Shopify       │         │  • Address       │        │  • Recovery      │
└──────────────────┘         └──────────────────┘        └──────────────────┘
          │                            │
          ▼                            ▼
    ┌──────────┐               ┌──────────────┐
    │  DuckDB  │               │   UPS API    │
    └──────────┘               │   (OAuth)    │
                               └──────────────┘
```

### Core Design Principle

The LLM acts as a **Configuration Engine**, not a **Data Pipe**. It interprets user intent and generates transformation rules (SQL filters, Jinja2 templates), but deterministic code executes those rules on actual shipping data. The LLM never touches row data directly.

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| **Orchestration Agent** | Python 3.11+, Claude Agent SDK, FastAPI |
| **Data Processing** | DuckDB, Pandas, openpyxl |
| **Template Engine** | Jinja2 with custom logistics filters |
| **UPS MCP** | TypeScript 5.x, Zod (schema validation) |
| **State Database** | SQLite + SQLAlchemy |
| **Frontend** | React 19, Vite, Tailwind CSS 4, shadcn/ui |

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher
- pnpm (for UPS MCP package)
- UPS Developer Account (for API credentials)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/shipagent.git
   cd shipagent
   ```

2. **Set up Python environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. **Build the UPS MCP server**
   ```bash
   cd packages/ups-mcp
   pnpm install
   pnpm build
   cd ../..
   ```

4. **Install frontend dependencies**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

### Configuration

Create a `.env` file in the project root:

```bash
# Anthropic API (required)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx

# UPS API Credentials (required for shipping)
UPS_CLIENT_ID=your_client_id
UPS_CLIENT_SECRET=your_client_secret
UPS_ACCOUNT_NUMBER=your_account_number

# UPS Environment (sandbox or production)
UPS_ENVIRONMENT=sandbox

# Shopify Integration (optional)
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxx
SHOPIFY_STORE_DOMAIN=mystore.myshopify.com

# Database (optional, defaults to SQLite)
DATABASE_URL=sqlite:///./shipagent.db
```

### Running the Application

1. **Start the backend API server**
   ```bash
   uvicorn src.api.main:app --reload --port 8000
   ```

2. **Start the frontend development server**
   ```bash
   cd frontend
   npm run dev
   ```

3. **Open your browser** at http://localhost:5173

---

## Usage

### Basic Workflow

1. **Connect a Data Source**
   - Upload a CSV/Excel file, or
   - Enter a database connection string, or
   - Connect your Shopify store

2. **Describe Your Shipment**
   ```
   Ship all orders from California using UPS Ground
   ```
   ```
   Ship pending orders over $100 with 2nd Day Air
   ```
   ```
   Create shipments for today's orders to zip codes starting with 90
   ```

3. **Review the Preview**
   - See matching rows, estimated costs, and any warnings
   - Approve or modify before execution

4. **Execute and Track**
   - Watch real-time progress
   - Download labels as ZIP
   - Tracking numbers automatically written back to source

### Example Commands

| Command | What it does |
|---------|--------------|
| `Ship all CA orders via Ground` | Filter by state, use UPS Ground |
| `Ship orders from today with Next Day Air` | Filter by date, use express |
| `Ship unfulfilled Shopify orders` | Pull from Shopify, ship pending |
| `Create shipments for orders over $50` | Filter by order value |

---

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/commands` | Submit a natural language command |
| `GET` | `/api/v1/jobs` | List all jobs with pagination |
| `GET` | `/api/v1/jobs/{id}` | Get job details |
| `GET` | `/api/v1/jobs/{id}/preview` | Get batch preview |
| `POST` | `/api/v1/jobs/{id}/confirm` | Confirm and execute batch |
| `GET` | `/api/v1/jobs/{id}/progress` | Get current progress |
| `GET` | `/api/v1/jobs/{id}/progress/stream` | SSE progress stream |
| `GET` | `/api/v1/jobs/{id}/labels/zip` | Download all labels |

### MCP Tools

#### Data Source MCP (13 tools)

| Tool | Description |
|------|-------------|
| `import_csv` | Import data from CSV file |
| `import_excel` | Import data from Excel file |
| `import_database` | Import data from SQL database |
| `get_schema` | Get current source schema |
| `get_row` | Get a specific row by number |
| `get_rows_by_filter` | Query rows with SQL WHERE |
| `query_data` | Execute arbitrary SQL query |
| `compute_checksums` | Generate SHA-256 for rows |
| `verify_checksum` | Verify row hasn't changed |
| `write_back` | Update source with tracking |

#### UPS MCP (6 tools)

| Tool | Description |
|------|-------------|
| `rating_quote` | Get shipping rate quote |
| `rating_shop` | Compare rates across services |
| `shipping_create` | Create shipment and label |
| `shipping_void` | Void a shipment |
| `shipping_get_label` | Retrieve label image |
| `address_validate` | Validate shipping address |

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

# Type checking
mypy src/

# Linting and formatting
ruff check src/ tests/
ruff format src/ tests/
```

### UPS MCP Development

```bash
cd packages/ups-mcp

# Build TypeScript
pnpm build

# Run tests
pnpm test

# Watch mode
pnpm dev
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
│   ├── api/                    # FastAPI REST endpoints
│   │   ├── routes/             # Route handlers
│   │   ├── main.py             # App factory
│   │   └── schemas.py          # Pydantic models
│   ├── db/                     # Database layer
│   │   ├── models.py           # SQLAlchemy models
│   │   └── session.py          # Session management
│   ├── errors/                 # Error handling
│   │   ├── codes.py            # E-XXXX error codes
│   │   └── ups_translator.py   # UPS error mapping
│   ├── services/               # Business logic
│   │   ├── job_service.py      # Job state machine
│   │   └── audit_service.py    # Audit logging
│   ├── mcp/
│   │   ├── data_source/        # Data Source MCP server
│   │   │   ├── server.py       # FastMCP server
│   │   │   ├── adapters/       # CSV, Excel, DB adapters
│   │   │   └── tools/          # MCP tool implementations
│   │   └── external_sources/   # External platform clients
│   └── orchestrator/           # AI orchestration
│       ├── nl_engine/          # NL parsing & generation
│       ├── filters/            # Jinja2 logistics filters
│       ├── agent/              # Claude Agent SDK
│       └── batch/              # Batch execution engine
├── packages/
│   └── ups-mcp/                # UPS MCP server (TypeScript)
│       └── src/
│           ├── tools/          # Rating, shipping, address
│           ├── auth.ts         # OAuth management
│           └── client.ts       # UPS API client
├── frontend/                   # React web interface
│   └── src/
│       ├── components/         # UI components
│       ├── hooks/              # React hooks
│       ├── lib/                # Utilities
│       └── types/              # TypeScript types
├── tests/                      # Test suite
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   └── helpers/                # Test utilities
└── docs/                       # Documentation
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

### Adding a Carrier MCP

Follow the UPS MCP pattern:
1. Define Zod schemas from OpenAPI specs
2. Implement tools with namespaced names
3. Handle OAuth/authentication
4. Return standardized response format

### Adding Template Filters

Register custom Jinja2 filters:

```python
from src.orchestrator.filters import register_filter

@register_filter
def my_filter(value: str) -> str:
    return value.upper()
```

---

## Roadmap

- [x] Phase 1: Core Infrastructure (API, Database, Errors)
- [x] Phase 2: Data Source MCP
- [x] Phase 3: UPS MCP Integration
- [x] Phase 4: NL Engine (Intent Parsing, Mapping)
- [x] Phase 5: Agent Orchestration
- [x] Phase 6: Batch Execution Engine
- [ ] Phase 7: Web Interface (In Progress)
- [ ] Phase 8: Multi-carrier Support (FedEx, USPS)
- [ ] Phase 9: International Shipping & Customs

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

- [Anthropic Claude](https://www.anthropic.com/) - AI orchestration
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP specification
- [UPS Developer Kit](https://developer.ups.com/) - Shipping APIs
- [FastAPI](https://fastapi.tiangolo.com/) - API framework
- [DuckDB](https://duckdb.org/) - In-process SQL engine
