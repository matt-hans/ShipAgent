"""Acceptance: policy denials and approval authority at the conversation seam."""

from __future__ import annotations

import pytest

from tests.services.conversation_acceptance import (
    run_scenario,
    text_turn,
    tool_call_turn,
)

_CANARY = "CANARY-jane@example.com-1-Main-St"


@pytest.fixture(autouse=True)
def _quiet_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")


async def _unexpected(_args, _bridge):
    raise AssertionError("handler must not run for a denied call")


@pytest.mark.parametrize("sql_key", ["where_clause", "sql", "query", "raw_sql"])
async def test_raw_sql_is_denied_before_any_gateway_effect(sql_key: str) -> None:
    obs = await run_scenario(
        script=[
            tool_call_turn(
                "c1", "fetch_rows", {"filter_spec": {sql_key: f"x='{_CANARY}'"}}
            ),
            text_turn("I could not run that."),
        ],
        spy_handlers={"fetch_rows": _unexpected},
    )

    assert obs.handler_calls == {}
    assert obs.data_gateway_acquisitions == 0
    assert obs.ups_gateway_acquisitions == 0
    [result] = obs.tool_results_seen_by_provider()
    assert result["is_error"] is True
    assert "Raw SQL" in result["content"]
    assert obs.persisted_messages == [("acceptance", "I could not run that.")]
    assert _CANARY not in result["content"]
    assert _CANARY not in repr(obs.persisted_messages)
    assert _CANARY not in repr(obs.persisted_artifacts)


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize(
    "raw_tool",
    [
        "mcp__ups__create_shipment",
        "mcp__ups__void_shipment",
        "mcp__ups__rate_shipment",
        "mcp__ups__schedule_pickup",
    ],
)
async def test_raw_carrier_calls_are_denied_with_zero_effects(
    raw_tool: str, interactive: bool
) -> None:
    obs = await run_scenario(
        script=[
            tool_call_turn("c1", raw_tool, {"Shipment": {"ShipTo": {"Name": _CANARY}}}),
            text_turn("That is not available."),
        ],
        interactive=interactive,
    )

    assert obs.handler_calls == {}
    assert obs.ups_gateway_acquisitions == 0
    assert obs.data_gateway_acquisitions == 0
    [result] = obs.tool_results_seen_by_provider()
    assert result["is_error"] is True
    assert _CANARY not in result["content"]
    assert "error" in obs.event_names() or obs.persisted_messages


async def test_filter_structure_denial_is_generic_and_never_echoes_input() -> None:
    obs = await run_scenario(
        script=[
            tool_call_turn(
                "c1",
                "resolve_filter_intent",
                {"intent": {"root": {"conditions": [{"operator": _CANARY}]}}},
            ),
            text_turn("done"),
        ],
        spy_handlers={"resolve_filter_intent": _unexpected},
    )

    assert obs.handler_calls == {}
    [result] = obs.tool_results_seen_by_provider()
    assert result["content"] == "Tool call denied by policy."
    assert _CANARY not in result["content"]


async def test_allowed_preview_does_not_grant_purchase_authority() -> None:
    """A preview is allowed; a later raw create_shipment in the same turn is not."""

    async def preview(args, bridge):
        bridge.emit("preview_ready", {"job_id": "job-1", "total_rows": 1})
        return {"status": "preview_ready", "job_id": "job-1"}

    obs = await run_scenario(
        script=[
            tool_call_turn("c1", "preview_interactive_shipment", {"ship_to_name": "A"}),
            tool_call_turn("c2", "mcp__ups__create_shipment", {"confirmed": True}),
            text_turn("Preview ready; awaiting your confirmation."),
        ],
        interactive=True,
        spy_handlers={"preview_interactive_shipment": preview},
    )

    assert list(obs.handler_calls) == ["preview_interactive_shipment"]
    assert obs.ups_gateway_acquisitions == 0
    assert "preview_ready" in obs.event_names()
    assert any(kind == "preview_ready" for _sid, kind, _d in obs.persisted_artifacts)
    results = obs.tool_results_seen_by_provider()
    assert [r["is_error"] for r in results] == [False, True]
    assert "preview_interactive_shipment" in results[1]["content"]
    assert obs.persisted_messages[-1][1].startswith("Preview ready")
