# ShipAgent

## What This Is

A proof-of-concept prototype demonstrating natural language-driven batch shipment processing. Users describe what they want to ship in plain English, and an AI agent handles parsing intent, extracting data from various sources, mapping to UPS format, and executing shipments with full data integrity.

## Core Value

**The ONE thing that must work:** Users can issue a natural language command like "Ship all California orders from today's spreadsheet using UPS Ground" and the system correctly creates those shipments via UPS API without data loss or incorrect shipments.

## Problem Being Solved

Batch shipping is tedious and error-prone. Users have order data scattered across spreadsheets and databases. Manually mapping this data to carrier API requirements is slow and mistakes are costly. This prototype proves that natural language + AI can bridge the gap between messy real-world data and precise carrier API specifications.

## Architecture Philosophy

**"LLM as Configuration Engine, not Data Pipe"**

- The LLM interprets user intent and generates transformation rules (Jinja2 mapping templates)
- Deterministic code executes those rules against actual data
- The LLM never touches row-level shipment data directly
- This ensures zero data loss and perfect compliance with UPS API spec

This separation is critical: LLMs can hallucinate, but by keeping them out of the data execution path, we get natural language understanding without risking corrupted shipment data.

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Orchestration | Claude SDK (Python) | Intent interpretation, workflow coordination, agentic capabilities |
| Web Framework | FastAPI | API endpoints, web UI backend |
| Data Processing | DuckDB + Pandas | Query/transform data from any source |
| UPS Integration | TypeScript + Zod | Schema validation, OAuth, API calls |
| Template Engine | Jinja2 | Data → UPS payload mapping |
| State Persistence | SQLite | Job state, audit logs, crash recovery |
| Architecture | MCP (Model Context Protocol) | Separation of concerns into independent servers |

## Data Sources (MVP)

All four supported from day one:

1. **CSV files** — User uploads spreadsheet exports
2. **Excel files** — .xlsx with potentially multiple sheets
3. **Google Sheets** — Live connection to cloud spreadsheets
4. **Database** — Direct connection (Postgres, MySQL, SQLite, etc.)

Each source requires:
- Schema discovery (column names, types)
- Data extraction with filtering
- Write-back capability (tracking numbers back to source)
- Row checksums for integrity verification

## UPS Capabilities (v1)

| Namespace | Capabilities |
|-----------|-------------|
| Shipping | Create shipments, void shipments, generate PDF labels |
| Rating | Get quotes, compare service options, time-in-transit estimates |

Deferred to v2+: Address validation, tracking, returns, alternate label formats

## Batch Processing

### Supported Scales

- **Small (1-50):** Individual orders, quick one-off jobs
- **Medium (50-500):** Daily batch operations
- **High-volume (500+):** Warehouse-scale processing

### Execution Modes

Dual capability, user-toggleable:

| Mode | Behavior |
|------|----------|
| **Confirm Mode** | Preview shipment details, show cost estimates, require user approval before creating labels |
| **Auto Mode** | Skip confirmation, execute immediately, optimized for speed |

### Error Handling

**Fail-fast strategy:** Stop entire batch on first error. We never want to accidentally create incorrect shipments. Better to halt and let user fix the issue than continue with potentially wrong data.

### Workflow

1. User provides natural language command
2. Agent parses intent → identifies data source, filter criteria, carrier/service
3. Agent generates SQL filter + Jinja2 mapping template
4. Data extracted from source, SHA-256 checksums computed per row
5. Template validated against UPS schema (agent self-corrects if validation fails)
6. **If Confirm Mode:** Preview shown with cost estimate, user approves
7. Batch execution loop — each row processed with per-row state writes
8. On error: halt immediately, preserve state for recovery
9. On success: tracking numbers written back to source, labels saved as PDF

## User Interface

Web UI — design to be determined in separate session. For prototype, likely a simple interface for:
- Entering natural language commands
- Viewing batch progress
- Previewing shipments before confirmation
- Downloading labels
- Viewing audit logs

## Constraints

- **UPS only** for MVP (no multi-carrier)
- **PDF labels only** (no ZPL/thermal printer support)
- **Single UPS account** (no multi-tenant)
- **English only** for natural language commands

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Natural language command parsing and intent extraction
- [ ] CSV data source adapter (read, schema discovery, write-back)
- [ ] Excel data source adapter (read, schema discovery, write-back)
- [ ] Google Sheets data source adapter (read, schema discovery, write-back)
- [ ] Database data source adapter (read, schema discovery, write-back)
- [ ] Jinja2 template generation for data → UPS payload mapping
- [ ] UPS OAuth authentication
- [ ] UPS Shipping API integration (create shipment, void, get label)
- [ ] UPS Rating API integration (get quote, compare services)
- [ ] Confirm mode with preview and cost display
- [ ] Auto mode for fast batch execution
- [ ] Fail-fast error handling with batch halt
- [ ] Per-row state tracking for crash recovery
- [ ] PDF label generation and storage
- [ ] Tracking number write-back to source
- [ ] Web UI for command input and batch management
- [ ] Claude SDK orchestration agent

### Out of Scope

- Multi-carrier support (FedEx, USPS, etc.) — UPS only for MVP
- ZPL/thermal printer label formats — PDF only
- Address validation API — defer to v2
- Tracking API — defer to v2
- Return shipments — defer to v2
- Multi-tenant/multi-account — single UPS account
- Non-English language support

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LLM as Configuration Engine | Prevents hallucination on actual shipment data; LLM generates templates, code executes | Architecture pattern |
| Fail-fast error handling | Safety over throughput; never create incorrect shipments | Batch halts on first error |
| All 4 data sources in MVP | Proves flexibility of the approach | CSV, Excel, Sheets, DB all supported |
| PDF labels only | Simplifies MVP; thermal printers add complexity | Single label format |
| Claude SDK for orchestration | Leverage agentic capabilities, official Anthropic tooling | Primary framework choice |
| MCP architecture | Clean separation of concerns; open to simplification if needed | Modular design |

## Open Questions

- [ ] Web UI design specifics (separate design session planned)
- [ ] Specific database types to prioritize (Postgres? MySQL? Both?)
- [ ] Google Sheets authentication flow details
- [ ] Label storage location and naming convention
- [ ] Audit log retention policy

---
*Last updated: 2025-01-23 after initialization*
