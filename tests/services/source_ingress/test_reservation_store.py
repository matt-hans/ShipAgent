"""Private metadata persistence requires explicit commit, not source admission."""

import importlib
import importlib.util
import json
import sqlite3
import time
from contextlib import contextmanager, suppress
from dataclasses import asdict

import pytest

from src.services.source_ingress.reservation_contracts import (
    ReservationError,
    ReservationNamespace,
    ReservationRequest,
)


def implementation():
    name = "src.services.source_ingress.reservation_store"
    assert importlib.util.find_spec(name) is not None, "reservation store is absent"
    return importlib.import_module(name)


def new_store(tmp_path):
    store = implementation().ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    store.open(deadline=time.monotonic() + 2)
    return store


def namespace(key="request-a"):
    return ReservationNamespace(
        account_id="account-a",
        provider_connection_id="connection-a",
        link_epoch="epoch-a",
        conversation_reference="sa_conversation_" + "a" * 32,
        execution_target_id="target-a",
        target_fingerprint="fingerprint-a",
        request_key=key,
    )


def request(key="request-a", **overrides):
    values = {"request_key": key, "content_length": 12, "content_sha256": "b" * 64}
    values.update(overrides)
    return ReservationRequest(**values)


@contextmanager
def transaction(store):
    tx = store.transaction()
    try:
        tx.acquire(deadline=time.monotonic() + 2)
        yield tx
    finally:
        tx.retire()


def insert(tx, key="request-a", *, now=100, **overrides):
    values = {
        "admitted_revision": 1,
        "admitted_at": now,
        "upload_expires_at": now + 300,
        "prospective_source_expires_at": now + 86400,
    }
    values.update(overrides)
    return tx.insert(namespace(key), request(key), **values)


def test_explicit_commit_reopens_same_private_identity_and_original_times(tmp_path):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        first = insert(tx)
        receipt = first.to_receipt()
        assert len(receipt.reservation_id) == 32
        assert not receipt.reservation_id.startswith("sa_")
        assert set(asdict(receipt)) == {
            "reservation_id",
            "status",
            "admitted_at",
            "upload_expires_at",
            "prospective_source_expires_at",
        }
        tx.commit()
    reopened = implementation().ReservationStore(
        store.path, account_id="account-a", execution_target_id="target-a"
    )
    reopened.open(deadline=time.monotonic() + 2)
    with transaction(reopened) as tx:
        assert tx.lookup(namespace()).to_receipt() == receipt
        assert insert(tx, now=150).to_receipt() == receipt
        tx.commit()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1


def test_retirement_without_commit_rolls_back_and_scope_cannot_be_reused(tmp_path):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        insert(tx)
    with transaction(store) as fresh:
        assert fresh.lookup(namespace()) is None
    with pytest.raises(ReservationError):
        tx.lookup(namespace())
    with pytest.raises(ReservationError):
        tx.commit()
    with pytest.raises(ReservationError):
        tx.acquire(deadline=time.monotonic() + 2)


def test_conflict_leaves_first_record_and_capacity_unchanged(tmp_path):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        first = insert(tx)
        tx.commit()
    with transaction(store) as tx:
        with pytest.raises(ReservationError) as caught:
            tx.insert(
                namespace(),
                request(content_length=13),
                admitted_revision=1,
                admitted_at=150,
                upload_expires_at=450,
                prospective_source_expires_at=86550,
            )
        assert caught.value.code == "request_conflict"
        assert tx.lookup(namespace()).to_receipt() == first.to_receipt()


def test_two_live_reservations_cap_but_identical_recovery_precedes_cap(tmp_path):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        first = insert(tx, "one")
        insert(tx, "two")
        assert insert(tx, "one").to_receipt() == first.to_receipt()
        with pytest.raises(ReservationError) as caught:
            insert(tx, "three")
        assert caught.value.code == "source_limit_exceeded"
        tx.commit()
    with transaction(store) as tx:
        insert(tx, "three", now=400)
        tx.commit()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 3


def test_logical_accounting_is_encoded_metadata_not_sqlite_file_size(tmp_path):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        insert(tx)
        tx.commit()
    with sqlite3.connect(store.path) as db:
        row = db.execute(
            "SELECT reservation_id, namespace_digest, input_digest, payload, metadata_bytes FROM reservations"
        ).fetchone()
    expected = sum(len(value.encode("utf-8")) for value in row[:4]) + 16
    assert row[4] == expected
    assert row[3] == json.dumps(
        json.loads(row[3]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    assert store.path.stat().st_size > expected


@pytest.mark.parametrize("bad_count", [-1, 0, 1, 8193])
def test_corrupt_accounting_is_unavailable_before_another_admission(
    tmp_path, bad_count
):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        insert(tx)
        tx.commit()
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE reservations SET metadata_bytes = ?", (bad_count,))
    with pytest.raises(ReservationError) as caught:
        with transaction(store) as tx:
            insert(tx, "new")
    assert caught.value.code == "reservation_unavailable"


def test_open_requires_existing_owned_store_and_never_rewrites_foreign_format(tmp_path):
    module = implementation()
    with pytest.raises(ReservationError):
        module.ReservationStore(
            tmp_path / "missing.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
        ).open(deadline=time.monotonic() + 2)
    assert not (tmp_path / "missing.sqlite3").exists()
    store = new_store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA application_id=1")
        db.execute("PRAGMA journal_mode=DELETE")
    with pytest.raises(ReservationError):
        module.ReservationStore(
            store.path, account_id="account-a", execution_target_id="target-a"
        ).open(deadline=time.monotonic() + 2)
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert db.execute("PRAGMA application_id").fetchone()[0] == 1


def test_close_after_effect_failure_can_retire_again_without_losing_commit_evidence(
    tmp_path, monkeypatch
):
    store = new_store(tmp_path)
    real_connect = sqlite3.connect

    class FaultyClose(sqlite3.Connection):
        failed_once = False

        def close(self):
            super().close()
            if not self.failed_once:
                self.failed_once = True
                raise OSError("PRIVATE_CLOSE_CANARY")

    def connect(*args, **kwargs):
        return real_connect(*args, **kwargs, factory=FaultyClose)

    tx = store.transaction()
    try:
        with monkeypatch.context() as fault:
            fault.setattr(sqlite3, "connect", connect)
            tx.acquire(deadline=time.monotonic() + 2)
        insert(tx)
        assert not tx.committed
        tx.commit()
        with pytest.raises(ReservationError) as caught:
            tx.retire()
        assert "PRIVATE_" not in str(caught.value)
        assert tx.committed
        tx.retire()
        assert tx.committed
    finally:
        with suppress(ReservationError):
            tx.retire()


@pytest.mark.parametrize("size", [9000, 50000])
@pytest.mark.parametrize(
    "column", ["payload", "reservation_id", "namespace_digest", "input_digest"]
)
def test_oversized_stored_field_is_rejected_before_json_decode(
    tmp_path, monkeypatch, size, column
):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        insert(tx)
        tx.commit()
    with sqlite3.connect(store.path) as db:
        # Column is a closed test parameter, never an external SQL input.
        db.execute(f"UPDATE reservations SET {column}=?", ("x" * size,))
    parsed = []

    def forbidden_decode(value):
        parsed.append(True)
        raise AssertionError("oversized metadata reached JSON decoding")

    with monkeypatch.context() as guard:
        guard.setattr(implementation().json, "loads", forbidden_decode)
        with pytest.raises(ReservationError) as caught:
            with transaction(store) as tx:
                tx.lookup(namespace())
    assert caught.value.code == "reservation_unavailable"
    assert parsed == []


@pytest.mark.parametrize(
    "corruption", ["extra", "duplicate", "version", "input", "namespace"]
)
def test_noncanonical_or_unknown_payload_fields_fail_closed(tmp_path, corruption):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        insert(tx)
        tx.commit()
    with sqlite3.connect(store.path) as db:
        row = db.execute(
            "SELECT payload,reservation_id,namespace_digest,input_digest FROM reservations"
        ).fetchone()
        decoded = json.loads(row[0])
        if corruption == "extra":
            decoded["PRIVATE_FIELD_CANARY"] = "PRIVATE_VALUE_CANARY"
        elif corruption == "version":
            decoded["version"] = 2
        elif corruption == "input":
            decoded["input"]["content_length"] = True
        elif corruption == "namespace":
            decoded["namespace"]["link_epoch"] = None
        payload = implementation().canonical_json(decoded)
        if corruption == "duplicate":
            payload = payload[:-1] + ',"version":1}'
        size = implementation().metadata_size(payload, *row[1:])
        db.execute(
            "UPDATE reservations SET payload=?,metadata_bytes=?", (payload, size)
        )
    with pytest.raises(ReservationError) as caught:
        with transaction(store) as tx:
            tx.lookup(namespace())
    assert caught.value.code == "reservation_unavailable"
    assert "PRIVATE_" not in str(caught.value) + repr(caught.value)


def test_retained_count_includes_expired_records_without_recycling(
    tmp_path, monkeypatch
):
    module = implementation()
    assert module.MAX_RETAINED_RECORDS == 1024
    monkeypatch.setattr(module, "MAX_RETAINED_RECORDS", 2)
    store = new_store(tmp_path)
    with transaction(store) as tx:
        first = insert(tx, "one")
        insert(tx, "two")
        tx.commit()
    with transaction(store) as tx:
        # Storage can describe history; only the future authority coordinator
        # may return an authorized live reservation or a fixed expired outcome.
        assert insert(tx, "one", now=400).to_receipt() == first.to_receipt()
        with pytest.raises(ReservationError) as caught:
            insert(tx, "three", now=400)
        assert caught.value.code == "source_limit_exceeded"


def test_total_metadata_boundary_counts_owner_and_all_expired_record_bytes(
    tmp_path, monkeypatch
):
    module = implementation()
    assert module.MAX_METADATA_BYTES == 4 * 1024 * 1024
    store = new_store(tmp_path)
    with transaction(store) as tx:
        insert(tx, "one")
        tx.commit()
    with sqlite3.connect(store.path) as db:
        row_bytes = db.execute("SELECT metadata_bytes FROM reservations").fetchone()[0]
    owner_bytes = 16 + len(b"account-a") + len(b"target-a")
    monkeypatch.setattr(module, "MAX_METADATA_BYTES", owner_bytes + 2 * row_bytes)
    with transaction(store) as tx:
        insert(tx, "two")
        tx.commit()
    with transaction(store) as tx:
        with pytest.raises(ReservationError) as caught:
            insert(tx, "six", now=400)
        assert caught.value.code == "source_limit_exceeded"


def test_record_byte_bound_is_checked_before_insertion(tmp_path, monkeypatch):
    module = implementation()
    assert module.MAX_RECORD_BYTES == 8192
    store = new_store(tmp_path)
    monkeypatch.setattr(module, "MAX_RECORD_BYTES", 100)
    with transaction(store) as tx:
        with pytest.raises(ReservationError) as caught:
            insert(tx)
        assert caught.value.code == "source_limit_exceeded"
        assert tx.lookup(namespace()) is None


def test_sql_failure_is_closed_and_retirement_rolls_back(tmp_path):
    store = new_store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("""CREATE TRIGGER reject_reservation BEFORE INSERT ON reservations
            BEGIN SELECT RAISE(ABORT, 'PRIVATE_SQL_CANARY'); END""")
    with pytest.raises(ReservationError) as caught:
        with transaction(store) as tx:
            insert(tx)
            tx.commit()
    assert caught.value.code == "reservation_unavailable"
    assert "PRIVATE_" not in str(caught.value)
    with transaction(store) as tx:
        assert tx.lookup(namespace()) is None


def test_replaced_file_and_foreign_owner_are_unavailable(tmp_path):
    store = new_store(tmp_path)
    with pytest.raises(ReservationError):
        implementation().ReservationStore(
            store.path, account_id="another-account", execution_target_id="target-a"
        ).open(deadline=time.monotonic() + 2)
    store.path.rename(tmp_path / "retired.sqlite3")
    with pytest.raises(ReservationError):
        with transaction(store):
            pass
    assert not store.path.exists()


def test_writer_wait_uses_operation_deadline_and_partial_scope_retires(tmp_path):
    store = new_store(tmp_path)
    blocker = sqlite3.connect(store.path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    tx = store.transaction()
    try:
        started = time.monotonic()
        with pytest.raises(ReservationError) as caught:
            tx.acquire(deadline=started + 0.08)
        assert caught.value.code == "reservation_unavailable"
        assert time.monotonic() - started < 0.75
        tx.retire()
    finally:
        tx.retire()
        blocker.rollback()
        blocker.close()


def test_expired_deadline_blocks_commit_but_does_not_block_rollback(tmp_path):
    store = new_store(tmp_path)
    clock = [100.0]
    tx = store.transaction(monotonic=lambda: clock[0])
    try:
        tx.acquire(deadline=102)
        insert(tx)
        clock[0] = 102
        with pytest.raises(ReservationError):
            tx.commit()
        assert not tx.committed
    finally:
        tx.retire()
    with transaction(store) as fresh:
        assert fresh.lookup(namespace()) is None


@pytest.mark.parametrize("bad_deadline", [True, float("nan"), float("inf")])
def test_invalid_deadline_does_not_open_or_mutate_store(tmp_path, bad_deadline):
    store = new_store(tmp_path)
    tx = store.transaction()
    try:
        with pytest.raises(ReservationError):
            tx.acquire(deadline=bad_deadline)
        assert not tx.committed
    finally:
        tx.retire()
    with transaction(store) as fresh:
        assert fresh.lookup(namespace()) is None


def test_constructor_allocates_without_io_and_open_is_explicit_single_attempt(tmp_path):
    path = tmp_path / "not-created" / "sources.sqlite3"
    store = implementation().ReservationStore(
        path, account_id="account-a", execution_target_id="target-a", create=True
    )
    assert not path.parent.exists()
    with pytest.raises(ReservationError):
        store.transaction()
    with pytest.raises(ReservationError):
        store.open(deadline=time.monotonic() + 2)
    path.parent.mkdir(mode=0o700)
    with pytest.raises(ReservationError):
        store.open(deadline=time.monotonic() + 2)
    store.close()
    with pytest.raises(ReservationError):
        store.transaction()
    assert not path.exists()


def test_writer_acquisition_does_not_read_reservation_rows_before_authority(
    tmp_path, monkeypatch
):
    store = new_store(tmp_path)
    with transaction(store) as tx:
        first = insert(tx)
        tx.commit()
    original_execute = implementation().ReservationTransaction._execute
    queries = []

    def inspect_query(scope, sql, parameters=()):
        queries.append(sql)
        assert "FROM reservations" not in sql
        return original_execute(scope, sql, parameters)

    tx = store.transaction()
    try:
        with monkeypatch.context() as guard:
            guard.setattr(
                implementation().ReservationTransaction, "_execute", inspect_query
            )
            reopened = implementation().ReservationStore(
                store.path, account_id="account-a", execution_target_id="target-a"
            )
            reopened.open(deadline=time.monotonic() + 2)
            reopened.close()
            tx.acquire(deadline=time.monotonic() + 2)
        assert queries
        assert tx.lookup(namespace()).to_receipt() == first.to_receipt()
    finally:
        tx.retire()


@pytest.mark.parametrize("effect", ["before", "after"])
def test_failed_setup_retirement_is_retained_for_explicit_close(
    tmp_path, monkeypatch, effect
):
    module = implementation()
    real_connect = sqlite3.connect
    captured = []

    class FaultyClose(sqlite3.Connection):
        fail_cleanup = True

        def close(self):
            if not self.fail_cleanup or effect == "after":
                super().close()
            if self.fail_cleanup:
                raise OSError("PRIVATE_SETUP_CLEANUP_CANARY")

    def connect(*args, **kwargs):
        db = real_connect(*args, factory=FaultyClose, **kwargs)
        captured.append(db)
        return db

    store = module.ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    try:
        with monkeypatch.context() as fault:
            fault.setattr(sqlite3, "connect", connect)
            with pytest.raises(ReservationError) as caught:
                store.open(deadline=time.monotonic() + 2)
        assert "PRIVATE_" not in str(caught.value) + repr(caught.value)
        assert store.initialization_committed
        assert len(captured) == 1
        with pytest.raises(ReservationError):
            store.transaction()
        with pytest.raises(ReservationError):
            store.open(deadline=time.monotonic() + 2)
        with pytest.raises(ReservationError):
            store.close()
        captured[0].fail_cleanup = False
        store.close()
        store.close()
        assert store.initialization_committed
        with pytest.raises(ReservationError):
            store.transaction()
        with pytest.raises(sqlite3.ProgrammingError):
            captured[0].execute("SELECT 1")
        reopened = module.ReservationStore(
            store.path, account_id="account-a", execution_target_id="target-a"
        )
        reopened.open(deadline=time.monotonic() + 2)
        with transaction(reopened) as tx:
            assert tx.lookup(namespace()) is None
        reopened.close()
    finally:
        for db in captured:
            db.fail_cleanup = False
            with suppress(sqlite3.ProgrammingError):
                db.close()


def test_store_close_does_not_reclaim_handed_out_transaction(tmp_path):
    store = new_store(tmp_path)
    tx = store.transaction()
    try:
        tx.acquire(deadline=time.monotonic() + 2)
        first = insert(tx)
        store.close()
        assert tx.lookup(namespace()).to_receipt() == first.to_receipt()
        tx.commit()
        with pytest.raises(ReservationError):
            store.transaction()
    finally:
        tx.retire()


def test_failed_open_retains_setup_writer_until_explicit_successful_close(
    tmp_path, monkeypatch
):
    original = new_store(tmp_path)
    store = implementation().ReservationStore(
        original.path, account_id="account-a", execution_target_id="target-a"
    )
    real_connect = sqlite3.connect
    captured = []

    class FaultyRollback(sqlite3.Connection):
        fail_cleanup = True

        def rollback(self):
            if self.fail_cleanup:
                raise OSError("PRIVATE_ROLLBACK_CANARY")
            return super().rollback()

    def connect(*args, **kwargs):
        db = real_connect(*args, factory=FaultyRollback, **kwargs)
        captured.append(db)
        return db

    try:
        with monkeypatch.context() as fault:
            fault.setattr(sqlite3, "connect", connect)
            with pytest.raises(ReservationError) as caught:
                store.open(deadline=time.monotonic() + 2)
        assert "PRIVATE_" not in str(caught.value)
        assert not store.initialization_committed
        assert len(captured) == 1 and captured[0].in_transaction
        with sqlite3.connect(store.path, timeout=0.01) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("BEGIN IMMEDIATE")
        with pytest.raises(ReservationError):
            store.close()
        with pytest.raises(ReservationError):
            store.transaction()
        captured[0].fail_cleanup = False
        store.close()
        with pytest.raises(sqlite3.ProgrammingError):
            captured[0].execute("SELECT 1")
        with sqlite3.connect(store.path, timeout=0.01) as competing:
            competing.execute("BEGIN IMMEDIATE")
            competing.rollback()
        with pytest.raises(ReservationError):
            store.open(deadline=time.monotonic() + 2)
    finally:
        for db in captured:
            db.fail_cleanup = False
            with suppress(sqlite3.ProgrammingError):
                db.rollback()
                db.close()


def test_open_checks_deadline_after_setup_cleanup_without_erasing_commit(
    tmp_path, monkeypatch
):
    module = implementation()
    clock = [100.0]
    store = module.ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    original_retire = module.ReservationTransaction.retire

    def delayed_retire(scope):
        original_retire(scope)
        clock[0] = 102.0

    with monkeypatch.context() as fault:
        fault.setattr(module.ReservationTransaction, "retire", delayed_retire)
        with pytest.raises(ReservationError):
            store.open(deadline=102, monotonic=lambda: clock[0])
    assert store.initialization_committed
    with pytest.raises(ReservationError):
        store.transaction()
    store.close()
    reopened = module.ReservationStore(
        store.path, account_id="account-a", execution_target_id="target-a"
    )
    reopened.open(deadline=time.monotonic() + 2)
    with transaction(reopened) as tx:
        assert tx.lookup(namespace()) is None
    reopened.close()


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), 100])
def test_invalid_or_elapsed_open_deadline_never_creates_a_file(tmp_path, deadline):
    store = implementation().ReservationStore(
        tmp_path / "sources.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )
    with pytest.raises(ReservationError):
        store.open(deadline=deadline, monotonic=lambda: 100)
    assert not store.path.exists()
    assert not store.initialization_committed
    store.close()
