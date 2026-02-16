# UPS MCP Integration Guide

**Supporting New UPS MCP Tools in ShipAgent**

The UPS MCP server (`ups-mcp`) is an external dependency that provides UPS API operations as MCP tools. ShipAgent consumes these tools through two distinct paths. This document details every file that must be updated when the UPS MCP server adds new tools, changes response formats, or expands its API coverage.

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
10. [Agent Hooks and Safety Gates](#10-agent-hooks-and-safety-gates)
11. [File Reference Matrix](#11-file-reference-matrix)
12. [Hard-Won UPS API Lessons](#12-hard-won-ups-api-lessons)
13. [Testing Checklist](#13-testing-checklist)
14. [Potential UPS MCP Expansions](#14-potential-ups-mcp-expansions)

---

## 1. Two-Path Architecture

ShipAgent consumes UPS MCP tools through two independent paths:

```
┌──────────────────────────────────────────────────────────────────────┐
│                         PATH A: Interactive                         │
│                                                                      │
│  User ─→ Agent (Claude SDK) ──stdio──→ UPS MCP Server               │
│                                                                      │
│  The agent calls UPS MCP tools directly during conversation.         │
│  Tool definitions are auto-discovered from the MCP server.           │
│  Used for: ad-hoc rating, address validation, tracking, voiding.     │
│  Tool names appear as: mcp__ups__rate_shipment, etc.                 │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                       PATH B: Batch Processing                       │
│                                                                      │
│  Agent ─→ batch tools ─→ BatchEngine ─→ UPSMCPClient ──stdio──→ UPS │
│                                                                      │
│  The agent calls ShipAgent's deterministic batch tools.              │
│  Those tools use UPSMCPClient, which programmatically calls          │
│  UPS MCP tools via a separate stdio connection.                      │
│  Used for: bulk rating (preview), bulk shipping (execute).           │
└──────────────────────────────────────────────────────────────────────┘
```

### Impact on New Tools

| Path | Discovery | ShipAgent Changes Required |
|------|-----------|--------------------------|
| **Interactive** | Automatic — SDK reads tool list from MCP server on connect | **Minimal.** System prompt guidance only. |
| **Batch** | Manual — each tool must be explicitly wrapped in `UPSMCPClient` | **Significant.** Client method, response normalizer, retry policy, batch engine integration. |

---

## 2. Current Tool Inventory

Eighteen tools are available from the UPS MCP server (v2):

| # | Tool | Domain | Interactive | Batch | UPSMCPClient Method | Purpose |
|---|------|--------|:-----------:|:-----:|---------------------|---------|
| 1 | `rate_shipment` | Rating | Yes | Yes | `get_rate()` | Get shipping cost estimate |
| 2 | `create_shipment` | Shipping | Yes | Yes | `create_shipment()` | Create shipment + generate label |
| 3 | `void_shipment` | Shipping | Yes | Yes | `void_shipment()` | Cancel an existing shipment |
| 4 | `validate_address` | Address | Yes | Yes | `validate_address()` | Validate/correct addresses |
| 5 | `track_package` | Tracking | Yes | No | — | Track shipment status |
| 6 | `recover_label` | Shipping | Yes | No | — | Recover previously generated labels |
| 7 | `get_time_in_transit` | Transit | Yes | No | — | Estimate delivery timeframes |
| 8 | `get_landed_cost_quote` | Landed Cost | Yes | Yes | `get_landed_cost()` | Calculate duties/taxes/fees for international shipments |
| 9 | `upload_paperless_document` | Paperless | Yes | Yes | `upload_document()` | Upload customs/trade documents |
| 10 | `push_document_to_shipment` | Paperless | Yes | Yes | `push_document()` | Attach document to shipment |
| 11 | `delete_paperless_document` | Paperless | Yes | Yes | `delete_document()` | Remove document from Forms History |
| 12 | `find_locations` | Locator | Yes | Yes | `find_locations()` | Find UPS Access Points and retail stores |
| 13 | `rate_pickup` | Pickup | Yes | Yes | `rate_pickup()` | Get pickup cost estimate |
| 14 | `schedule_pickup` | Pickup | Yes | Yes | `schedule_pickup()` | Schedule carrier pickup |
| 15 | `cancel_pickup` | Pickup | Yes | Yes | `cancel_pickup()` | Cancel a scheduled pickup |
| 16 | `get_pickup_status` | Pickup | Yes | Yes | `get_pickup_status()` | Check pending pickup status |
| 17 | `get_political_divisions` | Pickup | Yes | Yes | `get_political_divisions()` | List states/provinces for a country |
| 18 | `get_service_center_facilities` | Pickup | Yes | Yes | `get_service_center_facilities()` | Find service center drop-off locations |

**Interactive path (AD-1 policy):** New v2 tools (8–18) are auto-discovered by the SDK. In ShipAgent's orchestrator, new tools are registered for **batch mode only** — the interactive mode tool registry remains unchanged at 3 tools (`preview_interactive_shipment`, `get_job_status`, `get_platform_status`). The agent can call new UPS tools directly via MCP in both modes.

**Batch path:** Tools 8–18 are wrapped in `UPSMCPClient` with named methods, response normalizers, and retry policies. The orchestrator tool registry includes 10 new tool definitions for batch mode.

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

**When to modify:** Every time a new UPS MCP tool needs batch/programmatic access.

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
- `batch_preview_tool` — rate all job rows
- `batch_execute_tool` — ship all job rows (requires `approved=True`)
- `preview_interactive_shipment_tool` — single shipment preview
- `_get_ups_client()` — lazy singleton for UPSMCPClient

**When to modify:** When a new UPS operation should be available as an agent-callable tool in the batch path.

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

### Layer 10: Agent Hooks

**File:** `src/orchestrator/agent/hooks.py`

Safety gates on tool calls:
- Pre-tool validation (e.g., `create_shipment` must have valid input)
- Post-tool logging
- Mode-aware blocking (interactive mode blocks direct `create_shipment`)

**When to modify:** When a new tool needs safety validation or mode-aware blocking.

---

## 4. Scenario Playbooks

### Scenario A: New Read-Only Interactive Tool

**Example:** UPS MCP adds `get_shipping_documents` (retrieve customs forms, invoices, etc.)

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/orchestrator/agent/system_prompt.py` | Add usage guidance for the agent | Recommended |

**That's it.** The SDK auto-discovers the tool from the MCP server. The agent can call `mcp__ups__get_shipping_documents` immediately.

---

### Scenario B: New Tool Needed in Batch Path

**Example:** UPS MCP adds `validate_address_v2` with enhanced validation, and ShipAgent wants to use it for pre-flight address checking before batch shipping.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/services/ups_mcp_client.py` | Add `validate_address_v2()` method | Yes |
| 2 | `src/services/ups_mcp_client.py` | Add `_normalize_address_v2_response()` | Yes |
| 3 | `src/services/ups_mcp_client.py` | Add to retry policy (read-only = 2 retries) | Yes |
| 4 | `src/services/batch_engine.py` | Add pre-flight validation step in `preview()` | Yes |
| 5 | `src/errors/ups_translation.py` | Map any new error codes | If applicable |
| 6 | `src/orchestrator/agent/tools/pipeline.py` | Expose as agent tool if needed | Optional |
| 7 | `src/orchestrator/agent/tools/__init__.py` | Register tool definition | If exposing |
| 8 | `src/orchestrator/agent/system_prompt.py` | Document usage | If exposing |
| 9 | `tests/services/test_ups_mcp_client.py` | Test response normalization | Yes |
| 10 | `tests/services/test_batch_engine.py` | Test pre-flight integration | Yes |

**Implementation in UPSMCPClient:**

```python
async def validate_address_v2(self, address: dict[str, Any]) -> dict[str, Any]:
    """Validate address with enhanced response."""
    try:
        raw = await self._call(
            "validate_address_v2",
            address,
            max_retries=2,      # Read-only — safe to retry
            base_delay=0.2,
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
| 10 | `src/orchestrator/agent/hooks.py` | Add safety gate (returns need confirmation) | Recommended |
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

**Example:** UPS MCP adds `estimate_duties_and_taxes` for international shipments.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/orchestrator/agent/system_prompt.py` | Add guidance for when to use the tool | Recommended |
| 2 | `src/orchestrator/agent/hooks.py` | Add pre-tool validation if needed | Optional |

No UPSMCPClient wrapper needed — the agent calls it directly via `mcp__ups__estimate_duties_and_taxes`.

---

### Scenario G: Wrapping an Existing Interactive Tool for Batch Use

**Example:** ShipAgent wants to use `track_package` (currently interactive-only) in batch mode to check delivery status of all shipped orders.

**ShipAgent changes required:**

| # | File | Change | Required? |
|---|------|--------|:---------:|
| 1 | `src/services/ups_mcp_client.py` | Add `track_package()` method | Yes |
| 2 | `src/services/ups_mcp_client.py` | Add `_normalize_tracking_response()` | Yes |
| 3 | `src/services/ups_mcp_client.py` | Add to retry policy (read-only = 2 retries) | Yes |
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

**Exception:** `create_shipment` gets ONE retry if the error is a 503 with "no healthy upstream" (UPS infrastructure issue, not a duplicate-shipment risk).

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

Manages OpenAPI spec files that the UPS MCP server needs:

| Spec File | Source | Purpose |
|-----------|--------|---------|
| `Rating.yaml` | `docs/rating.yaml` | Rating API schema |
| `Shipping.yaml` | `docs/shipping.yaml` | Shipping API schema |
| `TimeInTransit.yaml` | Generated placeholder | Time-in-transit (stub) |

When new UPS MCP tools require additional spec files, add them to `ensure_ups_specs_dir()`.

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

## 10. Agent Hooks and Safety Gates

**File:** `src/orchestrator/agent/hooks.py`

Hooks intercept tool calls before and after execution:

### Pre-Tool Hooks (Validation)

| Hook | Tool | Purpose |
|------|------|---------|
| `validate_shipping_input` | `create_shipment` | Validates input is a dict |
| `validate_void_shipment` | `void_shipment` | Ensures shipment ID present |
| `validate_data_query` | `query_data` | Warns on unfiltered queries |

### Mode-Aware Blocking

```python
# Interactive mode: blocks direct create_shipment, directs to preview_interactive_shipment
# Batch mode: blocks direct create_shipment, directs to batch_preview/batch_execute
create_shipping_hook(interactive_shipping=True|False)
```

### Post-Tool Hooks

- `log_post_tool()` — logs all tool executions
- `detect_error_response()` — detects error indicators in responses

### Adding Hooks for New Tools

```python
# In hooks.py
def validate_new_tool(tool_name: str, tool_input: dict) -> dict | None:
    """Validate new_tool input before execution."""
    if not tool_input.get("required_field"):
        return {"error": "required_field is missing"}
    return None  # Allow execution

# In create_hook_matchers()
matchers["mcp__ups__new_tool"] = HookMatcher(
    pre_tool=validate_new_tool,
)
```

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

### Update If Safety Gate Needed

| File | Specific Change |
|------|----------------|
| `src/orchestrator/agent/hooks.py` | Add pre-tool validator + hook matcher |

### Rarely Update

| File | When |
|------|------|
| `src/services/mcp_client.py` | Only for MCP protocol changes |
| `src/services/gateway_provider.py` | Only if new singleton MCP client needed |
| `src/orchestrator/agent/client.py` | Only if adding a new MCP server (not tool) |
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
| **Mutating tools: no retry** | `create_shipment` must NOT be retried (duplicate shipment risk). Exception: 503 "no healthy upstream". | `ups_mcp_client.py` |
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
- [ ] Hooks added if tool needs safety gates

---

## 14. Potential UPS MCP Expansions

The following tools could be added to the UPS MCP server. For each, the table indicates what ShipAgent changes would be needed:

### High Priority

| Tool | Description | Interactive | Batch Client | Payload Builder | Batch Engine | Agent Tool | System Prompt |
|------|-------------|:-----------:|:------------:|:---------------:|:------------:|:----------:|:-------------:|
| `create_return_shipment` | Generate return labels | Auto | New method | New function | New mode | New handler | New workflow |
| `rate_shipment_multi` | Rate multiple services at once | Auto | New method | New function | Replace per-service loop | Update existing | Update guidance |
| `create_pickup` | Schedule carrier pickup | Auto | New method | New function | — | New handler | New section |
| `get_proof_of_delivery` | Retrieve POD documents | Auto | Optional | — | — | Optional | Optional |

### Medium Priority

| Tool | Description | Interactive | Batch Client | Payload Builder | Batch Engine | Agent Tool | System Prompt |
|------|-------------|:-----------:|:------------:|:---------------:|:------------:|:----------:|:-------------:|
| `create_international_shipment` | Ship with customs forms | Auto | New method | New function (customs) | New mode | New handler | New workflow |
| `estimate_duties_taxes` | Landed cost calculator | Auto | Optional | New function | Pre-flight step | Optional | New section |
| `validate_address_international` | Non-US address validation | Auto | New method | — | Pre-flight step | Optional | Update rules |
| `get_shipping_documents` | Retrieve customs docs | Auto | Optional | — | Post-execute step | Optional | Optional |

### Lower Priority

| Tool | Description | Interactive | Batch Client | Payload Builder | Batch Engine | Agent Tool | System Prompt |
|------|-------------|:-----------:|:------------:|:---------------:|:------------:|:----------:|:-------------:|
| `create_freight_shipment` | LTL/freight shipping | Auto | New method | New function | New mode | New handler | New section |
| `manage_subscription` | Tracking notifications | Auto | — | — | — | — | Optional |
| `get_accessorials` | List available surcharges | Auto | — | — | — | Optional | Optional |
| `calculate_density` | Freight density calc | Auto | — | — | — | — | — |

### Legend

| Cell Value | Meaning |
|-----------|---------|
| Auto | SDK auto-discovers, no code change |
| New method | Add method to `UPSMCPClient` |
| New function | Add function to `ups_payload_builder.py` |
| New mode | Add execution path to `BatchEngine` |
| New handler | Add tool handler to agent tools |
| New workflow | Add workflow section to system prompt |
| New section | Add documentation section to system prompt |
| Update existing | Modify existing code |
| Optional | Nice-to-have, not required |
| — | Not applicable |
