# UPS MCP v2 Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate 11 new UPS MCP tools (18 total) into ShipAgent across backend foundation, batch wrapping, and frontend card components.

**Architecture:** Three-phase layered rollout. Phase 1 updates config, specs, error codes, system prompt, and hooks to enable all new tools interactively. Phase 2 wraps 8 tools in UPSMCPClient with normalizers and registers them as agent tools. Phase 3 adds domain-colored card components to the frontend.

**Tech Stack:** Python (FastAPI, Claude Agent SDK), TypeScript (React, Tailwind CSS v4, OKLCH colors)

**Design Doc:** `docs/plans/2026-02-15-ups-mcp-v2-integration-design.md`
**UPS MCP Integration Guide:** `docs/ups-mcp-integration-guide.md`

---

## Phase 1: Foundation

### Task 1: Add UPS_ACCOUNT_NUMBER to MCP subprocess config

**Files:**
- Modify: `src/orchestrator/agent/config.py:131-137`
- Modify: `src/services/ups_mcp_client.py:114-124`
- Test: `tests/orchestrator/agent/test_config.py`

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/test_config.py — add to existing test file
def test_ups_mcp_config_includes_account_number(monkeypatch):
    """UPS MCP subprocess env must include UPS_ACCOUNT_NUMBER."""
    monkeypatch.setenv("UPS_CLIENT_ID", "test-id")
    monkeypatch.setenv("UPS_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("UPS_ACCOUNT_NUMBER", "ABC123")
    from src.orchestrator.agent.config import get_ups_mcp_config
    config = get_ups_mcp_config()
    assert config["env"]["UPS_ACCOUNT_NUMBER"] == "ABC123"


def test_ups_mcp_config_account_number_defaults_empty(monkeypatch):
    """UPS_ACCOUNT_NUMBER defaults to empty string when not set."""
    monkeypatch.setenv("UPS_CLIENT_ID", "test-id")
    monkeypatch.setenv("UPS_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("UPS_ACCOUNT_NUMBER", raising=False)
    from src.orchestrator.agent.config import get_ups_mcp_config
    config = get_ups_mcp_config()
    assert config["env"]["UPS_ACCOUNT_NUMBER"] == ""
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_config.py -k "account_number" -v`
Expected: FAIL — `UPS_ACCOUNT_NUMBER` key not in env dict

**Step 3: Write minimal implementation**

In `src/orchestrator/agent/config.py`, add `UPS_ACCOUNT_NUMBER` to the env dict at line 136:

```python
# Line 131-137: Add UPS_ACCOUNT_NUMBER
return MCPServerConfig(
    command=_get_python_command(),
    args=["-m", "ups_mcp"],
    env={
        "CLIENT_ID": client_id or "",
        "CLIENT_SECRET": client_secret or "",
        "ENVIRONMENT": environment,
        "UPS_ACCOUNT_NUMBER": os.environ.get("UPS_ACCOUNT_NUMBER", ""),
        "UPS_MCP_SPECS_DIR": specs_dir,
        "PATH": os.environ.get("PATH", ""),
    },
)
```

Also update `src/services/ups_mcp_client.py` line 117-123 to pass `UPS_ACCOUNT_NUMBER` in `_build_server_params()`:

```python
env={
    "CLIENT_ID": self._client_id,
    "CLIENT_SECRET": self._client_secret,
    "ENVIRONMENT": self._environment,
    "UPS_ACCOUNT_NUMBER": self._account_number,
    "UPS_MCP_SPECS_DIR": specs_dir,
    "PATH": os.environ.get("PATH", ""),
},
```

Update the docstring at line 90 to mention 18 tools instead of 7.

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/test_config.py -k "account_number" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/config.py src/services/ups_mcp_client.py tests/orchestrator/agent/test_config.py
git commit -m "feat: pass UPS_ACCOUNT_NUMBER to MCP subprocess env"
```

---

### Task 2: Add optional spec files to ups_specs.py

**Files:**
- Modify: `src/services/ups_specs.py:30-33`
- Test: `tests/services/test_ups_specs.py`

**Step 1: Write the failing test**

```python
# tests/services/test_ups_specs.py — add to existing or create
import os
from pathlib import Path
from unittest.mock import patch

def test_ensure_ups_specs_dir_creates_optional_specs(tmp_path):
    """Optional spec files are copied when source exists."""
    # Create source docs dir with an optional spec
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "rating.yaml").write_text("openapi: 3.0.3\ninfo:\n  title: Rating\npaths: {}")
    (docs_dir / "shipping.yaml").write_text("openapi: 3.0.3\ninfo:\n  title: Shipping\npaths: {}")
    (docs_dir / "landed_cost.yaml").write_text("openapi: 3.0.3\ninfo:\n  title: LandedCost\npaths: {}")

    runtime_dir = tmp_path / ".cache" / "ups_mcp_specs"

    with patch("src.services.ups_specs._SOURCE_DOCS_DIR", docs_dir), \
         patch("src.services.ups_specs._RUNTIME_SPECS_DIR", runtime_dir):
        from src.services.ups_specs import ensure_ups_specs_dir
        result = ensure_ups_specs_dir()

    assert (Path(result) / "LandedCost.yaml").exists()


def test_ensure_ups_specs_dir_skips_missing_optional_specs(tmp_path):
    """Missing optional spec files are silently skipped."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "rating.yaml").write_text("openapi: 3.0.3\ninfo:\n  title: Rating\npaths: {}")
    (docs_dir / "shipping.yaml").write_text("openapi: 3.0.3\ninfo:\n  title: Shipping\npaths: {}")
    # No landed_cost.yaml, paperless.yaml, etc.

    runtime_dir = tmp_path / ".cache" / "ups_mcp_specs"

    with patch("src.services.ups_specs._SOURCE_DOCS_DIR", docs_dir), \
         patch("src.services.ups_specs._RUNTIME_SPECS_DIR", runtime_dir):
        from src.services.ups_specs import ensure_ups_specs_dir
        result = ensure_ups_specs_dir()

    assert not (Path(result) / "LandedCost.yaml").exists()
    # Required specs still work
    assert (Path(result) / "Rating.yaml").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_specs.py -k "optional_specs" -v`
Expected: FAIL — `LandedCost.yaml` not created

**Step 3: Write minimal implementation**

In `src/services/ups_specs.py`, expand the mapping dict at line 30-33:

```python
mapping = {
    "Rating.yaml": _SOURCE_DOCS_DIR / "rating.yaml",
    "Shipping.yaml": _SOURCE_DOCS_DIR / "shipping.yaml",
    # Optional specs — skipped if source file doesn't exist
    "LandedCost.yaml": _SOURCE_DOCS_DIR / "landed_cost.yaml",
    "Paperless.yaml": _SOURCE_DOCS_DIR / "paperless.yaml",
    "Locator.yaml": _SOURCE_DOCS_DIR / "locator.yaml",
    "Pickup.yaml": _SOURCE_DOCS_DIR / "pickup.yaml",
}
```

The existing loop at lines 34-40 already handles missing source files with `if not source_path.exists(): continue`, so no other changes needed.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_ups_specs.py -k "optional_specs" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/ups_specs.py tests/services/test_ups_specs.py
git commit -m "feat: add optional spec file mappings for UPS MCP v2 domains"
```

---

### Task 3: Register new error codes in registry

**Files:**
- Modify: `src/errors/registry.py:204-264`
- Test: `tests/errors/test_registry.py`

**Step 1: Write the failing test**

```python
# tests/errors/test_registry.py — add to existing
import pytest
from src.errors.registry import get_error, ErrorCategory

@pytest.mark.parametrize("code,category,title", [
    ("E-2020", ErrorCategory.VALIDATION, "Missing Required Fields"),
    ("E-2021", ErrorCategory.VALIDATION, "Malformed Request Structure"),
    ("E-2022", ErrorCategory.VALIDATION, "Ambiguous Billing"),
    ("E-3007", ErrorCategory.UPS_API, "Document Not Found"),
    ("E-3008", ErrorCategory.UPS_API, "Pickup Timing Error"),
    ("E-3009", ErrorCategory.UPS_API, "No Locations Found"),
    ("E-4011", ErrorCategory.SYSTEM, "Elicitation Declined"),
    ("E-4012", ErrorCategory.SYSTEM, "Elicitation Cancelled"),
])
def test_v2_error_codes_registered(code, category, title):
    """All UPS MCP v2 error codes must be registered."""
    error = get_error(code)
    assert error is not None, f"{code} not found in registry"
    assert error.category == category
    assert error.title == title
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/errors/test_registry.py -k "v2_error_codes" -v`
Expected: FAIL — E-2020, E-2021, etc. not found

**Step 3: Write minimal implementation**

Add after line 211 in `src/errors/registry.py` (after E-3006 Customs Validation):

```python
    # UPS MCP v2 — Structured validation errors (E-2020 – E-2022)
    "E-2020": ErrorCode(
        code="E-2020",
        category=ErrorCategory.VALIDATION,
        title="Missing Required Fields",
        message_template="Missing {count} required field(s): {fields}",
        remediation="Provide the missing fields listed above. Check your data source column mapping.",
    ),
    "E-2021": ErrorCode(
        code="E-2021",
        category=ErrorCategory.VALIDATION,
        title="Malformed Request Structure",
        message_template="Request body has structural errors: {ups_message}",
        remediation="Check that the request body matches the expected UPS API format.",
    ),
    "E-2022": ErrorCode(
        code="E-2022",
        category=ErrorCategory.VALIDATION,
        title="Ambiguous Billing",
        message_template="Multiple billing objects found in ShipmentCharge. Only one payer type allowed.",
        remediation="Use exactly one of: BillShipper, BillReceiver, or BillThirdParty per charge.",
    ),
    # UPS MCP v2 — Domain-specific UPS API errors (E-3007 – E-3009)
    "E-3007": ErrorCode(
        code="E-3007",
        category=ErrorCategory.UPS_API,
        title="Document Not Found",
        message_template="Paperless document not found or expired: {ups_message}",
        remediation="The document may have expired. Re-upload the document and try again.",
    ),
    "E-3008": ErrorCode(
        code="E-3008",
        category=ErrorCategory.UPS_API,
        title="Pickup Timing Error",
        message_template="Pickup scheduling failed: {ups_message}",
        remediation="Check that the pickup date is in the future and within UPS scheduling windows.",
    ),
    "E-3009": ErrorCode(
        code="E-3009",
        category=ErrorCategory.UPS_API,
        title="No Locations Found",
        message_template="No UPS locations found for the given search criteria.",
        remediation="Try expanding the search radius or adjusting the address.",
    ),
    # UPS MCP v2 — Elicitation user actions (E-4011 – E-4012)
    "E-4011": ErrorCode(
        code="E-4011",
        category=ErrorCategory.SYSTEM,
        title="Elicitation Declined",
        message_template="User declined to provide required information.",
        remediation="The operation was cancelled because required fields were not provided.",
    ),
    "E-4012": ErrorCode(
        code="E-4012",
        category=ErrorCategory.SYSTEM,
        title="Elicitation Cancelled",
        message_template="User cancelled the operation.",
        remediation="The operation was cancelled by the user.",
    ),
```

Note: Using E-3007/E-3008/E-3009 (not E-3006 which is taken for customs) and E-4011/E-4012 (not E-4001/E-4002 which are taken for DB/FS errors).

**Step 4: Run test to verify it passes**

Run: `pytest tests/errors/test_registry.py -k "v2_error_codes" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/errors/registry.py tests/errors/test_registry.py
git commit -m "feat: register UPS MCP v2 error codes (E-2020–E-2022, E-3007–E-3009, E-4011–E-4012)"
```

---

### Task 4: Map new error codes in translation layer

**Files:**
- Modify: `src/errors/ups_translation.py:37-64`
- Modify: `src/services/ups_mcp_client.py:680-703` (reason-based routing)
- Test: `tests/errors/test_ups_translation.py`

**Step 1: Write the failing test**

```python
# tests/errors/test_ups_translation.py — add to existing
import pytest
from src.errors.ups_translation import translate_ups_error

@pytest.mark.parametrize("ups_code,expected_sa_code", [
    ("9590022", "E-3007"),
    ("190102", "E-3008"),
    ("ELICITATION_DECLINED", "E-4011"),
    ("ELICITATION_CANCELLED", "E-4012"),
])
def test_v2_error_code_mapping(ups_code, expected_sa_code):
    """New UPS MCP v2 error codes map to correct ShipAgent codes."""
    sa_code, msg, remediation = translate_ups_error(ups_code, "test error")
    assert sa_code == expected_sa_code


def test_v2_message_pattern_no_locations():
    """'no locations found' pattern maps to E-3009."""
    sa_code, msg, _ = translate_ups_error(None, "No locations found for this area")
    assert sa_code == "E-3009"


def test_v2_message_pattern_no_pdf():
    """'no pdf found' pattern maps to E-3007."""
    sa_code, msg, _ = translate_ups_error(None, "No PDF found for given documentId")
    assert sa_code == "E-3007"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/errors/test_ups_translation.py -k "v2_" -v`
Expected: FAIL — new codes not in UPS_ERROR_MAP

**Step 3: Write minimal implementation**

In `src/errors/ups_translation.py`:

Update `UPS_ERROR_MAP` (after line 44):
```python
    # UPS MCP v2 — Elicitation user actions
    "ELICITATION_DECLINED": "E-4011",   # Override: was E-2012
    "ELICITATION_CANCELLED": "E-4012",  # Override: was E-2012
    # UPS MCP v2 — Domain-specific codes
    "9590022": "E-3007",    # Paperless: document not found
    "190102": "E-3008",     # Pickup: timing error
```

Update `UPS_MESSAGE_PATTERNS` (after line 63):
```python
    "no locations found": "E-3009",
    "no pdf found": "E-3007",
```

Then update `_translate_error()` in `src/services/ups_mcp_client.py` to route `MALFORMED_REQUEST` by reason. Around line 683-685, expand the reason handling:

```python
        # Route MALFORMED_REQUEST by reason for finer error codes
        if ups_code == "MALFORMED_REQUEST":
            if reason == "ambiguous_payer":
                ups_code = "MALFORMED_REQUEST_AMBIGUOUS"
            elif reason == "malformed_structure":
                ups_code = "MALFORMED_REQUEST_STRUCTURE"
```

And add to `UPS_ERROR_MAP`:
```python
    "MALFORMED_REQUEST": "E-2021",               # Generic malformed
    "MALFORMED_REQUEST_AMBIGUOUS": "E-2022",      # Ambiguous payer
    "MALFORMED_REQUEST_STRUCTURE": "E-2021",      # Malformed structure
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/errors/test_ups_translation.py -k "v2_" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/errors/ups_translation.py src/services/ups_mcp_client.py tests/errors/test_ups_translation.py
git commit -m "feat: map UPS MCP v2 error codes in translation layer"
```

---

### Task 5: Add schedule_pickup safety hook

**Files:**
- Modify: `src/orchestrator/agent/hooks.py:464-505`
- Test: `tests/orchestrator/agent/test_hooks.py`

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/test_hooks.py — add to existing
import pytest
from src.orchestrator.agent.hooks import create_hook_matchers

def test_schedule_pickup_hook_matcher_exists():
    """Hook matchers must include mcp__ups__schedule_pickup."""
    matchers = create_hook_matchers(interactive_shipping=False)
    pre_matchers = matchers["PreToolUse"]
    pickup_matchers = [m for m in pre_matchers if m.matcher == "mcp__ups__schedule_pickup"]
    assert len(pickup_matchers) == 1, "Missing schedule_pickup hook matcher"


@pytest.mark.asyncio
async def test_schedule_pickup_hook_validates_required_fields():
    """schedule_pickup hook denies when pickup_date is missing."""
    matchers = create_hook_matchers(interactive_shipping=False)
    pre_matchers = matchers["PreToolUse"]
    pickup_matcher = [m for m in pre_matchers if m.matcher == "mcp__ups__schedule_pickup"][0]
    hook = pickup_matcher.hooks[0]

    result = await hook(
        {"tool_name": "mcp__ups__schedule_pickup", "tool_input": {}},
        "test-id",
        None,
    )
    # Should deny — missing required fields
    assert result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


@pytest.mark.asyncio
async def test_schedule_pickup_hook_allows_valid_input():
    """schedule_pickup hook allows when required fields present."""
    matchers = create_hook_matchers(interactive_shipping=False)
    pre_matchers = matchers["PreToolUse"]
    pickup_matcher = [m for m in pre_matchers if m.matcher == "mcp__ups__schedule_pickup"][0]
    hook = pickup_matcher.hooks[0]

    result = await hook(
        {
            "tool_name": "mcp__ups__schedule_pickup",
            "tool_input": {
                "pickup_date": "20260220",
                "ready_time": "0900",
                "close_time": "1700",
                "address_line": "123 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country_code": "US",
                "contact_name": "John Smith",
                "phone_number": "5125551234",
            },
        },
        "test-id",
        None,
    )
    assert result == {}  # Allowed
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_hooks.py -k "schedule_pickup" -v`
Expected: FAIL — no schedule_pickup matcher

**Step 3: Write minimal implementation**

Add to `src/orchestrator/agent/hooks.py` — new validator function (before `create_hook_matchers()`):

```python
async def validate_schedule_pickup(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    """Validate schedule_pickup inputs before execution.

    Checks for required fields: pickup_date, ready_time, close_time,
    address_line, city, state, postal_code, country_code, contact_name,
    phone_number. Denies if critical fields are missing.

    Args:
        input_data: Contains 'tool_name' and 'tool_input' keys.
        tool_use_id: Unique identifier for this tool use.
        context: Hook context from Claude Agent SDK.

    Returns:
        Empty dict to allow, or hookSpecificOutput with denial to block.
    """
    tool_input = input_data.get("tool_input", {})
    _log_to_stderr(
        f"[VALIDATION] Pre-hook checking: schedule_pickup | ID: {tool_use_id}"
    )

    required = [
        "pickup_date", "ready_time", "close_time",
        "address_line", "city", "state", "postal_code", "country_code",
        "contact_name", "phone_number",
    ]
    missing = [f for f in required if not tool_input.get(f)]
    if missing:
        return _deny_with_reason(
            f"Missing required pickup fields: {', '.join(missing)}. "
            "Collect these details from the user before scheduling."
        )
    return {}
```

Update `create_hook_matchers()` at line 484 to add the new matcher:

```python
    return {
        "PreToolUse": [
            HookMatcher(
                matcher="mcp__ups__create_shipment",
                hooks=[shipping_hook],
            ),
            HookMatcher(
                matcher="mcp__ups__void_shipment",
                hooks=[validate_void_shipment],
            ),
            HookMatcher(
                matcher="mcp__ups__schedule_pickup",
                hooks=[validate_schedule_pickup],
            ),
            HookMatcher(
                matcher=None,
                hooks=[validate_pre_tool],
            ),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher=None,
                hooks=[log_post_tool, detect_error_response],
            ),
        ],
    }
```

Add `validate_schedule_pickup` to `__all__`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/test_hooks.py -k "schedule_pickup" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/hooks.py tests/orchestrator/agent/test_hooks.py
git commit -m "feat: add schedule_pickup safety gate hook"
```

---

### Task 6: Update system prompt with new domain workflows

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py:326-351`
- Test: `tests/orchestrator/agent/test_system_prompt.py`

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/test_system_prompt.py — add to existing
from src.orchestrator.agent.system_prompt import build_system_prompt

def test_system_prompt_includes_pickup_guidance():
    """System prompt must include pickup scheduling workflow."""
    prompt = build_system_prompt()
    assert "Pickup" in prompt
    assert "schedule_pickup" in prompt or "Schedule Pickup" in prompt
    assert "PRN" in prompt  # Pickup Request Number


def test_system_prompt_includes_locator_guidance():
    """System prompt must include location finder guidance."""
    prompt = build_system_prompt()
    assert "find_locations" in prompt or "Location" in prompt
    assert "Access Point" in prompt or "access_point" in prompt


def test_system_prompt_includes_landed_cost_guidance():
    """System prompt must include landed cost estimation guidance."""
    prompt = build_system_prompt()
    assert "Landed Cost" in prompt or "landed_cost" in prompt
    assert "duties" in prompt.lower()


def test_system_prompt_includes_paperless_guidance():
    """System prompt must include paperless document workflow."""
    prompt = build_system_prompt()
    assert "Paperless" in prompt or "paperless" in prompt
    assert "DocumentID" in prompt or "document_id" in prompt


def test_system_prompt_includes_political_divisions():
    """System prompt must mention political divisions reference tool."""
    prompt = build_system_prompt()
    assert "political_divisions" in prompt or "Political Divisions" in prompt


def test_system_prompt_interactive_mode_includes_new_domains():
    """Interactive mode prompt also includes new domain guidance."""
    prompt = build_system_prompt(interactive_shipping=True)
    assert "Pickup" in prompt
    assert "Landed Cost" in prompt or "landed_cost" in prompt
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_system_prompt.py -k "test_system_prompt_includes" -v`
Expected: FAIL — new domain sections missing

**Step 3: Write minimal implementation**

In `src/orchestrator/agent/system_prompt.py`, add new domain sections before the return statement at line 326. Insert a new `ups_capabilities_section` variable built from the new domain guidance:

```python
    # UPS MCP v2 — Additional capabilities (both modes)
    ups_v2_section = """
## UPS Pickup Scheduling

- Use `rate_pickup` to estimate pickup cost BEFORE scheduling
- Use `schedule_pickup` to book a carrier pickup — this is a FINANCIAL COMMITMENT, always confirm with the user first
- Capture the PRN (Pickup Request Number) from the response — needed for cancellation
- Use `cancel_pickup` with the PRN to cancel a scheduled pickup
- Use `get_pickup_status` to check pending pickups for the account
- After batch execution completes with successful shipments, SUGGEST scheduling a pickup
- Use `get_service_center_facilities` to suggest drop-off alternatives when pickup is not suitable
- Pickup date format: YYYYMMDD. Times: HHMM (24-hour). ready_time must be before close_time.

## UPS Location Finder

- Use `find_locations` to find nearby UPS Access Points, retail stores, and service centers
- Supports 4 location types: access_point, retail, general, services
- Default search radius: 15 miles (configurable with radius and unit_of_measure)
- Present results with address, phone, and operating hours

## Landed Cost (International)

- Use `get_landed_cost_quote` to estimate duties, taxes, and fees for international shipments
- Required: currency_code, export_country_code, import_country_code, commodities list
- Each commodity needs at minimum: price, quantity. HS code (hs_code) recommended for accuracy
- Present per-commodity breakdown: duties, taxes, fees + total landed cost

## Paperless Customs Documents

- Use `upload_paperless_document` to upload customs/trade documents (PDF, DOC, XLS, etc.)
- Document type codes: "002" (commercial invoice), "003" (certificate of origin), "011" (packing list)
- After upload, capture the DocumentID from the response
- Use `push_document_to_shipment` to attach a document to a shipment using the tracking number
- Use `delete_paperless_document` to remove a document from UPS Forms History
- Chained workflow: upload document → create shipment → push document to shipment

## Reference Data

- Use `get_political_divisions` to look up valid states/provinces for any country code
- Useful when validating user-provided international addresses
"""
```

Insert this into the return string between `{international_section}` and the `## Connected Data Source` heading.

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/test_system_prompt.py -k "test_system_prompt_includes" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_system_prompt.py
git commit -m "feat: add UPS MCP v2 domain workflow guidance to system prompt"
```

---

### Task 7: Update .env.example

**Files:**
- Modify: `.env.example`

**Step 1: No test needed for docs-only change**

**Step 2: Update .env.example**

Add/update the `UPS_ACCOUNT_NUMBER` entry to clarify it's now recommended:

```bash
# UPS Account Number — recommended for pickup scheduling, paperless docs,
# landed cost quotes, and shipment billing. Falls back to empty if not set.
UPS_ACCOUNT_NUMBER=your_account_number
```

**Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: document UPS_ACCOUNT_NUMBER as recommended in .env.example"
```

---

## Phase 2: Batch Integration

### Task 8: Add pickup methods to UPSMCPClient

**Files:**
- Modify: `src/services/ups_mcp_client.py` (after line 284, before internal helpers)
- Test: `tests/services/test_ups_mcp_client.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_ups_mcp_client.py — add pickup tests
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_schedule_pickup_calls_correct_tool(ups_client):
    """schedule_pickup must call MCP tool 'schedule_pickup'."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PickupCreationResponse": {"PRN": "2929602E9CP"}
    })
    result = await ups_client.schedule_pickup(
        pickup_date="20260220", ready_time="0900", close_time="1700",
        address_line="123 Main St", city="Austin", state="TX",
        postal_code="78701", country_code="US",
        contact_name="John Smith", phone_number="5125551234",
    )
    assert result["success"] is True
    assert result["prn"] == "2929602E9CP"
    ups_client._mcp.call_tool.assert_called_once()
    call_args = ups_client._mcp.call_tool.call_args
    assert call_args[0][0] == "schedule_pickup"


@pytest.mark.asyncio
async def test_cancel_pickup_by_prn(ups_client):
    """cancel_pickup with PRN calls correct tool."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PickupCancelResponse": {"Status": {"Code": "1"}}
    })
    result = await ups_client.cancel_pickup(cancel_by="prn", prn="2929602E9CP")
    assert result["success"] is True
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_rate_pickup_returns_charges(ups_client):
    """rate_pickup returns estimated charges."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PickupRateResponse": {
            "RateResult": {
                "ChargeDetail": [{"ChargeAmount": "5.50", "ChargeCode": "C"}],
                "GrandTotalOfAllCharge": "5.50",
            }
        }
    })
    result = await ups_client.rate_pickup(
        pickup_type="oncall", address_line="123 Main", city="Austin",
        state="TX", postal_code="78701", country_code="US",
        pickup_date="20260220", ready_time="0900", close_time="1700",
    )
    assert result["success"] is True
    assert "charges" in result


@pytest.mark.asyncio
async def test_get_pickup_status(ups_client):
    """get_pickup_status returns pending pickups."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PickupPendingStatusResponse": {
            "PendingStatus": [{"PickupDate": "20260220", "PRN": "ABC123"}]
        }
    })
    result = await ups_client.get_pickup_status(pickup_type="oncall")
    assert result["success"] is True
    assert "pickups" in result


@pytest.mark.asyncio
async def test_schedule_pickup_retry_policy(ups_client):
    """schedule_pickup must NOT retry (mutating operation)."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PickupCreationResponse": {"PRN": "TEST"}
    })
    await ups_client.schedule_pickup(
        pickup_date="20260220", ready_time="0900", close_time="1700",
        address_line="123 Main", city="Austin", state="TX",
        postal_code="78701", country_code="US",
        contact_name="John", phone_number="5125551234",
    )
    call_kwargs = ups_client._mcp.call_tool.call_args[1]
    assert call_kwargs["max_retries"] == 0


@pytest.mark.asyncio
async def test_rate_pickup_retry_policy(ups_client):
    """rate_pickup uses read-only retry policy."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PickupRateResponse": {"RateResult": {"GrandTotalOfAllCharge": "5.50"}}
    })
    await ups_client.rate_pickup(
        pickup_type="oncall", address_line="123", city="Austin",
        state="TX", postal_code="78701", country_code="US",
        pickup_date="20260220", ready_time="0900", close_time="1700",
    )
    call_kwargs = ups_client._mcp.call_tool.call_args[1]
    assert call_kwargs["max_retries"] == 2
```

Note: The `ups_client` fixture should be defined in conftest.py or at top of file — a connected UPSMCPClient with mocked `_mcp`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_mcp_client.py -k "pickup" -v`
Expected: FAIL — methods don't exist

**Step 3: Write minimal implementation**

Add 4 public methods and 4 normalizers to `src/services/ups_mcp_client.py`. Also update `_call()` at line 309 to include new read-only tools in the fast-retry set:

```python
# Update line 309:
if tool_name in {
    "rate_shipment", "validate_address", "track_package",
    "rate_pickup", "get_pickup_status", "get_landed_cost_quote",
    "find_locations", "get_political_divisions", "get_service_center_facilities",
}:
```

And update lines 321, 333-334 to include new mutating tools:

```python
# Update line 321:
if (
    tool_name in {"create_shipment", "void_shipment", "schedule_pickup", "cancel_pickup",
                   "upload_paperless_document", "push_document_to_shipment", "delete_paperless_document"}
    and self._is_safe_mutating_retry_error(e.error_text)
):
```

```python
# Update line 333:
is_non_mutating = tool_name in {
    "rate_shipment", "validate_address", "track_package",
    "rate_pickup", "get_pickup_status", "get_landed_cost_quote",
    "find_locations", "get_political_divisions", "get_service_center_facilities",
}
```

The 4 pickup methods follow the existing pattern (see `void_shipment` for mutating, `validate_address` for read-only). Full method code is in the design doc section 3.1.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_ups_mcp_client.py -k "pickup" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "feat: add pickup methods to UPSMCPClient (schedule, cancel, rate, status)"
```

---

### Task 9: Add landed cost + paperless methods to UPSMCPClient

**Files:**
- Modify: `src/services/ups_mcp_client.py`
- Test: `tests/services/test_ups_mcp_client.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_ups_mcp_client.py — add landed cost + paperless tests
@pytest.mark.asyncio
async def test_get_landed_cost(ups_client):
    """get_landed_cost returns duty/tax breakdown."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "LandedCostResponse": {
            "shipment": {
                "totalLandedCost": "45.23",
                "currencyCode": "USD",
                "shipmentItems": [
                    {"commodityId": "1", "duties": "12.50", "taxes": "7.73", "fees": "0.00"}
                ],
            }
        }
    })
    result = await ups_client.get_landed_cost(
        currency_code="USD", export_country_code="US",
        import_country_code="GB",
        commodities=[{"price": 25.00, "quantity": 2}],
    )
    assert result["success"] is True
    assert result["totalLandedCost"] == "45.23"
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_upload_document(ups_client):
    """upload_document returns DocumentID."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "UploadResponse": {
            "FormsHistoryDocumentID": {"DocumentID": "2013-12-04-00.15.33.207814"}
        }
    })
    result = await ups_client.upload_document(
        file_content_base64="dGVzdA==", file_name="invoice.pdf",
        file_format="pdf", document_type="002",
    )
    assert result["success"] is True
    assert result["documentId"] == "2013-12-04-00.15.33.207814"


@pytest.mark.asyncio
async def test_push_document(ups_client):
    """push_document links document to shipment."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "PushToImageRepositoryResponse": {"FormsHistoryDocumentID": {"DocumentID": "TEST"}}
    })
    result = await ups_client.push_document(
        document_id="TEST", shipment_identifier="1Z123",
    )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_delete_document(ups_client):
    """delete_document removes from Forms History."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "DeleteResponse": {"Status": "Success"}
    })
    result = await ups_client.delete_document(document_id="TEST")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_upload_document_no_retry(ups_client):
    """upload_document must NOT retry (mutating)."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "UploadResponse": {"FormsHistoryDocumentID": {"DocumentID": "T"}}
    })
    await ups_client.upload_document(
        file_content_base64="dGVzdA==", file_name="test.pdf",
        file_format="pdf", document_type="002",
    )
    call_kwargs = ups_client._mcp.call_tool.call_args[1]
    assert call_kwargs["max_retries"] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_mcp_client.py -k "landed_cost or document" -v`
Expected: FAIL — methods don't exist

**Step 3: Write minimal implementation**

Add 4 public methods + 4 normalizers following the same pattern as Task 8.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_ups_mcp_client.py -k "landed_cost or document" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "feat: add landed cost + paperless methods to UPSMCPClient"
```

---

### Task 10: Create pickup agent tool handlers

**Files:**
- Create: `src/orchestrator/agent/tools/pickup.py`
- Test: `tests/orchestrator/agent/tools/test_pickup.py`

**Step 1: Write the failing tests**

```python
# tests/orchestrator/agent/tools/test_pickup.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_schedule_pickup_tool_success():
    """schedule_pickup_tool returns PRN on success."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "ABC123"}

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool
        result = await schedule_pickup_tool(
            pickup_date="20260220", ready_time="0900", close_time="1700",
            address_line="123 Main", city="Austin", state="TX",
            postal_code="78701", country_code="US",
            contact_name="John", phone_number="5125551234",
        )
    assert result["status"] == "ok"
    assert result["prn"] == "ABC123"


@pytest.mark.asyncio
async def test_schedule_pickup_tool_error():
    """schedule_pickup_tool returns error on failure."""
    from src.services.errors import UPSServiceError
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.side_effect = UPSServiceError(code="E-3008", message="timing error")

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool
        result = await schedule_pickup_tool(
            pickup_date="20260220", ready_time="0900", close_time="1700",
            address_line="123 Main", city="Austin", state="TX",
            postal_code="78701", country_code="US",
            contact_name="John", phone_number="5125551234",
        )
    assert result["status"] == "error"
    assert "E-3008" in result["code"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/tools/test_pickup.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Write minimal implementation**

Create `src/orchestrator/agent/tools/pickup.py` with 4 handler functions following the pattern in `pipeline.py`. Each handler:
1. Gets the UPSMCPClient via `_get_ups_client()` (from `core.py`)
2. Calls the appropriate client method
3. Returns `_ok(result)` on success
4. Catches `UPSServiceError` and returns `_err(code, message, remediation)`

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/tools/test_pickup.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/pickup.py tests/orchestrator/agent/tools/test_pickup.py
git commit -m "feat: add pickup agent tool handlers"
```

---

### Task 11: Create paperless document agent tool handlers

**Files:**
- Create: `src/orchestrator/agent/tools/documents.py`
- Test: `tests/orchestrator/agent/tools/test_documents.py`

Same pattern as Task 10 but for upload_paperless_document_tool, push_document_to_shipment_tool, delete_paperless_document_tool.

**Step 1–5:** Follow the same TDD cycle as Task 10.

**Commit:**
```bash
git add src/orchestrator/agent/tools/documents.py tests/orchestrator/agent/tools/test_documents.py
git commit -m "feat: add paperless document agent tool handlers"
```

---

### Task 12: Add landed cost tool handler to pipeline

**Files:**
- Modify: `src/orchestrator/agent/tools/pipeline.py`
- Test: `tests/orchestrator/agent/tools/test_pipeline.py`

Add `get_landed_cost_tool` handler to the existing pipeline module. Same TDD pattern.

**Commit:**
```bash
git add src/orchestrator/agent/tools/pipeline.py tests/orchestrator/agent/tools/test_pipeline.py
git commit -m "feat: add landed cost tool handler to pipeline module"
```

---

### Task 13: Register all new tools in __init__.py

**Files:**
- Modify: `src/orchestrator/agent/tools/__init__.py:19-38` (imports), `53-280` (definitions)
- Test: `tests/orchestrator/agent/tools/test_init.py`

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/tools/test_init.py — add to existing
from src.orchestrator.agent.tools import get_all_tool_definitions

def test_v2_tools_registered_batch_mode():
    """All UPS MCP v2 tool definitions appear in batch mode."""
    defs = get_all_tool_definitions()
    names = {d["name"] for d in defs}
    expected_v2 = {
        "schedule_pickup", "cancel_pickup", "rate_pickup", "get_pickup_status",
        "upload_paperless_document", "push_document_to_shipment", "delete_paperless_document",
        "get_landed_cost",
    }
    assert expected_v2.issubset(names), f"Missing: {expected_v2 - names}"


def test_v2_tools_registered_interactive_mode():
    """UPS MCP v2 tools also available in interactive mode."""
    defs = get_all_tool_definitions(interactive_shipping=True)
    names = {d["name"] for d in defs}
    # Pickup and landed cost should be in interactive mode
    assert "schedule_pickup" in names
    assert "get_landed_cost" in names
```

**Step 2–5:** Add imports from `pickup.py` and `documents.py`, add 8 tool definitions to the `definitions` list, each with name, description, input_schema, and handler. Ensure they're included in both interactive and batch modes.

**Commit:**
```bash
git add src/orchestrator/agent/tools/__init__.py tests/orchestrator/agent/tools/test_init.py
git commit -m "feat: register 8 UPS MCP v2 tools in agent tool registry"
```

---

## Phase 3: Frontend

### Task 14: Add domain color system to CSS

**Files:**
- Modify: `frontend/src/index.css`

Add OKLCH domain color variables and utility classes. No automated test — visual verification.

**Commit:**
```bash
git add frontend/src/index.css
git commit -m "feat: add domain-specific OKLCH colors for pickup, locator, paperless, landed cost"
```

---

### Task 15: Add new TypeScript types

**Files:**
- Modify: `frontend/src/types/api.ts`

Add `PickupResult`, `LocationResult`, `LandedCostResult`, `PaperlessResult` interfaces as specified in the design doc.

**Commit:**
```bash
git add frontend/src/types/api.ts
git commit -m "feat: add TypeScript types for UPS MCP v2 tool results"
```

---

### Task 16: Create PickupCard component

**Files:**
- Create: `frontend/src/components/command-center/PickupCard.tsx`

Renders 4 variants (rate, schedule, cancel, status) with purple domain borders.

**Commit:**
```bash
git add frontend/src/components/command-center/PickupCard.tsx
git commit -m "feat: add PickupCard component with domain-colored variants"
```

---

### Task 17: Create LocationCard component

**Files:**
- Create: `frontend/src/components/command-center/LocationCard.tsx`

Renders location search results with teal domain border.

**Commit:**
```bash
git add frontend/src/components/command-center/LocationCard.tsx
git commit -m "feat: add LocationCard component for UPS location search results"
```

---

### Task 18: Create LandedCostCard component

**Files:**
- Create: `frontend/src/components/command-center/LandedCostCard.tsx`

Renders duty/tax breakdown with indigo domain border.

**Commit:**
```bash
git add frontend/src/components/command-center/LandedCostCard.tsx
git commit -m "feat: add LandedCostCard component for international cost breakdown"
```

---

### Task 19: Create PaperlessCard component

**Files:**
- Create: `frontend/src/components/command-center/PaperlessCard.tsx`

Renders document operation results with amber domain border.

**Commit:**
```bash
git add frontend/src/components/command-center/PaperlessCard.tsx
git commit -m "feat: add PaperlessCard component for paperless document operations"
```

---

### Task 20: Wire SSE event routing + CompletionArtifact pickup button

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx`
- Modify: `frontend/src/components/command-center/CompletionArtifact.tsx`

Add routing for `pickup_result`, `location_result`, `landed_cost_result`, `paperless_result`, `pickup_available` events. Add "Schedule Pickup" button to CompletionArtifact.

**Commit:**
```bash
git add frontend/src/components/CommandCenter.tsx frontend/src/components/command-center/CompletionArtifact.tsx
git commit -m "feat: wire UPS MCP v2 event routing and pickup button in CompletionArtifact"
```

---

### Task 21: Update documentation

**Files:**
- Modify: `docs/ups-mcp-integration-guide.md`
- Modify: `CLAUDE.md`

Update the integration guide tool inventory table from 7 to 18 tools. Update CLAUDE.md project status and tool counts.

**Commit:**
```bash
git add docs/ups-mcp-integration-guide.md CLAUDE.md
git commit -m "docs: update integration guide and CLAUDE.md for UPS MCP v2 (18 tools)"
```
