# UPS MCP Pivot: Direct Python Import + Deterministic Payloads

**Date:** 2026-02-09
**Status:** Approved
**Scope:** Replace TypeScript UPS MCP with Python fork (direct import), consolidate batch execution, enforce deterministic payload building, remove template generation pipeline.

---

## Problem

ShipAgent has accumulated redundant complexity around UPS integration:

1. **TypeScript UPS MCP** (`packages/ups-mcp/`) requires Node.js, spawned as subprocess, communicated via JSON-RPC over stdio. The Python UPS MCP fork (`ups-mcp` pip package) does the same thing natively in Python.

2. **Two batch execution paths** exist: the REST API path (`preview.py` confirm endpoint) and the orchestrator path (`executor.py`). Both do the same thing differently.

3. **LLM-generated Jinja2 templates** create UPS payloads from source data. This is a hallucination risk — the LLM generates code that touches shipment data. ~1100 lines of template generation, validation, and self-correction machinery support this.

4. **The payload builder already exists** (`ups_payload_builder.py`) and does deterministic payload construction. It's only used by one of the two paths.

## Design Principles

- **LLM = Orchestrator only.** Parses user intent, calls tools in order. Never generates or touches shipment data.
- **Deterministic payload building.** All UPS payloads constructed by Python code from source data + structured intent. No templates, no LLM-generated transformations.
- **Direct Python import.** The UPS MCP fork is a library, not a subprocess. No stdio, no JSON-RPC, no MCP protocol overhead.
- **Delete more than we write.** Net reduction in code and complexity.

---

## Architecture

```
User (NL command via UI)
    |
    v
LLM Orchestrator (parses intent, calls tools in order)
    |
    v
+--------------------------------------------------+
|           Deterministic Execution Layer           |
|                                                   |
|  Data Source MCP --> Payload Builder --> UPS SDK   |
|  (Shopify/CSV/DB)   (Python code)    (fork)       |
+--------------------------------------------------+
    |
    v
REST API --> UI (preview, progress, results)
```

### LLM responsibilities (orchestration only)

- Parse NL intent: service code, filters, accessorials
- For CSV/Excel: map column names to shipment fields (one-time config step)
- Call tools in sequence: fetch data -> preview -> (user approves) -> execute
- Never touches row-level shipment data

### Deterministic code responsibilities

- Pull data from sources (Shopify API, CSV via DuckDB)
- Build UPS payloads from source data + parsed intent
- Call UPS APIs via the Python fork's ToolManager (direct import)
- Extract results (tracking numbers, labels, costs)
- All error translation and response normalization

---

## Component Design

### 1. UPS Service Layer (`src/services/ups_service.py` - new)

Thin wrapper around the fork's `ToolManager`. Replaces `src/mcp/ups_client.py` (~450 lines of subprocess/JSON-RPC).

```python
from ups_mcp.tools import ToolManager

class UPSService:
    def __init__(self, base_url, client_id, client_secret):
        self._tm = ToolManager(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
        )

    def create_shipment(self, request_body: dict) -> dict:
        raw = self._tm.create_shipment(request_body=request_body)
        return self._normalize_shipment_response(raw)

    def get_rate(self, request_body: dict) -> dict:
        raw = self._tm.rate_shipment(
            requestoption="Rate", request_body=request_body,
        )
        return self._normalize_rate_response(raw)

    def validate_address(self, **params) -> dict:
        raw = self._tm.validate_address(**params)
        return self._normalize_address_response(raw)

    def void_shipment(self, shipment_id: str) -> dict:
        raw = self._tm.void_shipment(
            shipmentidentificationnumber=shipment_id,
        )
        return self._normalize_void_response(raw)
```

- ToolManager uses synchronous `requests`. Callers use `asyncio.to_thread()` at the call site.
- Fork raises `ToolError(json.dumps({status_code, code, message, details}))`. We catch directly in Python — no JSON-extraction-from-MCP-error-text chain.
- Response normalization methods extract: tracking numbers, label base64, costs in cents, shipment identification number.

### 2. Consolidated Batch Engine (`src/services/batch_engine.py` - new)

Replaces both `src/api/routes/preview.py` execution logic and `src/orchestrator/batch/executor.py`.

```python
class BatchEngine:
    def __init__(self, ups_service: UPSService, job_service: JobService):
        self._ups = ups_service
        self._jobs = job_service

    async def preview(self, job_id, rows, shipper, intent) -> BatchPreview:
        """Rate first N rows, estimate total cost."""
        # deterministic payload build -> UPS rate quote per row

    async def execute(self, job_id, rows, shipper, intent,
                      on_progress=None) -> BatchResult:
        """Execute all rows with per-row state for crash recovery."""
        # For each pending row:
        #   1. build_shipment_request(row, shipper, intent)
        #   2. await asyncio.to_thread(self._ups.create_shipment, payload)
        #   3. Save tracking/label/cost to JobRow
        #   4. Call on_progress (drives SSE in REST API)

    async def resume(self, job_id, ...) -> BatchResult:
        """Resume interrupted batch from last successful row."""
```

- `ShippingIntent` is the structured output from LLM intent parsing (service code, accessorials, user overrides). Pure data, no templates.
- `on_progress` callback lets the REST API wire in SSE events without the engine knowing about HTTP.
- Crash recovery: per-row state writes to SQLite, resume picks up from last successful row.

### 3. Column Mapping (`src/services/column_mapping.py` - new)

For CSV/Excel with arbitrary column names. Replaces the Jinja2 template generation pipeline (~1100 lines).

The LLM produces a simple lookup table:

```python
column_mapping = {
    "shipTo.name": "recipient_name",
    "shipTo.addressLine1": "ship_address",
    "shipTo.city": "city",
    "shipTo.stateProvinceCode": "state",
    "shipTo.postalCode": "zip_code",
    "shipTo.countryCode": "country",
    "packages[0].weight": "weight_lbs",
}
```

Stored on the Job as JSON. At execution time, deterministic code reads each row using the mapping, then passes extracted values to `build_shipment_request()`.

Validation: check all required fields have a mapping entry before preview/execution. Fail immediately if not — no self-correction loop.

### 4. Enhanced Payload Builder (`src/services/ups_payload_builder.py` - modified)

Enhanced to accept the full UPS field surface and `ShippingIntent`:

**ShipTo fields (9):**

| Field | Required | UPS Max |
|-------|----------|---------|
| `shipTo.name` | yes | 35 |
| `shipTo.attentionName` | no | 35 |
| `shipTo.addressLine1` | yes | 35 |
| `shipTo.addressLine2` | no | 35 |
| `shipTo.addressLine3` | no | 35 |
| `shipTo.city` | yes | 30 |
| `shipTo.stateProvinceCode` | yes | 5 |
| `shipTo.postalCode` | yes | 9 |
| `shipTo.countryCode` | yes | 2 |
| `shipTo.phone` | no | 15 |

**Package fields (per-package, supports `packages[N].field`):**

| Field | Required |
|-------|----------|
| `packages[0].weight` | yes |
| `packages[0].length` | no |
| `packages[0].width` | no |
| `packages[0].height` | no |
| `packages[0].packagingType` | no |
| `packages[0].declaredValue` | no |
| `packages[0].description` | no |

**Shipment-level fields (6):**

| Field | Required |
|-------|----------|
| `serviceCode` | no (default from intent) |
| `description` | no |
| `reference` | no |
| `reference2` | no |
| `saturdayDelivery` | no |
| `signatureRequired` | no |

**Shipper overrides (normally from Shopify/env, per-row if needed):**

| Field | Required |
|-------|----------|
| `shipper.name` | no |
| `shipper.addressLine1` | no |
| `shipper.city` | no |
| `shipper.stateProvinceCode` | no |
| `shipper.postalCode` | no |
| `shipper.countryCode` | no |
| `shipper.phone` | no |

Fields not mapped or not present are simply omitted — UPS uses its defaults.

---

## Code Disposition

### DELETE (~2500+ lines)

| File | Lines | Reason |
|------|-------|--------|
| `packages/ups-mcp/` | entire dir | TypeScript MCP replaced by Python fork |
| `src/mcp/ups_client.py` | ~450 | Subprocess/JSON-RPC replaced by direct import |
| `src/orchestrator/nl_engine/mapping_generator.py` | ~350 | Jinja2 template generation replaced by column mapping |
| `src/orchestrator/nl_engine/template_validator.py` | ~250 | Template schema validation not needed |
| `src/orchestrator/nl_engine/self_correction.py` | ~250 | LLM template fixing not needed |
| `src/orchestrator/nl_engine/ups_schema.py` | ~400 | UPS JSON Schema definitions not needed |
| `src/orchestrator/batch/executor.py` | ~350 | Consolidated into BatchEngine |
| `src/orchestrator/batch/preview.py` | ~300 | Consolidated into BatchEngine |

### CREATE (~400-500 lines)

| File | Purpose |
|------|---------|
| `src/services/ups_service.py` | Thin wrapper around fork's ToolManager |
| `src/services/batch_engine.py` | Consolidated preview + execution engine |
| `src/services/column_mapping.py` | Column mapping validation and row extraction |

### MODIFY

| File | Change |
|------|--------|
| `src/services/ups_payload_builder.py` | Full field table, accept optional fields, accept ShippingIntent |
| `src/api/routes/preview.py` | Delegate to BatchEngine instead of inline execution |
| `src/orchestrator/agent/config.py` | Remove UPS MCP subprocess config |
| `src/orchestrator/agent/hooks.py` | Update address validation for flat field format |
| `src/orchestrator/agent/tools.py` | Point at BatchEngine |
| `src/orchestrator/models/mapping.py` | Simplify to column mapping model |
| `src/errors/ups_translation.py` | Simplify error extraction (direct Python exceptions) |

---

## Implementation Order

1. Create `UPSService` (direct import wrapper) — test independently
2. Enhance `ups_payload_builder.py` with full field table + ShippingIntent
3. Create `column_mapping.py` (mapping validation + row extraction)
4. Create `BatchEngine` (consolidated preview + execution)
5. Rewire REST API routes to use BatchEngine
6. Rewire orchestrator agent tools to use BatchEngine
7. Delete obsolete files (template system, TS MCP, old executor/preview)
8. Update tests throughout

---

## Environment Requirements

- `UPS_MCP_SPECS_DIR` env var must point to the OpenAPI spec YAML files (bundled at `src/mcp/ups/specs/`). The fork's wheel doesn't include them.
- `UPS_CLIENT_ID`, `UPS_CLIENT_SECRET`, `UPS_ACCOUNT_NUMBER` env vars unchanged.
- Python >= 3.12 (fork requirement, already bumped in pyproject.toml).

---

## Verification

1. `UPSService` unit tests: mock `ToolManager`, verify normalization
2. `BatchEngine` unit tests: mock `UPSService`, verify preview + execution flow
3. Column mapping tests: validation, extraction, missing field handling
4. Payload builder tests: full field coverage, optional field inclusion
5. Integration: REST API -> BatchEngine -> UPSService -> mock ToolManager
6. E2E manual: submit shipping command, verify batch completes with labels
7. Deletion check: `grep -r "packages/ups-mcp" src/ tests/` returns empty
