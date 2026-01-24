# Architecture Research

**Project:** ShipAgent - Natural Language Batch Shipment Processing
**Researched:** 2026-01-23
**Mode:** Ecosystem Research
**Overall Confidence:** HIGH (existing architecture aligns with industry patterns)

---

## Executive Summary

ShipAgent's proposed architecture follows validated patterns for AI-orchestrated batch processing systems. The "LLM as Configuration Engine" principle separates non-deterministic AI intent parsing from deterministic data execution, which research confirms is essential for production reliability. The MCP (Model Context Protocol) architecture provides clean separation of concerns with established security and scalability patterns.

Key architectural validation points:
- Multi-agent orchestration (Claude SDK + MCPs) matches 2025 best practices
- Deterministic execution with per-row state tracking follows crash recovery patterns
- DuckDB + Pandas integration is optimal for the 1-1000 row batch scale
- Jinja2 templating for data transformation is industry-standard
- OAuth 2.0 + REST API patterns match current UPS/FedEx requirements

---

## System Components

### Component Boundaries (Validated Architecture)

| Component | Responsibility | Technology | Boundary |
|-----------|---------------|------------|----------|
| **Orchestration Agent** | Intent parsing, workflow coordination, batch execution | Python + Claude SDK + FastAPI | The "brain" - coordinates all other components but never touches external APIs directly |
| **Data Source MCP** | Data access abstraction, schema discovery, query execution, write-back | Python + DuckDB + Pandas | Owns all data source interactions; Agent queries through MCP tools only |
| **UPS Shipping MCP** | Carrier API integration, schema validation, OAuth management | TypeScript + Zod | Owns all UPS API interactions; validates every payload before submission |
| **State Database** | Job state, transaction journal, audit logs, crash recovery | SQLite (dev) / PostgreSQL (prod) | Owned by Agent; provides durability guarantees |
| **Browser UI** | User interaction, command input, batch approval, progress display | React/HTML (future) | Presentation layer only; consumes Agent WebSocket/HTTP |

### Component Isolation Rationale

**Why separate MCPs instead of monolithic agent?**

1. **Fault Isolation** - If Data MCP crashes reading a corrupted Excel file, UPS MCP continues running; Agent can restart just the failed component
2. **Technology Optimization** - Python for data science (Pandas, DuckDB), TypeScript for schema safety (Zod from OpenAPI)
3. **Security Boundaries** - Each MCP has minimal permissions; Data MCP has file access but not network; UPS MCP has network but not file system
4. **Independent Scaling** - Future: UPS MCP could be replicated for parallel shipment creation

**Confidence:** HIGH - This pattern is validated by [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/) which recommends "Single Responsibility: Each MCP server should have one clear, well-defined purpose."

---

## Data Flow

### Primary Flow: Batch Shipment Processing

```
User Intent                    LLM Processing                 Deterministic Execution
-----------                    --------------                 -----------------------

"Ship all CA orders    -->     Intent Parser      -->        SQL Filter Generated
 via Ground"                   (Claude API)                  + Jinja2 Template

                                     |
                                     v

                              Data Source MCP    -->         Filtered rows extracted
                              (query_data)                   SHA-256 checksums computed

                                     |
                                     v

                              UPS Shipping MCP   -->         Template validated against
                              (shipping_validate)            UPS schema (dry run)

                                     |
                                     v
                              [If validation fails]
                              Self-Correction    -->         LLM fixes template
                              Loop                           Retry validation

                                     |
                                     v

                              Approval Gate      -->         Preview shown to user
                                                             Cost estimate displayed

                                     |
                                     v

                              Batch Executor     -->         Per-row loop:
                              (deterministic)                1. Write PENDING state
                                                             2. Apply template
                                                             3. Call UPS API
                                                             4. Save label
                                                             5. Write SUCCESS state

                                     |
                                     v

                              Data Source MCP    -->         Tracking numbers
                              (write_results)                written back to source
```

### Data Flow Principles

1. **LLM touches configuration, not data** - The LLM generates SQL filters and Jinja2 templates, but never processes actual row data
2. **Deterministic execution after approval** - Once user approves, the batch loop is pure deterministic code
3. **State before action** - Row state written to DB before API call, enabling crash recovery
4. **Checksums for integrity** - SHA-256 hash per row detects if source data changes mid-batch

**Confidence:** HIGH - Matches [Temporal's durable execution patterns](https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal): "Your Workflow is the orchestration layer... It needs to be deterministic so [the system] can help your agent survive through process crashes."

---

## Integration Points

### External Systems

| System | Protocol | Authentication | Direction | Notes |
|--------|----------|----------------|-----------|-------|
| **Anthropic API** | HTTPS | API Key | Agent -> Anthropic | Intent parsing, template generation, self-correction |
| **UPS API** | HTTPS REST | OAuth 2.0 | UPS MCP -> UPS | Shipping, rating, address validation, tracking |
| **Google Sheets** | HTTPS REST | OAuth 2.0 | Data MCP -> Sheets | Read order data, write tracking numbers |
| **Local Filesystem** | File I/O | OS permissions | Agent + Data MCP | CSV/Excel read, label file write |

### Internal Communication

| Path | Transport | Pattern | Notes |
|------|-----------|---------|-------|
| Agent <-> Data MCP | stdio | Request/Response | Child process, no network |
| Agent <-> UPS MCP | stdio | Request/Response | Child process, no network |
| Agent <-> State DB | SQL | ACID transactions | Direct connection via aiosqlite/asyncpg |
| Agent <-> Browser UI | WebSocket/HTTP | Streaming + Request/Response | Future: real-time batch progress |

### Integration Patterns Applied

**Pattern 1: Gateway/Gatekeeper**
- UPS MCP acts as a gateway that validates every payload before submission
- Zod schemas generated from UPS OpenAPI spec catch errors at compile time
- No invalid payloads ever reach UPS API

**Pattern 2: Anti-Corruption Layer**
- Data Source MCP abstracts heterogeneous data sources (CSV, Excel, Sheets, DB) behind unified SQL interface
- Agent never knows/cares about file format
- Schema discovery normalizes type information

**Pattern 3: Outbox Pattern (for crash recovery)**
- State DB records intent before execution
- Row marked PENDING before API call
- On crash: query PENDING rows to resume

**Confidence:** HIGH - Gateway pattern aligns with [enterprise carrier integration recommendations](https://proshipinc.com/blog/api-on-platform-or-hybrid-the-high-stakes-carrier-engine-decision-for-enterprise-parcel-shippers/): "End-of-line shipping demands a faster, more reliable rating architecture."

---

## Suggested Build Order

Based on component dependencies, the recommended implementation order:

### Phase 1: Foundation (No External Dependencies)

**Build first - everything else depends on these:**

1. **State Database Schema** - Job and row state tables, audit log structure
   - Why first: All components need to write state
   - Dependency: None
   - Complexity: Low

2. **Template Engine + Filter Library** - Jinja2 environment with logistics filters
   - Why second: Core transformation logic
   - Dependency: None
   - Complexity: Medium

3. **Batch Executor (Local Mode)** - Deterministic loop with Observer pattern, mock outputs
   - Why third: Core execution loop
   - Dependency: State DB, Template Engine
   - Complexity: Medium

### Phase 2: Data Layer

**Build next - Agent needs data to orchestrate:**

4. **Data Source MCP - CSV Adapter** - Read CSV, schema discovery, checksums
   - Why: Simplest data source, good for testing
   - Dependency: Phase 1 complete
   - Complexity: Medium

5. **Data Source MCP - Query Engine** - DuckDB integration, SQL filtering
   - Why: Enables LLM-generated queries
   - Dependency: CSV Adapter
   - Complexity: Medium

6. **Data Source MCP - Excel Adapter** - Read/write XLSX
   - Why: Common enterprise format
   - Dependency: Query Engine
   - Complexity: Medium

7. **Data Source MCP - Google Sheets Adapter** - OAuth + gspread
   - Why: Cloud data source
   - Dependency: Query Engine
   - Complexity: Medium-High (OAuth flow)

### Phase 3: Carrier Integration

**Build next - Enables actual shipment creation:**

8. **UPS Shipping MCP - Auth Manager** - OAuth 2.0 token management
   - Why first: All UPS calls need auth
   - Dependency: None (can build in parallel with Phase 2)
   - Complexity: Medium

9. **UPS Shipping MCP - Schema Validators** - Zod from OpenAPI
   - Why: Validation before any API call
   - Dependency: None (build-time generation)
   - Complexity: Medium

10. **UPS Shipping MCP - Shipping Tools** - validate, create, void
    - Why: Core shipping functionality
    - Dependency: Auth Manager, Schema Validators
    - Complexity: High

11. **UPS Shipping MCP - Rating Tools** - quote, shop
    - Why: Cost estimates for approval gate
    - Dependency: Auth Manager, Schema Validators
    - Complexity: Medium

### Phase 4: Orchestration

**Build next - Ties everything together:**

12. **Orchestration Agent - MCP Coordinator** - Spawn and manage MCP processes
    - Why: Agent needs to communicate with MCPs
    - Dependency: Data MCP + UPS MCP complete
    - Complexity: Medium

13. **Orchestration Agent - Intent Parser** - LLM-powered command understanding
    - Why: Entry point for user commands
    - Dependency: Claude SDK
    - Complexity: High

14. **Orchestration Agent - Mapping Generator** - LLM-powered template creation
    - Why: Generates transformation logic
    - Dependency: Intent Parser, Template Engine
    - Complexity: High

15. **Orchestration Agent - Approval Gate** - Preview, cost display, user confirmation
    - Why: Safety checkpoint before execution
    - Dependency: Batch Executor, Rating Tools
    - Complexity: Medium

### Phase 5: User Interface

**Build last - Consumes Agent's existing interfaces:**

16. **FastAPI Endpoints** - HTTP/WebSocket API for UI
    - Why: UI communication layer
    - Dependency: Agent complete
    - Complexity: Medium

17. **Browser UI** - React/HTML interface
    - Why: User-facing presentation
    - Dependency: FastAPI endpoints
    - Complexity: Medium-High

### Dependency Graph

```
                                    Phase 1: Foundation
                                    -------------------
                                    State DB Schema
                                           |
                                    Template Engine + Filters
                                           |
                                    Batch Executor
                                           |
                    +----------------------+----------------------+
                    |                                             |
             Phase 2: Data                                 Phase 3: Carrier
             ---------------                               -----------------
             CSV Adapter                                   Auth Manager
                 |                                              |
             Query Engine                                 Schema Validators
                 |                                              |
        +--------+--------+                          +---------+---------+
        |                 |                          |                   |
    Excel Adapter    Sheets Adapter             Shipping Tools     Rating Tools
        |                 |                          |                   |
        +-----------------+                          +-------------------+
                    |                                         |
                    +------------------+----------------------+
                                       |
                                Phase 4: Orchestration
                                ----------------------
                                   MCP Coordinator
                                         |
                              +----------+----------+
                              |                     |
                        Intent Parser        Mapping Generator
                              |                     |
                              +----------+----------+
                                         |
                                   Approval Gate
                                         |
                                Phase 5: UI
                                ----------
                              FastAPI Endpoints
                                      |
                                 Browser UI
```

**Confidence:** HIGH - Build order follows [standard dependency inversion principles](https://modelcontextprotocol.info/docs/best-practices/): build stable foundations first, integration points next, orchestration after, presentation last.

---

## Architecture Patterns

### Pattern 1: LLM as Configuration Engine

**What:** LLM interprets intent and generates transformation rules (SQL filters, Jinja2 templates) but never processes actual data. Deterministic code executes the rules.

**Why:** LLMs can hallucinate. By keeping them out of the data execution path, we get natural language understanding without risking corrupted shipment data.

**Implementation:**
- Intent Parser outputs structured commands (service code, filter criteria)
- Mapping Generator outputs Jinja2 template
- Batch Executor applies template to data (no LLM involved)

**Research Validation:** This matches [GraphBit's production-grade pattern](https://www.marktechpost.com/2025/12/27/how-to-build-production-grade-agentic-workflows-with-graphbit-using-deterministic-tools-validated-execution-graphs-and-optional-llm-orchestration/): "Tools can be composed into a reliable, rule-based pipeline... The system supports gradual adoption of agentic intelligence without sacrificing reproducibility."

### Pattern 2: Model Context Protocol (MCP)

**What:** Separation of concerns into independent servers (MCPs) with standardized tool interfaces, orchestrated by an AI agent.

**Why:** Fault isolation, technology optimization, security boundaries, independent scaling.

**Implementation:**
- Data Source MCP: data access tools (`get_schema`, `query_data`, `write_results`)
- UPS Shipping MCP: carrier tools (`shipping_validate`, `shipping_create`, `rating_quote`)
- Agent coordinates via stdio transport

**Research Validation:** MCP is now [industry standard adopted by OpenAI and Google DeepMind](https://en.wikipedia.org/wiki/Model_Context_Protocol). Best practices recommend single-responsibility servers.

### Pattern 3: Checkpoint/Restart for Crash Recovery

**What:** Per-row state written before each operation, enabling resume from last success point.

**Why:** Batch shipment processing involves money (label purchases). Cannot afford to lose progress or duplicate shipments.

**Implementation:**
- State DB records: `{job_id, row_checksum, status: PENDING/SUCCESS/FAILED, tracking_number, timestamp}`
- Before UPS API call: write PENDING
- After success: write SUCCESS with tracking number
- On restart: query rows with status != SUCCESS

**Research Validation:** Matches [Dagster's checkpointing definition](https://dagster.io/glossary/checkpointing): "Checkpointing allows a system to recover from failures by restarting the processing from the last saved state rather than reprocessing all the data from scratch." Also aligns with [CMU database recovery principles](https://15445.courses.cs.cmu.edu/spring2025/notes/21-recovery.pdf): idempotent operations that produce same result whether executed once or multiple times.

### Pattern 4: Self-Correction Loop

**What:** When UPS schema validation fails, Agent asks LLM to fix the template and retries.

**Why:** Source data varies. Template that works for row 1 might fail for row 100 (address too long, invalid state code). Self-correction adapts.

**Implementation:**
1. Apply template to sample rows
2. Validate against UPS schema (Zod)
3. If error: send error message + template to LLM
4. LLM returns corrected template
5. Retry validation (max 3 attempts)
6. If still failing: halt and ask user

**Research Validation:** Matches [Claude Agent SDK patterns](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk): "Claude often operates in a specific feedback loop: gather context -> take action -> verify work -> repeat."

### Pattern 5: Observer Pattern for Execution Events

**What:** Batch Executor emits lifecycle events (`onRowStart`, `onRowSuccess`, `onRowFailure`). Observers subscribe for state writing, notifications, etc.

**Why:** Decouples core execution logic from side effects. Adding Slack notifications doesn't change Batch Executor code.

**Implementation:**
- Batch Executor: `self.observers.notify('row_success', {row_id, tracking_number})`
- State Writer Observer: writes to State DB
- (Future) Notification Observer: sends Slack/email
- (Future) UI Observer: pushes WebSocket updates

**Research Validation:** Standard [GoF Observer pattern](https://refactoring.guru/design-patterns/observer) for event-driven systems. Common in batch processing for audit trails.

### Pattern 6: Zero-Copy Data Integration (DuckDB + Pandas)

**What:** DuckDB operates directly on Pandas DataFrame memory buffers without copying data.

**Why:** Performance and memory efficiency for medium-scale batch processing (1-1000 rows).

**Implementation:**
- Load CSV/Excel into Pandas DataFrame
- Register DataFrame with DuckDB: `duckdb.register('orders', df)`
- Execute SQL: `duckdb.sql("SELECT * FROM orders WHERE state='CA'")`
- Results accessible as DataFrame or Arrow

**Research Validation:** [DigitalOcean confirms](https://www.digitalocean.com/community/tutorials/duckdb-complements-pandas-for-large-scale-analytics): "DuckDB offers direct, zero-copy access to Pandas and Polars DataFrames... incredibly fast I/O that is architecturally impossible in a client-server system."

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: LLM as Data Pipe

**What:** Passing actual row data through the LLM for transformation.

**Why bad:** LLMs hallucinate. A single wrong digit in a ZIP code means lost package. Also: expensive (token costs), slow (API latency per row), and privacy risk (shipping data contains PII).

**Instead:** LLM generates template once; deterministic code applies it N times.

### Anti-Pattern 2: Monolithic MCP

**What:** Single MCP server handling data access AND carrier API AND file system.

**Why bad:** Blast radius. Bug in Excel parsing crashes entire system. Security: one exploit exposes all capabilities.

**Instead:** Separate MCPs with minimal permissions each.

### Anti-Pattern 3: In-Place Source Modification

**What:** Writing tracking numbers back to original CSV/Excel file during batch execution.

**Why bad:** If batch fails midway, source file is partially modified. User loses clean starting point.

**Instead:** Write to new file (e.g., `orders_processed_20260123.csv`) or versioned copy. Original preserved.

### Anti-Pattern 4: Optimistic Execution Without Approval

**What:** Immediately creating shipments without user preview/confirmation.

**Why bad:** Shipment creation costs money and creates real-world packages. User might have made typo in filter criteria.

**Instead:** Approval Gate with preview (row count, cost estimate, sample rows) before any labels purchased.

### Anti-Pattern 5: Silent Failure Continuation

**What:** Batch continues processing after a row fails, hoping errors are isolated.

**Why bad:** Errors often indicate systemic issue (wrong template, invalid credentials, rate limit). Continuing creates inconsistent state.

**Instead:** Fail-fast. Stop on first error, preserve state, report to user. Better to halt than ship wrong packages.

---

## Scalability Considerations

| Concern | Current Design (1-1000 rows) | 10K+ rows | Notes |
|---------|------------------------------|-----------|-------|
| **Memory** | DuckDB in-memory | Streaming/pagination | DuckDB excels up to 1B rows on modern laptop |
| **API Rate Limits** | Serial execution | Parallel with backoff | UPS has rate limits; current design handles gracefully |
| **State DB** | SQLite single-writer | PostgreSQL with connection pool | SQLite fine for prototype; clear upgrade path |
| **MCP Transport** | stdio (child process) | HTTP/SSE (containers) | MCP spec supports both; config change only |
| **Label Storage** | Local filesystem | S3/GCS bucket | Swap Label Handler destination |

**Key insight:** Current architecture is designed for MVP scale (1-1000 rows) but has clear upgrade paths for each component. No architectural rewrites needed for 10x scale.

---

## Technology Validation

### Validated Choices

| Technology | Validation | Confidence |
|------------|------------|------------|
| **Claude Agent SDK** | Official Anthropic framework; matches documented patterns | HIGH |
| **MCP Architecture** | Industry standard since 2024; adopted by OpenAI, Google | HIGH |
| **DuckDB + Pandas** | Zero-copy integration confirmed; optimal for 1GB-100GB | HIGH |
| **Jinja2 for Templates** | Industry standard for Python data transformation | HIGH |
| **SQLite for State** | ACID transactions; standard for local-first apps | HIGH |
| **Zod for UPS Schema** | TypeScript OpenAPI tooling mature; type-safe validation | HIGH |
| **OAuth 2.0 for UPS** | Required by UPS/FedEx; no alternatives | HIGH |

### Potential Concerns

| Concern | Assessment | Mitigation |
|---------|------------|------------|
| **stdio MCP transport** | Fine for local dev; may need HTTP for containers | MCP spec supports both; config change |
| **Single-threaded batch** | OK for 1K rows; slow for 10K+ | Future: parallel chunks with state isolation |
| **Google Sheets OAuth** | Complex consent flow | Document thoroughly; consider service account for automation |

---

## Sources

### Architecture Patterns
- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview) - Official documentation
- [Building Agents with Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk) - Anthropic engineering blog
- [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/) - Official MCP guidance
- [MCP Specification 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18) - Current protocol spec

### Batch Processing & Crash Recovery
- [Checkpoint/Restore Systems in AI Agents](https://eunomia.dev/blog/2025/05/11/checkpointrestore-systems-evolution-techniques-and-applications-in-ai-agents/) - Comprehensive survey
- [Durable Execution for Agent Orchestration](https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal) - Temporal patterns
- [GraphBit Deterministic Workflows](https://www.marktechpost.com/2025/12/27/how-to-build-production-grade-agentic-workflows-with-graphbit-using-deterministic-tools-validated-execution-graphs-and-optional-llm-orchestration/) - Production patterns

### Data Processing
- [DuckDB + Pandas Integration](https://www.digitalocean.com/community/tutorials/duckdb-complements-pandas-for-large-scale-analytics) - Zero-copy patterns
- [DuckDB Enterprise Patterns](https://endjin.com/blog/2025/04/duckdb-in-practice-enterprise-integration-architectural-patterns) - Architectural guidance

### Shipping Integration
- [Carrier API Changes 2025](https://afs.net/blog/ups-fedex-api-changes/) - OAuth 2.0 migration
- [Enterprise Carrier Integration](https://proshipinc.com/blog/api-on-platform-or-hybrid-the-high-stakes-carrier-engine-decision-for-enterprise-parcel-shippers/) - Hybrid architecture patterns

---

## Roadmap Implications

Based on this research, the architecture supports the following phase structure:

1. **Foundation Phase** - State DB + Template Engine + Batch Executor (local mode)
   - Rationale: Core deterministic execution must work before adding LLM orchestration
   - Risk: Low (standard patterns)

2. **Data Integration Phase** - Data Source MCP with adapters
   - Rationale: Agent needs data to orchestrate
   - Risk: Medium (Google Sheets OAuth complexity)

3. **Carrier Integration Phase** - UPS Shipping MCP
   - Rationale: Real shipment creation
   - Risk: Medium (UPS API nuances, sandbox vs production)

4. **Orchestration Phase** - Intent Parser + Mapping Generator + Approval Gate
   - Rationale: Ties MCPs together with LLM intelligence
   - Risk: High (LLM reliability, self-correction tuning)

5. **UI Phase** - FastAPI + Browser UI
   - Rationale: User-facing layer built on stable backend
   - Risk: Medium (WebSocket complexity, UX design)

**Critical Path:** Phases 1-3 can partially parallelize. Phase 4 requires 2+3 complete. Phase 5 requires 4 complete.

**Research Flags:**
- Phase 3 (UPS): May need deeper research on sandbox/production differences
- Phase 4 (Orchestration): Self-correction loop tuning requires experimentation
- Phase 2 (Sheets): OAuth consent flow needs user testing
