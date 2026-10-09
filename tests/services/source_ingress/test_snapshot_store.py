"""Disk source ownership is established before any SQLite recovery effect."""

import sqlite3
import time
from contextlib import contextmanager

import pytest

from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.reservation_store import ReservationStore
from tests.services.agent_runs.test_source_ownership import owned_conversation


def metadata(tmp_path, runs, *, create=True):
    return ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        create=create,
    )


def test_maintenance_writer_proves_storage_pins_without_conversation_or_authority(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path, state="active", epoch=None) as (
        runs,
        _,
        _,
        _,
        scope,
    ):
        assert callable(getattr(scope, "require_storage_owner", None)), (
            "maintenance writer proof is absent"
        )
        scope.acquire(deadline=time.monotonic() + 2)

        def forbidden(*args, **kwargs):
            pytest.fail("maintenance looked up a conversation")

        monkeypatch.setattr(scope, "resolve", forbidden)
        values = {
            "account_id": "account-a",
            "execution_target_id": "target-a",
            "coordinator_path": runs.path.with_suffix(".coordinator.lock"),
        }
        scope.require_storage_owner(**values)
        for key, value in [
            ("account_id", "foreign"),
            ("execution_target_id", "foreign"),
            ("coordinator_path", tmp_path / "other.lock"),
        ]:
            with pytest.raises(RuntimeError, match="unavailable"):
                scope.require_storage_owner(**(values | {key: value}))


@pytest.mark.parametrize("state", ["none", "unacquired", "retired", "expired"])
def test_source_open_requires_live_matching_writer_before_connect(
    tmp_path, monkeypatch, state
):
    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        store = metadata(tmp_path, runs)
        if state in {"retired", "expired"}:
            scope.acquire(deadline=time.monotonic() + 2)
            if state == "retired":
                scope.retire()
            else:
                scope._deadline = time.monotonic() - 1
        calls = []
        original = sqlite3.connect

        def connect(path, *args, **kwargs):
            if str(store.path) in str(path):
                calls.append(str(path))
                pytest.fail("unfenced source SQLite connection")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", connect)
        try:
            with pytest.raises(ReservationError, match="unavailable"):
                store.open(
                    conversation=None if state == "none" else scope,
                    deadline=time.monotonic() + 2,
                )
            assert calls == [] and not store.path.exists()
        finally:
            store.close()


def test_source_setup_and_transactions_keep_the_same_writer_until_retired(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        source = store.transaction(conversation=scope)
        try:
            source.acquire(deadline=time.monotonic() + 2)
            assert (
                source._db.in_transaction
            )  # The same writer remains captured through retirement.
            source.retire()
            scope.retire()
            calls = []
            original = sqlite3.connect

            def connect(path, *args, **kwargs):
                if str(store.path) in str(path):
                    calls.append(str(path))
                    pytest.fail("cached store bypassed its retired writer")
                return original(path, *args, **kwargs)

            monkeypatch.setattr(sqlite3, "connect", connect)
            stale = store.transaction(conversation=scope)
            try:
                with pytest.raises(ReservationError):
                    stale.acquire(deadline=time.monotonic() + 2)
                assert calls == []
            finally:
                stale.retire()
        finally:
            source.retire()
            store.close()


def test_oversized_source_recovery_file_is_denied_before_sqlite_connect(
    tmp_path, monkeypatch
):
    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        store.close()
        with store.path.open("r+b") as output:
            output.truncate(16 * 1024 * 1024 + 4096)
        reopened = metadata(tmp_path, runs, create=False)
        calls = []
        original = sqlite3.connect

        def connect(path, *args, **kwargs):
            if str(store.path) in str(path):
                calls.append(str(path))
                pytest.fail("oversized source opened before profile refusal")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", connect)
        try:
            with pytest.raises(ReservationError):
                reopened.open(conversation=scope, deadline=time.monotonic() + 2)
            assert calls == []
        finally:
            reopened.close()


def test_every_source_transaction_uses_the_supported_sqlite_profile(tmp_path):
    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        try:
            tx.acquire(deadline=time.monotonic() + 2)
            for name, value in {
                "max_page_count": 4096,
                "cache_spill": 0,
                "temp_store": 2,
                "wal_autocheckpoint": 0,
                "auto_vacuum": 0,
                "mmap_size": 0,
            }.items():
                assert tx._db.execute("PRAGMA " + name).fetchone()[0] == value
        finally:
            tx.retire()
            store.close()


def test_retirement_busy_checkpoint_retains_exact_connection_and_known_commit(tmp_path):
    from contextlib import closing

    from tests.services.source_ingress.test_reservation_store import insert

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        try:
            with closing(sqlite3.connect(store.path, isolation_level=None)) as reader:
                reader.execute("BEGIN")
                reader.execute("SELECT * FROM reservations").fetchall()
                tx.acquire(deadline=time.monotonic() + 2)
                insert(tx)
                tx.commit()
                with pytest.raises(ReservationError):
                    tx.retire()
                assert tx.committed is True
                assert tx._db is not None
                reader.rollback()
            tx.retire()
            assert tx.committed is True and tx._db is None
        finally:
            tx.retire()
            store.close()


async def test_retained_maintenance_owner_opens_without_model_or_operator_authority(
    tmp_path,
):
    import importlib
    import importlib.util

    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore

    name = "src.services.source_ingress.source_store_owner"
    assert importlib.util.find_spec(name), "source maintenance owner is absent"
    calls = []

    def provider(_):
        calls.append(True)
        pytest.fail("storage setup must not call a model")

    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    agent = AgentRunService(store=runs, provider_factory=provider)
    await agent.start()
    store = metadata(tmp_path, runs)
    owner = importlib.import_module(name).SourceStoreOwner(agent, store)
    try:
        owner.open()
        assert store.path.is_file() and store.initialization_committed
        assert calls == []
        borrowed, generation = agent.borrow_coordinator()
        assert generation > 0
        borrowed.retire()
    finally:
        owner.close()
        await agent.close()


async def test_failed_maintenance_setup_keeps_original_borrow_until_explicit_cleanup(
    tmp_path, monkeypatch
):
    import importlib
    import importlib.util

    from src.services.agent_runs.service import AgentRunService
    from src.services.agent_runs.store import AgentRunStore
    from src.services.source_ingress.reservation_store import ReservationTransaction

    name = "src.services.source_ingress.source_store_owner"
    assert importlib.util.find_spec(name), "source maintenance owner is absent"
    runs = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    agent = AgentRunService(
        store=runs, provider_factory=lambda _: pytest.fail("model called")
    )
    await agent.start()
    store = metadata(tmp_path, runs)
    owner = importlib.import_module(name).SourceStoreOwner(agent, store)
    original = ReservationTransaction._close_database
    failed = False

    def close(scope):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("PRIVATE-CLOSE-CANARY")
        original(scope)

    monkeypatch.setattr(ReservationTransaction, "_close_database", close)
    try:
        with pytest.raises(ReservationError):
            owner.open()
        assert store.initialization_committed
        with pytest.raises(RuntimeError):
            agent.borrow_coordinator()
        owner.close()
    finally:
        owner.close()
        await agent.close()


@pytest.mark.parametrize("after_effect", [False, True])
def test_creation_file_is_retained_before_close_failure_and_never_opens_sqlite(
    tmp_path, monkeypatch, after_effect
):
    from src.services.source_ingress.reservation_store import ReservationTransaction

    assert callable(getattr(ReservationTransaction, "_retire_created_file", None)), (
        "created-file retirement owner is absent"
    )
    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        original = ReservationTransaction._retire_created_file
        handles = []
        fail = True

        def retire(tx):
            nonlocal fail
            if tx._created_file is not None and fail:
                fail = False
                handles.append(tx._created_file)
                if after_effect:
                    original(tx)
                raise OSError("PRIVATE-CREATE-CLOSE")
            original(tx)

        monkeypatch.setattr(ReservationTransaction, "_retire_created_file", retire)
        connect = sqlite3.connect

        def no_source(path, *args, **kwargs):
            assert str(store.path) not in str(path), (
                "SQL opened before creation descriptor retired"
            )
            return connect(path, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", no_source)
        with pytest.raises(ReservationError):
            store.open(conversation=scope, deadline=time.monotonic() + 2)
        store.close()
        assert handles and all(handle.closed for handle in handles)
        assert store.path.stat().st_size == 0


def test_connection_safeguards_precede_the_first_owner_row_lookup(
    tmp_path, monkeypatch
):
    from src.services.source_ingress.reservation_store import ReservationTransaction

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        original_store = metadata(tmp_path, runs)
        original_store.open(conversation=scope, deadline=time.monotonic() + 2)
        original_store.close()
        reopened = metadata(tmp_path, runs, create=False)
        original = ReservationTransaction._verify_owner
        observed = []

        def verify(tx):
            current = tuple(
                tx._db.execute("PRAGMA " + key).fetchone()[0]
                for key in ("temp_store", "automatic_index", "trusted_schema")
            )
            observed.append(current)
            assert current == (2, 0, 0), (
                "schema-dependent read preceded connection safeguards"
            )
            original(tx)

        monkeypatch.setattr(ReservationTransaction, "_verify_owner", verify)
        try:
            reopened.open(conversation=scope, deadline=time.monotonic() + 2)
            assert observed and set(observed) == {(2, 0, 0)}
        finally:
            reopened.close()


def test_new_source_store_starts_with_v2_lifecycle_tables(tmp_path):
    from contextlib import closing

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        try:
            store.open(conversation=scope, deadline=time.monotonic() + 2)
            with closing(sqlite3.connect(store.path)) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 2
                assert {
                    row[0]
                    for row in db.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table'"
                    )
                } == {
                    "target_owner",
                    "reservations",
                    "source_lifecycle",
                    "snapshot_manifests",
                }
        finally:
            store.close()


@pytest.mark.parametrize("kind", ["trigger", "view", "extra_index"])
def test_unsupported_schema_is_refused_before_owner_row_read(
    tmp_path, monkeypatch, kind
):
    from contextlib import closing

    from src.services.source_ingress.reservation_store import ReservationTransaction

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        store.close()
        with closing(sqlite3.connect(store.path)) as db:
            if kind == "trigger":
                db.execute(
                    "CREATE TRIGGER injected AFTER INSERT ON reservations BEGIN SELECT 1; END"
                )
            elif kind == "view":
                db.execute("DROP TABLE target_owner")
                db.execute(
                    "CREATE VIEW target_owner AS SELECT 1 AS singleton, 'account-a' AS account_id, 'target-a' AS target_id"
                )
            else:
                db.execute("CREATE INDEX injected ON reservations(input_digest)")
            db.commit()
        reopened = metadata(tmp_path, runs, create=False)
        original = ReservationTransaction._execute
        reads = []

        def execute(tx, sql, *args):
            if "SELECT account_id" in sql:
                reads.append(sql)
            return original(tx, sql, *args)

        monkeypatch.setattr(ReservationTransaction, "_execute", execute)
        try:
            with pytest.raises(ReservationError):
                reopened.open(conversation=scope, deadline=time.monotonic() + 2)
            assert reads == []
        finally:
            reopened.close()


def snapshots(tx):
    from src.services.source_ingress import snapshot_store

    assert callable(getattr(snapshot_store, "SnapshotTransaction", None)), (
        "snapshot lifecycle metadata is absent"
    )
    return snapshot_store.SnapshotTransaction(tx)


def test_claim_is_private_single_owner_and_keeps_original_reservation_times(tmp_path):
    from dataclasses import FrozenInstanceError

    from tests.services.source_ingress.test_reservation_store import insert

    with owned_conversation(tmp_path) as (runs, _, generation, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        try:
            tx.acquire(deadline=time.monotonic() + 2)
            record = insert(tx)
            lifecycle = snapshots(tx).claim(
                record, generation=generation, authorization_expires_at=350, now=150
            )
            assert lifecycle.state == "receiving"
            assert lifecycle.reservation_id == record.receipt.reservation_id
            assert lifecycle.generation == generation
            assert lifecycle.authorization_expires_at == 350
            assert lifecycle.reserved_content_bytes == 3 * 1024 * 1024
            assert lifecycle.cleanup_pending is True
            assert lifecycle.raw_basename == lifecycle.attempt_id + ".raw"
            assert lifecycle.normalized_basename == lifecycle.attempt_id + ".normalized"
            assert len(lifecycle.attempt_id) == 32
            with pytest.raises(FrozenInstanceError):
                lifecycle.state = "complete"
            assert lifecycle.attempt_id not in repr(lifecycle)
            with pytest.raises(ReservationError):
                snapshots(tx).claim(
                    record, generation=generation, authorization_expires_at=390, now=151
                )
            assert snapshots(tx).lookup_lifecycle(record) == lifecycle
            assert record.receipt.upload_expires_at == 400
            tx.commit()
        finally:
            tx.retire()
            store.close()


def test_expired_claimed_work_keeps_slot_and_reserved_peak_bytes(tmp_path):
    from tests.services.source_ingress.test_reservation_store import insert

    with owned_conversation(tmp_path) as (runs, _, generation, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        try:
            tx.acquire(deadline=time.monotonic() + 2)
            for key in ["first", "second"]:
                record = insert(tx, key)
                snapshots(tx).claim(
                    record, generation=generation, authorization_expires_at=350, now=150
                )
            with pytest.raises(ReservationError) as error:
                insert(tx, "third", now=500)
            assert error.value.code == "source_limit_exceeded"
            inventory = snapshots(tx).inventory(now=500)
            assert inventory.incomplete_count == 2
            assert inventory.content_bytes == 6 * 1024 * 1024
        finally:
            tx.retire()
            store.close()


@contextmanager
def snapshot_transaction(tmp_path):
    from tests.services.source_ingress.test_reservation_store import insert

    with owned_conversation(tmp_path) as (runs, _, generation, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        try:
            tx.acquire(deadline=time.monotonic() + 2)
            record = insert(tx)
            adapter = snapshots(tx)
            attempt = adapter.claim(
                record, generation=generation, authorization_expires_at=350, now=150
            )
            yield tx, adapter, record, attempt
        finally:
            tx.retire()
            store.close()


def stage_snapshot(adapter, record, attempt):
    from src.services.source_ingress import snapshot_contracts

    assert callable(getattr(snapshot_contracts, "SnapshotManifest", None)), (
        "immutable manifest contract is absent"
    )
    attempt = adapter.record_files(attempt, identities=((1, 11), (1, 12)))
    for expected, state in [
        ("receiving", "sealed"),
        ("sealed", "parsing"),
        ("parsing", "staged"),
    ]:
        attempt = adapter.set_phase(attempt, expected=expected, state=state)
    manifest = snapshot_contracts.SnapshotManifest(
        snapshot_id="d" * 32,
        reservation_id=record.receipt.reservation_id,
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        raw_content_sha256=record.request.content_sha256,
        normalized_sha256="e" * 64,
        raw_length=record.request.content_length,
        normalized_length=60,
        row_count=1,
        column_count=2,
        parser_profile=record.request.parser_profile,
        raw_identity=attempt.raw_identity,
        normalized_identity=attempt.normalized_identity,
        source_expires_at=record.receipt.prospective_source_expires_at,
    )
    return attempt, manifest


def test_completed_manifest_is_immutable_and_keeps_cleanup_capacity(tmp_path):
    from dataclasses import FrozenInstanceError

    with snapshot_transaction(tmp_path) as (tx, adapter, record, attempt):
        attempt, manifest = stage_snapshot(adapter, record, attempt)
        completed = adapter.complete(attempt, manifest)
        assert completed.state == "complete" and completed.cleanup_pending
        assert (
            adapter.lookup_manifest(record.namespace, manifest.snapshot_id) == manifest
        )
        assert adapter.inventory(now=500).content_bytes == 3 * 1024 * 1024
        assert adapter.inventory(now=500).incomplete_count == 1
        assert adapter.inventory(now=500).completed_count == 1
        with pytest.raises(FrozenInstanceError):
            manifest.raw_length = 999
        assert manifest.snapshot_id not in repr(manifest)
        with pytest.raises(ReservationError):
            adapter.complete(completed, manifest)
        with pytest.raises(ReservationError):
            adapter.mark_failed(completed, cleanup_complete=False)
        with pytest.raises(ReservationError):
            adapter.acknowledge_retirement(
                completed, generation=attempt.generation, retirement_proof=object()
            )
        assert (
            adapter.lookup_manifest(record.namespace, manifest.snapshot_id) == manifest
        )
        tx.commit()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_lifecycle",
        "missing_reservation",
        "wrong_generation",
        "wrong_identity",
        "wrong_expiry",
        "wrong_counter",
        "oversized_payload",
    ],
)
def test_cross_inventory_corruption_blocks_reference_and_claim_recovery(
    tmp_path, mutation
):
    import json

    from src.services.source_ingress.reservation_store import canonical_json

    with snapshot_transaction(tmp_path) as (tx, adapter, record, attempt):
        attempt, manifest = stage_snapshot(adapter, record, attempt)
        adapter.complete(attempt, manifest)
        if mutation == "missing_lifecycle":
            tx._execute("DELETE FROM source_lifecycle")
        elif mutation == "missing_reservation":
            tx._execute("DELETE FROM reservations")
        elif mutation == "wrong_counter":
            tx._execute("UPDATE snapshot_manifests SET metadata_bytes=1")
        elif mutation == "oversized_payload":
            tx._execute(
                "UPDATE snapshot_manifests SET payload=?", ("canary-secret" * 800,)
            )
        else:
            payload = json.loads(
                tx._execute("SELECT payload FROM snapshot_manifests").fetchone()[0]
            )
            if mutation == "wrong_generation":
                payload["generation"] += 1
            elif mutation == "wrong_identity":
                payload["raw_identity"] = [1, 99]
            else:
                payload["source_expires_at"] += 1
            encoded = canonical_json(payload)
            tx._execute(
                "UPDATE snapshot_manifests SET payload=?,metadata_bytes=?",
                (encoded, len(encoded.encode()) + 72),
            )
        for action in [
            lambda: adapter.inventory(now=150),
            lambda: tx.lookup(record.namespace),
            lambda: adapter.claim(
                record,
                generation=attempt.generation,
                authorization_expires_at=350,
                now=150,
            ),
        ]:
            with pytest.raises(ReservationError) as error:
                action()
            assert error.value.code == "reservation_unavailable"
            assert "canary" not in str(error.value)


def test_failed_metadata_is_terminal_but_cannot_claim_retired_work(tmp_path):
    with snapshot_transaction(tmp_path) as (_, adapter, record, attempt):
        with pytest.raises(ReservationError):
            adapter.mark_failed(attempt, cleanup_complete=True)
        failed = adapter.mark_failed(attempt, cleanup_complete=False)
        assert failed.state == "failed" and failed.cleanup_pending
        assert adapter.inventory(now=500).incomplete_count == 1
        with pytest.raises(ReservationError):
            adapter.set_phase(failed, expected="failed", state="receiving")
        with pytest.raises(ReservationError):
            adapter.claim(
                record,
                generation=attempt.generation,
                authorization_expires_at=350,
                now=160,
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", True),
        ("state", []),
        ("cleanup_pending", 1),
        ("raw_identity", [1, 2]),
        ("attempt_id", "private-canary"),
    ],
)
def test_lifecycle_contract_rejects_wrong_scalar_shapes(tmp_path, field, value):
    from dataclasses import replace

    with snapshot_transaction(tmp_path) as (_, _, _, attempt):
        with pytest.raises(ReservationError):
            replace(attempt, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_length", True),
        ("row_count", -1),
        ("column_count", 65),
        ("normalized_length", 2 * 1024 * 1024 + 1),
        ("parser_profile", "other"),
        ("normalized_sha256", "CANARY"),
    ],
)
def test_manifest_contract_rejects_wrong_shape(tmp_path, field, value):
    from dataclasses import replace

    with snapshot_transaction(tmp_path) as (_, adapter, record, attempt):
        _, manifest = stage_snapshot(adapter, record, attempt)
        with pytest.raises(ReservationError):
            replace(manifest, **{field: value})


def test_transition_rejects_stale_attempt_missing_files_and_identity_replacement(
    tmp_path,
):
    with snapshot_transaction(tmp_path) as (_, adapter, record, attempt):
        with pytest.raises(ReservationError):
            adapter.set_phase(attempt, expected="receiving", state="sealed")
        recorded = adapter.record_files(attempt, identities=((1, 11), (1, 12)))
        with pytest.raises(ReservationError):
            adapter.record_files(recorded, identities=((1, 13), (1, 14)))
        with pytest.raises(ReservationError):
            adapter.set_phase(attempt, expected="receiving", state="sealed")
        assert adapter.lookup_lifecycle(record) == recorded


def test_manifest_record_cap_rejects_before_decoding_any_manifest(
    tmp_path, monkeypatch
):
    import src.services.source_ingress.snapshot_store as module

    with snapshot_transaction(tmp_path) as (tx, adapter, _, _):
        assert module.MAX_COMPLETED_SNAPSHOTS == 128
        for index in range(129):
            tx._execute(
                "INSERT INTO snapshot_manifests VALUES(?,?,?,?)",
                (f"{index:032x}", f"{index:032x}", "{}", 74),
            )
        original = module._decode

        def decode(payload, model):
            assert model is not module.SnapshotManifest, (
                "manifest payload decoded before row-count refusal"
            )
            return original(payload, model)

        monkeypatch.setattr(module, "_decode", decode)
        with pytest.raises(ReservationError):
            adapter.inventory(now=150)


def test_complete_rechecks_metadata_and_manifest_count_budget(tmp_path, monkeypatch):
    import src.services.source_ingress.snapshot_store as module

    with snapshot_transaction(tmp_path) as (_, adapter, record, attempt):
        attempt, manifest = stage_snapshot(adapter, record, attempt)
        monkeypatch.setattr(module, "MAX_COMPLETED_SNAPSHOTS", 0)
        with pytest.raises(ReservationError) as error:
            adapter.complete(attempt, manifest)
        assert error.value.code == "source_limit_exceeded"
        assert adapter.lookup_lifecycle(record) == attempt


def test_copied_held_fence_cannot_open_source_or_retire_original_writer(
    tmp_path, monkeypatch
):
    import copy

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        copied = copy.copy(scope)
        store = metadata(tmp_path, runs)
        real = sqlite3.connect
        calls = []

        def connect(path, *args, **kwargs):
            if str(store.path) in str(path):
                calls.append(str(path))
            return real(path, *args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(sqlite3, "connect", connect)
                with pytest.raises(ReservationError):
                    store.open(conversation=copied, deadline=time.monotonic() + 2)
            assert calls == []
            with pytest.raises(RuntimeError):
                copied.retire()
            scope.require_storage_owner(
                account_id="account-a",
                execution_target_id="target-a",
                coordinator_path=runs.path.with_suffix(".coordinator.lock"),
            )
        finally:
            store.close()


def test_completed_identity_cannot_reuse_reservation_or_attempt_id(tmp_path):
    from dataclasses import replace

    with snapshot_transaction(tmp_path) as (_, adapter, record, attempt):
        attempt, manifest = stage_snapshot(adapter, record, attempt)
        for identity in (record.receipt.reservation_id, attempt.attempt_id):
            with pytest.raises(ReservationError):
                replace(manifest, snapshot_id=identity)


def test_inherited_fence_retirement_is_denied_before_child_sqlite_use(tmp_path):
    import os
    import select

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        reader, writer = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(reader)
            try:
                scope.retire()
                os.write(writer, b"accepted")
            except RuntimeError:
                os.write(writer, b"denied")
            finally:
                os.close(writer)
                os._exit(0)
        os.close(writer)
        try:
            assert select.select([reader], [], [], 1)[0]
            assert os.read(reader, 32) == b"denied"
        finally:
            os.close(reader)
            _, status = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        scope.require_storage_owner(
            account_id="account-a",
            execution_target_id="target-a",
            coordinator_path=runs.path.with_suffix(".coordinator.lock"),
        )


@pytest.mark.parametrize(
    "kind",
    ["counter", "oversized", "duplicate_key", "unretired_flag", "orphan_complete"],
)
def test_lifecycle_corruption_is_closed_and_never_trusts_stored_counters(
    tmp_path, kind
):
    import json

    from src.services.source_ingress.reservation_store import canonical_json

    with snapshot_transaction(tmp_path) as (tx, adapter, _, _):
        if kind == "counter":
            tx._execute("UPDATE source_lifecycle SET metadata_bytes=-1")
        elif kind == "oversized":
            tx._execute(
                "UPDATE source_lifecycle SET payload=?,metadata_bytes=?",
                ("PRIVATE_CANARY" * 400, 40 + 14 * 400),
            )
        else:
            payload = json.loads(
                tx._execute("SELECT payload FROM source_lifecycle").fetchone()[0]
            )
            if kind == "unretired_flag":
                payload["cleanup_pending"] = False
            elif kind == "orphan_complete":
                payload.update(
                    state="complete", raw_identity=[1, 11], normalized_identity=[1, 12]
                )
            encoded = canonical_json(payload)
            if kind == "duplicate_key":
                encoded = encoded[:-1] + ',"version":1}'
            tx._execute(
                "UPDATE source_lifecycle SET payload=?,metadata_bytes=?",
                (encoded, len(encoded.encode()) + 40),
            )
        with pytest.raises(ReservationError) as error:
            adapter.inventory(now=150)
        assert error.value.code == "reservation_unavailable"
        assert "PRIVATE" not in str(error.value)


def test_claim_collision_and_shared_file_identity_never_create_second_owner(
    tmp_path, monkeypatch
):
    import src.services.source_ingress.snapshot_store as module
    from tests.services.source_ingress.test_reservation_store import insert

    with snapshot_transaction(tmp_path) as (tx, adapter, _, attempt):
        second = insert(tx, "second")
        with monkeypatch.context() as patch:
            patch.setattr(module.secrets, "token_hex", lambda _: attempt.attempt_id)
            with pytest.raises(ReservationError):
                adapter.claim(
                    second,
                    generation=attempt.generation,
                    authorization_expires_at=350,
                    now=150,
                )
        assert adapter.lookup_lifecycle(second) is None
        second_attempt = adapter.claim(
            second, generation=attempt.generation, authorization_expires_at=350, now=150
        )
        first_recorded = adapter.record_files(attempt, identities=((1, 11), (1, 12)))
        with pytest.raises(ReservationError):
            adapter.record_files(second_attempt, identities=((1, 11), (1, 13)))
        assert adapter.lookup_lifecycle(second) == second_attempt
        assert first_recorded.raw_identity == (1, 11)


@pytest.mark.parametrize("after_effect", [False, True])
def test_complete_commit_fault_reopens_only_actual_durable_manifest(
    tmp_path, after_effect
):
    with snapshot_transaction(tmp_path) as (tx, adapter, record, attempt):
        attempt, manifest = stage_snapshot(adapter, record, attempt)
        adapter.complete(attempt, manifest)
        original = tx._commit_database

        def commit():
            if after_effect:
                original()
            raise sqlite3.OperationalError("PRIVATE_COMMIT_CANARY")

        tx._commit_database = commit
        with pytest.raises(ReservationError):
            tx.commit()
        assert tx.commit_attempted and not tx.committed
        tx.retire()
        reopened = tx._store.transaction(conversation=tx._conversation)
        try:
            reopened.acquire(deadline=time.monotonic() + 2)
            if after_effect:
                assert (
                    snapshots(reopened).lookup_manifest(
                        record.namespace, manifest.snapshot_id
                    )
                    == manifest
                )
                assert snapshots(reopened).inventory(now=500).incomplete_count == 1
            else:
                assert reopened.lookup(record.namespace) is None
        finally:
            reopened.retire()


def test_completed_manifest_lookup_checks_exact_private_namespace(tmp_path):
    from dataclasses import replace

    with snapshot_transaction(tmp_path) as (_, adapter, record, attempt):
        attempt, manifest = stage_snapshot(adapter, record, attempt)
        adapter.complete(attempt, manifest)
        for key, value in [
            ("request_key", "other"),
            ("provider_connection_id", "other"),
            ("link_epoch", "other"),
            ("account_id", "other"),
            ("execution_target_id", "other"),
            ("target_fingerprint", "other"),
        ]:
            with pytest.raises(ReservationError):
                adapter.lookup_manifest(
                    replace(record.namespace, **{key: value}), manifest.snapshot_id
                )
        assert (
            adapter.lookup_manifest(record.namespace, manifest.snapshot_id) == manifest
        )


def test_actual_1024_record_v2_inventory_preserves_page_profile_and_denies_next(
    tmp_path,
):
    import hashlib
    from dataclasses import asdict

    import src.services.source_ingress.reservation_store as module
    from src.services.source_ingress.reservation_contracts import ReservationReceipt
    from tests.services.source_ingress.test_reservation_store import namespace, request

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        try:
            tx.acquire(deadline=time.monotonic() + 2)
            assert module.MAX_RETAINED_RECORDS == 1024
            for index in range(1024):
                key = f"archived-{index}"
                record = module.ReservationRecord(
                    namespace(key),
                    request(key),
                    1,
                    ReservationReceipt(f"{index:032x}", "reserved", 100, 400, 86500),
                )
                payload = module._payload(record)
                namespace_hash = hashlib.sha256(
                    module.canonical_json(asdict(record.namespace)).encode()
                ).hexdigest()
                input_data = asdict(record.request)
                input_data.pop("request_key")
                input_hash = hashlib.sha256(
                    module.canonical_json(input_data).encode()
                ).hexdigest()
                size = module.metadata_size(
                    payload, record.receipt.reservation_id, namespace_hash, input_hash
                )
                tx._execute(
                    "INSERT INTO reservations VALUES(?,?,?,?,?,?)",
                    (
                        record.receipt.reservation_id,
                        namespace_hash,
                        input_hash,
                        400,
                        payload,
                        size,
                    ),
                )
            assert snapshots(tx).inventory(now=500).incomplete_count == 0
            with pytest.raises(ReservationError) as error:
                from tests.services.source_ingress.test_reservation_store import insert

                insert(tx, "over-cap", now=500)
            assert error.value.code == "source_limit_exceeded"
            assert tx._db.execute("PRAGMA max_page_count").fetchone()[0] == 4096
            assert tx._db.execute("PRAGMA page_count").fetchone()[0] <= 4096
            tx.commit()
        finally:
            tx.retire()
            store.close()
        assert store.path.stat().st_size <= 16 * 1024 * 1024


@pytest.mark.parametrize("second_kind", ["transaction", "reopen", "new_store"])
def test_one_source_owner_per_fence_denies_before_any_second_disk_effect(
    tmp_path, monkeypatch, second_kind
):
    from src.services.source_ingress.sqlite_profile import SourceSqliteProfile

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        first = store.transaction(conversation=scope)
        second = None
        try:
            first.acquire(deadline=time.monotonic() + 2)
            if second_kind == "transaction":
                second = store.transaction(conversation=scope)

                def action():
                    return second.acquire(deadline=time.monotonic() + 0.1)
            elif second_kind == "reopen":
                second = metadata(tmp_path, runs, create=False)

                def action():
                    return second.open(
                        conversation=scope, deadline=time.monotonic() + 0.1
                    )
            else:
                second = ReservationStore(
                    tmp_path / "second.sqlite3",
                    account_id="account-a",
                    execution_target_id="target-a",
                    coordinator_path=runs.path.with_suffix(".coordinator.lock"),
                    create=True,
                )

                def action():
                    return second.open(
                        conversation=scope, deadline=time.monotonic() + 0.1
                    )

            calls = []
            original = SourceSqliteProfile.inspect_files

            def inspect(profile, *args, **kwargs):
                calls.append(True)
                return original(profile, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(SourceSqliteProfile, "inspect_files", inspect)
                with pytest.raises(ReservationError):
                    action()
            assert calls == []
            assert not (tmp_path / "second.sqlite3").exists()
            with pytest.raises(RuntimeError):
                scope.retire()
            first._require_active()
            # An unadmitted second owner must not release the original binding.
            second.retire() if second_kind == "transaction" else second.close()
            with pytest.raises(RuntimeError):
                scope.retire()
        finally:
            first.retire()
            if second is not None:
                second.retire() if second_kind == "transaction" else second.close()
            store.close()


def test_copied_source_transaction_cannot_read_or_retire_original_handles(tmp_path):
    import copy

    with snapshot_transaction(tmp_path) as (tx, adapter, record, _):
        copied = copy.copy(tx)
        with pytest.raises(ReservationError):
            copied.lookup(record.namespace)
        with pytest.raises(ReservationError):
            copied.retire()
        assert tx.lookup(record.namespace) == record
        assert adapter.inventory(now=150).incomplete_count == 1


@pytest.mark.parametrize("after_effect", [False, True])
def test_source_binding_interruption_is_retained_before_any_file_creation(
    tmp_path, monkeypatch, after_effect
):
    class Interrupted(BaseException):
        pass

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        original = scope._claim_source_owner

        def claim(owner):
            if after_effect:
                original(owner)
            raise Interrupted()

        try:
            with monkeypatch.context() as patch:
                patch.setattr(scope, "_claim_source_owner", claim)
                with pytest.raises(Interrupted):
                    store.open(conversation=scope, deadline=time.monotonic() + 2)
            assert not store.path.exists()
            if after_effect:
                with pytest.raises(RuntimeError):
                    scope.retire()
                assert scope._source_owner is store._setup
            store.close()
            assert scope._source_owner is None
        finally:
            store.close()


@pytest.mark.parametrize("after_effect", [False, True])
def test_source_release_interruption_never_releases_a_later_owner(
    tmp_path, monkeypatch, after_effect
):
    class Interrupted(BaseException):
        pass

    with snapshot_transaction(tmp_path) as (tx, _, _, _):
        scope = tx._conversation
        original = scope._release_source_owner

        def release(owner):
            if after_effect:
                original(owner)
            raise Interrupted()

        with monkeypatch.context() as patch:
            patch.setattr(scope, "_release_source_owner", release)
            with pytest.raises(Interrupted):
                tx.retire()
        assert tx._db is None and tx._files_checked
        if not after_effect:
            with pytest.raises(RuntimeError):
                scope.retire()
            tx.retire()
        later = tx._store.transaction(conversation=scope)
        try:
            later.acquire(deadline=time.monotonic() + 2)
            tx.retire()  # Old retry cannot clear later's exact binding.
            later._require_active()
            with pytest.raises(RuntimeError):
                scope.retire()
        finally:
            later.retire()


def test_inherited_source_transaction_denies_retirement_before_sqlite_use(tmp_path):
    import os
    import select

    with snapshot_transaction(tmp_path) as (tx, _, record, _):
        reader, writer = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(reader)
            try:
                tx.retire()
                os.write(writer, b"accepted")
            except ReservationError:
                os.write(writer, b"denied")
            finally:
                os.close(writer)
                os._exit(0)
        os.close(writer)
        try:
            assert select.select([reader], [], [], 1)[0]
            assert os.read(reader, 32) == b"denied"
        finally:
            os.close(reader)
            _, status = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        assert tx.lookup(record.namespace) == record


def test_deadline_after_checkpoint_execute_retires_cursor_even_while_error_is_retained(
    tmp_path, monkeypatch
):
    import gc

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        scope.acquire(deadline=time.monotonic() + 2)
        store = metadata(tmp_path, runs)
        store.open(conversation=scope, deadline=time.monotonic() + 2)
        tx = store.transaction(conversation=scope)
        original_execute, original_remaining = tx._execute, tx._remaining
        checkpoint = [False, 0]
        rejection = None

        def execute(sql, parameters=()):
            checkpoint[:] = [sql == "PRAGMA wal_checkpoint(TRUNCATE)", 0]
            try:
                return original_execute(sql, parameters)
            finally:
                checkpoint[0] = False

        def remaining():
            if checkpoint[0]:
                checkpoint[1] += 1
                if checkpoint[1] == 2:
                    raise ReservationError("reservation_unavailable")
            return original_remaining()

        try:
            with monkeypatch.context() as patch:
                patch.setattr(tx, "_execute", execute)
                patch.setattr(tx, "_remaining", remaining)
                try:
                    tx.acquire(deadline=time.monotonic() + 2)
                except ReservationError as error:
                    rejection = error
            assert rejection is not None
            # Keep the admission traceback alive: cursor retirement must not
            # depend on exception garbage collection or logging behavior.
            tx.retire()
            assert tx._db is None and scope._source_owner is None
        finally:
            rejection = None
            gc.collect()  # Explicitly release failed-probe traceback before retry.
            tx.retire()
            store.close()


def test_conversation_deadline_cursor_cannot_keep_closed_connection_alive(
    tmp_path, monkeypatch
):
    import gc
    import subprocess
    import sys

    with owned_conversation(tmp_path) as (runs, _, _, _, scope):
        clock = [100]
        scope._monotonic = lambda: clock[0]
        cursors = []
        real_connect = sqlite3.connect
        rejection = None

        class CaptureCheckpoint(sqlite3.Connection):
            def execute(self, sql, *args):
                cursor = super().execute(sql, *args)
                if sql == "PRAGMA journal_mode=WAL":
                    cursors.append(cursor)
                    clock[0] = 102
                return cursor

        def connect(path, *args, **kwargs):
            if str(runs.path) in str(path):
                kwargs["factory"] = CaptureCheckpoint
            return real_connect(path, *args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(sqlite3, "connect", connect)
                try:
                    scope.acquire(deadline=102)
                except RuntimeError as error:
                    rejection = error
            assert rejection is not None and len(cursors) == 1
            scope.retire()
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    """
import errno, fcntl, os, sys
try:
    fd = os.open(sys.argv[1], os.O_RDWR)
except FileNotFoundError:
    print('retired')
else:
    try:
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 128, os.SEEK_SET)
        except OSError as error:
            assert error.errno in (errno.EAGAIN, errno.EACCES)
            print('held')
        else:
            print('retired')
    finally:
        os.close(fd)
""",
                    str(runs.path) + "-shm",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == "retired", (
                "unfinalized cursor retained SQLite DMS after Python close"
            )
        finally:
            cursors.clear()
            rejection = None
            gc.collect()
            scope.retire()


@contextmanager
def cursor_owner(tmp_path, kind):
    if kind == "source":
        with snapshot_transaction(tmp_path) as (tx, _, _, _):
            yield tx
    else:
        with owned_conversation(tmp_path) as (_, _, _, _, scope):
            scope.acquire(deadline=time.monotonic() + 2)
            yield scope


@pytest.mark.parametrize("kind", ["source", "conversation"])
@pytest.mark.parametrize("after_effect", [False, True])
def test_pending_cursor_close_fault_retains_original_scope_until_explicit_retry(
    tmp_path, monkeypatch, kind, after_effect
):
    with cursor_owner(tmp_path, kind) as owner:
        original_remaining = owner._remaining
        calls = [0]
        expected_error = ReservationError if kind == "source" else RuntimeError
        rejection = None

        def remaining():
            calls[0] += 1
            if calls[0] == 2:
                if kind == "source":
                    raise ReservationError("reservation_unavailable")
                raise RuntimeError("Source conversation is unavailable.")
            return original_remaining()

        with monkeypatch.context() as patch:
            patch.setattr(owner, "_remaining", remaining)
            try:
                owner._execute("SELECT 1")
            except expected_error as error:
                rejection = error
        assert rejection is not None
        assert isinstance(owner._pending_cursor, sqlite3.Cursor)
        original_close = owner._close_pending_cursor

        def close():
            if after_effect:
                original_close()
            raise OSError("PRIVATE_CURSOR_CLOSE_CANARY")

        with monkeypatch.context() as patch:
            patch.setattr(owner, "_close_pending_cursor", close)
            with pytest.raises(expected_error) as error:
                owner.retire()
        assert "PRIVATE_" not in str(error.value)
        assert not owner._retired and owner._db is not None
        assert (owner._pending_cursor is None) is after_effect
        if kind == "source":
            assert owner._conversation._source_owner is owner
        owner.retire()
        assert owner._pending_cursor is None and owner._db is None


def test_cleanup_checkpoint_cursor_is_retained_after_control_flow_interruption(
    tmp_path, monkeypatch
):
    import gc

    class Interrupted(BaseException):
        pass

    with snapshot_transaction(tmp_path) as (tx, _, _, _):
        original = tx._cleanup_execute
        rejection = None

        def execute(sql):
            cursor = original(sql)
            if sql == "PRAGMA wal_checkpoint(TRUNCATE)":
                raise Interrupted()
            return cursor

        try:
            with monkeypatch.context() as patch:
                patch.setattr(tx, "_cleanup_execute", execute)
                try:
                    tx.retire()
                except Interrupted as error:
                    rejection = error
            assert rejection is not None and tx._db is not None
            assert tx._conversation._source_owner is tx
            tx.retire()
            assert tx._db is None and tx._conversation._source_owner is None
        finally:
            rejection = None
            gc.collect()
            tx.retire()
