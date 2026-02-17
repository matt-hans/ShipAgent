# FilterSpec Compiler Architecture — Deterministic NL-to-SQL

**Date:** 2026-02-16
**Status:** Approved
**Phase:** Implementation Ready

---

## Problem Statement

The current filter pipeline is non-deterministic. The same prompt — "Ship all orders going to companies in the Northeast — use 2nd Day Air" — returned 10, 13, and 17 shipments across three separate runs instead of the expected 5.

**Root cause:** The system prompt at `src/orchestrator/agent/system_prompt.py:173-215` hardcodes Shopify-specific column names (`customer_name`, `ship_to_name`, `financial_status`, `total_weight_grams`) as filter examples — even when the CSV has completely different columns (`state`, `company`, `recipient_name`, `weight_lbs`). Combined with no sample values (the LLM doesn't know `state` contains abbreviations like `CA`, `NY`), no column validation before execution, and free-form SQL WHERE clause generation, the agent produces a different query each run.

**Solution:** Replace free-form SQL generation with a structured FilterSpec JSON compiler. The LLM outputs `FilterIntent` JSON, a deterministic semantic resolver expands canonical terms (regions, business predicates), and a SQL compiler produces parameterized DuckDB queries. Hook-level enforcement prevents raw SQL bypass.

---

## 1. Architecture Overview — The Deterministic Filter Pipeline

### Current Flow (non-deterministic)

```
User prompt → LLM → raw SQL WHERE string → DuckDB
```

### New Flow (deterministic)

```
User prompt
    │
    ▼
LLM generates FilterIntent (structured JSON — no SQL)
    │
    ▼
resolve_filter_intent() tool
    ├── Tier A terms: auto-expand (service codes, abbreviations)
    ├── Tier B terms: flag for confirmation (regions, business predicates)
    └── Tier C terms: reject with clarification options (UNRESOLVED_INTENT)
    │
    ▼ [If Tier B: agent presents expansion to user, awaits confirmation]
    │
    ▼
FilterSpec (fully resolved, all semantics concrete)
    │
    ▼
ship_command_pipeline(filter_spec=...) tool
    │
    ▼
compile_filter_spec() — deterministic compiler (internal)
    │
    ▼
Validated parameterized SQL (server-side, never LLM-generated)
    │
    ▼
DuckDB execution → preview → user confirms cost → execute
```

### Key Invariants

1. The LLM **never** produces SQL. It produces a typed `FilterIntent` JSON object.
2. The compiler is the **sole authority** for SQL generation. It owns the operator allowlist, column validation, and precedence rules.
3. All semantic terms are resolved **before** any query touches DuckDB.
4. Two confirmation gates: semantic confirmation (Tier B) + cost confirmation (existing preview).
5. Hook enforcement **denies** any tool call that contains a raw `where_clause` string.

### Tool Contract

| Tool | Direction | Purpose |
|------|-----------|---------|
| `resolve_filter_intent` | LLM → Server | Takes `FilterIntent` JSON, returns `ResolvedFilterSpec` with status |
| `ship_command_pipeline` | LLM → Server | Accepts `filter_spec` (resolved), replaces `where_clause` param |
| `fetch_rows` | LLM → Server | Accepts `filter_spec` (resolved), replaces `where_clause` param |
| `validate_filter_syntax` | **Deleted** | Hard cutover — removed entirely, no stub |
| `validate_filter_spec` | Internal only | Called inside `compile_filter_spec`, not exposed to LLM |

### Design Decisions (10 refinements incorporated)

1. **Strict status enum:** `RESOLVED | NEEDS_CONFIRMATION | UNRESOLVED`
2. **Schema + dict versioning:** `schema_signature` and `canonical_dict_version` travel with every spec
3. **Resolution tokens:** Opaque HMAC-signed token binds Tier B confirmation to a specific interpretation
4. **Internal validation:** `validate_filter_spec` called inside compiler, not exposed to LLM
5. **Hook enforcement:** Deny `where_clause`, `sql`, `query` keys on orchestrator tool payloads
6. **Single contract:** Both fast and fallback paths consume `FilterSpec`
7. **Fail-closed compiler:** Deterministic error codes for every failure mode
8. **Session-scoped confirmation cache:** Confirmed semantics persist within session
9. **Execution-time schema recheck:** Abort if source changed after confirmation
10. **Two gates:** Semantic (Tier B conditional) + cost (always)

---

## 2. FilterSpec Schema — Data Model

### Type Hierarchy

```
FilterIntent (LLM output)
    ├── root: FilterGroup
    │     ├── logic: "AND" | "OR"
    │     └── conditions: list of
    │           ├── FilterCondition (direct column filter)
    │           │     column: str
    │           │     operator: <allowlisted>
    │           │     operands: list[TypedLiteral]  (unified, arity-enforced)
    │           ├── SemanticReference (canonical term)
    │           │     semantic_key: "NORTHEAST" | "BUSINESS_RECIPIENT" | ...
    │           │     target_column: str (which column to apply to)
    │           └── FilterGroup (nested logic)
    ├── service_code: str | None
    └── schema_signature: str

FilterSpecEnvelope (metadata wrapper)
    ├── schema_signature: str
    ├── canonical_dict_version: str
    ├── locale: str
    └── source_id: str

ResolvedFilterSpec (after resolution)
    ├── status: RESOLVED | NEEDS_CONFIRMATION | UNRESOLVED
    ├── root: FilterGroup (all SemanticReferences replaced with FilterConditions)
    ├── explanation: str (human-readable)
    ├── resolution_token: str | None (HMAC-signed, for Tier B confirmation binding)
    ├── pending_confirmations: list[{term, expansion, tier}] | None
    ├── unresolved_terms: list[{phrase, suggestions: [{key, expansion}]}] | None
    ├── schema_signature: str
    └── canonical_dict_version: str

CompiledFilter (after compilation)
    ├── where_sql: str (parameterized: $1, $2, ...)
    ├── params: list[Any]
    ├── columns_used: list[str]
    ├── explanation: str
    └── schema_signature: str
```

### Allowed Operators (exhaustive — compiler rejects anything else)

| Operator | SQL | Applies to | Param count |
|----------|-----|-----------|-------------|
| `eq` | `"{col}" = $N` | All types | 1 |
| `neq` | `"{col}" != $N` | All types | 1 |
| `gt` | `"{col}" > $N` | Numeric, date | 1 |
| `gte` | `"{col}" >= $N` | Numeric, date | 1 |
| `lt` | `"{col}" < $N` | Numeric, date | 1 |
| `lte` | `"{col}" <= $N` | Numeric, date | 1 |
| `in` | `"{col}" IN ($N, ...)` | String, numeric | N |
| `not_in` | `"{col}" NOT IN ($N, ...)` | String, numeric | N |
| `contains_ci` | `"{col}" ILIKE $N` (`%val%`) | String | 1 (escaped, `ESCAPE '\'`) |
| `starts_with_ci` | `"{col}" ILIKE $N` (`val%`) | String | 1 (escaped, `ESCAPE '\'`) |
| `ends_with_ci` | `"{col}" ILIKE $N` (`%val`) | String | 1 (escaped, `ESCAPE '\'`) |
| `is_null` | `"{col}" IS NULL` | All types | 0 |
| `is_not_null` | `"{col}" IS NOT NULL` | All types | 0 |
| `is_blank` | `("{col}" IS NULL OR "{col}" = $N)` | All types | 1 (`""`) |
| `is_not_blank` | `("{col}" IS NOT NULL AND "{col}" != $N)` | All types | 1 (`""`) |
| `between` | `"{col}" BETWEEN $N AND $N+1` | Numeric, date | 2 |

The original `like`/`ilike` operators are replaced by `contains_ci`, `starts_with_ci`, `ends_with_ci` to prevent wildcard injection. The compiler emits escaped patterns with `ESCAPE '\'`.

### Typed Literals

All operand values carry explicit type tags: `string | number | boolean | date`. The compiler coerces values to match column types deterministically.

### Structural Guardrails

| Limit | Default | Error |
|-------|---------|-------|
| Max tree depth | 4 | `STRUCTURAL_LIMIT_EXCEEDED` |
| Max condition count | 50 | `STRUCTURAL_LIMIT_EXCEEDED` |
| Max IN-list cardinality | 100 | `STRUCTURAL_LIMIT_EXCEEDED` |
| Max total params | 500 | `STRUCTURAL_LIMIT_EXCEEDED` |

### Error Codes (fail-closed)

| Code | Trigger |
|------|---------|
| `UNKNOWN_COLUMN` | Column name not in schema |
| `UNKNOWN_CANONICAL_TERM` | Semantic key not in any dictionary |
| `AMBIGUOUS_TERM` | Multiple possible expansions |
| `INVALID_OPERATOR` | Operator not in allowlist |
| `TYPE_MISMATCH` | e.g., `gt` on a VARCHAR column |
| `SCHEMA_CHANGED` | Schema signature at compile != signature at resolution |
| `MISSING_TARGET_COLUMN` | Semantic key references a column absent from schema |
| `INVALID_ARITY` | Operand count doesn't match operator requirements |
| `MISSING_OPERAND` | Required operand not provided |
| `EMPTY_IN_LIST` | IN/NOT_IN with empty operand list |
| `TOKEN_INVALID_OR_EXPIRED` | Resolution token signature invalid or TTL expired |
| `TOKEN_HASH_MISMATCH` | Token's `resolved_spec_hash` doesn't match incoming `filter_spec` |
| `CONFIRMATION_REQUIRED` | Spec status is not RESOLVED when compilation attempted |
| `STRUCTURAL_LIMIT_EXCEEDED` | Max depth, max conditions, or max params exceeded |

### Semantic Expansion Example

`BUSINESS_RECIPIENT` resolves to:
```json
{
  "logic": "AND",
  "conditions": [
    {"column": "company", "operator": "is_not_null"},
    {"column": "company", "operator": "neq", "operands": [{"type": "string", "value": ""}]}
  ]
}
```

---

## 3. Canonical Constants Module

**New file:** `src/services/filter_constants.py`

Follows the established pattern of `ups_constants.py` and `ups_service_codes.py` — single source of truth, many consumers.

### Region Maps

```python
REGIONS = {
    "NORTHEAST":    ["NY", "MA", "CT", "PA", "NJ", "ME", "NH", "RI", "VT"],
    "NEW_ENGLAND":  ["CT", "ME", "MA", "NH", "RI", "VT"],
    "MID_ATLANTIC": ["NY", "NJ", "PA", "DE", "MD", "DC"],
    "SOUTHEAST":    ["FL", "GA", "SC", "NC", "VA", "WV", "AL", "MS", "TN", "KY", "LA", "AR"],
    "MIDWEST":      ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS"],
    "SOUTHWEST":    ["TX", "OK", "NM", "AZ"],
    "WEST":         ["CA", "OR", "WA", "NV", "UT", "CO", "WY", "MT", "ID"],
    "WEST_COAST":   ["CA", "OR", "WA"],
    "PACIFIC":      ["CA", "OR", "WA", "HI", "AK"],
    "ALL_US":       [...]  # 50 states + DC + PR
}
```

**Policy:** DC and PR are in `ALL_US` only. Individual regions include them only where geographically correct (DC in `MID_ATLANTIC`).

### Region Aliases (NL → canonical key)

```python
REGION_ALIASES = {
    "northeast": "NORTHEAST", "the northeast": "NORTHEAST", "northeast states": "NORTHEAST",
    "new england": "NEW_ENGLAND",
    "mid-atlantic": "MID_ATLANTIC", "mid atlantic": "MID_ATLANTIC",
    "southeast": "SOUTHEAST",
    "midwest": "MIDWEST", "the midwest": "MIDWEST",
    "southwest": "SOUTHWEST",
    "west": "WEST", "western states": "WEST",
    "west coast": "WEST_COAST",
    "pacific": "PACIFIC", "pacific states": "PACIFIC",
}
# "the south" → Tier C (too ambiguous — force clarification)
```

### Business Predicates

```python
BUSINESS_PREDICATES = {
    "BUSINESS_RECIPIENT": {
        "description": "Company name is present and non-empty",
        "target_column_patterns": ["company", "company_name", "organization_name"],
        "expansion": "is_not_blank on matched column",
    },
    "PERSONAL_RECIPIENT": {
        "description": "No company name (personal/residential)",
        "target_column_patterns": ["company", "company_name", "organization_name"],
        "expansion": "is_blank on matched column",
    },
}
```

### Ambiguity Tiers

| Tier | Policy | Examples |
|------|--------|---------|
| **A** (auto-expand, no confirmation) | State abbreviation mappings (California → CA), service code aliases (Ground → 03), country code mappings (United Kingdom → GB) | Deterministic, unambiguous |
| **B** (canonical, always confirm) | Region expansions (NORTHEAST → state list), business predicates, weight band classifications, ambiguous country names | Canonical but should be verified with user |
| **C** (unknown, force clarification) | Everything not in Tier A or B dictionaries. "the south" deliberately Tier C. | 2-3 candidate suggestions, require explicit pick |

### Column Pattern Matching

Business predicates and semantic references use `target_column_patterns` — a list of column name patterns matched case-insensitively against the actual schema.

Priority order: **exact match → synonym match → pattern heuristic**.

- **0 matches:** `MISSING_TARGET_COLUMN` with suggested columns
- **1 match:** Use it
- **2+ matches:** `AMBIGUOUS_TERM` with options for user to pick

### Versioning

- **Canonical dict version:** `"filter_constants_v1"` — increments when any dictionary changes
- **Region profile:** `US_STANDARD_V1`
- **Normalization:** Single function — `casefold + strip punctuation/hyphens/spaces`

---

## 4. Semantic Resolver

**New file:** `src/orchestrator/filter_resolver.py`

### Interface

```python
def resolve_filter_intent(
    intent: FilterIntent,
    schema_columns: set[str],
    column_types: dict[str, str],
    schema_signature: str,
    session_confirmations: dict[str, str],
) -> ResolvedFilterSpec:
    """Pure function. Resolves semantic references to concrete filter conditions.

    Args:
        intent: Structured filter intent from LLM.
        schema_columns: Available column names from current data source.
        column_types: Column name → DuckDB type mapping.
        schema_signature: Hash of current schema for staleness detection.
        session_confirmations: {resolution_token: confirmed_expansion} from prior Tier B confirmations.

    Returns:
        ResolvedFilterSpec with status, resolved AST, explanation, and optional confirmation/clarification data.
    """
```

### Resolution Algorithm

For each condition in the AST:

**1. FilterCondition (direct column filter):**
- Validate `column` exists in `schema_columns` → `UNKNOWN_COLUMN` if not
- Validate `operator` is in allowlist → `INVALID_OPERATOR` if not
- Validate arity (operand count matches operator) → `INVALID_ARITY` if not
- Validate type compatibility (operator vs column type) → `TYPE_MISMATCH` if not
- Pass through unchanged

**2. SemanticReference (canonical term):**
- Normalize `semantic_key` via casefold + punctuation normalization
- Look up in canonical dictionaries (regions → business → weight bands → country)
- **Found in Tier A:** Auto-expand. Replace with concrete FilterConditions. No confirmation.
- **Found in Tier B:** Check `session_confirmations` for prior confirmation with matching token. If confirmed, expand. If not, set `status = NEEDS_CONFIRMATION`, generate `resolution_token`, add to `pending_confirmations`.
- **Not found (Tier C):** Set `status = UNRESOLVED`. Generate 2-3 candidate suggestions via deterministic fuzzy matching. Add to `unresolved_terms`.

**3. Target column resolution (for business/semantic predicates):**
- Match `target_column_patterns` against `schema_columns` (exact → synonym → pattern)
- 0 matches → `MISSING_TARGET_COLUMN` with suggested columns
- 1 match → use it
- 2+ matches → `AMBIGUOUS_TERM` with options

**4. FilterGroup (recursive):**
- Resolve all child conditions
- If any child is `NEEDS_CONFIRMATION` or `UNRESOLVED`, propagate upward
- Status precedence: `UNRESOLVED > NEEDS_CONFIRMATION > RESOLVED`
- After all semantics resolved, canonicalize: sort commutative children, normalize IN-list values, deduplicate

### Resolution Token Structure

```python
# HMAC-signed token containing:
{
    "session_id": str,
    "schema_signature": str,
    "canonical_dict_version": str,
    "resolved_spec_hash": str,   # hash of the expansion — tamper-proof
    "expires_at": "ISO8601",     # 10-minute TTL
}
```

Server validates HMAC signature before accepting any token.

### Session Confirmation Cache

```python
# In AgentSession:
confirmed_resolutions: dict[str, ResolvedFilterSpec]  # token → confirmed spec
```

Stored on the `AgentSession` object (in-memory, per-conversation). Cleared on session reset or data source change.

---

## 5. SQL Compiler

**New file:** `src/orchestrator/filter_compiler.py`

### Interface

```python
def compile_filter_spec(
    spec: ResolvedFilterSpec,
    schema_columns: set[str],
    column_types: dict[str, str],
    runtime_schema_signature: str,
) -> CompiledFilter:
    """Pure function. Compiles a resolved FilterSpec into parameterized SQL.

    Args:
        spec: Fully resolved filter spec (status must be RESOLVED).
        schema_columns: Current schema columns for redundant safety check.
        column_types: Column name → DuckDB type mapping.
        runtime_schema_signature: Current schema hash — must match spec's signature.

    Returns:
        CompiledFilter with parameterized SQL, params list, column list, and explanation.

    Raises:
        FilterCompilationError with deterministic error code on any failure.
    """
```

### Output

```python
@dataclass
class CompiledFilter:
    where_sql: str           # "state IN ($1, $2, $3, $4, $5, $6) AND (company IS NOT NULL AND company != $7)"
    params: list[Any]        # ['NY', 'MA', 'CT', 'PA', 'NJ', 'ME', '']
    columns_used: list[str]  # ['state', 'company']
    explanation: str          # "Northeast states (NY, MA, CT, PA, NJ, ME) with company name present"
    schema_signature: str
```

### Compilation Algorithm

1. **Entry guard:** Assert `spec.status == RESOLVED`. If not → `CONFIRMATION_REQUIRED`. Validate `spec.schema_signature == runtime_schema_signature` → `SCHEMA_CHANGED` if mismatch.

2. **Walk the FilterGroup tree:**
   - For each `FilterCondition`:
     - Validate column exists in `schema_columns` (redundant safety)
     - Validate operator arity matches operand count
     - Apply literal coercion (string `"5"` → int `5` if column is INTEGER)
     - Emit parameterized SQL fragment: `"{column}" {op} $N` (positional params)
     - Append literal values to `params` list
   - For each `FilterGroup`:
     - Recursively compile children
     - Join with ` AND ` or ` OR `
     - Wrap in parentheses for correct precedence

3. **Canonicalization** (before SQL emission):
   - Sort IN-list values (alphabetic for strings, numeric for numbers)
   - Sort commutative AND/OR children by full subtree serialization
   - Identical inputs always produce identical SQL

4. **Structural guards:** Enforce max depth (4), max conditions (50), max IN-list cardinality (100), max total params (500). Exceed any → `STRUCTURAL_LIMIT_EXCEEDED`.

5. **Wildcard escaping:** `contains_ci`, `starts_with_ci`, `ends_with_ci` escape `%`, `_`, `\` in values before wrapping with wildcards. All emitted with `ESCAPE '\'`.

6. **NULL semantics:** `neq` and `not_in` emit explicit NULL-aware SQL where applicable.

7. **Parameterized execution:** Uses `$1, $2, ...` positional placeholders. DuckDB executes via `db.execute(sql, params)`. Eliminates SQL injection and quoting drift entirely. ALL query paths use parameterized execution (replacing raw interpolation at `query_tools.py:113` and `:119`).

---

## 6. Tool Contract + Hook Enforcement

### Tool Changes

| Tool | Current Signature | New Signature |
|------|------------------|---------------|
| `resolve_filter_intent` | N/A (new) | `intent: FilterIntent` → `ResolvedFilterSpec` |
| `ship_command_pipeline` | `where_clause: str` | `filter_spec: FilterSpec` + `resolution_token: str` |
| `fetch_rows` | `where_clause: str` | `filter_spec: FilterSpec` |
| `validate_filter_syntax` | `where_clause: str` | **Deleted** (hard cutover — no stub) |

### New Tool Definition: `resolve_filter_intent`

```python
{
    "name": "resolve_filter_intent",
    "input_schema": {
        "properties": {
            "intent": {
                "type": "object",
                "description": "Structured filter intent with conditions and semantic references",
                "properties": {
                    "root": { "...FilterGroup schema..." },
                    "service_code": {"type": "string"},
                }
            }
        },
        "required": ["intent"]
    }
}
```

### Modified Tool: `ship_command_pipeline`

```python
{
    "name": "ship_command_pipeline",
    "input_schema": {
        "properties": {
            "filter_spec": {"type": "object", "description": "Resolved FilterSpec from resolve_filter_intent"},
            "resolution_token": {"type": "string", "description": "Token from confirmed resolution (required for Tier B terms)"},
            "command": {"type": "string"},
            "service_code": {"type": "string"},
        },
        "required": ["command"]
    }
}
```

### Hook Enforcement (new PreToolUse hooks in `hooks.py`)

**1. `deny_raw_sql_in_filter_tools`** — Scoped to `resolve_filter_intent`, `ship_command_pipeline`, `fetch_rows` only (not all orchestrator tools). Inspects payload recursively (not just top-level) for keys: `where_clause`, `sql`, `query`, `raw_sql`. If any found → deny.

**2. `validate_filter_spec_on_pipeline`** — PreToolUse hook on `ship_command_pipeline` and `fetch_rows`. Validates:
- `filter_spec` is present and structurally valid
- If `resolution_token` present: validates HMAC signature + expiry + session + schema signature + dict version + `resolved_spec_hash` match
- Schema signature matches current source

**3. `validate_intent_on_resolve`** — PreToolUse hook on `resolve_filter_intent`. Validates:
- Intent root is a valid FilterGroup
- Operators are from the allowlist
- No embedded SQL strings in operand values (defense-in-depth)

### Hook Ordering

Deny is final — not overridable by later hooks in chain (at `hooks.py:555`).

### System Prompt Workflow Update

```
### Shipping Commands

1. Parse user intent into a FilterIntent (structured conditions, semantic keys, operators)
2. Call resolve_filter_intent with the intent
3. If status is NEEDS_CONFIRMATION: present the explanation to the user and await approval
4. If status is UNRESOLVED: present the suggestions and ask user to pick or rephrase
5. If status is RESOLVED (or after user confirms): call ship_command_pipeline with the resolved filter_spec and resolution_token
6. Preview appears — respond with one brief sentence asking user to review

NEVER generate SQL WHERE clauses. NEVER include where_clause, sql, or query parameters in tool calls.
```

### Cutover Strategy (Hard Cutover — No Dual Path)

All changes land in a single commit sequence. There is no migration period where both paths coexist.

1. Replace `where_clause` with `filter_spec` in `ship_command_pipeline` and `fetch_rows` (same commit)
2. Delete `validate_filter_syntax` tool entirely (no stub)
3. Deploy `deny_raw_sql` hook (blocks any raw SQL keys on filter tools)
4. Replace raw SQL interpolation at `query_tools.py:113` and `:119` with parameterized execution
5. End-to-end determinism acceptance tests must pass before merge (release gate)

### Audit Metadata in Preview Payloads

The preview response includes: `filter_spec_hash`, `compiled_hash`, `schema_signature`, `canonical_dict_version` for full audit trail.

---

## 7. Frontend Filter Transparency

The `PreviewCard` currently shows row counts and costs. It will now also display filter provenance.

### PreviewCard UI Treatment

```
+---------------------------------------------------+
| ✦ Filter: Northeast states (NY, MA, CT, PA,       |
|           NJ, ME) with company name present        |
|   ▸ View compiled filter                           |
+---------------------------------------------------+
|  5 shipments · $142.50 estimated · 0 warnings     |
|  ├── Row 1: James Thornton → New York, NY  $28.50 |
|  ...                                               |
```

**Three layers:**

1. **Semantic explanation** (human-readable, always visible): "Northeast states (NY, MA, CT, PA, NJ, ME) with company name present"
2. **Compiled filter** (technical, collapsible): `WHERE state IN ($1..$6) AND (company IS NOT NULL AND company != $7)`
3. **Audit metadata** (hidden by default, developer-accessible via `data-*` attributes): `filter_spec_hash`, `compiled_hash`, `schema_signature`, `canonical_dict_version`

### File Changes

| File | Change |
|------|--------|
| `frontend/src/types/api.ts` | Add `filter_explanation`, `compiled_filter`, `filter_audit` to `BatchPreview` type |
| `frontend/src/components/command-center/PreviewCard.tsx` | Add explanation bar above row list. Collapsible "View filter" for compiled SQL |
| `src/orchestrator/agent/tools/core.py` | `_emit_preview_ready()` — include `filter_explanation`, `compiled_filter`, `filter_audit` in both SSE and LLM payloads |
| `src/orchestrator/agent/tools/pipeline.py` | After compilation, attach explanation + audit metadata to result before emit |

---

## 8. System Prompt Rewrite

**File:** `src/orchestrator/agent/system_prompt.py`

The batch-mode filter section (currently lines 173-246) is completely replaced.

### Key Changes

- **Remove** all SQL generation instructions (lines 173-215)
- **Remove** "generate a SQL WHERE clause" workflow (lines 221-222)
- **Replace** with `FilterIntent` schema documentation:
  - Available operators (the allowlist from Section 2)
  - Available canonical semantic keys (from `filter_constants.py`)
  - The FilterGroup recursive structure
  - Example intents for common patterns
- **Keep** `_build_schema_section()` with sample values (still needed for grounding)
- **Add** `_build_filter_rules()` function that generates schema-aware + canonical-term-aware rules dynamically

### The Prompt Explicitly States

```
NEVER generate SQL WHERE clauses. NEVER include where_clause, sql, or query
parameters in tool calls. Always express filters as structured FilterIntent objects
with typed conditions and semantic references.
```

### Dynamic Filter Rules

The new `_build_filter_rules()` function:
- Reads column names and types from the connected data source
- Adds sample values for each column (from new `get_column_samples()` MCP tool)
- Lists available canonical terms that are relevant to the current schema's columns
- Generates schema-specific filtering instructions

---

## 9. Testing Strategy

### New Test Files

| File | Key Tests |
|------|-----------|
| `tests/orchestrator/test_filter_resolver.py` | Tier A auto-expand, Tier B confirmation flow, Tier C rejection, column matching (exact/synonym/pattern), multiple candidates → AMBIGUOUS, zero candidates → MISSING, status precedence, token validation, schema signature check, literal coercion |
| `tests/orchestrator/test_filter_compiler.py` | All 16 operators, parameterized output, canonicalization (same input → same output), structural guards (max depth/nodes/params), wildcard escaping, NULL semantics, empty IN-list rejection, identifier safety, audit hash reproducibility |
| `tests/orchestrator/test_filter_constants.py` | Region completeness (all 50 + DC + PR in ALL_US), no region overlap violations, alias normalization, tier classification correctness, dict version format |
| `tests/orchestrator/agent/test_filter_hooks.py` | Raw SQL denial (top-level + nested), token validation in pipeline hook, filter_spec structural validation, scoped to correct tools only |
| `tests/mcp/data_source/test_parameterized_query.py` | DuckDB parameterized execution, no raw interpolation, correct results with params |

### Updated Test Files

| File | Changes |
|------|---------|
| `tests/orchestrator/agent/test_system_prompt.py` | Replace SQL-assertion tests with FilterIntent schema assertions. Verify no SQL instructions in batch mode. Verify canonical term documentation. |
| `tests/orchestrator/agent/test_tools_v2.py` | Update tool definition assertions — `where_clause` removed, `filter_spec` added |
| `tests/mcp/test_integration.py` | Update tool count expectations (+1 for `get_column_samples`) |
| `tests/integration/mcp/test_data_mcp_lifecycle.py` | Update for parameterized query path |

### Integration Test (End-to-End Determinism)

- Upload `test_data/sample_shipments.csv`
- Run "Ship all orders going to companies in the Northeast — use 2nd Day Air" 5 consecutive times
- Assert exactly 5 rows returned every time
- Assert `state` values are exactly `{NY, MA, CT, PA, NJ, ME}`
- Assert all rows have non-null, non-empty `company`

---

## 10. Complete File Inventory

### New Files (4)

| File | Purpose |
|------|---------|
| `src/services/filter_constants.py` | Canonical regions, business predicates, weight bands, tier classification, dict version |
| `src/orchestrator/models/filter_spec.py` | Pydantic models: `FilterCondition`, `SemanticReference`, `FilterGroup`, `FilterIntent`, `FilterSpecEnvelope`, `ResolvedFilterSpec`, `CompiledFilter`, typed literals, error codes, `ResolutionStatus` enum |
| `src/orchestrator/filter_resolver.py` | `resolve_filter_intent()` — pure function, semantic resolution, tier classification, HMAC token generation |
| `src/orchestrator/filter_compiler.py` | `compile_filter_spec()` — pure function, AST → parameterized SQL, canonicalization, structural guards |

### Modified Files (16+)

| File | Changes |
|------|---------|
| `src/orchestrator/agent/system_prompt.py` | Replace SQL filter rules with FilterIntent schema docs. Add `_build_filter_rules()`. Add sample values to `_build_schema_section()`. |
| `src/orchestrator/agent/tools/__init__.py` | Add `resolve_filter_intent` definition. Replace `where_clause` with `filter_spec` on `ship_command_pipeline` and `fetch_rows`. Delete `validate_filter_syntax`. |
| `src/orchestrator/agent/tools/pipeline.py` | Accept `filter_spec` + `resolution_token`, call compiler internally, attach audit metadata to preview. |
| `src/orchestrator/agent/tools/data.py` | Replace `where_clause` with `filter_spec` in `fetch_rows`. Add `resolve_filter_intent_tool()` handler. Delete `validate_filter_syntax_tool()`. |
| `src/orchestrator/agent/hooks.py` | Add `deny_raw_sql_in_filter_tools`, `validate_filter_spec_on_pipeline`, `validate_intent_on_resolve`. |
| `src/orchestrator/agent/tools/core.py` | Include `filter_explanation`, `compiled_filter`, `filter_audit` in preview payloads. |
| `src/api/routes/conversations.py` | Accept + pass `column_samples`. Fetch samples in `_process_agent_message()`. Add `confirmed_resolutions` to session. |
| `src/services/agent_session_manager.py` | Add `confirmed_resolutions: dict` to `AgentSession`. |
| `src/mcp/data_source/tools/query_tools.py` | Accept `where_sql` + `params` for parameterized execution. Remove raw SQL interpolation at lines 113, 119. |
| `src/mcp/data_source/tools/schema_tools.py` | Add `get_column_samples()` MCP tool. |
| `src/mcp/data_source/server.py` | Register `get_column_samples`. |
| `src/services/data_source_mcp_client.py` | Add `get_column_samples()` method. Update `get_rows_by_filter()` for parameterized queries. |
| `src/mcp/data_source/tools/source_info_tools.py` | Filter `_source_row_num` from prompt-facing schema metadata. |
| `src/errors/registry.py` | Add filter error codes: `E-2030` through `E-2040`. |
| `frontend/src/types/api.ts` | Add `filter_explanation`, `compiled_filter`, `filter_audit` to `BatchPreview`. |
| `frontend/src/components/command-center/PreviewCard.tsx` | Render filter explanation bar + collapsible compiled filter. |

### New Test Files (5)

| File | Purpose |
|------|---------|
| `tests/orchestrator/test_filter_resolver.py` | Resolver unit tests |
| `tests/orchestrator/test_filter_compiler.py` | Compiler unit tests |
| `tests/orchestrator/test_filter_constants.py` | Constants validation tests |
| `tests/orchestrator/agent/test_filter_hooks.py` | Hook enforcement tests |
| `tests/mcp/data_source/test_parameterized_query.py` | DuckDB parameterized execution tests |

---

## Resolved Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DC and PR in regions | `ALL_US` only; DC in `MID_ATLANTIC` | Individual regions should be geographically accurate |
| Business predicate definition | `company IS NOT NULL AND company != ''` | No domain suffix heuristics needed |
| Tier B confirmation policy | Always confirm | Consistent, zero-ambiguity UX over speed optimization |
| Semantic memory persistence | Persistent code-level constants in canonical module | Follows `ups_constants.py` / `ups_service_codes.py` pattern |
| Unresolved fallback behavior | Clarification with 2-3 options, require explicit pick | Never auto-execute on unknown terms; captured phrases expand dictionaries |
| SQL escape hatch in v1 | No escape hatch | Clean break, enforce discipline from day one |
| Token signing | HMAC-signed (not raw base64) | Tamper-proof confirmation binding |
| Compiler visibility | Internal only — agent never sees SQL | Maintains LLM-as-config-engine invariant |
