"""Cancelling accepted model work is scoped and remains dormant by default."""

import pytest

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_targets import TargetToolRequest
from src.hosted_mcp.execution_target_handlers import (
    build_execution_target_tool_handlers,
)
from src.hosted_mcp.server import build_server
from src.provider_adapters.mcp_projection import to_mcp_tool_descriptor
from src.registry.catalog import public_tools
from src.registry.models import SideEffectClass
from src.services.agent_runs.execution_target import AgentRunExecutionTarget


def test_cancel_contract_is_dormant_stateful_scoped_and_idempotent():
    contracts = {tool.name: tool for tool in public_tools()}
    assert "cancel_shipagent_run" in contracts
    cancel = contracts["cancel_shipagent_run"]
    assert cancel.auth_scopes == ["shipagent.preview"]
    assert cancel.side_effect == SideEffectClass.agent_work
    assert cancel.rate_limit_class == "write"
    assert cancel.call_repetition == "idempotent"
    assert cancel.hosted_readiness == "not_ready"
    assert cancel.provider_export_enabled is False
    assert cancel.execution_target_required is True
    assert cancel.input_schema["required"] == ["run_reference"]
    assert cancel.input_schema["additionalProperties"] is False
    for name in ("submit_shipagent_task", "read_shipagent_run", "cancel_shipagent_run"):
        result = contracts[name].output_schema["properties"]
        assert "cancelled" in result["state"]["enum"]
        assert "cancelled" in result["outcome"]["enum"]


async def test_default_server_does_not_export_cancel():
    assert "cancel_shipagent_run" not in await build_server().get_tools()


@pytest.mark.parametrize(
    ("name", "external"),
    [
        ("submit_shipagent_task", True),
        ("cancel_shipagent_run", True),
        ("read_shipagent_run", False),
    ],
)
def test_agent_work_descriptors_disclose_possible_configured_provider_reach(
    name, external
):
    contract = next(tool for tool in public_tools() if tool.name == name)
    descriptor = to_mcp_tool_descriptor(contract)
    assert descriptor["annotations"]["openWorldHint"] is external
    assert descriptor["annotations"]["readOnlyHint"] is (name == "read_shipagent_run")


async def test_cancel_target_adapter_preserves_trusted_owner_and_run_reference():
    calls = []

    class Service:
        class store:
            account_id = "account-a"

        def cancel(self, **kwargs):
            calls.append(kwargs)
            return {"state": "cancelled"}

    target = AgentRunExecutionTarget(Service())
    handlers = build_execution_target_tool_handlers(target, include_agent_runs=True)
    assert "cancel_shipagent_run" in handlers
    context = AuthorizationContext(
        account_id="account-a",
        provider_connection_id="connection-a",
        provider_surface="chatgpt",
        subject="synthetic",
        client_id="client-a",
        scopes=frozenset({"shipagent.preview"}),
    )
    result = await handlers["cancel_shipagent_run"](
        context, {"run_reference": "sa_agent_run_" + "a" * 32}
    )
    assert result == {"state": "cancelled"}
    assert calls == [
        {
            "connection_id": "connection-a",
            "run_reference": "sa_agent_run_" + "a" * 32,
        }
    ]
    with pytest.raises(PermissionError):
        await target.invoke(
            TargetToolRequest(
                account_id="account-b",
                provider_connection_id="connection-a",
                provider_surface="chatgpt",
                tool_name="cancel_shipagent_run",
                arguments={"run_reference": "sa_agent_run_" + "a" * 32},
                correlation_id="cancel",
            )
        )
    assert len(calls) == 1
