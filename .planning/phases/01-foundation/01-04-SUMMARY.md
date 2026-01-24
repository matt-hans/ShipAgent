---
phase: 01-foundation
plan: 04
subsystem: error-handling
tags: [errors, validation, ups-api, user-feedback]

dependency-graph:
  requires:
    - 01-01-PLAN (database infrastructure for error logging)
  provides:
    - error-code-registry
    - ups-error-translation
    - error-formatting-utilities
  affects:
    - 01-02-PLAN (audit logging can use error codes)
    - 03-* (UPS MCP uses error translation)
    - 06-* (batch executor uses error grouping)

tech-stack:
  added: []
  patterns:
    - error-code-registry
    - error-translation-layer
    - error-grouping-pattern

key-files:
  created:
    - src/errors/__init__.py
    - src/errors/registry.py
    - src/errors/ups_translation.py
    - src/errors/formatter.py
  modified: []

decisions:
  - id: D-01-04-001
    description: E-XXXX error code format with category prefixes
    rationale: E-1xxx data, E-2xxx validation, E-3xxx UPS, E-4xxx system, E-5xxx auth for logical grouping
  - id: D-01-04-002
    description: ErrorCode dataclass with message templates
    rationale: Consistent structure with placeholder substitution for context-specific messages
  - id: D-01-04-003
    description: Dual lookup strategy for UPS errors
    rationale: Direct code mapping first, pattern matching fallback for unknown codes

metrics:
  duration: 5 minutes
  completed: 2026-01-24
---

# Phase 01 Plan 04: Error Handling Framework Summary

**One-liner:** Error code registry with E-XXXX format, UPS API error translation, and error grouping utilities for user-friendly batch processing feedback.

## What Was Built

### 1. Error Code Registry (`src/errors/registry.py`)
Defines 18 error codes across 5 categories:

| Category | Range | Count | Examples |
|----------|-------|-------|----------|
| DATA | E-1xxx | 3 | Missing field, empty source, invalid type |
| VALIDATION | E-2xxx | 5 | Invalid ZIP, state, phone, weight, address length |
| UPS_API | E-3xxx | 5 | Service unavailable, rate limit, address validation, service not available |
| SYSTEM | E-4xxx | 3 | Database error, file system, template error |
| AUTH | E-5xxx | 2 | Authentication failed, token expired |

Each ErrorCode includes:
- `code`: E-XXXX format identifier
- `category`: ErrorCategory enum value
- `title`: Short display title
- `message_template`: Message with {placeholder} syntax
- `remediation`: Actionable steps for user
- `is_retryable`: Boolean for retry logic

### 2. UPS Error Translation (`src/errors/ups_translation.py`)
Maps UPS API errors to ShipAgent error codes:

**Direct Code Mapping (17 UPS codes):**
- Address validation: 120100-120104 -> E-3003
- Service availability: 111030, 111050, 111057 -> E-3004
- Weight/dimensions: 120500-120502 -> E-2004
- Authentication: 250001-250003 -> E-5001, E-5002
- System: 190001, 190002, 190100 -> E-3001, E-3002

**Pattern Matching (7 patterns):**
- "invalid zip", "invalid postal" -> E-2001
- "address not found" -> E-3003
- "service unavailable" -> E-3001
- "rate limit" -> E-3002
- "unauthorized" -> E-5001
- "token expired" -> E-5002

**Response Extraction:**
- Handles 3 UPS response formats: errors[], response.errors[], Fault.detail

### 3. Error Formatter (`src/errors/formatter.py`)
Provides error display and grouping:

**ShipAgentError Exception:**
- Inherits from Exception
- Factory method `from_code()` for registry-based creation
- Tracks affected rows, columns, and retry status

**Formatting Functions:**
- `format_error()`: Single error with location and remediation
- `group_errors()`: Combines duplicates by code+message
- `format_error_summary()`: Multi-error summary for display

## Commits

| Hash | Type | Description |
|------|------|-------------|
| a97a232 | feat | Create error code registry |
| 69bb42f | feat | Create UPS error translation map |
| 80cda8c | feat | Create error formatter and grouping utilities |

## Verification Results

All success criteria verified:
1. Error codes follow E-XXXX format (regex validated)
2. Registry contains all 5 categories (DATA, VALIDATION, UPS_API, SYSTEM, AUTH)
3. UPS error codes translate correctly (120100 -> E-3003)
4. Pattern matching catches UPS errors without known codes
5. ShipAgentError.from_code() creates errors with context substitution
6. Error grouping combines duplicates across rows
7. Formatted output is clear and actionable

**Integration Test Output:**
```
1. Testing error registry:
   E-2001: Invalid ZIP Code
   Category: validation
   Total errors defined: 18

2. Testing UPS error translation:
   UPS 120100 -> E-3003
   Pattern match -> E-2001

3. Testing ShipAgentError:
   Created: E-2001: Invalid ZIP code format in row 5...

4. Testing error formatting:
   E-2001: Invalid ZIP code in row 5
   Location: Row 5
   Column: zip_code
   Action: Use 5 or 9 digit ZIP.

5. Testing error grouping:
   4 errors grouped into 2 unique errors
   ZIP error affects rows: [1, 3, 5]

6. Testing error summary:
   2 error type(s) found...

7. Testing UPS response extraction:
   Extracted: code=120100, message=Invalid postal code
```

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**Ready for:**
- 01-02-PLAN (Audit Logging) - can log with error codes
- 01-03-PLAN (Job Service) - can track job errors
- 03-* (UPS MCP) - error translation ready
- 06-* (Batch Executor) - error grouping ready

**Dependencies satisfied:**
- Error code registry with 18 defined errors
- UPS error translation with code + pattern matching
- Error formatting with grouping for batch display

## Usage Examples

```python
# Get error definition from registry
from src.errors import get_error
e = get_error('E-2001')
print(f'{e.code}: {e.title}')  # E-2001: Invalid ZIP Code

# Translate UPS API error
from src.errors import translate_ups_error
code, msg, remedy = translate_ups_error('120100', 'Address validation failed', {'row': 5})
print(f'{code}: {msg}')  # E-3003: UPS could not validate address in row 5.

# Create error from registry
from src.errors import ShipAgentError
err = ShipAgentError.from_code('E-2001', row=5, column='zip_code', value='1234')
print(err)  # E-2001: Invalid ZIP code format in row 5, column 'zip_code'. Value: '1234'.

# Group and format batch errors
from src.errors import format_error_summary, ShipAgentError
errors = [
    ShipAgentError(code='E-2001', message='Invalid ZIP', remediation='Fix ZIP', rows=[1]),
    ShipAgentError(code='E-2001', message='Invalid ZIP', remediation='Fix ZIP', rows=[3]),
]
print(format_error_summary(errors))
# Output shows grouped errors with affected rows [1, 3]
```

---

*Completed: 2026-01-24*
*Duration: 5 minutes*
