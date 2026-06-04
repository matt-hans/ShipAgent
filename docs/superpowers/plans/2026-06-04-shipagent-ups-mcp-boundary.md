# ShipAgent UPS MCP Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the UPS MCP boundary slice of `docs/superpowers/specs/2026-06-04-marketplace-production-readiness-design.md`: the ShipAgent-side hosted boundary for the external UPS MCP server, including typed capability contracts, safe adapter methods, response validators, fail-closed readiness checks, fixtures, and documentation. This repository owns the boundary and tests; the actual UPS MCP server changes happen in its separate repository under a separate implementation plan.

**Architecture:** Add a hosted-only `src/hosted/ups_boundary/` package that wraps the existing `UPSMCPClient` without moving UPS business logic into provider adapters. The boundary exposes introspection, evaluates whether the external UPS MCP server satisfies hosted-v1 requirements, validates normalized UPS responses before hosted workflows consume them, and produces readiness reports that production startup can fail closed on. Existing local desktop flows continue using `src/services/ups_mcp_client.py` directly until the broader marketplace workflow-spine phases replace the Claude SDK conversation path.

**Tech Stack:** Python, Pydantic v2, pytest, pytest-asyncio, existing `MCPClient`, existing `UPSMCPClient`, existing sanitized error taxonomy.

---

## Source Of Truth

This is a child implementation plan, not an independent product or architecture
spec. The authoritative hosted marketplace design is
`docs/superpowers/specs/2026-06-04-marketplace-production-readiness-design.md`.

Use this plan only for the ShipAgent-side UPS MCP boundary work. If this plan
conflicts with the marketplace readiness design, the marketplace readiness
design wins. Update this plan before implementation rather than resolving the
conflict ad hoc in code.

The external UPS MCP server is outside this repository. This plan may create a
contract document for that server, but it must not be used as the implementation
plan for the UPS MCP repository. That repository needs its own plan after this
ShipAgent boundary contract is accepted.

## Context

ShipAgent is moving from a local desktop shipping assistant to a hosted marketplace MCP app. The umbrella design is `docs/superpowers/specs/2026-06-04-marketplace-production-readiness-design.md`.

That umbrella now folds Claude SDK removal into the marketplace readiness roadmap:

- Phase 0 removes the Claude Agent SDK dependency and introduces a provider-neutral workflow/model-provider spine.
- Phase 1 locks the registry, DTO, and provider artifact contracts.
- Phase 2 builds hosted storage/readiness foundations.
- This plan is Phase 3: the hosted UPS MCP boundary and external UPS MCP contract.

The actual UPS MCP server is a different repository. This plan does not modify that external repository. It defines the ShipAgent-side boundary that makes that repository safe to depend on for hosted production:

- ShipAgent must not infer production readiness from "the local prototype works."
- ShipAgent must verify required UPS MCP tools are present.
- ShipAgent must require declared hosted capabilities that cannot be proven from tool names alone.
- ShipAgent must validate normalized UPS responses before those responses enter hosted previews, approval records, shipment execution, label metadata, or transcript-safe result envelopes.
- ShipAgent must document the contract the UPS MCP repository must satisfy.

This plan is intentionally narrow. It does not implement Claude SDK removal, the full hosted marketplace runtime, tenant repositories, workers, widgets, model-provider HTTP adapters, or provider artifacts. It creates the UPS boundary those hosted components will call.

## Phase Contract

This plan can be implemented after Phase 1 names the hosted DTO and error-envelope vocabulary. It can also run in parallel with Phase 0 and Phase 2 if the implementer keeps this package isolated from model-provider runtime code and tenant storage internals.

Inputs from earlier phases:

- hosted-v1 tool names and confirmation semantics from the registry contract
- provider-safe error envelope codes/categories
- decision that public marketplace tools expose ShipAgent workflow tools, not raw UPS MCP primitives
- decision that local model-provider runtime uses direct Python workflow/tool dispatch, not Claude SDK MCP orchestration

Outputs consumed by later phases:

- `HostedUpsBoundaryAdapter`
- capability/readiness report DTOs
- normalized UPS response validators
- UPS MCP capability contract documentation
- production readiness signal for hosted preview/rating/execution startup

This phase must not add model-provider SDK dependencies, `claude_agent_sdk`
imports, marketplace public tool handlers, registry exports, or frontend widget
code.

## Current Repo State

Existing files to reuse:

- `src/services/mcp_client.py` provides the generic async MCP stdio client and currently has `check_health()`, but no public tool-listing method.
- `src/services/ups_mcp_client.py` wraps the UPS MCP server and already supports:
  - `get_rate(request_body, requestoption="Rate")`
  - `get_rate(request_body, requestoption="Shop")`
  - `create_shipment(request_body)`
  - `validate_address(address)`
  - normalized rate, shop, address, shipment, pickup, tracking, and landed-cost results
  - retry policy separation for read-only versus mutating tools
- `src/services/gateway_provider.py` creates local UPS gateways using local credential resolution; hosted code must not reuse env/admin fallback as marketplace authorization.
- `src/hosted/confirmation_service.py` exists and is unrelated to this boundary except that future hosted shipment execution will consume both confirmation tokens and UPS boundary calls.
- `tests/services/test_mcp_client.py` and `tests/services/test_ups_mcp_client.py` already cover the current client behavior and should be extended, not replaced.

## Target File Structure

Create:

```text
src/hosted/ups_boundary/
  __init__.py
  adapter.py
  contract.py
  models.py
  readiness.py
  validators.py

tests/hosted/ups_boundary/
  test_adapter.py
  test_contract.py
  test_models.py
  test_readiness.py
  test_validators.py

docs/integrations/
  ups-mcp-hosted-contract.md
```

Modify:

```text
src/services/mcp_client.py
src/services/ups_mcp_client.py
tests/services/test_mcp_client.py
tests/services/test_ups_mcp_client.py
```

Do not modify in this plan:

```text
generated/provider_artifacts/
shipagent-frontend/
src/orchestrator/agent/
src/orchestrator/runtime/
src/api/routes/
src/registry/
pyproject.toml
shipagent-core.spec
scripts/start-backend.sh
```

Those areas are handled by the broader hosted marketplace readiness phases. In
particular, Phase 0 owns Claude SDK removal and model-provider HTTP adapters;
this plan owns only the UPS MCP boundary.

---

## Task 1: Add Boundary DTO Tests

- [ ] Create the test directory.

```bash
mkdir -p tests/hosted/ups_boundary
```

- [ ] Add `tests/hosted/ups_boundary/test_models.py` with tests for readiness defaults, deterministic serialization, and validation result shape.

```python
from datetime import datetime

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
    UpsBoundaryValidationResult,
)


def test_capability_report_is_ready_when_no_errors_or_missing_requirements() -> None:
    report = UpsBoundaryCapabilityReport(
        available_tools={"rate_shipment", "validate_address", "create_shipment"},
        declared_capabilities={
            UpsBoundaryCapability.RATE_QUOTE,
            UpsBoundaryCapability.RATE_SHOP,
            UpsBoundaryCapability.ADDRESS_VALIDATION,
            UpsBoundaryCapability.CREATE_SHIPMENT,
            UpsBoundaryCapability.CREATE_SHIPMENT_IDEMPOTENCY,
            UpsBoundaryCapability.SHIPMENT_RESPONSE_NORMALIZATION,
            UpsBoundaryCapability.INTERNATIONAL_CHARGES,
            UpsBoundaryCapability.SAFE_ERROR_MAPPING,
            UpsBoundaryCapability.MUTATING_RETRY_POLICY,
        },
    )

    assert report.ready is True
    assert isinstance(report.checked_at, datetime)


def test_capability_report_is_not_ready_with_missing_tools() -> None:
    report = UpsBoundaryCapabilityReport(missing_tools=["create_shipment"])

    assert report.ready is False


def test_capability_report_is_not_ready_with_error_check() -> None:
    report = UpsBoundaryCapabilityReport(
        checks=[
            UpsBoundaryCheck(
                name="declared_capabilities",
                severity=UpsBoundarySeverity.ERROR,
                message="UPS MCP did not declare hosted-v1 capabilities.",
            )
        ]
    )

    assert report.ready is False


def test_validation_result_serializes_without_raw_payloads() -> None:
    result = UpsBoundaryValidationResult(
        name="rate_shop",
        valid=False,
        error_code="E-3004",
        message="Missing rated shipment options.",
    )

    assert result.model_dump() == {
        "name": "rate_shop",
        "valid": False,
        "error_code": "E-3004",
        "message": "Missing rated shipment options.",
    }
```

- [ ] Run the model tests and confirm they fail because the package does not exist.

```bash
pytest tests/hosted/ups_boundary/test_models.py -q
```

Expected output includes:

```text
ModuleNotFoundError: No module named 'src.hosted.ups_boundary'
```

## Task 2: Implement Boundary DTOs

- [ ] Create `src/hosted/ups_boundary/__init__.py`.

```python
"""Hosted UPS MCP boundary contracts."""
```

- [ ] Create `src/hosted/ups_boundary/models.py`.

```python
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UpsBoundaryCapability(StrEnum):
    RATE_QUOTE = "rate_quote"
    RATE_SHOP = "rate_shop"
    ADDRESS_VALIDATION = "address_validation"
    CREATE_SHIPMENT = "create_shipment"
    CREATE_SHIPMENT_IDEMPOTENCY = "create_shipment_idempotency"
    SHIPMENT_RESPONSE_NORMALIZATION = "shipment_response_normalization"
    INTERNATIONAL_CHARGES = "international_charges"
    SAFE_ERROR_MAPPING = "safe_error_mapping"
    MUTATING_RETRY_POLICY = "mutating_retry_policy"


class UpsBoundarySeverity(StrEnum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


class UpsBoundaryCheck(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    name: str
    severity: UpsBoundarySeverity
    message: str


class UpsBoundaryValidationResult(BaseModel):
    name: str
    valid: bool
    error_code: str | None = None
    message: str = ""


class UpsBoundaryCapabilityReport(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    contract_version: str = "hosted-v1"
    server_name: str = "ups_mcp"
    server_version: str | None = None
    available_tools: set[str] = Field(default_factory=set)
    declared_capabilities: set[UpsBoundaryCapability] = Field(default_factory=set)
    missing_tools: list[str] = Field(default_factory=list)
    missing_capabilities: list[UpsBoundaryCapability] = Field(default_factory=list)
    checks: list[UpsBoundaryCheck] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def ready(self) -> bool:
        has_errors = any(check.severity == UpsBoundarySeverity.ERROR for check in self.checks)
        return not self.missing_tools and not self.missing_capabilities and not has_errors


class UpsBoundaryReadiness(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    status: Literal["ready", "degraded", "not_ready"]
    report: UpsBoundaryCapabilityReport
```

- [ ] Run the model tests.

```bash
pytest tests/hosted/ups_boundary/test_models.py -q
```

Expected output:

```text
4 passed
```

- [ ] Commit the DTOs and tests.

```bash
git add src/hosted/ups_boundary/__init__.py src/hosted/ups_boundary/models.py tests/hosted/ups_boundary/test_models.py
git commit -m "Add hosted UPS boundary DTOs"
```

## Task 3: Add Public MCP Tool Introspection Tests

- [ ] Append tests to `tests/services/test_mcp_client.py` for a public `list_tool_names()` method. If the file already has a suitable async test class, place these tests next to the existing health-check tests.

```python
@pytest.mark.asyncio
async def test_list_tool_names_returns_session_tool_names() -> None:
    client = MCPClient(command="node", args=["server.js"])
    client._session = AsyncMock()
    client._session.list_tools.return_value = SimpleNamespace(
        tools=[
            SimpleNamespace(name="rate_shipment"),
            SimpleNamespace(name="create_shipment"),
        ]
    )

    assert await client.list_tool_names() == {"rate_shipment", "create_shipment"}


@pytest.mark.asyncio
async def test_list_tool_names_requires_connected_session() -> None:
    client = MCPClient(command="node", args=["server.js"])

    with pytest.raises(MCPConnectionError):
        await client.list_tool_names()
```

- [ ] Ensure these imports exist in `tests/services/test_mcp_client.py`.

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.mcp_client import MCPClient, MCPConnectionError
```

- [ ] Run the new tests and confirm they fail because `list_tool_names()` does not exist.

```bash
pytest tests/services/test_mcp_client.py -q -k "list_tool_names"
```

Expected output includes:

```text
AttributeError: 'MCPClient' object has no attribute 'list_tool_names'
```

## Task 4: Implement Public MCP Tool Introspection

- [ ] In `src/services/mcp_client.py`, add this method to `MCPClient` near `check_health()`.

```python
    async def list_tool_names(self) -> set[str]:
        """Return tool names advertised by the connected MCP server."""
        if self._session is None:
            raise MCPConnectionError("MCP client not connected")

        result = await self._session.list_tools()
        tools = getattr(result, "tools", result)
        return {tool.name for tool in tools}
```

- [ ] Update `check_health()` in `src/services/mcp_client.py` to use the new method so introspection has one code path.

Replace the body with:

```python
    async def check_health(self) -> bool:
        """Check if MCP server is responsive."""
        try:
            await self.list_tool_names()
            return True
        except Exception as e:
            logger.warning(f"MCP health check failed: {e}")
            return False
```

- [ ] Run the targeted MCP client tests.

```bash
pytest tests/services/test_mcp_client.py -q -k "list_tool_names or health"
```

Expected output ends with passing tests for the selected cases.

- [ ] Commit the introspection change.

```bash
git add src/services/mcp_client.py tests/services/test_mcp_client.py
git commit -m "Expose MCP tool introspection"
```

## Task 5: Add UPS Client Boundary Introspection Tests

- [ ] Append tests to `tests/services/test_ups_mcp_client.py` for the UPS wrapper methods.

```python
@pytest.mark.asyncio
async def test_ups_client_lists_tool_names() -> None:
    mcp = AsyncMock()
    mcp.list_tool_names.return_value = {"rate_shipment", "shipagent_capabilities"}
    client = UPSMCPClient(mcp)

    assert await client.list_tool_names() == {"rate_shipment", "shipagent_capabilities"}


@pytest.mark.asyncio
async def test_ups_client_returns_none_when_capability_tool_missing() -> None:
    mcp = AsyncMock()
    mcp.list_tool_names.return_value = {"rate_shipment"}
    client = UPSMCPClient(mcp)

    assert await client.get_shipagent_capabilities() is None
    mcp.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_ups_client_reads_shipagent_capabilities() -> None:
    mcp = AsyncMock()
    mcp.list_tool_names.return_value = {"rate_shipment", "shipagent_capabilities"}
    mcp.call_tool.return_value = {
        "contract_version": "hosted-v1",
        "server_version": "1.2.3",
        "capabilities": ["rate_quote", "rate_shop"],
    }
    client = UPSMCPClient(mcp)

    assert await client.get_shipagent_capabilities() == {
        "contract_version": "hosted-v1",
        "server_version": "1.2.3",
        "capabilities": ["rate_quote", "rate_shop"],
    }
```

- [ ] Ensure `UPSMCPClient`, `AsyncMock`, and `pytest` are already imported in `tests/services/test_ups_mcp_client.py`; add missing imports only if needed.

- [ ] Run the new tests and confirm they fail because the methods do not exist.

```bash
pytest tests/services/test_ups_mcp_client.py -q -k "shipagent_capabilities or lists_tool_names"
```

Expected output includes an attribute error for `list_tool_names` or `get_shipagent_capabilities`.

## Task 6: Implement UPS Client Boundary Introspection

- [ ] In `src/services/ups_mcp_client.py`, add `shipagent_capabilities` to `_READ_ONLY_TOOLS`.

```python
    "shipagent_capabilities",
```

- [ ] Add these methods to `UPSMCPClient` near other small public client methods.

```python
    async def list_tool_names(self) -> set[str]:
        """Return tool names advertised by the UPS MCP server."""
        return await self._mcp.list_tool_names()

    async def get_shipagent_capabilities(self) -> dict[str, Any] | None:
        """Return optional ShipAgent hosted capability metadata from the UPS MCP server."""
        available_tools = await self.list_tool_names()
        if "shipagent_capabilities" not in available_tools:
            return None
        return await self._call("shipagent_capabilities", {})
```

- [ ] Confirm `Any` is imported from `typing` in `src/services/ups_mcp_client.py`; add it if missing.

- [ ] Run targeted UPS client tests.

```bash
pytest tests/services/test_ups_mcp_client.py -q -k "shipagent_capabilities or lists_tool_names"
```

Expected output ends with passing tests for the selected cases.

- [ ] Run the existing retry policy tests to confirm `shipagent_capabilities` is treated as read-only.

```bash
pytest tests/services/test_ups_mcp_client.py -q -k "retry or mutating"
```

Expected output ends with passing selected tests.

- [ ] Commit the UPS client introspection change.

```bash
git add src/services/ups_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "Expose UPS MCP hosted capabilities"
```

## Task 7: Add Contract Evaluation Tests

- [ ] Create `tests/hosted/ups_boundary/test_contract.py`.

```python
from src.hosted.ups_boundary.contract import (
    REQUIRED_CAPABILITIES,
    REQUIRED_TOOLS,
    evaluate_boundary_contract,
)
from src.hosted.ups_boundary.models import UpsBoundaryCapability, UpsBoundarySeverity


def test_required_contract_documents_first_release_boundary() -> None:
    assert REQUIRED_TOOLS == frozenset(
        {"rate_shipment", "validate_address", "create_shipment"}
    )
    assert UpsBoundaryCapability.RATE_SHOP in REQUIRED_CAPABILITIES
    assert UpsBoundaryCapability.CREATE_SHIPMENT_IDEMPOTENCY in REQUIRED_CAPABILITIES
    assert UpsBoundaryCapability.INTERNATIONAL_CHARGES in REQUIRED_CAPABILITIES


def test_evaluate_boundary_contract_ready_with_required_tools_and_capabilities() -> None:
    report = evaluate_boundary_contract(
        available_tools={"rate_shipment", "validate_address", "create_shipment"},
        declared_payload={
            "contract_version": "hosted-v1",
            "server_version": "1.2.3",
            "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
        },
    )

    assert report.ready is True
    assert report.server_version == "1.2.3"
    assert report.missing_tools == []
    assert report.missing_capabilities == []


def test_evaluate_boundary_contract_fails_without_create_shipment() -> None:
    report = evaluate_boundary_contract(
        available_tools={"rate_shipment", "validate_address"},
        declared_payload={
            "contract_version": "hosted-v1",
            "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
        },
    )

    assert report.ready is False
    assert report.missing_tools == ["create_shipment"]


def test_evaluate_boundary_contract_fails_without_declared_payload() -> None:
    report = evaluate_boundary_contract(
        available_tools={"rate_shipment", "validate_address", "create_shipment"},
        declared_payload=None,
    )

    assert report.ready is False
    assert UpsBoundaryCapability.CREATE_SHIPMENT_IDEMPOTENCY in report.missing_capabilities
    assert any(
        check.name == "shipagent_capabilities"
        and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_ignores_unknown_declared_capabilities() -> None:
    report = evaluate_boundary_contract(
        available_tools={"rate_shipment", "validate_address", "create_shipment"},
        declared_payload={
            "contract_version": "hosted-v1",
            "capabilities": [
                *(capability.value for capability in REQUIRED_CAPABILITIES),
                "future_capability",
            ],
        },
    )

    assert report.ready is True
```

- [ ] Run the contract tests and confirm they fail because `contract.py` does not exist.

```bash
pytest tests/hosted/ups_boundary/test_contract.py -q
```

Expected output includes:

```text
ModuleNotFoundError: No module named 'src.hosted.ups_boundary.contract'
```

## Task 8: Implement Contract Evaluation

- [ ] Create `src/hosted/ups_boundary/contract.py`.

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
)


REQUIRED_TOOLS = frozenset(
    {
        "rate_shipment",
        "validate_address",
        "create_shipment",
    }
)

TOOL_CAPABILITY_HINTS = {
    "rate_shipment": frozenset(
        {
            UpsBoundaryCapability.RATE_QUOTE,
            UpsBoundaryCapability.RATE_SHOP,
        }
    ),
    "validate_address": frozenset({UpsBoundaryCapability.ADDRESS_VALIDATION}),
    "create_shipment": frozenset({UpsBoundaryCapability.CREATE_SHIPMENT}),
}

DECLARATION_ONLY_CAPABILITIES = frozenset(
    {
        UpsBoundaryCapability.CREATE_SHIPMENT_IDEMPOTENCY,
        UpsBoundaryCapability.SHIPMENT_RESPONSE_NORMALIZATION,
        UpsBoundaryCapability.INTERNATIONAL_CHARGES,
        UpsBoundaryCapability.SAFE_ERROR_MAPPING,
        UpsBoundaryCapability.MUTATING_RETRY_POLICY,
    }
)

REQUIRED_CAPABILITIES = frozenset(
    {
        UpsBoundaryCapability.RATE_QUOTE,
        UpsBoundaryCapability.RATE_SHOP,
        UpsBoundaryCapability.ADDRESS_VALIDATION,
        UpsBoundaryCapability.CREATE_SHIPMENT,
        *DECLARATION_ONLY_CAPABILITIES,
    }
)


def evaluate_boundary_contract(
    *,
    available_tools: set[str],
    declared_payload: Mapping[str, Any] | None,
) -> UpsBoundaryCapabilityReport:
    declared_capabilities = _parse_declared_capabilities(declared_payload)
    inferred_capabilities = _infer_capabilities_from_tools(available_tools)
    effective_capabilities = declared_capabilities | inferred_capabilities

    missing_tools = sorted(REQUIRED_TOOLS - available_tools)
    missing_capabilities = sorted(
        REQUIRED_CAPABILITIES - effective_capabilities,
        key=lambda capability: capability.value,
    )
    checks = _build_checks(declared_payload, missing_tools, missing_capabilities)

    return UpsBoundaryCapabilityReport(
        server_version=_parse_server_version(declared_payload),
        available_tools=available_tools,
        declared_capabilities=declared_capabilities,
        missing_tools=missing_tools,
        missing_capabilities=missing_capabilities,
        checks=checks,
    )


def _infer_capabilities_from_tools(available_tools: set[str]) -> set[UpsBoundaryCapability]:
    inferred: set[UpsBoundaryCapability] = set()
    for tool_name in available_tools:
        inferred.update(TOOL_CAPABILITY_HINTS.get(tool_name, frozenset()))
    return inferred


def _parse_declared_capabilities(
    declared_payload: Mapping[str, Any] | None,
) -> set[UpsBoundaryCapability]:
    if declared_payload is None:
        return set()

    values = declared_payload.get("capabilities", [])
    if not isinstance(values, list):
        return set()

    capabilities: set[UpsBoundaryCapability] = set()
    for value in values:
        try:
            capabilities.add(UpsBoundaryCapability(value))
        except ValueError:
            continue
    return capabilities


def _parse_server_version(declared_payload: Mapping[str, Any] | None) -> str | None:
    if declared_payload is None:
        return None
    server_version = declared_payload.get("server_version")
    return server_version if isinstance(server_version, str) else None


def _build_checks(
    declared_payload: Mapping[str, Any] | None,
    missing_tools: list[str],
    missing_capabilities: list[UpsBoundaryCapability],
) -> list[UpsBoundaryCheck]:
    checks: list[UpsBoundaryCheck] = []

    if declared_payload is None:
        checks.append(
            UpsBoundaryCheck(
                name="shipagent_capabilities",
                severity=UpsBoundarySeverity.ERROR,
                message="UPS MCP did not expose hosted-v1 capability metadata.",
            )
        )

    if missing_tools:
        checks.append(
            UpsBoundaryCheck(
                name="required_tools",
                severity=UpsBoundarySeverity.ERROR,
                message=f"UPS MCP is missing required tools: {', '.join(missing_tools)}.",
            )
        )

    if missing_capabilities:
        missing = ", ".join(capability.value for capability in missing_capabilities)
        checks.append(
            UpsBoundaryCheck(
                name="required_capabilities",
                severity=UpsBoundarySeverity.ERROR,
                message=f"UPS MCP is missing required hosted capabilities: {missing}.",
            )
        )

    if not checks:
        checks.append(
            UpsBoundaryCheck(
                name="boundary_contract",
                severity=UpsBoundarySeverity.OK,
                message="UPS MCP satisfies ShipAgent hosted-v1 boundary requirements.",
            )
        )

    return checks
```

- [ ] Run the contract tests.

```bash
pytest tests/hosted/ups_boundary/test_contract.py -q
```

Expected output:

```text
5 passed
```

- [ ] Commit the contract evaluator.

```bash
git add src/hosted/ups_boundary/contract.py tests/hosted/ups_boundary/test_contract.py
git commit -m "Add hosted UPS boundary contract evaluation"
```

## Task 9: Add Boundary Adapter Tests

- [ ] Create `tests/hosted/ups_boundary/test_adapter.py`.

```python
from unittest.mock import AsyncMock

import pytest

from src.hosted.ups_boundary.adapter import HostedUpsBoundaryAdapter
from src.hosted.ups_boundary.models import UpsBoundaryCapability


@pytest.mark.asyncio
async def test_adapter_inspects_ups_client_capabilities() -> None:
    ups_client = AsyncMock()
    ups_client.list_tool_names.return_value = {
        "rate_shipment",
        "validate_address",
        "create_shipment",
    }
    ups_client.get_shipagent_capabilities.return_value = {
        "contract_version": "hosted-v1",
        "server_version": "1.2.3",
        "capabilities": [
            "rate_quote",
            "rate_shop",
            "address_validation",
            "create_shipment",
            "create_shipment_idempotency",
            "shipment_response_normalization",
            "international_charges",
            "safe_error_mapping",
            "mutating_retry_policy",
        ],
    }

    report = await HostedUpsBoundaryAdapter(ups_client).inspect_capabilities()

    assert report.ready is True
    assert report.server_version == "1.2.3"
    assert UpsBoundaryCapability.RATE_SHOP in report.declared_capabilities


@pytest.mark.asyncio
async def test_adapter_fails_closed_when_capabilities_are_absent() -> None:
    ups_client = AsyncMock()
    ups_client.list_tool_names.return_value = {
        "rate_shipment",
        "validate_address",
        "create_shipment",
    }
    ups_client.get_shipagent_capabilities.return_value = None

    report = await HostedUpsBoundaryAdapter(ups_client).inspect_capabilities()

    assert report.ready is False
    assert report.server_version is None
    assert report.missing_tools == []
    assert UpsBoundaryCapability.CREATE_SHIPMENT_IDEMPOTENCY in report.missing_capabilities
```

- [ ] Run adapter tests and confirm they fail because `adapter.py` does not exist.

```bash
pytest tests/hosted/ups_boundary/test_adapter.py -q
```

Expected output includes:

```text
ModuleNotFoundError: No module named 'src.hosted.ups_boundary.adapter'
```

## Task 10: Implement Boundary Adapter

- [ ] Create `src/hosted/ups_boundary/adapter.py`.

```python
from __future__ import annotations

from collections.abc import Mapping, Protocol
from typing import Any

from src.hosted.ups_boundary.contract import evaluate_boundary_contract
from src.hosted.ups_boundary.models import UpsBoundaryCapabilityReport


class UpsBoundaryClient(Protocol):
    async def list_tool_names(self) -> set[str]:
        ...

    async def get_shipagent_capabilities(self) -> Mapping[str, Any] | None:
        ...


class HostedUpsBoundaryAdapter:
    def __init__(self, ups_client: UpsBoundaryClient) -> None:
        self._ups_client = ups_client

    async def inspect_capabilities(self) -> UpsBoundaryCapabilityReport:
        available_tools = await self._ups_client.list_tool_names()
        declared_payload = await self._ups_client.get_shipagent_capabilities()
        return evaluate_boundary_contract(
            available_tools=available_tools,
            declared_payload=declared_payload,
        )
```

- [ ] Run adapter tests.

```bash
pytest tests/hosted/ups_boundary/test_adapter.py -q
```

Expected output:

```text
2 passed
```

- [ ] Commit the adapter.

```bash
git add src/hosted/ups_boundary/adapter.py tests/hosted/ups_boundary/test_adapter.py
git commit -m "Add hosted UPS boundary adapter"
```

## Task 11: Add Normalized UPS Response Validator Tests

- [ ] Create `tests/hosted/ups_boundary/test_validators.py`.

```python
from src.hosted.ups_boundary.validators import (
    validate_address_validation_result,
    validate_create_shipment_result,
    validate_rate_quote_result,
    validate_rate_shop_result,
)


def test_validate_rate_quote_result_accepts_normalized_charges() -> None:
    result = validate_rate_quote_result(
        {
            "success": True,
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
            "serviceCode": "03",
        }
    )

    assert result.valid is True


def test_validate_rate_quote_result_rejects_missing_currency() -> None:
    result = validate_rate_quote_result(
        {
            "success": True,
            "totalCharges": {"monetaryValue": "12.34"},
        }
    )

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_rate_shop_result_requires_options() -> None:
    result = validate_rate_shop_result({"success": True, "ratedShipments": []})

    assert result.valid is False
    assert result.error_code == "E-3004"


def test_validate_rate_shop_result_accepts_options() -> None:
    result = validate_rate_shop_result(
        {
            "success": True,
            "ratedShipments": [
                {
                    "serviceCode": "03",
                    "serviceDescription": "UPS Ground",
                    "totalCharges": {
                        "monetaryValue": "12.34",
                        "currencyCode": "USD",
                    },
                }
            ],
        }
    )

    assert result.valid is True


def test_validate_address_validation_result_accepts_known_status() -> None:
    result = validate_address_validation_result(
        {
            "status": "ambiguous",
            "candidates": [{"normalized": True}],
        }
    )

    assert result.valid is True


def test_validate_address_validation_result_rejects_unknown_status() -> None:
    result = validate_address_validation_result({"status": "maybe"})

    assert result.valid is False
    assert result.error_code == "E-3007"


def test_validate_create_shipment_result_accepts_normalized_label_metadata() -> None:
    result = validate_create_shipment_result(
        {
            "success": True,
            "shipmentIdentificationNumber": "1Z999",
            "trackingNumbers": ["1Z999"],
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
            "labelData": [{"format": "PDF"}],
        }
    )

    assert result.valid is True


def test_validate_create_shipment_result_rejects_missing_tracking() -> None:
    result = validate_create_shipment_result(
        {
            "success": True,
            "shipmentIdentificationNumber": "1Z999",
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
            "labelData": [{"format": "PDF"}],
        }
    )

    assert result.valid is False
    assert result.error_code == "E-3006"
```

- [ ] Run validator tests and confirm they fail because `validators.py` does not exist.

```bash
pytest tests/hosted/ups_boundary/test_validators.py -q
```

Expected output includes:

```text
ModuleNotFoundError: No module named 'src.hosted.ups_boundary.validators'
```

## Task 12: Implement Normalized UPS Response Validators

- [ ] Create `src/hosted/ups_boundary/validators.py`.

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.hosted.ups_boundary.models import UpsBoundaryValidationResult


def validate_rate_quote_result(result: Mapping[str, Any]) -> UpsBoundaryValidationResult:
    if result.get("success") is not True:
        return _invalid("rate_quote", "E-3004", "UPS rate quote was not successful.")
    if not _has_money(result.get("totalCharges")):
        return _invalid("rate_quote", "E-3004", "UPS rate quote is missing normalized charges.")
    return _valid("rate_quote")


def validate_rate_shop_result(result: Mapping[str, Any]) -> UpsBoundaryValidationResult:
    if result.get("success") is not True:
        return _invalid("rate_shop", "E-3004", "UPS rate shopping was not successful.")

    rated_shipments = result.get("ratedShipments")
    if not isinstance(rated_shipments, list) or not rated_shipments:
        return _invalid("rate_shop", "E-3004", "UPS rate shopping returned no options.")

    for option in rated_shipments:
        if not isinstance(option, Mapping):
            return _invalid("rate_shop", "E-3004", "UPS rate option is not normalized.")
        if not isinstance(option.get("serviceCode"), str) or not option["serviceCode"]:
            return _invalid("rate_shop", "E-3004", "UPS rate option is missing service code.")
        if not _has_money(option.get("totalCharges")):
            return _invalid("rate_shop", "E-3004", "UPS rate option is missing charges.")

    return _valid("rate_shop")


def validate_address_validation_result(result: Mapping[str, Any]) -> UpsBoundaryValidationResult:
    status = result.get("status")
    if status not in {"valid", "corrected", "ambiguous", "invalid", "unsupported", "unknown"}:
        return _invalid("address_validation", "E-3007", "UPS address validation status is invalid.")
    candidates = result.get("candidates")
    if candidates is not None and not isinstance(candidates, list):
        return _invalid("address_validation", "E-3007", "UPS address candidates are not normalized.")
    return _valid("address_validation")


def validate_create_shipment_result(result: Mapping[str, Any]) -> UpsBoundaryValidationResult:
    if result.get("success") is not True:
        return _invalid("create_shipment", "E-3006", "UPS shipment creation was not successful.")
    if not isinstance(result.get("shipmentIdentificationNumber"), str):
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing shipment ID.")
    tracking_numbers = result.get("trackingNumbers")
    if not isinstance(tracking_numbers, list) or not tracking_numbers:
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing tracking numbers.")
    if not _has_money(result.get("totalCharges")):
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing charges.")
    label_data = result.get("labelData")
    if not isinstance(label_data, list) or not label_data:
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing label metadata.")
    return _valid("create_shipment")


def _has_money(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return isinstance(value.get("monetaryValue"), str) and isinstance(value.get("currencyCode"), str)


def _valid(name: str) -> UpsBoundaryValidationResult:
    return UpsBoundaryValidationResult(name=name, valid=True)


def _invalid(name: str, error_code: str, message: str) -> UpsBoundaryValidationResult:
    return UpsBoundaryValidationResult(
        name=name,
        valid=False,
        error_code=error_code,
        message=message,
    )
```

- [ ] Run validator tests.

```bash
pytest tests/hosted/ups_boundary/test_validators.py -q
```

Expected output:

```text
8 passed
```

- [ ] Commit the validators.

```bash
git add src/hosted/ups_boundary/validators.py tests/hosted/ups_boundary/test_validators.py
git commit -m "Validate hosted UPS boundary responses"
```

## Task 13: Add Boundary Readiness Tests

- [ ] Create `tests/hosted/ups_boundary/test_readiness.py`.

```python
from unittest.mock import AsyncMock

import pytest

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapability,
    UpsBoundaryCapabilityReport,
    UpsBoundaryCheck,
    UpsBoundarySeverity,
)
from src.hosted.ups_boundary.readiness import check_ups_mcp_boundary_readiness


def _ready_report() -> UpsBoundaryCapabilityReport:
    return UpsBoundaryCapabilityReport(
        available_tools={"rate_shipment", "validate_address", "create_shipment"},
        declared_capabilities=set(UpsBoundaryCapability),
    )


@pytest.mark.asyncio
async def test_readiness_ready_when_report_is_ready() -> None:
    adapter = AsyncMock()
    adapter.inspect_capabilities.return_value = _ready_report()

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "ready"
    assert readiness.report.ready is True


@pytest.mark.asyncio
async def test_readiness_not_ready_when_report_is_missing_requirements() -> None:
    adapter = AsyncMock()
    adapter.inspect_capabilities.return_value = UpsBoundaryCapabilityReport(
        missing_tools=["create_shipment"]
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "not_ready"


@pytest.mark.asyncio
async def test_readiness_degraded_when_report_has_warning_only() -> None:
    adapter = AsyncMock()
    adapter.inspect_capabilities.return_value = UpsBoundaryCapabilityReport(
        available_tools={"rate_shipment", "validate_address", "create_shipment"},
        declared_capabilities=set(UpsBoundaryCapability),
        checks=[
            UpsBoundaryCheck(
                name="fixture_age",
                severity=UpsBoundarySeverity.WARN,
                message="UPS MCP fixture set is older than the review window.",
            )
        ],
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "degraded"
```

- [ ] Run readiness tests and confirm they fail because `readiness.py` does not exist.

```bash
pytest tests/hosted/ups_boundary/test_readiness.py -q
```

Expected output includes:

```text
ModuleNotFoundError: No module named 'src.hosted.ups_boundary.readiness'
```

## Task 14: Implement Boundary Readiness

- [ ] Create `src/hosted/ups_boundary/readiness.py`.

```python
from __future__ import annotations

from typing import Protocol

from src.hosted.ups_boundary.models import (
    UpsBoundaryCapabilityReport,
    UpsBoundaryReadiness,
    UpsBoundarySeverity,
)


class UpsBoundaryInspectable(Protocol):
    async def inspect_capabilities(self) -> UpsBoundaryCapabilityReport:
        ...


async def check_ups_mcp_boundary_readiness(
    adapter: UpsBoundaryInspectable,
) -> UpsBoundaryReadiness:
    report = await adapter.inspect_capabilities()

    if not report.ready:
        return UpsBoundaryReadiness(status="not_ready", report=report)

    has_warning = any(check.severity == UpsBoundarySeverity.WARN for check in report.checks)
    if has_warning:
        return UpsBoundaryReadiness(status="degraded", report=report)

    return UpsBoundaryReadiness(status="ready", report=report)
```

- [ ] Run readiness tests.

```bash
pytest tests/hosted/ups_boundary/test_readiness.py -q
```

Expected output:

```text
3 passed
```

- [ ] Commit the readiness probe.

```bash
git add src/hosted/ups_boundary/readiness.py tests/hosted/ups_boundary/test_readiness.py
git commit -m "Add hosted UPS boundary readiness probe"
```

## Task 15: Document the External UPS MCP Contract

- [ ] Create `docs/integrations/ups-mcp-hosted-contract.md`.

````markdown
# UPS MCP Hosted Contract

ShipAgent hosted marketplace runtime depends on an external UPS MCP server. That server lives in a separate repository. This document defines the contract ShipAgent validates before using that server in hosted production.

## Required Tools

The UPS MCP server must expose these MCP tools for hosted-v1:

- `rate_shipment`
- `validate_address`
- `create_shipment`
- `shipagent_capabilities`

`shipagent_capabilities` is read-only and returns metadata. It must not call UPS.

## Capability Declaration

`shipagent_capabilities` returns:

```json
{
  "contract_version": "hosted-v1",
  "server_version": "1.2.3",
  "capabilities": [
    "rate_quote",
    "rate_shop",
    "address_validation",
    "create_shipment",
    "create_shipment_idempotency",
    "shipment_response_normalization",
    "international_charges",
    "safe_error_mapping",
    "mutating_retry_policy"
  ]
}
```

ShipAgent can infer `rate_quote`, `rate_shop`, `address_validation`, and `create_shipment` from tool presence, but hosted production still requires the declaration because the remaining guarantees are behavioral.

## Behavioral Guarantees

- `rate_shipment` supports UPS `requestoption="Rate"` for default purchasable previews.
- `rate_shipment` supports UPS `requestoption="Shop"` for explicit rate comparison.
- `validate_address` returns normalized statuses: `valid`, `corrected`, `ambiguous`, `invalid`, `unsupported`, or `unknown`.
- `create_shipment` is mutating and must not be retried by generic MCP retry loops after the UPS boundary is crossed.
- `create_shipment` accepts deterministic idempotency inputs from ShipAgent hosted workers and preserves them through UPS calls where the UPS API supports them.
- Shipment responses are normalized before returning to ShipAgent.
- International shipping is supported only for configured, review-tested lanes in ShipAgent hosted production.
- Domain failures are returned in a form ShipAgent can map to hosted-safe error envelopes. Raw UPS XML/JSON responses, exception traces, local paths, credentials, and request payloads must not cross this boundary.

## Normalized Response Requirements

Rate quote responses must include:

- `success: true`
- `totalCharges.monetaryValue`
- `totalCharges.currencyCode`

Rate shop responses must include:

- `success: true`
- non-empty `ratedShipments`
- each option has `serviceCode`
- each option has `totalCharges.monetaryValue`
- each option has `totalCharges.currencyCode`

Address validation responses must include:

- `status`
- optional `candidates` array with normalized candidate data

Shipment creation responses must include:

- `success: true`
- `shipmentIdentificationNumber`
- non-empty `trackingNumbers`
- `totalCharges.monetaryValue`
- `totalCharges.currencyCode`
- non-empty `labelData`

## ShipAgent Ownership

ShipAgent owns:

- tenant authorization
- connected account selection
- origin profile selection
- order batch persistence
- preview checksums
- approval records
- confirmation tokens
- shipment worker idempotency keys
- hosted label metadata
- transcript-safe result envelopes
- provider artifacts and widgets

The UPS MCP server owns:

- UPS API request execution
- UPS response normalization
- UPS-specific error normalization
- UPS API version compatibility
- UPS lane/service capability implementation

## Local Runtime

Desktop/local ShipAgent flows may continue using environment fallback and local credential resolution. Hosted marketplace readiness must use this contract and fail closed when the external UPS MCP server does not satisfy it.
````

- [ ] Confirm the markdown file renders without unclosed fences.

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
path = Path("docs/integrations/ups-mcp-hosted-contract.md")
text = path.read_text()
assert text.count("```") % 2 == 0
print("balanced fences")
PY
```

Expected output:

```text
balanced fences
```

- [ ] Commit the contract document.

```bash
git add docs/integrations/ups-mcp-hosted-contract.md
git commit -m "Document UPS MCP hosted contract"
```

## Task 16: Run Boundary Test Suite

- [ ] Run all hosted UPS boundary tests.

```bash
pytest tests/hosted/ups_boundary -q
```

Expected output:

```text
22 passed
```

- [ ] Run the touched service tests.

```bash
pytest tests/services/test_mcp_client.py tests/services/test_ups_mcp_client.py -q -k "list_tool_names or shipagent_capabilities or health or retry or mutating"
```

Expected output ends with passing selected tests.

- [ ] Run lint on touched Python files.

```bash
ruff check \
  src/hosted/ups_boundary \
  src/services/mcp_client.py \
  src/services/ups_mcp_client.py \
  tests/hosted/ups_boundary \
  tests/services/test_mcp_client.py \
  tests/services/test_ups_mcp_client.py
```

Expected output:

```text
All checks passed!
```

- [ ] Run formatter check or formatter on touched Python files according to repo convention.

```bash
ruff format \
  src/hosted/ups_boundary \
  src/services/mcp_client.py \
  src/services/ups_mcp_client.py \
  tests/hosted/ups_boundary \
  tests/services/test_mcp_client.py \
  tests/services/test_ups_mcp_client.py
```

Expected output reports files unchanged or reformatted.

- [ ] If formatting changed files, rerun the tests from this task and commit the formatting changes.

```bash
git status --short
git add src/hosted/ups_boundary src/services/mcp_client.py src/services/ups_mcp_client.py tests/hosted/ups_boundary tests/services/test_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "Format hosted UPS boundary code"
```

If `git status --short` shows no tracked changes from formatting, do not create an empty commit.

## Task 17: Add Boundary Export Smoke Test

- [ ] Add `tests/hosted/ups_boundary/test_package_exports.py`.

```python
from src.hosted.ups_boundary.adapter import HostedUpsBoundaryAdapter
from src.hosted.ups_boundary.contract import evaluate_boundary_contract
from src.hosted.ups_boundary.readiness import check_ups_mcp_boundary_readiness
from src.hosted.ups_boundary.validators import validate_create_shipment_result


def test_boundary_package_imports_public_entrypoints() -> None:
    assert HostedUpsBoundaryAdapter is not None
    assert evaluate_boundary_contract is not None
    assert check_ups_mcp_boundary_readiness is not None
    assert validate_create_shipment_result is not None
```

- [ ] Run the smoke test.

```bash
pytest tests/hosted/ups_boundary/test_package_exports.py -q
```

Expected output:

```text
1 passed
```

- [ ] Commit the smoke test.

```bash
git add tests/hosted/ups_boundary/test_package_exports.py
git commit -m "Add hosted UPS boundary import smoke test"
```

## Task 18: Final Verification

- [ ] Run the complete boundary and touched service test set.

```bash
pytest \
  tests/hosted/ups_boundary \
  tests/services/test_mcp_client.py \
  tests/services/test_ups_mcp_client.py \
  -q
```

Expected output ends with all selected tests passing.

- [ ] Run lint across the touched paths.

```bash
ruff check \
  src/hosted/ups_boundary \
  src/services/mcp_client.py \
  src/services/ups_mcp_client.py \
  tests/hosted/ups_boundary \
  tests/services/test_mcp_client.py \
  tests/services/test_ups_mcp_client.py
```

Expected output:

```text
All checks passed!
```

- [ ] Review the resulting diff.

```bash
git diff --stat HEAD~8..HEAD
git diff HEAD~8..HEAD -- src/hosted/ups_boundary src/services/mcp_client.py src/services/ups_mcp_client.py tests/hosted/ups_boundary tests/services/test_mcp_client.py tests/services/test_ups_mcp_client.py docs/integrations/ups-mcp-hosted-contract.md
```

Expected review points:

- No hosted code reaches into `MCPClient._session`.
- No hosted code accepts UPS credentials, account numbers, tenant IDs, row payloads, labels, or local file paths.
- No provider adapter owns UPS shipping behavior.
- No UPS boundary code imports model-provider runtime modules or `claude_agent_sdk`.
- No changes in this plan add or remove model-provider dependencies.
- Boundary response validators return sanitized error codes/messages only.
- The external UPS MCP contract is documented in `docs/integrations/ups-mcp-hosted-contract.md`.

- [ ] Confirm no generated provider artifact files were modified.

```bash
git status --short generated/provider_artifacts
```

Expected output is empty.

- [ ] Commit any remaining tracked changes from final verification.

```bash
git status --short
git add docs/integrations/ups-mcp-hosted-contract.md src/hosted/ups_boundary src/services/mcp_client.py src/services/ups_mcp_client.py tests/hosted/ups_boundary tests/services/test_mcp_client.py tests/services/test_ups_mcp_client.py
git commit -m "Complete ShipAgent UPS MCP boundary"
```

If `git status --short` shows no tracked changes, the work is already committed.

---

## Done Criteria

The implementation is complete when all of these are true:

- `src/hosted/ups_boundary/` exists and imports cleanly.
- `MCPClient.list_tool_names()` is covered by tests.
- `UPSMCPClient.list_tool_names()` and `UPSMCPClient.get_shipagent_capabilities()` are covered by tests.
- `evaluate_boundary_contract()` fails closed when the external UPS MCP server is missing required tools or hosted-v1 capability declarations.
- `HostedUpsBoundaryAdapter.inspect_capabilities()` evaluates an injected `UPSMCPClient`-compatible object without accessing private MCP session state.
- Normalized UPS rate, shop, address validation, and shipment creation response validators are covered by positive and negative fixtures.
- `check_ups_mcp_boundary_readiness()` returns `ready`, `degraded`, or `not_ready` from a capability report.
- `docs/integrations/ups-mcp-hosted-contract.md` documents the required external UPS MCP server contract.
- Tests under `tests/hosted/ups_boundary` pass.
- Touched service tests for MCP introspection and UPS hosted capabilities pass.
- Ruff check passes on touched Python paths.
- No generated provider artifact files are changed by this plan.

## Notes For The External UPS MCP Repository

After this ShipAgent-side boundary lands, the UPS MCP repository needs matching work:

- Add a read-only `shipagent_capabilities` tool.
- Return the hosted-v1 capability payload exactly as documented.
- Ensure `rate_shipment` supports both `Rate` and `Shop` request options.
- Ensure `validate_address` returns normalized statuses compatible with ShipAgent validators.
- Ensure `create_shipment` honors deterministic idempotency input and never participates in generic retry loops after the UPS API boundary is crossed.
- Keep raw UPS responses, stack traces, credentials, local paths, and request payloads out of MCP-visible results.

Those changes belong in the UPS MCP repository, not this one.
