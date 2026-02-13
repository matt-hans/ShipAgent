# Interactive Shipping Mode Toggle — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a frontend toggle that enables/disables interactive single-shipment creation, with deterministic backend enforcement and session-level state.

**Architecture:** Session-level `interactive_shipping` flag flows from frontend localStorage → conversation creation request → `AgentSession` → system prompt conditioning + hook factory enforcement. Toggle mid-conversation resets the session. Batch pipeline is unaffected.

**Tech Stack:** React + TypeScript (frontend), Python + FastAPI + Claude Agent SDK (backend), shadcn/ui Switch component (new)

**Branch baseline:** All file paths and line references are against `claude/zen-bohr` worktree.

---

### Task 1: UPS MCP Repin

**Files:**
- Modify: `pyproject.toml:36`
- Modify: `uv.lock` (auto-generated)

**Step 1: Get latest commit SHA from ups-mcp main**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent && git ls-remote https://github.com/UPS-API/ups-mcp.git refs/heads/main | cut -f1`

Record the SHA output. If the upstream repo does NOT contain `shipment_validator.py`, use the fork URL instead.

**Step 2: Update pyproject.toml**

In `pyproject.toml:36`, replace the existing pin:
```python
# Before:
"ups-mcp @ git+https://github.com/UPS-API/ups-mcp.git@41fb64f71c5f9afe0fb8764e9dd29a71e3c773e1",
# After (use actual SHA from step 1):
"ups-mcp @ git+https://github.com/UPS-API/ups-mcp.git@<NEW_SHA>",
```

**Step 3: Sync lockfile and install**

Run:
```bash
cd /Users/matthewhans/Desktop/Programming/ShipAgent
uv lock && uv sync
```

**Step 4: Verify elicitation module exists**

Run: `python3 -c "from ups_mcp import server; print('OK')"`
Expected: `OK`

Run: `ls .venv/lib/python*/site-packages/ups_mcp/shipment_validator.py 2>/dev/null && echo "FOUND" || echo "MISSING"`
Expected: `FOUND`

**Step 5: Run existing tests to confirm no regressions**

Run: `python3 -m pytest tests/errors/ tests/orchestrator/ tests/services/ -k "not test_stream_endpoint_exists" --tb=short -q`
Expected: All tests pass (2 pre-existing failures in test_config.py are acceptable)

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
build: repin ups-mcp to include elicitation/preflight support

Update ups-mcp from 41fb64f to <NEW_SHA> which includes:
- Preflight validation pipeline (shipment_validator.py)
- Structured ToolError payloads with missing[] arrays
- 6 new error codes for elicitation flow
- Canonicalization of Package/ShipmentCharge as dict or list
EOF
)"
```

---

### Task 2: Backend Schema + Session Storage

**Files:**
- Modify: `src/api/schemas_conversations.py:1-42`
- Modify: `src/services/agent_session_manager.py:42-97`
- Test: `tests/api/test_conversations.py` (or create if needed)

**Step 1: Write the failing tests**

Create or add to `tests/api/test_conversations_interactive.py`:

```python
"""Tests for interactive_shipping flag in conversation lifecycle."""

import pytest
from src.api.schemas_conversations import CreateConversationRequest, CreateConversationResponse


class TestCreateConversationRequest:
    """Tests for the CreateConversationRequest schema."""

    def test_defaults_to_false(self):
        """interactive_shipping defaults to False when omitted."""
        req = CreateConversationRequest()
        assert req.interactive_shipping is False

    def test_accepts_true(self):
        """interactive_shipping can be set to True."""
        req = CreateConversationRequest(interactive_shipping=True)
        assert req.interactive_shipping is True

    def test_accepts_false_explicit(self):
        """interactive_shipping can be explicitly set to False."""
        req = CreateConversationRequest(interactive_shipping=False)
        assert req.interactive_shipping is False


class TestCreateConversationResponseEcho:
    """Tests for echoing interactive_shipping in response."""

    def test_response_includes_flag(self):
        """Response echoes the effective interactive_shipping value."""
        resp = CreateConversationResponse(
            session_id="test-123",
            interactive_shipping=True,
        )
        assert resp.interactive_shipping is True
        assert resp.session_id == "test-123"

    def test_response_defaults_false(self):
        """Response defaults interactive_shipping to False."""
        resp = CreateConversationResponse(
            session_id="test-123",
        )
        assert resp.interactive_shipping is False


class TestAgentSessionStorage:
    """Tests for interactive_shipping stored on AgentSession."""

    def test_session_defaults_false(self):
        """AgentSession defaults interactive_shipping to False."""
        from src.services.agent_session_manager import AgentSession
        session = AgentSession("test-id")
        assert session.interactive_shipping is False

    def test_session_stores_true(self):
        """AgentSession stores interactive_shipping when set."""
        from src.services.agent_session_manager import AgentSession
        session = AgentSession("test-id")
        session.interactive_shipping = True
        assert session.interactive_shipping is True
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/api/test_conversations_interactive.py -v`
Expected: FAIL — `CreateConversationRequest` doesn't exist yet, `interactive_shipping` not on models

**Step 3: Implement schema changes**

In `src/api/schemas_conversations.py`, add the request model and update response:

```python
class CreateConversationRequest(BaseModel):
    """Optional request body for creating a conversation session.

    All fields are optional with safe defaults for backward compatibility.
    Existing clients that POST with no body continue to work.
    """

    interactive_shipping: bool = Field(
        default=False,
        description="Enable interactive single-shipment creation via UPS MCP elicitation",
    )


class CreateConversationResponse(BaseModel):
    """Response for creating a new conversation session."""

    session_id: str
    interactive_shipping: bool = Field(
        default=False,
        description="Effective interactive_shipping mode for this session",
    )
```

In `src/services/agent_session_manager.py`, add to `AgentSession.__init__()`:

```python
self.interactive_shipping: bool = False
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/api/test_conversations_interactive.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/api/schemas_conversations.py src/services/agent_session_manager.py tests/api/test_conversations_interactive.py
git commit -m "$(cat <<'EOF'
feat: add interactive_shipping to conversation schema + session

- CreateConversationRequest with optional interactive_shipping (default False)
- CreateConversationResponse echoes effective value
- AgentSession stores the flag for rebuild hash computation
- Backward-compatible: no-body requests default to False
EOF
)"
```

---

### Task 3: Conversation Route Wiring + Agent Rebuild Hash

**Files:**
- Modify: `src/api/routes/conversations.py:427-450` (create endpoint)
- Modify: `src/api/routes/conversations.py:157-201` (`_ensure_agent`)
- Modify: `src/api/routes/conversations.py:233-371` (`_process_agent_message` logging)
- Test: `tests/api/test_conversations_interactive.py` (add route-level tests)

**Step 1: Write the failing tests**

Add to `tests/api/test_conversations_interactive.py`:

```python
class TestConversationRouteInteractiveFlag:
    """Tests for interactive_shipping flowing through conversation route."""

    def test_ensure_agent_rebuilds_on_flag_change(self):
        """_ensure_agent rebuilds when interactive_shipping changes (same source)."""
        from src.api.routes.conversations import _compute_source_hash
        from src.services.agent_session_manager import AgentSession

        session = AgentSession("test-rebuild")
        # Simulate first build with interactive=False
        source_hash = _compute_source_hash(None)
        flag_hash_off = f"{source_hash}|interactive=False"
        flag_hash_on = f"{source_hash}|interactive=True"

        # Hashes must differ when only flag changes
        assert flag_hash_off != flag_hash_on

    def test_compute_source_hash_includes_interactive(self):
        """Rebuild hash includes interactive_shipping flag."""
        from src.api.routes.conversations import _compute_source_hash

        hash_base = _compute_source_hash(None)
        # Hash alone is stable
        assert hash_base == _compute_source_hash(None)
```

**Step 2: Run tests to verify they fail (or pass — hash logic is pure)**

Run: `python3 -m pytest tests/api/test_conversations_interactive.py::TestConversationRouteInteractiveFlag -v`

**Step 3: Implement route changes**

In `src/api/routes/conversations.py`:

1. Update `create_conversation()` endpoint to accept optional body:

```python
from src.api.schemas_conversations import CreateConversationRequest, CreateConversationResponse

@router.post("/", response_model=CreateConversationResponse, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest | None = None,
) -> CreateConversationResponse:
    """Create a new conversation session.

    Args:
        payload: Optional request body. Defaults to interactive_shipping=False.

    Returns:
        CreateConversationResponse with session_id and effective mode.
    """
    effective_payload = payload or CreateConversationRequest()

    session_id = str(uuid4())
    session = _session_manager.get_or_create_session(session_id)
    session.interactive_shipping = effective_payload.interactive_shipping

    # Best-effort prewarm ...
    # (existing prewarm logic unchanged)

    logger.info(
        "Created conversation session: %s interactive_shipping=%s",
        session_id,
        session.interactive_shipping,
    )
    return CreateConversationResponse(
        session_id=session_id,
        interactive_shipping=session.interactive_shipping,
    )
```

2. Update `_ensure_agent()` to include flag in rebuild hash and pass to prompt/agent:

```python
async def _ensure_agent(
    session: "AgentSession",
    source_info: "DataSourceInfo | None",
) -> bool:
    from src.orchestrator.agent.client import OrchestrationAgent
    from src.orchestrator.agent.system_prompt import build_system_prompt

    source_hash = _compute_source_hash(source_info)
    combined_hash = f"{source_hash}|interactive={session.interactive_shipping}"

    if session.agent is not None and session.agent_source_hash == combined_hash:
        return False

    if session.agent is not None:
        logger.info(
            "Config changed for session %s, rebuilding agent",
            session.session_id,
        )
        try:
            await session.agent.stop()
        except Exception as e:
            logger.warning("Error stopping old agent: %s", e)

    system_prompt = build_system_prompt(
        source_info=source_info,
        interactive_shipping=session.interactive_shipping,
    )
    agent = OrchestrationAgent(
        system_prompt=system_prompt,
        interactive_shipping=session.interactive_shipping,
    )
    await agent.start()

    session.agent = agent
    session.agent_source_hash = combined_hash
    logger.info(
        "Agent started for session %s interactive_shipping=%s",
        session.session_id,
        session.interactive_shipping,
    )
    return True
```

3. Add `interactive_shipping` to `_process_agent_message` timing logs (all `agent_timing` markers).

**Step 4: Run tests**

Run: `python3 -m pytest tests/api/test_conversations_interactive.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/api/routes/conversations.py tests/api/test_conversations_interactive.py
git commit -m "$(cat <<'EOF'
feat: wire interactive_shipping through conversation route

- create_conversation accepts optional body with interactive_shipping
- _ensure_agent includes flag in rebuild hash (flag change triggers rebuild)
- Flag passed to build_system_prompt() and OrchestrationAgent()
- agent_timing logs include interactive_shipping for observability
- Backward-compatible: no-body POST defaults to False
EOF
)"
```

---

### Task 4: System Prompt Conditioning

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py:60-233`
- Test: `tests/orchestrator/agent/test_system_prompt.py`

**Step 1: Write the failing tests**

Add to `tests/orchestrator/agent/test_system_prompt.py`:

```python
class TestInteractiveShippingPromptConditioning:
    """Tests for interactive_shipping prompt conditioning."""

    def test_interactive_sections_included_when_true(self):
        """Direct shipment + validation sections present when interactive=True."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "Direct Single-Shipment Commands" in prompt
        assert "Handling Create Shipment Validation Errors" in prompt

    def test_interactive_sections_omitted_when_false(self):
        """Direct shipment + validation sections absent when interactive=False."""
        prompt = build_system_prompt(interactive_shipping=False)
        assert "Direct Single-Shipment Commands" not in prompt
        assert "Handling Create Shipment Validation Errors" not in prompt

    def test_interactive_sections_omitted_by_default(self):
        """Default (no flag) omits interactive sections."""
        prompt = build_system_prompt()
        assert "Direct Single-Shipment Commands" not in prompt

    def test_coexistence_routing_policy_when_true(self):
        """Coexistence routing rules present when interactive=True."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "batch path" in prompt.lower()
        assert "ambiguous" in prompt.lower()
        assert "clarifying question" in prompt.lower()

    def test_direct_path_precedence_text(self):
        """Direct path takes precedence for ad-hoc when interactive=True."""
        prompt = build_system_prompt(interactive_shipping=True)
        assert "takes precedence" in prompt.lower() or "check first" in prompt.lower()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/agent/test_system_prompt.py::TestInteractiveShippingPromptConditioning -v`
Expected: FAIL — `build_system_prompt()` doesn't accept `interactive_shipping` yet

**Step 3: Implement prompt conditioning**

In `src/orchestrator/agent/system_prompt.py`, update `build_system_prompt()`:

```python
def build_system_prompt(
    source_info: DataSourceInfo | None = None,
    interactive_shipping: bool = False,
) -> str:
```

Move the "Direct Single-Shipment Commands" and "Handling Create Shipment Validation Errors" sections into a conditional block:

```python
    # Interactive shipping sections (only when enabled)
    interactive_section = ""
    if interactive_shipping:
        interactive_section = """
### Direct Single-Shipment Commands (check first)

...existing text from lines 139-160...

### Coexistence Routing Policy

When interactive shipping is enabled alongside a connected data source:
- Any request implying multiple shipments → batch path only
- Explicit batch or data-source operations → batch path
- Explicit single ad-hoc shipment details → direct MCP path (takes precedence)
- Ambiguous intent with data source connected → ask one clarifying question before calling any tool
- Before direct shipment creation when a data source is connected → short confirmation step
"""

    # ... later in the prompt string:
    validation_section = ""
    if interactive_shipping:
        validation_section = """
## Handling Create Shipment Validation Errors

...existing text from lines 205-226...
"""
```

Insert `{interactive_section}` after the Filter Generation Rules and before "Shipping Commands", and `{validation_section}` after Safety Rules.

**Step 4: Run tests**

Run: `python3 -m pytest tests/orchestrator/agent/test_system_prompt.py -v`
Expected: ALL PASS (including existing tests)

**Step 5: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py tests/orchestrator/agent/test_system_prompt.py
git commit -m "$(cat <<'EOF'
feat: condition system prompt on interactive_shipping flag

When interactive_shipping=False (default), omit direct single-shipment
and validation error sections entirely. When True, include both plus
coexistence routing policy with precedence rules.
EOF
)"
```

---

### Task 5: Hook Factory with Instance-Scoped Enforcement

**Files:**
- Modify: `src/orchestrator/agent/hooks.py:49-86` (validate_shipping_input)
- Modify: `src/orchestrator/agent/hooks.py:406-445` (create_hook_matchers)
- Modify: `src/orchestrator/agent/client.py:131-209` (OrchestrationAgent.__init__ + _create_options)
- Test: `tests/orchestrator/agent/test_hooks.py`

**Step 1: Write the failing tests**

Add to `tests/orchestrator/agent/test_hooks.py`:

```python
class TestInteractiveShippingHookEnforcement:
    """Tests for deterministic create_shipment gating by interactive_shipping."""

    @pytest.mark.asyncio
    async def test_create_shipment_denied_when_interactive_off(self):
        """create_shipment is deterministically blocked when interactive=False."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=False)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert "deny" in str(result)
        assert "Interactive shipping is disabled" in str(result)

    @pytest.mark.asyncio
    async def test_create_shipment_allowed_when_interactive_on(self):
        """create_shipment allowed (structural guard only) when interactive=True."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": {"request_body": {}}},
            "test-id",
            None,
        )
        assert result == {}  # Allowed

    @pytest.mark.asyncio
    async def test_structural_guard_still_applies_when_interactive_on(self):
        """Non-dict tool_input denied even when interactive=True."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=True)
        result = await hook(
            {"tool_name": "mcp__ups__create_shipment", "tool_input": "not a dict"},
            "test-id",
            None,
        )
        assert "deny" in str(result)

    @pytest.mark.asyncio
    async def test_non_shipping_tools_unaffected(self):
        """Other tools pass through regardless of interactive flag."""
        from src.orchestrator.agent.hooks import create_shipping_hook

        hook = create_shipping_hook(interactive_shipping=False)
        result = await hook(
            {"tool_name": "mcp__ups__rate_shipment", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}  # Allowed — only create_shipment is gated
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/agent/test_hooks.py::TestInteractiveShippingHookEnforcement -v`
Expected: FAIL — `create_shipping_hook` doesn't exist yet

**Step 3: Implement hook factory**

In `src/orchestrator/agent/hooks.py`, add a factory function:

```python
def create_shipping_hook(
    interactive_shipping: bool = False,
):
    """Factory that creates a create_shipment pre-hook with mode enforcement.

    When interactive_shipping=False, deterministically denies create_shipment.
    When interactive_shipping=True, applies structural guard only (dict check).

    Args:
        interactive_shipping: Whether interactive single-shipment mode is enabled.

    Returns:
        Async hook function with interactive_shipping captured via closure.
    """
    async def _validate_shipping(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        """Validate create_shipment with mode-aware enforcement."""
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        _log_to_stderr(
            f"[VALIDATION] Pre-hook checking: {tool_name} | ID: {tool_use_id} | "
            f"interactive={interactive_shipping}"
        )

        if "create_shipment" in tool_name:
            # Hard enforcement: deny when interactive mode is off
            if not interactive_shipping:
                return _deny_with_reason(
                    "Interactive shipping is disabled. "
                    "Use batch processing for shipment creation."
                )

            # Structural guard: deny non-dict inputs
            if not isinstance(tool_input, dict):
                return _deny_with_reason(
                    "Invalid tool_input: expected a dict, "
                    f"got {type(tool_input).__name__}."
                )

        return {}

    return _validate_shipping
```

Update `create_hook_matchers()` to accept `interactive_shipping` and use the factory:

```python
def create_hook_matchers(interactive_shipping: bool = False) -> dict[str, list[HookMatcher]]:
    """Create hook matchers with mode-aware enforcement.

    Args:
        interactive_shipping: Whether interactive mode is enabled.

    Returns:
        Dict with PreToolUse and PostToolUse hook configurations.
    """
    shipping_hook = create_shipping_hook(interactive_shipping=interactive_shipping)

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
                matcher="mcp__data__query",
                hooks=[validate_data_query],
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

Update `OrchestrationAgent.__init__()` in `client.py` to accept and pass through `interactive_shipping`:

```python
def __init__(
    self,
    system_prompt: str | None = None,
    max_turns: int = 50,
    permission_mode: str = "acceptEdits",
    model: str | None = None,
    interactive_shipping: bool = False,
) -> None:
    self._system_prompt = system_prompt
    self._model = model or DEFAULT_MODEL
    self._interactive_shipping = interactive_shipping
    self.emitter_bridge = EventEmitterBridge()
    self._options = self._create_options(max_turns, permission_mode)
    self._client: Optional[ClaudeSDKClient] = None
    self._started = False
    self._last_turn_count = 0
```

Update `_create_options()` to pass `interactive_shipping` to `create_hook_matchers()`:

```python
hooks=create_hook_matchers(interactive_shipping=self._interactive_shipping),
```

Also update `__all__` in hooks.py to export `create_shipping_hook`.

**Step 4: Run tests**

Run: `python3 -m pytest tests/orchestrator/agent/test_hooks.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/orchestrator/agent/hooks.py src/orchestrator/agent/client.py tests/orchestrator/agent/test_hooks.py
git commit -m "$(cat <<'EOF'
feat: hook factory with instance-scoped interactive_shipping enforcement

- create_shipping_hook() factory captures interactive_shipping via closure
- When False: deterministically denies create_shipment (not prompt-based)
- When True: structural guard only (dict-type check)
- OrchestrationAgent passes interactive_shipping to create_hook_matchers()
- No global mutable registry — per-instance lifecycle
EOF
)"
```

---

### Task 6: MALFORMED_REQUEST Reason Preservation

**Files:**
- Modify: `src/services/ups_mcp_client.py:576-650` (`_translate_error`)
- Test: `tests/services/test_ups_mcp_client.py`

**Step 1: Write the failing test**

Add to `tests/services/test_ups_mcp_client.py` in `TestTranslateErrorMCPPreflight`:

```python
def test_malformed_request_preserves_reason_in_details(self):
    """MALFORMED_REQUEST preserves reason variant in details and message."""
    error = MCPToolError(error_text=json.dumps({
        "code": "MALFORMED_REQUEST",
        "message": "Ambiguous payer configuration",
        "reason": "ambiguous_payer",
    }))
    result = client._translate_error(error)
    assert result.code == "E-2011"
    assert result.details is not None
    assert result.details.get("reason") == "ambiguous_payer"
    assert "ambiguous_payer" in result.message.lower() or "ambiguous" in result.message.lower()

def test_malformed_request_reason_malformed_structure(self):
    """MALFORMED_REQUEST with malformed_structure reason."""
    error = MCPToolError(error_text=json.dumps({
        "code": "MALFORMED_REQUEST",
        "message": "Invalid payload structure",
        "reason": "malformed_structure",
    }))
    result = client._translate_error(error)
    assert result.code == "E-2011"
    assert result.details.get("reason") == "malformed_structure"
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/services/test_ups_mcp_client.py::TestTranslateErrorMCPPreflight::test_malformed_request_preserves_reason_in_details -v`
Expected: FAIL — `reason` not in details yet

**Step 3: Implement reason preservation**

In `_translate_error()`, after building context and before creating `UPSServiceError`, add:

```python
        # Preserve MCP reason field for diagnostics (P2 feedback)
        reason = error_data.get("reason")
        if reason and isinstance(reason, str):
            ups_message = f"{ups_message} (reason: {reason})"
```

The `error_data` dict is already passed as `details=error_data`, so `reason` is automatically preserved in `UPSServiceError.details`.

**Step 4: Run tests**

Run: `python3 -m pytest tests/services/test_ups_mcp_client.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "$(cat <<'EOF'
feat: preserve MCP reason field in MALFORMED_REQUEST errors

Include reason variant (malformed_structure, ambiguous_payer) in
UPSServiceError message for diagnostics. The full error_data dict
(including reason) is already passed through as details.
EOF
)"
```

---

### Task 7: Behavior-Level Integration Test

**Files:**
- Create: `tests/orchestrator/agent/test_interactive_mode.py`

**Step 1: Write the behavior test**

```python
"""Behavior-level test for interactive shipping mode.

Asserts observed runtime behavior: hook + mode routing + error translation
working together. Does NOT test prompt text — that's covered by unit tests.
"""

import json
import pytest

from src.orchestrator.agent.hooks import create_shipping_hook
from src.services.ups_mcp_client import UPSMCPClient
from src.services.mcp_client import MCPToolError


class TestInteractiveModeEndToEnd:
    """Behavior tests for interactive shipping mode flow."""

    @pytest.mark.asyncio
    async def test_interactive_on_allows_and_translates_missing_error(self):
        """With interactive=True: hook allows → _translate_error produces E-2010.

        Simulates: agent calls create_shipment → MCP preflight returns ToolError
        with missing[] → ShipAgent translates to actionable E-2010 error.
        """
        # 1. Hook allows create_shipment when interactive=True
        hook = create_shipping_hook(interactive_shipping=True)
        hook_result = await hook(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"request_body": {"Shipment": {}}},
            },
            "test-tool-id",
            None,
        )
        assert hook_result == {}, "Hook should allow create_shipment when interactive=True"

        # 2. _translate_error converts missing[] ToolError to E-2010
        client = UPSMCPClient.__new__(UPSMCPClient)
        error = MCPToolError(error_text=json.dumps({
            "code": "ELICITATION_UNSUPPORTED",
            "message": "Missing required shipment fields",
            "missing": [
                {"dot_path": "Shipment.Shipper.Name", "flat_key": "shipper_name", "prompt": "Shipper name"},
                {"dot_path": "Shipment.ShipTo.Name", "flat_key": "ship_to_name", "prompt": "Recipient name"},
            ],
        }))
        ups_error = client._translate_error(error)

        assert ups_error.code == "E-2010"
        assert "Shipper name" in ups_error.message
        assert "Recipient name" in ups_error.message
        assert "2" in ups_error.message  # count

    @pytest.mark.asyncio
    async def test_interactive_off_denies_create_shipment(self):
        """With interactive=False: hook denies before error translation runs."""
        hook = create_shipping_hook(interactive_shipping=False)
        hook_result = await hook(
            {
                "tool_name": "mcp__ups__create_shipment",
                "tool_input": {"request_body": {"Shipment": {}}},
            },
            "test-tool-id",
            None,
        )
        assert "deny" in str(hook_result)
        assert "Interactive shipping is disabled" in str(hook_result)

    @pytest.mark.asyncio
    async def test_batch_tools_unaffected_by_mode(self):
        """Batch tools (ship_command_pipeline etc.) work regardless of mode."""
        hook = create_shipping_hook(interactive_shipping=False)

        # rate_shipment is not gated
        result = await hook(
            {"tool_name": "mcp__ups__rate_shipment", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}

        # track_package is not gated
        result = await hook(
            {"tool_name": "mcp__ups__track_package", "tool_input": {}},
            "test-id",
            None,
        )
        assert result == {}
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/orchestrator/agent/test_interactive_mode.py -v`
Expected: PASS (after Tasks 5 and 6 are done)

**Step 3: Commit**

```bash
git add tests/orchestrator/agent/test_interactive_mode.py
git commit -m "$(cat <<'EOF'
test: add behavior-level test for interactive shipping mode

Asserts runtime behavior: hook allows/denies based on flag, _translate_error
produces E-2010 from missing[] payloads, batch tools unaffected.
EOF
)"
```

---

### Task 8: Frontend — shadcn/ui Switch Component

**Files:**
- Create: `frontend/src/components/ui/switch.tsx`

**Step 1: Add the Switch primitive**

```tsx
/**
 * Switch component — shadcn/ui primitive.
 *
 * A toggle switch for boolean state. Uses Radix UI Switch under the hood.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';

export interface SwitchProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ className, checked = false, onCheckedChange, ...props }, ref) => {
    return (
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        ref={ref}
        onClick={() => onCheckedChange?.(!checked)}
        className={cn(
          'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent shadow-sm transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          'disabled:cursor-not-allowed disabled:opacity-50',
          checked ? 'bg-primary' : 'bg-slate-700',
          className,
        )}
        {...props}
      >
        <span
          className={cn(
            'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
            checked ? 'translate-x-4' : 'translate-x-0',
          )}
        />
      </button>
    );
  },
);

Switch.displayName = 'Switch';

export { Switch };
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/ui/switch.tsx
git commit -m "feat(ui): add Switch toggle component (shadcn/ui primitive)"
```

---

### Task 9: Frontend — State + API + Hook Changes

**Files:**
- Modify: `frontend/src/hooks/useAppState.tsx:14-205`
- Modify: `frontend/src/types/api.ts:570-572`
- Modify: `frontend/src/lib/api.ts:348-358`
- Modify: `frontend/src/hooks/useConversation.ts:52-200`

**Step 1: Add `interactiveShipping` to AppState**

In `frontend/src/hooks/useAppState.tsx`:

Add to `AppState` interface:
```typescript
interactiveShipping: boolean;
setInteractiveShipping: (enabled: boolean) => void;
```

Add state with localStorage persistence (same pattern as warningPreference):
```typescript
const [interactiveShipping, setInteractiveShippingState] = React.useState<boolean>(() => {
  return localStorage.getItem('shipagent_interactive_shipping') === 'true';
});

const setInteractiveShipping = React.useCallback((enabled: boolean) => {
  setInteractiveShippingState(enabled);
  localStorage.setItem('shipagent_interactive_shipping', String(enabled));
}, []);
```

Add to `value` object and export type.

**Step 2: Update API types and client**

In `frontend/src/types/api.ts`, update `CreateConversationResponse`:
```typescript
export interface CreateConversationResponse {
  session_id: string;
  interactive_shipping: boolean;
}
```

In `frontend/src/lib/api.ts`, update `createConversation`:
```typescript
export async function createConversation(
  options?: { interactive_shipping?: boolean },
): Promise<CreateConversationResponse> {
  const response = await fetch(`${API_BASE}/conversations/`, {
    method: 'POST',
    headers: options ? { 'Content-Type': 'application/json' } : undefined,
    body: options ? JSON.stringify(options) : undefined,
  });
  return parseResponse<CreateConversationResponse>(response);
}
```

**Step 3: Update useConversation to accept and pass interactive_shipping**

In `frontend/src/hooks/useConversation.ts`:

Add `sessionGeneration` ref for stale-event guard:
```typescript
const sessionGenerationRef = useRef(0);
```

Update `ensureSession` to accept `interactiveShipping`:
```typescript
const ensureSession = useCallback(async (interactiveShipping: boolean): Promise<string> => {
  if (sessionIdRef.current) {
    return sessionIdRef.current;
  }
  const resp = await createConversation({ interactive_shipping: interactiveShipping });
  const sid = resp.session_id;
  setSessionId(sid);
  sessionIdRef.current = sid;
  connectSSE(sid);
  return sid;
}, [connectSSE]);
```

Update `sendMessage` to accept `interactiveShipping`:
```typescript
const sendMessage = useCallback(async (content: string, interactiveShipping: boolean = false) => {
  // ...existing logic, pass interactiveShipping to ensureSession
  const sid = await ensureSession(interactiveShipping);
  // ...
}, [ensureSession]);
```

Update `reset()` to increment generation:
```typescript
const reset = useCallback(async () => {
  sessionGenerationRef.current += 1;
  // ...existing cleanup
}, []);
```

Add generation guard in SSE `onmessage`:
```typescript
const currentGen = sessionGenerationRef.current;
// ... inside onmessage:
if (sessionGenerationRef.current !== currentGen) return; // stale event
```

**Step 4: Type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: Some errors from CommandCenter.tsx (sendMessage signature changed) — will fix in Task 10

**Step 5: Commit**

```bash
git add frontend/src/hooks/useAppState.tsx frontend/src/types/api.ts frontend/src/lib/api.ts frontend/src/hooks/useConversation.ts
git commit -m "$(cat <<'EOF'
feat(frontend): add interactiveShipping state, API, and session lifecycle

- useAppState: interactiveShipping persisted to localStorage
- api.ts: createConversation accepts interactive_shipping option
- useConversation: passes flag to session creation, stale-event guard
- Types updated for CreateConversationResponse echo field
EOF
)"
```

---

### Task 10: Frontend — Header Toggle + CommandCenter Wiring

**Files:**
- Modify: `frontend/src/components/layout/Header.tsx:1-31`
- Modify: `frontend/src/components/CommandCenter.tsx:33-415`
- Modify: `frontend/src/components/command-center/presentation.tsx:1080+` (WelcomeMessage)

**Step 1: Add toggle to Header**

```tsx
import { Package } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { useAppState } from '@/hooks/useAppState';

export function Header() {
  const { interactiveShipping, setInteractiveShipping } = useAppState();

  return (
    <header className="app-header">
      <div className="h-[1px] bg-gradient-to-r from-transparent via-accent/50 to-transparent" />
      <div className="container-wide h-12 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Package className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-semibold text-foreground">ShipAgent</span>
        </div>
        <div className="flex items-center gap-2">
          <label
            htmlFor="interactive-shipping-toggle"
            className="text-xs text-slate-400 cursor-pointer select-none"
          >
            Interactive Shipping
          </label>
          <Switch
            id="interactive-shipping-toggle"
            checked={interactiveShipping}
            onCheckedChange={setInteractiveShipping}
          />
        </div>
      </div>
    </header>
  );
}
```

Note: The actual toggle-reset-confirm logic happens in CommandCenter.tsx which watches for changes. The Header just sets state.

**Step 2: Wire toggle into CommandCenter**

In `CommandCenter.tsx`:

Add `interactiveShipping` to destructured useAppState:
```typescript
const { ..., interactiveShipping } = useAppState();
```

Add effect to handle toggle changes (with confirm dialog + race-safe reset):
```typescript
const prevInteractiveRef = React.useRef(interactiveShipping);
const [isResettingSession, setIsResettingSession] = React.useState(false);

React.useEffect(() => {
  if (prevInteractiveRef.current === interactiveShipping) return;
  prevInteractiveRef.current = interactiveShipping;

  // Only reset if there's an active session
  if (!conv.sessionId) return;

  // Confirm if there's in-progress work
  if (preview || conv.isProcessing) {
    const confirmed = window.confirm(
      'Switching mode resets your current session. Continue?'
    );
    if (!confirmed) {
      // Revert toggle
      const { setInteractiveShipping } = useAppState();
      // Can't call hook in effect — use the setter from destructured state
      return;
    }
  }

  // Race-safe reset
  setIsResettingSession(true);
  conv.reset().finally(() => setIsResettingSession(false));
}, [interactiveShipping]);
```

Update `sendMessage` call to pass `interactiveShipping`:
```typescript
conv.sendMessage(inputValue, interactiveShipping);
```

Update placeholder text:
```typescript
placeholder={
  interactiveShipping && !hasDataSource
    ? 'Describe your shipment details for interactive creation...'
    : interactiveShipping && hasDataSource
      ? 'Describe one shipment or enter a batch command...'
      : !hasDataSource
        ? 'Connect a data source to begin...'
        : 'Enter a shipping command...'
}
```

Add interactive mode banner near ActiveSourceBanner when appropriate. When interactive is ON and source is connected, show a small indicator.

**Step 3: Update WelcomeMessage**

In `presentation.tsx`, update `WelcomeMessage` to accept and use `interactiveShipping`:

```tsx
export function WelcomeMessage({
  onExampleClick,
  interactiveShipping = false,
}: {
  onExampleClick?: (text: string) => void;
  interactiveShipping?: boolean;
}) {
  // ... existing logic
  // Add interactive examples when enabled:
  // "Ship a 5lb box to John Smith at 123 Main St via Ground"
}
```

**Step 4: Type check and build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: No errors, build succeeds

**Step 5: Commit**

```bash
git add frontend/src/components/layout/Header.tsx frontend/src/components/CommandCenter.tsx frontend/src/components/command-center/presentation.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): header toggle + CommandCenter wiring for interactive mode

- Header: Switch toggle with label, always visible
- CommandCenter: race-safe reset on toggle, confirm for in-progress work,
  context-aware placeholder text, interactiveShipping passed to sendMessage
- WelcomeMessage: interactive-mode example commands
EOF
)"
```

---

### Task 11: Full Test Suite Verification

**Step 1: Run backend tests**

Run: `python3 -m pytest tests/errors/ tests/orchestrator/ tests/services/ tests/api/test_conversations_interactive.py -v --tb=short`
Expected: All pass (2 pre-existing failures in test_config.py acceptable)

**Step 2: Run frontend type check + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: No errors

**Step 3: Run integration matrix verification (manual)**

Document the 4 scenarios to test when backend is running:
1. Toggle OFF + "ship a box to John Smith" → agent explains batch-only mode
2. Toggle ON + "ship a 5lb box to 123 Main St" (partial details) → agent asks for missing fields
3. Toggle ON + "ship all California orders via Ground" → routes to batch pipeline
4. Toggle ON + "ship orders" (ambiguous, source connected) → agent asks clarifying question

**Step 4: Commit verification results**

No code changes — just confirm all tests pass.

---

## Summary

| Task | Scope | Key Files |
|------|-------|-----------|
| 1. UPS MCP Repin | Build | `pyproject.toml`, `uv.lock` |
| 2. Schema + Session | Backend | `schemas_conversations.py`, `agent_session_manager.py` |
| 3. Route Wiring | Backend | `conversations.py` |
| 4. System Prompt | Backend | `system_prompt.py` |
| 5. Hook Factory | Backend | `hooks.py`, `client.py` |
| 6. Reason Preservation | Backend | `ups_mcp_client.py` |
| 7. Behavior Test | Test | `test_interactive_mode.py` |
| 8. Switch Component | Frontend | `ui/switch.tsx` |
| 9. State + API + Hook | Frontend | `useAppState.tsx`, `api.ts`, `useConversation.ts`, `types/api.ts` |
| 10. Header + Wiring | Frontend | `Header.tsx`, `CommandCenter.tsx`, `presentation.tsx` |
| 11. Full Verification | Test | All files |
