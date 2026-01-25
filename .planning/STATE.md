# ShipAgent State

## Project Reference

**Core Value:** Users issue NL commands like "Ship all California orders using UPS Ground" and system creates shipments via UPS API without data loss.

**Architecture:** LLM as Configuration Engine - generates templates, deterministic code executes on data.

**Current Focus:** Phase 4 In Progress (Natural Language and Mapping Engine)

---

## Current Position

**Phase:** 4 of 7 (Natural Language and Mapping Engine) - IN PROGRESS
**Plan:** 6 of 7 complete (04-01 through 04-06)
**Status:** In progress
**Last activity:** 2026-01-25 - Completed 04-05-PLAN.md (Self-Correction Loop)

```
Progress: [###############-----] 70%
Phase 4 of 7 | Plan 6 of 7 complete | 24/26 total plans
```

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Plans Completed | 24 |
| Plans Failed | 0 |
| Success Rate | 100% |
| Phases Completed | 3 / 7 |

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
| Manual Zod schemas over auto-generation | openapi-zod-client produces TS inference errors; manual schemas are cleaner | 03-01 |
| Removed .passthrough() from wrapper schemas | Deep nesting with passthrough causes TypeScript complexity errors | 03-01 |
| Sandbox environment only | Per CONTEXT.md Decision 1, production support is out of scope for MVP | 03-01 |
| 60-second token buffer | Token refresh 60s before expiry provides safety margin for network latency | 03-02 |
| No retry on 4xx errors | Client errors fail immediately; retrying won't fix request problems | 03-02 |
| UPS transaction headers required | transId (UUID) and transactionSrc included in all API requests | 03-02 |
| Zod schema for MCP tools | MCP SDK expects Zod schemas for parameter validation, not JSON Schema | 03-03 |
| Service name mapping | Map UPS service codes to human-readable names for better UX | 03-03 |
| Package-level itemized charges | Extract fuel/delivery/residential surcharges from RatedPackage | 03-03 |
| PDF only labels | Per CONTEXT.md Decision 3, simplified implementation with single format | 03-04 |
| Tracking number as filename | Label files saved as {tracking_number}.pdf for easy lookup | 03-04 |
| Overwrite existing labels | shipping_get_label overwrites existing file for reprints | 03-04 |
| Address tool separate | address_validate is standalone, users compose into workflow | 03-05 |
| XAV status enum | Use 'valid', 'ambiguous', 'invalid' mapping to UPS indicators | 03-05 |
| ZIP+4 formatting | Extended postal codes formatted as ZIP-4 (e.g., 90001-1234) | 03-05 |
| tool_choice for structured output | Use Claude tool_choice instead of beta.messages.parse for structured outputs | 04-01 |
| sqlglot for SQL validation | Proper SQL parser catches real errors, prevents injection | 04-02 |
| Catch TokenError + ParseError | sqlglot raises TokenError for lexical errors like unclosed strings | 04-02 |
| Schema grounding in prompt | Prevents LLM from hallucinating column names | 04-02 |
| Draft7Validator for JSON Schema | Widely supported, sufficient for UPS schema features | 04-04 |
| Collect ALL errors via iter_errors() | Users need complete error list for efficient fixing | 04-04 |
| ValidationError with full context | Per CONTEXT.md Decision 4: specific field, expected, actual, rule | 04-04 |
| Default value before transformation | Apply default_value filter before transformation filters to handle None | 04-03 |
| TYPE_CHECKING for ValidationError import | Avoid circular import between correction.py and template_validator.py | 04-05 |
| Max attempts clamped to 1-5 | Prevent infinite loops while allowing user configuration | 04-05 |
| 5 elicitation templates from CONTEXT.md | Cover common scenarios: date column, weight, dimensions, big, service | 04-06 |
| Max 4 questions per elicitation | Per Claude Agent SDK documentation limits | 04-06 |
| Schema customization for question options | Replace generic options with actual columns from source data | 04-06 |

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

## Phase 3 Completion Summary

Phase 3 delivered the UPS Integration MCP with 6 MCP tools:

| Plan | Name | Key Artifacts |
|------|------|---------------|
| 03-01 | TypeScript Package & Schema Foundation | @shipagent/ups-mcp package, Zod schemas, config validation |
| 03-02 | OAuth Authentication | UpsAuthManager, UpsApiClient, error types, 11 unit tests |
| 03-03 | Rating Tools | rating_quote, rating_shop tools, 15 unit tests |
| 03-04 | Shipping Tools | shipping_create, shipping_void, shipping_get_label, 13 unit tests |
| 03-05 | Address Validation | address_validate tool, 15 unit tests |
| 03-06 | Integration Tests | 7 integration tests (smoke tested), 54 unit tests total |

**MCP Tools (6 total):**
- Rating: rating_quote, rating_shop
- Shipping: shipping_create, shipping_void, shipping_get_label
- Address: address_validate

**Note:** Full integration testing with UPS sandbox API pending credentials. Smoke test verified: build passes, 54 unit tests pass, integration tests skip gracefully without credentials

---

## Session Continuity

### Last Session

**Date:** 2026-01-25
**Action:** Completed 04-05-PLAN.md (Self-Correction Loop)
**Outcome:** LLM-powered template correction with 3-attempt retry, MaxCorrectionsExceeded with 4 user options, 28 unit tests passing.

### Next Session

**Resume with:** `/gsd:execute-phase 4` to complete Phase 4 (04-07 End-to-End Pipeline)
**Context needed:** None - STATE.md contains full context

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `/gsd:progress` | Check current status |
| `/gsd:discuss-phase 4` | Gather context for Phase 4 |
| `/gsd:plan-phase 4` | Create detailed plan for Phase 4 |
| `/gsd:execute-phase 4` | Execute Phase 4 plans |
| `/gsd:debug [issue]` | Debug specific problem |

---

*Last updated: 2026-01-25*
