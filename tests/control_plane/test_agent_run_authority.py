"""Current durable identity gates task input before an authority-aware transport."""

from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.control_plane.agent_run_authority import AgentRunAuthorityResolver
from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.execution_targets import TargetToolRequest
from src.control_plane.models import ProviderConnection
from src.control_plane.redis_keys import RedisKey
from src.control_plane.relay.protocol import (
    RelayVersionMetadata,
)
from src.control_plane.relay.registry import RelayDeviceRegistry
from tests.control_plane.relay.test_registry import KEY_SERVICE, PUBLIC_KEY, FakeRedis

VERSION = RelayVersionMetadata(
    shipagent_core_version="1.0.0",
    registry_contract_version="registry-v1",
    ups_boundary_contract_version="ups-v1",
    capabilities=[
        "submit_shipagent_task",
        "continue_shipagent_task",
        "read_shipagent_run",
        "cancel_shipagent_run",
    ],
)


async def setup_authority(db):
    clients = ProviderClientRegistry({"chatgpt-client": "chatgpt"})
    owner = await AuthorizationService(db, clients).resolve(
        subject="auth0|owner",
        client_id="chatgpt-client",
        scopes={"shipagent.preview", "shipagent.status"},
    )
    redis = FakeRedis()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    registry = RelayDeviceRegistry(redis, db_session_factory=factory)
    device = await registry.register_device(
        owner.account_id, "Synthetic headless", PUBLIC_KEY
    )
    challenge = await registry.create_challenge(owner.account_id, device.device_id)
    from src.control_plane.relay.protocol import build_handshake_claims

    claims = build_handshake_claims(
        device_id=device.device_id,
        account_id=owner.account_id,
        relay_session_id=challenge.relay_session_id,
        nonce=challenge.nonce,
        version=VERSION,
    )
    session = await registry.accept_handshake(KEY_SERVICE.sign_handshake_claims(claims))
    resolver = AgentRunAuthorityResolver(
        session_factory=factory,
        clients=clients,
        registry=registry,
        account_id=owner.account_id,
        execution_target_id=session.execution_target_id,
        required_version=VERSION,
    )
    request = TargetToolRequest(
        owner.account_id,
        owner.provider_connection_id,
        owner.provider_surface,
        "submit_shipagent_task",
        {"task": "PRIVATE_TASK_CANARY"},
        "synthetic",
    )
    return resolver, request, registry, redis, session


async def test_current_authority_survives_resolver_restart_but_not_connection_revocation(
    control_db,
):
    resolver, request, registry, redis, session = await setup_authority(control_db)
    first = await resolver.resolve(request)
    assert first.account_id == request.account_id
    assert first.provider_connection_id == request.provider_connection_id
    assert first.execution_target_id == session.execution_target_id
    assert "CANARY" not in repr(first)
    assert await resolver.resolve(request, expected=first) == first
    connection = await control_db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == request.provider_connection_id
        )
    )
    connection.status = "revoked"
    await control_db.commit()
    with pytest.raises(PermissionError, match="unavailable"):
        await resolver.resolve(request, expected=first)


async def test_relink_generation_invalidates_prior_authority_without_resurrecting_it(
    control_db,
):
    resolver, request, *_ = await setup_authority(control_db)
    first = await resolver.resolve(request)
    assert first.link_generation == 1
    connection = await control_db.get(
        ProviderConnection, request.provider_connection_id
    )
    connection.link_generation += 1
    await control_db.commit()
    with pytest.raises(PermissionError, match="unavailable"):
        await resolver.resolve(request, expected=first)
    fresh = await resolver.resolve(request)
    assert fresh.link_generation == 2
    assert fresh != first


@pytest.mark.parametrize(
    "change", ["account", "connection", "surface", "unsupported_tool"]
)
async def test_untrusted_identity_and_unadmitted_tools_fail_closed(control_db, change):
    resolver, request, *_ = await setup_authority(control_db)
    request = replace(
        request,
        **{
            "account": {"account_id": "other-account"},
            "connection": {"provider_connection_id": "other-connection"},
            "surface": {"provider_surface": "claude_ai"},
            "unsupported_tool": {"tool_name": "batch_execute"},
        }[change],
    )
    with pytest.raises(PermissionError, match="unavailable"):
        await resolver.resolve(request)


@pytest.mark.parametrize("change", ["offline", "version", "capability", "replacement"])
async def test_current_target_must_match_exact_qualified_profile(control_db, change):
    resolver, request, registry, redis, session = await setup_authority(control_db)
    first = await resolver.resolve(request)
    if change == "offline":
        await registry.disconnect_session(
            request.account_id, session.device_id, session.relay_session_id
        )
    else:
        heartbeat = await registry.get_active_heartbeat(request.account_id)
        if change == "version":
            heartbeat.version.registry_contract_version = "unknown-contract"
        elif change == "capability":
            heartbeat.version.capabilities = []
        else:
            heartbeat.execution_target_id = "replacement-target"
        await redis.set(
            RedisKey.relay_heartbeat(session.device_id), heartbeat.model_dump_json()
        )
    with pytest.raises(PermissionError, match="unavailable"):
        await resolver.resolve(request, expected=first)


async def test_lifecycle_transport_receives_trusted_binding_outside_arguments(
    control_db,
):
    from src.control_plane.execution_targets import RelayExecutionTarget
    from src.control_plane.relay.invocations import RelayInvocationBroker
    from src.control_plane.relay.protocol import (
        RelayInvocationEnvelope,
        RelayInvocationResultFrame,
    )

    resolver, request, registry, redis, session = await setup_authority(control_db)
    broker = RelayInvocationBroker()
    frames = []

    class Receiver:
        async def send_json(self, payload):
            frame = RelayInvocationEnvelope.model_validate(payload)
            frames.append(frame)
            await broker.accept_result(
                RelayInvocationResultFrame(
                    relay_session_id=frame.relay_session_id,
                    relay_invocation_id=frame.relay_invocation_id,
                    status="ok",
                    result={"synthetic": True},
                )
            )

        async def close(self, code=1000, reason=None):
            pass

    await broker.register(
        session.relay_session_id,
        Receiver(),
        account_id=request.account_id,
        device_id=session.device_id,
    )
    target = RelayExecutionTarget(registry, broker, agent_run_authority=resolver)
    assert await target.invoke(request) == {"synthetic": True}
    assert frames[0].agent_run_authority == await resolver.resolve(request)
    assert frames[0].arguments == {"task": "PRIVATE_TASK_CANARY"}
    connection = await control_db.get(
        ProviderConnection, request.provider_connection_id
    )
    connection.status = "revoked"
    await control_db.commit()
    with pytest.raises(PermissionError, match="unavailable"):
        await target.invoke(request)
    assert len(frames) == 1


async def test_legacy_broker_cannot_send_lifecycle_without_authority(control_db):
    from src.control_plane.relay.invocations import RelayInvocationBroker

    resolver, request, registry, redis, session = await setup_authority(control_db)
    broker = RelayInvocationBroker()
    with pytest.raises(PermissionError, match="unavailable"):
        await broker.invoke(
            relay_session_id=session.relay_session_id,
            tool_name="submit_shipagent_task",
            arguments=request.arguments,
            audit_correlation_id="synthetic",
            timeout_seconds=1,
        )


async def test_revocation_while_waiting_for_device_guard_prevents_transport(control_db):
    import asyncio

    from src.control_plane.relay.invocations import RelayInvocationBroker

    resolver, request, registry, redis, session = await setup_authority(control_db)
    binding = await resolver.resolve(request)
    broker = RelayInvocationBroker()
    sends = []

    class Receiver:
        async def send_json(self, payload):
            sends.append(payload)

        async def close(self, code=1000, reason=None):
            pass

    await broker.register(
        session.relay_session_id,
        Receiver(),
        account_id=request.account_id,
        device_id=session.device_id,
    )

    async def admit():
        await resolver.resolve(request, expected=binding)

    async with broker.session_operation_guard.hold(
        request.account_id, session.device_id
    ):
        pending = asyncio.create_task(
            broker.invoke(
                relay_session_id=session.relay_session_id,
                tool_name=request.tool_name,
                arguments=request.arguments,
                audit_correlation_id="synthetic",
                timeout_seconds=1,
                agent_run_authority=binding,
                admit=admit,
            )
        )
        await asyncio.sleep(0)
        connection = await control_db.get(
            ProviderConnection, request.provider_connection_id
        )
        connection.status = "revoked"
        await control_db.commit()
    with pytest.raises(PermissionError, match="unavailable"):
        await pending
    assert sends == []


async def test_binding_is_part_of_the_input_hash(control_db):
    from src.control_plane.relay.protocol import relay_invocation_input_hash

    resolver, request, *_ = await setup_authority(control_db)
    binding = await resolver.resolve(request)
    first = relay_invocation_input_hash(
        request.tool_name, request.arguments, agent_run_authority=binding
    )
    assert first != relay_invocation_input_hash(request.tool_name, request.arguments)
    assert first != relay_invocation_input_hash(
        request.tool_name,
        request.arguments,
        agent_run_authority=binding.model_copy(update={"link_generation": 2}),
    )


async def test_real_mcp_lifecycle_uses_durable_control_plane_admission(
    control_db, tmp_path
):
    """The target-side consumer/epoch below is synthetic, not deployed authority."""
    from src.control_plane.auth.context import AuthorizationContext
    from src.control_plane.execution_targets import RelayExecutionTarget
    from src.control_plane.relay.invocations import RelayInvocationBroker
    from src.control_plane.relay.protocol import (
        RelayInvocationEnvelope,
        RelayInvocationResultFrame,
        relay_invocation_input_hash,
    )
    from src.services.agent_runs.execution_target import AgentRunExecutionTarget
    from src.services.agent_runs.store import AgentRunStore
    from src.services.conversation_runtime.fake_provider import FakeProviderClient
    from tests.services.agent_runs.test_mcp_continuation import call, stopped
    from tests.services.agent_runs.test_mcp_tracer import synthetic_mcp
    from tests.services.conversation_acceptance import text_turn

    resolver, request, registry, redis, relay = await setup_authority(control_db)
    binding = await resolver.resolve(request)
    context = AuthorizationContext(
        account_id=request.account_id,
        provider_connection_id=request.provider_connection_id,
        provider_surface=request.provider_surface,
        subject="auth0|owner",
        client_id="chatgpt-client",
        scopes=frozenset({"shipagent.preview", "shipagent.status"}),
    )
    providers = [
        FakeProviderClient(
            script=[text_turn('{"clarification_code":"package_scope"}')]
        ),
        FakeProviderClient(script=[text_turn("PRIVATE_PLAN_CANARY")]),
        FakeProviderClient(
            script=[text_turn('{"clarification_code":"shipping_goal"}')]
        ),
    ]
    pending = iter(providers)
    broker = RelayInvocationBroker()
    owned = {}
    frames = []

    class SyntheticTargetConsumer:
        async def send_json(self, payload):
            frame = RelayInvocationEnvelope.model_validate(payload)
            assert frame.agent_run_authority == binding
            assert frame.input_hash == relay_invocation_input_hash(
                frame.tool_name, frame.arguments, agent_run_authority=binding
            )
            frames.append(frame)
            # A scripted consumer on an authenticated broker test connection;
            # production still needs enrollment/current worker-authority fencing.
            result = await owned["target"].invoke(
                TargetToolRequest(
                    binding.account_id,
                    binding.provider_connection_id,
                    binding.provider_surface,
                    frame.tool_name,
                    frame.arguments,
                    frame.audit_correlation_id,
                )
            )
            await broker.accept_result(
                RelayInvocationResultFrame(
                    relay_session_id=frame.relay_session_id,
                    relay_invocation_id=frame.relay_invocation_id,
                    status="ok",
                    result=result,
                )
            )

        async def close(self, code=1000, reason=None):
            pass

    await broker.register(
        relay.relay_session_id,
        SyntheticTargetConsumer(),
        account_id=request.account_id,
        device_id=relay.device_id,
    )

    def facade(service):
        owned["target"] = AgentRunExecutionTarget(service)
        return RelayExecutionTarget(registry, broker, agent_run_authority=resolver)

    path = tmp_path / "runs.sqlite3"

    def run_store(create=False):
        return AgentRunStore(
            path,
            account_id=request.account_id,
            execution_target_id=relay.execution_target_id,
            create=create,
        )

    def epoch(connection):
        return (
            str(binding.link_generation)
            if connection == binding.provider_connection_id
            else None
        )

    async with synthetic_mcp(
        run_store(True),
        lambda _: next(pending),
        context=context,
        connection_epoch=epoch,
        execution_target_factory=facade,
    ) as client:
        first = await call(
            client,
            "submit_shipagent_task",
            {"task": "Plan shipping", "mode": "source_free", "request_key": "cp-first"},
        )
        waiting = await stopped(client, first["run_reference"])
        assert waiting["state"] == "waiting_for_input"
        second = await call(
            client,
            "continue_shipagent_task",
            {
                "conversation_reference": first["conversation_reference"],
                "run_reference": first["run_reference"],
                "expected_revision": 1,
                "task": "One package",
                "request_key": "cp-second",
            },
        )
        complete = await stopped(client, second["run_reference"])
        assert complete["state"] == "completed"
        third = await call(
            client,
            "submit_shipagent_task",
            {"task": "Plan another", "mode": "source_free", "request_key": "cp-third"},
        )
        await stopped(client, third["run_reference"])
        cancelled = await call(
            client, "cancel_shipagent_run", {"run_reference": third["run_reference"]}
        )
        assert cancelled["conversation_state"] == "cancelled"
    async with synthetic_mcp(
        run_store(),
        lambda _: pytest.fail("Reads must not replay models"),
        context=context,
        connection_epoch=epoch,
        execution_target_factory=facade,
    ) as client:
        assert (
            await call(
                client,
                "read_shipagent_run",
                {"run_reference": complete["run_reference"]},
            )
            == complete
        )
        from fastmcp.exceptions import ToolError

        connection = await control_db.get(
            ProviderConnection, request.provider_connection_id
        )
        connection.status = "revoked"
        await control_db.commit()
        before = len(frames)
        with pytest.raises(ToolError):
            await call(
                client,
                "read_shipagent_run",
                {"run_reference": complete["run_reference"]},
            )
        assert len(frames) == before
    assert sum(len(provider.requests) for provider in providers) == 3


async def test_account_suspension_and_target_revocation_are_current_authority(
    control_db,
):
    from src.control_plane.models import CloudAccount

    resolver, request, registry, redis, session = await setup_authority(control_db)
    first = await resolver.resolve(request)
    account = await control_db.get(CloudAccount, request.account_id)
    account.suspended = True
    await control_db.commit()
    with pytest.raises(PermissionError, match="unavailable"):
        await resolver.resolve(request, expected=first)
    account.suspended = False
    await control_db.commit()
    await registry.revoke_device(request.account_id, session.device_id)
    with pytest.raises(PermissionError, match="unavailable"):
        await resolver.resolve(request, expected=first)
