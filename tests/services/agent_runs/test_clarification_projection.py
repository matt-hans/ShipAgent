"""The control channel is one complete closed object, never parsed prose."""

import pytest

from src.services.agent_runs.clarification import clarification_code


@pytest.mark.parametrize(
    "text",
    [
        '{"clarification_code":"shipping_goal","clarification_code":"shipping_goal"}',
        '{"clarification_code":"package_scope","clarification_code":"shipping_goal"}',
    ],
)
def test_duplicate_json_keys_do_not_select_followup(text):
    with pytest.raises(ValueError):
        clarification_code([text])
