---
phase: 04-nl-mapping-engine
plan: 03
subsystem: orchestrator.nl_engine
tags:
  - mapping-templates
  - jinja2-filters
  - logistics-transformations
  - pydantic

dependency-graph:
  requires:
    - "phase-03: UPS service codes reference"
    - "04-01: ServiceCode enum, SERVICE_ALIASES"
  provides:
    - Jinja2 logistics filter library with 9 filters
    - FieldMapping and MappingTemplate Pydantic models
    - generate_mapping_template function for template creation
    - compute_schema_hash for order-independent schema matching
    - render_template for applying templates to row data
    - suggest_mappings for LLM-powered mapping suggestions
  affects:
    - "04-05: Self-correction loop uses template validation"
    - "05: Batch executor uses templates for payload generation"

tech-stack:
  added:
    - jinja2 (SandboxedEnvironment for template security)
  patterns:
    - Jinja2 filter chains for data transformation
    - Default value applied before transformation to handle None

key-files:
  created:
    - src/orchestrator/filters/__init__.py
    - src/orchestrator/filters/logistics.py
    - src/orchestrator/models/mapping.py
    - src/orchestrator/nl_engine/mapping_generator.py
    - tests/orchestrator/test_logistics_filters.py
    - tests/orchestrator/test_mapping_generator.py
  modified:
    - src/orchestrator/models/__init__.py
    - src/orchestrator/nl_engine/__init__.py

decisions:
  - id: default-value-before-transformation
    description: Apply default_value filter before transformation filters in Jinja2 expressions
    rationale: Prevents filter errors when source is None; default gets replaced before validation filters run

metrics:
  duration: 8m
  completed: 2026-01-25
---

# Phase 04 Plan 03: Mapping Template Generator Summary

Jinja2 logistics filter library and mapping template generator with 104 unit tests passing.

## What Was Built

### Logistics Filter Library

Created `src/orchestrator/filters/logistics.py` with 9 Jinja2 filters from CLAUDE.md:

| Filter | Purpose | Example |
|--------|---------|---------|
| `truncate_address(max=35)` | Truncate at word boundary | "123 Main Street Suite 400" -> "123 Main Street" |
| `format_us_zip` | Normalize to 5-digit or ZIP+4 | "900011234" -> "90001-1234" |
| `round_weight(decimals=1)` | Round with 0.1 minimum | 0.02 -> 0.1 |
| `convert_weight(from, to)` | Convert g/kg/oz/lbs | 1.0 kg -> 2.20462 lbs |
| `lookup_service_code` | Map aliases to UPS codes | "ground" -> "03" |
| `to_ups_date` | Format as YYYYMMDD | "2024-01-15" -> "20240115" |
| `to_ups_phone` | Normalize to 10 digits | "(555) 123-4567" -> "5551234567" |
| `default_value(fallback)` | Replace None/empty/NaN | None -> "Unknown" |
| `split_name(part)` | Extract first/last name | "John Doe", "last" -> "Doe" |

### Mapping Models

Created `src/orchestrator/models/mapping.py` with Pydantic models:

1. **FieldMapping**: Single field mapping
   - `source_column`: Column from source data
   - `target_path`: JSONPath in UPS payload (e.g., "ShipTo.Name")
   - `transformation`: Optional Jinja2 filter
   - `default_value`: Fallback for null/empty

2. **MappingTemplate**: Complete template
   - `name`: Template name for saving
   - `source_schema_hash`: Hash for matching schemas
   - `mappings`: List of FieldMapping
   - `missing_required`: UPS fields not mapped
   - `jinja_template`: Compiled Jinja2 string

3. **UPSTargetField**: UPS schema field info
   - `path`, `type`, `required`, `max_length`, `description`

4. **MappingGenerationError**: Template compilation errors

### Template Generator Functions

Created `src/orchestrator/nl_engine/mapping_generator.py`:

1. **UPS_REQUIRED_FIELDS**: Key fields for MVP shipping
   - ShipTo.Name, ShipTo.Address.*, Package.PackageWeight.Weight

2. **compute_schema_hash**: Order-independent hash of column names

3. **generate_mapping_template**: Create Jinja2 template from mappings
   - Validates source columns exist
   - Builds nested JSON structure
   - Identifies missing required fields

4. **render_template**: Apply template to row data
   - Uses SandboxedEnvironment for security
   - Returns parsed JSON dict

5. **suggest_mappings**: LLM-powered suggestions (requires API key)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Default value applied BEFORE transformation | Prevents errors like to_ups_phone(None); None replaced with default first |
| SandboxedEnvironment for Jinja2 | Security: restricts access to dangerous attributes/methods |
| Order-independent schema hash | Same columns always produce same hash regardless of order |
| Missing required tracked in template | User sees which UPS fields still need mapping |

## Test Coverage

| Test Class | Tests | Coverage |
|------------|-------|----------|
| TestTruncateAddress | 8 | Word boundaries, edge cases |
| TestFormatUsZip | 7 | 5/9 digit, formatting |
| TestRoundWeight | 5 | Decimals, minimum |
| TestConvertWeight | 8 | All unit conversions |
| TestToUpsPhone | 6 | Formatting, country code |
| TestToUpsDate | 6 | Various date formats |
| TestDefaultValue | 7 | None, empty, NaN |
| TestSplitName | 7 | First/last extraction |
| TestLookupServiceCode | 8 | Aliases, codes |
| TestLogisticsFiltersRegistry | 2 | Registration |
| TestGetLogisticsEnvironment | 5 | Sandbox, filters |
| TestSchemaHash | 6 | Determinism, order |
| TestFieldMapping | 4 | Model validation |
| TestMappingTemplate | 3 | Model validation |
| TestGenerateMappingTemplate | 7 | Template creation |
| TestRenderTemplate | 7 | Template rendering |
| TestMappingGenerationError | 4 | Error handling |
| TestIntegrationScenarios | 2 | End-to-end |
| **Total** | **104** | **All passing** |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added jinja2 dependency**
- **Found during:** Task 1 verification
- **Issue:** ModuleNotFoundError: No module named 'jinja2'
- **Fix:** Added jinja2>=3.0.0 to pyproject.toml (already present from prior work)
- **Commit:** N/A (dependency already existed)

**2. [Rule 1 - Bug] Fixed default_value filter order**
- **Found during:** Task 3 test execution
- **Issue:** to_ups_phone filter failed when source was None (before default applied)
- **Fix:** Reordered filters so default_value runs before transformation
- **Files modified:** src/orchestrator/nl_engine/mapping_generator.py
- **Commit:** 0dc06f5

## Verification Results

1. `from src.orchestrator.filters.logistics import get_logistics_environment` - SUCCESS
2. `from src.orchestrator.nl_engine.mapping_generator import generate_mapping_template` - SUCCESS
3. `pytest tests/orchestrator/test_logistics_filters.py tests/orchestrator/test_mapping_generator.py -v` - 104 passed
4. All 9 logistics filters from CLAUDE.md implemented - SUCCESS
5. Jinja2 templates use SandboxedEnvironment for security - SUCCESS

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| 0294146 | feat | Create logistics filter library for Jinja2 |
| 2b91db2 | feat | Create mapping models and template generator |
| 0dc06f5 | test | Add comprehensive tests for mapping and filters |

## Next Phase Readiness

**Ready for 04-05: Self-Correction Loop**

Prerequisites delivered:
- FieldMapping and MappingTemplate models for correction state
- generate_mapping_template for regenerating corrected templates
- render_template for testing corrected output
- All logistics filters for data transformation

No blockers identified.
