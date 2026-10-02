# Provider Projections Origin Redaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Plan 6 from the OpenAI/Claude connector spec: provider output profiles, origin-based redaction, public descriptor visibility, and the unified `prepare_shipments` source schema.

**Architecture:** Keep shipping behavior in shared workflow/control-plane contracts and keep provider adapters limited to descriptor projection. `src/control_plane/result_projection.py` becomes the single provider-result projection engine for OpenAI structured output, OpenAI widget-only metadata, and Claude markdown, while registry contracts define source-origin tags and provider descriptor visibility. Hosted MCP tools consume the projection using the current Auth0 `AuthorizationContext.provider_surface` established by Plan 1.

**Tech Stack:** Python 3.12+, Pydantic, JSON Schema, FastMCP `ToolResult`, pytest, existing registry/provider-adapter generators.

---

## Source Of Truth

Authoritative design:

```text
docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md
```

Plan 6 covers these spec requirements:

- output profiles in `result_projection.py`: `OPENAI_STRUCTURED`, `OPENAI_WIDGET_META`, `CLAUDE_MARKDOWN`
- D4 origin-based redaction
- provider descriptor visibility, especially OpenAI app-only `execute_shipments` and Claude model-visible `execute_shipments`
- aggregate projection for active-source and existing-batch local data
- tracking-number visibility and masking rules
- unified `prepare_shipments` source schema projection
- public/private provider surfaces and generic MCP restrictions
- tests proving generated artifacts are regenerated from canonical registry/adapters only

This plan does not implement approval pages, execution grants, job lifecycle dispatch, label streaming, OpenAI widget UI, or Plan 10 adversarial prompts. Those are Plan 7, Plan 8, and Plan 10 responsibilities.

## Current Repo State

Relevant source files inspected:

```text
AGENTS.md
src/AGENTS.md
src/control_plane/result_projection.py
src/control_plane/app.py
src/control_plane/auth/context.py
src/hosted_mcp/server.py
src/provider_adapters/export_filter.py
src/provider_adapters/mcp_projection.py
src/provider_adapters/openai_projection.py
src/registry/models.py
src/registry/tools/public.py
src/registry/tools/schema.py
src/services/conversation_runtime/dispatcher.py
src/services/conversation_runtime/tool_catalog.py
scripts/generate_provider_artifacts.py
```

Relevant tests inspected:

```text
tests/control_plane/test_result_projection.py
tests/hosted/test_hosted_mcp_registry.py
tests/provider_adapters/test_projections.py
tests/registry/test_artifact_drift.py
tests/registry/test_catalog.py
tests/registry/test_export.py
tests/registry/test_models.py
tests/services/conversation_runtime/test_tool_catalog.py
```

Important existing behavior:

- `src/control_plane/result_projection.py` currently validates a dict against `ToolContract.output_schema`, enforces `max_result_bytes`, and rejects a small set of forbidden keys for aggregate profiles.
- `src/hosted_mcp/server.py` already calls `project_result(self._contract, result)` before returning a FastMCP `ToolResult`.
- FastMCP `ToolResult` supports `content`, `structured_content`, and `meta`. Use `meta` for OpenAI widget-only metadata.
- `AuthorizationContext.provider_surface` currently carries values such as `chatgpt` and `claude_ai`; Plan 6 should map these to output profiles without adding shipping logic to provider adapters.
- `src/provider_adapters/openai_projection.py` currently adds only `_meta.ui.resourceUri`.
- `src/registry/tools/public.py` still includes `submit_one_off_shipment`, legacy colon scopes, generic exports for all first-slice tools, and `prepare_shipments` with only `order_batch_id`.
- `generated/provider_artifacts/*.json` are currently generated outputs. Never hand-edit them; run `scripts/generate_provider_artifacts.py`.

## Target File Structure

Create:

```text
src/registry/tools/shipment_source.py
```

Modify:

```text
src/control_plane/result_projection.py
src/hosted_mcp/server.py
src/provider_adapters/openai_projection.py
src/registry/models.py
src/registry/tools/public.py
tests/control_plane/test_result_projection.py
tests/hosted/test_hosted_mcp_registry.py
tests/provider_adapters/test_projections.py
tests/registry/test_catalog.py
tests/registry/test_export.py
tests/registry/test_models.py
generated/provider_artifacts/claude_remote_mcp_public_tools.json
generated/provider_artifacts/generic_mcp_tools.json
generated/provider_artifacts/openai_apps_public_tools.json
generated/provider_artifacts/registry.json
```

Do not modify:

```text
src/services/conversation_runtime/dispatcher.py
src/services/conversation_runtime/tool_catalog.py
src/services/conversation_runtime/openai_provider.py
src/services/conversation_runtime/gemini_provider.py
src/orchestrator/agent/tools/
src/control_plane/relay/
src/control_plane/request_controls.py
shipagent-frontend/
provider-widget/
```

The conversation runtime dispatcher already strips local row data for desktop/provider-neutral chat. Plan 6 keeps hosted OpenAI/Claude connector projection in `src/control_plane/result_projection.py` so Plans 7 and 8 can consume one canonical projection engine.

---

### Task 1: Add Output Profiles And Origin-Based Projection

**Files:**

- Modify: `src/control_plane/result_projection.py`
- Test: `tests/control_plane/test_result_projection.py`

- [ ] **Step 1: Add failing tests for D4 origin rules and output profiles**

Append these tests to `tests/control_plane/test_result_projection.py`.

```python
import json

from src.control_plane.result_projection import (
    DataOrigin,
    OutputProfile,
    ProjectionContext,
    project_provider_result,
)


def _shipment_projection_contract(**overrides) -> ToolContract:
    base = {
        "name": "prepare_shipments",
        "title": "Prepare shipments",
        "description": "Create immutable preview artifacts for shipment execution.",
        "contract_version": "1.0.0",
        "visibility": "public",
        "availability": ["hosted", "local"],
        "implementation_status": "implemented",
        "hosted_readiness": "ready",
        "tenant_safe": True,
        "provider_export_enabled": True,
        "side_effect": "estimate",
        "requires_confirmation": False,
        "auth_scopes": ["shipagent.preview"],
        "provider_exports": ["openai_apps_public", "claude_remote_mcp_public"],
        "audit_level": "basic",
        "result_sensitivity": "business",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "source_origin": {"type": "string"},
                "preview_ref": {"type": "string"},
                "summary": {
                    "type": "object",
                    "properties": {
                        "shipment_count": {"type": "integer"},
                        "warning_count": {"type": "integer"},
                        "total_charge": {"type": "number"},
                        "currency": {"type": "string"},
                    },
                    "required": ["shipment_count", "warning_count", "total_charge", "currency"],
                    "additionalProperties": False,
                },
                "tracking_count": {"type": "integer"},
                "tracking_number": {"type": "string"},
                "shipment": {"type": "object"},
            },
            "required": ["status", "source_origin", "preview_ref", "summary"],
            "additionalProperties": False,
        },
    }
    base.update(overrides)
    return ToolContract.model_validate(base)


def test_active_source_projection_returns_aggregates_not_rows():
    contract = _shipment_projection_contract()
    result = {
        "status": "preview_ready",
        "source_origin": "active_source_selection",
        "preview_ref": "prv_123",
        "summary": {
            "shipment_count": 2,
            "warning_count": 1,
            "total_charge": 18.44,
            "currency": "USD",
        },
        "preview_rows": [
            {
                "recipient_name": "Jane Doe",
                "address_line_1": "1 Main Street",
                "city": "Boston",
            }
        ],
        "tracking_numbers": ["1Z999AA10123456784", "1Z999AA10123456785"],
        "raw_response": {"ups": "payload"},
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.OPENAI_STRUCTURED,
            source_origin=DataOrigin.ACTIVE_SOURCE_SELECTION,
            provider_surface="chatgpt",
        ),
    )

    assert projected.structured_content == {
        "status": "preview_ready",
        "source_origin": "active_source_selection",
        "preview_ref": "prv_123",
        "summary": {
            "shipment_count": 2,
            "warning_count": 1,
            "total_charge": 18.44,
            "currency": "USD",
        },
        "tracking_count": 2,
    }
    serialized = json.dumps(projected.structured_content, sort_keys=True)
    assert "Jane Doe" not in serialized
    assert "1 Main Street" not in serialized
    assert "1Z999AA10123456784" not in serialized
    assert "raw_response" not in serialized


def test_one_off_projection_echoes_provider_supplied_fields_and_tracking_number():
    contract = _shipment_projection_contract(
        result_profile="provider_ingress_echo",
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "source_origin": {"type": "string"},
                "preview_ref": {"type": "string"},
                "summary": {"type": "object"},
                "shipment": {"type": "object"},
                "tracking_number": {"type": "string"},
            },
            "required": ["status", "source_origin", "preview_ref", "summary", "shipment"],
            "additionalProperties": False,
        },
    )
    result = {
        "status": "completed",
        "source_origin": "one_off",
        "preview_ref": "prv_123",
        "summary": {"shipment_count": 1, "warning_count": 0, "total_charge": 9.22, "currency": "USD"},
        "shipment": {
            "recipient_name": "Alex Rivera",
            "address_line_1": "10 Market Street",
            "city": "San Francisco",
        },
        "tracking_number": "1Z999AA10123456784",
        "ups_account_number": "A12345",
        "label_bytes": "base64-label",
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.OPENAI_STRUCTURED,
            source_origin=DataOrigin.ONE_OFF,
            provider_surface="chatgpt",
        ),
    )

    assert projected.structured_content["shipment"]["recipient_name"] == "Alex Rivera"
    assert projected.structured_content["shipment"]["address_line_1"] == "10 Market Street"
    assert projected.structured_content["tracking_number"] == "1Z999AA10123456784"
    serialized = json.dumps(projected.structured_content, sort_keys=True)
    assert "A12345" not in serialized
    assert "base64-label" not in serialized


def test_local_history_tracking_number_is_masked():
    contract = _shipment_projection_contract(
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "source_origin": {"type": "string"},
                "preview_ref": {"type": "string"},
                "summary": {"type": "object"},
                "tracking_number": {"type": "string"},
            },
            "required": ["status", "source_origin", "preview_ref", "summary", "tracking_number"],
            "additionalProperties": False,
        },
    )
    result = {
        "status": "completed",
        "source_origin": "local_history",
        "preview_ref": "prv_123",
        "summary": {"shipment_count": 1, "warning_count": 0, "total_charge": 9.22, "currency": "USD"},
        "tracking_number": "1Z999AA10123456784",
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.OPENAI_STRUCTURED,
            source_origin=DataOrigin.LOCAL_HISTORY,
            provider_surface="chatgpt",
        ),
    )

    assert projected.structured_content["tracking_number"] == "1Z999...6784"


def test_claude_markdown_profile_formats_and_truncates_with_headroom():
    contract = _shipment_projection_contract()
    long_status = "preview_ready_" + ("x" * 200)
    result = {
        "status": long_status,
        "source_origin": "active_source_selection",
        "preview_ref": "prv_123",
        "summary": {
            "shipment_count": 2,
            "warning_count": 1,
            "total_charge": 18.44,
            "currency": "USD",
        },
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.CLAUDE_MARKDOWN,
            source_origin=DataOrigin.ACTIVE_SOURCE_SELECTION,
            provider_surface="claude_ai",
            max_model_chars=120,
        ),
    )

    assert projected.model_content.startswith("| Field | Value |")
    assert len(projected.model_content) <= 120
    assert "projection truncated" in projected.model_content


def test_openai_widget_meta_profile_is_redacted_separately_from_model_content():
    contract = _shipment_projection_contract()
    result = {
        "status": "preview_ready",
        "source_origin": "active_source_selection",
        "preview_ref": "prv_123",
        "summary": {
            "shipment_count": 2,
            "warning_count": 1,
            "total_charge": 18.44,
            "currency": "USD",
        },
        "widget_meta": {
            "approval_request_ref": "apr_123",
            "preview_rows": [{"recipient_name": "Jane Doe"}],
            "raw_response": {"ups": "payload"},
        },
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.OPENAI_WIDGET_META,
            source_origin=DataOrigin.ACTIVE_SOURCE_SELECTION,
            provider_surface="chatgpt",
        ),
    )

    assert projected.structured_content == {}
    assert projected.meta == {"approval_request_ref": "apr_123"}
    assert "Jane Doe" not in json.dumps(projected.meta, sort_keys=True)
```

- [ ] **Step 2: Run the new projection tests and verify they fail for missing profile types**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py -v
```

Expected: FAIL with an import error mentioning `DataOrigin`, `OutputProfile`, `ProjectionContext`, or `project_provider_result`.

- [ ] **Step 3: Merge the profile-aware projection engine into `src/control_plane/result_projection.py`**

Use this complete file content as the Plan 6 baseline. If Plan 2 has already added `job_ref` or degraded relay envelope projection helpers, preserve those public helpers and fold them into the `project_provider_result(...)` path rather than deleting them.

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from jsonschema import validate

from src.registry.models import ToolContract

CLAUDE_MARKDOWN_MAX_CHARS = 140_000


class OutputProfile(StrEnum):
    OPENAI_STRUCTURED = "openai_structured"
    OPENAI_WIDGET_META = "openai_widget_meta"
    CLAUDE_MARKDOWN = "claude_markdown"


class DataOrigin(StrEnum):
    ONE_OFF = "one_off"
    ACTIVE_SOURCE_SELECTION = "active_source_selection"
    EXISTING_BATCH = "existing_batch"
    LOCAL_HISTORY = "local_history"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProjectionContext:
    output_profile: OutputProfile = OutputProfile.OPENAI_STRUCTURED
    source_origin: DataOrigin = DataOrigin.UNKNOWN
    provider_surface: str | None = None
    max_model_chars: int | None = None


@dataclass(frozen=True)
class ProjectedToolResult:
    structured_content: dict[str, Any]
    model_content: str
    meta: dict[str, Any] = field(default_factory=dict)


FORBIDDEN_AGGREGATE_KEYS = frozenset(
    {
        "rows",
        "preview_rows",
        "sample_rows",
        "address_line_1",
        "recipient_name",
        "account_number",
        "credentials",
        "label_bytes",
        "raw_response",
        "request_body",
        "local_path",
    }
)

_NEVER_VISIBLE_KEYS = frozenset(
    {
        "account_number",
        "api_key",
        "api_secret",
        "credentials",
        "document_bytes",
        "document_url",
        "file_content_base64",
        "keyring",
        "label",
        "label_bytes",
        "label_data",
        "label_download_url",
        "label_url",
        "password",
        "raw_payload",
        "raw_request",
        "raw_response",
        "request_body",
        "request_payload",
        "response_body",
        "response_payload",
        "secret",
        "token",
        "ups_account_number",
        "ups_credentials",
    }
)

_LOCAL_DETAIL_KEYS = frozenset(
    {
        "address",
        "address_line_1",
        "address_line_2",
        "city",
        "customer",
        "customer_name",
        "email",
        "local_path",
        "order",
        "order_id",
        "order_ids",
        "package",
        "phone",
        "postal_code",
        "preview_rows",
        "raw_rows",
        "recipient",
        "recipient_name",
        "row",
        "rows",
        "sample_rows",
        "ship_to",
        "shipment",
        "shipments",
        "state",
        "street",
    }
)

_TRACKING_SCALAR_KEYS = frozenset(
    {
        "tracking_number",
        "tracking_id",
        "trackingnumber",
        "trackingid",
    }
)

_TRACKING_LIST_KEYS = frozenset(
    {
        "tracking_numbers",
        "tracking_ids",
        "trackingnumbers",
        "trackingids",
    }
)

_LOCAL_SOURCE_ORIGINS = frozenset(
    {
        DataOrigin.ACTIVE_SOURCE_SELECTION,
        DataOrigin.EXISTING_BATCH,
        DataOrigin.LOCAL_HISTORY,
    }
)


def _normalize_key(key: Any) -> str:
    return "".join(char.lower() for char in str(key) if char.isalnum() or char == "_")


_NEVER_VISIBLE_NORMALIZED = frozenset(_normalize_key(key) for key in _NEVER_VISIBLE_KEYS)
_LOCAL_DETAIL_NORMALIZED = frozenset(_normalize_key(key) for key in _LOCAL_DETAIL_KEYS)
_TRACKING_SCALAR_NORMALIZED = frozenset(_normalize_key(key) for key in _TRACKING_SCALAR_KEYS)
_TRACKING_LIST_NORMALIZED = frozenset(_normalize_key(key) for key in _TRACKING_LIST_KEYS)


def _forbidden_paths(value: object, path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = (*path, str(key))
            if key in FORBIDDEN_AGGREGATE_KEYS:
                found.append(".".join(nested_path))
            found.extend(_forbidden_paths(nested, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_forbidden_paths(nested, (*path, str(index))))
    return found


def _origin_from_result(result: dict[str, Any], context: ProjectionContext) -> DataOrigin:
    if context.source_origin != DataOrigin.UNKNOWN:
        return context.source_origin
    candidate = result.get("source_origin") or result.get("shipment_source_type")
    if isinstance(candidate, str):
        try:
            return DataOrigin(candidate)
        except ValueError:
            return DataOrigin.UNKNOWN
    return DataOrigin.UNKNOWN


def project_result(
    contract: ToolContract,
    result: dict[str, Any],
    context: ProjectionContext | None = None,
) -> dict[str, Any]:
    return project_provider_result(contract, result, context).structured_content


def project_provider_result(
    contract: ToolContract,
    result: dict[str, Any],
    context: ProjectionContext | None = None,
) -> ProjectedToolResult:
    projection_context = context or ProjectionContext()
    origin = _origin_from_result(result, projection_context)

    if contract.result_profile == "aggregate" and origin == DataOrigin.UNKNOWN:
        forbidden = _forbidden_paths(result)
        if forbidden:
            raise ValueError(
                f"aggregate result contains forbidden keys: {sorted(forbidden)}"
            )

    if projection_context.output_profile == OutputProfile.OPENAI_WIDGET_META:
        meta = _project_widget_meta(result, origin)
        encoded_meta = json.dumps(meta, separators=(",", ":"), sort_keys=True).encode()
        if len(encoded_meta) > contract.max_result_bytes:
            raise ValueError("provider result exceeds contract size")
        return ProjectedToolResult(
            structured_content={},
            model_content="",
            meta=meta,
        )

    projected = _project_mapping(result, origin)
    validate(instance=projected, schema=contract.output_schema)
    encoded = json.dumps(projected, separators=(",", ":"), sort_keys=True).encode()
    if len(encoded) > contract.max_result_bytes:
        raise ValueError("provider result exceeds contract size")

    return ProjectedToolResult(
        structured_content=projected,
        model_content=_model_content(projected, projection_context),
        meta=_project_widget_meta(result, origin),
    )


def _project_widget_meta(result: dict[str, Any], origin: DataOrigin) -> dict[str, Any]:
    raw_meta = result.get("widget_meta")
    if not isinstance(raw_meta, dict):
        return {}
    return _project_mapping(raw_meta, origin)


def _project_mapping(value: dict[str, Any], origin: DataOrigin) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = _normalize_key(key)
        if normalized_key in _NEVER_VISIBLE_NORMALIZED:
            continue
        if normalized_key == "widget_meta":
            continue
        if _is_local_origin(origin) and normalized_key in _LOCAL_DETAIL_NORMALIZED:
            continue

        if normalized_key in _TRACKING_LIST_NORMALIZED:
            if _is_local_batch_origin(origin):
                projected["tracking_count"] = _tracking_count(item)
            elif origin == DataOrigin.LOCAL_HISTORY:
                projected[key] = _mask_tracking_collection(item)
            else:
                tracked = _project_value(item, origin)
                if tracked is not None:
                    projected[key] = tracked
            continue

        if normalized_key in _TRACKING_SCALAR_NORMALIZED:
            if _is_local_batch_origin(origin):
                projected["tracking_count"] = _tracking_count(item)
            elif origin == DataOrigin.LOCAL_HISTORY:
                projected[key] = _mask_tracking_number(item)
            else:
                tracked = _project_value(item, origin)
                if tracked is not None:
                    projected[key] = tracked
            continue

        projected_item = _project_value(item, origin)
        if projected_item is not None:
            projected[key] = projected_item
    return projected


def _project_value(value: Any, origin: DataOrigin) -> Any:
    if isinstance(value, dict):
        return _project_mapping(value, origin)
    if isinstance(value, list):
        projected_items = [
            projected_item
            for item in value
            if (projected_item := _project_value(item, origin)) is not None
        ]
        return projected_items
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return None


def _is_local_origin(origin: DataOrigin) -> bool:
    return origin in _LOCAL_SOURCE_ORIGINS


def _is_local_batch_origin(origin: DataOrigin) -> bool:
    return origin in {DataOrigin.ACTIVE_SOURCE_SELECTION, DataOrigin.EXISTING_BATCH}


def _tracking_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if value in (None, ""):
        return 0
    return 1


def _mask_tracking_collection(value: Any) -> Any:
    if isinstance(value, list):
        return [_mask_tracking_number(item) for item in value if item]
    return _mask_tracking_number(value)


def _mask_tracking_number(value: Any) -> str:
    text = str(value)
    if len(text) <= 8:
        return "***"
    return f"{text[:5]}...{text[-4:]}"


def _model_content(
    structured_content: dict[str, Any],
    context: ProjectionContext,
) -> str:
    if context.output_profile == OutputProfile.CLAUDE_MARKDOWN:
        return _markdown_table(
            structured_content,
            max_chars=context.max_model_chars or CLAUDE_MARKDOWN_MAX_CHARS,
        )
    return json.dumps(structured_content, sort_keys=True, separators=(",", ":"))


def _markdown_table(value: dict[str, Any], *, max_chars: int) -> str:
    lines = ["| Field | Value |", "| --- | --- |"]
    for key in sorted(value):
        lines.append(f"| {_markdown_escape(key)} | {_markdown_escape(_display_value(value[key]))} |")
    rendered = "\n".join(lines)
    if len(rendered) <= max_chars:
        return rendered
    suffix = "\n\n[projection truncated]"
    keep = max(0, max_chars - len(suffix))
    return rendered[:keep].rstrip() + suffix


def _display_value(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")
```

- [ ] **Step 4: Run the result projection tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the projection engine**

```bash
git add src/control_plane/result_projection.py tests/control_plane/test_result_projection.py
git commit -m "feat: add provider output projection profiles"
```

---

### Task 2: Apply Projection Context In Hosted MCP Results

**Files:**

- Modify: `src/hosted_mcp/server.py`
- Test: `tests/hosted/test_hosted_mcp_registry.py`

- [ ] **Step 1: Add failing hosted MCP tests for profile selection**

Append these tests to `tests/hosted/test_hosted_mcp_registry.py`.

```python
import json


@pytest.mark.asyncio
async def test_hosted_mcp_projects_chatgpt_widget_meta_outside_model_content():
    async def handler(context, arguments):
        return {
            "status": "preview_ready",
            "source_origin": "active_source_selection",
            "preview_ref": "prv_123",
            "summary": {
                "shipment_count": 2,
                "warning_count": 0,
                "total_charge": 18.44,
                "currency": "USD",
            },
            "preview_rows": [{"recipient_name": "Jane Doe"}],
            "widget_meta": {
                "approval_request_ref": "apr_123",
                "preview_rows": [{"recipient_name": "Jane Doe"}],
            },
        }

    contract = exportable_mcp_tool("prepare_shipments").model_copy(
        update={
            "auth_scopes": ["shipagent.preview"],
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "source_origin": {"type": "string"},
                    "preview_ref": {"type": "string"},
                    "summary": {"type": "object"},
                },
                "required": ["status", "source_origin", "preview_ref", "summary"],
                "additionalProperties": False,
            },
        }
    )
    server = build_server(tools=[contract], tool_handlers={"prepare_shipments": handler})
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="chatgpt",
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.preview"}),
    )

    token = set_authorization_context(context)
    try:
        result = await tools["prepare_shipments"].run({})
    finally:
        clear_authorization_context(token)

    assert result.structured_content["summary"]["shipment_count"] == 2
    assert result.meta == {"approval_request_ref": "apr_123"}
    assert "Jane Doe" not in result.content[0].text
    assert "Jane Doe" not in json.dumps(result.meta, sort_keys=True)


@pytest.mark.asyncio
async def test_hosted_mcp_projects_claude_results_as_markdown_text():
    async def handler(context, arguments):
        return {
            "status": "preview_ready",
            "source_origin": "active_source_selection",
            "preview_ref": "prv_123",
            "summary": {
                "shipment_count": 2,
                "warning_count": 0,
                "total_charge": 18.44,
                "currency": "USD",
            },
            "preview_rows": [{"recipient_name": "Jane Doe"}],
        }

    contract = exportable_mcp_tool("prepare_shipments").model_copy(
        update={
            "auth_scopes": ["shipagent.preview"],
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "source_origin": {"type": "string"},
                    "preview_ref": {"type": "string"},
                    "summary": {"type": "object"},
                },
                "required": ["status", "source_origin", "preview_ref", "summary"],
                "additionalProperties": False,
            },
        }
    )
    server = build_server(tools=[contract], tool_handlers={"prepare_shipments": handler})
    tools = await server.get_tools()
    context = AuthorizationContext(
        account_id="acct-1",
        provider_connection_id="pc-1",
        provider_surface="claude_ai",
        subject="auth0|owner-1",
        client_id="claude-client",
        scopes=frozenset({"shipagent.preview"}),
    )

    token = set_authorization_context(context)
    try:
        result = await tools["prepare_shipments"].run({})
    finally:
        clear_authorization_context(token)

    assert result.content[0].text.startswith("| Field | Value |")
    assert result.structured_content["preview_ref"] == "prv_123"
    assert "Jane Doe" not in result.content[0].text
```

- [ ] **Step 2: Run the hosted tests and verify profile selection is not wired**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_hosted_mcp_registry.py -v -k "projects_chatgpt_widget_meta or projects_claude_results"
```

Expected: FAIL because `BoundRegistryTool.run()` still calls `project_result()` and always serializes JSON text.

- [ ] **Step 3: Update imports in `src/hosted_mcp/server.py`**

Change the result-projection import block to:

```python
from src.control_plane.result_projection import (
    DataOrigin,
    OutputProfile,
    ProjectionContext,
    project_provider_result,
)
```

- [ ] **Step 4: Add profile selection helpers to `src/hosted_mcp/server.py`**

Place these helpers immediately before `class BoundRegistryTool`.

```python
def _profile_for_surface(surface: str) -> OutputProfile:
    if surface == "chatgpt":
        return OutputProfile.OPENAI_STRUCTURED
    if surface.startswith("claude"):
        return OutputProfile.CLAUDE_MARKDOWN
    return OutputProfile.OPENAI_STRUCTURED


def _source_origin_from_arguments(arguments: dict[str, Any]) -> DataOrigin:
    source = arguments.get("shipment_source")
    if isinstance(source, dict):
        source_type = source.get("source_type")
        if isinstance(source_type, str):
            try:
                return DataOrigin(source_type)
            except ValueError:
                return DataOrigin.UNKNOWN
    return DataOrigin.UNKNOWN
```

- [ ] **Step 5: Replace the projection block in `BoundRegistryTool.run()`**

Replace this block:

```python
        result = project_result(self._contract, result)
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(result, sort_keys=True),
                )
            ],
            structured_content=result,
        )
```

with:

```python
        projected = project_provider_result(
            self._contract,
            result,
            ProjectionContext(
                output_profile=_profile_for_surface(context.provider_surface),
                source_origin=_source_origin_from_arguments(arguments),
                provider_surface=context.provider_surface,
            ),
        )
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=projected.model_content,
                )
            ],
            structured_content=projected.structured_content,
            meta=projected.meta or None,
        )
```

- [ ] **Step 6: Run hosted projection tests**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_hosted_mcp_registry.py -v -k "projects_chatgpt_widget_meta or projects_claude_results"
```

Expected: PASS.

- [ ] **Step 7: Confirm hosted MCP uses the new projection entry point**

Run:

```bash
rg -n "project_provider_result" src/hosted_mcp/server.py
```

Expected: output includes the import and the call inside `BoundRegistryTool.run()`.

- [ ] **Step 8: Commit hosted projection wiring**

```bash
git add src/hosted_mcp/server.py tests/hosted/test_hosted_mcp_registry.py
git commit -m "feat: project hosted tool results by provider surface"
```

---

### Task 3: Define Unified `prepare_shipments` Source Schema

**Files:**

- Create: `src/registry/tools/shipment_source.py`
- Modify: `src/registry/tools/public.py`
- Test: `tests/registry/test_catalog.py`
- Test: `tests/hosted/test_hosted_mcp_registry.py`

- [ ] **Step 1: Add failing registry tests for the public tool set and source union**

Update `EXPECTED_PUBLIC` in `tests/registry/test_catalog.py` to remove `submit_one_off_shipment`:

```python
EXPECTED_PUBLIC = {
    "get_shipagent_status",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
}
```

Replace `test_prepare_tool_schema_is_strict()` in `tests/registry/test_catalog.py` with:

```python
def test_prepare_tool_schema_uses_closed_shipment_source_union():
    tool = next(tool for tool in public_tools() if tool.name == "prepare_shipments")

    assert set(tool.input_schema["properties"]) == {"shipment_source", "idempotency_key"}
    source_schema = tool.input_schema["properties"]["shipment_source"]
    variants = source_schema["oneOf"]
    source_types = {
        variant["properties"]["source_type"]["const"]
        for variant in variants
    }
    assert source_types == {"one_off", "active_source_selection", "existing_batch"}
    for variant in variants:
        assert variant["additionalProperties"] is False
        assert "source_type" in variant["required"]
    assert "tenant_id" not in tool.input_schema["properties"]
```

Update the import in `tests/hosted/test_hosted_mcp_registry.py` if needed and keep the existing identity-field test using `FIRST_SLICE_TOOL_NAMES`; the constant will be changed in production code in Step 4.

- [ ] **Step 2: Run registry tests and verify they fail against the old schema**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py -v -k "public_catalog or prepare_tool_schema"
```

Expected: FAIL because `submit_one_off_shipment` still exists and `prepare_shipments` still accepts `order_batch_id`.

- [ ] **Step 3: Create `src/registry/tools/shipment_source.py`**

Create this complete file.

```python
from __future__ import annotations

from typing import Any

from src.registry.tools.schema import object_schema


def one_off_shipment_schema() -> dict[str, Any]:
    return object_schema(
        {
            "ship_to": object_schema(
                {
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "address_line_1": {"type": "string", "minLength": 1, "maxLength": 120},
                    "address_line_2": {"type": "string", "maxLength": 120},
                    "city": {"type": "string", "minLength": 1, "maxLength": 80},
                    "state": {"type": "string", "minLength": 1, "maxLength": 80},
                    "postal_code": {"type": "string", "minLength": 1, "maxLength": 20},
                    "country_code": {"type": "string", "minLength": 2, "maxLength": 2},
                },
                ["name", "address_line_1", "city", "state", "postal_code", "country_code"],
            ),
            "package": object_schema(
                {
                    "weight_value": {"type": "number", "exclusiveMinimum": 0},
                    "weight_unit": {"type": "string", "enum": ["lb", "oz", "kg", "g"]},
                    "length": {"type": "number", "exclusiveMinimum": 0},
                    "width": {"type": "number", "exclusiveMinimum": 0},
                    "height": {"type": "number", "exclusiveMinimum": 0},
                    "dimension_unit": {"type": "string", "enum": ["in", "cm"]},
                },
                ["weight_value", "weight_unit"],
            ),
            "service": object_schema(
                {
                    "carrier": {"type": "string", "enum": ["ups"]},
                    "service_code": {"type": "string", "minLength": 1, "maxLength": 40},
                },
                ["carrier", "service_code"],
            ),
        },
        ["ship_to", "package", "service"],
    )


def shipment_source_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            object_schema(
                {
                    "source_type": {"const": "one_off"},
                    "shipment": one_off_shipment_schema(),
                },
                ["source_type", "shipment"],
            ),
            object_schema(
                {
                    "source_type": {"const": "active_source_selection"},
                    "filter_intent": {
                        "type": "object",
                        "description": "Canonical FilterIntent payload applied locally by the Execution Target.",
                        "additionalProperties": True,
                    },
                    "column_mapping": {
                        "type": "object",
                        "description": "Canonical shipment column mapping selected by the provider conversation.",
                        "additionalProperties": True,
                    },
                    "package_plan": {
                        "type": "object",
                        "description": "Canonical package defaults or per-row package mapping plan.",
                        "additionalProperties": True,
                    },
                    "service_plan": {
                        "type": "object",
                        "description": "Canonical carrier service selection plan.",
                        "additionalProperties": True,
                    },
                },
                ["source_type", "filter_intent", "column_mapping", "package_plan", "service_plan"],
            ),
            object_schema(
                {
                    "source_type": {"const": "existing_batch"},
                    "batch_ref": {
                        "type": "string",
                        "minLength": 8,
                        "maxLength": 256,
                        "description": "Opaque local batch reference created by ShipAgent.",
                    },
                },
                ["source_type", "batch_ref"],
            ),
        ]
    }


def prepare_shipments_input_schema() -> dict[str, Any]:
    return object_schema(
        {
            "shipment_source": shipment_source_schema(),
            "idempotency_key": {
                "type": "string",
                "minLength": 8,
                "maxLength": 128,
                "description": "Client-generated idempotency key for prepare retries.",
            },
        },
        ["shipment_source"],
    )
```

- [ ] **Step 4: Update public tool names and import the new schema helper**

In `src/registry/tools/public.py`, add this import:

```python
from src.registry.tools.shipment_source import prepare_shipments_input_schema
```

Replace `FIRST_SLICE_TOOL_NAMES` with:

```python
FIRST_SLICE_TOOL_NAMES = (
    "get_shipagent_status",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
)
```

- [ ] **Step 5: Remove the `submit_one_off_shipment` contract from `PUBLIC_TOOLS`**

Delete the `public_tool("submit_one_off_shipment", ...)` entry from `PUBLIC_TOOLS`. Do not create a replacement purchase path. One-off shipment data now enters through `prepare_shipments.shipment_source.source_type == "one_off"`.

- [ ] **Step 6: Replace the `prepare_shipments` input schema**

In the `public_tool("prepare_shipments", ...)` entry, replace the current `object_schema({"order_batch_id": ...}, ["order_batch_id"])` input schema with:

```python
        prepare_shipments_input_schema(),
```

- [ ] **Step 7: Run the source-schema tests**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py tests/hosted/test_hosted_mcp_registry.py -v -k "public_catalog or prepare_tool_schema or identity_fields"
```

Expected: PASS for the selected tests.

- [ ] **Step 8: Commit the source schema**

```bash
git add src/registry/tools/shipment_source.py src/registry/tools/public.py tests/registry/test_catalog.py tests/hosted/test_hosted_mcp_registry.py
git commit -m "feat: define unified prepare shipment source schema"
```

---

### Task 4: Update Public Scopes, Export Surfaces, And Descriptor Visibility

**Files:**

- Modify: `src/registry/models.py`
- Modify: `src/registry/tools/public.py`
- Modify: `src/provider_adapters/openai_projection.py`
- Test: `tests/registry/test_catalog.py`
- Test: `tests/provider_adapters/test_projections.py`
- Test: `tests/registry/test_export.py`
- Test: `tests/registry/test_models.py`

- [ ] **Step 1: Add failing tests for stable public scopes and provider exports**

Append this test to `tests/registry/test_catalog.py`.

```python
def test_public_provider_scopes_use_stable_shipagent_tiers():
    tools = {tool.name: tool for tool in public_tools()}

    assert tools["get_shipagent_status"].auth_scopes == ["shipagent.status"]
    assert tools["validate_shipment_address"].auth_scopes == ["shipagent.preview"]
    assert tools["get_shipment_rates"].auth_scopes == ["shipagent.preview"]
    assert tools["prepare_shipments"].auth_scopes == ["shipagent.preview"]
    assert tools["execute_shipments"].auth_scopes == ["shipagent.execute"]
    assert tools["get_job_status"].auth_scopes == ["shipagent.execute"]
    assert tools["create_label_download"].auth_scopes == ["shipagent.artifacts"]
```

Replace `test_public_tools_are_tenant_safe_and_provider_exportable()` in `tests/registry/test_catalog.py` with:

```python
def test_public_tools_are_tenant_safe_and_provider_exportable():
    for tool in public_tools():
        assert tool.visibility == ToolVisibility.public
        assert tool.tenant_safe is True
        assert tool.implementation_status == "implemented"
        assert tool.hosted_readiness == "ready"
        assert tool.provider_export_enabled is True
        assert ProviderExport.openai_apps_public in tool.provider_exports
        assert ProviderExport.claude_remote_mcp_public in tool.provider_exports
        assert ProviderExport.anthropic not in tool.provider_exports


def test_generic_mcp_exports_status_and_preview_only():
    generic_names = {
        tool.name
        for tool in public_tools()
        if ProviderExport.generic_mcp in tool.provider_exports
    }

    assert generic_names == {
        "get_shipagent_status",
        "validate_shipment_address",
        "get_shipment_rates",
        "prepare_shipments",
    }
```

Append this test to `tests/provider_adapters/test_projections.py`.

```python
def test_openai_execute_descriptor_is_app_only_and_claude_descriptor_is_model_visible():
    openai_descriptor = to_openai_app_tool(tool("execute_shipments"))
    claude_descriptor = to_mcp_tool_descriptor(tool("execute_shipments"))

    assert openai_descriptor["_meta"]["ui"]["visibility"] == ["app"]
    assert "visibility" not in claude_descriptor.get("_meta", {}).get("ui", {})
```

Append this test to `tests/provider_adapters/test_projections.py`.

```python
def test_generic_mcp_excludes_execution_continuation_and_label_artifact_tools():
    exported = exportable_tools(ProviderExport.generic_mcp)

    assert {contract.name for contract in exported} == {
        "get_shipagent_status",
        "validate_shipment_address",
        "get_shipment_rates",
        "prepare_shipments",
    }
```

- [ ] **Step 2: Run the new scope/export tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py tests/provider_adapters/test_projections.py -v -k "stable_shipagent_tiers or generic_mcp_exports or execute_descriptor or excludes_execution"
```

Expected: FAIL because public tools still use legacy scopes, generic exports include all tools, and OpenAI descriptors have no app-only visibility.

- [ ] **Step 3: Add provider descriptor visibility to `ToolContract`**

In `src/registry/models.py`, add this field to `ToolContract` after `provider_exports`:

```python
    provider_descriptor_visibility: dict[
        str,
        Literal["model", "app", "hidden"],
    ] = Field(default_factory=dict)
```

The existing `from typing import Any, Literal` import already provides `Literal`.

- [ ] **Step 4: Update `public_tool()` to accept provider exports and descriptor visibility**

In `src/registry/tools/public.py`, update the `public_tool()` signature by adding these parameters before `requires_confirmation`:

```python
    provider_exports: list[ProviderExport] | None = None,
    provider_descriptor_visibility: dict[str, str] | None = None,
```

Inside the `ToolContract(...)` call, replace:

```python
        provider_exports=PUBLIC_RELAY_PROVIDERS,
```

with:

```python
        provider_exports=provider_exports or PUBLIC_RELAY_PROVIDERS,
        provider_descriptor_visibility=provider_descriptor_visibility or {},
```

Also change the `provider_export_enabled` default in the `public_tool()` signature from `False` to:

```python
    provider_export_enabled: bool = True,
```

- [ ] **Step 5: Update public scopes and generic export restrictions**

In `src/registry/tools/public.py`, update each public tool:

```python
    public_tool(
        "get_shipagent_status",
        "Get shipagent status",
        "Return operational status for the active account and execution target.",
        SideEffectClass.read,
        ["shipagent.status"],
```

```python
    public_tool(
        "validate_shipment_address",
        "Validate shipment address",
        "Validate a destination and return canonical address guidance.",
        SideEffectClass.estimate,
        ["shipagent.preview"],
```

```python
    public_tool(
        "get_shipment_rates",
        "Get shipment rates",
        "Generate rate options for a validated shipment request.",
        SideEffectClass.estimate,
        ["shipagent.preview"],
```

```python
    public_tool(
        "prepare_shipments",
        "Prepare shipments",
        "Create immutable preview artifacts for a shipment source.",
        SideEffectClass.estimate,
        ["shipagent.preview"],
```

```python
    public_tool(
        "execute_shipments",
        "Execute shipments",
        "Execute a prepared preview and return immutable execution artifacts.",
        SideEffectClass.purchase,
        ["shipagent.execute"],
```

```python
    public_tool(
        "get_job_status",
        "Get job status",
        "Get the status and progress summary for a ShipAgent job reference.",
        SideEffectClass.read,
        ["shipagent.execute"],
```

```python
    public_tool(
        "create_label_download",
        "Create label download",
        "Create a browser-authenticated label download reference for a completed shipment job.",
        SideEffectClass.read,
        ["shipagent.artifacts"],
```

For `execute_shipments`, `get_job_status`, and `create_label_download`, add this argument:

```python
        provider_exports=[
            ProviderExport.openai_apps_public,
            ProviderExport.claude_remote_mcp_public,
        ],
```

For `execute_shipments`, also add:

```python
        provider_descriptor_visibility={
            ProviderExport.openai_apps_public.value: "app",
            ProviderExport.claude_remote_mcp_public.value: "model",
        },
```

- [ ] **Step 6: Update OpenAI descriptor projection to emit app-only visibility**

Replace `src/provider_adapters/openai_projection.py` with:

```python
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.models import ProviderExport, ToolContract


def to_openai_app_tool(tool: ToolContract) -> dict:
    descriptor = to_mcp_tool_descriptor(tool)
    meta = descriptor.setdefault("_meta", {})
    ui_meta = meta.setdefault("ui", {})
    if tool.ui_resource:
        ui_meta["resourceUri"] = tool.ui_resource

    visibility = tool.provider_descriptor_visibility.get(
        ProviderExport.openai_apps_public.value
    )
    if visibility == "app":
        ui_meta["visibility"] = ["app"]
    elif visibility == "hidden":
        ui_meta["visibility"] = ["hidden"]

    if not ui_meta:
        meta.pop("ui", None)
    if not meta:
        descriptor.pop("_meta", None)
    return descriptor
```

- [ ] **Step 7: Update hosted tests for stable public scopes**

In `tests/hosted/test_hosted_mcp_registry.py`, replace legacy scope sets:

```python
scopes=frozenset({"account:read", "device:read"})
```

with:

```python
scopes=frozenset({"shipagent.status"})
```

Replace:

```python
assert exc.value.required_scopes == ["device:read"]
```

with:

```python
assert exc.value.required_scopes == ["shipagent.status"]
```

Replace:

```python
scopes=frozenset({"shipments:rate"})
```

with:

```python
scopes=frozenset({"shipagent.preview"})
```

- [ ] **Step 8: Update provider-adapter side-effect expectations**

In `tests/provider_adapters/test_projections.py`, replace the parametrized `test_side_effect_safety_metadata` cases with:

```python
    [
        ("get_shipagent_status", True, False, False, False),
        ("validate_shipment_address", True, False, False, False),
        ("get_shipment_rates", True, False, True, False),
        ("prepare_shipments", True, False, True, False),
        ("execute_shipments", False, False, True, True),
        ("get_job_status", True, False, False, False),
        ("create_label_download", True, False, True, False),
    ],
```

- [ ] **Step 9: Update registry export snapshot tests for removed `submit_one_off_shipment`**

In `tests/registry/test_export.py`, replace `EXPECTED_TOOL_NAMES` with:

```python
EXPECTED_TOOL_NAMES = [
    "get_shipagent_status",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
    "raw_ups_tool",
]
```

- [ ] **Step 10: Add a model test for descriptor visibility values**

Append this test to `tests/registry/test_models.py`.

```python
def test_tool_contract_accepts_provider_descriptor_visibility():
    tool = next(tool for tool in public_tools() if tool.name == "execute_shipments")

    assert tool.provider_descriptor_visibility == {
        "openai_apps_public": "app",
        "claude_remote_mcp_public": "model",
    }
```

If `tests/registry/test_models.py` does not already import `public_tools`, add:

```python
from src.registry.catalog import public_tools
```

- [ ] **Step 11: Run registry and projection tests**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_catalog.py tests/registry/test_export.py tests/registry/test_models.py tests/provider_adapters/test_projections.py tests/hosted/test_hosted_mcp_registry.py -v
```

Expected: PASS.

- [ ] **Step 12: Commit public surface changes**

```bash
git add src/registry/models.py src/registry/tools/public.py src/provider_adapters/openai_projection.py tests/registry/test_catalog.py tests/registry/test_export.py tests/registry/test_models.py tests/provider_adapters/test_projections.py tests/hosted/test_hosted_mcp_registry.py
git commit -m "feat: project public provider tool surfaces"
```

---

### Task 5: Regenerate Provider Artifacts From Canonical Sources

**Files:**

- Modify by generator only: `generated/provider_artifacts/claude_remote_mcp_public_tools.json`
- Modify by generator only: `generated/provider_artifacts/generic_mcp_tools.json`
- Modify by generator only: `generated/provider_artifacts/openai_apps_public_tools.json`
- Modify by generator only: `generated/provider_artifacts/registry.json`
- Test: `tests/registry/test_artifact_drift.py`

- [ ] **Step 1: Run the provider artifact generator**

Run:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
```

Expected: command exits 0 and rewrites provider artifacts from `src/registry/` and `src/provider_adapters/`.

- [ ] **Step 2: Inspect generated artifact diffs**

Run:

```bash
git diff -- generated/provider_artifacts
```

Expected:

- `registry.json` no longer contains `submit_one_off_shipment`.
- `openai_apps_public_tools.json` contains `execute_shipments` with `_meta.ui.visibility: ["app"]`.
- `claude_remote_mcp_public_tools.json` contains `execute_shipments` without app-only visibility.
- `generic_mcp_tools.json` contains only `get_shipagent_status`, `validate_shipment_address`, `get_shipment_rates`, and `prepare_shipments`.
- Public scopes are `shipagent.status`, `shipagent.preview`, `shipagent.execute`, and `shipagent.artifacts`.

- [ ] **Step 3: Run artifact drift test**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit generated artifacts**

```bash
git add generated/provider_artifacts/claude_remote_mcp_public_tools.json generated/provider_artifacts/generic_mcp_tools.json generated/provider_artifacts/openai_apps_public_tools.json generated/provider_artifacts/registry.json
git commit -m "chore: regenerate provider connector artifacts"
```

---

### Task 6: Add Regression Coverage For Plan 7 And Plan 8 Consumers

**Files:**

- Modify: `tests/control_plane/test_result_projection.py`
- Modify: `tests/provider_adapters/test_projections.py`

- [ ] **Step 1: Add a regression test proving Plan 7 can return schema-valid blocked envelopes**

Append this test to `tests/control_plane/test_result_projection.py`.

```python
def test_schema_valid_error_envelope_keeps_model_safe_fields():
    contract = _shipment_projection_contract(
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "reason": {"type": "string"},
                "terminal": {"type": "boolean"},
                "message": {"type": "string"},
                "approval_request_ref": {"type": "string"},
            },
            "required": ["status", "reason", "terminal", "message"],
            "additionalProperties": False,
        },
    )
    result = {
        "status": "blocked",
        "reason": "target_offline",
        "terminal": True,
        "message": "Your ShipAgent runtime is offline. Reconnect it and prepare again.",
        "approval_request_ref": "apr_123",
        "raw_response": {"detail": "target logs"},
        "request_body": {"secret": "value"},
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.CLAUDE_MARKDOWN,
            source_origin=DataOrigin.ACTIVE_SOURCE_SELECTION,
            provider_surface="claude_ai",
        ),
    )

    assert projected.structured_content == {
        "status": "blocked",
        "reason": "target_offline",
        "terminal": True,
        "message": "Your ShipAgent runtime is offline. Reconnect it and prepare again.",
        "approval_request_ref": "apr_123",
    }
    assert "target logs" not in projected.model_content
    assert "secret" not in projected.model_content
```

- [ ] **Step 2: Add a regression test proving Plan 8 can rely on widget meta while the model sees aggregates**

Append this test to `tests/control_plane/test_result_projection.py`.

```python
def test_openai_structured_projection_keeps_widget_meta_private():
    contract = _shipment_projection_contract()
    result = {
        "status": "preview_ready",
        "source_origin": "active_source_selection",
        "preview_ref": "prv_123",
        "summary": {
            "shipment_count": 3,
            "warning_count": 0,
            "total_charge": 27.66,
            "currency": "USD",
        },
        "widget_meta": {
            "approval_request_ref": "apr_123",
            "execute_tool": "execute_shipments",
            "preview_hash": "sha256:abc123",
        },
    }

    projected = project_provider_result(
        contract,
        result,
        ProjectionContext(
            output_profile=OutputProfile.OPENAI_STRUCTURED,
            source_origin=DataOrigin.ACTIVE_SOURCE_SELECTION,
            provider_surface="chatgpt",
        ),
    )

    assert "approval_request_ref" not in projected.structured_content
    assert projected.meta == {
        "approval_request_ref": "apr_123",
        "execute_tool": "execute_shipments",
        "preview_hash": "sha256:abc123",
    }
```

- [ ] **Step 3: Add a descriptor regression test for OpenAI widget dependency**

Append this test to `tests/provider_adapters/test_projections.py`.

```python
def test_openai_prepare_descriptor_keeps_widget_resource_and_model_visibility():
    descriptor = to_openai_app_tool(tool("prepare_shipments"))

    assert descriptor["_meta"]["ui"]["resourceUri"] == "ui://shipagent/preview.html"
    assert "visibility" not in descriptor["_meta"]["ui"]
```

- [ ] **Step 4: Run regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py tests/provider_adapters/test_projections.py -v -k "error_envelope or widget_meta_private or prepare_descriptor"
```

Expected: PASS.

- [ ] **Step 5: Commit regression coverage**

```bash
git add tests/control_plane/test_result_projection.py tests/provider_adapters/test_projections.py
git commit -m "test: lock connector projection contracts"
```

---

### Task 7: Full Verification For Plan 6

**Files:**

- No source edits in this task

- [ ] **Step 1: Run focused control-plane and registry tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py tests/hosted/test_hosted_mcp_registry.py tests/provider_adapters/test_projections.py tests/registry/test_catalog.py tests/registry/test_export.py tests/registry/test_models.py tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 2: Run conversation runtime tests to confirm Plan 6 did not change local runtime behavior**

Run:

```bash
.venv/bin/python -m pytest tests/services/conversation_runtime/ -v
```

Expected: PASS.

- [ ] **Step 3: Run broad backend validation excluding long stream/SSE/progress suites**

Run:

```bash
.venv/bin/python -m pytest -k "not stream and not sse and not progress"
```

Expected: PASS.

- [ ] **Step 4: Run lint**

Run:

```bash
.venv/bin/python -m ruff check src/ tests/
```

Expected: PASS.

- [ ] **Step 5: Run formatting check or format**

Run:

```bash
.venv/bin/python -m ruff format src/ tests/
```

Expected: command exits 0. If it changes files, review the formatting diff and include those files in the final commit.

- [ ] **Step 6: Confirm generated artifacts are current after formatting**

Run:

```bash
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit any formatting-only changes**

Run only if Step 5 changed files:

```bash
git add src/ tests/
git commit -m "style: format provider projection changes"
```

Expected: commit created only when `git diff -- src tests` showed formatting changes.

---

## Dependencies Consumed And Provided

Consumed from Plan 1:

- `AuthorizationContext.provider_surface` must be set for hosted MCP requests.
- Hosted tool requests must have a Provider Connection identity before projection runs.
- Plan 1 route context gives Plan 6 enough information to choose OpenAI structured output or Claude markdown; no relay dispatch behavior is required.

Provided to Plan 7:

- `project_provider_result()` and `ProjectionContext` for schema-valid provider results.
- D4 redaction enforcement for `one_off`, `active_source_selection`, `existing_batch`, and `local_history`.
- Unified `prepare_shipments.shipment_source` schema.
- Generic MCP export restrictions for execution, continuation, and label artifact tools.
- Stable public scopes for preview, execute, and artifacts.

Provided to Plan 8:

- OpenAI app-only descriptor metadata for `execute_shipments`.
- OpenAI widget metadata projection via FastMCP `ToolResult.meta`.
- `prepare_shipments` input schema with `one_off`, `active_source_selection`, and `existing_batch` variants.
- Model-visible structured content that stays aggregate-only for local-source data.

## Overlap Risks

- Plan 3 may add `minimum_capabilities` and version-gate metadata to `ToolContract`. This plan only adds `provider_descriptor_visibility`; do not edit version-gate fields or compatibility matrices in Plan 6.
- Plan 7 will implement approval requests, execution grants, job references, and label references. This plan defines provider-safe schemas and projection only; do not add approval persistence, execution dispatch, or label streaming here.
- Plan 8 will build the OpenAI widget UI and call app-only tools. This plan only emits descriptor visibility and widget metadata projection; do not create `provider-widget` assets or Angular/HTML widget behavior here.

## Self-Review Checklist

- Spec coverage: Tasks 1, 2, and 6 cover output profiles, D4 origin-based redaction, aggregate local-source projection, tracking-number masking, provider-safe formatting, OpenAI widget metadata, and Claude markdown. Tasks 3 and 4 cover unified `prepare_shipments` source schema, descriptor visibility, stable public scopes, public/private surfaces, and generic MCP restrictions. Task 5 covers generated artifacts via the generator. Task 7 covers the testing strategy.
- Placeholder scan: The plan contains concrete paths, commands, expected outcomes, and code snippets for every code-changing step.
- Type consistency: `OutputProfile`, `DataOrigin`, `ProjectionContext`, and `ProjectedToolResult` are defined in Task 1 and used consistently in Tasks 2 and 6. `provider_descriptor_visibility` is defined in Task 4 before OpenAI projection uses it.
