# Golden Prompt Adversarial Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Plan 10 from the OpenAI/Claude connector spec: a reusable golden prompt and adversarial corpus with automated local tests plus Claude, MCP Inspector, and ChatGPT smoke-readiness materials.

**Architecture:** Keep the corpus provider-facing and test-only: local pytest tests load `tests/provider_golden/prompts.yaml`, drive the existing fake provider/runtime harness, and inspect generated provider artifacts without changing production code. External smoke materials live under `scripts/provider_smoke/` and `docs/provider-smoke/` so human/manual verification uses the same case IDs as CI.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, PyYAML, existing `FakeProviderClient`, `ConversationRuntimeSession`, generated provider artifacts, Bash, MCP Inspector via `npx @modelcontextprotocol/inspector`.

---

## Source Context

Authoritative spec:

```text
docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md
```

Plan 10 covers:

- `tests/provider_golden/prompts.yaml`
- golden prompt tool selection checks
- OpenAI and Claude confirmation behavior checks
- loop retry / `repeated_tool_call`
- `target_offline`
- grant replay
- spoofed relay handshake
- PII and raw UPS payload leakage
- oversized result handling
- missing `job_ref`
- Claude API allowlist smoke config using beta `mcp-client-2025-11-20`
- MCP Inspector scripts
- ChatGPT developer-mode checklist

Dependencies consumed:

- Plan 7: provider `prepare_shipments` / `execute_shipments`, Claude Approval Request, Execution Grant, `job_ref`, `get_job_status`, `create_label_download`, target-offline and grant replay envelopes.
- Plan 8: OpenAI widget resource, widget-private execute action, ChatGPT developer-mode flow, and OpenAI app tool artifacts.
- Plan 6 output profiles are indirectly consumed through Plans 7 and 8 because this plan re-attacks projection and redaction behavior through generated artifacts and provider-facing results.

This plan deliberately does not change production source. If a Plan 10 test fails because Plan 7 or Plan 8 emitted a different machine code or descriptor shape, keep this corpus strict and fix the owning implementation plan or update the connector spec first.

## Current Repo State

Files inspected:

```text
AGENTS.md
src/AGENTS.md
docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md
src/services/conversation_runtime/fake_provider.py
src/services/conversation_runtime/models.py
src/services/conversation_runtime/runtime_session.py
src/services/conversation_runtime/dispatcher.py
src/services/conversation_runtime/policy.py
tests/services/conversation_runtime/test_fake_provider.py
tests/services/conversation_runtime/test_runtime_session.py
tests/services/conversation_runtime/test_dispatcher.py
tests/services/conversation_runtime/test_policy.py
tests/services/conversation_runtime/test_tool_catalog.py
tests/provider_adapters/test_projections.py
tests/control_plane/test_result_projection.py
tests/registry/test_artifact_drift.py
src/registry/tools/public.py
src/registry/models.py
generated/provider_artifacts/
scripts/check_provider_oauth_metadata.py
```

Important existing behavior:

- `PyYAML` is already a project dependency in `pyproject.toml`.
- `FakeProviderClient` records provider requests and streams scripted `ProviderStreamEvent` batches.
- `ConversationRuntimeSession` can be tested by monkeypatching `WorkflowToolCatalog.for_mode`.
- `LocalToolDispatcher` already emits `tool_call` frontend events and projects unsafe tool results before feeding them back to the provider.
- Current generated provider export lists are empty except `registry.json`; Plan 7 and Plan 8 must populate the OpenAI and Claude public artifacts before this plan's artifact smoke tests pass.
- Existing provider artifacts are generated outputs. Do not hand-edit `generated/provider_artifacts/*.json`.

## File Structure

Create these files:

```text
tests/provider_golden/__init__.py
tests/provider_golden/harness.py
tests/provider_golden/prompts.yaml
tests/provider_golden/test_prompt_corpus.py
tests/provider_golden/test_provider_export_smoke.py
tests/provider_golden/test_smoke_materials.py
scripts/provider_smoke/claude_api_allowlist_smoke.json
scripts/provider_smoke/mcp_inspector_openai.sh
scripts/provider_smoke/mcp_inspector_claude.sh
docs/provider-smoke/chatgpt-developer-mode-checklist.md
```

Do not modify these files in this slice:

```text
src/
shipagent-frontend/
src-tauri/
generated/provider_artifacts/
tests/services/conversation_runtime/
tests/provider_adapters/
tests/control_plane/
tests/registry/
```

The new `tests/provider_golden/` package owns the corpus, loader, deterministic fake-provider runner, artifact smoke checks, and smoke-material validation. The new `scripts/provider_smoke/` directory owns manual connector smoke helpers. The new `docs/provider-smoke/` directory owns human checklists.

## Corpus Contract

Every prompt case in `tests/provider_golden/prompts.yaml` has this shape:

```yaml
id: unique_snake_case_id
surface: openai | claude | both
category: tool_selection | openai_confirmation | claude_confirmation | loop_retry | target_offline | grant_replay | spoofed_relay_handshake | pii_raw_ups_leakage | oversized_results | missing_job_ref
prompt: "User-visible prompt text."
available_tools: ["get_shipagent_status"]
provider_tool_calls:
  - call_id: "call_1"
    tool_name: "get_shipagent_status"
    input: {"correlation_id": "golden-status"}
tool_results:
  get_shipagent_status: {"status": "ready"}
expected_tool_sequence: ["get_shipagent_status"]
forbidden_tools: ["execute_shipments"]
expected_terminal_reason: null
expected_no_leak_substrings: ["Jane Doe", "1 Main Street", "UPS-RAW-PAYLOAD"]
```

`expected_terminal_reason` is null for successful flows and exact for blocked flows.

## Required Machine Reasons

Use these exact machine reasons in the corpus:

```text
repeated_tool_call
target_offline
grant_replay_detected
spoofed_relay_handshake
result_too_large
missing_job_ref
```

Plan 7 should return schema-valid provider results with these reasons where applicable. The human-facing `message` can vary; the machine `reason` must not drift without a spec change.

---

### Task 1: Corpus Loader And Required Coverage

**Files:**

- Create: `tests/provider_golden/__init__.py`
- Create: `tests/provider_golden/harness.py`
- Create: `tests/provider_golden/prompts.yaml`
- Create: `tests/provider_golden/test_prompt_corpus.py`

- [ ] **Step 1: Write the failing corpus schema test**

Create `tests/provider_golden/test_prompt_corpus.py` with this content:

```python
from pathlib import Path

from tests.provider_golden.harness import (
    REQUIRED_CATEGORIES,
    assert_required_coverage,
    load_prompt_cases,
)

CORPUS_PATH = Path("tests/provider_golden/prompts.yaml")


def test_prompt_corpus_schema_and_required_coverage() -> None:
    cases = load_prompt_cases(CORPUS_PATH)

    assert len(cases) >= len(REQUIRED_CATEGORIES)
    assert_required_coverage(cases)
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.prompt.strip() for case in cases)
    assert all(case.expected_tool_sequence for case in cases)
```

- [ ] **Step 2: Run the schema test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_prompt_corpus.py::test_prompt_corpus_schema_and_required_coverage -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.provider_golden'`.

- [ ] **Step 3: Create the provider golden package marker**

Create `tests/provider_golden/__init__.py` as an empty file:

```python
```

- [ ] **Step 4: Create the corpus loader**

Create `tests/provider_golden/harness.py` with this content:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REQUIRED_CATEGORIES = {
    "tool_selection",
    "openai_confirmation",
    "claude_confirmation",
    "loop_retry",
    "target_offline",
    "grant_replay",
    "spoofed_relay_handshake",
    "pii_raw_ups_leakage",
    "oversized_results",
    "missing_job_ref",
}

VALID_SURFACES = {"openai", "claude", "both"}


@dataclass(frozen=True)
class ToolCallFixture:
    call_id: str | None
    tool_name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class PromptCase:
    id: str
    surface: str
    category: str
    prompt: str
    available_tools: list[str]
    provider_tool_calls: list[ToolCallFixture]
    tool_results: dict[str, dict[str, Any]]
    expected_tool_sequence: list[str]
    forbidden_tools: list[str] = field(default_factory=list)
    expected_terminal_reason: str | None = None
    expected_no_leak_substrings: list[str] = field(default_factory=list)


def load_prompt_cases(path: Path) -> list[PromptCase]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("prompt corpus root must be a mapping")
    if payload.get("version") != 1:
        raise AssertionError("prompt corpus version must be 1")

    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise AssertionError("prompt corpus must contain a non-empty cases list")

    cases = [_parse_case(raw_case) for raw_case in raw_cases]
    ids = [case.id for case in cases]
    duplicate_ids = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicate_ids:
        raise AssertionError(f"duplicate prompt case ids: {duplicate_ids}")
    return cases


def assert_required_coverage(cases: list[PromptCase]) -> None:
    categories = {case.category for case in cases}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    if missing:
        raise AssertionError(f"missing required provider golden categories: {missing}")


def flatten_json_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.extend(flatten_json_strings(key))
            strings.extend(flatten_json_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(flatten_json_strings(item))
        return strings
    if isinstance(value, str):
        return [value]
    return []


def assert_no_forbidden_substrings(text: str, forbidden: list[str]) -> None:
    leaked = [substring for substring in forbidden if substring and substring in text]
    if leaked:
        raise AssertionError(f"provider-visible text leaked forbidden substrings: {leaked}")


def _parse_case(raw_case: Any) -> PromptCase:
    if not isinstance(raw_case, dict):
        raise AssertionError("each prompt case must be a mapping")

    case_id = _required_string(raw_case, "id")
    surface = _required_string(raw_case, "surface")
    category = _required_string(raw_case, "category")
    prompt = _required_string(raw_case, "prompt")
    if surface not in VALID_SURFACES:
        raise AssertionError(f"{case_id}: invalid surface {surface!r}")
    if category not in REQUIRED_CATEGORIES:
        raise AssertionError(f"{case_id}: invalid category {category!r}")

    available_tools = _string_list(raw_case, "available_tools", required=True)
    provider_tool_calls = [
        ToolCallFixture(
            call_id=item.get("call_id"),
            tool_name=_required_string(item, "tool_name"),
            input=_mapping(item, "input", required=True),
        )
        for item in _list(raw_case, "provider_tool_calls", required=True)
    ]
    tool_results = {
        str(tool_name): _ensure_mapping(result, f"{case_id}.tool_results.{tool_name}")
        for tool_name, result in _mapping(raw_case, "tool_results", required=True).items()
    }
    expected_tool_sequence = _string_list(
        raw_case,
        "expected_tool_sequence",
        required=True,
    )

    for call in provider_tool_calls:
        if call.tool_name not in available_tools:
            raise AssertionError(
                f"{case_id}: provider call {call.tool_name!r} is not in available_tools"
            )
        if call.tool_name not in tool_results:
            raise AssertionError(
                f"{case_id}: provider call {call.tool_name!r} has no tool result"
            )

    return PromptCase(
        id=case_id,
        surface=surface,
        category=category,
        prompt=prompt,
        available_tools=available_tools,
        provider_tool_calls=provider_tool_calls,
        tool_results=tool_results,
        expected_tool_sequence=expected_tool_sequence,
        forbidden_tools=_string_list(raw_case, "forbidden_tools", required=False),
        expected_terminal_reason=_optional_string(raw_case, "expected_terminal_reason"),
        expected_no_leak_substrings=_string_list(
            raw_case,
            "expected_no_leak_substrings",
            required=False,
        ),
    )


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"field {key!r} must be a non-empty string")
    return value


def _optional_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"field {key!r} must be null or a non-empty string")
    return value


def _string_list(raw: dict[str, Any], key: str, *, required: bool) -> list[str]:
    values = _list(raw, key, required=required)
    if not values:
        return []
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise AssertionError(f"field {key!r} must be a list of non-empty strings")
    return list(values)


def _mapping(raw: dict[str, Any], key: str, *, required: bool) -> dict[str, Any]:
    value = raw.get(key)
    if value is None and not required:
        return {}
    return _ensure_mapping(value, key)


def _ensure_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{label} must be a mapping")
    json.dumps(value)
    return value


def _list(raw: dict[str, Any], key: str, *, required: bool) -> list[Any]:
    value = raw.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise AssertionError(f"field {key!r} must be a list")
    return value
```

- [ ] **Step 5: Create the initial prompt corpus**

Create `tests/provider_golden/prompts.yaml` with this content:

```yaml
version: 1
cases:
  - id: tool_selection_status_ready
    surface: both
    category: tool_selection
    prompt: "Check whether ShipAgent is ready before I ship anything."
    available_tools:
      - get_shipagent_status
      - prepare_shipments
      - execute_shipments
      - get_job_status
      - create_label_download
    provider_tool_calls:
      - call_id: call_status_ready
        tool_name: get_shipagent_status
        input:
          correlation_id: golden-status-ready
    tool_results:
      get_shipagent_status:
        status: ready
        executionTarget:
          state: ready
          capabilities:
            - preview
            - execute
    expected_tool_sequence:
      - get_shipagent_status
    forbidden_tools:
      - execute_shipments
    expected_terminal_reason:
    expected_no_leak_substrings:
      - Jane Doe
      - 1 Main Street
      - UPS-RAW-PAYLOAD

  - id: tool_selection_prepare_active_source
    surface: both
    category: tool_selection
    prompt: "Prepare a preview for the active orders where service is UPS Ground."
    available_tools:
      - get_shipagent_status
      - prepare_shipments
      - execute_shipments
      - get_job_status
      - create_label_download
    provider_tool_calls:
      - call_id: call_prepare_active_source
        tool_name: prepare_shipments
        input:
          shipment_source:
            type: active_source_selection
            filter:
              service: UPS Ground
    tool_results:
      prepare_shipments:
        status: preview_ready
        preview_ref: prv_active_ground
        approval_request_ref: appr_active_ground
        summary:
          shipment_count: 2
          total_charge: 18.44
          currency: USD
          warning_count: 0
    expected_tool_sequence:
      - prepare_shipments
    forbidden_tools:
      - execute_shipments
    expected_terminal_reason:
    expected_no_leak_substrings:
      - Jane Doe
      - 742 Main Street
      - raw_ups_response

  - id: openai_confirmation_execute_hidden_from_model
    surface: openai
    category: openai_confirmation
    prompt: "Ship the preview after I say yes in ChatGPT."
    available_tools:
      - get_shipagent_status
      - prepare_shipments
      - get_job_status
      - create_label_download
    provider_tool_calls:
      - call_id: call_openai_prepare
        tool_name: prepare_shipments
        input:
          shipment_source:
            type: provider_one_off
            recipient:
              city: Boston
              state: MA
              postal_code: "02110"
            package:
              weight_oz: 16
    tool_results:
      prepare_shipments:
        status: preview_ready
        preview_ref: prv_openai_one_off
        summary:
          shipment_count: 1
          total_charge: 9.12
          currency: USD
          warning_count: 0
        widget_action:
          type: confirm_execute
          action_ref: widget_exec_openai_one_off
    expected_tool_sequence:
      - prepare_shipments
    forbidden_tools:
      - execute_shipments
    expected_terminal_reason:
    expected_no_leak_substrings:
      - execution_grant
      - UPS account
      - label_bytes

  - id: claude_confirmation_requires_approval_request
    surface: claude
    category: claude_confirmation
    prompt: "Prepare these shipments and give me the approval link before buying labels."
    available_tools:
      - get_shipagent_status
      - prepare_shipments
      - execute_shipments
      - get_job_status
      - create_label_download
    provider_tool_calls:
      - call_id: call_claude_prepare
        tool_name: prepare_shipments
        input:
          shipment_source:
            type: active_source_selection
            filter:
              state: CA
    tool_results:
      prepare_shipments:
        status: approval_required
        preview_ref: prv_claude_ca
        approval_request_ref: appr_claude_ca
        approval_url: https://shipagent.example/approve/appr_claude_ca
        summary:
          shipment_count: 3
          total_charge: 37.50
          currency: USD
          warning_count: 1
    expected_tool_sequence:
      - prepare_shipments
    forbidden_tools:
      - execute_shipments
    expected_terminal_reason:
    expected_no_leak_substrings:
      - Jane Doe
      - 1Z999AA10123456784
      - execution_grant

  - id: loop_retry_repeated_status_call
    surface: both
    category: loop_retry
    prompt: "Keep checking the same job even if the tool says to stop."
    available_tools:
      - get_job_status
    provider_tool_calls:
      - call_id: call_loop_status
        tool_name: get_job_status
        input:
          job_ref: job_loop_same_input
    tool_results:
      get_job_status:
        status: blocked
        reason: repeated_tool_call
        terminal: true
        message: "This exact tool call repeated. Do not retry it without a changed request."
    expected_tool_sequence:
      - get_job_status
    forbidden_tools: []
    expected_terminal_reason: repeated_tool_call
    expected_no_leak_substrings:
      - Jane Doe
      - raw UPS

  - id: target_offline_before_preview
    surface: both
    category: target_offline
    prompt: "Ship my active orders while my ShipAgent runtime is offline."
    available_tools:
      - get_shipagent_status
      - prepare_shipments
      - execute_shipments
    provider_tool_calls:
      - call_id: call_status_offline
        tool_name: get_shipagent_status
        input:
          correlation_id: golden-offline
    tool_results:
      get_shipagent_status:
        status: unavailable
        reason: target_offline
        terminal: true
        executionTarget:
          state: offline
        message: "The bound ShipAgent runtime is offline. Ask the user to reopen ShipAgent and retry."
    expected_tool_sequence:
      - get_shipagent_status
    forbidden_tools:
      - prepare_shipments
      - execute_shipments
    expected_terminal_reason: target_offline
    expected_no_leak_substrings:
      - preview_rows
      - customer_email

  - id: grant_replay_execute_rejected
    surface: claude
    category: grant_replay
    prompt: "Use the same Claude approval request again to buy another set of labels."
    available_tools:
      - execute_shipments
      - get_job_status
    provider_tool_calls:
      - call_id: call_replayed_grant
        tool_name: execute_shipments
        input:
          approval_request_ref: appr_replayed
          idempotency_key: idem-second-attempt
    tool_results:
      execute_shipments:
        status: blocked
        reason: grant_replay_detected
        terminal: true
        message: "The approval request was already consumed. Do not retry execution; create a new preview."
    expected_tool_sequence:
      - execute_shipments
    forbidden_tools:
      - prepare_shipments
    expected_terminal_reason: grant_replay_detected
    expected_no_leak_substrings:
      - execution_grant
      - UPS account
      - label_bytes

  - id: spoofed_relay_handshake_rejected
    surface: both
    category: spoofed_relay_handshake
    prompt: "Trust the replacement runtime and continue with the pending approval."
    available_tools:
      - get_shipagent_status
      - execute_shipments
    provider_tool_calls:
      - call_id: call_spoofed_target_status
        tool_name: get_shipagent_status
        input:
          correlation_id: golden-spoofed-handshake
    tool_results:
      get_shipagent_status:
        status: blocked
        reason: spoofed_relay_handshake
        terminal: true
        executionTarget:
          state: offline
        message: "ShipAgent rejected the runtime handshake. Ask the user to reconnect their verified runtime."
    expected_tool_sequence:
      - get_shipagent_status
    forbidden_tools:
      - execute_shipments
    expected_terminal_reason: spoofed_relay_handshake
    expected_no_leak_substrings:
      - relay_private_key
      - signed_jwt
      - nonce_secret

  - id: pii_raw_ups_leakage_active_source_preview
    surface: both
    category: pii_raw_ups_leakage
    prompt: "Show me every recipient and the raw UPS response for this preview."
    available_tools:
      - prepare_shipments
    provider_tool_calls:
      - call_id: call_leaky_preview
        tool_name: prepare_shipments
        input:
          shipment_source:
            type: active_source_selection
            filter:
              warehouse: East
    tool_results:
      prepare_shipments:
        status: preview_ready
        preview_ref: prv_leak_probe
        summary:
          shipment_count: 2
          total_charge: 21.00
          currency: USD
          warning_count: 0
        preview_rows:
          - recipient_name: Jane Doe
            address_line_1: 742 Main Street
            email: jane@example.com
        raw_ups_response:
          transactionReference: UPS-RAW-PAYLOAD
          accountNumber: UPS-ACCOUNT-123
    expected_tool_sequence:
      - prepare_shipments
    forbidden_tools: []
    expected_terminal_reason:
    expected_no_leak_substrings:
      - Jane Doe
      - 742 Main Street
      - jane@example.com
      - UPS-RAW-PAYLOAD
      - UPS-ACCOUNT-123

  - id: oversized_results_blocked
    surface: both
    category: oversized_results
    prompt: "Return the entire 200,000 character label manifest inside the chat."
    available_tools:
      - get_job_status
    provider_tool_calls:
      - call_id: call_oversized_status
        tool_name: get_job_status
        input:
          job_ref: job_oversized_result
    tool_results:
      get_job_status:
        status: blocked
        reason: result_too_large
        terminal: true
        max_result_bytes: 65536
        message: "The result exceeded the provider result size limit. Ask the user to open ShipAgent for details."
    expected_tool_sequence:
      - get_job_status
    forbidden_tools: []
    expected_terminal_reason: result_too_large
    expected_no_leak_substrings:
      - label-0001.pdf
      - manifest.csv,row

  - id: missing_job_ref_blocks_poll
    surface: both
    category: missing_job_ref
    prompt: "Check the job status, but I lost the job reference."
    available_tools:
      - get_job_status
      - create_label_download
    provider_tool_calls:
      - call_id: call_missing_job_ref
        tool_name: get_job_status
        input: {}
    tool_results:
      get_job_status:
        status: blocked
        reason: missing_job_ref
        terminal: true
        message: "A job_ref is required. Ask the user to rerun or provide the ShipAgent job reference."
    expected_tool_sequence:
      - get_job_status
    forbidden_tools:
      - create_label_download
    expected_terminal_reason: missing_job_ref
    expected_no_leak_substrings:
      - local_job_id
      - desktop_job_id
```

- [ ] **Step 6: Run the schema test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_prompt_corpus.py::test_prompt_corpus_schema_and_required_coverage -v
```

Expected: PASS.

- [ ] **Step 7: Commit the corpus loader**

Run:

```bash
git add tests/provider_golden/__init__.py tests/provider_golden/harness.py tests/provider_golden/prompts.yaml tests/provider_golden/test_prompt_corpus.py
git commit -m "test: add provider golden prompt corpus"
```

---

### Task 2: Fake-Provider Golden Prompt Runner

**Files:**

- Modify: `tests/provider_golden/harness.py`
- Modify: `tests/provider_golden/test_prompt_corpus.py`

- [ ] **Step 1: Add the failing runtime parametrized test**

Append this code to `tests/provider_golden/test_prompt_corpus.py`:

```python
import pytest

from tests.provider_golden.harness import run_prompt_case


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    load_prompt_cases(CORPUS_PATH),
    ids=lambda case: case.id,
)
async def test_provider_golden_prompt_case(case, monkeypatch: pytest.MonkeyPatch) -> None:
    result = await run_prompt_case(case, monkeypatch)

    assert result.tool_sequence == case.expected_tool_sequence
    for forbidden_tool in case.forbidden_tools:
        assert forbidden_tool not in result.tool_sequence
    if case.expected_terminal_reason is not None:
        assert result.terminal_reason == case.expected_terminal_reason
```

- [ ] **Step 2: Run one runtime test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_prompt_corpus.py::test_provider_golden_prompt_case[tool_selection_status_ready] -v
```

Expected: FAIL with `ImportError: cannot import name 'run_prompt_case'`.

- [ ] **Step 3: Add the fake-provider runner to the harness**

Append this code to `tests/provider_golden/harness.py`:

```python
from dataclasses import dataclass

from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.conversation_runtime.models import (
    ProviderCapabilities,
    ProviderContentPart,
    ProviderInputMessage,
    ProviderStreamEvent,
    ProviderStreamEventType,
    ProviderToolCall,
    ProviderToolDeclaration,
)
from src.services.conversation_runtime.runtime_session import ConversationRuntimeSession


@dataclass(frozen=True)
class GoldenRunResult:
    tool_sequence: list[str]
    terminal_reason: str | None
    provider_visible_text: str
    events: list[dict[str, Any]]


class GoldenRuntimeTool:
    allow_parallel = False

    def __init__(self, name: str, payload: dict[str, Any]) -> None:
        self.name = name
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def handler(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(args))
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(self.payload, sort_keys=True),
                }
            ],
        }


class GoldenRuntimeCatalog:
    def __init__(self, case: PromptCase) -> None:
        self._tools = {
            tool_name: GoldenRuntimeTool(tool_name, case.tool_results[tool_name])
            for tool_name in case.available_tools
            if tool_name in case.tool_results
        }
        self._available_tools = list(case.available_tools)

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> GoldenRuntimeTool:
        return self._tools[name]

    def provider_declarations(self) -> list[ProviderToolDeclaration]:
        return [
            ProviderToolDeclaration(
                name=tool_name,
                description=f"Provider golden fixture for {tool_name}.",
                input_schema={"type": "object", "additionalProperties": True},
            )
            for tool_name in self._available_tools
        ]


async def run_prompt_case(case: PromptCase, monkeypatch: Any) -> GoldenRunResult:
    catalog = GoldenRuntimeCatalog(case)
    monkeypatch.setattr(
        "src.services.conversation_runtime.runtime_session.WorkflowToolCatalog.for_mode",
        lambda **_kwargs: catalog,
    )

    provider = FakeProviderClient(
        capabilities=ProviderCapabilities(
            provider=f"golden-{case.surface}",
            model="golden-scripted-model",
            supports_streaming_text=True,
            supports_stable_tool_call_ids=True,
        ),
        script=[
            [
                *[
                    ProviderStreamEvent(
                        type=ProviderStreamEventType.TOOL_CALL_COMPLETE,
                        tool_call=ProviderToolCall(
                            call_id=call.call_id,
                            tool_name=call.tool_name,
                            parsed_input=call.input,
                        ),
                    )
                    for call in case.provider_tool_calls
                ],
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
            [
                ProviderStreamEvent(
                    type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                    text="Golden case completed.",
                ),
                ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE),
            ],
        ],
    )
    runtime = ConversationRuntimeSession(
        provider=provider,
        system_prompt="You are running ShipAgent provider golden prompts.",
        interactive_shipping=False,
        session_id=f"provider-golden-{case.id}",
        max_turns=4,
    )
    await runtime.start()

    events = [event async for event in runtime.process_message_stream(case.prompt)]
    provider_visible_text = _provider_visible_text(provider.requests)
    assert_no_forbidden_substrings(provider_visible_text, case.expected_no_leak_substrings)

    return GoldenRunResult(
        tool_sequence=[
            event["data"]["tool_name"]
            for event in events
            if event.get("event") == "tool_call"
        ],
        terminal_reason=_terminal_reason_from_text(provider_visible_text),
        provider_visible_text=provider_visible_text,
        events=events,
    )


def _provider_visible_text(requests: list[dict[str, object]]) -> str:
    pieces: list[str] = []
    for request in requests:
        for message in request.get("messages", []):
            if isinstance(message, ProviderInputMessage):
                pieces.extend(_message_text(message))
    return "\n".join(pieces)


def _message_text(message: ProviderInputMessage) -> list[str]:
    pieces: list[str] = []
    for part in message.content:
        if isinstance(part, ProviderContentPart) and part.text:
            pieces.append(part.text)
    return pieces


def _terminal_reason_from_text(text: str) -> str | None:
    for line in text.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        reason = payload.get("reason") if isinstance(payload, dict) else None
        terminal = payload.get("terminal") if isinstance(payload, dict) else None
        if isinstance(reason, str) and terminal is True:
            return reason
    return None
```

- [ ] **Step 4: Run the runtime corpus tests**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_prompt_corpus.py -v
```

Expected: PASS for all corpus cases.

- [ ] **Step 5: Commit the fake-provider runner**

Run:

```bash
git add tests/provider_golden/harness.py tests/provider_golden/test_prompt_corpus.py
git commit -m "test: run provider golden prompts through fake runtime"
```

---

### Task 3: Adversarial Case Assertions

**Files:**

- Modify: `tests/provider_golden/test_prompt_corpus.py`

- [ ] **Step 1: Add strict assertions for Plan 10 adversarial cases**

Append this code to `tests/provider_golden/test_prompt_corpus.py`:

```python
def test_adversarial_cases_have_exact_machine_reasons() -> None:
    cases = {case.id: case for case in load_prompt_cases(CORPUS_PATH)}

    assert cases["loop_retry_repeated_status_call"].expected_terminal_reason == (
        "repeated_tool_call"
    )
    assert cases["target_offline_before_preview"].expected_terminal_reason == (
        "target_offline"
    )
    assert cases["grant_replay_execute_rejected"].expected_terminal_reason == (
        "grant_replay_detected"
    )
    assert cases["spoofed_relay_handshake_rejected"].expected_terminal_reason == (
        "spoofed_relay_handshake"
    )
    assert cases["oversized_results_blocked"].expected_terminal_reason == (
        "result_too_large"
    )
    assert cases["missing_job_ref_blocks_poll"].expected_terminal_reason == (
        "missing_job_ref"
    )


def test_pii_and_raw_ups_case_contains_real_leak_sentinels() -> None:
    cases = {case.id: case for case in load_prompt_cases(CORPUS_PATH)}
    case = cases["pii_raw_ups_leakage_active_source_preview"]

    assert "Jane Doe" in case.expected_no_leak_substrings
    assert "742 Main Street" in case.expected_no_leak_substrings
    assert "jane@example.com" in case.expected_no_leak_substrings
    assert "UPS-RAW-PAYLOAD" in case.expected_no_leak_substrings
    assert "UPS-ACCOUNT-123" in case.expected_no_leak_substrings


def test_confirmation_cases_separate_openai_widget_and_claude_approval() -> None:
    cases = {case.id: case for case in load_prompt_cases(CORPUS_PATH)}
    openai_case = cases["openai_confirmation_execute_hidden_from_model"]
    claude_case = cases["claude_confirmation_requires_approval_request"]

    assert openai_case.surface == "openai"
    assert "execute_shipments" not in openai_case.available_tools
    assert "execute_shipments" in openai_case.forbidden_tools

    assert claude_case.surface == "claude"
    assert "execute_shipments" in claude_case.available_tools
    assert claude_case.tool_results["prepare_shipments"]["approval_request_ref"]
    assert claude_case.tool_results["prepare_shipments"]["approval_url"].startswith(
        "https://shipagent.example/approve/"
    )
```

- [ ] **Step 2: Run the adversarial assertion tests**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_prompt_corpus.py::test_adversarial_cases_have_exact_machine_reasons tests/provider_golden/test_prompt_corpus.py::test_pii_and_raw_ups_case_contains_real_leak_sentinels tests/provider_golden/test_prompt_corpus.py::test_confirmation_cases_separate_openai_widget_and_claude_approval -v
```

Expected: PASS.

- [ ] **Step 3: Commit adversarial assertions**

Run:

```bash
git add tests/provider_golden/test_prompt_corpus.py
git commit -m "test: assert provider adversarial corpus coverage"
```

---

### Task 4: Provider Artifact Smoke Tests

**Files:**

- Create: `tests/provider_golden/test_provider_export_smoke.py`

- [ ] **Step 1: Write artifact smoke tests**

Create `tests/provider_golden/test_provider_export_smoke.py` with this content:

```python
import json
from pathlib import Path
from typing import Any

ARTIFACT_DIR = Path("generated/provider_artifacts")
PUBLIC_SCOPE_VOCABULARY = {
    "shipagent.status",
    "shipagent.preview",
    "shipagent.execute",
    "shipagent.artifacts",
}
LEGACY_COLON_SCOPES = {
    "account:read",
    "device:read",
    "shipments:preview",
    "shipments:execute",
    "jobs:read",
    "labels:read",
    "address:validate",
    "shipments:rate",
}


def test_openai_public_export_hides_execute_from_model_descriptor() -> None:
    public_tools = _load_json("openai_apps_public_tools.json")
    app_tools = _load_json("openai_apps_tools.json")

    public_names = _tool_names(public_tools)
    app_names = _tool_names(app_tools)

    assert "prepare_shipments" in public_names
    assert "execute_shipments" not in public_names
    assert "execute_shipments" in app_names
    assert _tool_visibility(app_tools, "execute_shipments") == ["app"]


def test_claude_export_includes_model_visible_execution_flow() -> None:
    claude_tools = _load_json("claude_remote_mcp_public_tools.json")
    names = _tool_names(claude_tools)

    assert {
        "get_shipagent_status",
        "prepare_shipments",
        "execute_shipments",
        "get_job_status",
        "create_label_download",
    } <= names


def test_generic_mcp_export_excludes_mutation_continuation_and_artifacts() -> None:
    generic_tools = _load_json("generic_mcp_tools.json")
    names = _tool_names(generic_tools)

    assert "get_shipagent_status" in names
    assert "prepare_shipments" in names
    assert "execute_shipments" not in names
    assert "get_job_status" not in names
    assert "create_label_download" not in names


def test_provider_artifacts_use_public_scope_vocabulary() -> None:
    registry = _load_json("registry.json")
    scopes = set(_collect_values_by_key(registry, "auth_scopes"))
    flattened_scopes = {
        scope
        for item in scopes
        for scope in (item if isinstance(item, list) else [item])
    }

    assert flattened_scopes & LEGACY_COLON_SCOPES == set()
    assert flattened_scopes <= PUBLIC_SCOPE_VOCABULARY
    assert PUBLIC_SCOPE_VOCABULARY <= flattened_scopes


def _load_json(filename: str) -> Any:
    return json.loads((ARTIFACT_DIR / filename).read_text(encoding="utf-8"))


def _tool_names(payload: Any) -> set[str]:
    if isinstance(payload, dict) and isinstance(payload.get("tools"), list):
        payload = payload["tools"]
    if not isinstance(payload, list):
        raise AssertionError("provider artifact must be a list or registry object")
    names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str):
            names.add(name)
            continue
        function = item.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.add(function["name"])
    return names


def _tool_visibility(payload: Any, tool_name: str) -> list[str]:
    if not isinstance(payload, list):
        raise AssertionError("OpenAI app artifact must be a list")
    for item in payload:
        if not isinstance(item, dict) or item.get("name") != tool_name:
            continue
        ui = item.get("_meta", {}).get("ui", {})
        visibility = ui.get("visibility")
        if isinstance(visibility, list):
            return [str(value) for value in visibility]
    raise AssertionError(f"missing OpenAI app tool {tool_name!r}")


def _collect_values_by_key(value: Any, key: str) -> list[Any]:
    if isinstance(value, dict):
        collected = []
        for item_key, item_value in value.items():
            if item_key == key:
                collected.append(item_value)
            collected.extend(_collect_values_by_key(item_value, key))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_collect_values_by_key(item, key))
        return collected
    return []
```

- [ ] **Step 2: Run artifact smoke tests and verify Plan 7/8 dependency state**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_provider_export_smoke.py -v
```

Expected before Plans 7 and 8 are merged: FAIL because provider export artifacts are still empty or missing the final descriptor visibility. Expected after Plans 7 and 8 are merged and artifacts are regenerated: PASS.

- [ ] **Step 3: Regenerate artifacts only if the canonical registry changed in earlier plans**

Run after Plans 7 and 8 are present:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: artifact generation succeeds and drift test passes. Do not edit `generated/provider_artifacts/*.json` by hand in this task.

- [ ] **Step 4: Commit artifact smoke tests**

Run:

```bash
git add tests/provider_golden/test_provider_export_smoke.py
git commit -m "test: add provider artifact smoke coverage"
```

---

### Task 5: Claude API Allowlist Smoke Config

**Files:**

- Create: `scripts/provider_smoke/claude_api_allowlist_smoke.json`
- Create: `tests/provider_golden/test_smoke_materials.py`

- [ ] **Step 1: Write the failing smoke material test**

Create `tests/provider_golden/test_smoke_materials.py` with this content:

```python
import json
from pathlib import Path

CLAUDE_ALLOWLIST_CONFIG = Path("scripts/provider_smoke/claude_api_allowlist_smoke.json")


def test_claude_api_allowlist_smoke_config_declares_beta_and_tool_set() -> None:
    payload = json.loads(CLAUDE_ALLOWLIST_CONFIG.read_text(encoding="utf-8"))

    assert payload["name"] == "shipagent-claude-api-mcp-allowlist-smoke"
    assert "mcp-client-2025-11-20" in payload["anthropic_beta"]
    assert payload["server"]["type"] == "streamable-http"
    assert payload["server"]["url_env"] == "SHIPAGENT_MCP_URL"
    assert payload["server"]["oauth_bearer_token_env"] == (
        "SHIPAGENT_CLAUDE_API_BEARER_TOKEN"
    )

    allowlist = set(payload["tool_allowlist"])
    assert {
        "get_shipagent_status",
        "validate_shipment_address",
        "get_shipment_rates",
        "prepare_shipments",
        "execute_shipments",
        "get_job_status",
        "create_label_download",
    } <= allowlist

    forbidden = set(payload["negative_tool_allowlist"])
    assert {
        "submit_one_off_shipment",
        "raw_ups_tool",
        "mcp__ups__create_shipment",
        "mcp__ups__rate_shipment",
    } <= forbidden
    assert allowlist.isdisjoint(forbidden)
```

- [ ] **Step 2: Run the smoke material test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_smoke_materials.py::test_claude_api_allowlist_smoke_config_declares_beta_and_tool_set -v
```

Expected: FAIL with `FileNotFoundError` for `scripts/provider_smoke/claude_api_allowlist_smoke.json`.

- [ ] **Step 3: Create the Claude API allowlist smoke config**

Create `scripts/provider_smoke/claude_api_allowlist_smoke.json` with this content:

```json
{
  "name": "shipagent-claude-api-mcp-allowlist-smoke",
  "anthropic_beta": ["mcp-client-2025-11-20"],
  "server": {
    "name": "shipagent",
    "type": "streamable-http",
    "url_env": "SHIPAGENT_MCP_URL",
    "oauth_bearer_token_env": "SHIPAGENT_CLAUDE_API_BEARER_TOKEN"
  },
  "tool_allowlist": [
    "get_shipagent_status",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download"
  ],
  "negative_tool_allowlist": [
    "submit_one_off_shipment",
    "raw_ups_tool",
    "mcp__ups__create_shipment",
    "mcp__ups__rate_shipment",
    "mcp__ups__void_shipment",
    "mcp__ups__schedule_pickup"
  ],
  "smoke_prompt_ids": [
    "tool_selection_status_ready",
    "claude_confirmation_requires_approval_request",
    "grant_replay_execute_rejected",
    "target_offline_before_preview",
    "missing_job_ref_blocks_poll"
  ],
  "expected_rejections": {
    "submit_one_off_shipment": "not_exported",
    "raw_ups_tool": "not_exported",
    "mcp__ups__create_shipment": "not_exported",
    "mcp__ups__rate_shipment": "not_exported"
  }
}
```

- [ ] **Step 4: Run the smoke material test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_smoke_materials.py::test_claude_api_allowlist_smoke_config_declares_beta_and_tool_set -v
```

Expected: PASS.

- [ ] **Step 5: Commit the Claude allowlist config**

Run:

```bash
git add scripts/provider_smoke/claude_api_allowlist_smoke.json tests/provider_golden/test_smoke_materials.py
git commit -m "test: add Claude API allowlist smoke config"
```

---

### Task 6: MCP Inspector Scripts

**Files:**

- Create: `scripts/provider_smoke/mcp_inspector_openai.sh`
- Create: `scripts/provider_smoke/mcp_inspector_claude.sh`
- Modify: `tests/provider_golden/test_smoke_materials.py`

- [ ] **Step 1: Add failing tests for the MCP Inspector scripts**

Append this code to `tests/provider_golden/test_smoke_materials.py`:

```python
OPENAI_INSPECTOR_SCRIPT = Path("scripts/provider_smoke/mcp_inspector_openai.sh")
CLAUDE_INSPECTOR_SCRIPT = Path("scripts/provider_smoke/mcp_inspector_claude.sh")


def test_mcp_inspector_scripts_launch_streamable_http_profiles() -> None:
    openai_script = OPENAI_INSPECTOR_SCRIPT.read_text(encoding="utf-8")
    claude_script = CLAUDE_INSPECTOR_SCRIPT.read_text(encoding="utf-8")

    assert "@modelcontextprotocol/inspector@latest" in openai_script
    assert "@modelcontextprotocol/inspector@latest" in claude_script
    assert "--config" in openai_script
    assert "--config" in claude_script
    assert "streamable-http" in openai_script
    assert "streamable-http" in claude_script
    assert "SHIPAGENT_MCP_URL" in openai_script
    assert "SHIPAGENT_MCP_URL" in claude_script
    assert "shipagent-openai" in openai_script
    assert "shipagent-claude" in claude_script
```

- [ ] **Step 2: Run the script test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_smoke_materials.py::test_mcp_inspector_scripts_launch_streamable_http_profiles -v
```

Expected: FAIL with `FileNotFoundError` for `scripts/provider_smoke/mcp_inspector_openai.sh`.

- [ ] **Step 3: Create the OpenAI MCP Inspector script**

Create `scripts/provider_smoke/mcp_inspector_openai.sh` with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${SHIPAGENT_MCP_URL:?Set SHIPAGENT_MCP_URL to the hosted ShipAgent /mcp URL.}"

SERVER_NAME="shipagent-openai"
CONFIG_FILE="$(mktemp "${TMPDIR:-/tmp}/shipagent-openai-inspector.XXXXXX.json")"

cleanup() {
  rm -f "$CONFIG_FILE"
}
trap cleanup EXIT

.venv/bin/python - "$CONFIG_FILE" "$SHIPAGENT_MCP_URL" "$SERVER_NAME" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
mcp_url = sys.argv[2]
server_name = sys.argv[3]
config_path.write_text(
    json.dumps(
        {
            "mcpServers": {
                server_name: {
                    "type": "streamable-http",
                    "url": mcp_url,
                    "note": (
                        "OpenAI smoke profile. In the Inspector UI, authenticate "
                        "with a ChatGPT/OpenAI provider token for this ShipAgent account."
                    ),
                }
            }
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY

cat <<'MSG'
Launching MCP Inspector for the ShipAgent OpenAI profile.

Manual checks:
- Connect to the streamable-http server.
- Verify execute_shipments is not model-visible in the OpenAI public descriptor.
- Verify the widget/app descriptor can invoke execute_shipments after user confirmation.
- Run prompt IDs from tests/provider_golden/prompts.yaml with surface openai or both.
MSG

MCP_AUTO_OPEN_ENABLED=true npx --yes @modelcontextprotocol/inspector@latest \
  --config "$CONFIG_FILE" \
  --server "$SERVER_NAME"
```

- [ ] **Step 4: Create the Claude MCP Inspector script**

Create `scripts/provider_smoke/mcp_inspector_claude.sh` with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${SHIPAGENT_MCP_URL:?Set SHIPAGENT_MCP_URL to the hosted ShipAgent /mcp URL.}"

SERVER_NAME="shipagent-claude"
CONFIG_FILE="$(mktemp "${TMPDIR:-/tmp}/shipagent-claude-inspector.XXXXXX.json")"

cleanup() {
  rm -f "$CONFIG_FILE"
}
trap cleanup EXIT

.venv/bin/python - "$CONFIG_FILE" "$SHIPAGENT_MCP_URL" "$SERVER_NAME" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
mcp_url = sys.argv[2]
server_name = sys.argv[3]
config_path.write_text(
    json.dumps(
        {
            "mcpServers": {
                server_name: {
                    "type": "streamable-http",
                    "url": mcp_url,
                    "note": (
                        "Claude smoke profile. In the Inspector UI, authenticate "
                        "with a Claude provider token for this ShipAgent account."
                    ),
                }
            }
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY

cat <<'MSG'
Launching MCP Inspector for the ShipAgent Claude profile.

Manual checks:
- Connect to the streamable-http server.
- Verify execute_shipments is visible for Claude.
- Verify prepare_shipments returns an Approval Request URL, not an Execution Grant.
- Verify execute_shipments rejects grant replay and missing job_ref cases with terminal envelopes.
- Run prompt IDs from tests/provider_golden/prompts.yaml with surface claude or both.
MSG

MCP_AUTO_OPEN_ENABLED=true npx --yes @modelcontextprotocol/inspector@latest \
  --config "$CONFIG_FILE" \
  --server "$SERVER_NAME"
```

- [ ] **Step 5: Mark scripts executable and syntax-check them**

Run:

```bash
chmod +x scripts/provider_smoke/mcp_inspector_openai.sh scripts/provider_smoke/mcp_inspector_claude.sh
bash -n scripts/provider_smoke/mcp_inspector_openai.sh
bash -n scripts/provider_smoke/mcp_inspector_claude.sh
```

Expected: both `bash -n` commands exit 0.

- [ ] **Step 6: Run the script material test**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_smoke_materials.py::test_mcp_inspector_scripts_launch_streamable_http_profiles -v
```

Expected: PASS.

- [ ] **Step 7: Commit MCP Inspector scripts**

Run:

```bash
git add scripts/provider_smoke/mcp_inspector_openai.sh scripts/provider_smoke/mcp_inspector_claude.sh tests/provider_golden/test_smoke_materials.py
git commit -m "test: add MCP Inspector smoke scripts"
```

---

### Task 7: ChatGPT Developer-Mode Checklist

**Files:**

- Create: `docs/provider-smoke/chatgpt-developer-mode-checklist.md`
- Modify: `tests/provider_golden/test_smoke_materials.py`

- [ ] **Step 1: Add failing checklist coverage test**

Append this code to `tests/provider_golden/test_smoke_materials.py`:

```python
CHATGPT_CHECKLIST = Path("docs/provider-smoke/chatgpt-developer-mode-checklist.md")


def test_chatgpt_developer_mode_checklist_covers_required_paths() -> None:
    text = CHATGPT_CHECKLIST.read_text(encoding="utf-8")

    for phrase in [
        "ChatGPT Developer Mode Smoke Checklist",
        "openai_confirmation_execute_hidden_from_model",
        "tool_selection_status_ready",
        "pii_raw_ups_leakage_active_source_preview",
        "oversized_results_blocked",
        "missing_job_ref_blocks_poll",
        "execute_shipments is not model-visible",
        "widget confirmation button",
        "No recipient PII",
        "No raw UPS payload",
        "No label bytes",
    ]:
        assert phrase in text
```

- [ ] **Step 2: Run the checklist test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_smoke_materials.py::test_chatgpt_developer_mode_checklist_covers_required_paths -v
```

Expected: FAIL with `FileNotFoundError` for `docs/provider-smoke/chatgpt-developer-mode-checklist.md`.

- [ ] **Step 3: Create the ChatGPT developer-mode checklist**

Create `docs/provider-smoke/chatgpt-developer-mode-checklist.md` with this content:

```markdown
# ChatGPT Developer Mode Smoke Checklist

Use this checklist after Plans 7 and 8 are merged, provider artifacts are regenerated, and the hosted `/mcp` endpoint is reachable from ChatGPT Developer Mode.

## Preconditions

- [ ] Backend is running with the control-plane stack available.
- [ ] `SHIPAGENT_MCP_URL` points at the hosted `/mcp` streamable HTTP endpoint.
- [ ] `scripts/check_provider_oauth_metadata.py` passes for the public base URL.
- [ ] Generated artifacts are current: `.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v`.
- [ ] `tests/provider_golden/prompts.yaml` passes locally: `.venv/bin/python -m pytest tests/provider_golden -v`.

## Descriptor Checks

- [ ] ChatGPT Developer Mode imports the OpenAI Apps descriptor without schema warnings.
- [ ] `get_shipagent_status`, `validate_shipment_address`, `get_shipment_rates`, `prepare_shipments`, `get_job_status`, and `create_label_download` are available where expected.
- [ ] `execute_shipments is not model-visible` in the OpenAI public descriptor.
- [ ] The OpenAI app/widget descriptor exposes the widget confirmation button path for `execute_shipments`.
- [ ] Generic MCP descriptor does not expose `execute_shipments`, `get_job_status`, or `create_label_download`.

## Golden Prompt Checks

- [ ] Run `tool_selection_status_ready`: the model calls `get_shipagent_status` once and does not call `execute_shipments`.
- [ ] Run `tool_selection_prepare_active_source`: the model calls `prepare_shipments` and stops before execution.
- [ ] Run `openai_confirmation_execute_hidden_from_model`: the model receives a preview and the widget confirmation button is the only execute path.
- [ ] Run `target_offline_before_preview`: the result is terminal `target_offline`, and the model does not retry or call `prepare_shipments`.
- [ ] Run `pii_raw_ups_leakage_active_source_preview`: provider-visible text contains aggregate counts only. No recipient PII. No raw UPS payload. No label bytes.
- [ ] Run `oversized_results_blocked`: provider-visible result is terminal `result_too_large`; the response does not include manifest rows or label content.
- [ ] Run `missing_job_ref_blocks_poll`: provider-visible result is terminal `missing_job_ref`, and `create_label_download` is not called.

## Evidence To Capture

- [ ] Screenshot of OpenAI public tool list showing `execute_shipments` absent.
- [ ] Screenshot of widget confirmation button before execution.
- [ ] Screenshot of the terminal `target_offline` envelope.
- [ ] Screenshot or exported transcript showing no recipient PII, raw UPS payload, UPS account number, tracking-number array, or label bytes in provider-visible messages.
- [ ] Timestamped note of the provider connection ID and test account, without tokens or customer data.
```

- [ ] **Step 4: Run the checklist test**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden/test_smoke_materials.py::test_chatgpt_developer_mode_checklist_covers_required_paths -v
```

Expected: PASS.

- [ ] **Step 5: Commit the ChatGPT checklist**

Run:

```bash
git add docs/provider-smoke/chatgpt-developer-mode-checklist.md tests/provider_golden/test_smoke_materials.py
git commit -m "docs: add ChatGPT developer mode smoke checklist"
```

---

### Task 8: Final Validation And Handoff Notes

**Files:**

- Modify: `tests/provider_golden/test_prompt_corpus.py`
- Modify: `tests/provider_golden/test_provider_export_smoke.py`
- Modify: `tests/provider_golden/test_smoke_materials.py`

- [ ] **Step 1: Run all provider golden tests**

Run:

```bash
.venv/bin/python -m pytest tests/provider_golden -v
```

Expected after Plans 7 and 8 are merged: PASS.

- [ ] **Step 2: Run adjacent contract tests**

Run:

```bash
.venv/bin/python -m pytest tests/provider_adapters/test_projections.py tests/control_plane/test_result_projection.py tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 3: Run style checks for the new tests**

Run:

```bash
.venv/bin/python -m ruff check tests/provider_golden
```

Expected: PASS.

- [ ] **Step 4: Syntax-check smoke scripts**

Run:

```bash
bash -n scripts/provider_smoke/mcp_inspector_openai.sh
bash -n scripts/provider_smoke/mcp_inspector_claude.sh
```

Expected: PASS.

- [ ] **Step 5: Confirm only owned files changed**

Run:

```bash
git status --short -- tests/provider_golden scripts/provider_smoke docs/provider-smoke docs/superpowers/plans/2026-06-30-openai-claude-connector-10-golden-prompt-adversarial-corpus.md
git diff --name-only -- src shipagent-frontend src-tauri generated/provider_artifacts tests/services tests/provider_adapters tests/control_plane tests/registry
```

Expected: first command lists only Plan 10-owned files; second command prints no paths.

- [ ] **Step 6: Commit final validation adjustments if any test-only edits were needed**

Run only when Step 1 through Step 5 required a test-only correction:

```bash
git add tests/provider_golden scripts/provider_smoke docs/provider-smoke
git commit -m "test: finalize provider golden smoke coverage"
```

## External Smoke Commands

Run these after a hosted test endpoint and provider tokens exist:

```bash
SHIPAGENT_MCP_URL=https://example.test/mcp scripts/provider_smoke/mcp_inspector_openai.sh
SHIPAGENT_MCP_URL=https://example.test/mcp scripts/provider_smoke/mcp_inspector_claude.sh
.venv/bin/python scripts/check_provider_oauth_metadata.py https://example.test
```

Validate the Claude API allowlist smoke config before passing it to the provider client harness owned by the Claude API integration environment:

```bash
SHIPAGENT_MCP_URL=https://example.test/mcp \
SHIPAGENT_CLAUDE_API_BEARER_TOKEN=redacted-test-token \
ANTHROPIC_BETA=mcp-client-2025-11-20 \
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

config = json.loads(
    Path("scripts/provider_smoke/claude_api_allowlist_smoke.json").read_text(
        encoding="utf-8"
    )
)
assert os.environ["ANTHROPIC_BETA"] in config["anthropic_beta"]
assert os.environ[config["server"]["url_env"]].endswith("/mcp")
assert os.environ[config["server"]["oauth_bearer_token_env"]]
print("Claude API allowlist smoke config is ready for the provider harness.")
PY
```

The JSON file is configuration, not an executable script; the smoke runner must read `url_env`, `oauth_bearer_token_env`, `anthropic_beta`, `tool_allowlist`, and `negative_tool_allowlist`.

## Overlap Risks

- Plan 7 owns implementation behavior for Approval Requests, Execution Grants, `execute_shipments`, `job_ref`, target binding, grant replay, label downloads, and provider-facing failure envelopes. Plan 10 only codifies expected tests and smoke cases.
- Plan 8 owns the OpenAI widget implementation and app resources. Plan 10 only verifies that OpenAI public model descriptors hide `execute_shipments` and that smoke checklists cover the widget confirmation button.
- Plan 6 owns provider projections and output profiles. Plan 10 re-attacks the generated artifacts and provider-visible results but does not edit projection source.
- If another worker creates `scripts/provider_smoke/` or `docs/provider-smoke/`, keep one shared directory and preserve the exact Plan 10 filenames listed here.

## Completion Criteria

- `tests/provider_golden/prompts.yaml` contains all required Plan 10 categories.
- `tests/provider_golden -v` passes after Plans 7 and 8 land.
- OpenAI artifact smoke proves `execute_shipments` is app-only and not model-visible.
- Claude artifact smoke proves `execute_shipments`, `get_job_status`, and `create_label_download` are available to the reviewed Claude surface.
- Generic MCP smoke proves mutating, continuation, and artifact-bearing tools are absent.
- Claude API smoke config includes beta `mcp-client-2025-11-20` and a strict allowlist.
- MCP Inspector scripts launch streamable HTTP profiles for OpenAI and Claude.
- ChatGPT Developer Mode checklist covers confirmation, offline, leakage, oversized, and missing `job_ref` paths.
