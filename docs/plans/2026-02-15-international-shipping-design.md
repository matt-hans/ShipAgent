# International Shipping Design — CA/MX Phase

**Date**: 2026-02-15
**Status**: Approved
**Architecture**: Payload-Centric (Approach A)

---

## 1. Scope & Decisions

| Decision | Choice |
|----------|--------|
| Destination countries | Canada & Mexico only (US→CA, US→MX) |
| Shipping flows | Both batch (CSV/Excel/Shopify) and interactive (chat) |
| Service codes | All 5 UPS international: 07, 08, 11, 54, 65 |
| Customs documentation | Full InternationalForms with commercial invoice |
| Commodities | Multi-commodity per shipment |
| Multi-commodity format | Separate commodities sheet/table linked by order ID |
| Cost display | Itemized breakdown (shipping, duties/taxes, brokerage) |
| Missing field handling | MCP elicitation for interactive; descriptive failure for batch |
| Feature flag | `INTERNATIONAL_ENABLED_LANES` env var, default-off in production |

---

## 2. Architecture: Payload-Centric with International Enrichers

All international logic is centralized in the payload builder layer. The payload builder detects international shipments (origin ≠ destination country), queries the rules engine for requirements, injects required fields, and builds InternationalForms from commodity data. The rest of the system passes data through.

**Why Approach A**:
- Compliance logic is deterministic and testable at the payload boundary
- Avoids making conversational quality the critical path for correctness
- Minimizes blast radius by extending existing builder flow
- Scales with rule modules rather than prompt complexity

**Agent role**: Assistive, not authoritative. Agent learns about international services and guides users but does not own compliance logic. MCP elicitation acts as safety net for interactive path only.

---

## 3. International Eligibility & Requirements Rules Layer

**New module**: `src/services/international_rules.py`

A deterministic rules engine that, given origin country, destination country, and service code, returns exactly which fields are required.

### RequirementSet Output

```python
@dataclass
class RequirementSet:
    rule_version: str                    # e.g., "1.0.0" for auditability
    effective_date: str                  # ISO8601 date
    is_international: bool
    requires_description: bool
    requires_shipper_contact: bool
    requires_recipient_contact: bool
    requires_invoice_line_total: bool
    requires_international_forms: bool
    requires_commodities: bool
    supported_services: list[str]
    currency_code: str
    form_type: str                       # "01" = commercial invoice
    export_thresholds: dict | None       # EEI/ITN triggers, invoice value thresholds
    not_shippable_reason: str | None     # explicit reason if lane/service unsupported
```

### Lane Rules (separated from service capability rules)

| Lane | Description | InvoiceLineTotal | InternationalForms | Shipper Contact | Recipient Contact |
|------|-------------|------------------|-------------------|-----------------|-------------------|
| US→CA | US to Canada forward | Required | Required (commercial invoice) | Required | Required |
| US→MX | US to Mexico forward | Not required | Required (commercial invoice) | Required | Required |
| US→PR | US to Puerto Rico | Required | Not required (US territory) | Optional | Optional |

### Pre-Submit Validation

`validate_international_readiness(order_data, requirements) → list[ValidationError]`

Returns structured errors with:
- Machine code (e.g., `MISSING_RECIPIENT_PHONE`)
- Human-readable text (e.g., "Recipient phone number is required for international shipments")
- Field path (e.g., `ShipTo.Phone.Number`)

**Fail closed**: Unsupported lane/service combinations return `not_shippable_reason` with explicit explanation.

### Guardrails
- `rule_version` and `effective_date` in every RequirementSet for auditability
- Lane rules separated from service capability rules (service updates don't require lane rewrites)
- Value-based/export thresholds as first-class rule conditions
- Fail closed for unsupported lane/service combos

---

## 4. Payload Builder International Enrichment

**Modified module**: `src/services/ups_payload_builder.py`

### Enrichment Flow

1. Existing payload construction runs (shipper, ship-to, packages, service)
2. `InternationalRules.get_requirements()` called with origin/destination/service
3. If international → enrichment stage fires:
   - **Contact enrichment**: Inject `AttentionName` + `Phone.Number` for Shipper and ShipTo
   - **Description injection**: Set `Shipment.Description` from order_data
   - **InvoiceLineTotal injection**: For US→CA/PR, add `CurrencyCode` + `MonetaryValue`
   - **InternationalForms construction**: Build forms section with commodities
4. `validate_international_readiness()` runs on enriched payload
5. Pass → send to UPS MCP; Fail → batch: row fails with machine codes; interactive: MCP elicitation

### InternationalForms Structure

```python
"InternationalForms": {
    "FormType": "01",  # Commercial Invoice
    "InvoiceDate": "20260215",  # from carrier/account timezone policy
    "ReasonForExport": "SALE",
    "CurrencyCode": "USD",
    "Product": [
        {
            "Description": "Artisan Coffee Beans",
            "CommodityCode": "090111",
            "OriginCountryCode": "CO",
            "Unit": {
                "Number": "2",
                "UnitOfMeasurement": {"Code": "PCS", "Description": "Pieces"},
                "Value": "25.00"
            }
        }
    ]
}
```

### Key Changes to Existing Functions

- **Remove hardcoded "US" defaults** for country codes — fail with `MISSING_COUNTRY_CODE` instead
- **`normalize_phone()`**: Allow 7-15 digits, preserve country code prefix for international
- **`normalize_zip()`**: Pass through non-US postal codes without US-specific formatting
- **`stateProvinceCode`**: Optional when destination is non-US
- **`InvoiceDate`**: Single timezone policy (carrier/account timezone), not local runtime

### Column Mapping Additions (`column_mapping.py`)

New field mappings:
```python
"shipTo.attentionName": "ship_to_attention_name",
"shipper.attentionName": "shipper_attention_name",
"invoiceLineTotal.currencyCode": "invoice_currency_code",
"invoiceLineTotal.monetaryValue": "invoice_monetary_value",
"shipmentDescription": "shipment_description",
```

`REQUIRED_FIELDS` becomes context-aware: `validate_mapping()` accepts `destination_country` parameter. International destinations require additional fields.

### Guardrails
- Enrichment is idempotent (safe if called twice)
- Use `Decimal` for money types, normalize to UPS string format at serialization boundary
- Strict schema/contract test for `InternationalForms.Product[].Unit` shape
- `validate_international_readiness()` is lane-aware and phase-aware (batch vs interactive emit different handling paths)

---

## 5. Commodity Data Pipeline

### Multi-Table Join Design

The Data Source MCP gains commodity-level data serving from a separate sheet/table.

**New MCP tool**: `get_commodities_bulk(order_key_column, order_key_values: list[str])` — single query for all order IDs, returns grouped commodity dicts. Avoids N+1 lookups.

### Import Flow (Excel with commodities sheet)

1. User uploads Excel with "Orders" sheet + "Commodities" sheet
2. `import_excel` detects multiple sheets, imports both into DuckDB
3. Agent sees both schemas in system prompt
4. Batch engine calls `get_commodities_bulk` for all international rows
5. Commodities attached to `order_data["commodities"]` before payload construction

### Commodities Schema

| Column | Description | Required |
|--------|-------------|----------|
| `order_id` | Foreign key to shipments | Yes |
| `description` | Commodity description | Yes |
| `commodity_code` | HS tariff code (6-10 digits) | Yes |
| `origin_country` | Country of manufacture (ISO alpha-2) | Yes |
| `quantity` | Number of units (positive integer) | Yes |
| `unit_value` | Value per unit in invoice currency (Decimal) | Yes |
| `unit_of_measure` | UPS unit code (defaults to "PCS") | No |
| `weight` | Weight per unit | No |

### Source-Specific Commodity Sources

- **CSV**: Two files — shipments CSV + commodities CSV, both imported
- **Excel**: Two sheets in same workbook
- **Shopify**: `line_items` on each order normalized to commodity schema
- **Interactive**: Agent collects through conversation, no separate sheet

### Guardrails
- Enforce join integrity: explicit behavior for missing/duplicate order_id keys, deterministic ordering
- Validate currency consistency: commodity unit_value currency must match invoice currency
- Strict commodity validators: HS code format (6-10 digits), ISO country code, positive qty/value, allowed UPS UOM codes
- Cache hydrated commodities between preview and execute for payload stability

---

## 6. Agent & System Prompt Updates

### Service Code Expansion

`ServiceCode` enum gains:
```
WORLDWIDE_EXPRESS = "07"
WORLDWIDE_EXPEDITED = "08"
UPS_STANDARD = "11"
WORLDWIDE_EXPRESS_PLUS = "54"
WORLDWIDE_SAVER = "65"
```

`SERVICE_ALIASES` gains: "worldwide express" → 07, "international express" → 07, "worldwide expedited" → 08, "international expedited" → 08, "worldwide saver" → 65, "international saver" → 65, "worldwide express plus" → 54, "express plus" → 54.

### System Prompt Changes

- Service table adds international services with domestic/international distinction
- International shipping guidance section: enabled lanes, required fields, filter examples
- Guidance gated by `INTERNATIONAL_ENABLED_LANES` at runtime — prompt never over-promises
- Negative examples: missing country should not silently become US

### Row Normalization Fix

`_normalize_rows_for_shipping()` in `core.py`:
- **Remove** silent `"US"` default
- Missing `ship_to_country` → leave missing, caught by rules engine with `MISSING_COUNTRY_CODE`

### Interactive Tool Updates

- `ship_to_country` explicitly collected (no silent default)
- New optional fields: `ship_to_phone`, `shipment_description`, `invoice_currency_code`, `invoice_monetary_value`
- MCP elicitation as safety net for fields agent misses

### Guardrails
- Service code validation source-of-truth in one shared module (avoid enum/prompt drift)
- `prompt_version` in logs for traceability
- `destination_countries` derived from normalized data, not free-form text, for audit integrity

---

## 7. Response Parsing & Cost Breakdown

### UPS Response Parsing

`_normalize_shipment_response()` and `_normalize_rate_response()` extract itemized charges:

```python
{
    "totalCharges": {"monetaryValue": "65.50", "currencyCode": "USD"},
    "transportationCharges": {"monetaryValue": "45.50", "currencyCode": "USD"},
    "dutiesAndTaxes": {"monetaryValue": "12.00", "currencyCode": "USD"},
    "brokerageCharges": {"monetaryValue": "8.00", "currencyCode": "USD"},
}
```

Parser paths: `ShipmentCharges.TransportationCharges`, `ShipmentCharges.DutyAndTaxCharges`, `ShipmentCharges.ServiceOptionsCharges`, `NegotiatedRateCharges`.

If breakdown absent (domestic): only `totalCharges` populated.

### Database Schema Changes

`JobRow` gains:
- `destination_country: str | None` — ISO alpha-2
- `duties_taxes_cents: int | None`
- `charge_breakdown: str | None` — JSON blob, versioned

`Job` gains:
- `total_duties_taxes_cents: int | None`
- `international_row_count: int` (default 0)

### API Schema Changes

All response models gain optional international fields (destination_country, duties_taxes_cents, charge_breakdown, total_duties_taxes_cents, international_row_count).

### Guardrails
- `charge_breakdown_version` for schema evolution traceability
- Currency consistency checks before aggregating totals
- Parse money with `Decimal`, convert to cents once centrally
- Preserve raw UPS charge fragments in audit logs
- Contract tests for negotiated/non-negotiated responses and missing breakdown fields

---

## 8. Frontend Changes

### TypeScript Types

`PreviewRow`, `JobRow` gain: `destination_country?`, `duties_taxes_cents?`, `charge_breakdown?`
`BatchPreview`, `Job` gain: `total_duties_taxes_cents?`, `international_row_count?`

Shared `ChargeBreakdown` type with runtime normalizer for malformed payloads.

### Component Changes

**PreviewCard**: Itemized cost lines (Shipping / Duties & Taxes / Brokerage / Total), country badge, international count in stats.

**CompletionArtifact**: International indicator badge, cost breakdown on expand.

**ProgressDisplay**: Duties/taxes as fourth metric for international batches.

**JobDetailPanel**: Destination country and charge breakdown in row detail expansion.

### Guardrails
- Centralize money formatting (`Intl.NumberFormat`) using provided `currencyCode`
- Deterministic render order: transportation → duties/taxes → brokerage → other
- Backend `total` is source-of-truth (prevent double-counting)
- Click/expand behavior (not hover-only) for mobile/keyboard accessibility
- Cents-to-decimal conversion in one shared utility
- Domestic-regression UI snapshots: no visual change when international fields absent

---

## 9. Error Handling

### New Error Codes

| Code | Category | Message |
|------|----------|---------|
| `E-2013` | VALIDATION | Missing required international field: `{field_name}` |
| `E-2014` | VALIDATION | Invalid HS tariff code: `{hs_code}` |
| `E-2015` | VALIDATION | Unsupported shipping lane: `{origin}→{destination}` |
| `E-2016` | VALIDATION | Service `{service}` not available for `{origin}→{destination}` |
| `E-2017` | VALIDATION | Currency mismatch: `{commodity_currency}` vs `{invoice_currency}` |
| `E-3006` | UPS_API | Customs validation failed: `{ups_message}` (with subreasons) |

All error codes include `retryable` and `http_status` metadata for deterministic orchestration.

`E-3006` splits into normalized subreasons (`CUSTOMS_MISSING_DATA`, `CUSTOMS_INVALID_HS`, etc.) while preserving raw UPS text.

### Error Translation

`UPS_ERROR_MAP` gains international UPS error codes. `UPS_MESSAGE_PATTERNS` gains "customs", "export", "duty", "commercial invoice" patterns. Snapshot tests for regression.

---

## 10. Testing Strategy

### Unit Tests (deterministic)
- `test_international_rules.py` — lane requirements, service eligibility, validation, unsupported lane rejection, threshold triggers
- `test_payload_builder_international.py` — InternationalForms construction, contact enrichment, InvoiceLineTotal, idempotency, schema contracts
- `test_commodity_validation.py` — HS code format, currency consistency, positive values, join integrity
- `test_column_mapping_international.py` — context-aware required fields, auto-map patterns
- `test_response_parsing_international.py` — charge breakdown, missing breakdown fallback, negotiated rates
- `test_international_error_codes.py` — code resolution, machine codes + human text, snapshot regression

### Integration Tests (gated by `RUN_UPS_INTEGRATION=1`)
- `test_international_rate.py` — rate US→CA with commodities, verify duties in response
- `test_international_ship.py` — create US→CA shipment, verify label + customs docs
- Stable fixtures, explicit skip messaging in CI

### End-to-End Tests
- Mixed domestic + international batch: partial failure handling, correct aggregates
- Domestic-only batch: zero behavioral change (regression)
- Interactive international shipment via agent conversation

### Frontend Tests
- Domestic-regression snapshots (no visual change)
- International preview with charge breakdown renders correctly
- Country badge, international indicator display

---

## 11. Pre-Implementation Checklist

1. `INTERNATIONAL_ENABLED_LANES` default-off in production until pilot
2. Migration order: DB → API schemas → backend services → agent → frontend, with rollback at each step
3. Kill-switch: setting `INTERNATIONAL_ENABLED_LANES=""` immediately disables all international paths
4. DoD: unit + integration coverage, mixed domestic+international batch pass, no domestic UI regressions

## 12. Observability Requirements

- `rule_version` logged on every international validation
- `prompt_version` logged on every agent interaction
- Error code metrics per lane (E-2013 through E-3006)
- Per-lane success/failure rates (US→CA, US→MX)
- Raw UPS charge fragments preserved in audit logs

## 13. Rollout Phases

| Phase | Lane | Exit Criteria |
|-------|------|--------------|
| Phase 1: Pilot | US→CA only | 50+ successful shipments, <5% failure rate, no domestic regressions |
| Phase 2: Expand | US→MX added | 25+ MX shipments, commodity validation stable, error codes actionable |
| Phase 3: GA | Both lanes GA | Feature flag removed, documentation published, test data updated |

---

## Files Changed/Created

| Action | File | Purpose |
|--------|------|---------|
| CREATE | `src/services/international_rules.py` | Lane-driven requirements engine |
| MODIFY | `src/services/ups_payload_builder.py` | International enrichment, InternationalForms, remove US defaults |
| MODIFY | `src/services/column_mapping.py` | International field mappings, context-aware validation |
| MODIFY | `src/services/ups_mcp_client.py` | Charge breakdown extraction |
| MODIFY | `src/services/batch_engine.py` | Commodity hydration, international pre-check |
| MODIFY | `src/orchestrator/models/intent.py` | International service codes + aliases |
| MODIFY | `src/orchestrator/agent/system_prompt.py` | International guidance |
| MODIFY | `src/orchestrator/agent/tools/__init__.py` | Interactive tool international fields |
| MODIFY | `src/orchestrator/agent/tools/core.py` | Remove silent US default |
| MODIFY | `src/orchestrator/agent/tools/interactive.py` | International field collection |
| MODIFY | `src/orchestrator/agent/tools/pipeline.py` | International context to batch engine |
| MODIFY | `src/mcp/data_source/tools/query_tools.py` | `get_commodities_bulk` tool |
| MODIFY | `src/mcp/data_source/tools/import_tools.py` | Multi-sheet import awareness |
| MODIFY | `src/db/models.py` | International columns |
| MODIFY | `src/api/schemas.py` | International response fields |
| MODIFY | `src/errors/registry.py` | E-2013 through E-2017, E-3006 |
| MODIFY | `src/errors/ups_translation.py` | International error mappings |
| MODIFY | `frontend/src/types/api.ts` | International TypeScript types |
| MODIFY | `frontend/src/components/command-center/PreviewCard.tsx` | Charge breakdown, country badge |
| MODIFY | `frontend/src/components/command-center/CompletionArtifact.tsx` | International indicator |
| MODIFY | `frontend/src/components/command-center/ProgressDisplay.tsx` | Duties/taxes metric |
| MODIFY | `frontend/src/components/JobDetailPanel.tsx` | International detail display |
| CREATE | `tests/services/test_international_rules.py` | Rules engine tests |
| CREATE | `tests/services/test_payload_builder_international.py` | International payload tests |
| CREATE | `tests/services/test_commodity_validation.py` | Commodity data tests |
