# UPS MCP v2 Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate 11 new UPS MCP tools (18 total) into ShipAgent across backend foundation, batch wrapping, and frontend card components.

**Architecture:** Three-phase layered rollout. Phase 1 updates config, specs, error codes, system prompt, and hooks to enable all new tools interactively via MCP auto-discovery. Phase 2 wraps batch-eligible tools in UPSMCPClient with normalizers and registers deterministic agent tools. Phase 3 adds domain-colored card components to the frontend with explicit event producers.

**Tech Stack:** Python (FastAPI, Claude Agent SDK), TypeScript (React, Tailwind CSS v4, OKLCH colors)

**Design Doc:** `docs/plans/2026-02-15-ups-mcp-v2-integration-design.md`
**UPS MCP Integration Guide:** `docs/ups-mcp-integration-guide.md`

---

## Architecture Decisions (AD)

These decisions resolve ambiguities identified during plan review. Each is referenced by tasks that depend on it.

### AD-1: Interactive Mode Exposure Model → `interactive-exclusive`

**Decision:** The interactive mode tool registry keeps its existing 3-tool contract: `{get_job_status, get_platform_status, preview_interactive_shipment}`. New v2 orchestrator tools (`schedule_pickup`, `rate_pickup`, `get_landed_cost`, etc.) are registered in **batch mode only**.

**Rationale:** The interactive mode's purpose is ad-hoc single-shipment creation. Its 3-tool limit is structural enforcement (not a bug). The agent in interactive mode can still access new UPS capabilities directly via MCP auto-discovery (`mcp__ups__schedule_pickup`, `mcp__ups__find_locations`, etc.) — the SDK exposes all MCP tools regardless of orchestrator tool filtering. Orchestrator-level tool handlers (which wrap UPSMCPClient for batch processing) don't belong in interactive mode.

**Impact:**
- `get_all_tool_definitions(interactive_shipping=True)` continues to return exactly 3 tools
- Existing test `test_tool_definitions_filtered_for_interactive_mode` (line 840) remains unchanged
- System prompt updates (Task 6) guide the agent to use MCP tools directly in interactive mode
- No changes to `tools/__init__.py` interactive filtering logic

### AD-2: Event Producer Contract → Explicit Bridge Emission

**Decision:** Each new tool handler that produces frontend-visible results MUST emit a typed event via `_emit_event()` through the `EventEmitterBridge`, following the established `preview_ready` pattern. The event type string and payload schema are defined in a contract matrix below.

**Event Contract Matrix:**

| Event Type | Producer File:Function | Trigger | Payload Schema |
|------------|----------------------|---------|----------------|
| `pickup_result` | `tools/pickup.py:schedule_pickup_tool` | After successful `UPSMCPClient.schedule_pickup()` | `{action: "scheduled"\|"cancelled"\|"rated"\|"status", prn?: str, charges?: list, pickups?: list, success: bool}` |
| `location_result` | `tools/pickup.py:find_locations_tool` | After successful `UPSMCPClient.find_locations()` | `{locations: list[{id, address, phone, hours}], search_type: str, radius: float}` |
| `landed_cost_result` | `tools/pipeline.py:get_landed_cost_tool` | After successful `UPSMCPClient.get_landed_cost()` | `{totalLandedCost: str, currencyCode: str, items: list[{commodityId, duties, taxes, fees}]}` |
| `paperless_result` | `tools/documents.py:upload_paperless_document_tool` | After successful upload/push/delete | `{action: "uploaded"\|"pushed"\|"deleted", documentId?: str, success: bool}` |

Each emission follows the same pattern as `_emit_preview_ready()` (`core.py:341-362`):
1. Call `_emit_event(event_type, payload, bridge=bridge)` to send to SSE queue
2. Return `_ok({...slim_payload...})` to send to the LLM (slim version without large arrays)

### AD-3: Tool Naming Convention → Canonical Name Matrix

**Decision:** Every tool has exactly one canonical name per layer. No aliases. All plan references use these exact names.

| MCP Tool (SDK auto-discovery) | UPSMCPClient Method | Orchestrator Tool (agent tool registry) | SSE Event Type |
|-------------------------------|--------------------|-----------------------------------------|----------------|
| `mcp__ups__rate_pickup` | `rate_pickup()` | `rate_pickup` | `pickup_result` |
| `mcp__ups__schedule_pickup` | `schedule_pickup()` | `schedule_pickup` | `pickup_result` |
| `mcp__ups__cancel_pickup` | `cancel_pickup()` | `cancel_pickup` | `pickup_result` |
| `mcp__ups__get_pickup_status` | `get_pickup_status()` | `get_pickup_status` | `pickup_result` |
| `mcp__ups__find_locations` | `find_locations()` | `find_locations` | `location_result` |
| `mcp__ups__get_landed_cost_quote` | `get_landed_cost()` | `get_landed_cost` | `landed_cost_result` |
| `mcp__ups__upload_paperless_document` | `upload_document()` | `upload_paperless_document` | `paperless_result` |
| `mcp__ups__push_document_to_shipment` | `push_document()` | `push_document_to_shipment` | `paperless_result` |
| `mcp__ups__delete_paperless_document` | `delete_document()` | `delete_paperless_document` | `paperless_result` |
| `mcp__ups__get_political_divisions` | — (interactive only) | — | — |
| `mcp__ups__get_service_center_facilities` | `get_service_center_facilities()` | `get_service_center_facilities` | `location_result` |

### AD-4: Tool Response Envelope → `_ok()` / `_err()` Only

**Decision:** All new tool handlers MUST return via `_ok(data)` or `_err(message)` from `core.py:108-135`. This produces the MCP envelope format `{"isError": bool, "content": [{"type": "text", "text": "..."}]}`. Tests assert against this envelope, not against raw dicts.

**Existing test pattern** (test_tools_v2.py:64):
```python
assert result["isError"] is False
data = json.loads(result["content"][0]["text"])
assert data["source_type"] == "csv"
```

All new tests follow this pattern exactly.

### AD-5: Safety Hook Namespace Clarification

**Decision:** The `validate_schedule_pickup` hook targets the **MCP tool** name `mcp__ups__schedule_pickup` (which the agent calls in interactive mode via MCP auto-discovery). The deterministic orchestrator tool `schedule_pickup` (registered in `tools/__init__.py`) does NOT need a hook because it goes through `UPSMCPClient` which already validates inputs programmatically.

Both namespaces are covered:
- MCP path (interactive): Hook on `mcp__ups__schedule_pickup` blocks calls without required fields
- Orchestrator path (batch): `UPSMCPClient.schedule_pickup()` validates programmatically; tool handler catches `UPSServiceError`

### AD-6: Error Code Migration Strategy

**Decision:** Remap `ELICITATION_DECLINED` from `E-2012` → `E-4011` and `ELICITATION_CANCELLED` from `E-2012` → `E-4012`. This is a deliberate semantic correction: these are user-action outcomes (SYSTEM category), not validation errors (VALIDATION category).

**Breaking tests to update (4 total):**
1. `tests/errors/test_ups_translation.py:46` — `assert code == "E-2012"` → `assert code == "E-4011"`
2. `tests/errors/test_ups_translation.py:54` — `assert code == "E-2012"` → `assert code == "E-4012"`
3. `tests/errors/test_ups_translation.py:96` — Update to use `ELICITATION_DECLINED` → `E-4011` context
4. `tests/services/test_ups_mcp_client.py:499` — `assert exc_info.value.code == "E-2012"` → `assert exc_info.value.code == "E-4012"`

**E-2012 definition is preserved** in registry.py — it may still be used for other cancelled-operation contexts. No definition is deleted.

### AD-7: Test File Organization → Centralized

**Decision:** New tool handler tests go into the existing `tests/orchestrator/agent/test_tools_v2.py` file, not into new files under `tests/orchestrator/agent/tools/`. This matches the current repo convention where all tool tests are centralized in one file.

New tests are added as clearly delimited sections:
```python
# ---------------------------------------------------------------------------
# UPS MCP v2 — Pickup tool handlers
# ---------------------------------------------------------------------------
```

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

### Task 4: Map new error codes in translation layer + migrate existing tests

**Depends on:** Task 3
**Resolves:** Finding 5 (error code migration impact)

**Files:**
- Modify: `src/errors/ups_translation.py:37-64`
- Modify: `src/services/ups_mcp_client.py:680-703` (reason-based routing)
- Modify: `tests/errors/test_ups_translation.py:40-96` (migrate 3 existing tests)
- Modify: `tests/services/test_ups_mcp_client.py:485-499` (migrate 1 existing test)
- Test: `tests/errors/test_ups_translation.py` (new v2 tests)

**Step 1: Migrate existing tests first (AD-6 breaking changes)**

Update 4 existing tests that assert `E-2012` for elicitation codes:

```python
# tests/errors/test_ups_translation.py — MODIFY existing tests

# Line 40-46: Change E-2012 → E-4011
def test_elicitation_declined_maps_to_e4011(self):
    """ELICITATION_DECLINED -> E-4011 (user action, not validation)."""
    code, msg, _ = translate_ups_error(
        "ELICITATION_DECLINED",
        "User declined the form",
    )
    assert code == "E-4011"

# Line 48-54: Change E-2012 → E-4012
def test_elicitation_cancelled_maps_to_e4012(self):
    """ELICITATION_CANCELLED -> E-4012 (user action, not validation)."""
    code, _, _ = translate_ups_error(
        "ELICITATION_CANCELLED",
        "User cancelled the form",
    )
    assert code == "E-4012"

# Line 90-96: Update to use E-4011 context
def test_e4011_template_with_ups_message(self):
    """E-4011 message template reflects user decline."""
    _, msg, _ = translate_ups_error(
        "ELICITATION_DECLINED",
        "User declined the form",
    )
    assert "declined" in msg.lower() or "cancelled" in msg.lower()
```

```python
# tests/services/test_ups_mcp_client.py — MODIFY existing test

# Line 485-499: Change E-2012 → E-4012
@pytest.mark.asyncio
async def test_elicitation_cancelled_maps_to_e4012(self, ups_client, mock_mcp_client):
    """ELICITATION_CANCELLED -> E-4012."""
    mock_mcp_client.call_tool.side_effect = MCPToolError(
        tool_name="create_shipment",
        error_text=json.dumps({
            "code": "ELICITATION_CANCELLED",
            "message": "User cancelled the form",
            "missing": [],
        }),
    )

    with pytest.raises(UPSServiceError) as exc_info:
        await ups_client.create_shipment(request_body={})

    assert exc_info.value.code == "E-4012"
```

**Step 2: Write the new v2 failing tests**

```python
# tests/errors/test_ups_translation.py — add NEW tests
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


def test_v2_malformed_request_ambiguous_payer():
    """MALFORMED_REQUEST with reason 'ambiguous_payer' maps to E-2022."""
    # The _translate_error in ups_mcp_client routes by reason before calling translate_ups_error.
    # Test the synthetic code that _translate_error generates.
    sa_code, _, _ = translate_ups_error("MALFORMED_REQUEST_AMBIGUOUS", "ambiguous payer")
    assert sa_code == "E-2022"


def test_v2_malformed_request_structure():
    """MALFORMED_REQUEST with reason 'malformed_structure' maps to E-2021."""
    sa_code, _, _ = translate_ups_error("MALFORMED_REQUEST_STRUCTURE", "bad structure")
    assert sa_code == "E-2021"
```

**Step 3: Run all tests to verify — migrated tests fail (code still maps to E-2012), new tests fail (codes not mapped)**

Run: `pytest tests/errors/test_ups_translation.py tests/services/test_ups_mcp_client.py -k "elicitation or v2_" -v`
Expected: FAIL on all

**Step 4: Write implementation**

In `src/errors/ups_translation.py`:

Update `UPS_ERROR_MAP` — change existing entries and add new ones:
```python
    # UPS MCP v2 — Elicitation user actions (migrated from E-2012)
    "ELICITATION_DECLINED": "E-4011",
    "ELICITATION_CANCELLED": "E-4012",
    # UPS MCP v2 — Domain-specific codes
    "9590022": "E-3007",    # Paperless: document not found
    "190102": "E-3008",     # Pickup: timing error
    # UPS MCP v2 — MALFORMED_REQUEST reason-based routing (synthetic codes from _translate_error)
    "MALFORMED_REQUEST": "E-2021",               # Generic malformed
    "MALFORMED_REQUEST_AMBIGUOUS": "E-2022",      # Ambiguous payer
    "MALFORMED_REQUEST_STRUCTURE": "E-2021",      # Malformed structure
```

Update `UPS_MESSAGE_PATTERNS`:
```python
    "no locations found": "E-3009",
    "no pdf found": "E-3007",
```

Then update `_translate_error()` in `src/services/ups_mcp_client.py` to route `MALFORMED_REQUEST` by reason. Around line 683-685, expand the reason handling:

```python
        # Route MALFORMED_REQUEST by reason for finer error codes
        if ups_code == "MALFORMED_REQUEST":
            reason = parsed.get("reason", "")
            if reason == "ambiguous_payer":
                ups_code = "MALFORMED_REQUEST_AMBIGUOUS"
            elif reason == "malformed_structure":
                ups_code = "MALFORMED_REQUEST_STRUCTURE"
```

**Step 5: Run all tests to verify they pass**

Run: `pytest tests/errors/test_ups_translation.py tests/services/test_ups_mcp_client.py -k "elicitation or v2_" -v`
Expected: ALL PASS

**Step 6: Run full test suite to verify no regressions**

Run: `pytest tests/errors/ tests/services/test_ups_mcp_client.py -v -k "not stream and not sse"`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add src/errors/ups_translation.py src/services/ups_mcp_client.py tests/errors/test_ups_translation.py tests/services/test_ups_mcp_client.py
git commit -m "feat: map UPS MCP v2 error codes + migrate elicitation codes from E-2012 to E-4011/E-4012"
```

---

### Task 5: Add schedule_pickup safety hook (MCP namespace)

**Resolves:** Finding 4 (hook namespace mismatch)

**Files:**
- Modify: `src/orchestrator/agent/hooks.py:464-505`
- Test: `tests/orchestrator/agent/test_hooks.py`

**Important (AD-5):** This hook targets `mcp__ups__schedule_pickup` — the MCP tool name the agent calls in interactive mode via SDK auto-discovery. The orchestrator tool `schedule_pickup` (registered in Task 13) goes through `UPSMCPClient` which validates programmatically, so it doesn't need a separate hook.

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
    assert len(pickup_matchers) == 1, "Missing mcp__ups__schedule_pickup hook matcher"


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
git commit -m "feat: add schedule_pickup safety gate hook (mcp__ups__schedule_pickup)"
```

---

### Task 6: Update system prompt with new domain workflows

**Resolves:** AD-1 (interactive mode uses MCP auto-discovery, not orchestrator tools)

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


def test_system_prompt_interactive_mode_mentions_mcp_tools():
    """Interactive mode prompt guides agent to use MCP tools directly."""
    prompt = build_system_prompt(interactive_shipping=True)
    # Interactive mode should reference MCP tool names for direct agent use
    assert "Pickup" in prompt
    assert "Landed Cost" in prompt or "landed_cost" in prompt
    # Should NOT reference orchestrator tool names (those are batch-only)
    # The agent uses mcp__ups__schedule_pickup etc. via MCP auto-discovery
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_system_prompt.py -k "test_system_prompt_includes" -v`
Expected: FAIL — new domain sections missing

**Step 3: Write minimal implementation**

In `src/orchestrator/agent/system_prompt.py`, add new domain sections before the return statement at line 326. Insert a new `ups_v2_section` variable:

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

Insert this into the return string between `{international_section}` and the `## Connected Data Source` heading:

```python
    return f"""You are ShipAgent, ...

{service_table}
{international_section}
{ups_v2_section}
## Connected Data Source
...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/test_system_prompt.py -k "test_system_prompt_includes" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_system_prompt.py
git commit -m "feat: add UPS MCP v2 domain workflow guidance to system prompt"
```

---

### Task 7: Update .env.example comments

**Resolves:** Finding 9 (UPS_ACCOUNT_NUMBER already exists, reframe as comment update)

**Files:**
- Modify: `.env.example:22`

**Step 1: No test needed for comment-only change**

**Step 2: Update the comment above UPS_ACCOUNT_NUMBER**

Change line 22 area from:
```bash
UPS_ACCOUNT_NUMBER=your_ups_account_number
```
To:
```bash
# UPS Account Number — required for pickup scheduling, paperless docs,
# landed cost quotes, and shipment billing. Most v2 tools use this as fallback.
UPS_ACCOUNT_NUMBER=your_ups_account_number
```

**Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: clarify UPS_ACCOUNT_NUMBER usage for v2 tools in .env.example"
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
    # Verify schedule_pickup is in the mutating tool set
    assert "schedule_pickup" not in ups_client._READ_ONLY_TOOLS
    assert "schedule_pickup" in ups_client._MUTATING_TOOLS


@pytest.mark.asyncio
async def test_rate_pickup_retry_policy(ups_client):
    """rate_pickup uses read-only retry policy."""
    assert "rate_pickup" in ups_client._READ_ONLY_TOOLS
```

Note: The `ups_client` fixture should be defined in conftest.py or at top of file — a connected UPSMCPClient with mocked `_mcp`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_mcp_client.py -k "pickup" -v`
Expected: FAIL — methods don't exist

**Step 3: Write minimal implementation**

Add 4 public methods and 4 normalizers to `src/services/ups_mcp_client.py`. Also update the retry classification sets:

```python
# Promote to class-level constants for testability
_READ_ONLY_TOOLS = frozenset({
    "rate_shipment", "validate_address", "track_package",
    "rate_pickup", "get_pickup_status", "get_landed_cost_quote",
    "find_locations", "get_political_divisions", "get_service_center_facilities",
})

_MUTATING_TOOLS = frozenset({
    "create_shipment", "void_shipment", "schedule_pickup", "cancel_pickup",
    "upload_paperless_document", "push_document_to_shipment", "delete_paperless_document",
})
```

The 4 pickup methods follow the existing pattern (see `void_shipment` for mutating, `validate_address` for read-only). Each method:
1. Calls `self._call(tool_name, args)` with appropriate retry policy
2. Normalizes the UPS response into a clean dict
3. Returns `{"success": True, ...normalized_fields}`
4. Raises `UPSServiceError` on failure (caught by `_call()`)

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_ups_mcp_client.py -k "pickup" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "feat: add pickup methods to UPSMCPClient (schedule, cancel, rate, status)"
```

---

### Task 9: Add landed cost + paperless + locator methods to UPSMCPClient

**Files:**
- Modify: `src/services/ups_mcp_client.py`
- Test: `tests/services/test_ups_mcp_client.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_ups_mcp_client.py — add landed cost + paperless + locator tests
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
async def test_find_locations(ups_client):
    """find_locations returns location list."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "LocatorResponse": {
            "SearchResults": {
                "DropLocation": [
                    {"LocationID": "L1", "AddressKeyFormat": {"AddressLine": "123 Main"}}
                ]
            }
        }
    })
    result = await ups_client.find_locations(
        location_type="retail", address_line="123 Main",
        city="Austin", state="TX", postal_code="78701", country_code="US",
    )
    assert result["success"] is True
    assert len(result["locations"]) == 1


@pytest.mark.asyncio
async def test_get_service_center_facilities(ups_client):
    """get_service_center_facilities returns facility list."""
    ups_client._mcp.call_tool = AsyncMock(return_value={
        "ServiceCenterResponse": {
            "ServiceCenterList": [{"FacilityName": "UPS Store #1234"}]
        }
    })
    result = await ups_client.get_service_center_facilities(
        city="Austin", state="TX", postal_code="78701", country_code="US",
    )
    assert result["success"] is True
    assert "facilities" in result


@pytest.mark.asyncio
async def test_upload_document_no_retry(ups_client):
    """upload_document must NOT retry (mutating)."""
    assert "upload_paperless_document" in ups_client._MUTATING_TOOLS


@pytest.mark.asyncio
async def test_find_locations_uses_read_only_retry(ups_client):
    """find_locations uses read-only retry policy."""
    assert "find_locations" in ups_client._READ_ONLY_TOOLS
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_ups_mcp_client.py -k "landed_cost or document or locations or facilities" -v`
Expected: FAIL — methods don't exist

**Step 3: Write minimal implementation**

Add 6 public methods + 6 normalizers following the same pattern as Task 8.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_ups_mcp_client.py -k "landed_cost or document or locations or facilities" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "feat: add landed cost, paperless, locator methods to UPSMCPClient"
```

---

### Task 10: Create pickup + locator agent tool handlers with event emission

**Depends on:** Task 8
**Resolves:** Finding 2 (event producer gap), Finding 3 (response envelope contract)

**Files:**
- Create: `src/orchestrator/agent/tools/pickup.py`
- Test: `tests/orchestrator/agent/test_tools_v2.py` (add new section per AD-7)

**Step 1: Write the failing tests**

Tests use the `_ok()/_err()` envelope (AD-4) and verify event emission (AD-2):

```python
# tests/orchestrator/agent/test_tools_v2.py — add new section

# ---------------------------------------------------------------------------
# UPS MCP v2 — Pickup tool handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_pickup_tool_success():
    """schedule_pickup_tool returns _ok envelope and emits pickup_result event."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "ABC123"}

    bridge = EventEmitterBridge()
    captured = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool
        result = await schedule_pickup_tool(
            {
                "pickup_date": "20260220", "ready_time": "0900", "close_time": "1700",
                "address_line": "123 Main", "city": "Austin", "state": "TX",
                "postal_code": "78701", "country_code": "US",
                "contact_name": "John", "phone_number": "5125551234",
            },
            bridge=bridge,
        )

    # Verify _ok envelope
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["prn"] == "ABC123"

    # Verify event emission (AD-2)
    assert len(captured) == 1
    assert captured[0][0] == "pickup_result"
    assert captured[0][1]["action"] == "scheduled"
    assert captured[0][1]["prn"] == "ABC123"


@pytest.mark.asyncio
async def test_schedule_pickup_tool_error():
    """schedule_pickup_tool returns _err envelope on failure."""
    from src.services.errors import UPSServiceError
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.side_effect = UPSServiceError(code="E-3008", message="timing error")

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool
        result = await schedule_pickup_tool(
            {
                "pickup_date": "20260220", "ready_time": "0900", "close_time": "1700",
                "address_line": "123 Main", "city": "Austin", "state": "TX",
                "postal_code": "78701", "country_code": "US",
                "contact_name": "John", "phone_number": "5125551234",
            },
        )

    # Verify _err envelope
    assert result["isError"] is True
    assert "E-3008" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_find_locations_tool_emits_location_result():
    """find_locations_tool emits location_result event with results."""
    mock_ups = AsyncMock()
    mock_ups.find_locations.return_value = {
        "success": True,
        "locations": [{"id": "L1", "address": {"line": "123 Main"}}],
    }

    bridge = EventEmitterBridge()
    captured = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import find_locations_tool
        result = await find_locations_tool(
            {
                "location_type": "retail",
                "address_line": "123 Main", "city": "Austin",
                "state": "TX", "postal_code": "78701", "country_code": "US",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "location_result"
    assert len(captured[0][1]["locations"]) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -k "schedule_pickup_tool or find_locations_tool" -v`
Expected: FAIL — module doesn't exist

**Step 3: Write minimal implementation**

Create `src/orchestrator/agent/tools/pickup.py` with handler functions. Each handler:
1. Accepts `(args: dict, bridge: EventEmitterBridge | None = None)`
2. Gets `UPSMCPClient` via `_get_ups_client()` from `core.py`
3. Calls the appropriate client method
4. Emits typed event via `_emit_event(event_type, payload, bridge=bridge)` (AD-2)
5. Returns `_ok({...slim_data...})` — slim version for LLM context
6. Catches `UPSServiceError` and returns `_err(f"[{e.code}] {e.message}")` (AD-4)

```python
"""Pickup and location tool handlers for the orchestration agent.

Handles: schedule_pickup, cancel_pickup, rate_pickup, get_pickup_status,
find_locations, get_service_center_facilities.
"""

from __future__ import annotations

from typing import Any

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _emit_event,
    _err,
    _get_ups_client,
    _ok,
)
from src.services.errors import UPSServiceError


async def schedule_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Schedule a UPS pickup and emit pickup_result event."""
    try:
        client = await _get_ups_client()
        result = await client.schedule_pickup(**args)
        payload = {"action": "scheduled", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok({"prn": result.get("prn"), "success": True, "action": "scheduled"})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")

# ... similar for cancel_pickup_tool, rate_pickup_tool, get_pickup_status_tool,
# find_locations_tool, get_service_center_facilities_tool
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -k "schedule_pickup_tool or find_locations_tool" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/pickup.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: add pickup + locator agent tool handlers with event emission"
```

---

### Task 11: Create paperless document agent tool handlers with event emission

**Depends on:** Task 9
**Resolves:** Finding 2 (event producer gap)

**Files:**
- Create: `src/orchestrator/agent/tools/documents.py`
- Test: `tests/orchestrator/agent/test_tools_v2.py` (add new section per AD-7)

**Step 1: Write the failing tests**

```python
# tests/orchestrator/agent/test_tools_v2.py — add new section

# ---------------------------------------------------------------------------
# UPS MCP v2 — Paperless document tool handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_paperless_document_tool_emits_event():
    """upload_paperless_document_tool emits paperless_result on success."""
    mock_ups = AsyncMock()
    mock_ups.upload_document.return_value = {
        "success": True, "documentId": "DOC-123",
    }

    bridge = EventEmitterBridge()
    captured = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch("src.orchestrator.agent.tools.documents._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.documents import upload_paperless_document_tool
        result = await upload_paperless_document_tool(
            {
                "file_content_base64": "dGVzdA==",
                "file_name": "invoice.pdf",
                "file_format": "pdf",
                "document_type": "002",
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["documentId"] == "DOC-123"

    assert len(captured) == 1
    assert captured[0][0] == "paperless_result"
    assert captured[0][1]["action"] == "uploaded"
    assert captured[0][1]["documentId"] == "DOC-123"
```

**Step 2–4:** Same TDD cycle as Task 10.

Create `src/orchestrator/agent/tools/documents.py` with 3 handlers (upload, push, delete). Each follows the same pattern: call UPSMCPClient → emit `paperless_result` event → return `_ok()`.

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/documents.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: add paperless document agent tool handlers with event emission"
```

---

### Task 12: Add landed cost tool handler to pipeline with event emission

**Depends on:** Task 9
**Resolves:** Finding 2 (event producer gap), Finding 6 (naming: canonical name is `get_landed_cost`)

**Files:**
- Modify: `src/orchestrator/agent/tools/pipeline.py`
- Test: `tests/orchestrator/agent/test_tools_v2.py` (add to existing)

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/test_tools_v2.py — add

@pytest.mark.asyncio
async def test_get_landed_cost_tool_emits_event():
    """get_landed_cost_tool emits landed_cost_result on success."""
    mock_ups = AsyncMock()
    mock_ups.get_landed_cost.return_value = {
        "success": True,
        "totalLandedCost": "45.23",
        "currencyCode": "USD",
        "items": [{"commodityId": "1", "duties": "12.50", "taxes": "7.73", "fees": "0.00"}],
    }

    bridge = EventEmitterBridge()
    captured = []
    bridge.callback = lambda event_type, data: captured.append((event_type, data))

    with patch("src.orchestrator.agent.tools.pipeline._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pipeline import get_landed_cost_tool
        result = await get_landed_cost_tool(
            {
                "currency_code": "USD",
                "export_country_code": "US",
                "import_country_code": "GB",
                "commodities": [{"price": 25.00, "quantity": 2}],
            },
            bridge=bridge,
        )

    assert result["isError"] is False
    assert len(captured) == 1
    assert captured[0][0] == "landed_cost_result"
    assert captured[0][1]["totalLandedCost"] == "45.23"
```

**Step 2–4:** Same TDD cycle.

Add `get_landed_cost_tool` to `pipeline.py` following the same pattern.

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/pipeline.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: add landed cost tool handler to pipeline with event emission"
```

---

### Task 13: Register all new tools in __init__.py (batch mode only)

**Depends on:** Tasks 10, 11, 12
**Resolves:** Finding 1 (interactive mode architecture), Finding 6 (naming consistency)

**Files:**
- Modify: `src/orchestrator/agent/tools/__init__.py:19-38` (imports), `53-280` (definitions)
- Test: `tests/orchestrator/agent/test_tools_v2.py` (add to existing)

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/test_tools_v2.py — add

def test_v2_tools_registered_batch_mode():
    """All UPS MCP v2 orchestrator tools appear in batch mode."""
    defs = get_all_tool_definitions()
    names = {d["name"] for d in defs}
    expected_v2 = {
        "schedule_pickup", "cancel_pickup", "rate_pickup", "get_pickup_status",
        "find_locations", "get_service_center_facilities",
        "upload_paperless_document", "push_document_to_shipment", "delete_paperless_document",
        "get_landed_cost",
    }
    assert expected_v2.issubset(names), f"Missing: {expected_v2 - names}"


def test_v2_tools_not_in_interactive_mode():
    """Interactive mode MUST NOT include v2 orchestrator tools (AD-1).

    The agent accesses new UPS tools via MCP auto-discovery
    (mcp__ups__schedule_pickup etc.), not via orchestrator tool registry.
    The interactive allowlist stays at exactly 3 tools.
    """
    defs = get_all_tool_definitions(interactive_shipping=True)
    names = {d["name"] for d in defs}
    # Existing contract — exactly 3 tools
    assert names == {"get_job_status", "get_platform_status", "preview_interactive_shipment"}
    # Explicitly verify no v2 tools leaked in
    v2_tools = {
        "schedule_pickup", "cancel_pickup", "rate_pickup",
        "find_locations", "get_landed_cost", "upload_paperless_document",
    }
    assert not names.intersection(v2_tools), f"v2 tools leaked into interactive mode: {names & v2_tools}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -k "v2_tools" -v`
Expected: `test_v2_tools_registered_batch_mode` FAILS (tools not registered); `test_v2_tools_not_in_interactive_mode` PASSES (since tools aren't there yet — serves as regression guard)

**Step 3: Write minimal implementation**

Add imports from `pickup.py` and `documents.py` to `__init__.py`, add 10 tool definitions to the `definitions` list. Each follows the existing pattern with name, description, input_schema, and handler bound to bridge.

**Critical: Do NOT modify the interactive mode filtering** at line 281-286. The existing `interactive_allowed` set stays as-is:
```python
interactive_allowed = {"get_job_status", "get_platform_status", "preview_interactive_shipment"}
```

New tools are appended to `definitions` before the interactive filter runs, so they're automatically available in batch mode and automatically excluded from interactive mode.

**Step 4: Run ALL tool tests to verify**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -v`
Expected: ALL PASS — including existing `test_tool_definitions_filtered_for_interactive_mode` (line 836-840)

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/__init__.py tests/orchestrator/agent/test_tools_v2.py
git commit -m "feat: register 10 UPS MCP v2 tools in batch mode (interactive unchanged per AD-1)"
```

---

### Task 13.5: End-to-end integration tests (pickup + landed cost flows)

**Depends on:** Tasks 10, 12, 13
**Resolves:** Recommendation 5 (add integration tests before frontend)

**Files:**
- Test: `tests/orchestrator/agent/test_tools_v2.py` (add integration section)

**Step 1: Write integration tests**

```python
# tests/orchestrator/agent/test_tools_v2.py — add integration section

# ---------------------------------------------------------------------------
# UPS MCP v2 — Integration: tool call → event emission → payload verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_pickup_flow_tool_to_event():
    """End-to-end: schedule_pickup_tool → pickup_result event with correct payload."""
    mock_ups = AsyncMock()
    mock_ups.schedule_pickup.return_value = {"success": True, "prn": "E2E-PRN-123"}

    bridge = EventEmitterBridge()
    captured_events = []
    bridge.callback = lambda et, d: captured_events.append((et, d))

    with patch("src.orchestrator.agent.tools.pickup._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pickup import schedule_pickup_tool
        tool_result = await schedule_pickup_tool(
            {
                "pickup_date": "20260301", "ready_time": "0800", "close_time": "1800",
                "address_line": "456 Oak Ave", "city": "Dallas", "state": "TX",
                "postal_code": "75201", "country_code": "US",
                "contact_name": "Jane Doe", "phone_number": "2145551234",
            },
            bridge=bridge,
        )

    # Verify tool returned _ok envelope to LLM
    assert tool_result["isError"] is False
    llm_data = json.loads(tool_result["content"][0]["text"])
    assert llm_data["prn"] == "E2E-PRN-123"
    assert llm_data["action"] == "scheduled"

    # Verify SSE event emitted with full payload
    assert len(captured_events) == 1
    event_type, event_data = captured_events[0]
    assert event_type == "pickup_result"
    assert event_data["action"] == "scheduled"
    assert event_data["prn"] == "E2E-PRN-123"
    assert event_data["success"] is True


@pytest.mark.asyncio
async def test_e2e_landed_cost_flow_tool_to_event():
    """End-to-end: get_landed_cost_tool → landed_cost_result event with breakdown."""
    mock_ups = AsyncMock()
    mock_ups.get_landed_cost.return_value = {
        "success": True,
        "totalLandedCost": "87.50",
        "currencyCode": "USD",
        "items": [
            {"commodityId": "1", "duties": "25.00", "taxes": "12.50", "fees": "0.00"},
            {"commodityId": "2", "duties": "30.00", "taxes": "20.00", "fees": "0.00"},
        ],
    }

    bridge = EventEmitterBridge()
    captured_events = []
    bridge.callback = lambda et, d: captured_events.append((et, d))

    with patch("src.orchestrator.agent.tools.pipeline._get_ups_client", return_value=mock_ups):
        from src.orchestrator.agent.tools.pipeline import get_landed_cost_tool
        tool_result = await get_landed_cost_tool(
            {
                "currency_code": "USD",
                "export_country_code": "US",
                "import_country_code": "GB",
                "commodities": [
                    {"price": 50.00, "quantity": 1, "hs_code": "6109.10"},
                    {"price": 75.00, "quantity": 1, "hs_code": "6110.20"},
                ],
            },
            bridge=bridge,
        )

    # Verify tool returned _ok envelope to LLM
    assert tool_result["isError"] is False
    llm_data = json.loads(tool_result["content"][0]["text"])
    assert llm_data["totalLandedCost"] == "87.50"

    # Verify SSE event emitted with full breakdown
    assert len(captured_events) == 1
    event_type, event_data = captured_events[0]
    assert event_type == "landed_cost_result"
    assert event_data["totalLandedCost"] == "87.50"
    assert len(event_data["items"]) == 2
```

**Step 2: Run tests**

Run: `pytest tests/orchestrator/agent/test_tools_v2.py -k "e2e_" -v`
Expected: PASS (since producers were implemented in Tasks 10/12)

**Step 3: Commit**

```bash
git add tests/orchestrator/agent/test_tools_v2.py
git commit -m "test: add end-to-end integration tests for pickup + landed cost flows"
```

---

## Phase 3: Frontend

### Task 14: Add domain color system to CSS

**Files:**
- Modify: `frontend/src/index.css`

Add OKLCH domain color variables and utility classes:

```css
/* Domain colors (UPS MCP v2) */
--color-domain-shipping: oklch(0.75 0.18 145);    /* Green — existing */
--color-domain-pickup: oklch(0.70 0.18 300);       /* Purple */
--color-domain-locator: oklch(0.75 0.15 185);      /* Teal */
--color-domain-paperless: oklch(0.78 0.15 85);     /* Amber */
--color-domain-landed-cost: oklch(0.65 0.18 265);  /* Indigo */

/* Domain card border utilities */
.card-domain-pickup { border-color: var(--color-domain-pickup); }
.card-domain-locator { border-color: var(--color-domain-locator); }
.card-domain-paperless { border-color: var(--color-domain-paperless); }
.card-domain-landed-cost { border-color: var(--color-domain-landed-cost); }
```

No automated test — visual verification.

**Commit:**
```bash
git add frontend/src/index.css
git commit -m "feat: add domain-specific OKLCH colors for pickup, locator, paperless, landed cost"
```

---

### Task 15: Add new TypeScript types and update AgentEventType

**Resolves:** Finding 8 (AgentEventType union not updated)

**Files:**
- Modify: `frontend/src/types/api.ts:620-632` (AgentEventType union)
- Modify: `frontend/src/types/api.ts` (new result interfaces)

Add 4 new event types to the `AgentEventType` union (line 620-632):

```typescript
export type AgentEventType =
  | 'agent_thinking'
  | 'tool_call'
  | 'tool_result'
  | 'agent_message'
  | 'agent_message_delta'
  | 'preview_ready'
  | 'pickup_result'          // NEW
  | 'location_result'        // NEW
  | 'landed_cost_result'     // NEW
  | 'paperless_result'       // NEW
  | 'confirmation_needed'
  | 'execution_progress'
  | 'completion'
  | 'error'
  | 'done'
  | 'ping';
```

Add result interfaces matching the event contract matrix (AD-2):

```typescript
/** Pickup operation result from SSE stream. */
export interface PickupResult {
  action: 'scheduled' | 'cancelled' | 'rated' | 'status';
  success: boolean;
  prn?: string;
  charges?: Array<{ chargeAmount: string; chargeCode: string }>;
  pickups?: Array<{ pickupDate: string; prn: string }>;
}

/** Location search result from SSE stream. */
export interface LocationResult {
  locations: Array<{
    id: string;
    address: Record<string, string>;
    phone?: string;
    hours?: Record<string, string>;
  }>;
  search_type: string;
  radius: number;
}

/** Landed cost estimation result from SSE stream. */
export interface LandedCostResult {
  totalLandedCost: string;
  currencyCode: string;
  items: Array<{
    commodityId: string;
    duties: string;
    taxes: string;
    fees: string;
  }>;
}

/** Paperless document operation result from SSE stream. */
export interface PaperlessResult {
  action: 'uploaded' | 'pushed' | 'deleted';
  success: boolean;
  documentId?: string;
}
```

Run: `cd frontend && npx tsc --noEmit` to verify type correctness.

**Commit:**
```bash
git add frontend/src/types/api.ts
git commit -m "feat: add TypeScript types and AgentEventType variants for UPS MCP v2"
```

---

### Task 16: Create PickupCard component

**Files:**
- Create: `frontend/src/components/command-center/PickupCard.tsx`

Renders 4 variants (scheduled, cancelled, rated, status) with purple domain border (`card-domain-pickup`). Accepts `PickupResult` as props.

**Commit:**
```bash
git add frontend/src/components/command-center/PickupCard.tsx
git commit -m "feat: add PickupCard component with domain-colored variants"
```

---

### Task 17: Create LocationCard component

**Files:**
- Create: `frontend/src/components/command-center/LocationCard.tsx`

Renders location search results with teal domain border (`card-domain-locator`). Accepts `LocationResult` as props. Shows address, phone, hours for each location.

**Commit:**
```bash
git add frontend/src/components/command-center/LocationCard.tsx
git commit -m "feat: add LocationCard component for UPS location search results"
```

---

### Task 18: Create LandedCostCard component

**Files:**
- Create: `frontend/src/components/command-center/LandedCostCard.tsx`

Renders duty/tax/fees breakdown with indigo domain border (`card-domain-landed-cost`). Accepts `LandedCostResult` as props. Shows per-commodity breakdown table + total.

**Commit:**
```bash
git add frontend/src/components/command-center/LandedCostCard.tsx
git commit -m "feat: add LandedCostCard component for international cost breakdown"
```

---

### Task 19: Create PaperlessCard component

**Files:**
- Create: `frontend/src/components/command-center/PaperlessCard.tsx`

Renders document operation results with amber domain border (`card-domain-paperless`). Accepts `PaperlessResult` as props. Shows action (uploaded/pushed/deleted) + document ID.

**Commit:**
```bash
git add frontend/src/components/command-center/PaperlessCard.tsx
git commit -m "feat: add PaperlessCard component for paperless document operations"
```

---

### Task 20: Wire SSE event routing in CommandCenter + CompletionArtifact pickup button

**Depends on:** Tasks 15-19
**Resolves:** Finding 2 (event routing now has producers from Tasks 10-12)

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx:147-207`
- Modify: `frontend/src/components/command-center/CompletionArtifact.tsx`

**Step 1: Add event routing**

In `CommandCenter.tsx`, add routing branches after the `preview_ready` handler (line 165-196):

```typescript
// After the existing preview_ready handler...
} else if (event.type === 'pickup_result') {
    const pickupData = event.data as unknown as PickupResult;
    addMessage({
        role: 'system',
        content: '',
        metadata: { action: 'pickup_result', data: pickupData },
    });
} else if (event.type === 'location_result') {
    const locationData = event.data as unknown as LocationResult;
    addMessage({
        role: 'system',
        content: '',
        metadata: { action: 'location_result', data: locationData },
    });
} else if (event.type === 'landed_cost_result') {
    const costData = event.data as unknown as LandedCostResult;
    addMessage({
        role: 'system',
        content: '',
        metadata: { action: 'landed_cost_result', data: costData },
    });
} else if (event.type === 'paperless_result') {
    const paperlessData = event.data as unknown as PaperlessResult;
    addMessage({
        role: 'system',
        content: '',
        metadata: { action: 'paperless_result', data: paperlessData },
    });
```

**Step 2: Add card rendering**

In the message rendering section of CommandCenter (where `action === 'preview'` routes to `<PreviewCard>`), add:

```typescript
{msg.metadata?.action === 'pickup_result' && (
    <PickupCard data={msg.metadata.data as PickupResult} />
)}
{msg.metadata?.action === 'location_result' && (
    <LocationCard data={msg.metadata.data as LocationResult} />
)}
{msg.metadata?.action === 'landed_cost_result' && (
    <LandedCostCard data={msg.metadata.data as LandedCostResult} />
)}
{msg.metadata?.action === 'paperless_result' && (
    <PaperlessCard data={msg.metadata.data as PaperlessResult} />
)}
```

**Step 3: Add CompletionArtifact pickup button**

In `CompletionArtifact.tsx`, add a "Schedule Pickup" button with purple styling that sends a pickup scheduling command through the conversation:

```typescript
{/* Show pickup suggestion when batch completes with successes */}
{completionData.successful_count > 0 && (
    <button
        className="btn-secondary card-domain-pickup"
        onClick={() => onSendMessage?.("Schedule a pickup for today's shipments")}
    >
        Schedule Pickup
    </button>
)}
```

**Step 4: Run type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

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

Update the integration guide tool inventory table from 7 to 18 tools. Update CLAUDE.md:
- UPS MCP server tool count: 7 → 18
- Add new tool names to the MCP tool table
- Note error code additions (E-2020–E-2022, E-3007–E-3009, E-4011–E-4012)
- Document the interactive mode policy (AD-1): new tools available via MCP auto-discovery, not orchestrator registry

**Commit:**
```bash
git add docs/ups-mcp-integration-guide.md CLAUDE.md
git commit -m "docs: update integration guide and CLAUDE.md for UPS MCP v2 (18 tools)"
```
