---
phase: 04
plan: 02
subsystem: nl-engine
tags: [nlp, sql, filter, claude-api, structured-outputs]
dependency-graph:
  requires: [04-01]
  provides: [filter-generator, sql-validation]
  affects: [04-03, 04-04]
tech-stack:
  added: [sqlglot]
  patterns: [schema-grounded-generation, structured-outputs-tool-use]
key-files:
  created:
    - src/orchestrator/models/filter.py
    - src/orchestrator/nl_engine/filter_generator.py
    - tests/orchestrator/test_filter_generator.py
  modified:
    - src/orchestrator/nl_engine/__init__.py
    - pyproject.toml
decisions:
  - id: sqlglot-for-validation
    decision: Use sqlglot for SQL syntax validation
    rationale: Proper SQL parser catches real errors, prevents injection
  - id: tool-use-for-structured
    decision: Use Claude tool_use instead of beta.messages.parse
    rationale: Tool use provides reliable structured output extraction
  - id: token-error-handling
    decision: Catch both ParseError and TokenError from sqlglot
    rationale: TokenError raised for lexical errors like unclosed strings
metrics:
  duration: 5m30s
  completed: 2026-01-25
---

# Phase 4 Plan 2: Filter Generator Summary

**One-liner:** Schema-grounded SQL WHERE clause generation using Claude structured outputs with sqlglot validation.

---

## What Was Built

This plan implemented the filter generation subsystem that converts natural language filter expressions into validated SQL WHERE clauses. The system is schema-grounded to prevent column hallucination.

### Components Created

1. **Filter Models** (`src/orchestrator/models/filter.py`)
   - `ColumnInfo`: Schema column metadata for grounding (name, type, nullable, sample_values)
   - `SQLFilterResult`: Generated filter result (where_clause, columns_used, needs_clarification)
   - `FilterGenerationError`: Custom exception with context

2. **Filter Generator** (`src/orchestrator/nl_engine/filter_generator.py`)
   - `validate_sql_syntax()`: Uses sqlglot to validate SQL syntax
   - `generate_filter()`: Schema-grounded NL to SQL conversion using Claude
   - Helper functions for column type identification and temporal detection
   - Post-generation validation of columns against schema

3. **Unit Tests** (`tests/orchestrator/test_filter_generator.py`)
   - 34 unit tests covering SQL validation, model construction, and helpers
   - 6 integration tests (skipped without ANTHROPIC_API_KEY)

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| sqlglot for SQL validation | Proper SQL parser catches syntax errors; regex would miss edge cases |
| Claude tool_use pattern | Reliable structured output extraction vs beta structured outputs |
| Catch TokenError + ParseError | sqlglot raises TokenError for lexical errors (unclosed strings) |
| Schema grounding in prompt | Prevents LLM from hallucinating column names |
| Post-generation column validation | Double-check even with grounded prompt |

---

## Verification Results

| Check | Result |
|-------|--------|
| `from src.orchestrator.models.filter import SQLFilterResult` | PASSED |
| `from src.orchestrator.nl_engine.filter_generator import generate_filter` | PASSED |
| Unit tests pass (34 tests) | PASSED |
| validate_sql_syntax validates/rejects correctly | PASSED |

---

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `4ad4bd9` | feat | Create filter models for SQL generation |
| `e3661d1` | feat | Implement schema-grounded filter generator |
| `d778b31` | test | Add unit tests for filter generation (34 tests) |

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TokenError not caught in validate_sql_syntax**
- **Found during:** Task 3 test execution
- **Issue:** sqlglot raises `TokenError` for lexical errors (unclosed strings), not just `ParseError`
- **Fix:** Added `TokenError` to exception handling in `validate_sql_syntax()`
- **Files modified:** `src/orchestrator/nl_engine/filter_generator.py`
- **Commit:** `d778b31`

---

## Dependencies Added

| Package | Version | Purpose |
|---------|---------|---------|
| sqlglot | >=26.0.0 | SQL syntax validation and parsing |
| anthropic | >=0.42.0 | Claude API client for structured outputs |

---

## Next Phase Readiness

**Ready for 04-03 (Mapping Template Generator)**

Prerequisites satisfied:
- Filter models available for reuse
- Structured output pattern established
- Schema grounding approach validated

No blockers identified.

---

*Completed: 2026-01-25 | Duration: 5m30s*
