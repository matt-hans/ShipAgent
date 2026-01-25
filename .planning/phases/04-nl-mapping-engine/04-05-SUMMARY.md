---
phase: 04-nl-mapping-engine
plan: 05
subsystem: nl-engine
tags: [self-correction, validation, llm, retry-loop]

dependency-graph:
  requires:
    - 04-03 (Mapping template generator)
    - 04-04 (Template validator)
  provides:
    - Automatic template fixing via LLM
    - Retry loop with configurable max attempts
    - User escalation after max failures
  affects:
    - 04-07 (End-to-end pipeline uses self-correction)
    - 05 (Batch execution uses self-correction for template issues)

tech-stack:
  added: []
  patterns:
    - LLM-based error correction
    - Retry with exponential feedback
    - Exception-based control flow for escalation

key-files:
  created:
    - src/orchestrator/models/correction.py
    - src/orchestrator/nl_engine/self_correction.py
    - tests/orchestrator/test_self_correction.py
  modified:
    - src/orchestrator/models/__init__.py (exports correction models)
    - src/orchestrator/nl_engine/__init__.py (exports self-correction)

decisions:
  - name: "TYPE_CHECKING for ValidationError import"
    rationale: "Avoid circular import between correction.py and template_validator.py"
    alternatives: ["Define local ValidationError in correction.py"]
  - name: "Any type for validation_errors in CorrectionAttempt"
    rationale: "Runtime flexibility while avoiding import issues"
    alternatives: ["Strict typing with deferred imports"]
  - name: "Max attempts clamped to 1-5"
    rationale: "Prevent infinite loops while allowing user configuration"
    alternatives: ["No upper bound"]

metrics:
  duration: "6 minutes"
  completed: "2026-01-25"
---

# Phase 4 Plan 05: Self-Correction Loop Summary

**One-liner:** Automatic LLM-powered template fixing with 3-attempt retry and user escalation options.

## What Was Built

### 1. Correction Models (`correction.py`)

Pydantic models for tracking self-correction state:

| Model | Purpose |
|-------|---------|
| `CorrectionAttempt` | Records single correction attempt with template, errors, changes |
| `CorrectionResult` | Aggregates all attempts with success/failure outcome |
| `CorrectionOptions` | Enum with 4 user options after max failures |
| `MaxCorrectionsExceeded` | Exception raised when max attempts exhausted |

**CorrectionOptions values (per CONTEXT.md Decision 4):**
- `correct_source`: User fixes source data
- `manual_fix`: User provides manual template fix
- `skip_problematic`: Skip failing rows
- `abort`: Cancel the operation

### 2. Self-Correction Functions (`self_correction.py`)

**Core Functions:**

```python
# Format errors for LLM consumption
formatted = format_errors_for_llm(errors)
# -> "Error 1: Field 'ShipTo.Phone.Number'\n  Expected: 10-digit...\n  Fix: Use to_ups_phone()..."

# Extract template from LLM response
template = extract_template_from_response(response_text)
# -> Handles ```jinja2, ```json, ``` blocks

# Single correction attempt via Claude API
attempt = attempt_correction(template, errors, source_schema)

# Full correction loop
result = self_correction_loop(
    template=template,
    source_schema=schema,
    target_schema=UPS_SHIPTO_SCHEMA,
    sample_data={"name": "John"},
    max_attempts=3
)

# Format user feedback
feedback = format_user_feedback(attempt, max_attempts=3)
```

**Correction Loop Flow:**
1. Render template with sample/mock data
2. Validate against UPS JSON Schema
3. If valid: return success
4. If invalid: call Claude to fix template
5. Repeat up to max_attempts
6. If still invalid: raise MaxCorrectionsExceeded with options

**User Feedback Format (per CONTEXT.md Decision 4):**
```
Template validation failed (attempt 2 of 3)
Error: Field 'ShipTo.Phone.Number' - invalid format
  Expected: 10-digit US phone number
  Got: '555-1234'

Attempting correction...
```

### 3. Test Coverage

**28 unit tests** organized in 7 test classes:

| Test Class | Tests | Coverage |
|------------|-------|----------|
| `TestCorrectionModels` | 5 | Model creation and validation |
| `TestFormatErrorsForLLM` | 5 | Error formatting with suggestions |
| `TestExtractTemplate` | 6 | Template extraction from responses |
| `TestMaxCorrectionsExceeded` | 4 | Exception handling and options |
| `TestUserFeedback` | 4 | User-facing feedback formatting |
| `TestSelfCorrectionLoopUnit` | 4 | Loop behavior with mocked API |
| `TestSelfCorrectionLoopIntegration` | 2 | Real API tests (skip without key) |

## Key Implementation Details

### Fix Suggestions by Error Type

The `format_errors_for_llm` function includes actionable fix suggestions:

| Path/Rule | Suggested Fix |
|-----------|---------------|
| Phone fields | Use to_ups_phone() filter |
| PostalCode | Use format_us_zip() filter |
| Address maxLength | Use truncate_address(35) |
| Name maxLength | Use truncate_address(35) |
| Weight fields | Use round_weight() and convert_weight() |
| required rule | Map source column or add default_value() |

### Template Extraction

Handles multiple response formats:
- `\`\`\`jinja2` blocks (primary)
- `\`\`\`json` blocks
- Plain `\`\`\`` blocks
- Raw JSON objects in response
- Full response as fallback

### Claude API Integration

System prompt instructs Claude to:
1. Only change what's necessary
2. Use available logistics filters
3. Apply default_value BEFORE transformations
4. Return only the corrected template

Model used: `claude-sonnet-4-20250514`

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `ae9d612` | feat | Create correction models for self-correction tracking |
| `cda1cc7` | feat | Implement self-correction loop for template validation |
| `26e9d26` | test | Add comprehensive self-correction tests |

## Exports

### From `models/__init__.py`:
```python
from src.orchestrator.models import (
    CorrectionAttempt,
    CorrectionResult,
    CorrectionOptions,
    MaxCorrectionsExceeded,
)
```

### From `nl_engine/__init__.py`:
```python
from src.orchestrator.nl_engine import (
    self_correction_loop,
    format_errors_for_llm,
    extract_template_from_response,
    format_user_feedback,
    MaxCorrectionsExceeded,
)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed circular import**
- **Found during:** Task 2 verification
- **Issue:** correction.py imported ValidationError from template_validator.py, which imported from nl_engine/__init__.py, which imported from self_correction.py, which imported from correction.py
- **Fix:** Used TYPE_CHECKING for ValidationError import, changed validation_errors type to Any at runtime
- **Files modified:** src/orchestrator/models/correction.py
- **Commit:** cda1cc7

## Next Phase Readiness

**Prerequisites for 04-07 (End-to-End Pipeline):**
- self_correction_loop validates and fixes templates automatically
- MaxCorrectionsExceeded provides user escalation path
- format_user_feedback produces clear progress updates
- All 4 correction options available per CONTEXT.md

**No blockers identified.**
