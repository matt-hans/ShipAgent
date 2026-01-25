---
phase: 04-nl-mapping-engine
plan: 04
subsystem: nl-engine
tags: [validation, json-schema, jinja2, ups-api]

dependency-graph:
  requires:
    - 03-01 (UPS Zod schemas)
    - 04-03 (Mapping template generator)
  provides:
    - Template validation before UPS API calls
    - UPS JSON Schema definitions for Python
    - Field-level error reporting
  affects:
    - 04-05 (Self-correction loop uses validation errors)
    - 04-06 (Batch execution validates before each call)

tech-stack:
  added:
    - jsonschema>=4.0.0
  patterns:
    - JSON Schema Draft 7 validation
    - Pydantic models for validation results

key-files:
  created:
    - src/orchestrator/nl_engine/ups_schema.py
    - src/orchestrator/nl_engine/template_validator.py
    - tests/orchestrator/test_template_validator.py
  modified:
    - pyproject.toml (added jsonschema dependency)
    - src/orchestrator/nl_engine/__init__.py (exports)

decisions:
  - name: "Draft7Validator for JSON Schema"
    rationale: "Widely supported, sufficient for UPS schema features"
    alternatives: ["Draft4", "Draft2020"]
  - name: "Collect ALL errors via iter_errors()"
    rationale: "Users need complete error list for efficient fixing"
    alternatives: ["Fail fast on first error"]
  - name: "ValidationError with full context"
    rationale: "Per CONTEXT.md Decision 4: specific field, expected, actual, rule"
    alternatives: ["Simple error message string"]

metrics:
  duration: "5 minutes"
  completed: "2026-01-25"
---

# Phase 4 Plan 04: Template Validation Summary

**One-liner:** JSON Schema validation of Jinja2 template outputs against UPS API requirements with full error context.

## What Was Built

### 1. UPS JSON Schema Definitions (`ups_schema.py`)

Translated Zod schemas from Phase 3 (`packages/ups-mcp/src/generated/shipping.ts`) into Python JSON Schema format:

| Schema | Properties | Required Fields |
|--------|------------|-----------------|
| `UPS_PHONE_SCHEMA` | 2 | Number |
| `UPS_ADDRESS_SCHEMA` | 6 | AddressLine, City, CountryCode |
| `UPS_SHIPTO_SCHEMA` | 9 | Name, Address |
| `UPS_SHIPPER_SCHEMA` | 9 | Name, ShipperNumber, Address |
| `UPS_PACKAGE_SCHEMA` | 6 | Packaging, PackageWeight |
| `UPS_SERVICE_SCHEMA` | 2 | Code |
| `UPS_SHIPMENT_SCHEMA` | 8 | Shipper, ShipTo, PaymentInformation, Service, Package |

**Schema Registry:** `SCHEMA_REGISTRY` provides direct lookup by schema name.

**Path-Based Lookup:** `get_schema_for_path()` supports nested paths like "ShipTo.Address.City".

### 2. Template Output Validator (`template_validator.py`)

**Core Functions:**

```python
# Validate full template output
result = validate_template_output(rendered_output, UPS_SHIPTO_SCHEMA)

# Validate single field during template building
result = validate_field_value(phone_data, "Phone")

# Format errors for display
message = format_validation_errors(result)
```

**ValidationError Model:**
- `path`: JSONPath to failing field (e.g., "ShipTo.Phone.Number")
- `message`: Human-readable error description
- `expected`: What was expected (type, format, constraint)
- `actual`: What was received
- `schema_rule`: Which rule was violated (required, maxLength, type, etc.)

**Error Collection:** Uses `Draft7Validator.iter_errors()` to collect ALL errors, not just the first.

**Formatted Output Example (per CONTEXT.md Decision 4):**
```
Validation failed with 2 error(s):

Error 1: ShipTo.Phone.Number
  Expected: string with at least 1 character(s)
  Got: ''
  Rule: minLength

Error 2: ShipTo.Address.City
  Expected: required field (missing: ['AddressLine', 'City', 'CountryCode'])
  Got: "object with keys: ['AddressLine', 'CountryCode']"
  Rule: required
```

### 3. Test Coverage

**50 unit tests** organized in 7 test classes:

| Test Class | Tests | Coverage |
|------------|-------|----------|
| `TestUPSSchemas` | 21 | Phone, Address, ShipTo, Package, Service schemas |
| `TestValidateTemplateOutput` | 7 | Main validation function |
| `TestValidateFieldValue` | 6 | Incremental field validation |
| `TestFormatValidationErrors` | 6 | Error formatting per CONTEXT.md |
| `TestValidationResult` | 3 | Result model behavior |
| `TestTemplateValidationError` | 2 | Exception handling |
| `TestGetSchemaForPath` | 5 | Schema registry lookup |

## Key Implementation Details

### JSON Schema Translation

Zod schemas were translated with equivalent constraints:
- `z.string().min(1).max(15)` -> `{"type": "string", "minLength": 1, "maxLength": 15}`
- `z.array(z.string()).min(1).max(3)` -> `{"type": "array", "items": {...}, "minItems": 1, "maxItems": 3}`
- `z.string().length(2)` -> `{"type": "string", "minLength": 2, "maxLength": 2}`

### oneOf Handling

For union types like Package (single or array), used JSON Schema `oneOf`:
```python
"Package": {
    "oneOf": [
        UPS_PACKAGE_SCHEMA,
        {"type": "array", "items": UPS_PACKAGE_SCHEMA},
    ]
}
```

### Nested Path Resolution

`get_schema_for_path()` navigates through schema hierarchy:
```python
# "ShipTo.Address.City" -> navigate ShipTo -> Address -> properties -> City
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `529485b` | feat | Add UPS JSON Schema definitions |
| `6a52d2d` | feat | Implement template output validator |
| `c2e8e08` | test | Add comprehensive template validation tests |

## Integration Points

### Downstream Usage (04-05 Self-Correction Loop)

```python
from src.orchestrator.nl_engine import validate_template_output, format_validation_errors

# In self-correction loop
result = validate_template_output(rendered, UPS_SHIPMENT_SCHEMA)
if not result.valid:
    error_message = format_validation_errors(result)
    # Feed error_message to LLM for template fix
```

### Exported from `nl_engine/__init__.py`

```python
from src.orchestrator.nl_engine import (
    validate_template_output,
    validate_field_value,
    format_validation_errors,
    ValidationResult,
    ValidationError,
    TemplateValidationError,
    UPS_SHIPTO_SCHEMA,
    UPS_PACKAGE_SCHEMA,
    UPS_SHIPMENT_SCHEMA,
    get_schema_for_path,
)
```

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**Prerequisites for 04-05 (Self-Correction Loop):**
- validate_template_output returns structured errors
- format_validation_errors produces LLM-readable output
- All schema types validated and tested

**No blockers identified.**
