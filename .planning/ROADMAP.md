# ShipAgent Roadmap

## Overview

Natural language interface for batch shipment processing via UPS API. Users describe shipments in plain English, system handles parsing, mapping, and execution with full data integrity.

**Core Value:** Users issue NL commands like "Ship all California orders using UPS Ground" and system creates shipments via UPS API without data loss.

---

## Phase Structure

### Phase 1: Foundation and State Management

**Goal:** System has persistent state infrastructure, template engine, and audit logging foundation that all subsequent phases build upon.

**Dependencies:** None (foundation phase)

**Requirements:**
- BATCH-07: System persists job state to SQLite for durability
- OUT-02: System logs all operations with timestamps for audit trail
- OUT-03: System provides clear, actionable error messages when operations fail
- OUT-04: User can view job history and status

**Success Criteria:**
1. Job state persists across system restarts (create job, kill process, restart, job still exists)
2. Every operation writes timestamped log entries that can be queried
3. Error messages include specific failure reason and suggested remediation
4. User can retrieve list of past jobs with their final status

**Plans:** 5 plans

Plans:
- [x] 01-01-PLAN.md — Database schema, SQLAlchemy models, connection management
- [x] 01-02-PLAN.md — Job state machine service with CRUD and per-row tracking
- [x] 01-03-PLAN.md — Audit logging service with redaction and export
- [x] 01-04-PLAN.md — Error handling framework with E-XXXX codes and UPS translation
- [x] 01-05-PLAN.md — FastAPI endpoints for jobs and audit logs

---

### Phase 2: Data Source MCP

**Goal:** Users can import shipment data from files and databases with automatic schema discovery and data integrity verification.

**Dependencies:** Phase 1 (needs state DB for checksums, audit logging)

**Requirements:**
- DATA-01: User can import shipment data from CSV files with automatic schema discovery
- DATA-02: User can import shipment data from Excel files (.xlsx) with sheet selection
- DATA-03: User can import shipment data from database (Postgres/MySQL) via connection string
- DATA-05: System computes row checksums (SHA-256) for data integrity verification
- ORCH-02: Data Source MCP built with FastMCP (Python) exposes tools for data access

**Success Criteria:**
1. User uploads CSV and sees discovered columns with inferred types within 2 seconds
2. User uploads Excel file with multiple sheets and can select which sheet to process
3. User provides database connection string and system lists available tables for import
4. Each imported row has unique SHA-256 checksum that changes if row data changes
5. Data operations are exposed as MCP tools callable via stdio transport

**Plans:** 6 plans

Plans:
- [x] 02-01-PLAN.md — Package structure, Pydantic models, FastMCP server with DuckDB lifespan
- [x] 02-02-PLAN.md — CSV adapter and import_csv tool with schema discovery
- [x] 02-03-PLAN.md — Excel adapter with sheet selection and import_excel tool
- [x] 02-04-PLAN.md — Database adapter for PostgreSQL/MySQL with large table protection
- [x] 02-05-PLAN.md — Schema, query, and checksum tools
- [x] 02-06-PLAN.md — Integration testing and final verification

---

### Phase 3: UPS Integration MCP

**Goal:** System can authenticate with UPS, validate payloads, get rate quotes, and create shipments with PDF labels.

**Dependencies:** Phase 1 (needs state DB for token storage)

**Requirements:**
- UPS-01: System authenticates with UPS API using OAuth 2.0 with automatic token refresh
- UPS-02: User can get shipping rates/quotes for packages before creating shipments
- UPS-03: User can create shipments and generate PDF labels via UPS Shipping API
- UPS-04: System validates payloads against UPS OpenAPI schema using Zod
- UPS-05: UPS MCP server built in TypeScript with Zod schemas generated from OpenAPI specs
- ORCH-03: UPS MCP built with McpServer (TypeScript) exposes shipping/rating tools
- OUT-01: System generates and saves PDF labels to filesystem

**Success Criteria:**
1. System obtains OAuth token and automatically refreshes before expiry without user intervention
2. User provides package dimensions/weight and receives rate quote with cost breakdown
3. User submits valid shipment request and receives tracking number plus PDF label
4. Invalid payload returns specific schema validation error identifying the failing field
5. PDF labels are saved to filesystem with predictable naming (tracking_number.pdf)

**Plans:** 6 plans

Plans:
- [x] 03-01-PLAN.md — TypeScript package setup, Zod schema generation from OpenAPI specs
- [x] 03-02-PLAN.md — OAuth 2.0 authentication and HTTP client with retry logic
- [x] 03-03-PLAN.md — Rating tools (rating_quote, rating_shop) with cost breakdown
- [x] 03-04-PLAN.md — Shipping tools (shipping_create, shipping_void, shipping_get_label)
- [x] 03-05-PLAN.md — Address validation tool (address_validate)
- [x] 03-06-PLAN.md — Integration testing against UPS sandbox

---

### Phase 4: Natural Language and Mapping Engine

**Goal:** Users can issue natural language commands that are parsed into structured intents and automatically generate data-to-UPS mapping templates.

**Dependencies:** Phase 2 (needs data schema), Phase 3 (needs UPS schema for validation)

**Requirements:**
- NL-01: User can issue natural language commands like "Ship all California orders using UPS Ground"
- NL-02: System parses intent to extract: data source, filter criteria, carrier service, package details
- NL-03: System generates Jinja2 mapping templates to transform source data to UPS payload format
- NL-04: System validates generated templates against UPS schema before execution
- NL-05: System self-corrects mapping templates when validation fails
- NL-06: User can filter data using natural language ("today's orders", "over 5 lbs", "California addresses")

**Success Criteria:**
1. User types "Ship California orders via Ground" and system identifies state filter + service level
2. System generates SQL WHERE clause from natural language filter criteria
3. System auto-maps source columns (e.g., "recipient_name") to UPS fields (e.g., "ShipTo.Name")
4. Template validation runs against UPS schema and reports any mismatches before execution
5. When validation fails, system automatically adjusts template and re-validates (max 3 attempts)

---

### Phase 5: Orchestration Agent

**Goal:** Claude Agent SDK coordinates all MCPs, manages agentic workflow, and provides hooks for validation.

**Dependencies:** Phase 2 (Data MCP), Phase 3 (UPS MCP), Phase 4 (Intent parser, template generator)

**Requirements:**
- ORCH-01: Claude Agent SDK orchestrates all MCPs and manages agentic workflow
- ORCH-04: MCPs communicate via stdio transport as child processes
- ORCH-05: Orchestration agent uses hooks for pre/post tool validation

**Success Criteria:**
1. Agent spawns Data MCP and UPS MCP as child processes on startup
2. Agent routes tool calls to appropriate MCP based on tool namespace
3. Pre-tool hooks validate inputs before MCP execution
4. Post-tool hooks validate outputs and trigger error handling when needed
5. Agent maintains conversation context across multiple user commands

---

### Phase 6: Batch Execution Engine

**Goal:** System processes batches of shipments with preview mode, fail-fast error handling, and crash recovery.

**Dependencies:** Phase 3 (UPS shipping), Phase 5 (orchestration), Phase 1 (state persistence)

**Requirements:**
- BATCH-01: System processes batches of 1-500+ shipments in a single job
- BATCH-02: User can preview shipment details and total cost before execution (confirm mode)
- BATCH-03: User can skip preview and execute immediately (auto mode)
- BATCH-04: User can toggle between confirm mode and auto mode
- BATCH-05: System halts entire batch on first error (fail-fast)
- BATCH-06: System tracks per-row state for crash recovery
- DATA-04: System writes tracking numbers back to original data source after successful shipment

**Success Criteria:**
1. System processes 500 shipments in single batch without memory exhaustion
2. Preview mode displays each shipment's details plus aggregate cost estimate
3. Auto mode executes without confirmation prompts
4. User can switch modes mid-session via command
5. First validation/API error halts batch with clear error message
6. After crash, system resumes from last successfully processed row
7. Tracking numbers appear in original CSV/Excel/database after successful shipment

---

### Phase 7: Web Interface

**Goal:** Users interact with the system through a web UI for commands, progress monitoring, and label downloads.

**Dependencies:** Phase 5 (orchestration for API), Phase 6 (batch execution for progress)

**Requirements:**
- UI-01: Web UI for entering natural language commands
- UI-02: Web UI displays batch progress during execution
- UI-03: Web UI shows shipment preview with cost estimate before confirmation
- UI-04: Web UI allows downloading generated PDF labels
- UI-05: FastAPI backend serves Web UI and API endpoints

**Success Criteria:**
1. User can type natural language command in text input and submit
2. Progress indicator shows current row / total rows during batch execution
3. Preview screen displays shipment list with cost totals before user confirms
4. User can click to download individual labels or bulk download as ZIP
5. FastAPI serves both API endpoints and static UI assets

---

## Progress

| Phase | Status | Requirements | Completion |
|-------|--------|--------------|------------|
| 1 - Foundation | Complete | 4 | 100% |
| 2 - Data Source MCP | Complete | 5 | 100% |
| 3 - UPS Integration MCP | Complete | 7 | 100% |
| 4 - NL and Mapping | Not Started | 6 | 0% |
| 5 - Orchestration | Not Started | 3 | 0% |
| 6 - Batch Execution | Not Started | 7 | 0% |
| 7 - Web Interface | Not Started | 5 | 0% |

**Total:** 37 requirements across 7 phases (16 complete)

---

## Dependency Graph

```
Phase 1: Foundation
    |
    +---> Phase 2: Data Source MCP
    |         |
    +---> Phase 3: UPS Integration MCP
              |         |
              v         v
         Phase 4: NL and Mapping
                   |
                   v
            Phase 5: Orchestration
                   |
                   v
            Phase 6: Batch Execution
                   |
                   v
            Phase 7: Web Interface
```

---

## Risk Notes

| Phase | Risk Level | Notes |
|-------|------------|-------|
| 1 | Low | Standard SQLite patterns |
| 2 | Low | Well-documented data processing |
| 3 | Medium | UPS OAuth requires careful token management |
| 4 | High | LLM reliability needs experimentation |
| 5 | Medium | MCP coordination patterns less documented |
| 6 | Medium | Crash recovery and idempotency critical |
| 7 | Low | Standard React/FastAPI patterns |

---

*Last updated: 2026-01-24*
