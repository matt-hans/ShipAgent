# UPS MCP v2 Integration Design

**Date:** 2026-02-15
**Scope:** Integrate 11 new UPS MCP tools (18 total) across backend, batch layer, and frontend.
**Approach:** Layered Rollout — Phase 1 (Foundation), Phase 2 (Batch), Phase 3 (Frontend).

---

## Table of Contents

1. [Decisions](#1-decisions)
2. [Phase 1: Foundation](#2-phase-1-foundation)
3. [Phase 2: Batch Integration](#3-phase-2-batch-integration)
4. [Phase 3: Frontend](#4-phase-3-frontend)
5. [File Change Matrix](#5-file-change-matrix)
6. [Testing Strategy](#6-testing-strategy)

---

## 1. Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | Interactive + all batch candidates | Full integration: all 11 tools interactive, 8 wrapped in UPSMCPClient |
| Approach | Layered rollout (3 phases) | Clean separation, each phase independently testable |
| Color scheme | Shipping/Rating=green (existing), Pickup=purple, Locator=teal, Paperless=amber, Landed Cost=indigo | Keep existing green for core shipping, differentiate new domains |
| UI rendering | Dedicated card components per domain | PickupCard, LocationCard, LandedCostCard, PaperlessCard |
| Safety gates | Confirmation for financial ops only | `schedule_pickup` gets a hook; read-only and reversible ops do not |
| Pickup flow | CompletionArtifact button + direct agent command | Button is a shortcut; user can also ask the agent directly |
| Paperless | Agent tools + BatchEngine internal | Exposed as standalone agent tools AND used internally by BatchEngine for international flows |

---

## 2. Phase 1: Foundation

All changes in this phase enable the 11 new tools in the interactive path (auto-discovered by the SDK) and establish shared infrastructure.

### 2.1 Config Update

**File:** `src/orchestrator/agent/config.py`

Add `UPS_ACCOUNT_NUMBER` to the UPS MCP subprocess environment. Currently missing — only CLIENT_ID, CLIENT_SECRET, ENVIRONMENT, UPS_MCP_SPECS_DIR, and PATH are passed. The new tools (landed cost, paperless, pickup, cancel) all fall back to this env var.

```python
# In get_ups_mcp_config() env dict, add:
"UPS_ACCOUNT_NUMBER": os.environ.get("UPS_ACCOUNT_NUMBER", ""),
```

### 2.2 Spec Files

**File:** `src/services/ups_specs.py`

Add 4 new optional spec file references. These are needed if `UPS_MCP_SPECS_DIR` is used. If the MCP server uses bundled specs, this is a no-op but keeps the mapping explicit.

New entries in the spec mapping:
- `LandedCost.yaml` — enables `get_landed_cost_quote`
- `Paperless.yaml` — enables upload/push/delete paperless
- `Locator.yaml` — enables `find_locations`
- `Pickup.yaml` — enables all 6 pickup tools

These are **optional** — if source files don't exist in `docs/`, create minimal placeholders or skip (MCP server bundles them).

### 2.3 Error Codes

**File:** `src/errors/registry.py` — New E-codes:

| Code | Category | Title | Template | Remediation |
|------|----------|-------|----------|-------------|
| E-2020 | VALIDATION | Missing Required Fields (Structured) | `"Missing {count} required field(s): {fields}"` | `"Provide the missing fields listed above. Check your data source column mapping."` |
| E-2021 | VALIDATION | Malformed Request Structure | `"Request body has structural errors: {reason}"` | `"Check that the request body matches the expected format."` |
| E-2022 | VALIDATION | Ambiguous Billing | `"Multiple billing objects found in ShipmentCharge. Only one payer type allowed."` | `"Use exactly one of: BillShipper, BillReceiver, or BillThirdParty per charge."` |
| E-3006 | UPS_API | Document Not Found | `"Paperless document not found or expired: {ups_message}"` | `"The document may have expired. Re-upload the document and try again."` |
| E-3007 | UPS_API | Pickup Timing Error | `"Pickup scheduling failed: {ups_message}"` | `"Check that the pickup date is in the future and within UPS scheduling windows."` |
| E-3008 | UPS_API | No Locations Found | `"No UPS locations found for the given search criteria."` | `"Try expanding the search radius or adjusting the address."` |
| E-4001 | SYSTEM | Elicitation Declined | `"User declined to provide required information."` | `"The operation was cancelled because required fields were not provided."` |
| E-4002 | SYSTEM | Elicitation Cancelled | `"User cancelled the operation."` | `"The operation was cancelled by the user."` |

**File:** `src/errors/ups_translation.py` — New mappings:

```python
# Add to UPS_ERROR_MAP:
"MALFORMED_REQUEST": "E-2021",      # Split by reason in _translate_error
"9590022": "E-3006",                # Paperless document not found
"190102": "E-3007",                 # Pickup timing
"ELICITATION_DECLINED": "E-4001",   # User declined
"ELICITATION_CANCELLED": "E-4002",  # User cancelled

# Add to UPS_MESSAGE_PATTERNS:
"no locations found": "E-3008",
"no pdf found": "E-3006",
```

**File:** `src/services/ups_mcp_client.py` — Update `_translate_error()`:
- Parse `reason` field from `MALFORMED_REQUEST` errors
- Route `ambiguous_payer` to E-2022, `malformed_structure` to E-2021
- Handle structured `missing` array from `ELICITATION_UNSUPPORTED` for E-2020 (extract field count + names)

### 2.4 System Prompt

**File:** `src/orchestrator/agent/system_prompt.py`

Add 5 new workflow sections to `build_system_prompt()`:

**A. Expanded capabilities overview** — Update existing UPS section to mention all 4 new domains.

**B. Pickup workflow:**
- `rate_pickup` for cost estimation (always before scheduling)
- `schedule_pickup` is a FINANCIAL COMMITMENT — always confirm with user
- Capture PRN from response for cancellation
- `cancel_pickup` with PRN
- `get_pickup_status` for pending pickups
- After batch execute, SUGGEST scheduling a pickup
- `get_service_center_facilities` for drop-off alternatives

**C. Location finder:**
- `find_locations` for Access Points, retail, service centers
- 4 location types: access_point, retail, general, services
- Present results with address, phone, operating hours

**D. Landed cost (international):**
- `get_landed_cost_quote` for duty/tax/fee estimation
- Required: currency, origin country, destination country, commodity list
- Commodity needs: price, quantity, HS code (recommended)
- Present per-commodity breakdown + total

**E. Paperless documents:**
- `upload_paperless_document` for customs/trade docs
- Document types: "002" (invoice), "003" (CO), etc.
- Capture DocumentID from response
- `push_document_to_shipment` with tracking number
- `delete_paperless_document` for cleanup
- Workflow: upload → create shipment → push document

**F. Reference data:**
- `get_political_divisions` for valid states/provinces per country

### 2.5 Hooks

**File:** `src/orchestrator/agent/hooks.py`

**New hook:** `validate_schedule_pickup()` pre-tool hook:
- Validates required fields: pickup_date, ready_time, close_time, address fields, contact_name, phone_number
- Returns error dict if critical fields missing
- Add to `create_hook_matchers()` as matcher for `mcp__ups__schedule_pickup`

**No hooks for:** Read-only tools, paperless operations, cancel_pickup.

### 2.6 .env.example

Document `UPS_ACCOUNT_NUMBER` as recommended (elevated from optional to recommended):
```
# UPS Account Number — required for pickup, paperless, landed cost, and billing
UPS_ACCOUNT_NUMBER=your_account_number
```

---

## 3. Phase 2: Batch Integration

### 3.1 UPSMCPClient Methods

**File:** `src/services/ups_mcp_client.py`

8 new methods following the existing `_call()` → normalize → translate pattern:

#### Pickup Domain (4 methods)

| Method | MCP Tool | Retry Policy | Parameters |
|--------|----------|:------------:|------------|
| `schedule_pickup(pickup_date, ready_time, close_time, address_line, city, state, postal_code, country_code, contact_name, phone_number, **kwargs)` | `schedule_pickup` | 0 retries (mutating) | Flat params passed directly to MCP tool |
| `cancel_pickup(cancel_by, prn="")` | `cancel_pickup` | 0 retries (mutating) | cancel_by: "account" or "prn" |
| `rate_pickup(pickup_type, address_line, city, state, postal_code, country_code, pickup_date, ready_time, close_time, **kwargs)` | `rate_pickup` | 2 retries, 0.2s base (read-only) | Flat params |
| `get_pickup_status(pickup_type, account_number="")` | `get_pickup_status` | 2 retries, 0.2s base (read-only) | Flat params |

#### Landed Cost (1 method)

| Method | MCP Tool | Retry Policy | Parameters |
|--------|----------|:------------:|------------|
| `get_landed_cost(currency_code, export_country_code, import_country_code, commodities, shipment_type="Sale", account_number="")` | `get_landed_cost_quote` | 2 retries, 0.2s base (read-only) | Flat params, commodities is list[dict] |

#### Paperless Documents (3 methods)

| Method | MCP Tool | Retry Policy | Parameters |
|--------|----------|:------------:|------------|
| `upload_document(file_content_base64, file_name, file_format, document_type, shipper_number="")` | `upload_paperless_document` | 0 retries (mutating) | File content as base64 string |
| `push_document(document_id, shipment_identifier, shipment_type="1", shipper_number="")` | `push_document_to_shipment` | 0 retries (mutating) | Requires prior DocumentID + tracking number |
| `delete_document(document_id, shipper_number="")` | `delete_paperless_document` | 0 retries (mutating) | Cleanup operation |

**Key architectural note:** All new tools use **structured parameters** (flat args), not raw UPS API bodies. The MCP tool handles payload construction internally. So these methods pass `dict[str, Any]` of flat key-value pairs to `_call()`.

#### Response Normalizers (8 new)

| Normalizer | Output Shape |
|------------|-------------|
| `_normalize_schedule_pickup_response()` | `{"success": True, "prn": "..."}` |
| `_normalize_cancel_pickup_response()` | `{"success": True, "status": "cancelled"}` |
| `_normalize_rate_pickup_response()` | `{"success": True, "charges": {...}, "serviceDate": "..."}` |
| `_normalize_pickup_status_response()` | `{"success": True, "pickups": [...]}` |
| `_normalize_landed_cost_response()` | `{"success": True, "totalLandedCost": "...", "currencyCode": "...", "items": [...]}` |
| `_normalize_upload_response()` | `{"success": True, "documentId": "..."}` |
| `_normalize_push_response()` | `{"success": True, "status": "pushed"}` |
| `_normalize_delete_response()` | `{"success": True, "status": "deleted"}` |

### 3.2 Agent Tools

#### New file: `src/orchestrator/agent/tools/pickup.py`

4 tool handlers:

| Handler | Description | Mode |
|---------|-------------|------|
| `schedule_pickup_tool` | Collects pickup params, calls UPSMCPClient, emits bridge event with PRN | Both modes |
| `cancel_pickup_tool` | Takes PRN or cancel-by-account, calls UPSMCPClient | Both modes |
| `rate_pickup_tool` | Estimates pickup cost, returns rate info | Both modes |
| `get_pickup_status_tool` | Returns pending pickup status | Both modes |

#### New file: `src/orchestrator/agent/tools/documents.py`

3 tool handlers:

| Handler | Description | Mode |
|---------|-------------|------|
| `upload_paperless_document_tool` | Takes base64 content + metadata, returns DocumentID | Both modes |
| `push_document_to_shipment_tool` | Takes DocumentID + tracking number, links them | Both modes |
| `delete_paperless_document_tool` | Takes DocumentID, removes from Forms History | Both modes |

#### Additions to `src/orchestrator/agent/tools/pipeline.py`

1 new handler:

| Handler | Description | Mode |
|---------|-------------|------|
| `get_landed_cost_tool` | Takes commodity list + countries, returns duty/tax breakdown | Both modes |

#### Registration in `src/orchestrator/agent/tools/__init__.py`

- Import from `pickup.py`, `documents.py`, and updated `pipeline.py`
- Add 8 tool definitions (4 pickup + 3 paperless + 1 landed cost)
- All available in both batch and interactive modes (pickup/paperless/landed cost are cross-cutting concerns)

### 3.3 BatchEngine Extensions

**File:** `src/services/batch_engine.py`

**Post-execute pickup availability event:**
After `execute()` completes, emit a bridge event `pickup_available` containing:
- `successful_count`: Number of successful shipments
- `shipper_address`: Shipper address from the job context
- `job_id`: For reference

This event is consumed by the frontend to show the "Schedule Pickup" button in CompletionArtifact.

**International paperless flow (within execute):**
For each international row after `create_shipment` succeeds:
1. Check if customs document exists (e.g., from row data or pre-uploaded)
2. If yes: `await self._ups.upload_document(...)` → capture `documentId`
3. `await self._ups.push_document(documentId, trackingNumber)`
4. On failure: log warning via audit service, do NOT fail the row

**Landed cost pre-flight (within preview):**
For international rows:
1. Call `await self._ups.get_landed_cost(...)` per row
2. Attach duty/tax estimate to the preview row result
3. Surfaced in PreviewCard charge breakdown alongside transport charges

---

## 4. Phase 3: Frontend

### 4.1 Domain Color System

**File:** `frontend/src/index.css`

New OKLCH domain colors as CSS custom properties:

| Domain | Variable | OKLCH (dark) | Hex Approx |
|--------|----------|-------------|------------|
| Shipping/Rating | `--color-domain-shipping` | Existing `--color-success` | Green |
| Pickup | `--color-domain-pickup` | `oklch(0.7 0.18 300)` | Purple/violet |
| Locator | `--color-domain-locator` | `oklch(0.72 0.15 195)` | Teal/cyan |
| Paperless | `--color-domain-paperless` | `oklch(0.78 0.16 85)` | Amber/gold |
| Landed Cost | `--color-domain-landed-cost` | `oklch(0.65 0.18 270)` | Indigo |

New utility classes per domain:
- `.border-l-domain-{name}` — Left border color
- `.badge-{name}` — Badge with domain background/text color
- `.text-domain-{name}` — Text color
- `.bg-domain-{name}` — Background color (at /10 opacity)

### 4.2 Card Components

#### `frontend/src/components/command-center/PickupCard.tsx`

Renders 4 pickup result variants:

| Variant | Display | Key Data |
|---------|---------|----------|
| Rate result | Cost estimate + service date | Amount, currency, pickup type |
| Schedule confirmation | PRN + date/time + address | PRN, date, ready/close times, address, contact |
| Status | List of pending pickups | PRN, date, status per pickup |
| Cancel confirmation | Cancelled PRN | PRN, status |

Purple left border (`border-l-domain-pickup`), `badge-pickup` header badge.

#### `frontend/src/components/command-center/LocationCard.tsx`

Renders location search results:
- List layout with location cards
- Each location: name, type badge, address, phone, operating hours
- Distance from search address
- Teal left border, `badge-locator` header badge

#### `frontend/src/components/command-center/LandedCostCard.tsx`

Renders international cost breakdown:
- Total landed cost header with currency
- Per-commodity table: description, HS code, duties, taxes, fees
- Summary row with totals
- Indigo left border, `badge-landed-cost` header badge

#### `frontend/src/components/command-center/PaperlessCard.tsx`

Renders document operation results:

| Variant | Display | Key Data |
|---------|---------|----------|
| Upload success | DocumentID + file info | DocumentID, fileName, format, docType |
| Push success | Document linked to shipment | DocumentID, tracking number |
| Delete success | Document removed | DocumentID |

Amber left border, `badge-paperless` header badge.

### 4.3 SSE Event Routing

**File:** `frontend/src/components/CommandCenter.tsx`

New event type handlers in the SSE event router:

| Event Type | Card Component | Emitted By |
|-----------|---------------|------------|
| `pickup_result` | `PickupCard` | `schedule_pickup_tool`, `cancel_pickup_tool`, `rate_pickup_tool`, `get_pickup_status_tool` |
| `location_result` | `LocationCard` | Agent calls `mcp__ups__find_locations` (bridge event from agent response parsing) |
| `landed_cost_result` | `LandedCostCard` | `get_landed_cost_tool` |
| `paperless_result` | `PaperlessCard` | `upload_paperless_document_tool`, `push_document_to_shipment_tool`, `delete_paperless_document_tool` |
| `pickup_available` | CompletionArtifact button | BatchEngine post-execute |

Event routing follows the existing `preview_ready` pattern: bridge emits typed event → CommandCenter routes to card component.

### 4.4 CompletionArtifact Enhancement

**File:** `frontend/src/components/command-center/CompletionArtifact.tsx`

After batch execution with successful shipments:
- New "Schedule Pickup" button at bottom of completion card
- Styled with purple/pickup domain colors
- Click handler sends message to agent: `"Schedule a pickup for the shipments I just created"`
- Button only appears when `metadata.completion.successful > 0`
- Button appears when `pickup_available` event was received for this job

### 4.5 TypeScript Types

**File:** `frontend/src/types/api.ts`

New interfaces:

```typescript
interface PickupResult {
  type: 'rate' | 'schedule' | 'cancel' | 'status';
  prn?: string;
  estimatedCost?: { amount: string; currency: string };
  pickupDate?: string;
  readyTime?: string;
  closeTime?: string;
  address?: {
    line: string;
    city: string;
    state: string;
    postal: string;
    country: string;
  };
  contactName?: string;
  phone?: string;
  status?: string;
  pickups?: Array<{ prn: string; date: string; status: string }>;
}

interface LocationResult {
  locations: Array<{
    id: string;
    name?: string;
    type: string;
    address: {
      lines: string[];
      city: string;
      state: string;
      postal: string;
      country: string;
    };
    phone?: string;
    hours?: Record<string, string>;
    distance?: { value: number; unit: string };
  }>;
}

interface LandedCostResult {
  totalLandedCost: string;
  currencyCode: string;
  exportCountry: string;
  importCountry: string;
  items: Array<{
    commodityId: string;
    description?: string;
    hsCode?: string;
    duties: string;
    taxes: string;
    fees: string;
  }>;
}

interface PaperlessResult {
  type: 'upload' | 'push' | 'delete';
  documentId?: string;
  fileName?: string;
  fileFormat?: string;
  documentType?: string;
  trackingNumber?: string;
  status: string;
}
```

---

## 5. File Change Matrix

### Phase 1: Foundation (enables all 11 tools interactively)

| # | File | Change | Effort |
|---|------|--------|:------:|
| 1 | `src/orchestrator/agent/config.py` | Add `UPS_ACCOUNT_NUMBER` to env dict | Minimal |
| 2 | `src/services/ups_specs.py` | Add 4 optional spec file references | Low |
| 3 | `src/errors/registry.py` | Register 8 new E-codes (E-2020–E-2022, E-3006–E-3008, E-4001–E-4002) | Low |
| 4 | `src/errors/ups_translation.py` | Map new error codes + message patterns | Low |
| 5 | `src/services/ups_mcp_client.py` | Update `_translate_error()` for MALFORMED_REQUEST reason parsing | Low |
| 6 | `src/orchestrator/agent/system_prompt.py` | Add 5 new workflow sections for new domains | Medium |
| 7 | `src/orchestrator/agent/hooks.py` | Add `validate_schedule_pickup` hook + matcher | Low |
| 8 | `.env.example` | Document UPS_ACCOUNT_NUMBER as recommended | Minimal |

### Phase 2: Batch Integration

| # | File | Change | Effort |
|---|------|--------|:------:|
| 9 | `src/services/ups_mcp_client.py` | Add 8 methods + 8 normalizers + retry policies | High |
| 10 | `src/orchestrator/agent/tools/pickup.py` | New file: 4 pickup tool handlers | Medium |
| 11 | `src/orchestrator/agent/tools/documents.py` | New file: 3 paperless tool handlers | Medium |
| 12 | `src/orchestrator/agent/tools/pipeline.py` | Add `get_landed_cost_tool` handler | Low |
| 13 | `src/orchestrator/agent/tools/__init__.py` | Register 8 new tool definitions | Medium |
| 14 | `src/services/batch_engine.py` | Post-execute pickup event + international paperless flow + landed cost pre-flight | Medium |
| 15 | `tests/services/test_ups_mcp_client.py` | Test 8 new methods + normalizers | High |
| 16 | `tests/orchestrator/agent/tools/test_pickup.py` | Test pickup tool handlers | Medium |
| 17 | `tests/orchestrator/agent/tools/test_documents.py` | Test paperless tool handlers | Medium |
| 18 | `tests/services/test_batch_engine.py` | Test post-execute pickup + paperless flow | Medium |

### Phase 3: Frontend

| # | File | Change | Effort |
|---|------|--------|:------:|
| 19 | `frontend/src/index.css` | Add 4 domain color variables + utility classes | Low |
| 20 | `frontend/src/components/command-center/PickupCard.tsx` | New component: 4 pickup result variants | Medium |
| 21 | `frontend/src/components/command-center/LocationCard.tsx` | New component: location search results | Medium |
| 22 | `frontend/src/components/command-center/LandedCostCard.tsx` | New component: international cost breakdown | Medium |
| 23 | `frontend/src/components/command-center/PaperlessCard.tsx` | New component: document operation results | Low |
| 24 | `frontend/src/components/command-center/CompletionArtifact.tsx` | Add "Schedule Pickup" button | Low |
| 25 | `frontend/src/components/CommandCenter.tsx` | Route 5 new event types to card components | Medium |
| 26 | `frontend/src/types/api.ts` | Add 4 new result interfaces | Low |

---

## 6. Testing Strategy

### Phase 1 Tests

- Error registry: Verify all 8 new E-codes are registered with correct categories and templates
- Error translation: Test new UPS_ERROR_MAP entries and message pattern matching
- Error translation: Test MALFORMED_REQUEST reason-based routing (E-2021 vs E-2022)
- Config: Verify UPS_ACCOUNT_NUMBER appears in MCP subprocess env
- System prompt: Verify new sections appear in generated prompt for both modes
- Hooks: Test `validate_schedule_pickup` with valid/invalid inputs

### Phase 2 Tests

- UPSMCPClient: Test each of 8 new methods with mocked MCP responses
- UPSMCPClient: Test 8 normalizers with valid, empty, and malformed responses
- UPSMCPClient: Test retry policies (read-only=2, mutating=0) for each method
- Agent tools: Test each handler returns `_ok()` on success, `_err()` on failure
- Agent tools: Test bridge events emitted correctly
- Agent tools: Test tool definitions registered in `get_all_tool_definitions()` for both modes
- BatchEngine: Test post-execute `pickup_available` event emission
- BatchEngine: Test international paperless upload → push chain
- BatchEngine: Test landed cost pre-flight in preview

### Phase 3 Tests

- Visual: Each card component renders with correct domain-colored border
- Visual: Badge colors match domain
- Functional: SSE events route to correct card component
- Functional: CompletionArtifact "Schedule Pickup" button appears after successful batch
- Functional: Button sends correct message to agent
- Types: New TypeScript interfaces compile without errors

### Integration Tests

- End-to-end: Agent calls `schedule_pickup` interactively → PickupCard renders with PRN
- End-to-end: Agent calls `find_locations` → LocationCard renders with location list
- End-to-end: Batch execute → CompletionArtifact → "Schedule Pickup" button → agent pickup flow
- End-to-end: International batch preview shows landed cost breakdown per row
