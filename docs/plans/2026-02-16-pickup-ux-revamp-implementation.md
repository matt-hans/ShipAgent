# Pickup UX Revamp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the minimal pickup rate/schedule cards with a rich preview → confirm → completion artifact flow that mirrors the shipping UX.

**Architecture:** The `rate_pickup_tool` emits a new `pickup_preview` SSE event containing all pickup details + rate. The frontend renders a `PickupPreviewCard` with Confirm/Cancel buttons. On confirm, the agent calls `schedule_pickup_tool` which emits an enriched `pickup_result` rendered as a `PickupCompletionCard`. Charge codes are mapped to human-readable labels.

**Tech Stack:** Python (FastAPI backend tools), React + TypeScript (frontend components), existing SSE event system

---

### Task 1: Add Charge Code Labels and Enrich Rate Response

**Files:**
- Modify: `src/services/ups_mcp_client.py:1077-1102` (`_normalize_rate_pickup_response`)
- Test: `tests/services/test_ups_mcp_client.py`

**Step 1: Write the failing test**

Add to `tests/services/test_ups_mcp_client.py`:

```python
@pytest.mark.asyncio
async def test_rate_pickup_includes_charge_labels():
    """_normalize_rate_pickup_response maps charge codes to human labels."""
    raw = {
        "PickupRateResponse": {
            "RateResult": {
                "ChargeDetail": [
                    {"ChargeCode": "B", "ChargeAmount": "9.65"},
                    {"ChargeCode": "S", "ChargeAmount": "0.00"},
                ],
                "GrandTotalOfAllCharge": "9.65",
            }
        }
    }
    # Access the normalizer directly
    client = UPSMCPClient.__new__(UPSMCPClient)
    result = client._normalize_rate_pickup_response(raw)
    assert result["charges"][0]["chargeLabel"] == "Base Charge"
    assert result["charges"][1]["chargeLabel"] == "Surcharge"
    assert result["grandTotal"] == "9.65"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_mcp_client.py::test_rate_pickup_includes_charge_labels -v`
Expected: FAIL — `chargeLabel` key not present

**Step 3: Implement charge label mapping**

In `src/services/ups_mcp_client.py`, add near top of file (after imports):

```python
# Human-readable labels for UPS pickup charge codes.
PICKUP_CHARGE_LABELS: dict[str, str] = {
    "B": "Base Charge",
    "S": "Surcharge",
    "T": "Tax",
    "R": "Residential Surcharge",
    "F": "Fuel Surcharge",
}
```

Then modify `_normalize_rate_pickup_response` to add `chargeLabel`:

```python
def _normalize_rate_pickup_response(self, raw: dict) -> dict[str, Any]:
    """Extract charges from raw UPS pickup rate response.

    Args:
        raw: Raw UPS PickupRateResponse dict.

    Returns:
        Normalised response dict with success, charges (with labels), and grandTotal.
    """
    rate_result = raw.get("PickupRateResponse", {}).get("RateResult", {})
    charge_detail = rate_result.get("ChargeDetail", [])
    if isinstance(charge_detail, dict):
        charge_detail = [charge_detail]
    grand_total = rate_result.get("GrandTotalOfAllCharge", "0")
    charges = [
        {
            "chargeAmount": c.get("ChargeAmount", "0"),
            "chargeCode": c.get("ChargeCode", ""),
            "chargeLabel": PICKUP_CHARGE_LABELS.get(
                c.get("ChargeCode", ""), c.get("ChargeCode", "")
            ),
        }
        for c in charge_detail
    ]
    return {
        "success": True,
        "charges": charges,
        "grandTotal": grand_total,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_ups_mcp_client.py::test_rate_pickup_includes_charge_labels -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "feat: add human-readable charge labels to pickup rate response"
```

---

### Task 2: Modify `rate_pickup_tool` to Emit `pickup_preview` Event

**Files:**
- Modify: `src/orchestrator/agent/tools/pickup.py:101-125` (`rate_pickup_tool`)
- Test: `tests/orchestrator/agent/test_tools_v2.py`

**Step 1: Write the failing test**

Add to `tests/orchestrator/agent/test_tools_v2.py`:

```python
@pytest.mark.asyncio
async def test_rate_pickup_tool_emits_pickup_preview_event():
    """rate_pickup_tool emits pickup_preview (not pickup_result) with all input details."""
    mock_ups = AsyncMock()
    mock_ups.rate_pickup.return_value = {
        "success": True,
        "charges": [
            {"chargeAmount": "9.65", "chargeCode": "B", "chargeLabel": "Base Charge"},
        ],
        "grandTotal": "9.65",
    }

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import rate_pickup_tool

        result = await rate_pickup_tool(
            {
                "pickup_type": "oncall",
                "address_line": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country_code": "US",
                "pickup_date": "20260217",
                "ready_time": "0900",
                "close_time": "1700",
                "contact_name": "John Smith",
                "phone_number": "214-555-1234",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "pickup_preview"
    payload = captured[0][1]
    assert payload["address_line"] == "123 Main St"
    assert payload["city"] == "Dallas"
    assert payload["contact_name"] == "John Smith"
    assert payload["grand_total"] == "9.65"
    assert payload["charges"][0]["chargeLabel"] == "Base Charge"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py::test_rate_pickup_tool_emits_pickup_preview_event -v`
Expected: FAIL — event type is `pickup_result`, not `pickup_preview`

**Step 3: Modify `rate_pickup_tool`**

Replace the existing `rate_pickup_tool` in `src/orchestrator/agent/tools/pickup.py`:

```python
async def rate_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Get a pickup cost estimate and emit pickup_preview event.

    Emits a ``pickup_preview`` event containing the full pickup details
    (address, schedule, contact) alongside the rate charges, so the
    frontend can render a rich preview card with Confirm/Cancel buttons.

    Args:
        args: Dict with pickup_type, address fields, pickup_date,
              ready_time, close_time, contact_name, phone_number,
              and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with rate estimate, or error envelope.
    """
    try:
        client = await _get_ups_client()
        # Extract input details before passing to client
        input_details = {
            "pickup_type": args.get("pickup_type", "oncall"),
            "address_line": args.get("address_line", ""),
            "city": args.get("city", ""),
            "state": args.get("state", ""),
            "postal_code": args.get("postal_code", ""),
            "country_code": args.get("country_code", "US"),
            "pickup_date": args.get("pickup_date", ""),
            "ready_time": args.get("ready_time", ""),
            "close_time": args.get("close_time", ""),
            "contact_name": args.get("contact_name", ""),
            "phone_number": args.get("phone_number", ""),
        }
        result = await client.rate_pickup(**args)
        # Emit pickup_preview with all details + rate
        payload = {
            **input_details,
            "charges": result.get("charges", []),
            "grand_total": result.get("grandTotal", "0"),
        }
        _emit_event("pickup_preview", payload, bridge=bridge)
        return _ok(
            "Pickup rate estimate displayed. Waiting for user to confirm or cancel "
            "via the preview card. Do NOT call schedule_pickup until the user confirms."
        )
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in rate_pickup_tool")
        return _err(f"Unexpected error: {e}")
```

**Step 4: Update the existing rate test**

The existing `test_rate_pickup_tool_success` test checks for `pickup_result` event. Update it to check for `pickup_preview` instead:

In `tests/orchestrator/agent/test_tools_v2.py`, find the `test_rate_pickup_tool_success` test and change:
- `assert captured[0][0] == "pickup_result"` → `assert captured[0][0] == "pickup_preview"`
- Remove `assert captured[0][1]["action"] == "rated"` (no longer has action field)

**Step 5: Run tests to verify they pass**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -k "rate_pickup" -v`
Expected: All rate_pickup tests PASS

**Step 6: Commit**

```bash
git add src/orchestrator/agent/tools/pickup.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: rate_pickup_tool emits pickup_preview event with full details"
```

---

### Task 3: Enrich `schedule_pickup_tool` Completion Payload

**Files:**
- Modify: `src/orchestrator/agent/tools/pickup.py:24-60` (`schedule_pickup_tool`)
- Test: `tests/orchestrator/agent/test_tools_v2.py`

**Step 1: Write the failing test**

Add to `tests/orchestrator/agent/test_tools_v2.py`:

```python
@pytest.mark.asyncio
async def test_schedule_pickup_tool_emits_enriched_result():
    """schedule_pickup_tool includes address/contact/rate in pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "2929602E9CP"}

    bridge = EventEmitterBridge()
    captured: list[tuple[str, dict]] = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch(
        "src.orchestrator.agent.tools.pickup._get_ups_client",
        return_value=mock_ups,
    ):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool

        result = await schedule_pickup_tool(
            {
                "pickup_date": "20260217",
                "ready_time": "0900",
                "close_time": "1700",
                "address_line": "123 Main St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country_code": "US",
                "contact_name": "John Smith",
                "phone_number": "214-555-1234",
                "confirmed": True,
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    payload = captured[0][1]
    assert payload["prn"] == "2929602E9CP"
    assert payload["address_line"] == "123 Main St"
    assert payload["city"] == "Dallas"
    assert payload["contact_name"] == "John Smith"
    assert payload["pickup_date"] == "20260217"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py::test_schedule_pickup_tool_emits_enriched_result -v`
Expected: FAIL — `address_line` not in payload

**Step 3: Modify `schedule_pickup_tool`**

```python
async def schedule_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Schedule a UPS pickup and emit enriched pickup_result event.

    Requires ``confirmed=True`` in args as a safety gate — scheduling a
    pickup is a financial commitment.  The agent must first present
    pickup details to the user via rate_pickup and obtain explicit
    confirmation before calling this tool with ``confirmed=True``.

    Args:
        args: Dict with pickup_date, ready_time, close_time, address fields,
              contact_name, phone_number, confirmed flag, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with PRN on success, or error envelope.
    """
    if not args.pop("confirmed", False):
        return _err(
            "Safety gate: schedule_pickup requires explicit user confirmation. "
            "Present pickup details to the user first, then call again with "
            "confirmed=True."
        )
    # Capture input details for enriched completion event
    input_details = {
        "address_line": args.get("address_line", ""),
        "city": args.get("city", ""),
        "state": args.get("state", ""),
        "postal_code": args.get("postal_code", ""),
        "country_code": args.get("country_code", "US"),
        "pickup_date": args.get("pickup_date", ""),
        "ready_time": args.get("ready_time", ""),
        "close_time": args.get("close_time", ""),
        "contact_name": args.get("contact_name", ""),
        "phone_number": args.get("phone_number", ""),
    }
    try:
        client = await _get_ups_client()
        result = await client.schedule_pickup(**args)
        prn = result.get("prn", "unknown")
        payload = {
            "action": "scheduled",
            "success": True,
            "prn": prn,
            **input_details,
        }
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok(f"Pickup scheduled successfully. PRN: {prn}")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in schedule_pickup_tool")
        return _err(f"Unexpected error: {e}")
```

**Step 4: Run all pickup tests**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -k "pickup" -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/pickup.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: enrich schedule_pickup_tool completion event with address/contact details"
```

---

### Task 4: Update `rate_pickup` Tool Description for Preview Workflow

**Files:**
- Modify: `src/orchestrator/agent/tools/__init__.py:370-396` (rate_pickup definition)
- Modify: `src/orchestrator/agent/system_prompt.py:329-339` (pickup scheduling section)

**Step 1: Update tool description in `__init__.py`**

Change the `rate_pickup` tool definition description at line ~371:

```python
{
    "name": "rate_pickup",
    "description": (
        "Rate a UPS pickup and display the preview card. ALWAYS call this BEFORE "
        "schedule_pickup. Collects address, contact, and schedule details, gets "
        "the rate estimate, and displays a preview card to the user with Confirm/"
        "Cancel buttons. Include contact_name and phone_number in the args so "
        "they appear in the preview."
    ),
```

Add `contact_name` and `phone_number` to the rate_pickup input_schema properties (after `close_time`):

```python
"contact_name": {"type": "string", "description": "Contact name for the pickup."},
"phone_number": {"type": "string", "description": "Contact phone number."},
```

**Step 2: Update system prompt pickup section**

Replace the pickup scheduling section in `src/orchestrator/agent/system_prompt.py` (~line 330-339):

```python
## UPS Pickup Scheduling

- WORKFLOW: When user requests a pickup, call `rate_pickup` with ALL details (address, date, times, contact_name, phone_number). This displays a preview card with Confirm/Cancel buttons.
- After the user confirms via the preview card, call `schedule_pickup` with the SAME details + confirmed=true.
- Do NOT call schedule_pickup without first calling rate_pickup — the preview card is mandatory.
- Capture the PRN (Pickup Request Number) from the schedule response — needed for cancellation.
- Use `cancel_pickup` with the PRN to cancel a scheduled pickup.
- Use `get_pickup_status` to check pending pickups for the account.
- After batch execution completes with successful shipments, SUGGEST scheduling a pickup.
- Use `get_service_center_facilities` to suggest drop-off alternatives when pickup is not suitable.
- Pickup date format: YYYYMMDD. Times: HHMM (24-hour). ready_time must be before close_time.
```

**Step 3: Run system prompt tests**

Run: `pytest tests/orchestrator/agent/ -k "system_prompt" -v`
Expected: PASS (or adjust any tests that assert on exact prompt text)

**Step 4: Commit**

```bash
git add src/orchestrator/agent/tools/__init__.py src/orchestrator/agent/system_prompt.py
git commit -m "feat: update rate_pickup description and system prompt for preview workflow"
```

---

### Task 5: Add Frontend Types for `PickupPreview`

**Files:**
- Modify: `frontend/src/types/api.ts:672-680` (PickupResult) and add PickupPreview

**Step 1: Add `PickupPreview` interface**

Add after the `TrackingResult` interface (around line 735) in `frontend/src/types/api.ts`:

```ts
/** Pickup preview data emitted before scheduling for user confirmation. */
export interface PickupPreview {
  address_line: string;
  city: string;
  state: string;
  postal_code: string;
  country_code: string;
  pickup_date: string;
  ready_time: string;
  close_time: string;
  pickup_type: string;
  contact_name: string;
  phone_number: string;
  charges: Array<{ chargeCode: string; chargeLabel: string; chargeAmount: string }>;
  grand_total: string;
}
```

**Step 2: Enhance `PickupResult` with optional completion fields**

Update the existing `PickupResult` interface:

```ts
/** Pickup operation result from SSE stream. */
export interface PickupResult {
  action: 'scheduled' | 'cancelled' | 'rated' | 'status';
  success: boolean;
  prn?: string;
  // Enriched completion fields (present when action === 'scheduled')
  address_line?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country_code?: string;
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

**Step 3: Add `pickup_preview` to `AgentEventType`**

In the same file, add `'pickup_preview'` to the `AgentEventType` union (~line 620):

```ts
export type AgentEventType =
  | 'agent_thinking'
  | 'tool_call'
  | 'tool_result'
  | 'agent_message'
  | 'agent_message_delta'
  | 'preview_ready'
  | 'pickup_preview'   // <-- NEW
  | 'pickup_result'
  ...
```

**Step 4: Add `pickupPreview` to `ConversationMessage` metadata in `useAppState.tsx`**

In `frontend/src/hooks/useAppState.tsx`, add to the metadata interface (around line 86-92):

```ts
// UPS MCP v2 domain card payloads
pickup?: PickupResult;
pickupPreview?: PickupPreview;  // <-- NEW
location?: LocationResult;
```

Also add the import for `PickupPreview` at the top of the file.

**Step 5: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/hooks/useAppState.tsx
git commit -m "feat: add PickupPreview type and pickup_preview event support"
```

---

### Task 6: Create `PickupPreviewCard` Component

**Files:**
- Create: `frontend/src/components/command-center/PickupPreviewCard.tsx`

**Step 1: Create the component**

Create `frontend/src/components/command-center/PickupPreviewCard.tsx`:

```tsx
/**
 * Preview card for pickup scheduling — shows all details + rate
 * with Confirm/Cancel buttons, mirroring InteractivePreviewCard.
 */

import { cn } from '@/lib/utils';
import type { PickupPreview } from '@/types/api';
import { CheckIcon, XIcon, MapPinIcon, UserIcon } from '@/components/ui/icons';

/** Format YYYYMMDD to "Feb 17, 2026" style display. */
function formatPickupDate(raw: string): string {
  if (raw.length !== 8) return raw;
  const y = raw.slice(0, 4);
  const m = parseInt(raw.slice(4, 6), 10) - 1;
  const d = parseInt(raw.slice(6, 8), 10);
  const date = new Date(parseInt(y, 10), m, d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format HHMM to "9:00 AM" style display. */
function formatTime(raw: string): string {
  if (raw.length !== 4) return raw;
  const h = parseInt(raw.slice(0, 2), 10);
  const m = raw.slice(2, 4);
  const suffix = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${m} ${suffix}`;
}

interface PickupPreviewCardProps {
  data: PickupPreview;
  onConfirm: () => void;
  onCancel: () => void;
  isConfirming: boolean;
}

export function PickupPreviewCard({ data, onConfirm, onCancel, isConfirming }: PickupPreviewCardProps) {
  return (
    <div className="card-premium p-5 animate-scale-in max-w-lg border-l-4 card-domain-pickup">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-white">Pickup Preview</h3>
        <span className="badge badge-info">READY</span>
      </div>

      {/* Address + Contact grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <MapPinIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Pickup Address</span>
          </div>
          <div className="space-y-0.5 text-sm text-slate-200">
            <p>{data.address_line}</p>
            <p className="text-slate-300">
              {data.city}, {data.state} {data.postal_code}
            </p>
            <p className="text-[10px] font-mono text-slate-500">{data.country_code}</p>
          </div>
        </div>

        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <UserIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Contact</span>
          </div>
          <div className="space-y-0.5 text-sm text-slate-200">
            <p className="font-medium">{data.contact_name}</p>
            <p className="text-slate-400 text-xs font-mono">{data.phone_number}</p>
          </div>
        </div>
      </div>

      {/* Schedule row */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Date</p>
          <p className="text-sm font-semibold text-white">{formatPickupDate(data.pickup_date)}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Ready</p>
          <p className="text-sm font-semibold text-white">{formatTime(data.ready_time)}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Close</p>
          <p className="text-sm font-semibold text-white">{formatTime(data.close_time)}</p>
        </div>
      </div>

      {/* Rate breakdown */}
      {data.charges && data.charges.length > 0 && (
        <div className="mb-4 rounded-lg border border-slate-700/50 overflow-hidden">
          <div className="px-3 py-2 bg-slate-800/30">
            <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate Breakdown</p>
          </div>
          <div className="divide-y divide-slate-800">
            {data.charges.map((c, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="text-slate-300">{c.chargeLabel}</span>
                <span className="font-mono text-slate-200">${c.chargeAmount}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Grand total */}
      <div className="bg-gradient-to-r from-purple-500/10 to-purple-500/5 border border-purple-500/20 rounded-lg p-3 mb-4 text-center">
        <p className="text-[10px] font-medium text-purple-400 uppercase tracking-wider mb-1">Estimated Cost</p>
        <p className="text-2xl font-bold text-purple-400">${data.grand_total}</p>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onCancel}
          disabled={isConfirming}
          className="btn-secondary flex-1 h-9 text-sm"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={isConfirming}
          className="btn-primary flex-1 h-9 text-sm flex items-center justify-center gap-2"
        >
          {isConfirming ? (
            <>
              <span className="animate-spin h-3.5 w-3.5 border-2 border-white/20 border-t-white rounded-full" />
              <span>Scheduling...</span>
            </>
          ) : (
            <>
              <CheckIcon className="w-3.5 h-3.5" />
              <span>Confirm & Schedule</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/components/command-center/PickupPreviewCard.tsx
git commit -m "feat: add PickupPreviewCard component with confirm/cancel"
```

---

### Task 7: Create `PickupCompletionCard` Component

**Files:**
- Create: `frontend/src/components/command-center/PickupCompletionCard.tsx`

**Step 1: Create the component**

Create `frontend/src/components/command-center/PickupCompletionCard.tsx`:

```tsx
/**
 * Completion artifact for a scheduled pickup — shows PRN, address, time,
 * contact, and cost. Mirrors CompletionArtifact for shipping.
 */

import { cn } from '@/lib/utils';
import type { PickupResult } from '@/types/api';
import { CheckIcon } from '@/components/ui/icons';

/** Format YYYYMMDD to "Feb 17, 2026" style display. */
function formatPickupDate(raw: string): string {
  if (!raw || raw.length !== 8) return raw || '';
  const y = raw.slice(0, 4);
  const m = parseInt(raw.slice(4, 6), 10) - 1;
  const d = parseInt(raw.slice(6, 8), 10);
  const date = new Date(parseInt(y, 10), m, d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format HHMM to "9:00 AM" style display. */
function formatTime(raw: string): string {
  if (!raw || raw.length !== 4) return raw || '';
  const h = parseInt(raw.slice(0, 2), 10);
  const m = raw.slice(2, 4);
  const suffix = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${m} ${suffix}`;
}

export function PickupCompletionCard({ data }: { data: PickupResult }) {
  return (
    <div className="card-premium p-4 space-y-3 border-l-4 card-domain-pickup">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">Pickup Scheduled</h4>
        <span className={cn('badge', 'badge-success')}>CONFIRMED</span>
      </div>

      {/* PRN */}
      {data.prn && (
        <div className="flex items-center gap-2 bg-slate-800/50 rounded-lg px-3 py-2">
          <CheckIcon className="w-4 h-4 text-success flex-shrink-0" />
          <span className="text-xs text-muted-foreground">PRN:</span>
          <span className="text-sm font-mono font-semibold text-foreground">{data.prn}</span>
        </div>
      )}

      {/* Details grid */}
      {data.address_line && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-0.5">
            <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Address</p>
            <p className="text-xs text-slate-200">{data.address_line}</p>
            <p className="text-xs text-slate-300">
              {data.city}, {data.state} {data.postal_code}
            </p>
          </div>
          <div className="space-y-0.5">
            <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Contact</p>
            <p className="text-xs text-slate-200">{data.contact_name}</p>
            <p className="text-xs text-slate-400 font-mono">{data.phone_number}</p>
          </div>
        </div>
      )}

      {/* Schedule + cost */}
      <div className="flex items-center gap-3 text-xs font-mono text-slate-400">
        {data.pickup_date && (
          <span>{formatPickupDate(data.pickup_date)}</span>
        )}
        {data.ready_time && data.close_time && (
          <>
            <span className="text-slate-600">&middot;</span>
            <span>{formatTime(data.ready_time)} – {formatTime(data.close_time)}</span>
          </>
        )}
        {data.grand_total && (
          <>
            <span className="text-slate-600">&middot;</span>
            <span className="text-purple-400">${data.grand_total}</span>
          </>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/components/command-center/PickupCompletionCard.tsx
git commit -m "feat: add PickupCompletionCard completion artifact"
```

---

### Task 8: Wire Event Routing in CommandCenter

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx`

This is the core wiring task. The changes are:

**Step 1: Add imports**

At the top of `CommandCenter.tsx`, add:

```ts
import type { ..., PickupPreview } from '@/types/api';
import { PickupPreviewCard } from '@/components/command-center/PickupPreviewCard';
import { PickupCompletionCard } from '@/components/command-center/PickupCompletionCard';
```

**Step 2: Add pickup preview state**

After the existing state declarations (around line 66):

```ts
const [pickupPreview, setPickupPreview] = React.useState<PickupPreview | null>(null);
const [isPickupConfirming, setIsPickupConfirming] = React.useState(false);
```

**Step 3: Add `pickup_preview` event handler**

In the event processing effect (around line 210-245), add a new `else if` branch after the `pickup_result` handler:

```ts
} else if (event.type === 'pickup_preview') {
  const previewData = event.data as unknown as PickupPreview;
  setPickupPreview(previewData);
  addMessage({
    role: 'system',
    content: '',
    metadata: { action: 'pickup_preview' as any, pickupPreview: previewData },
  });
  suppressNextMessageRef.current = true;
}
```

**Step 4: Update `pickup_result` handler for enriched scheduled events**

Keep the existing `pickup_result` handler but it will now carry enriched data for `scheduled` action. The `PickupCard` and new `PickupCompletionCard` will handle rendering based on `action`. No change needed to the event handler itself — just the rendering logic.

**Step 5: Update message rendering**

In the conversation message map (around line 417-420), replace the `pickup_result` rendering:

```tsx
) : message.metadata?.action === 'pickup_preview' && message.metadata.pickupPreview ? (
  <div key={message.id} className="pl-11">
    <PickupPreviewCard
      data={message.metadata.pickupPreview}
      onConfirm={async () => {
        setIsPickupConfirming(true);
        try {
          await conv.sendMessage('Confirmed. Schedule the pickup.', interactiveShipping);
        } finally {
          setIsPickupConfirming(false);
          setPickupPreview(null);
        }
      }}
      onCancel={() => {
        setPickupPreview(null);
        addMessage({ role: 'system', content: 'Pickup cancelled.' });
      }}
      isConfirming={isPickupConfirming}
    />
  </div>
) : message.metadata?.action === 'pickup_result' && message.metadata.pickup ? (
  <div key={message.id} className="pl-11">
    {message.metadata.pickup.action === 'scheduled' ? (
      <PickupCompletionCard data={message.metadata.pickup} />
    ) : (
      <PickupCard data={message.metadata.pickup} />
    )}
  </div>
```

**Step 6: Disable input while pickup preview is active**

In the input disabled condition (line ~600), add `|| !!pickupPreview`:

```ts
disabled={!canInput || isProcessing || !!preview || !!executingJobId || !!pickupPreview || isResettingSession}
```

And same for the send button disabled condition (line ~617).

**Step 7: Clear pickup state on session reset**

In the `doReset` function (around line 113), add:

```ts
setPickupPreview(null);
setIsPickupConfirming(false);
```

**Step 8: Add `'pickup_preview'` to the action type in useAppState.tsx**

In `frontend/src/hooks/useAppState.tsx`, add `'pickup_preview'` to the `action` union type:

```ts
action?:
  | 'preview' | 'execute' | 'complete' | 'error' | 'elicit'
  | 'pickup_preview' | 'pickup_result' | 'location_result' | 'landed_cost_result' | 'paperless_result'
  | 'tracking_result';
```

**Step 9: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 10: Commit**

```bash
git add frontend/src/components/CommandCenter.tsx frontend/src/hooks/useAppState.tsx
git commit -m "feat: wire pickup_preview event routing with confirm/cancel in CommandCenter"
```

---

### Task 9: Update Existing PickupCard for Cancel/Status Only

**Files:**
- Modify: `frontend/src/components/command-center/PickupCard.tsx`

**Step 1: Simplify PickupCard**

The `PickupCard` now only handles `cancelled`, `status`, and fallback `rated` (if somehow used standalone). Remove the `rated` action from `ACTION_META` since it's now handled by `PickupPreviewCard`. Keep the rated section as a fallback but update the charge display to use `chargeLabel`:

In the rated charges section (~line 46-55), change `c.chargeCode` to use `chargeLabel` when available:

```tsx
<span className="text-muted-foreground">{c.chargeLabel || c.chargeCode}</span>
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/components/command-center/PickupCard.tsx
git commit -m "fix: PickupCard uses chargeLabel for human-readable charge names"
```

---

### Task 10: Run Full Test Suite and Verify

**Files:** None (verification only)

**Step 1: Run backend tests**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -v -k "pickup"`
Expected: All pickup tests PASS

**Step 2: Run UPS MCP client tests**

Run: `pytest tests/services/test_ups_mcp_client.py -v -k "pickup"`
Expected: All pickup tests PASS

**Step 3: Run full backend tests (excluding known hangs)**

Run: `pytest -k "not stream and not sse and not progress" --tb=short -q`
Expected: All tests PASS (except known pre-existing failures)

**Step 4: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 5: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 6: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "test: verify pickup UX revamp integration"
```
