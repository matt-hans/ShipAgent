# ShipAgent UPS MCP Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the UPS MCP boundary slice of `docs/superpowers/specs/2026-06-04-marketplace-production-readiness-design.md`: the ShipAgent-side hosted boundary for the external UPS MCP server, including typed capability contracts, a readiness-only adapter, response validators, fail-closed readiness checks, hosted-v1 fixtures, and documentation. This repository owns the boundary and tests; the actual UPS MCP server changes happen in its separate repository under a separate implementation plan.

**Architecture:** Add a hosted-only `src/hosted/ups_boundary/` package around an injected `UpsBoundaryClient` protocol without moving UPS business logic into provider adapters. The boundary exposes introspection, evaluates whether the external UPS MCP server satisfies hosted-v1 requirements, defines validators for normalized UPS responses before later hosted workflows consume them, and produces readiness reports that production startup can fail closed on. Hosted production must inject a private remote MCP client for the UPS MCP service; stdio/subprocess clients remain local development and test paths. Existing local desktop flows continue using `src/services/ups_mcp_client.py` directly until the broader marketplace workflow-spine phases replace the Claude SDK conversation path.

This boundary plan must not break the Angular/Tauri desktop app, local FastAPI
routes, local SSE preview flow, or local model-provider path. It adds hosted
readiness contracts alongside the existing local UPS client path.

**Tech Stack:** Python, Pydantic v2, pytest, pytest-asyncio, transport-neutral client protocol, existing stdio `MCPClient`/`UPSMCPClient` for local development and tests, private remote MCP client for hosted production, existing sanitized error taxonomy.

---

## Source Of Truth

This is a child implementation plan, not an independent product or architecture
spec. The authoritative hosted marketplace design is
`docs/superpowers/specs/2026-06-04-marketplace-production-readiness-design.md`.

Use this plan only for the ShipAgent-side UPS MCP boundary work. If this plan
conflicts with the marketplace readiness design, the marketplace readiness
design wins. Update this plan before implementation rather than resolving the
conflict ad hoc in code.

The external UPS MCP server is outside this repository. This plan must create
the standalone `docs/integrations/ups-mcp-hosted-contract.md` file as the
discoverable handoff artifact for that server, but it must not be used as the
implementation plan for the UPS MCP repository. That repository needs its own
plan after this ShipAgent boundary contract is accepted.

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
- ShipAgent must define validators for normalized UPS responses before later hosted workers allow those responses to enter hosted previews, approval records, shipment execution, label metadata, or transcript-safe result envelopes.
- ShipAgent must document the contract the UPS MCP repository must satisfy.

This plan is intentionally narrow. It does not implement Claude SDK removal, the full hosted marketplace runtime, tenant repositories, workers, widgets, model-provider HTTP adapters, or provider artifacts. It creates the readiness contract, validators, and fixtures that later hosted components will use.

## Phase Contract

This plan can be implemented after Phase 1 names the hosted DTO and error-envelope vocabulary. It can also run in parallel with Phase 0 and Phase 2 if the implementer keeps this package isolated from model-provider runtime code and tenant storage internals.

Inputs from earlier phases:

- hosted-v1 tool names and confirmation semantics from the registry contract
- provider-safe error envelope codes/categories
- decision that public marketplace tools expose ShipAgent workflow tools, not raw UPS MCP primitives
- decision that hosted public tools do not expose row/sample payloads; they
  return only transcript-safe aggregates, opaque IDs, warning categories,
  redacted summaries, widget hints, and next actions
- decision that `international_charges` is necessary but not sufficient for
  hosted international shipping; every hosted-enabled international lane needs
  an explicit reviewed lane fixture
- decision that local model-provider runtime uses direct Python workflow/tool dispatch, not Claude SDK MCP orchestration

Outputs consumed by later phases:

- `UpsBoundaryClient` protocol for stdio/local and private-remote hosted clients
- `HostedUpsBoundaryAdapter`
- capability/readiness report DTOs
- normalized UPS response validators
- hosted-v1 success and safe-error fixtures
- standalone UPS MCP capability contract documentation at
  `docs/integrations/ups-mcp-hosted-contract.md`
- production readiness signal for hosted preview/rating/execution startup

This phase must not add model-provider SDK dependencies, `claude_agent_sdk`
imports, marketplace public tool handlers, registry exports, public hosted tool
projections, generated provider artifacts, or frontend widget code. Registry
exports and provider projections belong to the registry/provider-artifact phase;
changing them here risks exposing raw UPS primitives before the public hosted
workflow surface is finalized.

This UPS boundary is not an internal model-planning layer. Hosted workers later
call deterministic ShipAgent services and the UPS MCP boundary directly; they do
not send row-level shipment data to a second internal LLM before reaching UPS.
The boundary must also not become a path for public hosted tools to expose sample
rows, row payloads, labels, request bodies, or raw UPS responses.
The private UPS MCP hop exists to isolate UPS-specific protocol, auth,
normalization, retry/idempotency, and raw response handling behind a contract.
It is not a second public MCP app, and it is not used for reasoning.

This phase also must not add hosted UPS operation methods such as
`rate_quote_shipagent_v1()`, `validate_address_shipagent_v1()`, or
`create_shipment_shipagent_v1()` to `HostedUpsBoundaryAdapter`. Later hosted
worker phases own operation call paths, per-tenant credential handoff,
`response_format="shipagent_v1"` invocation, label persistence, and public
result stripping.

This phase also must not implement hosted private-remote MCP transport. It may
define the `UpsBoundaryClient` protocol and exercise it with the existing
stdio-backed local/test client, but `PrivateRemoteUpsMcpClient`, service-to-
service auth, remote endpoint configuration, network observability, per-tenant
credential handoff, and production startup wiring belong to later hosted
runtime/auth/storage phases. Hosted production readiness must fail closed until
that remote client exists and passes this boundary's readiness checks.
`degraded` readiness is diagnostic only for local development, CI reports, and
pre-production review. Hosted production startup must require
`status == "ready"` and fail closed for both `not_ready` and `degraded`.
This phase defines warning/degraded shape with static examples only. It must not
compute real fixture freshness, review age, or provenance timestamps; provider
review automation owns those checks later.

## Current Repo State

Existing files to reuse:

- `src/services/mcp_client.py` provides the generic async MCP stdio client for local development and tests and currently has `check_health()`, but no public tool-listing method.
- `src/services/ups_mcp_client.py` wraps the UPS MCP server and already supports:
  - `get_rate(request_body, requestoption="Rate")`
  - `get_rate(request_body, requestoption="Shop")`
  - `create_shipment(request_body)`
  - `validate_address(address)`
  - normalized rate, shop, address, shipment, pickup, tracking, and landed-cost results
  - retry policy separation for read-only versus mutating tools
- Hosted production should not launch the UPS MCP server as a subprocess. It should inject a private remote MCP client that satisfies the same `UpsBoundaryClient` protocol.
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
  fixtures.py
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
Phase 1 owns registry exports, public hosted tool projections, and generated
provider artifacts; this plan owns only the UPS MCP boundary.
Desktop compatibility is a non-goal for this specific package only because the
package is hosted-boundary scoped; it must still avoid changing or regressing
desktop behavior.

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


def test_capability_report_is_not_ready_by_default() -> None:
    report = UpsBoundaryCapabilityReport()

    assert report.ready is False
    assert isinstance(report.checked_at, datetime)


def test_capability_report_is_ready_with_positive_contract_evidence() -> None:
    report = UpsBoundaryCapabilityReport(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_capabilities={
            UpsBoundaryCapability.RATE_QUOTE,
            UpsBoundaryCapability.RATE_SHOP,
            UpsBoundaryCapability.ADDRESS_VALIDATION,
            UpsBoundaryCapability.CREATE_SHIPMENT,
            UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH,
            UpsBoundaryCapability.SHIPMENT_RESPONSE_NORMALIZATION,
            UpsBoundaryCapability.INTERNATIONAL_CHARGES,
            UpsBoundaryCapability.SAFE_ERROR_MAPPING,
            UpsBoundaryCapability.MUTATING_RETRY_POLICY,
        },
        response_formats={"shipagent_v1"},
        checks=[
            UpsBoundaryCheck(
                name="boundary_contract",
                severity=UpsBoundarySeverity.OK,
                message="Hosted UPS boundary contract is ready.",
            )
        ],
    )

    assert report.ready is True


def test_capability_report_is_not_ready_with_missing_tools() -> None:
    report = UpsBoundaryCapabilityReport(missing_tools=["create_shipment"])

    assert report.ready is False


def test_capability_report_is_not_ready_with_missing_response_formats() -> None:
    report = UpsBoundaryCapabilityReport(missing_response_formats=["shipagent_v1"])

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
    IDEMPOTENCY_METADATA_PASSTHROUGH = "idempotency_metadata_passthrough"
    CARRIER_IDEMPOTENT_CREATE = "carrier_idempotent_create"
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
    response_formats: set[str] = Field(default_factory=set)
    missing_tools: list[str] = Field(default_factory=list)
    missing_capabilities: list[UpsBoundaryCapability] = Field(default_factory=list)
    missing_response_formats: list[str] = Field(default_factory=list)
    checks: list[UpsBoundaryCheck] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def ready(self) -> bool:
        if (
            self.missing_tools
            or self.missing_capabilities
            or self.missing_response_formats
        ):
            return False
        if any(check.severity == UpsBoundarySeverity.ERROR for check in self.checks):
            return False

        has_contract_success = any(
            check.name == "boundary_contract"
            and check.severity == UpsBoundarySeverity.OK
            for check in self.checks
        )
        return (
            bool(self.available_tools)
            and bool(self.declared_capabilities)
            and bool(self.response_formats)
            and has_contract_success
        )


class UpsBoundaryReadiness(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    status: Literal["ready", "degraded", "not_ready"]
    report: UpsBoundaryCapabilityReport

    @property
    def production_ready(self) -> bool:
        return self.status == "ready"
```

- [ ] Run the model tests.

```bash
pytest tests/hosted/ups_boundary/test_models.py -q
```

Expected output:

```text
6 passed
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
        "response_formats": ["raw", "shipagent_v1"],
    }
    client = UPSMCPClient(mcp)

    assert await client.get_shipagent_capabilities() == {
        "contract_version": "hosted-v1",
        "server_version": "1.2.3",
        "capabilities": ["rate_quote", "rate_shop"],
        "response_formats": ["raw", "shipagent_v1"],
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
    REQUIRED_CONTRACT_VERSION,
    REQUIRED_RESPONSE_FORMATS,
    REQUIRED_TOOLS,
    evaluate_boundary_contract,
)
from src.hosted.ups_boundary.models import UpsBoundaryCapability, UpsBoundarySeverity


def test_required_contract_documents_first_release_boundary() -> None:
    assert REQUIRED_CONTRACT_VERSION == "hosted-v1"
    assert REQUIRED_TOOLS == frozenset(
        {
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        }
    )
    assert UpsBoundaryCapability.RATE_SHOP in REQUIRED_CAPABILITIES
    assert UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH in REQUIRED_CAPABILITIES
    assert UpsBoundaryCapability.INTERNATIONAL_CHARGES in REQUIRED_CAPABILITIES
    assert REQUIRED_RESPONSE_FORMATS == frozenset({"shipagent_v1"})


def test_evaluate_boundary_contract_ready_with_required_tools_and_capabilities() -> None:
    report = evaluate_boundary_contract(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_payload={
            "contract_version": "hosted-v1",
            "server_version": "1.2.3",
            "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
            "response_formats": ["raw", "shipagent_v1"],
        },
    )

    assert report.ready is True
    assert report.server_version == "1.2.3"
    assert report.missing_tools == []
    assert report.missing_capabilities == []
    assert report.missing_response_formats == []


def test_evaluate_boundary_contract_fails_with_wrong_contract_version() -> None:
    report = evaluate_boundary_contract(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_payload={
            "contract_version": "hosted-v0",
            "server_version": "1.2.3",
            "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
            "response_formats": ["raw", "shipagent_v1"],
        },
    )

    assert report.ready is False
    assert any(
        check.name == "contract_version"
        and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_fails_without_create_shipment() -> None:
    report = evaluate_boundary_contract(
        available_tools={
            "rate_shipment",
            "validate_address",
            "shipagent_capabilities",
        },
        declared_payload={
            "contract_version": "hosted-v1",
            "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
            "response_formats": ["shipagent_v1"],
        },
    )

    assert report.ready is False
    assert report.missing_tools == ["create_shipment"]


def test_evaluate_boundary_contract_fails_without_declared_payload() -> None:
    report = evaluate_boundary_contract(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_payload=None,
    )

    assert report.ready is False
    assert UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH in report.missing_capabilities
    assert report.missing_response_formats == ["shipagent_v1"]
    assert any(
        check.name == "shipagent_capabilities"
        and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_fails_without_shipagent_v1_response_format() -> None:
    report = evaluate_boundary_contract(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_payload={
            "contract_version": "hosted-v1",
            "capabilities": [capability.value for capability in REQUIRED_CAPABILITIES],
            "response_formats": ["raw"],
        },
    )

    assert report.ready is False
    assert report.missing_response_formats == ["shipagent_v1"]
    assert any(
        check.name == "required_response_formats"
        and check.severity == UpsBoundarySeverity.ERROR
        for check in report.checks
    )


def test_evaluate_boundary_contract_ignores_unknown_declared_capabilities() -> None:
    report = evaluate_boundary_contract(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_payload={
            "contract_version": "hosted-v1",
            "capabilities": [
                *(capability.value for capability in REQUIRED_CAPABILITIES),
                "future_capability",
            ],
            "response_formats": ["raw", "shipagent_v1", "future_format"],
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


REQUIRED_CONTRACT_VERSION = "hosted-v1"

REQUIRED_TOOLS = frozenset(
    {
        "rate_shipment",
        "validate_address",
        "create_shipment",
        "shipagent_capabilities",
    }
)

REQUIRED_RESPONSE_FORMATS = frozenset({"shipagent_v1"})

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
        UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH,
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
    declared_response_formats = _parse_response_formats(declared_payload)
    inferred_capabilities = _infer_capabilities_from_tools(available_tools)
    effective_capabilities = declared_capabilities | inferred_capabilities

    missing_tools = sorted(REQUIRED_TOOLS - available_tools)
    missing_capabilities = sorted(
        REQUIRED_CAPABILITIES - effective_capabilities,
        key=lambda capability: capability.value,
    )
    missing_response_formats = sorted(
        REQUIRED_RESPONSE_FORMATS - declared_response_formats
    )
    checks = _build_checks(
        declared_payload,
        missing_tools,
        missing_capabilities,
        missing_response_formats,
    )

    return UpsBoundaryCapabilityReport(
        server_version=_parse_server_version(declared_payload),
        available_tools=available_tools,
        declared_capabilities=declared_capabilities,
        response_formats=declared_response_formats,
        missing_tools=missing_tools,
        missing_capabilities=missing_capabilities,
        missing_response_formats=missing_response_formats,
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


def _parse_response_formats(declared_payload: Mapping[str, Any] | None) -> set[str]:
    if declared_payload is None:
        return set()

    values = declared_payload.get("response_formats", [])
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str)}


def _parse_server_version(declared_payload: Mapping[str, Any] | None) -> str | None:
    if declared_payload is None:
        return None
    server_version = declared_payload.get("server_version")
    return server_version if isinstance(server_version, str) else None


def _build_checks(
    declared_payload: Mapping[str, Any] | None,
    missing_tools: list[str],
    missing_capabilities: list[UpsBoundaryCapability],
    missing_response_formats: list[str],
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
    elif declared_payload.get("contract_version") != REQUIRED_CONTRACT_VERSION:
        checks.append(
            UpsBoundaryCheck(
                name="contract_version",
                severity=UpsBoundarySeverity.ERROR,
                message=(
                    "UPS MCP contract version must be "
                    f"{REQUIRED_CONTRACT_VERSION}."
                ),
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

    if missing_response_formats:
        checks.append(
            UpsBoundaryCheck(
                name="required_response_formats",
                severity=UpsBoundarySeverity.ERROR,
                message=(
                    "UPS MCP is missing required hosted response formats: "
                    f"{', '.join(missing_response_formats)}."
                ),
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
7 passed
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
        "shipagent_capabilities",
    }
    ups_client.get_shipagent_capabilities.return_value = {
        "contract_version": "hosted-v1",
        "server_version": "1.2.3",
        "capabilities": [
            "rate_quote",
            "rate_shop",
            "address_validation",
            "create_shipment",
            "idempotency_metadata_passthrough",
            "shipment_response_normalization",
            "international_charges",
            "safe_error_mapping",
            "mutating_retry_policy",
        ],
        "response_formats": ["raw", "shipagent_v1"],
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
        "shipagent_capabilities",
    }
    ups_client.get_shipagent_capabilities.return_value = None

    report = await HostedUpsBoundaryAdapter(ups_client).inspect_capabilities()

    assert report.ready is False
    assert report.server_version is None
    assert report.missing_tools == []
    assert UpsBoundaryCapability.IDEMPOTENCY_METADATA_PASSTHROUGH in report.missing_capabilities
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

`HostedUpsBoundaryAdapter` is readiness-only in this phase. Do not add methods
that call `rate_shipment`, `validate_address`, or `create_shipment`; those
operation paths belong to the later hosted worker phase after remote transport,
tenant credential handoff, and artifact storage are defined.

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
from src.hosted.ups_boundary.fixtures import (
    HOSTED_V1_ADDRESS_VALIDATION_SUCCESS,
    HOSTED_V1_CREATE_SHIPMENT_SUCCESS,
    HOSTED_V1_RATE_QUOTE_SUCCESS,
    HOSTED_V1_RATE_SHOP_SUCCESS,
    HOSTED_V1_SAFE_ERROR,
)
from src.hosted.ups_boundary.validators import (
    validate_address_validation_result,
    validate_create_shipment_result,
    validate_rate_quote_result,
    validate_rate_shop_result,
    validate_safe_error_result,
)


def test_validate_rate_quote_result_accepts_normalized_charges() -> None:
    result = validate_rate_quote_result(HOSTED_V1_RATE_QUOTE_SUCCESS)

    assert result.valid is True


def test_validate_rate_quote_result_accepts_extra_success_fields() -> None:
    result = validate_rate_quote_result(
        {
            **HOSTED_V1_RATE_QUOTE_SUCCESS,
            "serviceDescription": "UPS Ground",
            "negotiatedRate": True,
            "warnings": [{"code": "TRANSIT_ESTIMATE"}],
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
    result = validate_rate_shop_result(HOSTED_V1_RATE_SHOP_SUCCESS)

    assert result.valid is True


def test_validate_address_validation_result_accepts_known_status() -> None:
    result = validate_address_validation_result(HOSTED_V1_ADDRESS_VALIDATION_SUCCESS)

    assert result.valid is True


def test_validate_address_validation_result_accepts_extra_success_fields() -> None:
    result = validate_address_validation_result(
        {
            **HOSTED_V1_ADDRESS_VALIDATION_SUCCESS,
            "correctionNotes": ["Postal code normalized."],
            "confidence": "high",
        }
    )

    assert result.valid is True


def test_validate_address_validation_result_rejects_unknown_status() -> None:
    result = validate_address_validation_result({"status": "maybe"})

    assert result.valid is False
    assert result.error_code == "E-3007"


def test_validate_create_shipment_result_accepts_normalized_label_metadata() -> None:
    result = validate_create_shipment_result(HOSTED_V1_CREATE_SHIPMENT_SUCCESS)

    assert result.valid is True


def test_validate_create_shipment_result_rejects_missing_tracking() -> None:
    result = validate_create_shipment_result(
        {
            "success": True,
            "idempotencyKey": "job-1:row-1:abc123",
            "shipmentIdentificationNumber": "1Z999",
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
            "labelData": [
                {
                    "format": "PDF",
                    "encoding": "base64",
                    "contentBase64": "JVBERi0xLjQ=",
                }
            ],
        }
    )

    assert result.valid is False
    assert result.error_code == "E-3006"


def test_validate_safe_error_result_accepts_safe_error_shape() -> None:
    result = validate_safe_error_result(HOSTED_V1_SAFE_ERROR)

    assert result.valid is True


def test_validate_safe_error_result_rejects_raw_details() -> None:
    result = validate_safe_error_result(
        {
            "success": False,
            "error": {
                "code": "UPS_VALIDATION",
                "category": "validation",
                "message": "UPS validation failed.",
                "retryable": False,
                "correlation_id": "corr-123",
                "details": {"raw": {"ShipmentRequest": {}}},
            },
        }
    )

    assert result.valid is False
    assert result.error_code == "E-3008"


def test_validate_safe_error_result_rejects_unlisted_error_keys() -> None:
    result = validate_safe_error_result(
        {
            "success": False,
            "error": {
                "code": "UPS_SERVICE_UNAVAILABLE",
                "category": "service_unavailable",
                "message": "UPS is unavailable.",
                "retryable": True,
                "correlation_id": "corr-123",
                "provider_status": 503,
            },
        }
    )

    assert result.valid is False
    assert result.error_code == "E-3008"
```

- [ ] Run validator tests and confirm they fail because `fixtures.py` and `validators.py` do not exist.

```bash
pytest tests/hosted/ups_boundary/test_validators.py -q
```

Expected output includes:

```text
ModuleNotFoundError: No module named 'src.hosted.ups_boundary.fixtures'
```

## Task 12: Implement Normalized UPS Response Validators

- [ ] Create `src/hosted/ups_boundary/fixtures.py`.

These fixtures are synthetic hosted-v1 contract examples. They must not contain
real customer data, credentials, tracking numbers, or real label bytes.

```python
from __future__ import annotations

from typing import Any


HOSTED_V1_RATE_QUOTE_SUCCESS: dict[str, Any] = {
    "success": True,
    "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
    "serviceCode": "03",
}

HOSTED_V1_RATE_SHOP_SUCCESS: dict[str, Any] = {
    "success": True,
    "ratedShipments": [
        {
            "serviceCode": "03",
            "serviceDescription": "UPS Ground",
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
        }
    ],
}

HOSTED_V1_ADDRESS_VALIDATION_SUCCESS: dict[str, Any] = {
    "status": "ambiguous",
    "candidates": [{"normalized": True}],
}

HOSTED_V1_CREATE_SHIPMENT_SUCCESS: dict[str, Any] = {
    "success": True,
    "idempotencyKey": "hosted-job-1:preview-row-1:abc123",
    "shipmentIdentificationNumber": "1ZHOSTEDTEST",
    "trackingNumbers": ["1ZHOSTEDTEST"],
    "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
    "labelData": [
        {
            "format": "PDF",
            "encoding": "base64",
            "contentBase64": "JVBERi0xLjQ=",
        }
    ],
}

HOSTED_V1_SAFE_ERROR: dict[str, Any] = {
    "success": False,
    "error": {
        "code": "UPS_RATE_LIMIT",
        "category": "rate_limit",
        "message": "UPS rate limit exceeded.",
        "retryable": True,
        "correlation_id": "corr-hosted-test",
    },
}
```

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
    if not isinstance(result.get("idempotencyKey"), str) or not result["idempotencyKey"]:
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing idempotency key.")
    if not isinstance(result.get("shipmentIdentificationNumber"), str):
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing shipment ID.")
    tracking_numbers = result.get("trackingNumbers")
    if not isinstance(tracking_numbers, list) or not tracking_numbers:
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing tracking numbers.")
    if not _has_money(result.get("totalCharges")):
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing charges.")
    label_data = result.get("labelData")
    if not isinstance(label_data, list) or not label_data:
        return _invalid("create_shipment", "E-3006", "UPS shipment response is missing label data.")
    for label in label_data:
        if not isinstance(label, Mapping):
            return _invalid("create_shipment", "E-3006", "UPS label data is not normalized.")
        if not isinstance(label.get("format"), str) or not label["format"]:
            return _invalid("create_shipment", "E-3006", "UPS label data is missing format.")
        if label.get("encoding") != "base64":
            return _invalid("create_shipment", "E-3006", "UPS label data is missing base64 encoding.")
        if not isinstance(label.get("contentBase64"), str) or not label["contentBase64"]:
            return _invalid("create_shipment", "E-3006", "UPS label data is missing internal label content.")
    return _valid("create_shipment")


_SAFE_ERROR_CATEGORIES = {
    "auth",
    "rate_limit",
    "validation",
    "service_unavailable",
    "address",
    "customs",
    "transport",
    "unknown",
}

_SAFE_ERROR_KEYS = {
    "code",
    "category",
    "message",
    "retryable",
    "correlation_id",
}

_UNSAFE_ERROR_KEYS = {
    "details",
    "raw",
    "raw_response",
    "request",
    "request_body",
    "payload",
    "stack",
    "stack_trace",
    "traceback",
    "local_path",
    "path",
    "credentials",
    "client_secret",
    "access_token",
}


def validate_safe_error_result(result: Mapping[str, Any]) -> UpsBoundaryValidationResult:
    if result.get("success") is not False:
        return _invalid("safe_error", "E-3008", "UPS error result must be marked unsuccessful.")

    error = result.get("error")
    if not isinstance(error, Mapping):
        return _invalid("safe_error", "E-3008", "UPS error result is missing error envelope.")

    if _contains_unsafe_error_key(error):
        return _invalid("safe_error", "E-3008", "UPS error result contains unsafe raw details.")

    if any(key not in _SAFE_ERROR_KEYS for key in error):
        return _invalid("safe_error", "E-3008", "UPS error result contains non-contract fields.")

    if not isinstance(error.get("code"), str) or not error["code"]:
        return _invalid("safe_error", "E-3008", "UPS error result is missing code.")
    if error.get("category") not in _SAFE_ERROR_CATEGORIES:
        return _invalid("safe_error", "E-3008", "UPS error result has invalid category.")
    if not isinstance(error.get("message"), str) or not error["message"]:
        return _invalid("safe_error", "E-3008", "UPS error result is missing message.")
    if not isinstance(error.get("retryable"), bool):
        return _invalid("safe_error", "E-3008", "UPS error result is missing retryable flag.")
    if not isinstance(error.get("correlation_id"), str) or not error["correlation_id"]:
        return _invalid("safe_error", "E-3008", "UPS error result is missing correlation ID.")

    return _valid("safe_error")


def _has_money(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return isinstance(value.get("monetaryValue"), str) and isinstance(value.get("currencyCode"), str)


def _contains_unsafe_error_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _UNSAFE_ERROR_KEYS:
                return True
            if _contains_unsafe_error_key(nested):
                return True
    if isinstance(value, list):
        return any(_contains_unsafe_error_key(item) for item in value)
    return False


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
13 passed
```

- [ ] Commit the fixtures and validators.

```bash
git add src/hosted/ups_boundary/fixtures.py src/hosted/ups_boundary/validators.py tests/hosted/ups_boundary/test_validators.py
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
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_capabilities=set(UpsBoundaryCapability),
        response_formats={"shipagent_v1"},
        checks=[
            UpsBoundaryCheck(
                name="boundary_contract",
                severity=UpsBoundarySeverity.OK,
                message="Hosted UPS boundary contract is ready.",
            )
        ],
    )


@pytest.mark.asyncio
async def test_readiness_ready_when_report_is_ready() -> None:
    adapter = AsyncMock()
    adapter.inspect_capabilities.return_value = _ready_report()

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "ready"
    assert readiness.production_ready is True
    assert readiness.report.ready is True


@pytest.mark.asyncio
async def test_readiness_not_ready_when_report_is_missing_requirements() -> None:
    adapter = AsyncMock()
    adapter.inspect_capabilities.return_value = UpsBoundaryCapabilityReport(
        missing_tools=["create_shipment"]
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "not_ready"
    assert readiness.production_ready is False


@pytest.mark.asyncio
async def test_readiness_degraded_when_report_has_warning_only() -> None:
    adapter = AsyncMock()
    adapter.inspect_capabilities.return_value = UpsBoundaryCapabilityReport(
        available_tools={
            "rate_shipment",
            "validate_address",
            "create_shipment",
            "shipagent_capabilities",
        },
        declared_capabilities=set(UpsBoundaryCapability),
        response_formats={"shipagent_v1"},
        checks=[
            UpsBoundaryCheck(
                name="boundary_contract",
                severity=UpsBoundarySeverity.OK,
                message="Hosted UPS boundary contract is ready.",
            ),
            UpsBoundaryCheck(
                name="fixture_age",
                severity=UpsBoundarySeverity.WARN,
                message="UPS MCP fixture set is older than the review window.",
            )
        ],
    )

    readiness = await check_ups_mcp_boundary_readiness(adapter)

    assert readiness.status == "degraded"
    assert readiness.production_ready is False
```

The `fixture_age` warning above is an example diagnostic shape only. Do not add
real fixture freshness, review-window, or provenance timestamp computation in
this boundary phase.

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

`degraded` is a diagnostic status only. It may appear in local development,
CI reports, and pre-production review, but hosted production startup must treat
only `status == "ready"` as production-ready.
This implementation does not compute real review freshness. Later provider
review automation may add `WARN` checks such as `fixture_age`, and those warnings
will produce `degraded`, which still fails hosted production startup.

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

This task must create the standalone integration contract file. The markdown
block below is the source content for that file, not a substitute for it. The
file is the discoverable handoff artifact for the sibling UPS MCP repository and
future readiness/review checks.

````markdown
# UPS MCP Hosted Contract

ShipAgent hosted marketplace runtime depends on an external UPS MCP server. That server lives in a separate repository. This document defines the contract ShipAgent validates before using that server in hosted production. The UPS MCP server is a private carrier integration boundary, not a model-planning layer or public marketplace app surface.

## Required Tools

The UPS MCP server must expose these MCP tools for hosted-v1:

- `rate_shipment`
- `validate_address`
- `create_shipment`
- `shipagent_capabilities`

`shipagent_capabilities` is read-only and returns metadata. It must not call UPS.

The existing UPS MCP server may keep raw UPS API payloads as the default response
format for local development and existing users. ShipAgent hosted production
requires an explicit hosted-normalized response mode. Recommended tool
parameters:

- `rate_shipment(..., response_format="raw")`
- `validate_address(..., response_format="raw")`
- `create_shipment(..., response_format="raw", idempotency_key="")`

When `response_format="shipagent_v1"`, the required tools return the normalized
shapes below. `create_shipment` must require a non-empty deterministic
`idempotency_key` when `response_format="shipagent_v1"`. When omitted,
`response_format` defaults to `"raw"` and existing raw UPS response behavior
remains unchanged.

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
    "idempotency_metadata_passthrough",
    "shipment_response_normalization",
    "international_charges",
    "safe_error_mapping",
    "mutating_retry_policy"
  ],
  "response_formats": ["raw", "shipagent_v1"]
}
```

ShipAgent can infer `rate_quote`, `rate_shop`, `address_validation`, and `create_shipment` from tool presence, but hosted production still requires the declaration because the remaining guarantees are behavioral. ShipAgent also requires `shipagent_v1` in `response_formats` because hosted normalized mode is explicit and cannot be proven from capability names alone.

`contract_version` must be exactly `"hosted-v1"` for this release. Missing or
different contract versions fail ShipAgent hosted readiness closed.

`idempotency_metadata_passthrough` means the UPS MCP server accepts a deterministic
`idempotency_key`, preserves it in available UPS transaction/correlation metadata,
and returns it in the normalized response. It does not claim the UPS API provides
true idempotent create semantics. If true carrier-level idempotent shipment
creation is proven, the server may additionally declare `carrier_idempotent_create`.
This boundary phase validates only that the normalized response echoes a
non-empty `idempotencyKey`; later hosted worker/execution code validates the
exact `hosted_job_id:preview_row_id:row_checksum` format and row-state match.

`international_charges` means the UPS MCP server can return normalized
international charge/customs-related shapes. It does not enable all
international lanes for ShipAgent hosted production. ShipAgent enables only
explicitly reviewed origin/destination lane fixtures in later hosted workflow
phases, and hosted readiness fails closed for any unreviewed lane.

## Behavioral Guarantees

- `rate_shipment` supports UPS `requestoption="Rate"` for default purchasable previews.
- `rate_shipment` supports UPS `requestoption="Shop"` for explicit rate comparison.
- `validate_address` returns normalized statuses in `response_format="shipagent_v1"`: `valid`, `corrected`, `ambiguous`, `invalid`, `unsupported`, or `unknown`.
- `create_shipment` is mutating and must not be retried by generic MCP retry loops after the UPS boundary is crossed.
- `create_shipment` requires a deterministic `idempotency_key` from ShipAgent hosted workers when `response_format="shipagent_v1"` and preserves it through UPS transaction/correlation metadata where the UPS API supports it.
- Shipment responses are normalized before returning to ShipAgent when `response_format="shipagent_v1"` is requested.
- International shipping is supported only for configured, review-tested lanes in ShipAgent hosted production. Capability declaration alone never enables a hosted international lane.
- Domain failures in `response_format="shipagent_v1"` are returned as hosted-safe error envelopes. Raw UPS XML/JSON responses, exception traces, local paths, credentials, request payloads, and raw `details` must not cross this boundary.

## Normalized Response Requirements

Success response validators are minimum-shape validators. They allow additional
normalized metadata such as service descriptions, negotiated-rate flags,
warnings, transit estimates, correction notes, or charge breakdowns. Later public
result DTOs must still strip any hosted-unsafe fields before transcript/widget
output.

In `response_format="shipagent_v1"`, rate quote responses must include:

- `success: true`
- `totalCharges.monetaryValue`
- `totalCharges.currencyCode`

In `response_format="shipagent_v1"`, rate shop responses must include:

- `success: true`
- non-empty `ratedShipments`
- each option has `serviceCode`
- each option has `totalCharges.monetaryValue`
- each option has `totalCharges.currencyCode`

In `response_format="shipagent_v1"`, address validation responses must include:

- `status`
- optional `candidates` array with normalized candidate data

In `response_format="shipagent_v1"`, shipment creation responses must include:

- `success: true`
- `idempotencyKey`
- `shipmentIdentificationNumber`
- non-empty `trackingNumbers`
- `totalCharges.monetaryValue`
- `totalCharges.currencyCode`
- non-empty `labelData`
- each label has `format`
- each label has `encoding: "base64"`
- each label has `contentBase64`

The boundary validator treats `idempotencyKey` as shape-only: it must be a
non-empty string. It must not validate the hosted key format because this package
does not own hosted job IDs, preview row IDs, row checksums, or execution state.

`contentBase64` is internal carrier-boundary data for ShipAgent hosted workers
only. ShipAgent persists it to tenant-scoped object storage and strips it before
any public MCP `structuredContent`, widget payload, job status, label link, or
audit summary response.

This boundary phase validates only the label response shape:

- `labelData` is non-empty
- each label has `format`
- each label has `encoding: "base64"`
- each label has non-empty string `contentBase64`

Hosted worker/artifact phases own byte-level artifact safety:

- base64 decoding
- size limits
- content type sniffing
- label PDF/image validation
- malware scanning
- tenant-scoped object storage
- signed-link publication

In `response_format="shipagent_v1"`, domain failure responses must include:

- `success: false`
- `error.code`
- `error.category`
- `error.message`
- `error.retryable`
- `error.correlation_id`

Allowed error categories are:

- `auth`
- `rate_limit`
- `validation`
- `service_unavailable`
- `address`
- `customs`
- `transport`
- `unknown`

The error envelope must contain only those five safe `error` keys. It must not
include raw `details`, `raw`, `raw_response`, `request`, `request_body`,
`payload`, `stack`, `stack_trace`, `traceback`, `local_path`, `path`,
`credentials`, `client_secret`, or `access_token` keys.
Unlike success responses, safe-error envelopes are closed because they are
public-safety sensitive.

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

For this boundary phase, ShipAgent implements only
`HostedUpsBoundaryAdapter.inspect_capabilities()`, the `UpsBoundaryClient`
protocol, hosted-v1 validators, hosted-v1 fixtures, and the readiness evaluator.
Later hosted worker phases own operation methods that call UPS MCP tools with
`response_format="shipagent_v1"`, validate success or safe-error envelopes
before consuming results, persist label artifacts, and strip internal
`labelData.contentBase64` before any public result.

The hosted worker path is deterministic ShipAgent code, not a second internal
LLM. User-facing model providers call public ShipAgent workflow tools; ShipAgent
then validates persisted server-side state and calls internal adapters.

The UPS MCP server owns:

- UPS API request execution
- UPS response normalization
- UPS-specific error normalization
- UPS API version compatibility
- UPS lane/service capability implementation

## Local Runtime

Desktop/local ShipAgent flows may continue using the Angular/Tauri shell,
FastAPI sidecar, local conversation runtime, local model-provider configuration,
environment fallback, and local credential resolution. Hosted marketplace
readiness must use this contract and fail closed when the external UPS MCP
server does not satisfy it. `degraded` readiness is diagnostic only; hosted
production startup must require `status == "ready"` and fail closed for both
`not_ready` and `degraded`.
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
30 passed
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
from src.hosted.ups_boundary.fixtures import HOSTED_V1_SAFE_ERROR
from src.hosted.ups_boundary.readiness import check_ups_mcp_boundary_readiness
from src.hosted.ups_boundary.validators import validate_create_shipment_result


def test_boundary_package_imports_public_entrypoints() -> None:
    assert HostedUpsBoundaryAdapter is not None
    assert evaluate_boundary_contract is not None
    assert HOSTED_V1_SAFE_ERROR["success"] is False
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
- `HostedUpsBoundaryAdapter` exposes readiness introspection only; it does not
  call UPS operation tools in this phase.
- No provider adapter owns UPS shipping behavior.
- No UPS boundary code imports model-provider runtime modules or `claude_agent_sdk`.
- No changes in this plan add or remove model-provider dependencies.
- Boundary response validators return sanitized error codes/messages only.
- `degraded` UPS boundary readiness is not accepted for hosted production
  startup.
- The external UPS MCP contract is documented in `docs/integrations/ups-mcp-hosted-contract.md`.

- [ ] Confirm no registry files or generated provider artifact files were
  modified.

```bash
git status --short src/registry generated/provider_artifacts
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
- `HostedUpsBoundaryAdapter` has no hosted operation methods in this phase.
- Normalized UPS rate, shop, address validation, shipment creation, and
  safe-error response validators are covered by positive and negative fixtures.
- Hosted-v1 success and safe-error fixtures are importable from
  `src.hosted.ups_boundary.fixtures`.
- The contract document states that `international_charges` does not enable
  hosted international lanes without explicit reviewed fixtures.
- This phase does not add hosted international lane fixtures. Those fixtures are
  deferred to the hosted lane-policy, provider review, and UPS MCP follow-up
  phases, where each hosted-enabled lane gets reviewed fixture coverage.
- Readiness warning/degraded shape is covered with a static diagnostic example;
  real fixture freshness/review-age computation is deferred to provider review
  automation.
- `check_ups_mcp_boundary_readiness()` returns `ready`, `degraded`, or `not_ready` from a capability report, and only `ready` is `production_ready`.
- `docs/integrations/ups-mcp-hosted-contract.md` exists as a standalone
  integration contract document and documents the required external UPS MCP
  server contract, not only as embedded content in this implementation plan.
- Tests under `tests/hosted/ups_boundary` pass.
- Touched service tests for MCP introspection and UPS hosted capabilities pass.
- Ruff check passes on touched Python paths.
- No `src/registry/` files, public hosted tool projections, or generated
  provider artifact files are changed by this plan.

## Notes For The External UPS MCP Repository

After this ShipAgent-side boundary lands, the UPS MCP repository needs matching work:

- Add a read-only `shipagent_capabilities` tool.
- Return the hosted-v1 capability payload exactly as documented.
- Preserve raw UPS response defaults for existing clients unless a breaking
  change is explicitly approved.
- Add explicit `response_format="shipagent_v1"` support for hosted-normalized
  rate, address validation, and shipment creation responses.
- Ensure `rate_shipment` supports both `Rate` and `Shop` request options.
- Ensure `validate_address` returns normalized statuses compatible with ShipAgent validators.
- Ensure `create_shipment` requires deterministic `idempotency_key` input in
  `response_format="shipagent_v1"`, returns it as `idempotencyKey`, declares
  `idempotency_metadata_passthrough`, and never participates in generic retry
  loops after the UPS API boundary is crossed.
- Do not require the UPS MCP server or ShipAgent boundary validator to parse the
  hosted idempotency key format; exact format validation belongs to the later
  hosted worker/execution phase.
- Declare `carrier_idempotent_create` only if true UPS-side idempotent shipment
  creation semantics are proven.
- Keep raw UPS responses, stack traces, credentials, local paths, and request payloads out of MCP-visible results.

Those changes belong in the UPS MCP repository, not this one.
