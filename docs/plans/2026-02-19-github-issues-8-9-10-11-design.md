# GitHub Issues #8, #9, #10, #11 — Unified Resolution Design

**Date:** 2026-02-19
**Status:** Revised (10 findings resolved — see Design Decisions table)
**Branch:** `fix/github-issues-8-9-10-11` (single branch, atomic commits per issue)
**Implementation order:** #10 → #9 → #11 → #8

---

## Summary

Four open GitHub issues resolved in a single development cycle. Two bugs (#9, #10) and two enhancements (#8, #11) with shared file co-dependencies handled through sequential commits.

| Issue | Type | Title | Scope |
|-------|------|-------|-------|
| #10 | Bug | Filter explanation drops AND/OR operators | Backend only |
| #9 | Bug | Missing service-packaging compatibility layer | Backend + system prompt |
| #11 | Enhancement | Schema & payload completeness (P0+P1) | Backend + Shopify client + filter compiler |
| #8 | Enhancement | CLI data source management | CLI layer |

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Service-packaging auto-reset | Auto-correct via shared `apply_compatibility_corrections()` + surface as warnings (existing PreviewCard warning system) | Single shared path for both preview (core.py) and execute (batch_engine.py); no new `adjustments` API field needed |
| Issue #11 scope | P0 + P1 fields only | P2/P3 tracked as follow-up issues |
| Filter explanation fix | Option B — AST-based recursive explanation + recursive nested group fix in resolver | Single source of truth; fixes both root joiner AND nested group logic bug (line 874) |
| CLI connect scope | Files + DB strings (with query) + Shopify env-based only | `--db` requires `--query` per backend; only Shopify has env-status endpoint |
| Domestic validation mode | Per-row validation via shared function | Same function called from both core.py preview path and batch_engine execute path |
| custom_attributes | json.dumps() at ingestion + DuckDB json_extract_string on VARCHAR | Ensures valid JSON in DuckDB (not Python repr from str()) |
| ShipFrom precedence | Row-level ship_from_* overrides Shipper for ShipFrom block; Shipper always from env | Supports multi-warehouse; Shipper is billing entity |
| Rate payload parity | Mirror surcharge-affecting indicators in build_rate_payload() | Accurate preview cost estimation |
| Branch strategy | Single branch, atomic commits per issue | Handles co-dependencies cleanly |

---

## Issue #10 — Filter Explanation AND/OR Fix

### Problem

`_build_explanation()` in `filter_compiler.py:643-656` and `filter_resolver.py:843-855` joins conditions with `"; "` instead of preserving AND/OR logic from the AST. OR filters look identical to AND filters to the user.

### Root Cause

Flat `explanation_parts: list[str]` accumulator in `filter_compiler.py:80` collects condition descriptions without structural context. `_build_explanation(parts)` at line 643 always joins with `"; ".join(parts)`, while the SQL compilation at line 224 correctly uses `f" {group.logic} "`.

### Solution

Replace the flat accumulator pattern with a recursive `_explain_ast()` function that walks the canonicalized AST.

### Changes

**`src/orchestrator/filter_compiler.py`:**

1. **Delete** `explanation_parts` accumulator (line 80) and all 16+ `explanation_parts.append(...)` calls in `_compile_condition()`
2. **Remove** `explanation_parts` parameter from `_compile_group()` and `_compile_condition()` signatures
3. **Delete** old `_build_explanation(parts: list[str])` function (lines 643-656)
4. **Add** `_explain_ast(node: FilterCondition | FilterGroup) -> str`:
   - `FilterCondition` → human-readable label (same text as old append calls)
   - `FilterGroup` → recursive children joined with `f" {node.logic.upper()} "`, multi-child groups wrapped in parentheses
5. **Add** `_build_explanation_from_ast(root: FilterGroup) -> str` — calls `_explain_ast(root)`, strips outer parens, wraps with `"Filter: "` / `"."`
6. **Replace** line 107: `explanation=_build_explanation(explanation_parts)` → `explanation=_build_explanation_from_ast(canonicalized_root)`

**`src/orchestrator/filter_resolver.py`:**

7. **Fix** `_build_explanation(root)` at line 843-855: replace `"; ".join(parts)` with `f" {root.logic.upper()} ".join(parts)` at root level
8. **Fix** `_explain_group(group)` at line 874: change `group.logic` (parent's logic) to `child.logic` (child group's own logic) — this is the nested group bug where an OR group inside an AND group incorrectly renders child conditions joined by "and"

The resolver fix requires **both** changes: root-level joiner (line 855) AND nested group joiner (line 874). The nested bug is that `_explain_group` uses the parameter `group` (which is the parent) to determine the joiner for child groups, when it should use `child.logic` instead.

### Example Outputs

| Filter | Before | After |
|--------|--------|-------|
| `length > 24 OR width > 24` | `Filter: length greater than 24; width greater than 24.` | `Filter: length greater than 24 OR width greater than 24.` |
| `service = Ground AND weight < 2` | `Filter: service equals Ground; weight less than 2.` | `Filter: service equals Ground AND weight less than 2.` |
| `(state in [CA, TX] OR weight > 10) AND value > 200` | `Filter: state in [CA, TX]; weight greater than 10; value greater than 200.` | `Filter: (state in [CA, TX] OR weight greater than 10) AND value greater than 200.` |

### Stale Code Removed

The entire `explanation_parts` pattern: accumulator variable, parameter threading through 4 function signatures, 16+ append calls. Net reduction in code complexity.

### Tests

- `tests/orchestrator/test_filter_compiler.py` — single condition, multi-AND, multi-OR, nested mixed

---

## Issue #9 — Service-Packaging Compatibility Layer

### Problem

No pre-flight validation prevents incompatible service+packaging combinations. A service override to Ground with UPS Letter packaging silently reaches UPS → error 111500. No domestic validation layer exists.

### Solution

Canonical compatibility matrices + `validate_domestic_payload()` function + auto-reset on service override + per-row validation in BatchEngine.

### Part A: Canonical Compatibility Matrices

**File:** `src/services/ups_constants.py` (after line 104)

```python
EXPRESS_ONLY_PACKAGING: frozenset[str]  # Letter, PAK, Tube, Express Box variants
EXPRESS_CLASS_SERVICES: frozenset[str]  # 01, 02, 13, 14, 59, 07, 54, 65
SATURDAY_DELIVERY_SERVICES: frozenset[str]  # 01, 02, 13, 14, 59
SERVICE_WEIGHT_LIMITS_LBS: dict[str, float]  # Per-service max weight
DEFAULT_WEIGHT_LIMIT_LBS: float = 150.0
LETTER_MAX_WEIGHT_LBS: float = 1.1
INTERNATIONAL_ONLY_PACKAGING: frozenset[str]  # 25kg Box, 10kg Box
```

### Part B: Domestic Validation Function

**File:** `src/services/ups_payload_builder.py`

```python
@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str  # "error" | "warning"
    auto_corrected: bool = False

def validate_domestic_payload(
    order_data: dict[str, Any], service_code: str
) -> list[ValidationIssue]:
```

Checks:
1. Packaging-service compatibility (EXPRESS_ONLY_PACKAGING vs EXPRESS_CLASS_SERVICES)
2. International-only packaging with domestic services
3. Letter weight limit (> 1.1 lbs)
4. Saturday Delivery with non-express services (warning, auto-strip)
5. Per-service weight limit exceeded

### Part C: Shared Compatibility Validation + Auto-Reset

**File:** `src/services/ups_payload_builder.py`

A single function `apply_compatibility_corrections(order_data: dict, service_code: str) -> list[ValidationIssue]` that:
1. Runs `validate_domestic_payload()` to detect issues
2. For auto-correctable issues (express-only packaging with non-express service, Saturday Delivery with non-express): mutates `order_data` in-place and returns issues with `auto_corrected=True`
3. For non-correctable errors (overweight, international-only packaging): returns issues with `severity="error"`

This function is the **single shared path** called from:
- `src/orchestrator/agent/tools/core.py:_build_job_row_data_with_metadata()` — at preview-time row building when `service_code_override` is applied
- `src/services/batch_engine.py:_process_row()` — at execution-time after `eff_service` is resolved (line 503), covering the confirm-time `selected_service_code` override from `preview.py:231`

Both paths call the same function, ensuring identical validation regardless of whether the service code was set at preview time (via pipeline tool) or at confirm time (via `selected_service_code` in the confirm request).

### Part D: BatchEngine Integration

**File:** `src/services/batch_engine.py` (after international validation ~line 524)

After `eff_service` is resolved at line 503:
1. Call `apply_compatibility_corrections(order_data, eff_service)`
2. Hard errors → raise `ValueError` (row gets `needs_review` status)
3. Auto-corrected warnings → log to stderr, row proceeds with corrected data

### Part E: Preview Notice (Reuses Existing Warnings Pattern)

Auto-corrections surface through the **existing** `warnings` field on `PreviewRowResponse` — no new `adjustments` field needed. The existing `rows_with_warnings` counter and PreviewCard warning rendering already handle this.

When `apply_compatibility_corrections()` auto-corrects packaging or strips Saturday Delivery:
- Add a warning string to the row's `warnings` list: e.g., `"Packaging auto-reset from UPS Letter to Customer Supplied: incompatible with Ground"`
- The metadata keys `_packaging_auto_reset` and `_saturday_delivery_stripped` are stored in `order_data` for audit but are NOT exposed as a separate API field

This avoids adding new schema fields (`adjustments`) to `BatchPreviewResponse`, `BatchPreview` TS type, and `PreviewCard`. The existing warning rendering in `PreviewCard.tsx:250-264` already handles per-row warnings.

### Part F: System Prompt Update

**File:** `src/orchestrator/agent/system_prompt.py`

Add packaging-service compatibility guidance for batch mode.

### Part G: Multi-Field Override

**File:** `src/orchestrator/agent/tools/pipeline.py`

Add optional `packaging_type` parameter to `ship_command_pipeline` tool definition.

### Tests

- `tests/services/test_ups_constants.py` — frozenset validation (existing file, extend)
- `tests/services/test_ups_payload_builder.py` — validate_domestic_payload() + apply_compatibility_corrections() (existing file, add new test classes)
- `tests/orchestrator/agent/test_tools_core.py` — auto-reset behavior in _build_job_row_data_with_metadata (new file, follows existing `test_tools_*.py` pattern)
- `tests/services/test_batch_engine.py` — per-row domestic validation integration (existing file, add new test class)

---

## Issue #11 — Schema & Payload Completeness (P0+P1)

### Problem

ExternalOrder model drops platform-specific fields (20 fixed fields). UPS payload builder omits dozens of documented UPS API fields.

### Scope

P0 + P1 fields only. P2/P3 (DryIce, HazMat, EEI, UPSPremier, SimpleRate, GlobalTaxInformation) tracked as follow-up issues.

### Sub-Problem A: Platform Field Promotion

#### A1: ExternalOrder Model Expansion

**File:** `src/mcp/external_sources/models.py` (after `item_count`)

New fields:
- `customer_tags: str | None` — Customer tags (comma-separated)
- `customer_order_count: int | None` — Historical order count
- `customer_total_spent: str | None` — Lifetime spend
- `order_note: str | None` — Order note from customer/merchant
- `risk_level: str | None` — Platform risk assessment (LOW/MEDIUM/HIGH)
- `shipping_rate_code: str | None` — Checkout shipping rate code
- `line_item_types: str | None` — Distinct product types (comma-separated)
- `discount_codes: str | None` — Applied discount codes (comma-separated)
- `custom_attributes: dict[str, Any]` — Arbitrary platform-specific fields

#### A2: Shopify Client Normalization

**File:** `src/mcp/external_sources/clients/shopify.py` (`_normalize_order()`)

Populate new fields from Shopify API response:
- `customer_tags` from `customer.tags`
- `customer_order_count` from `customer.orders_count`
- `customer_total_spent` from `customer.total_spent`
- `order_note` from `note`
- `risk_level` from risk assessments
- `shipping_rate_code` from `shipping_lines[0].code`
- `line_item_types` from `line_items[].product_type`
- `discount_codes` from `discount_codes[].code`
- `custom_attributes` from `note_attributes[]` + `line_items[].properties[]`

#### A2.1: custom_attributes JSON Serialization Strategy

**Critical**: `import_records()` in `source_info_tools.py:100-109` creates ALL DuckDB columns as VARCHAR and serializes values with `str(record.get(col, ""))`. A Python dict like `{"gift_message": "yes"}` becomes the string `"{'gift_message': 'yes'}"` (Python repr) — this is NOT valid JSON and `json_extract_string()` will fail on it.

**Fix:** In `_prepare_shopify_import_rows()` (`src/orchestrator/agent/tools/data.py:743-769`), serialize `custom_attributes` with `json.dumps()` BEFORE the row dict is passed to `import_records`:

```python
import json

for row in rows:
    custom_attrs = row.get("custom_attributes")
    if isinstance(custom_attrs, dict):
        row["custom_attributes"] = json.dumps(custom_attrs)
    elif custom_attrs is None:
        row["custom_attributes"] = "{}"
```

This ensures the DuckDB VARCHAR column contains valid JSON strings like `'{"gift_message": "yes"}'` instead of Python repr strings like `"{'gift_message': 'yes'}"`. The `json_extract_string()` SQL function in A4 will then work correctly.

#### A3: Other Platform Clients — Backward Compatibility

All new ExternalOrder fields use `Optional[T] = None` defaults (or `dict = Field(default_factory=dict)` for `custom_attributes`). This ensures **zero breaking changes** for WooCommerce (`woocommerce.py:359`), SAP (`sap.py:397`), and Oracle (`oracle.py:434`) clients — they construct ExternalOrder without the new fields, which safely default to None/empty.

**No code changes required** in Woo/SAP/Oracle clients for this PR. These clients can be enriched in follow-up PRs when equivalent platform fields are identified. A backward-compat test validates that constructing ExternalOrder with only the existing 27 fields succeeds.

#### A4: DuckDB JSON Path Filter Support

**File:** `src/orchestrator/filter_compiler.py` (`_compile_condition()`)

Detect `custom_attributes.*` column prefix → generate `json_extract_string("custom_attributes", '$.key')` SQL. Skip standard column validation for this prefix.

#### A5: System Prompt Update

Add new fields to schema hints and filter examples.

### Sub-Problem B: UPS Payload Field Coverage

#### B1: Column Mapping

**File:** `src/services/column_mapping.py`

New `_FIELD_TO_ORDER_DATA` entries:

**P0 — Shipment level:**
- `shipmentDate` → `shipment_date`
- `shipFrom.*` → `ship_from_name`, `ship_from_address1`, etc.

**P1 — Service options:**
- `costCenter` → `cost_center`
- `holdForPickup` → `hold_for_pickup`
- `shipperRelease` → `shipper_release`
- `liftGatePickup` → `lift_gate_pickup`
- `liftGateDelivery` → `lift_gate_delivery`
- `insideDelivery` → `inside_delivery`
- `directDeliveryOnly` → `direct_delivery_only`
- `deliverToAddresseeOnly` → `deliver_to_addressee_only`
- `carbonNeutral` → `carbon_neutral`
- `dropoffAtFacility` → `dropoff_at_facility`
- `notification.email` → `notification_email`

**P1 — Package level:**
- `largePackage` → `large_package`
- `additionalHandling` → `additional_handling`

**P1 — International forms:**
- `termsOfShipment` → `terms_of_shipment`
- `purchaseOrderNumber` → `purchase_order_number`
- `invoiceComments` → `invoice_comments`
- `freightCharges` → `freight_charges`
- `insuranceCharges` → `insurance_charges`

New `_AUTO_MAP_RULES` entries for auto-detection.

#### B2: Simplified Dict

**File:** `src/services/ups_payload_builder.py` (`build_shipment_request()`)

Read each new field from `order_data`, include in simplified dict with appropriate key naming.

#### B3: UPS JSON + ShipFrom Precedence

**File:** `src/services/ups_payload_builder.py` (`build_ups_api_payload()`)

Map simplified keys to UPS JSON structures:
- `ShipmentDate` → `Shipment.ShipmentDate`
- `ShipFrom` → `Shipment.ShipFrom` (Address, Name, Phone)
- Boolean indicators → empty-string presence flags in `ShipmentServiceOptions`
- `CostCenter` → `Shipment.CostCenter`
- `Notification` → `ShipmentServiceOptions.Notification` (code + email)
- Package-level indicators → per-package `PackageServiceOptions`

**ShipFrom vs Shipper Precedence Rules:**
- **Shipper** (line 478): Always from system config (`build_shipper()` → env vars `UPS_SHIPPER_*`). This is the billing entity and never changes per-row.
- **ShipFrom** (new): Row-level `ship_from_*` fields override the system shipper for the physical origin address. This supports multi-warehouse scenarios where each row ships from a different location.
- If no `ship_from_*` fields are present in `order_data`, the `ShipFrom` block is **omitted entirely** — UPS defaults to using the Shipper address as the ship-from address.
- If ANY `ship_from_*` field is present, the full `ShipFrom` block is built from row data with `ship_from_country` defaulting to `"US"`.

#### B3.1: Rate Payload Parity

**File:** `src/services/ups_payload_builder.py` (`build_rate_payload()` at line 990+)

The rate payload must mirror surcharge-affecting indicators for accurate preview cost estimation. Add the following to `build_rate_payload()` alongside the existing `SaturdayDeliveryIndicator` and `DeliveryConfirmation`:

- `HoldForPickupIndicator` (affects surcharge)
- `LiftGateForPickUpIndicator` (affects surcharge)
- `LiftGateForDeliveryIndicator` (affects surcharge)
- `UPScarbonneutralIndicator` (affects cost)
- `InsideDelivery` (affects surcharge)
- `LargePackageIndicator` (affects surcharge)
- `AdditionalHandlingIndicator` (affects surcharge)

Without these, preview costs will be lower than actual execution costs when these options are enabled.

#### B4: International Forms Enrichment

**File:** `src/services/ups_payload_builder.py` (`_enrich_international_forms()`)

Add: TermsOfShipment, PurchaseOrderNumber, Comments, FreightCharges, InsuranceCharges.

#### B5: Tests

- `tests/services/test_ups_payload_builder.py` — all P0/P1 fields end-to-end (existing file, add new test class)
- `tests/services/test_column_mapping.py` — new auto-map rules (existing file, add new test class)
- `tests/mcp/external_sources/test_shopify_normalize.py` — new ExternalOrder fields (existing file, extend)
- `tests/mcp/external_sources/test_clients.py` — backward compat: ExternalOrder with only original fields (existing file)

### Fields Deferred to Follow-Up (P2/P3)

- DryIce, HazMat, RefrigerationIndicator
- EEI/AES export filing, InBondCode
- GlobalTaxInformation, ShipperType/ConsigneeType
- UPSPremier, SimpleRate
- BlanketPeriod, ForwardAgent, UltimateConsignee, Producer
- RestrictedArticles, DGSignatoryInfo
- COD (shipment + package level)
- Shopify metafields (requires separate API call)

---

## Issue #8 — CLI Data Source Management

### Problem

CLI users have no data source lifecycle commands. Headless operators cannot check status, switch sources, reconnect saved profiles, or inspect schema.

### Solution

Add `data-source` Typer sub-app with 7 commands, extend `ShipAgentClient` protocol with 9 methods, implement in both HttpClient and InProcessRunner.

### Part A: Protocol Extension

**File:** `src/cli/protocol.py`

New data models:
- `DataSourceStatus` — connected, source_type, file_path, row_count, columns
- `SavedSourceSummary` — id, name, source_type, file_path, last_connected
- `SchemaColumn` — name, type, nullable, sample_values

New protocol methods:
- `get_source_status() -> DataSourceStatus`
- `connect_source(file_path: str) -> DataSourceStatus`
- `connect_db(connection_string: str, query: str) -> DataSourceStatus`
- `disconnect_source() -> None`
- `list_saved_sources() -> list[SavedSourceSummary]`
- `reconnect_saved_source(identifier: str, by_name: bool) -> DataSourceStatus`
- `get_source_schema() -> list[SchemaColumn]`
- `connect_platform(platform: str) -> DataSourceStatus` (Shopify only — validates env vars via `/shopify/env-status`)

### Part B: HttpClient Implementation

**File:** `src/cli/http_client.py`

Maps to existing REST endpoints:
- `GET /api/v1/data-sources/status`
- `POST /api/v1/data-sources/upload` (multipart)
- `POST /api/v1/data-sources/import` (requires `connection_string` + `query` for DB type)
- `POST /api/v1/data-sources/disconnect`
- `GET /api/v1/saved-sources`
- `POST /api/v1/saved-sources/reconnect`
- `GET /api/v1/platforms/shopify/env-status` (Shopify only — no generic `/{platform}/env-status`)
- `POST /api/v1/platforms/{platform}/connect` (credential-based, not used by CLI auto-connect)

### Part C: InProcessRunner Implementation

**File:** `src/cli/runner.py`

Calls gateway directly via `get_data_gateway()` and `get_external_sources_client()`.

### Part D: CLI Commands

**File:** `src/cli/main.py`

New `data_source` sub-app:

```
shipagent data-source status
shipagent data-source connect <file>
shipagent data-source connect --db <conn-string> --query <sql>
shipagent data-source connect --platform shopify
shipagent data-source list-saved
shipagent data-source reconnect <name-or-id>
shipagent data-source disconnect
shipagent data-source schema
```

**Note on `--db`**: The backend requires BOTH `connection_string` AND `query` for database imports (`data_sources.py:75-85`). The `--query` parameter is mandatory when using `--db`. Example: `shipagent data-source connect --db "postgresql://..." --query "SELECT * FROM orders WHERE status = 'open'"`.

**Note on `--platform`**: Only Shopify has an env-status auto-reconnect endpoint (`/shopify/env-status`). The `--platform` flag is scoped to `shopify` only. Other platforms (WooCommerce, SAP, Oracle) require explicit credential-based connection via the agent conversation or REST API. A generic `/{platform}/env-status` endpoint is not in scope for this PR.

### Part E: Interact Enhancement

**File:** `src/cli/main.py`

New flags on `interact`:
- `--file` — load file before REPL
- `--source` — reconnect saved source before REPL
- `--platform` — connect platform before REPL

### Part F: Config Enhancement

**File:** `src/cli/config.py`

New `DefaultDataSourceConfig` model + `default_data_source` field on `ShipAgentConfig`.

### Part G: Rich Output

**File:** `src/cli/output.py`

New formatters: `format_source_status()`, `format_saved_sources()`, `format_schema()`.

### Tests

- `tests/cli/test_protocol.py` — extend with data source protocol method tests (existing file)
- `tests/cli/test_http_client.py` — extend with data source HTTP method tests (existing file)
- `tests/cli/test_config.py` — extend with DefaultDataSourceConfig tests (existing file)
- `tests/cli/test_data_source_commands.py` — new file for Typer sub-app command tests

---

## Cross-Cutting Concerns

### Shared File Changes

| File | Issues | Changes |
|------|--------|---------|
| `src/services/ups_constants.py` | #9 | Compatibility matrices |
| `src/services/ups_payload_builder.py` | #9, #11 | validate_domestic_payload() + new field handling |
| `src/services/column_mapping.py` | #11 | New mapping entries + auto-map rules |
| `src/orchestrator/filter_compiler.py` | #10, #11 | AST explanation + JSON path support |
| `src/orchestrator/agent/system_prompt.py` | #9, #11 | Compatibility guidance + new field hints |
| `src/orchestrator/agent/tools/pipeline.py` | #9 | Multi-field override support |
| `src/orchestrator/agent/tools/core.py` | #9 | Auto-reset logic |

### Estimated Scope

| Issue | Files Changed | Lines Added | Lines Removed |
|-------|--------------|-------------|---------------|
| #10 | 3-4 | ~80 | ~50 |
| #9 | 6-7 | ~300 | ~10 |
| #11 | 8-10 | ~500 | ~20 |
| #8 | 7-8 | ~400 | ~0 |
| **Total** | **~20 unique files** | **~1280** | **~80** |

### Test Coverage Target

Each issue includes dedicated test files. All new fields, validation functions, and CLI commands have unit tests. Integration tests validate end-to-end flows (column mapping → order_data → simplified → UPS JSON for #11; CLI command → REST API → response for #8).
