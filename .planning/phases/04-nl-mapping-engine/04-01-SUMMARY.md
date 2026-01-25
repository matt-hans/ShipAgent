---
phase: 04-nl-mapping-engine
plan: 01
subsystem: orchestrator.nl_engine
tags:
  - intent-parsing
  - structured-outputs
  - service-codes
  - pydantic

dependency-graph:
  requires:
    - "phase-03: UPS service codes reference"
  provides:
    - ShippingIntent model for NL command parsing
    - ServiceCode enum with 5 UPS service types
    - SERVICE_ALIASES dict for user-friendly term resolution
    - parse_intent function using Claude structured outputs
  affects:
    - "04-02: Filter generator uses FilterCriteria"
    - "04-03: Mapping generator uses parsed intents"

tech-stack:
  added:
    - anthropic (Claude API client)
    - sqlglot (SQL syntax validation)
  patterns:
    - Claude tool_choice for guaranteed structured output
    - Pydantic models as structured output schemas

key-files:
  created:
    - src/orchestrator/models/intent.py
    - src/orchestrator/nl_engine/intent_parser.py
    - tests/orchestrator/test_intent_parser.py
    - tests/orchestrator/__init__.py
  modified:
    - src/orchestrator/__init__.py
    - src/orchestrator/models/__init__.py
    - src/orchestrator/nl_engine/__init__.py

decisions:
  - id: tool-choice-for-structured-output
    description: Use Claude tool_choice instead of beta.messages.parse for structured outputs
    rationale: More reliable with current SDK; tool_choice guarantees schema adherence

metrics:
  duration: 5m
  completed: 2026-01-25
---

# Phase 04 Plan 01: Intent Parsing Foundation Summary

Intent parsing foundation using Claude structured outputs with 19 service aliases and 49 unit tests.

## What Was Built

### Core Components

1. **ShippingIntent Model** (`src/orchestrator/models/intent.py`)
   - Pydantic model for parsed NL commands
   - Fields: action, data_source, service_code, filter_criteria, row_qualifier, package_defaults
   - Actions supported: ship, rate, validate_address

2. **ServiceCode Enum**
   - 5 UPS service types: GROUND (03), NEXT_DAY_AIR (01), SECOND_DAY_AIR (02), THREE_DAY_SELECT (12), NEXT_DAY_AIR_SAVER (13)
   - String-based enum for JSON serialization

3. **SERVICE_ALIASES Dict**
   - 19 user-friendly aliases mapped to ServiceCode
   - Covers all aliases from CONTEXT.md (ground, overnight, 2-day, 3-day, saver, etc.)
   - Case-insensitive lookup with whitespace handling

4. **parse_intent Function** (`src/orchestrator/nl_engine/intent_parser.py`)
   - Uses Claude API with tool_choice for structured output
   - System prompt includes service aliases, current date, available sources
   - Extracts action, data_source, service_code, filter_criteria, row_qualifier

5. **resolve_service_code Function**
   - Resolves aliases and direct codes to ServiceCode enum
   - Handles case-insensitive input with whitespace stripping
   - Raises ValueError for unknown services

### Supporting Models

- **FilterCriteria**: Raw expression, filter type, clarification needs
- **RowQualifier**: Batch qualifiers (first N, last N, random, every_nth, all)
- **IntentParseError**: Custom exception with suggestions

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Use tool_choice instead of beta.messages.parse | More reliable with current SDK version; guarantees schema adherence |
| 19 service aliases covering all CONTEXT.md terms | Comprehensive coverage of user-friendly shipping terms |
| Case-insensitive alias resolution | Better UX - users don't need exact casing |
| Pydantic ConfigDict(from_attributes=True) | Enables ORM model serialization per project pattern |

## Test Coverage

| Test Class | Tests | Coverage |
|------------|-------|----------|
| TestServiceCodeResolution | 26 | All aliases and direct codes |
| TestShippingIntentModel | 5 | Model validation |
| TestRowQualifierModel | 9 | Batch qualifiers |
| TestFilterCriteriaModel | 6 | Filter types |
| TestIntentParseError | 3 | Error handling |
| **Total** | **49** | **Unit tests passing** |

Integration tests skip gracefully without ANTHROPIC_API_KEY.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

1. `from src.orchestrator.models.intent import ShippingIntent, ServiceCode` - SUCCESS
2. `from src.orchestrator.nl_engine.intent_parser import parse_intent` - SUCCESS
3. `pytest tests/orchestrator/test_intent_parser.py -k "not Integration"` - 49 passed
4. SERVICE_ALIASES contains all 9 required aliases from CONTEXT.md - SUCCESS

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| 6a22a19 | feat | Create orchestrator package with intent models |
| baacf87 | feat | Implement intent parser with Claude structured outputs |
| 8f979d8 | test | Add unit tests for intent parsing |

## Next Phase Readiness

**Ready for 04-02: Filter Generator**

Prerequisites delivered:
- FilterCriteria model for filter expression representation
- ColumnInfo model already exists in filter.py
- SQLFilterResult model ready for use
- filter_generator.py already exists (from prior work)

No blockers identified.
