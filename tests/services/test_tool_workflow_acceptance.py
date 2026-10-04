"""Acceptance: read-only tool workflows behave identically on every provider.

Each scenario is one provider-neutral script (``tests/services/provider_scenarios``)
rendered onto the scripted fake and onto the real Anthropic, OpenAI and Gemini
adapters over mocked HTTP transports. They all run through
``conversation_handler.process_message`` with the *real* catalog, policy gate,
dispatcher and workflow handlers; only the UPS gateway is replaced by a
deterministic one. Positive scenarios assert the gateway was actually reached,
so an unregistered or unreachable tool cannot pass vacuously. Denial scenarios
register a spy for the dangerous tool, so they fail if the guard stops guarding.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.services.conversation_acceptance import Observation, run_scenario
from tests.services.provider_scenarios import (
    FRAGMENTING_PROVIDERS,
    ID_PROVIDERS,
    PROVIDERS,
    SYNTHETIC_KEY,
    Call,
    Reason,
    Rendered,
    Say,
    build_provider,
    wire_tool_results,
)

_CANARY = "CANARY-ACCT-0042-jane@example.com"
_RATE_REQUEST = {
    "RateRequest": {"Shipment": {"Service": {"Code": "03"}}, "note": "ground"}
}
_SHOP_REQUEST = {"RateRequest": {"Shipment": {"Service": {"Code": "02"}}}}
_ADDRESS = {
    "addressLine1": "1 Main St",
    "city": "Austin",
    "stateProvinceCode": "TX",
    "postalCode": "78701",
    "countryCode": "US",
}


class DeterministicUPSGateway:
    """Stands in for the UPS MCP gateway; records every call, performs none."""

    def __init__(self) -> None:
        self.rate_calls: list[dict[str, Any]] = []
        self.address_calls: list[dict[str, Any]] = []

    async def get_rate(
        self, request_body: dict[str, Any], requestoption: str = "Rate"
    ) -> dict[str, Any]:
        self.rate_calls.append(
            {"request_body": request_body, "requestoption": requestoption}
        )
        return {
            "success": True,
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
            # Raw carrier fields the model must never see.
            "shipperAccountNumber": _CANARY,
            "rawResponse": {"labelImage": _CANARY},
        }

    async def validate_address(self, **kwargs: Any) -> dict[str, Any]:
        self.address_calls.append(kwargs)
        return {"status": "valid", "candidates": [], "accountToken": _CANARY}


@pytest.fixture(autouse=True)
def _quiet_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HIDE_TRANSIENT_CHAT", "false")
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")


async def _run(
    kind: str,
    turns: list[list[Any]],
    gateway: DeterministicUPSGateway | None = None,
    **kwargs: Any,
) -> tuple[Observation, Rendered]:
    rendered = build_provider(kind, turns)
    obs = await run_scenario(
        script=[], provider=rendered.provider, ups_gateway=gateway, **kwargs
    )
    return obs, rendered


def _results(kind: str, rendered: Rendered, obs: Observation) -> list[dict[str, Any]]:
    """Tool results the provider received on its final request, in order."""
    if kind == "scripted":
        return [
            {"key": r["call_id"], "content": r["content"], "is_error": r["is_error"]}
            for r in obs.tool_results_seen_by_provider()
        ]
    return wire_tool_results(kind, rendered.requests[-1])


def _result_key(kind: str, call_id: str, tool_name: str) -> str:
    return tool_name if kind == "gemini" else call_id


def _visible_events(obs: Observation) -> list[str]:
    return [n for n in obs.event_names() if n != "agent_message_delta"]


def _assert_no_leak(obs: Observation, rendered: Rendered) -> None:
    visible = obs.everything_externally_visible() + json.dumps(rendered.requests)
    assert _CANARY not in visible
    assert SYNTHETIC_KEY not in obs.everything_externally_visible()


# ---- the full read-only flow -------------------------------------------------


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_rate_lookup_runs_through_real_handler_and_gateway_to_final_answer(
    kind: str,
) -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        kind,
        [
            [
                Call(
                    "call_rate",
                    "rate_shipment",
                    {"request_body": _RATE_REQUEST, "requestoption": "Rate"},
                )
            ],
            [Say("Ground is $12.34.")],
        ],
        gateway,
    )

    assert gateway.rate_calls == [
        {"request_body": _RATE_REQUEST, "requestoption": "Rate"}
    ]
    assert obs.ups_gateway_acquisitions == 1
    assert _visible_events(obs) == ["tool_call", "agent_message"]
    tool_call = obs.events[0]["data"]
    assert tool_call["tool_name"] == "rate_shipment"
    assert tool_call["tool_input"]["request_body"] == _RATE_REQUEST
    if kind in ID_PROVIDERS:
        assert tool_call["tool_use_id"] == "call_rate"
    assert obs.persisted_messages == [("acceptance", "Ground is $12.34.")]

    [result] = _results(kind, rendered, obs)
    assert result["key"] == _result_key(kind, "call_rate", "rate_shipment")
    assert "12.34" in result["content"]
    assert not result.get("is_error")
    _assert_no_leak(obs, rendered)


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_multiple_calls_dispatch_in_order_and_results_keep_that_order(
    kind: str,
) -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        kind,
        [
            [
                Call("c1", "rate_shipment", {"request_body": _RATE_REQUEST}),
                Call("c2", "validate_address", _ADDRESS),
                Call(
                    "c3",
                    "rate_shipment",
                    {"request_body": _SHOP_REQUEST, "requestoption": "Shop"},
                ),
            ],
            [Say("Done.")],
        ],
        gateway,
    )

    assert [c["request_body"] for c in gateway.rate_calls] == [
        _RATE_REQUEST,
        _SHOP_REQUEST,
    ]
    assert [c["requestoption"] for c in gateway.rate_calls] == ["Rate", "Shop"]
    assert len(gateway.address_calls) == 1
    assert gateway.address_calls[0]["postalCode"] == "78701"
    assert [
        e["data"]["tool_name"] for e in obs.events if e["event"] == "tool_call"
    ] == [
        "rate_shipment",
        "validate_address",
        "rate_shipment",
    ]
    assert [r["key"] for r in _results(kind, rendered, obs)] == [
        _result_key(kind, "c1", "rate_shipment"),
        _result_key(kind, "c2", "validate_address"),
        _result_key(kind, "c3", "rate_shipment"),
    ]
    assert obs.persisted_messages == [("acceptance", "Done.")]
    _assert_no_leak(obs, rendered)


@pytest.mark.parametrize("kind", FRAGMENTING_PROVIDERS)
async def test_fragmented_arguments_dispatch_once_with_the_complete_input(
    kind: str,
) -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        kind,
        [
            [
                Call(
                    "frag_1",
                    "rate_shipment",
                    {"request_body": _RATE_REQUEST},
                    fragment_size=4,
                )
            ],
            [Say("ok")],
        ],
        gateway,
    )

    assert gateway.rate_calls == [
        {"request_body": _RATE_REQUEST, "requestoption": "Rate"}
    ]
    assert len([e for e in obs.events if e["event"] == "tool_call"]) == 1
    [result] = _results(kind, rendered, obs)
    assert result["key"] == "frag_1"


# ---- invalid input is stopped before any effect -------------------------------


@pytest.mark.parametrize("raw", ['{"request_body": {"Rate', "[1, 2]", '"text"'])
@pytest.mark.parametrize("kind", FRAGMENTING_PROVIDERS)
async def test_malformed_arguments_are_rejected_before_any_handler_runs(
    kind: str, raw: str
) -> None:
    gateway = DeterministicUPSGateway()
    spied: list[dict[str, Any]] = []

    async def spy(args: dict[str, Any], _bridge: Any) -> dict[str, Any]:
        spied.append(args)
        return {"isError": False, "content": [{"type": "text", "text": "{}"}]}

    obs, rendered = await _run(
        kind,
        [
            [
                # A complete, valid call earlier in the same message must not
                # slip through when a later call in it is unusable.
                Call("good", "rate_shipment", {"request_body": _RATE_REQUEST}),
                # {} would be a valid input for this tool: only the malformed
                # text distinguishes "no arguments" from "unusable arguments".
                Call("bad", "get_platform_status", raw),
            ],
            [Say("should never be requested")],
        ],
        gateway,
        spy_handlers={"get_platform_status": spy},
    )

    assert spied == []
    assert obs.handler_calls == {}
    assert gateway.rate_calls == []
    assert obs.ups_gateway_acquisitions == 0
    assert obs.event_names()[-1] == "error"
    assert "tool_call" not in obs.event_names()
    assert obs.persisted_messages == []
    assert len(rendered.requests) == 1  # no continuation, no silent retry


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_missing_required_input_is_refused_by_the_handler_before_the_gateway(
    kind: str,
) -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        kind,
        [[Call("c1", "rate_shipment", {})], [Say("I need the shipment details.")]],
        gateway,
    )

    assert gateway.rate_calls == []
    assert obs.ups_gateway_acquisitions == 0
    [result] = _results(kind, rendered, obs)
    assert "rate_shipment failed." in result["content"]
    assert obs.persisted_messages == [("acceptance", "I need the shipment details.")]


@pytest.mark.parametrize("kind", PROVIDERS)
async def test_unknown_tool_is_refused_without_effects(kind: str) -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        kind,
        [[Call("c1", "teleport_package", {"to": _CANARY})], [Say("Not possible.")]],
        gateway,
    )

    assert obs.handler_calls == {}
    assert gateway.rate_calls == [] and gateway.address_calls == []
    assert obs.ups_gateway_acquisitions == 0
    assert obs.data_gateway_acquisitions == 0
    [result] = _results(kind, rendered, obs)
    assert "not available" in result["content"]
    assert obs.persisted_messages == [("acceptance", "Not possible.")]


async def _must_not_run(_args: dict[str, Any], _bridge: Any) -> Any:
    raise AssertionError("denied tool handler must not run")


@pytest.mark.parametrize(
    "raw_tool", ["mcp__ups__create_shipment", "mcp__ups__rate_shipment"]
)
@pytest.mark.parametrize("kind", PROVIDERS)
async def test_raw_carrier_call_is_denied_even_when_its_handler_is_reachable(
    kind: str, raw_tool: str
) -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        kind,
        [[Call("c1", raw_tool, {"Shipment": {"Name": _CANARY}})], [Say("Denied.")]],
        gateway,
        exposed_dangerous_tools={raw_tool: _must_not_run},
    )

    assert obs.handler_calls == {}
    assert gateway.rate_calls == []
    assert obs.ups_gateway_acquisitions == 0
    [result] = _results(kind, rendered, obs)
    assert result["content"] != ""
    assert _CANARY not in result["content"]
    assert obs.persisted_messages == [("acceptance", "Denied.")]


# ---- duplicate completed call ids ---------------------------------------------


@pytest.mark.parametrize("kind", ID_PROVIDERS)
async def test_duplicate_call_id_in_one_message_executes_once(kind: str) -> None:
    gateway = DeterministicUPSGateway()
    call = Call("dup", "rate_shipment", {"request_body": _RATE_REQUEST})

    obs, rendered = await _run(kind, [[call, call], [Say("Once.")]], gateway)

    assert len(gateway.rate_calls) == 1
    assert len([e for e in obs.events if e["event"] == "tool_call"]) == 1
    assert [r["key"] for r in _results(kind, rendered, obs)] == ["dup"]
    assert obs.persisted_messages == [("acceptance", "Once.")]


@pytest.mark.parametrize("kind", ID_PROVIDERS)
async def test_completed_call_id_replayed_in_a_later_turn_does_not_run_again(
    kind: str,
) -> None:
    gateway = DeterministicUPSGateway()
    call = Call("dup", "rate_shipment", {"request_body": _RATE_REQUEST})

    obs, rendered = await _run(kind, [[call], [call]], gateway)

    assert len(gateway.rate_calls) == 1
    assert len([e for e in obs.events if e["event"] == "tool_call"]) == 1
    assert obs.ups_gateway_acquisitions == 1
    if kind != "scripted":
        assert len(rendered.requests) == 2  # replay ends the turn; no third request


# ---- provider-private continuation stays inside each adapter -------------------


async def test_openai_reasoning_and_function_items_round_trip_in_order() -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        "openai",
        [
            [
                Reason("rs_PRIVATE_1"),
                Call("call_rate", "rate_shipment", {"request_body": _RATE_REQUEST}),
            ],
            [Say("Done.")],
        ],
        gateway,
    )

    items = rendered.requests[1]["input"]
    kinds = [item.get("type") or item.get("role") for item in items]
    assert kinds == ["user", "reasoning", "function_call", "function_call_output"]
    assert items[1]["id"] == "rs_PRIVATE_1"
    assert items[2]["call_id"] == items[3]["call_id"] == "call_rate"
    assert items[2]["id"] == "fc_call_rate"
    assert json.loads(items[2]["arguments"]) == {"request_body": _RATE_REQUEST}
    assert "rs_PRIVATE_1" not in obs.everything_externally_visible()
    assert len(gateway.rate_calls) == 1


async def test_anthropic_tool_use_and_result_pair_by_id_after_text() -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        "anthropic",
        [
            [
                Say("Checking."),
                Call("toolu_1", "rate_shipment", {"request_body": _RATE_REQUEST}),
                Call("toolu_2", "validate_address", _ADDRESS),
            ],
            [Say("Done.")],
        ],
        gateway,
    )

    *_, assistant, results = rendered.requests[1]["messages"]
    assert [b["type"] for b in assistant["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["id"] for b in assistant["content"][1:]] == ["toolu_1", "toolu_2"]
    assert assistant["content"][1]["input"] == {"request_body": _RATE_REQUEST}
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["toolu_1", "toolu_2"]
    assert obs.persisted_messages == [
        ("acceptance", "Checking."),
        ("acceptance", "Done."),
    ]


async def test_gemini_function_response_follows_function_call_by_name() -> None:
    gateway = DeterministicUPSGateway()

    obs, rendered = await _run(
        "gemini",
        [
            [Call("ignored", "rate_shipment", {"request_body": _RATE_REQUEST})],
            [Say("Done.")],
        ],
        gateway,
    )

    roles_and_parts = [
        (c.get("role"), [next(iter(p)) for p in c["parts"]])
        for c in rendered.requests[1]["contents"]
    ]
    assert roles_and_parts[-2:] == [
        ("model", ["functionCall"]),
        ("tool", ["functionResponse"]),
    ]
    call_part = rendered.requests[1]["contents"][-2]["parts"][0]["functionCall"]
    assert call_part == {
        "name": "rate_shipment",
        "args": {"request_body": _RATE_REQUEST},
    }
    response = rendered.requests[1]["contents"][-1]["parts"][0]["functionResponse"]
    assert response["name"] == "rate_shipment"
    assert len(gateway.rate_calls) == 1
