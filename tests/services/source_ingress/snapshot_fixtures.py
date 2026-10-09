"""Real target/authority ownership around synthetic private snapshot input."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.conversation_runtime.fake_provider import FakeProviderClient
from src.services.source_ingress.reservation_contracts import (
    ReservationRequest,
    SourceOperatorContext,
)
from src.services.source_ingress.reservation_store import ReservationStore
from src.services.source_ingress.reservations import SourceReservationCoordinator
from src.services.source_ingress.source_store_owner import SourceStoreOwner
from tests.services.agent_runs.test_continuation import terminal
from tests.services.conversation_acceptance import text_turn
from tests.services.source_ingress.reservation_fixtures import SQLiteSourceAuthority


@asynccontextmanager
async def snapshot_target(
    tmp_path, raw=b'Zip,Note\n00123,"line1\nline2"\n', *, startup=True
):
    providers = []

    def factory(_):
        provider = FakeProviderClient(
            script=[text_turn('{"clarification_code":"shipping_goal"}')]
        )
        providers.append(provider)
        return provider

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    agent = AgentRunService(
        store=runs, provider_factory=factory, connection_epoch=lambda _: "epoch-a"
    )
    metadata = ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        create=True,
    )
    maintenance = SourceStoreOwner(agent, metadata)
    managers = []
    coordinator = None
    try:
        await agent.start()
        maintenance.open()
        maintenance.upgrade_to_v2()
        authority = SQLiteSourceAuthority(tmp_path / "authority.sqlite3")
        accepted = agent.submit(
            connection_id="connection-a",
            arguments={
                "task": "SYNTHETIC_PRIVATE_TASK",
                "mode": "source_free",
                "request_key": "initial",
            },
        )
        assert (await terminal(agent, accepted["run_reference"]))[
            "state"
        ] == "waiting_for_input"
        async with asyncio.timeout(3):
            while agent._active_run is not None:
                await asyncio.sleep(0.001)
        arguments = {
            "operator_context": SourceOperatorContext("operator-a"),
            "provider_connection_id": "connection-a",
            "conversation_reference": accepted["conversation_reference"],
        }
        request = ReservationRequest(
            "source-a", len(raw), hashlib.sha256(raw).hexdigest()
        )
        coordinator = SourceReservationCoordinator(
            agent, metadata, authority, expected_target_fingerprint="fingerprint-a"
        )
        reservation = coordinator.reserve(**arguments, request=request)
        root = tmp_path / "content"
        root.mkdir(mode=0o700)
        if startup:
            from src.services.source_ingress.snapshot_files import SnapshotFiles

            maintenance.reconcile_snapshots(SnapshotFiles(root))
        target = SimpleNamespace(
            agent=agent,
            metadata=metadata,
            authority=authority,
            providers=providers,
            accepted=accepted,
            arguments=arguments,
            request=request,
            reservation=reservation,
            root=root,
            raw=raw,
            coordinator=coordinator,
            managers=managers,
        )
        yield target
    finally:
        for manager in reversed(managers):
            manager.close()
        if coordinator is not None:
            coordinator.close()
        maintenance.close()
        await agent.close()
        assert not agent._lease.is_owned() if agent._lease is not None else True


def snapshot_manager(target, **changes):
    from src.services.source_ingress.snapshots import SourceSnapshotManager

    manager = SourceSnapshotManager(
        target.agent,
        target.metadata,
        target.authority,
        target.root,
        expected_target_fingerprint="fingerprint-a",
        **changes,
    )
    target.managers.append(manager)  # Retain before opening the captured root.
    manager.open()
    return manager


def receive_args(target):
    return target.arguments | {
        "request_key": target.request.request_key,
        "reservation_id": target.reservation.reservation_id,
    }
