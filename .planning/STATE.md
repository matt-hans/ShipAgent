# ShipAgent State

## Project Reference

**Core Value:** Users issue NL commands like "Ship all California orders using UPS Ground" and system creates shipments via UPS API without data loss.

**Architecture:** LLM as Configuration Engine - generates templates, deterministic code executes on data.

**Current Focus:** Phase 2 Complete - Ready for Phase 3 (UPS Integration MCP)

---

## Current Position

**Phase:** 2 of 7 (Data Source MCP) - COMPLETE
**Plan:** 6 of 6 complete
**Status:** Phase complete

```
Progress: [##########] 100%
Phase 2 of 7 | Plan 6 of 6 complete
```

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Plans Completed | 11 |
| Plans Failed | 0 |
| Success Rate | 100% |
| Phases Completed | 2 / 7 |

---

## Accumulated Context

### Key Decisions

| Decision | Rationale | Phase |
|----------|-----------|-------|
| 7 phases derived from requirements | Natural delivery boundaries based on dependencies | Roadmap |
| Foundation first | State DB and logging needed by all other phases | Roadmap |
| Data MCP before UPS MCP | Can develop in parallel, but data needed for testing | Roadmap |
| NL/Mapping after both MCPs | Needs both data schema and UPS schema for validation | Roadmap |
| ISO8601 strings for timestamps | SQLite has no native datetime type; ISO strings are human-readable and sortable | 01-01 |
| Store costs in cents as integers | Avoid floating point precision issues with currency | 01-01 |
| SQLAlchemy 2.0 Mapped/mapped_column style | Modern type-safe approach with better IDE support | 01-01 |
| String enums inheriting from str and Enum | JSON serialization friendly, database stores plain strings | 01-01 |
| Combined row tracking in JobService | Row tracking methods logically part of JobService, no benefit to splitting | 01-02 |
| Database-level aggregation for costs | SQLAlchemy func.sum() more efficient than Python loop | 01-02 |
| Substring matching for redaction | Use 'field in key_lower' to catch variations like recipient_name | 01-03 |
| Redaction depth limit of 10 | Prevents infinite recursion while supporting typical nested payloads | 01-03 |
| Log level from HTTP status | 2xx/3xx=INFO, 4xx=WARNING, 5xx=ERROR matches HTTP semantics | 01-03 |
| E-XXXX error code format with category prefixes | E-1xxx data, E-2xxx validation, E-3xxx UPS, E-4xxx system, E-5xxx auth for logical grouping | 01-04 |
| ErrorCode dataclass with message templates | Consistent structure with placeholder substitution for context-specific messages | 01-04 |
| Dual lookup strategy for UPS errors | Direct code mapping first, pattern matching fallback for unknown codes | 01-04 |
| FastAPI Depends for services | Clean dependency injection, testable, follows FastAPI patterns | 01-05 |
| from_attributes=True in Pydantic | Pydantic v2 pattern for automatic ORM model serialization | 01-05 |
| /api/v1 prefix for routes | Enable future API versions without breaking changes | 01-05 |
| Deferred server export from __init__ | Server imports after models; avoid circular imports | 02-01 |
| TYPE_CHECKING for DuckDB type hints | Avoids import side effects in adapter ABC | 02-01 |
| Sorted JSON keys for checksums | Guarantees deterministic hashes regardless of dict key order | 02-01 |
| US date format as default | Per CONTEXT.md: default to US when ambiguous | 02-01 |
| Two-phase import with empty row filter | DuckDB read_csv keeps NULL rows; explicit filter needed per CONTEXT.md | 02-02 |
| ctx.request_context.lifespan_context | FastMCP v2 pattern for accessing lifespan context in tools | 02-02 |
| DuckDB ATTACH/DETACH for database imports | Snapshot semantics, no persistent connection, connection string not stored | 02-04 |
| 10k row threshold for large tables | Balance protection and usability; requires WHERE clause | 02-04 |
| Never log connection strings | Security-first: credentials never appear in logs | 02-04 |
| Type override via session context | Preserves original data, applies CAST at query time | 02-05 |
| 1-based row numbering | Matches user expectation (row 1 = first data row) | 02-05 |
| Max 1000 rows per query | Prevent memory exhaustion from large result sets | 02-05 |
| Block dangerous SQL keywords | Security: prevent unintended data modification | 02-05 |

### Discovered TODOs

None.

### Active Blockers

None.

### Technical Debt

None accumulated.

---

## Phase 1 Completion Summary

Phase 1 delivered the complete foundation layer:

| Plan | Name | Key Artifacts |
|------|------|---------------|
| 01-01 | Database Models | Job, JobRow, AuditLog models with SQLAlchemy 2.0 |
| 01-02 | Job Service | JobService with state machine, row tracking |
| 01-03 | Audit Service | AuditService with redaction, export |
| 01-04 | Error Handling | Error registry, UPS translation, formatting |
| 01-05 | API Endpoints | FastAPI REST API with job CRUD, log export |

---

## Phase 2 Completion Summary

Phase 2 delivered the Data Source MCP with 12 tools:

| Plan | Name | Key Artifacts |
|------|------|---------------|
| 02-01 | MCP Foundation | FastMCP server, Pydantic models, BaseSourceAdapter ABC |
| 02-02 | CSV Import | CSVAdapter, import_csv tool with schema discovery |
| 02-03 | Excel Import | ExcelAdapter, import_excel, list_sheets tools |
| 02-04 | Database Import | DatabaseAdapter, import_database, list_tables tools |
| 02-05 | Query Tools | get_schema, override_column_type, get_row, get_rows_by_filter, query_data, compute_checksums, verify_checksum |
| 02-06 | Integration Tests | 61 tests, requirement coverage verification |

**MCP Tools (12 total):**
- Import: import_csv, import_excel, import_database
- Discovery: list_sheets, list_tables
- Schema: get_schema, override_column_type
- Query: get_row, get_rows_by_filter, query_data
- Integrity: compute_checksums, verify_checksum

---

## Session Continuity

### Last Session

**Date:** 2026-01-24
**Action:** Completed Phase 2 (Data Source MCP)
**Outcome:** 12 MCP tools, 61 passing tests, all requirements verified (DATA-01, DATA-02, DATA-03, DATA-05, ORCH-02)

### Next Session

**Resume with:** `/gsd:discuss-phase 3` to gather context for UPS Integration MCP
**Context needed:** None - STATE.md contains full context

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `/gsd:progress` | Check current status |
| `/gsd:discuss-phase 3` | Gather context for Phase 3 |
| `/gsd:plan-phase 3` | Create detailed plan for Phase 3 |
| `/gsd:execute-phase 3` | Execute Phase 3 plans |
| `/gsd:debug [issue]` | Debug specific problem |

---

*Last updated: 2026-01-24*
