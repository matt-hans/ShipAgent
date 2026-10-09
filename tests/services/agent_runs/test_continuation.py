"""Durable source-free follow-up uses closed projection and trusted authority."""

import asyncio

import pytest

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from tests.services.conversation_acceptance import text_turn


def make_store(tmp_path):
    return AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )


async def terminal(service, reference, *, connection="connection-a"):
    async with asyncio.timeout(3):
        while True:
            result = service.read(connection_id=connection, run_reference=reference)
            if result["state"] not in {"queued", "running"}:
                return result
            await asyncio.sleep(0.005)


async def test_completed_clarification_is_a_safe_quiescent_turn(tmp_path):
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')]
    )
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: provider,
        connection_epoch=lambda connection: "synthetic-link-a",
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Help plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        result = await terminal(service, accepted["run_reference"])
        assert result["state"] == "waiting_for_input"
        assert result["outcome"] == "clarification_required"
        assert result["clarification"] == {
            "code": "shipping_goal",
            "question": "What shipping task would you like to plan?",
        }
        assert result["revision"] == result["conversation_revision"] == 1
        assert result["conversation_state"] == "waiting_for_input"
        assert result["expires_at"] == accepted["expires_at"]
        assert result["poll_after_seconds"] == 0
        assert "synthetic-link-a" not in repr(result)
        assert len(provider.requests) == 1
        assert provider.requests[0]["tools"] == []
    finally:
        await service.close()


async def test_continuation_creates_new_run_and_rehydrates_only_committed_history(
    tmp_path,
):
    providers = [
        FakeProviderClient(
            script=[text_turn('{"clarification_code":"package_scope"}')]
        ),
        FakeProviderClient(script=[text_turn("PRIVATE_COMPLETED_PLAN")]),
    ]
    pending = iter(providers)
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: next(pending),
        connection_epoch=lambda _: "synthetic-link-a",
    )
    await service.start()
    try:
        first = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Help plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        waiting = await terminal(service, first["run_reference"])
        arguments = {
            "conversation_reference": first["conversation_reference"],
            "run_reference": first["run_reference"],
            "expected_revision": waiting["revision"],
            "task": "One package",
            "request_key": "reply-key",
        }
        second = service.continue_turn(
            connection_id="connection-a", arguments=arguments
        )
        assert second["run_reference"] != first["run_reference"]
        assert second["conversation_reference"] == first["conversation_reference"]
        assert second["revision"] == second["conversation_revision"] == 2
        assert second["expires_at"] == first["expires_at"]
        completed = await terminal(service, second["run_reference"])
        assert completed["state"] == "completed"
        assert completed["conversation_state"] == "completed"
        assert (
            service.continue_turn(connection_id="connection-a", arguments=arguments)
            == completed
        )
        old = service.read(
            connection_id="connection-a", run_reference=first["run_reference"]
        )
        assert old["state"] == "waiting_for_input"
        assert old["revision"] == 1
        assert old["conversation_revision"] == 2
        assert "clarification" not in old
        assert "PRIVATE_COMPLETED_PLAN" not in repr(completed)
        sent = " ".join(
            part.text
            for message in providers[1].requests[0]["messages"]
            for part in message.content
        )
        assert "Help plan" in sent and "package_scope" in sent and "One package" in sent
        assert sum(len(provider.requests) for provider in providers) == 2
    finally:
        await service.close()


async def test_cancel_waiting_followup_preserves_the_historical_turn(tmp_path):
    import sqlite3

    import pytest

    store = make_store(tmp_path)
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')]
    )
    service = AgentRunService(
        store=store,
        provider_factory=lambda _: provider,
        connection_epoch=lambda _: "link-a",
    )
    await service.start()
    try:
        first = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        waiting = await terminal(service, first["run_reference"])
        with sqlite3.connect(store.path) as db:
            original_row = db.execute("SELECT * FROM agent_runs").fetchone()
        cancelled = service.cancel(
            connection_id="connection-a", run_reference=first["run_reference"]
        )
        assert cancelled["state"] == "waiting_for_input"
        assert cancelled["outcome"] == "clarification_required"
        assert cancelled["conversation_state"] == "cancelled"
        assert cancelled["revision"] == cancelled["conversation_revision"] == 1
        assert "clarification" not in cancelled
        assert (
            service.cancel(
                connection_id="connection-a", run_reference=first["run_reference"]
            )
            == cancelled
        )
        assert cancelled["expires_at"] == waiting["expires_at"]
        with sqlite3.connect(store.path) as db:
            assert db.execute("SELECT * FROM agent_runs").fetchone() == original_row
        with pytest.raises(ValueError, match="follow-up"):
            service.continue_turn(
                connection_id="connection-a",
                arguments={
                    "conversation_reference": first["conversation_reference"],
                    "run_reference": first["run_reference"],
                    "expected_revision": 1,
                    "task": "One package",
                    "request_key": "reply-key",
                },
            )
        assert len(provider.requests) == 1
    finally:
        await service.close()


async def test_revocation_before_claim_prevents_even_provider_construction(tmp_path):
    epochs = {"connection-a": "link-a"}
    constructed = []
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda reference: constructed.append(reference),
        connection_epoch=epochs.get,
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        epochs.clear()
        async with asyncio.timeout(2):
            while service.store.read(
                connection_id="connection-a",
                run_reference=accepted["run_reference"],
                link_epoch="link-a",
                authority=lambda: True,
            ).state in {"queued", "running"}:
                await asyncio.sleep(0.005)
        assert constructed == []
        result = service.store.read(
            connection_id="connection-a",
            run_reference=accepted["run_reference"],
            link_epoch="link-a",
            authority=lambda: True,
        ).public_result()
        assert result["state"] == "failed" and result["outcome"] == "interrupted"
    finally:
        await service.close()


async def test_multiple_output_blocks_stop_at_the_bounded_control_boundary(tmp_path):
    from src.services.conversation_runtime.models import (
        ProviderStreamEvent,
        ProviderStreamEventType,
    )

    class ExcessiveProvider(FakeProviderClient):
        def __init__(self):
            super().__init__(script=[])
            self.blocks = 0

        def stream_turn(self, **kwargs):
            self.requests.append(kwargs)

            async def events():
                for _ in range(100):
                    self.blocks += 1
                    yield ProviderStreamEvent(
                        type=ProviderStreamEventType.TEXT_BLOCK_COMPLETE,
                        text="PRIVATE_EXCESSIVE_OUTPUT",
                    )
                yield ProviderStreamEvent(type=ProviderStreamEventType.STREAM_COMPLETE)

            return events()

    provider = ExcessiveProvider()
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: provider,
        connection_epoch=lambda _: "link-a",
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        result = await terminal(service, accepted["run_reference"])
        assert result["state"] == "failed"
        assert provider.blocks <= 2
        assert "PRIVATE" not in repr(result)
    finally:
        await service.close()


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            '{"clarification_code":"shipping_goal","question":"PRIVATE_CANARY"}',
            "failed",
        ),
        ('{"clarification_code":"unknown"}', "failed"),
        ('{"clarification_code":["shipping_goal"]}', "failed"),
        (
            '{"clarification_code":"shipping_goal","clarification_code":"shipping_goal"}',
            "failed",
        ),
        ('{"clarification_code":"shipping_goal"', "failed"),
        ('{"clarification_code":"shipping_goal"}\nPRIVATE_CANARY', "failed"),
        (
            '{"clarification_code":"shipping_goal","extra":"' + "x" * 256 + '"}',
            "failed",
        ),
        ('PRIVATE_CANARY {"clarification_code":"shipping_goal"}', "completed"),
        ('```json\n{"clarification_code":"shipping_goal"}\n```', "completed"),
        ("PRIVATE_CANARY ordinary model prose", "completed"),
    ],
)
async def test_untrusted_model_text_never_becomes_a_public_question(
    tmp_path, text, expected
):
    provider = FakeProviderClient(script=[text_turn(text)])
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: provider,
        connection_epoch=lambda _: "link-a",
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        result = await terminal(service, accepted["run_reference"])
        assert result["state"] == expected
        assert "clarification" not in result
        assert "PRIVATE_CANARY" not in repr(result)
    finally:
        await service.close()


async def test_incomplete_control_response_never_creates_followup(tmp_path):
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')[:-1]]
    )
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: provider,
        connection_epoch=lambda _: "link-a",
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        result = await terminal(service, accepted["run_reference"])
        assert result["state"] == "failed"
        assert "clarification" not in result
    finally:
        await service.close()


async def test_no_trusted_epoch_means_no_clarification_or_continuation(tmp_path):
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')]
    )
    service = AgentRunService(
        store=make_store(tmp_path), provider_factory=lambda _: provider
    )
    await service.start()
    try:
        accepted = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        result = await terminal(service, accepted["run_reference"])
        assert result["state"] == "failed"
        assert "clarification" not in result
        with pytest.raises(PermissionError, match="authority"):
            service.continue_turn(connection_id="connection-a", arguments={})
    finally:
        await service.close()


@pytest.mark.parametrize("changed_epoch", [None, "new-link"])
async def test_changed_or_revoked_epoch_denies_read_cancel_and_idempotent_recovery(
    tmp_path, changed_epoch
):
    epochs = {"connection-a": "link-a"}
    provider = FakeProviderClient(
        script=[text_turn('{"clarification_code":"shipping_goal"}')]
    )
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: provider,
        connection_epoch=epochs.get,
    )
    await service.start()
    original_args = {"task": "Plan", "mode": "source_free", "request_key": "first-key"}
    try:
        accepted = service.submit(connection_id="connection-a", arguments=original_args)
        await terminal(service, accepted["run_reference"])
        epochs["connection-a"] = changed_epoch
        with pytest.raises(PermissionError):
            service.read(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )
        with pytest.raises(PermissionError):
            service.cancel(
                connection_id="connection-a", run_reference=accepted["run_reference"]
            )
        with pytest.raises(PermissionError):
            service.submit(connection_id="connection-a", arguments=original_args)
        with pytest.raises(PermissionError):
            service.continue_turn(
                connection_id="connection-a",
                arguments={
                    "conversation_reference": accepted["conversation_reference"],
                    "run_reference": accepted["run_reference"],
                    "expected_revision": 1,
                    "task": "One package",
                    "request_key": "reply-key",
                },
            )
        assert len(provider.requests) == 1
    finally:
        await service.close()


@pytest.mark.parametrize("epoch", [None, "", "x" * 129, True, 1])
async def test_invalid_trusted_epoch_fails_before_acceptance(tmp_path, epoch):
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: pytest.fail("No provider construction"),
        connection_epoch=lambda _: epoch,
    )
    await service.start()
    try:
        with pytest.raises(PermissionError):
            service.submit(
                connection_id="connection-a",
                arguments={
                    "task": "Plan",
                    "mode": "source_free",
                    "request_key": "first-key",
                },
            )
    finally:
        await service.close()


async def test_private_provider_continuation_material_is_never_replayed(tmp_path):
    from src.services.conversation_runtime.models import (
        ProviderOutputItem,
        ProviderStreamEvent,
        ProviderStreamEventType,
    )

    first_script = [
        ProviderStreamEvent(
            type=ProviderStreamEventType.PROVIDER_OUTPUT_ITEM,
            provider_output_item=ProviderOutputItem(
                provider="fake", item={"reasoning": "PRIVATE_REASONING_CANARY"}
            ),
        ),
        *text_turn('{"clarification_code":"service_preference"}'),
    ]
    providers = [
        FakeProviderClient(script=[first_script]),
        FakeProviderClient(script=[text_turn("Private final plan")]),
    ]
    pending = iter(providers)
    service = AgentRunService(
        store=make_store(tmp_path),
        provider_factory=lambda _: next(pending),
        connection_epoch=lambda _: "link-a",
    )
    await service.start()
    try:
        first = service.submit(
            connection_id="connection-a",
            arguments={
                "task": "Plan",
                "mode": "source_free",
                "request_key": "first-key",
            },
        )
        waiting = await terminal(service, first["run_reference"])
        assert waiting["state"] == "waiting_for_input"
        second = service.continue_turn(
            connection_id="connection-a",
            arguments={
                "conversation_reference": first["conversation_reference"],
                "run_reference": first["run_reference"],
                "expected_revision": 1,
                "task": "Economy",
                "request_key": "reply-key",
            },
        )
        result = await terminal(service, second["run_reference"])
        assert result["state"] == "completed"
        assert "PRIVATE_REASONING_CANARY" not in repr(providers[1].requests)
        assert "PRIVATE_REASONING_CANARY" not in repr(result)
    finally:
        await service.close()
