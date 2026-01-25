---
phase: 04-nl-mapping-engine
plan: 06
subsystem: nl-engine
tags: [elicitation, user-interaction, agent-sdk, pydantic]

dependency-graph:
  requires:
    - 04-01 (Intent parsing with FilterCriteria.needs_clarification)
    - 04-02 (Filter generator with SQLFilterResult.clarification_questions)
  provides:
    - Structured elicitation for ambiguous commands
    - 5 pre-built question templates for common scenarios
    - Schema-aware question customization
  affects:
    - 04-07 (Orchestrator uses elicitation for user interaction)

tech-stack:
  added: []
  patterns:
    - Claude Agent SDK AskUserQuestion pattern
    - Pydantic models for structured questions/responses

key-files:
  created:
    - src/orchestrator/models/elicitation.py
    - src/orchestrator/nl_engine/elicitation.py
    - tests/orchestrator/test_elicitation.py
  modified:
    - src/orchestrator/models/__init__.py (exports)
    - src/orchestrator/nl_engine/__init__.py (exports, import order fix)

decisions:
  - name: "5 template types from CONTEXT.md"
    rationale: "Cover common scenarios: date column, weight, dimensions, 'big' definition, service"
    alternatives: ["Generic template only", "More templates"]
  - name: "Schema customization for question options"
    rationale: "Replace generic options with actual columns from source data"
    alternatives: ["Always use static options"]
  - name: "Max 4 questions per elicitation"
    rationale: "Per Claude Agent SDK documentation limits"
    alternatives: ["No limit"]
  - name: "60-second timeout"
    rationale: "Per Claude Agent SDK defaults"
    alternatives: ["Configurable timeout"]

metrics:
  duration: "4 minutes"
  completed: "2026-01-25"
---

# Phase 4 Plan 06: Elicitation for Ambiguous Commands Summary

**One-liner:** MCP-style elicitation with 5 pre-built templates for handling ambiguous commands and missing information.

## What Was Built

### 1. Elicitation Models (`models/elicitation.py`)

Four Pydantic models following the Claude Agent SDK AskUserQuestion pattern:

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `ElicitationOption` | Single choice in a question | id, label, description, value |
| `ElicitationQuestion` | Structured question | header, question, options, allow_free_text, multi_select |
| `ElicitationResponse` | User's answer | question_id, selected_options, free_text, timestamp |
| `ElicitationContext` | Full session context | questions (max 4), responses, timeout_seconds (60) |

### 2. Elicitation Templates (`nl_engine/elicitation.py`)

Five pre-built templates per CONTEXT.md Decision 1:

| Template ID | Purpose | Options |
|-------------|---------|---------|
| `missing_date_column` | Which date column for "today's orders"? | order_date, ship_by_date, created_at |
| `ambiguous_weight` | Which weight column? | package_weight, total_weight |
| `missing_dimensions` | How to provide dimensions? | Default (10x10x10), Custom, Add Column |
| `ambiguous_big` | What defines "big"? | Weight > 5 lbs, Dimension > 12 in, Value > $100 |
| `missing_service` | Which shipping service? | UPS Ground, 2nd Day Air, Next Day Air |

### 3. Core Functions

```python
# Create question from template with optional schema customization
question = create_elicitation_question("missing_date_column", schema=schema)

# Process user response into resolved values
result = handle_elicitation_response(response)  # {"date_column": "order_date"}

# Check if intent/filter needs elicitation
template_ids = needs_elicitation(intent=intent, filter_result=filter_result)

# Build full context with questions (max 4)
context = create_elicitation_context(template_ids, schema=schema)
```

### 4. Schema Customization

When schema is provided, question options are customized:

```python
# Without schema - uses default options
q = create_elicitation_question("missing_date_column")
# Options: order_date, ship_by_date, created_at

# With schema - uses actual columns
schema = [ColumnInfo(name="invoice_date", type="date"), ...]
q = create_elicitation_question("missing_date_column", schema=schema)
# Options: invoice_date, ...
```

### 5. Response Handlers

Each question type has specific response handling:

| Question ID | Response Processing |
|-------------|---------------------|
| `date_column` | Returns `{"date_column": "selected_column"}` |
| `weight_column` | Returns `{"weight_column": "selected_column"}` |
| `dimensions` | Parses custom input or returns defaults |
| `big_definition` | Returns filter definition |
| `shipping_service` | Maps to UPS service code |

**Dimension Parsing:**
Supports multiple formats: `10x12x8`, `10 x 12 x 8`, `L:10 W:12 H:8`, `10, 12, 8`

### 6. Test Coverage

**48 unit tests** in 7 test classes:

| Test Class | Tests | Coverage |
|------------|-------|----------|
| `TestElicitationModels` | 7 | Pydantic model validation |
| `TestElicitationTemplates` | 6 | Template structure and content |
| `TestCreateElicitationQuestion` | 6 | Question creation and customization |
| `TestHandleElicitationResponse` | 9 | Response processing for all types |
| `TestNeedsElicitation` | 7 | Detection of clarification needs |
| `TestCreateElicitationContext` | 5 | Context creation with limits |
| `TestHelperFunctions` | 8 | Column finders and dimension parsing |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Circular import in models/correction.py**
- **Found during:** Task 3 test execution
- **Issue:** Circular import between `correction.py` -> `template_validator` -> `nl_engine/__init__` -> `self_correction` -> `correction.py`
- **Fix:** Reordered imports in `nl_engine/__init__.py` to import `template_validator` first
- **Files modified:** `src/orchestrator/nl_engine/__init__.py`
- **Commit:** `24b64d7`

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `66fa9a9` | feat | Create elicitation models for user interaction |
| `583ef2d` | feat | Implement elicitation templates and handlers |
| `24b64d7` | test | Add comprehensive tests for elicitation (48 tests) |

## Integration Points

### Usage in Orchestrator (04-07)

```python
from src.orchestrator.nl_engine import (
    needs_elicitation,
    create_elicitation_context,
    handle_elicitation_response,
)

# After intent parsing
template_ids = needs_elicitation(intent=intent)
if template_ids:
    context = create_elicitation_context(template_ids, schema=schema)
    # Present questions to user via Agent SDK
    # Process responses
    for question_id, response in user_responses.items():
        updates = handle_elicitation_response(response)
        # Merge updates into intent
```

### Exported from `nl_engine/__init__.py`

```python
from src.orchestrator.nl_engine import (
    ELICITATION_TEMPLATES,
    create_elicitation_question,
    handle_elicitation_response,
    needs_elicitation,
    create_elicitation_context,
)
```

### Exported from `models/__init__.py`

```python
from src.orchestrator.models import (
    ElicitationContext,
    ElicitationOption,
    ElicitationQuestion,
    ElicitationResponse,
)
```

## Next Phase Readiness

**Prerequisites for 04-07 (Orchestrator Integration):**
- Elicitation models provide structured question/response format
- needs_elicitation detects when clarification is needed
- handle_elicitation_response returns dict for merging into intent
- All 5 CONTEXT.md scenarios covered

**No blockers identified.**
