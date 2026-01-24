# ShipAgent Requirements

## Overview

Natural language interface for batch shipment processing via UPS API. Users describe shipments in plain English, system handles parsing, mapping, and execution with full data integrity.

---

## v1 Requirements

### Data Sources

- [ ] **DATA-01**: User can import shipment data from CSV files with automatic schema discovery
- [ ] **DATA-02**: User can import shipment data from Excel files (.xlsx) with sheet selection
- [ ] **DATA-03**: User can import shipment data from database (Postgres/MySQL) via connection string
- [ ] **DATA-04**: System writes tracking numbers back to original data source after successful shipment
- [ ] **DATA-05**: System computes row checksums (SHA-256) for data integrity verification

### UPS Integration

- [ ] **UPS-01**: System authenticates with UPS API using OAuth 2.0 with automatic token refresh
- [ ] **UPS-02**: User can get shipping rates/quotes for packages before creating shipments
- [ ] **UPS-03**: User can create shipments and generate PDF labels via UPS Shipping API
- [ ] **UPS-04**: System validates payloads against UPS OpenAPI schema (docs/shipping.yaml, docs/rating.yaml) using Zod
- [ ] **UPS-05**: UPS MCP server built in TypeScript with Zod schemas generated from OpenAPI specs

### Natural Language & LLM

- [ ] **NL-01**: User can issue natural language commands like "Ship all California orders using UPS Ground"
- [ ] **NL-02**: System parses intent to extract: data source, filter criteria, carrier service, package details
- [ ] **NL-03**: System generates Jinja2 mapping templates to transform source data to UPS payload format
- [ ] **NL-04**: System validates generated templates against UPS schema before execution
- [ ] **NL-05**: System self-corrects mapping templates when validation fails (LLM fixes errors automatically)
- [ ] **NL-06**: User can filter data using natural language ("today's orders", "over 5 lbs", "California addresses")

### Orchestration

- [ ] **ORCH-01**: Claude Agent SDK orchestrates all MCPs and manages agentic workflow
- [ ] **ORCH-02**: Data Source MCP built with FastMCP (Python) exposes tools for data access
- [ ] **ORCH-03**: UPS MCP built with McpServer (TypeScript) exposes shipping/rating tools
- [ ] **ORCH-04**: MCPs communicate via stdio transport as child processes
- [ ] **ORCH-05**: Orchestration agent uses hooks for pre/post tool validation

### Batch Execution

- [ ] **BATCH-01**: System processes batches of 1-500+ shipments in a single job
- [ ] **BATCH-02**: User can preview shipment details and total cost before execution (confirm mode)
- [ ] **BATCH-03**: User can skip preview and execute immediately (auto mode)
- [ ] **BATCH-04**: User can toggle between confirm mode and auto mode
- [ ] **BATCH-05**: System halts entire batch on first error (fail-fast) to prevent incorrect shipments
- [ ] **BATCH-06**: System tracks per-row state for crash recovery (can resume from last successful row)
- [ ] **BATCH-07**: System persists job state to SQLite for durability

### Output & Audit

- [ ] **OUT-01**: System generates and saves PDF labels to filesystem
- [ ] **OUT-02**: System logs all operations with timestamps for audit trail
- [ ] **OUT-03**: System provides clear, actionable error messages when operations fail
- [ ] **OUT-04**: User can view job history and status

### User Interface

- [ ] **UI-01**: Web UI for entering natural language commands
- [ ] **UI-02**: Web UI displays batch progress during execution
- [ ] **UI-03**: Web UI shows shipment preview with cost estimate before confirmation
- [ ] **UI-04**: Web UI allows downloading generated PDF labels
- [ ] **UI-05**: FastAPI backend serves Web UI and API endpoints

---

## v2 Requirements (Deferred)

### Data Sources
- [ ] Google Sheets integration with OAuth

### UPS Capabilities
- [ ] Address validation API integration
- [ ] Void/cancel shipments
- [ ] Tracking API integration

### Execution
- [ ] Template reuse (save successful mappings for repeated workflows)
- [ ] Partial batch recovery (skip failed rows, continue with valid ones)

### International
- [ ] International shipping with customs documentation
- [ ] HS codes and commercial invoices

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-carrier (FedEx, USPS) | UPS only for MVP - prove concept with one carrier |
| ZPL/thermal printer labels | PDF only - thermal adds printer driver complexity |
| Returns/RMA | Reverse logistics is complex - defer to v2+ |
| Multi-tenant/multi-account | Single UPS account - no auth complexity |
| Order management | Read-only from data sources - no order creation |
| Inventory management | Different domain - not shipping |
| Customer notifications | Users use existing systems |
| Payment processing | PCI compliance burden - users pay UPS directly |
| Non-English commands | English only for NL parsing |
| ML rate optimization | Rule-based for MVP |

---

## Traceability

*Populated by roadmap creation*

| Requirement | Phase | Plan |
|-------------|-------|------|
| | | |

---

## Technology Constraints

### Claude Agent SDK (Python)
- Use `@tool` decorator and `create_sdk_mcp_server` for in-process tools
- Use `ClaudeSDKClient` with async streaming for orchestration
- Leverage hooks for pre/post tool validation

### MCP Python SDK
- Use `FastMCP` with decorators for Data Source MCP
- Use lifespan context for database connection management
- Use stdio transport for spawned processes

### MCP TypeScript SDK
- Use `McpServer.registerTool()` with Zod schemas for UPS MCP
- Generate Zod schemas from OpenAPI specs (docs/shipping.yaml, docs/rating.yaml)
- Use stdio transport for Claude SDK integration

### UPS API
- OAuth 2.0 with automatic token refresh (mandatory since June 2024)
- Rate limits apply - implement backoff
- Use sandbox environment for development, production for live shipments

---

*Last updated: 2025-01-23*
