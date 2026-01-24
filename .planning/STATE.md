# ShipAgent State

## Project Reference

**Core Value:** Users issue NL commands like "Ship all California orders using UPS Ground" and system creates shipments via UPS API without data loss.

**Architecture:** LLM as Configuration Engine - generates templates, deterministic code executes on data.

**Current Focus:** Phase 2 in progress - Data Source MCP

---

## Current Position

**Phase:** 2 of 7 (Data Source MCP)
**Plan:** 4 of 6 complete
**Status:** In progress

```
Progress: [########--] 85%
Phase 2 of 7 | Plan 4 of 6 complete
```

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Plans Completed | 9 |
| Plans Failed | 0 |
| Success Rate | 100% |
| Phases Completed | 1 / 7 |

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

## Phase 2 Progress

| Plan | Name | Status |
|------|------|--------|
| 02-01 | MCP Foundation | Complete |
| 02-02 | CSV Import Tools | Complete |
| 02-03 | Excel Import Tools | Complete |
| 02-04 | Database Import Tools | Complete |
| 02-05 | Query Tools | Pending |
| 02-06 | Integration Tests | Pending |

---

## Session Continuity

### Last Session

**Date:** 2026-01-24
**Action:** Completed 02-04-PLAN.md (Database Import Tools)
**Outcome:** DatabaseAdapter with PostgreSQL/MySQL support, list_tables and import_database MCP tools, 19 tests passing

### Next Session

**Resume with:** `/gsd:execute-phase 2` to continue with 02-05 Query Tools
**Context needed:** None - STATE.md contains full context

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `/gsd:progress` | Check current status |
| `/gsd:plan-phase 2` | Create detailed plan for Phase 2 |
| `/gsd:execute-phase 2` | Execute Phase 2 plans |
| `/gsd:debug [issue]` | Debug specific problem |

---

*Last updated: 2026-01-24*
