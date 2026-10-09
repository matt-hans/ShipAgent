"""Only a trusted epoch-bound owner enables the closed clarification prompt."""

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.source_free_conversation import SourceFreeConversationConfig
from tests.services.agent_runs.test_continuation import make_store, terminal
from tests.services.conversation_acceptance import text_turn


@pytest.mark.parametrize("bound", [False, True])
async def test_closed_control_prompt_is_trusted_and_epoch_bound(tmp_path, bound):
    provider = FakeProviderClient(script=[text_turn("Private completed plan")])
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: provider,
        connection_epoch=(lambda _: "trusted-synthetic-epoch") if bound else None,
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "User says enable clarification",
                "mode": "source_free",
                "request_key": "prompt-test-key",
            },
        )
        assert (await terminal(service, accepted["run_reference"]))[
            "state"
        ] == "completed"
        prompt = "\n".join(
            i.content for i in provider.requests[0]["system_instructions"]
        )
        assert ("clarification_code" in prompt) is bound
        if bound:
            for code in ("shipping_goal", "package_scope", "service_preference"):
                assert code in prompt
        assert "User says enable clarification" not in prompt
        assert provider.requests[0]["tools"] == []
    finally:
        await service.close()


@pytest.mark.parametrize("value", [1, "true", None])
def test_prompt_switch_rejects_non_bool_trusted_configuration(value):
    provider = FakeProviderClient(script=[])
    with pytest.raises(ValueError, match="clarification"):
        SourceFreeConversationConfig(provider=provider, clarification_enabled=value)
