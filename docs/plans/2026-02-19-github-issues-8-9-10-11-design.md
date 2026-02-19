# GitHub Issues #8, #9, #10, #11 — Unified Resolution Design

**Date:** 2026-02-19
**Status:** Approved
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
| Service-packaging auto-reset | Auto-correct + visible notice in PreviewCard | Least friction; user sees what was adjusted |
| Issue #11 scope | P0 + P1 fields only | P2/P3 tracked as follow-up issues |
| Filter explanation fix | Option B — AST-based recursive explanation | Single source of truth; removes stale accumulator |
| CLI connect scope | Files + DB strings + env-based platforms | Full headless coverage |
| Domestic validation mode | Per-row validation | Matches existing international validation pattern |
| custom_attributes | Full JSON path filtering via DuckDB json_extract | Complete solution |
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

### Part C: Auto-Reset on Service Override

**File:** `src/orchestrator/agent/tools/core.py` (after line 262)

When `service_code_override` applied:
- If packaging ∈ `EXPRESS_ONLY_PACKAGING` and service ∉ `EXPRESS_CLASS_SERVICES`: reset to `DEFAULT_PACKAGING_CODE`, store `_packaging_auto_reset` metadata
- If `saturday_delivery` truthy and service ∉ `SATURDAY_DELIVERY_SERVICES`: clear flag, store `_saturday_delivery_stripped` metadata

### Part D: BatchEngine Integration

**File:** `src/services/batch_engine.py` (after international validation ~line 524)

Per-row validation — incompatible rows get `needs_review` status, valid rows proceed.

### Part E: Preview Notice

`_packaging_auto_reset` and `_saturday_delivery_stripped` metadata keys included in preview response as `adjustments` field. PreviewCard shows subtle notice bar.

### Part F: System Prompt Update

**File:** `src/orchestrator/agent/system_prompt.py`

Add packaging-service compatibility guidance for batch mode.

### Part G: Multi-Field Override

**File:** `src/orchestrator/agent/tools/pipeline.py`

Add optional `packaging_type` parameter to `ship_command_pipeline` tool definition.

### Tests

- `tests/services/test_ups_constants.py` — frozenset validation
- `tests/services/test_ups_payload_builder.py` — validate_domestic_payload() cases
- `tests/orchestrator/agent/test_core_override.py` — auto-reset behavior
- `tests/services/test_batch_engine.py` — per-row validation integration

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

#### A3: Other Platform Clients

WooCommerce, SAP, Oracle clients updated for equivalent fields where available.

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

#### B3: UPS JSON

**File:** `src/services/ups_payload_builder.py` (`build_ups_api_payload()`)

Map simplified keys to UPS JSON structures:
- `ShipmentDate` → `Shipment.ShipmentDate`
- `ShipFrom` → `Shipment.ShipFrom` (Address, Name, Phone)
- Boolean indicators → empty-string presence flags in `ShipmentServiceOptions`
- `CostCenter` → `Shipment.CostCenter`
- `Notification` → `ShipmentServiceOptions.Notification` (code + email)
- Package-level indicators → per-package `PackageServiceOptions`

#### B4: International Forms Enrichment

**File:** `src/services/ups_payload_builder.py` (`_enrich_international_forms()`)

Add: TermsOfShipment, PurchaseOrderNumber, Comments, FreightCharges, InsuranceCharges.

#### B5: Tests

- `tests/services/test_ups_payload_builder.py` — all P0/P1 fields end-to-end
- `tests/services/test_column_mapping.py` — new auto-map rules
- `tests/mcp/external_sources/test_shopify_normalization.py` — new ExternalOrder fields

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
- `connect_db(connection_string: str) -> DataSourceStatus`
- `disconnect_source() -> None`
- `list_saved_sources() -> list[SavedSourceSummary]`
- `reconnect_saved_source(identifier: str, by_name: bool) -> DataSourceStatus`
- `get_source_schema() -> list[SchemaColumn]`
- `get_platform_env_status(platform: str) -> dict`
- `connect_platform(platform: str) -> DataSourceStatus`

### Part B: HttpClient Implementation

**File:** `src/cli/http_client.py`

Maps to existing REST endpoints:
- `GET /api/v1/data-sources/status`
- `POST /api/v1/data-sources/upload` (multipart)
- `POST /api/v1/data-sources/import`
- `POST /api/v1/data-sources/disconnect`
- `GET /api/v1/saved-sources`
- `POST /api/v1/saved-sources/reconnect`
- `GET /api/v1/platforms/{platform}/env-status`
- `POST /api/v1/platforms/{platform}/connect`

### Part C: InProcessRunner Implementation

**File:** `src/cli/runner.py`

Calls gateway directly via `get_data_gateway()` and `get_external_sources_client()`.

### Part D: CLI Commands

**File:** `src/cli/main.py`

New `data_source` sub-app:

```
shipagent data-source status
shipagent data-source connect <file>
shipagent data-source connect --db <conn-string>
shipagent data-source connect --platform <name>
shipagent data-source list-saved
shipagent data-source reconnect <name-or-id>
shipagent data-source disconnect
shipagent data-source schema
```

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

- `tests/cli/test_data_source_commands.py`
- `tests/cli/test_protocol_data_source.py`
- `tests/cli/test_config_data_source.py`

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
