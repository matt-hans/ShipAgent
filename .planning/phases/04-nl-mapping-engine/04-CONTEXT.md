# Phase 4: Natural Language and Mapping Engine — CONTEXT

**Phase Goal:** Users can issue natural language commands that are parsed into structured intents and automatically generate data-to-UPS mapping templates.

**Created:** 2026-01-25
**Status:** Ready for research/planning

---

## Decision 1: Command Vocabulary & Boundaries

### Missing Information Handling
- **Decision:** Use MCP elicitation (AskUserQuestion pattern) for any unclear or missing information
- **Rationale:** Better UX than failing or guessing; user stays in control
- **Implementation:** Claude Agent SDK's `canUseTool` callback with AskUserQuestion tool

### Batch Qualifiers
- **Decision:** Support qualifiers like "first 10", "random sample of 5", "every other row"
- **Rationale:** Users need granular control over which rows to process
- **Examples:**
  - "Ship the first 10 California orders"
  - "Process every other row from today's imports"
  - "Create labels for a random sample of 5 orders"

### Ambiguous Commands
- **Decision:** Use MCP elicitation to clarify — never guess
- **Rationale:** Shipping has real-world costs; wrong assumptions are expensive
- **Example:** "Ship the big ones" → Elicit: "What defines 'big'? Weight > X lbs? Dimensions > Y?"

### Shorthand and Aliases
- **Decision:** Support common shipping shorthand
- **Mapping:**
  - "ground" → UPS Ground (03)
  - "overnight" / "next day" → Next Day Air (01)
  - "2-day" / "two day" → 2nd Day Air (02)
  - "3-day" / "three day" → 3 Day Select (12)
  - "saver" → Next Day Air Saver (13)
- **Extensible:** Store alias mappings in configuration for user customization

---

## Decision 2: Mapping Template Generation

### Column Matching Strategy
- **Decision:** Always require explicit mapping on first use — no auto-mapping guesses
- **Rationale:** Shipping data is critical; silent wrong mappings cause failed deliveries
- **Flow:**
  1. System detects source columns
  2. Presents UPS required fields
  3. User explicitly maps each field (with suggestions)
  4. Mapping saved for reuse

### Missing Required Fields
- **Decision:** Use elicitation with two options:
  1. Provide a default value for all rows
  2. Modify the source data to add the field
- **Rationale:** User chooses whether to fix at template level or data level
- **Example:** Missing package dimensions → "Provide default dimensions (L×W×H) or add columns to your data?"

### Field Transformations
- **Decision:** Include inline transformations via Jinja2 filters
- **Rationale:** Common transforms shouldn't require data preprocessing
- **Examples:**
  - `{{ full_name | split_name('first') }}` → Extract first name
  - `{{ phone | format_phone }}` → Normalize to UPS format
  - `{{ address | truncate_address(35) }}` → UPS max length
  - `{{ weight_oz | convert_weight('oz', 'lbs') }}` → Unit conversion

### Mapping Persistence
- **Decision:** Remember successful mappings + allow saved import templates
- **Features:**
  - Auto-suggest previous mapping when same column names detected
  - Named templates user can save and reuse ("Weekly Fulfillment Template")
  - Template includes: column mappings, default values, transformations
- **Storage:** SQLite in state database (template_name, schema_hash, mapping_json)

---

## Decision 3: Filter Interpretation

### Timezone Reference
- **Decision:** Use system timezone for all date interpretations
- **Rationale:** Simplicity; most users operate in a single timezone
- **Implementation:** Python `datetime.now()` without explicit tz, document in user guide

### Date Column Ambiguity
- **Decision:** Elicit which date column to use when multiple exist or none obvious
- **Rationale:** `order_date` vs `ship_by_date` vs `created_at` have different meanings
- **Example:** "today's orders" with multiple date columns → "Which date field? order_date, ship_by_date, or created_at?"

### Numeric Comparisons
- **Decision:** Infer if obvious, elicit if ambiguous
- **Obvious cases (infer):**
  - "over 5 lbs" → weight column (if only one weight-like column)
  - "above $100" → amount/total column (if only one currency-like column)
- **Ambiguous cases (elicit):**
  - Multiple weight columns → "Which weight field? package_weight or total_weight?"
  - "large orders" → "Define 'large': by weight, by value, or by item count?"

### Compound Filters
- **Decision:** Fully support compound filters in single commands
- **Rationale:** Users need maximum granularity for batch selection
- **Examples:**
  - "California orders over 5 lbs from this week"
  - "Rush orders that aren't residential"
  - "First 20 orders from today where total > $50"
- **Implementation:** Parse to SQL WHERE clause with AND/OR logic

---

## Decision 4: Self-Correction Behavior

### User Feedback During Correction
- **Decision:** Detailed feedback showing specific validation errors
- **Format:**
  ```
  Template validation failed (attempt 2 of 3)
  Error: Field 'ShipTo.Phone' invalid format
  Expected: 10-digit US phone number
  Got: "555-1234" (missing area code)
  Attempting correction...
  ```
- **Rationale:** Users understand what's wrong; can intervene if needed

### After Maximum Retries (3 failures)
- **Decision:** Show full validation errors and ask user for guidance
- **Options presented:**
  1. Correct the source data and retry
  2. Provide manual fix for the specific field
  3. Skip problematic rows and continue with valid ones
  4. Abort the operation
- **Rationale:** User stays in control; no silent data loss

### On Successful Correction
- **Decision:** Ask user to confirm the fix before proceeding
- **Format:**
  ```
  Self-correction successful:
  - Fixed: Split 'customer_name' into first/last name fields
  - Fixed: Added area code '555' to phone numbers missing it

  Proceed with these corrections? [Yes / No / Show details]
  ```
- **Rationale:** Transparency; user validates LLM's assumptions

### Configurable Behavior
- **Decision:** Allow user configuration of self-correction
- **Settings:**
  - `max_retry_attempts`: 1-5 (default: 3)
  - `self_correction_enabled`: true/false (default: true)
  - `auto_confirm_fixes`: true/false (default: false — always ask)
- **Storage:** User settings in state database

---

## Technical Notes for Planning

### MCP Elicitation Pattern
From Claude Agent SDK docs:
- Use `AskUserQuestion` tool in `canUseTool` callback
- 60-second timeout for responses
- 1-4 questions per call, 2-4 options each
- Support free-text "Other" responses

### Dependencies
- Phase 2: Data Source MCP (provides schema discovery, query tools)
- Phase 3: UPS MCP (provides schema validation, Zod schemas)

### Key Artifacts to Create
1. Intent parser (NL → structured command)
2. Filter generator (NL filters → SQL WHERE)
3. Mapping template generator (schema + mappings → Jinja2)
4. Template validator (Jinja2 + UPS schema → validation result)
5. Self-correction loop (validation errors → LLM fix → re-validate)
6. Mapping persistence (save/load templates)

---

## Deferred Ideas

None captured during discussion.

---

## Next Steps

1. `/gsd:research-phase 4` — Research implementation approaches
2. `/gsd:plan-phase 4` — Create detailed execution plans

---

*Last updated: 2026-01-25*
