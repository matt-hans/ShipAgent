"""Legacy model-supplied confirmation flags/tokens never grant pickup authority."""

from unittest.mock import AsyncMock

import pytest

from src.orchestrator.agent.tools.pickup import schedule_pickup_tool


@pytest.mark.parametrize(
    "args",
    [
        {"confirmed": True},
        {"confirmation_token": "copied-preview-token"},
        {"confirmed": True, "confirmation_token": "eyJzaWduYXR1cmUiOiJsZWdhY3kifQ=="},
    ],
)
async def test_model_confirmation_cannot_execute_pickup(args, monkeypatch):
    gateway = AsyncMock()
    monkeypatch.setattr("src.orchestrator.agent.tools.pickup._get_ups_client", gateway)
    result = await schedule_pickup_tool(args)
    assert result["isError"] is True
    gateway.assert_not_awaited()
