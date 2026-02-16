# Pickup UX Revamp Design

**Date:** 2026-02-16
**Status:** Approved
**Approach:** A — New `pickup_preview` event, dedicated PickupPreviewCard + PickupCompletionCard

## Problem

The current pickup flow has three UX issues:

1. **Cryptic rate labels** — UPS charge codes ("B", "S") are displayed raw instead of human-readable names ("Base Charge", "Surcharge")
2. **No preview/confirm pattern** — The agent asks for text confirmation in chat. No rich card with Confirm/Cancel buttons like the shipping flow provides.
3. **Minimal completion card** — After scheduling, only shows PRN. No address, time window, contact info, or rate summary.

## Solution

Mirror the shipping preview/confirm/completion pattern for pickups:

1. Agent calls `rate_pickup_tool` → emits `pickup_preview` event with all details + rate
2. Frontend renders `PickupPreviewCard` with full details + Confirm/Cancel buttons
3. User clicks Confirm → frontend sends confirmation message to agent
4. Agent calls `schedule_pickup_tool(confirmed=True)` → emits enriched `pickup_result`
5. Frontend renders `PickupCompletionCard` with PRN + all details

## Data Model Changes

### New `PickupPreview` type

```ts
interface PickupPreview {
  address_line: string;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  pickup_date: string;       // "20260217"
  ready_time: string;        // "0900"
  close_time: string;        // "1700"
  pickup_type: string;       // "oncall" | "smart"
  contact_name: string;
  phone_number: string;
  charges: Array<{ chargeCode: string; chargeLabel: string; chargeAmount: string }>;
  grand_total: string;
}
```

### Enhanced `PickupResult` (completion)

Add fields to existing type for rich completion card:

```ts
interface PickupResult {
  action: 'scheduled' | 'cancelled' | 'rated' | 'status';
  success: boolean;
  prn?: string;
  // Rich completion fields:
  address_line?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  pickup_date?: string;
  ready_time?: string;
  close_time?: string;
  contact_name?: string;
  phone_number?: string;
  grand_total?: string;
  charges?: Array<{ chargeAmount: string; chargeCode: string; chargeLabel: string }>;
  pickups?: Array<{ pickupDate: string; prn: string }>;
}
```

### Charge Code Labels

```python
PICKUP_CHARGE_LABELS = {
    "B": "Base Charge",
    "S": "Surcharge",
    "T": "Tax",
    "R": "Residential Surcharge",
    "F": "Fuel Surcharge",
}
```

## Backend Changes

### `rate_pickup_tool` (tools/pickup.py)

- Emits `pickup_preview` event (new type) instead of `pickup_result`
- Payload includes all input args (address, times, contact) + rate charges with human-readable labels
- The tool's return value to the agent instructs it to wait for user confirmation

### `schedule_pickup_tool` (tools/pickup.py)

- Enriched `pickup_result` payload includes address, times, contact, rate alongside PRN
- The tool receives the pickup details from the agent (which has them from the rate step)

### `UPSMCPClient._normalize_rate_pickup_response`

- Add `chargeLabel` field via `PICKUP_CHARGE_LABELS.get(code, code)` mapping

## Frontend Components

### `PickupPreviewCard` (new)

Purple domain border, mirrors `InteractivePreviewCard`:
- Header: "Pickup Preview" + "READY" badge
- Pickup Address section (location details)
- Schedule section: formatted date, ready time → close time window
- Contact section: name, phone
- Rate breakdown: itemized charges with labels + grand total highlight
- Actions: Cancel / Confirm & Schedule buttons

### `PickupCompletionCard` (new)

Purple domain border, rich completion artifact:
- Header: "Pickup Scheduled" + "CONFIRMED" badge
- PRN in monospace highlight
- Address, date/time, contact summary
- Total cost

### Existing `PickupCard`

Retained for `cancelled` and `status` actions only. Minimal changes.

## Frontend Event Routing (CommandCenter.tsx)

1. New `pickup_preview` event → store in `pickupPreview` state, render `PickupPreviewCard`
2. Confirm button → `conv.sendMessage("Confirmed. Schedule the pickup.", interactiveShipping)`
3. Cancel button → clear `pickupPreview` state, add system message
4. `pickup_result` with `action === 'scheduled'` → render `PickupCompletionCard`
5. Disable chat input while pickup preview is active (same as shipping preview)

## Agent System Prompt Update

Update pickup workflow instructions:
- When user asks to schedule pickup: first call `rate_pickup_tool` to get rate + emit preview
- Wait for user confirmation message
- Then call `schedule_pickup_tool(confirmed=True)` with all details

## Files Modified

| File | Change |
|------|--------|
| `src/orchestrator/agent/tools/pickup.py` | Emit `pickup_preview` event from rate tool; enrich schedule result |
| `src/services/ups_mcp_client.py` | Add `chargeLabel` to rate response normalization |
| `src/orchestrator/agent/system_prompt.py` | Update pickup workflow instructions |
| `frontend/src/types/api.ts` | Add `PickupPreview` type, enhance `PickupResult` |
| `frontend/src/components/command-center/PickupCard.tsx` | Refactor: keep for cancel/status only |
| `frontend/src/components/command-center/PickupPreviewCard.tsx` | New: preview with confirm/cancel |
| `frontend/src/components/command-center/PickupCompletionCard.tsx` | New: rich completion artifact |
| `frontend/src/components/CommandCenter.tsx` | Route `pickup_preview` event, manage state |
| `frontend/src/hooks/useAppState.tsx` | Add pickup preview to conversation message metadata |
| `tests/orchestrator/agent/test_tools_v2.py` | Update pickup tool tests |
