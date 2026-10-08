# UPS MCP Integration Guide

**Supporting New UPS MCP Tools in ShipAgent**

The UPS MCP server (`ups-mcp`) is an external dependency that provides UPS API operations as MCP tools. ShipAgent consumes these tools through deterministic gateways shared by interactive and batch workflows. New MCP operations are not automatically exposed to a model. This guide identifies the workflow, policy and projection changes required when UPS capabilities expand.

---

## Table of Contents

1. [Two-Path Architecture](#1-two-path-architecture)
2. [Current Tool Inventory](#2-current-tool-inventory)
3. [Integration Layers](#3-integration-layers)
4. [Scenario Playbooks](#4-scenario-playbooks)
5. [Response Normalization Reference](#5-response-normalization-reference)
6. [Error Translation Pipeline](#6-error-translation-pipeline)
7. [Payload Construction Pipeline](#7-payload-construction-pipeline)
8. [Configuration and Environment](#8-configuration-and-environment)
9. [Label Handling Pipeline](#9-label-handling-pipeline)
10. [Shared Policy and Safety Gates](#10-shared-policy-and-safety-gates)
11. [File Reference Matrix](#11-file-reference-matrix)
12. [Hard-Won UPS API Lessons](#12-hard-won-ups-api-lessons)
13. [Testing Checklist](#13-testing-checklist)
14. [Potential UPS MCP Expansions](#14-potential-ups-mcp-expansions)

---

## 1. Two-Path Architecture

Interactive and batch flows use the same ShipAgent-owned safety boundary:

```text
Anthropic / OpenAI / Gemini protocol adapter
    ↕ normalized requests, declarations and projected results
ConversationRuntimeSession
    → WorkflowToolCatalog → RuntimePolicyEngine → LocalToolDispatcher
    → deterministic workflow handler
        → interactive/auxiliary service → UPSMCPClient → UPS MCP
        → BatchEngine                  → UPSMCPClient → UPS MCP

Owner preview → explicit Confirm endpoint → prepared workflow execution
```

The adapter never calls raw `mcp__ups__*` tools. The catalog exposes only registered
workflow tools; policy denies raw carrier calls and model-initiated execution.
The dispatcher keeps imported rows, local contacts, credentials, labels, document
bytes and raw carrier payloads out of model results. Schema metadata and results
use closed projections. Authored chat and specifically allowed current-flow
inputs are distinct from owner-only local data; a handler's origin flag or text
wrapper does not make local data safe for the model.

### Impact on New Tools

| Path | Registration | ShipAgent Changes Required |
|------|--------------|----------------------------|
| **Interactive** | Explicit deterministic workflow definition and catalog metadata | Gateway method/normalizer, handler, policy and model-result projection review, confirmation if mutating, and tests. |
| **Batch** | Explicit deterministic gateway and workflow integration | Same gateway/safety boundary, plus `BatchEngine` integration when needed. |

See the [SDK-free runtime](runtime/sdk-free-runtime.md) and
[auxiliary workflow confirmation](runtime/auxiliary-workflow-parity.md) contracts.

---

## 2. Current Tool Inventory

The following carrier operation names describe the UPS integration surface, not
model-callable permissions. Availability to a conversation is determined by
`get_all_tool_definitions()` and `WorkflowToolCatalog`, with policy and workflow
gates applied at dispatch.

| Carrier operation | `UPSMCPClient` method | Conversation path |
|-------------------|-----------------------|-------------------|
| `rate_shipment` | `get_rate()` | `rate_shipment` workflow |
| `create_shipment` | `create_shipment()` | Interactive or batch priced preview, then trusted job confirmation; no direct model execution |
| `void_shipment` | `void_shipment()` | No provider-neutral void workflow; raw void remains denied (accepted capability gap under issue #37) |
| `validate_address` | `validate_address()` | `validate_address` workflow |
| `track_package` | `track_package()` | `track_package` workflow with owner-facing result card |
| `recover_label` | No named wrapper | Not exposed by the shared workflow catalog |
| `get_time_in_transit` | `get_time_in_transit()` | `get_time_in_transit` workflow |
| `get_landed_cost_quote` | `get_landed_cost()` | `get_landed_cost` workflow |
| `upload_paperless_document` | `upload_document()` | Explicit upload form and one-shot attachment grant |
| `push_document_to_shipment` | `push_document()` | Prepare card, then trusted workflow confirmation |
| `delete_paperless_document` | `delete_document()` | Prepare card, then trusted workflow confirmation |
| `find_locations` | `find_locations()` | `find_locations` workflow |
| `rate_pickup` | `rate_pickup()` | Validated quote and pickup preview |
| `schedule_pickup` | `schedule_pickup()` | Trusted confirmation of pickup preview; model calls are denied |
| `cancel_pickup` | `cancel_pickup()` | Prepare cancellation card, then trusted workflow confirmation |
| `get_pickup_status` | `get_pickup_status()` | `get_pickup_status` workflow |
| `get_political_divisions` | No named wrapper | Not exposed by the shared workflow catalog |
| `get_service_center_facilities` | `get_service_center_facilities()` | `get_service_center_facilities` workflow |

The read-only and auxiliary workflow definitions are available in both session
modes where allowed by the canonical mode filter. Their presence does not grant
mutation authority. In particular, a model `approved`/`confirmed` flag, copied
token or chat message cannot substitute for the trusted confirmation endpoint.

---

## 3. Integration Layers

Each layer has specific responsibilities and specific files:

### Layer 1: MCP Transport

**File:** `src/services/mcp_client.py`

Generic async MCP client providing:
- stdio process spawning and lifecycle
- JSON response parsing
- Configurable retry with exponential backoff
- Connection state tracking (`is_connected` property)
- `call_tool(name, args)` method

**When to modify:** Only for infrastructure changes (protocol updates, transport changes). Never for new UPS tools.

### Layer 2: UPS-Specific Client

**File:** `src/services/ups_mcp_client.py`

UPS-specific wrapper providing:
- Named methods for each UPS operation (`get_rate()`, `create_shipment()`, etc.)
- Response normalization (raw UPS JSON → standardized dict)
- Retry policy per tool (read-only tools retry, mutating tools don't)
- Error translation (UPS error codes → ShipAgent E-codes)
- Transport reconnection on connection failure

**When to modify:** Every time a new UPS MCP operation needs programmatic access, including interactive workflow handlers.

### Layer 3: Payload Construction

**File:** `src/services/ups_payload_builder.py`

Builds UPS API request bodies from mapped order data:
- `build_shipment_request()` — simplified format from order data
- `build_ups_api_payload()` — full UPS ShipmentRequest for `create_shipment`
- `build_ups_rate_payload()` — full UPS RateRequest for `rate_shipment`

**When to modify:** When a new tool requires a new payload format, or when the UPS API adds new fields.

### Layer 4: Column Mapping

**File:** `src/services/column_mapping.py`

Maps source data columns (CSV, Excel, Shopify) to UPS payload fields:
- `_FIELD_TO_ORDER_DATA` dict — canonical field name → order_data key
- `_AUTO_MAP_RULES` list — keyword-based auto-detection rules
- `apply_mapping()` — transforms source rows to order_data dicts

**When to modify:** When a new UPS tool requires fields not currently mapped (e.g., customs data, cost center, delivery instructions).

### Layer 5: Batch Engine

**File:** `src/services/batch_engine.py`

Orchestrates concurrent per-row UPS operations:
- `preview()` — rates rows via `UPSMCPClient.get_rate()` with concurrency semaphore
- `execute()` — ships rows via `UPSMCPClient.create_shipment()` with label persistence
- Progress callbacks for SSE streaming
- Write-back tracking numbers to source

**When to modify:** When a new tool should be part of the batch workflow (e.g., batch address validation before shipping, batch customs declarations).

### Layer 6: Agent Tools

**Files:** `src/orchestrator/agent/tools/core.py`, `pipeline.py`, `interactive.py`, `__init__.py`

Deterministic tool handlers invoked by the agent:
- `ship_command_pipeline_tool` — fast path (fetch → create job → preview)
- `BatchEngine.preview()` — rate job rows inside the prepared workflow
- `batch_execute_tool` — deterministic batch execution behind trusted job confirmation; model calls are denied even with `approved=True`
- `preview_interactive_shipment_tool` — single shipment preview
- `_get_ups_client()` — lazy singleton for UPSMCPClient

**When to modify:** When a new UPS operation should be available through a conversation workflow. Also update catalog metadata and review shared policy/projection; registration alone is insufficient.

### Layer 7: System Prompt

**File:** `src/orchestrator/agent/system_prompt.py`

Documents UPS capabilities for the agent:
- Service code reference table
- Workflow instructions (when to use which tool)
- Safety rules (preview before execute, confirmation gates)

**When to modify:** When the agent needs guidance on how/when to use new UPS capabilities.

### Layer 8: Error Handling

**Files:** `src/errors/ups_translation.py`, `src/errors/registry.py`, `src/services/errors.py`

Maps UPS errors to user-friendly ShipAgent errors:
- `UPS_ERROR_MAP` — UPS code → E-code mapping
- Pattern matching — UPS message substrings → E-codes
- `ErrorCode` registry — E-code → title, template, remediation
- `UPSServiceError` — exception class carrying E-code + raw details

**When to modify:** When a new tool returns error codes not yet mapped.

### Layer 9: Agent Configuration

**File:** `src/orchestrator/agent/config.py`

Spawns the UPS MCP server as a stdio child process:
- Environment variables passed to the subprocess
- Python command resolution (venv-aware)
- Spec directory management

**When to modify:** When new environment variables are required by the UPS MCP server.

### Layer 10: Shared Policy and Projection

**Files:** `src/services/conversation_runtime/tool_catalog.py`, `policy.py`,
`dispatcher.py`; `src/services/workflow_confirmation.py`

- Catalog metadata classifies mode, side effects, retry class and artifact events.
- Policy denies raw UPS calls and model-supplied purchase authority before effects.
- The dispatcher applies policy and catalog availability checks, records redacted
  decisions and projects results; deterministic handlers validate their inputs.
- Workflow services bind explicit user confirmation to a prepared payload and
  gateway; upload grants bind the user-selected attachment bytes and metadata.

**When to modify:** Every new workflow needs metadata and a safety/privacy review.
Mutating workflows must enforce explicit authority in deterministic code, not
just a prompt instruction or a catalog flag. See [Section 10](#10-shared-policy-and-safety-gates).

---

## 4. Scenario Playbooks

### Scenario A: New Read-Only Interactive Tool

**Example:** A future UPS operation retrieves shipping documents.

1. Add a named `UPSMCPClient` method, normalize the result, and explicitly classify
   its retry behavior. Do not assume an unknown operation is read-only.
2. Add a deterministic handler and definition in `src/orchestrator/agent/tools/`.
3. Add mode/side-effect metadata to `WorkflowToolCatalog`; review shared policy
   and implement a closed model-result projection in `LocalToolDispatcher`.
4. Keep document bytes, URLs and raw carrier responses in owner-local services
   and artifacts. Use an opaque handle if the model needs a continuation token.
5. Add gateway, handler, catalog, policy and serialized-provider privacy tests;
   update system-prompt guidance only after the boundary is covered.

MCP discovery alone never exposes the operation to the model. Do not call
`mcp__ups__get_shipping_documents` from a provider adapter.

---

### Scenario B: New Tool Needed in Batch Path

**Example:** UPS MCP adds `validate_address_v2` with enhanced validation, and ShipAgent wants to use it for pre-flight address checking before batch shipping.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/services/ups_mcp_client.py` | Add `validate_address_v2()` method | Yes |
| 2 | `src/services/ups_mcp_client.py` | Add `_normalize_address_v2_response()` | Yes |
| 3 | `src/services/ups_mcp_client.py` | Review read-only classification and bounded retry policy | Yes |
| 4 | `src/services/batch_engine.py` | Add pre-flight validation step in `preview()` | Yes |
| 5 | `src/errors/ups_translation.py` | Map any new error codes | If applicable |
| 6 | `src/orchestrator/agent/tools/pipeline.py` | Expose as agent tool if needed | Optional |
| 7 | `src/orchestrator/agent/tools/__init__.py` | Register tool definition | If exposing |
| 8 | `src/orchestrator/agent/system_prompt.py` | Document usage | If exposing |
| 9 | `tests/services/test_ups_mcp_client.py` | Test response normalization | Yes |
| 10 | `tests/services/test_batch_engine.py` | Test pre-flight integration | Yes |

**Implementation sketch in UPSMCPClient:** Classify `validate_address_v2` in
`_READ_ONLY_TOOLS` only after verifying it is read-only. `_call()` owns retry
options; callers do not pass `max_retries` or `base_delay`.

```python
async def validate_address_v2(self, address: dict[str, Any]) -> dict[str, Any]:
    """Validate address with enhanced response."""
    try:
        raw = await self._call(
            "validate_address_v2",
            address,
        )
    except MCPToolError as e:
        raise self._translate_error(e) from e
    return self._normalize_address_v2_response(raw)

def _normalize_address_v2_response(self, raw: dict) -> dict[str, Any]:
    """Extract validation result from v2 response format."""
    # Parse the new response structure
    # Return standardized dict
    pass
```

**Integration in BatchEngine:**

```python
async def preview(self, job_id, rows, shipper, service_code=None):
    # New: Pre-flight address validation
    for row in rows:
        address = self._extract_address(row)
        validation = await self._ups.validate_address_v2(address)
        if validation["status"] == "invalid":
            row["_address_warning"] = validation["message"]

    # Existing: Rate each row
    # ...
```

---

### Scenario C: Existing Tool Changes Response Format

**Example:** UPS MCP updates `rate_shipment` to return rates in a new structure.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/services/ups_mcp_client.py` | Update `_normalize_rate_response()` | Yes |
| 2 | `tests/services/test_ups_mcp_client.py` | Update response parsing tests | Yes |

**Current normalization** (the fields ShipAgent extracts):

```python
# Rate response fields consumed:
raw["RateResponse"]["RatedShipment"][0]["NegotiatedRateCharges"]["TotalCharge"]["MonetaryValue"]
raw["RateResponse"]["RatedShipment"][0]["NegotiatedRateCharges"]["TotalCharge"]["CurrencyCode"]
raw["RateResponse"]["RatedShipment"][0]["TotalCharges"]["MonetaryValue"]  # Fallback
```

If these paths change, update `_normalize_rate_response()` accordingly. The rest of the pipeline (BatchEngine, agent tools) consumes the normalized output — no other files need changes.

---

### Scenario D: New Tool Requiring New Payload Format

**Example:** UPS MCP adds `create_return_shipment` with a ReturnRequest body.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/services/ups_payload_builder.py` | Add `build_return_request()` function | Yes |
| 2 | `src/services/ups_mcp_client.py` | Add `create_return_shipment()` method | Yes |
| 3 | `src/services/ups_mcp_client.py` | Add `_normalize_return_response()` | Yes |
| 4 | `src/services/ups_mcp_client.py` | Add to retry policy (mutating = 0 retries) | Yes |
| 5 | `src/services/batch_engine.py` | Add return shipment mode (if batch returns) | If batch |
| 6 | `src/services/column_mapping.py` | Add return-specific field mappings | If new fields |
| 7 | `src/orchestrator/agent/tools/pipeline.py` | Add `create_return_tool` handler | Yes |
| 8 | `src/orchestrator/agent/tools/__init__.py` | Register tool definition | Yes |
| 9 | `src/orchestrator/agent/system_prompt.py` | Document return workflow | Yes |
| 10 | `src/services/conversation_runtime/tool_catalog.py`, `policy.py`, `dispatcher.py` and the workflow confirmation service | Classify effects, project safe results, and enforce prepared-payload confirmation before mutation | Yes |
| 11 | `src/errors/ups_translation.py` | Map return-specific error codes | If applicable |
| 12 | `tests/services/test_ups_payload_builder.py` | Test return payload construction | Yes |
| 13 | `tests/services/test_ups_mcp_client.py` | Test return response normalization | Yes |

---

### Scenario E: New Environment Variables Required

**Example:** UPS MCP now requires `UPS_SHIPPER_NUMBER` as a separate env var.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/orchestrator/agent/config.py` | Add env var to `get_ups_mcp_config()` | Yes |
| 2 | `.env.example` | Document new variable | Yes |
| 3 | `scripts/start-backend.sh` | Include in startup if needed | If applicable |

**In config.py:**

```python
def get_ups_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        command=_get_python_command(),
        args=["-m", "ups_mcp"],
        env={
            "CLIENT_ID": os.environ.get("UPS_CLIENT_ID", ""),
            "CLIENT_SECRET": os.environ.get("UPS_CLIENT_SECRET", ""),
            "ENVIRONMENT": _environment,
            "UPS_SHIPPER_NUMBER": os.environ.get("UPS_SHIPPER_NUMBER", ""),  # ← New
            "UPS_MCP_SPECS_DIR": str(specs_dir),
            "PATH": os.environ.get("PATH", ""),
        },
    )
```

---

### Scenario F: New Tool for Agent-Only Interactive Use

Interactive-only operations still require a named gateway method and registered
workflow with shared catalog metadata, policy, safe result projection and tests.
Use [Scenario A](#scenario-a-new-read-only-interactive-tool) for a read-only
operation; require preview and explicit confirmation for mutations.

For landed cost, reuse the existing `get_landed_cost` workflow and
`UPSMCPClient.get_landed_cost()` rather than adding a raw carrier call. Prompt
wording never replaces the deterministic wrapper or privacy boundary.

---

### Scenario G: Wrapping an Existing Interactive Tool for Batch Use

**Example:** A future batch tracking workflow can reuse the existing `track_package` handler and gateway method. Both already exist; do not re-add them. The following checklist applies when adapting another existing workflow to batch use.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/services/ups_mcp_client.py` | Reuse `track_package()`; add a wrapper only for an operation not already supported | As needed |
| 2 | `src/services/ups_mcp_client.py` | Review existing normalized output; add normalization only for a new response shape | As needed |
| 3 | `src/services/ups_mcp_client.py` | Review read-only classification and bounded retry policy | Yes |
| 4 | `src/orchestrator/agent/tools/pipeline.py` | Add `batch_track_tool` handler | Yes |
| 5 | `src/orchestrator/agent/tools/__init__.py` | Register `batch_track` definition | Yes |
| 6 | `src/orchestrator/agent/system_prompt.py` | Document batch tracking workflow | Yes |
| 7 | `tests/services/test_ups_mcp_client.py` | Test tracking response normalization | Yes |

---

## 5. Response Normalization Reference

Every UPS response goes through a normalizer in `UPSMCPClient` before reaching business logic. These are the current normalizers and the response fields they extract.

### Rate Response

**Normalizer:** `_normalize_rate_response()`

```
Input (raw UPS JSON):
  RateResponse
    └─ RatedShipment[0]
        ├─ NegotiatedRateCharges (preferred)
        │   └─ TotalCharge
        │       ├─ MonetaryValue: "12.50"
        │       └─ CurrencyCode: "USD"
        └─ TotalCharges (fallback)
            ├─ MonetaryValue: "15.00"
            └─ CurrencyCode: "USD"

Output (normalized):
  {
    "success": True,
    "totalCharges": {
      "monetaryValue": "12.50",
      "amount": "12.50",
      "currencyCode": "USD"
    }
  }
```

**Consumers:** `BatchEngine.preview()` → extracts `monetaryValue`, converts to cents.

### Shipment Response

**Normalizer:** `_normalize_shipment_response()`

```
Input (raw UPS JSON):
  ShipmentResponse
    └─ ShipmentResults
        ├─ ShipmentIdentificationNumber: "1Z..."
        ├─ PackageResults[]
        │   ├─ TrackingNumber: "1Z..."
        │   └─ ShippingLabel
        │       └─ GraphicImage: "base64..."  (PDF)
        └─ NegotiatedRateCharges (preferred)
            └─ TotalCharge
                ├─ MonetaryValue: "12.50"
                └─ CurrencyCode: "USD"

Output (normalized):
  {
    "success": True,
    "trackingNumbers": ["1Z..."],
    "labelData": ["base64..."],
    "shipmentIdentificationNumber": "1Z...",
    "totalCharges": {
      "monetaryValue": "12.50",
      "amount": "12.50",
      "currencyCode": "USD"
    }
  }
```

**Consumers:** `BatchEngine.execute()` → extracts tracking number, label data (base64 → PDF file), cost in cents.

### Address Validation Response

**Normalizer:** `_normalize_address_response()`

```
Input (raw UPS JSON):
  XAVResponse
    ├─ ValidAddressIndicator (present = valid)
    ├─ AmbiguousAddressIndicator (present = ambiguous)
    ├─ NoCandidatesIndicator (present = invalid)
    └─ Candidate[]
        └─ AddressKeyFormat
            ├─ AddressLine: ["123 Main St"]
            ├─ PoliticalDivision2: "Austin"  (city)
            ├─ PoliticalDivision1: "TX"      (state)
            └─ PostcodePrimaryLow: "78701"   (ZIP)

Output (normalized):
  {
    "success": True,
    "status": "valid" | "ambiguous" | "invalid" | "unknown",
    "candidates": [
      {
        "addressLines": ["123 Main St"],
        "city": "Austin",
        "stateProvinceCode": "TX",
        "postalCode": "78701"
      }
    ]
  }
```

### Void Response

**Normalizer:** `_normalize_void_response()`

```
Output (normalized):
  {
    "success": True,
    "status": "voided"
  }
```

### Adding a New Normalizer

When a new UPS MCP tool is wrapped, add a normalizer following this pattern:

```python
def _normalize_{tool}_response(self, raw: dict) -> dict[str, Any]:
    """Extract structured data from raw UPS {tool} response.

    Args:
        raw: Raw JSON response from UPS MCP tool.

    Returns:
        Normalized dict with 'success' key and tool-specific data.
    """
    # 1. Navigate to the data payload
    payload = raw.get("ResponseKey", {}).get("DataKey", {})

    # 2. Extract fields with safe defaults
    value = payload.get("Field", "")

    # 3. Return standardized structure
    return {
        "success": True,
        "field": value,
    }
```

---

## 6. Error Translation Pipeline

When a UPS MCP tool call fails, the error flows through this pipeline:

```
UPS MCP Server returns error
    ↓
MCPClient raises MCPToolError (raw error string)
    ↓
UPSMCPClient._translate_error()
    ├─ Parse JSON from error string
    ├─ Extract UPS code + message
    ├─ Check for MCP preflight codes (ELICITATION_UNSUPPORTED, etc.)
    ├─ Extract missing fields list (for E-2010)
    ├─ Call translate_ups_error(code, message)
    └─ Return UPSServiceError with E-code
    ↓
Business logic catches UPSServiceError
    ├─ BatchEngine: marks row as failed, logs audit entry
    ├─ Agent tool: returns _err() with E-code and remediation
    └─ API route: returns HTTP error response
```

### Error Code Categories

| Range | Category | Examples |
|-------|----------|---------|
| E-2xxx | Validation | E-2001 Invalid ZIP, E-2004 Invalid weight, E-2010 Missing fields |
| E-3xxx | UPS API | E-3001 System unavailable, E-3002 Rate limit, E-3003 Address invalid, E-3004 Service unavailable |
| E-4xxx | System | E-4010 Elicitation integration error |
| E-5xxx | Auth | E-5001 Auth failed, E-5002 Token expired |

### Retry Policy by Tool

| Classification | Max Retries | Base Delay | Tools |
|---------------|:-----------:|:----------:|-------|
| Read-only | 2 | 0.2s | `rate_shipment`, `validate_address`, `track_package` |
| Mutating | 0 | 1.0s | `create_shipment`, `void_shipment` |

**No mutation exception:** `create_shipment`, `void_shipment`, pickup mutations
and document mutations make one carrier attempt. A 503 with "no healthy upstream"
or a transport failure cannot establish non-acceptance. Reconnection must not
replay a mutation. Report an uncertain outcome and check carrier status before
requesting a new operation.

### Retryable Error Patterns

```python
patterns = ["rate limit", "429", "503", "502", "timeout", "connection", "190001", "190002"]
```

### Adding Error Mappings for New Tools

**File:** `src/errors/ups_translation.py`

```python
# Add UPS error codes to UPS_ERROR_MAP
UPS_ERROR_MAP = {
    # Existing...
    "NEW_CODE_1": "E-3005",  # New tool-specific error
    "NEW_CODE_2": "E-2013",  # New validation error
}
```

**File:** `src/errors/registry.py`

```python
# Register new E-codes
ERROR_REGISTRY["E-3005"] = ErrorCode(
    code="E-3005",
    category=ErrorCategory.UPS_API,
    title="New Tool Error",
    message_template="New tool failed: {ups_message}",
    remediation="Specific guidance for the user.",
    is_retryable=False,
)
```

---

## 7. Payload Construction Pipeline

Order data flows through this pipeline before reaching UPS:

```
Source Data (CSV/Shopify/etc.)
    ↓ column_mapping.py: apply_mapping()
Order Data Dict (canonical field names)
    ↓ ups_payload_builder.py: build_shipment_request()
Simplified Shipment Dict
    ↓ ups_payload_builder.py: build_ups_rate_payload() or build_ups_api_payload()
UPS API Request Body (rate or ship)
    ↓ ups_mcp_client.py: get_rate() or create_shipment()
UPS MCP Tool Call
```

### Column Mapping → Order Data

**File:** `src/services/column_mapping.py`

Auto-maps source columns to canonical names using keyword rules:

```python
# Example auto-map rules (keyword lists → canonical field)
(["recipient", "name"],         [], "recipientName")
(["address", "line", "1"],      [], "addressLine1")
(["city"],                      [], "city")
(["state"],                     [], "state")
(["zip", "postal"],             [], "postalCode")
(["weight"],                    [], "weight")
(["phone"],                     [], "phone")
(["service"],                   [], "serviceCode")
```

### Order Data → Simplified Request

**File:** `src/services/ups_payload_builder.py` — `build_shipment_request()`

Extracts shipping-relevant fields from order data into a simplified dict:

```python
{
    "recipientName": "John Smith",
    "recipientCompany": "Acme Corp",
    "addressLine1": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "postalCode": "78701",
    "country": "US",
    "phone": "5125551234",
    "weight": 2.5,
    "length": 12, "width": 8, "height": 6,
    "serviceCode": "03",
    "packagingCode": "02",
    "declaredValue": 45.99,
    "referenceNumbers": ["ORD-1001"],
}
```

### Simplified → UPS Rate Payload

**File:** `src/services/ups_payload_builder.py` — `build_ups_rate_payload()`

Key structure differences for rating vs shipping:
- Package type key is `PackagingType` (not `Packaging`)
- No `LabelSpecification`
- No `PaymentInformation`
- `RequestOption` is `"Rate"` (not `"nonvalidate"`)

### Simplified → UPS Ship Payload

**File:** `src/services/ups_payload_builder.py` — `build_ups_api_payload()`

Includes everything from rate plus:
- `Packaging` key (not `PackagingType`)
- `LabelSpecification` (PDF, 4x6)
- `PaymentInformation.ShipmentCharge` (array, not object)
- `ReferenceNumber` at package level (not shipment level)
- `RequestOption` is `"nonvalidate"`

### Adding Fields for New Tools

If a new UPS tool requires fields not currently in the pipeline:

1. **Column mapping** — Add auto-map rule in `column_mapping.py`:
   ```python
   (["customs", "value"], [], "customsValue")
   ```

2. **Simplified request** — Extract in `build_shipment_request()`:
   ```python
   result["customsValue"] = order_data.get("customs_value")
   ```

3. **UPS payload** — Include in `build_ups_api_payload()`:
   ```python
   if simplified.get("customsValue"):
       shipment["InternationalForms"] = {"FormType": ["01"], ...}
   ```

---

## 8. Configuration and Environment

### Environment Variables

**Required for UPS operations:**

| Variable | Purpose | Passed to MCP As |
|----------|---------|-----------------|
| `UPS_CLIENT_ID` | OAuth client ID | `CLIENT_ID` |
| `UPS_CLIENT_SECRET` | OAuth client secret | `CLIENT_SECRET` |

**Optional:**

| Variable | Purpose | Default |
|----------|---------|---------|
| `UPS_ACCOUNT_NUMBER` | Shipper account for billing | `""` (empty) |
| `UPS_BASE_URL` | UPS API base URL | `https://wwwcie.ups.com` (test) |
| `UPS_LABELS_OUTPUT_DIR` | Label file output directory | `PROJECT_ROOT/labels/` |
| `BATCH_CONCURRENCY` | Max concurrent UPS API calls | `5` |
| `BATCH_PREVIEW_MAX_ROWS` | Max rows to rate in preview | `50` |

### MCP Server Spawn

**File:** `src/orchestrator/agent/config.py`

The UPS MCP server is spawned as a stdio child process:

```python
MCPServerConfig(
    command=python_path,          # .venv/bin/python3
    args=["-m", "ups_mcp"],       # Run as Python module
    env={
        "CLIENT_ID": "...",
        "CLIENT_SECRET": "...",
        "ENVIRONMENT": "test" | "production",
        "UPS_MCP_SPECS_DIR": "/path/to/specs",
        "PATH": os.environ["PATH"],
    },
)
```

### UPS Spec Files

**File:** `src/services/ups_specs.py`

Resolves all seven OpenAPI files directly from the pinned `ups_mcp/specs`
package resources: Rating, Shipping, TimeInTransit, LandedCost, Paperless, Locator
and Pickup. `ensure_ups_specs_dir()` checks completeness and returns that
read-only directory. It never writes into the application installation or
creates placeholder operations. The PyInstaller spec collects these same files.

The repository `docs/*.yaml` remain reference material. Package routing and
parameter contracts preserve their existing interpreted operations; the real
TimeInTransit resource is required. A future UPS fork update must update the
pinned dependency and pass resource/registry/packaging tests together.

---

## 9. Label Handling Pipeline

```
UPS create_shipment response
    ↓ ShippingLabel.GraphicImage (base64-encoded PDF)
BatchEngine._save_label()
    ↓ Decode base64 → write PDF to disk
File: PROJECT_ROOT/labels/{hash}.pdf
    ↓ Path stored in JobRow.label_path
API routes serve the file
    ↓ /labels/{tracking} or /jobs/{id}/labels/{row}
Frontend displays in LabelPreview modal (react-pdf)
```

### Label Endpoints

| Route | Purpose |
|-------|---------|
| `GET /api/v1/labels/{tracking_number}` | Download single label by tracking number |
| `GET /api/v1/jobs/{id}/labels/merged` | Merged PDF of all job labels (via `pypdf`) |
| `GET /api/v1/jobs/{id}/labels/zip` | ZIP archive of all job labels |
| `GET /api/v1/jobs/{id}/labels/{row_number}` | Download label by row number |

### Files Involved

| File | Role |
|------|------|
| `src/services/batch_engine.py` | Decodes base64, writes PDF to disk |
| `src/db/models.py` | `JobRow.label_path` column stores file path |
| `src/api/routes/labels.py` | Serves label files via HTTP |
| `frontend/src/components/LabelPreview.tsx` | In-browser PDF rendering |

### If New Tools Generate Documents

If a new UPS MCP tool returns documents (customs forms, commercial invoices, etc.):

1. Add a column to `JobRow` for the document path (e.g., `customs_form_path`)
2. Decode and save in `BatchEngine` alongside labels
3. Add API route for document download in `routes/labels.py`
4. Add frontend viewer if format differs from PDF

---

## 10. Shared Policy and Safety Gates

The removed SDK hook/client modules are not extension points. The current
boundary is implemented by:

| File | Responsibility |
|------|----------------|
| `src/services/conversation_runtime/tool_catalog.py` | Canonical handler declarations plus mode, side-effect, retry, confirmation and artifact metadata |
| `src/services/conversation_runtime/policy.py` | `RuntimePolicyEngine` denies raw carrier calls, raw SQL and model-initiated purchase execution |
| `src/services/conversation_runtime/dispatcher.py` | `LocalToolDispatcher` checks policy and catalog availability, invokes a registered input-validating handler, audits and projects provider-safe results |
| `src/services/conversation_privacy.py` | Authored text/history boundary; owner-only artifacts never become model history |
| `src/services/workflow_confirmation.py` | One-shot prepared auxiliary actions bound to immutable payloads and the original gateway |
| `src/services/conversation_handler.py` | Session/generation ownership, pending actions and upload authority |

### Adding a Workflow Safely

1. Use closed input schemas and explicit deterministic validation. Add the handler
   to the canonical definitions, then classify it in `WorkflowToolCatalog`.
2. Review pre-tool policy. An allowed `PolicyDecision` is permission to reach the
   handler, not proof of user confirmation. New carrier operations must never
   bypass the raw-call denial.
3. For a mutation, prepare an owner-visible preview and bind explicit confirmation
   to the exact payload and gateway. Consume authority before dispatch; never
   recreate it from model flags, copied tokens, persisted prose or provider changes.
4. Uploads must consume the user-selected one-shot attachment grant; model-provided
   bytes, filenames or substitutions do not create upload authority.
5. Keep rows, local contacts, credentials, labels, documents and raw carrier data
   out of provider payloads. Add a closed result projection and safe fixed error
   text; do not return raw exception strings to the model. Authored chat/current-flow
   inputs are handled by origin-aware rules, not blanket permission to echo local data.
6. Use the generation-bound event bridge for owner artifacts. Verify stale or
   interrupted turns cannot emit into a newer conversation turn.
7. Test all supported provider protocols, denial-before-effect, consumed/expired
   confirmations, uncertain outcomes and owner/model privacy separation.

For concrete contracts, see [auxiliary workflow confirmation](runtime/auxiliary-workflow-parity.md)
and [conversation lifecycle](conversation-lifecycle.md). Raw shipment void remains
an explicit capability gap; adding a gateway method or prompt does not close it.

---

## 11. File Reference Matrix

Complete matrix of all files involved in UPS integration, organized by when they need updating:

### Always Update (Any New Batch Tool)

| File | Specific Change |
|------|----------------|
| `src/services/ups_mcp_client.py` | Add method + normalizer + retry policy |
| `tests/services/test_ups_mcp_client.py` | Test response normalization |

### Update If New Payload Format

| File | Specific Change |
|------|----------------|
| `src/services/ups_payload_builder.py` | Add `build_{tool}_payload()` function |
| `tests/services/test_ups_payload_builder.py` | Test payload construction |

### Update If New Mappable Fields

| File | Specific Change |
|------|----------------|
| `src/services/column_mapping.py` | Add auto-map rules + field-to-order-data entry |

### Update If Part of Batch Workflow

| File | Specific Change |
|------|----------------|
| `src/services/batch_engine.py` | Integrate into `preview()` or `execute()` flow |
| `tests/services/test_batch_engine.py` | Test batch integration |

### Update If Agent-Facing

| File | Specific Change |
|------|----------------|
| `src/orchestrator/agent/tools/{module}.py` | Add tool handler |
| `src/orchestrator/agent/tools/__init__.py` | Register tool definition |
| `src/orchestrator/agent/system_prompt.py` | Add usage guidance |
| `src/services/conversation_runtime/tool_catalog.py` | Classify mode, effects, retry and artifacts |
| `src/services/conversation_runtime/dispatcher.py` | Review/add closed model-result projection |

### Update If New Error Codes

| File | Specific Change |
|------|----------------|
| `src/errors/ups_translation.py` | Add to `UPS_ERROR_MAP` |
| `src/errors/registry.py` | Register new E-codes with templates |

### Update If New Env Vars

| File | Specific Change |
|------|----------------|
| `src/orchestrator/agent/config.py` | Pass to MCP subprocess env |
| `.env.example` | Document variable |

### Review Safety for Every Workflow

| File | Specific Change |
|------|----------------|
| `src/services/conversation_runtime/policy.py` | Deny unsafe/model-initiated execution before effects |
| `src/services/workflow_confirmation.py` | Enforce exact prepared action and explicit one-shot authority for auxiliary mutations |

### Rarely Update

| File | When |
|------|------|
| `src/services/mcp_client.py` | Only for MCP protocol changes |
| `src/services/gateway_provider.py` | Only if new singleton MCP client needed |
| `src/orchestrator/agent/config.py` | Add gateway-owned MCP configuration for a new server, not provider-owned dispatch |
| `src/services/ups_specs.py` | Only if new OpenAPI spec files needed |

---

## 12. Hard-Won UPS API Lessons

These are critical implementation details discovered through debugging. They apply to any new tool that builds UPS payloads:

| Lesson | Detail | File Reference |
|--------|--------|---------------|
| **Packaging key** | Use `Packaging` for shipping, `PackagingType` for rating. They are NOT interchangeable. | `ups_payload_builder.py` |
| **ShipmentCharge is an array** | `[{"Type": "01", "BillShipper": {...}}]` — not a single object. UPS silently fails otherwise. | `ups_payload_builder.py` |
| **ReferenceNumber placement** | Package-level only. Shipment-level is rejected for UPS Ground domestic. Max 35 chars per value. | `ups_payload_builder.py` |
| **Negotiated rates** | Always include `NegotiatedRatesIndicator: ""` and prefer `NegotiatedRateCharges` in responses. | `ups_payload_builder.py`, `ups_mcp_client.py` |
| **Units are hardcoded** | Weight: LBS. Dimensions: IN. No metric support currently. Shopify weight in grams requires conversion (÷ 453.592). | `ups_payload_builder.py` |
| **Account number required** | Empty account number causes silent billing failures. Validated in `build_ups_api_payload()`. | `ups_payload_builder.py` |
| **Mutating tools: no retry** | All mutations make one attempt, including on 503 "no healthy upstream". Check status after an uncertain result; no automatic replay. | `ups_mcp_client.py` |
| **MCP preflight errors** | Error codes like `ELICITATION_UNSUPPORTED` come from the MCP layer, not UPS itself. Map separately. | `ups_translation.py` |

---

## 13. Testing Checklist

When adding support for a new UPS MCP tool, verify all items:

### UPSMCPClient (`tests/services/test_ups_mcp_client.py`)

- [ ] New method calls correct MCP tool name
- [ ] Response normalizer handles success case
- [ ] Response normalizer handles empty/malformed response
- [ ] Retry policy is correct (read-only = 2, mutating = 0)
- [ ] Error translation produces correct E-code
- [ ] Transport reconnect behaves correctly (replay for read-only, block for mutating)

### Payload Builder (`tests/services/test_ups_payload_builder.py`)

- [ ] New payload function produces valid UPS API structure
- [ ] Required fields are validated (ValueError on missing)
- [ ] Optional fields are omitted when None
- [ ] Packaging key is correct for the tool (`Packaging` vs `PackagingType`)
- [ ] ShipmentCharge is an array (if applicable)
- [ ] ReferenceNumber is at package level (if applicable)

### Batch Engine (`tests/services/test_batch_engine.py`)

- [ ] New tool integrates into preview or execute flow
- [ ] Per-row errors are caught and logged (not propagated)
- [ ] Progress callback fires correctly
- [ ] Concurrency semaphore limits parallel calls
- [ ] Malformed row data produces warning, not crash

### Agent Tools (`tests/orchestrator/agent/tools/`)

- [ ] Tool definition registered in `get_all_tool_definitions()` output
- [ ] Handler returns `_ok()` on success
- [ ] Handler returns `_err()` on missing required params
- [ ] Handler returns `_err()` on UPS service failure
- [ ] Bridge events emitted if applicable
- [ ] Mode-aware filtering correct (batch vs interactive)

### Error Handling

- [ ] New UPS error codes added to `UPS_ERROR_MAP`
- [ ] New E-codes registered with title, template, remediation
- [ ] Pattern matching updated for new error messages (if applicable)

### Integration

- [ ] End-to-end test with real UPS test environment (manual)
- [ ] System prompt updated if tool is user-facing
- [ ] Catalog mode/side-effect metadata, policy and model-result projection covered
- [ ] Mutations require trusted explicit confirmation or the bound upload grant
- [ ] Raw carrier calls denied and uncertain mutations never replayed
- [ ] Imported/local data remains absent from all serialized provider payloads

---

## 14. Potential UPS MCP Expansions

These are illustrative expansion ideas, not a current availability matrix; some
capabilities already have wrappers listed in Section 2. Reuse existing workflows
where available. Every model-facing extension requires the shared safety boundary,
regardless of the per-layer changes listed below. No MCP operation is auto-exposed.

### High Priority

| Tool | Description | Interactive | Batch Client | Payload Builder | Batch Engine | Agent Tool | System Prompt |
|------|-------------|:-----------:|:------------:|:---------------:|:------------:|:----------:|:-------------:|
| `create_return_shipment` | Generate return labels | Workflow | New method | New function | New mode | New handler | New workflow |
| `rate_shipment_multi` | Rate multiple services at once | Workflow | New method | New function | Replace per-service loop | Update existing | Update guidance |
| `create_pickup` | Schedule carrier pickup | Workflow | New method | New function | — | New handler | New section |
| `get_proof_of_delivery` | Retrieve POD documents | Workflow | Optional | — | — | Optional | Optional |

### Medium Priority

| Tool | Description | Interactive | Batch Client | Payload Builder | Batch Engine | Agent Tool | System Prompt |
|------|-------------|:-----------:|:------------:|:---------------:|:------------:|:----------:|:-------------:|
| `create_international_shipment` | Ship with customs forms | Workflow | New method | New function (customs) | New mode | New handler | New workflow |
| `estimate_duties_taxes` | Landed cost calculator | Workflow | Optional | New function | Pre-flight step | Optional | New section |
| `validate_address_international` | Non-US address validation | Workflow | New method | — | Pre-flight step | Optional | Update rules |
| `get_shipping_documents` | Retrieve customs docs | Workflow | Optional | — | Post-execute step | Optional | Optional |

### Lower Priority

| Tool | Description | Interactive | Batch Client | Payload Builder | Batch Engine | Agent Tool | System Prompt |
|------|-------------|:-----------:|:------------:|:---------------:|:------------:|:----------:|:-------------:|
| `create_freight_shipment` | LTL/freight shipping | Workflow | New method | New function | New mode | New handler | New section |
| `manage_subscription` | Tracking notifications | Workflow | — | — | — | — | Optional |
| `get_accessorials` | List available surcharges | Workflow | — | — | — | Optional | Optional |
| `calculate_density` | Freight density calc | Workflow | — | — | — | — | — |

### Legend

| Cell Value | Meaning |
|-----------|---------|
| Workflow | Explicit handler/catalog registration, gateway, policy/projection review and tests; confirmation required for mutations |
| New method | Add method to `UPSMCPClient` |
| New function | Add function to `ups_payload_builder.py` |
| New mode | Add execution path to `BatchEngine` |
| New handler | Add tool handler to agent tools |
| New workflow | Add workflow section to system prompt |
| New section | Add documentation section to system prompt |
| Update existing | Modify existing code |
| Optional | Nice-to-have, not required |
| — | Not applicable |
