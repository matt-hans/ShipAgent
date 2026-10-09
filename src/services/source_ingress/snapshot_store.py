"""Fixed V2 metadata; every action uses the caller's already held transaction.

This adapter verifies metadata consistency, not bytes, receiver retirement or
operator authority. Complete rows remain cleanup-pending until the later real
receiver owner can supply attempt-bound retirement proof. No private ID is a
public Source Reference or an upload capability.
"""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from functools import wraps
from types import MappingProxyType

from src.services.source_ingress.reservation_contracts import ReservationError
from src.services.source_ingress.snapshot_contracts import (
    MAX_COMPLETED_SNAPSHOTS,
    MAX_CONTENT_BYTES,
    MAX_LIFECYCLE_BYTES,
    MAX_MANIFEST_BYTES,
    RESERVED_CONTENT_BYTES,
    SnapshotLifecycle,
    SnapshotManifest,
    require_private_id,
)

V2_TABLES = {
    "source_lifecycle": """CREATE TABLE source_lifecycle (
        reservation_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        metadata_bytes INTEGER NOT NULL)""",
    "snapshot_manifests": """CREATE TABLE snapshot_manifests (
        snapshot_id TEXT PRIMARY KEY,
        reservation_id TEXT NOT NULL UNIQUE,
        payload TEXT NOT NULL,
        metadata_bytes INTEGER NOT NULL)""",
}


@dataclass(frozen=True, slots=True, repr=False)
class SnapshotInventory:
    lifecycles: Mapping[str, SnapshotLifecycle]
    manifests: Mapping[str, SnapshotManifest]
    metadata_bytes: int
    content_bytes: int
    incomplete_count: int
    completed_count: int


def _unavailable() -> ReservationError:
    return ReservationError("reservation_unavailable")


def _closed_errors(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ReservationError:
            raise
        except Exception:
            raise _unavailable() from None

    return call


def _now(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise _unavailable()


def _encode(item) -> str:
    from src.services.source_ingress.reservation_store import canonical_json

    return canonical_json(asdict(item))


def _decode(payload, model):
    from src.services.source_ingress.reservation_store import canonical_json

    data = json.loads(payload)
    if (
        type(data) is not dict
        or set(data) != {field.name for field in fields(model)}
        or canonical_json(data) != payload
    ):
        raise _unavailable()
    for name in ("raw_identity", "normalized_identity"):
        if data[name] is not None:
            if type(data[name]) is not list:
                raise _unavailable()
            data[name] = tuple(data[name])
    return model(**data)


def _matches(manifest, lifecycle, record) -> bool:
    return (
        manifest.reservation_id
        == lifecycle.reservation_id
        == record.receipt.reservation_id
        and manifest.attempt_id == lifecycle.attempt_id
        and manifest.generation == lifecycle.generation
        and manifest.raw_identity == lifecycle.raw_identity
        and manifest.normalized_identity == lifecycle.normalized_identity
        and manifest.raw_length == record.request.content_length
        and manifest.raw_content_sha256 == record.request.content_sha256
        and manifest.parser_profile == record.request.parser_profile
        and manifest.source_expires_at == record.receipt.prospective_source_expires_at
    )


class SnapshotTransaction:
    """Metadata-only adapter. The fenced caller owns COMMIT and retirement."""

    def __init__(self, transaction) -> None:
        self._tx = transaction

    def inventory(self, *, now: float) -> SnapshotInventory:
        records, base_bytes = self._tx._records(_include_snapshots=False)
        return self._read_metadata(records, base_bytes, now=now)

    def _bounded_rows(self, table, model, cap, payload_cap):
        # All SQL identifiers originate in this closed module, never a request.
        identifiers = (
            "reservation_id"
            if table == "source_lifecycle"
            else "snapshot_id, reservation_id"
        )
        checks = ", ".join(
            f"typeof({name}), length(CAST({name} AS BLOB))"
            for name in identifiers.split(", ")
        )
        sizes = self._tx._execute(
            f"SELECT rowid, {checks}, typeof(payload), length(CAST(payload AS BLOB)), "
            f"typeof(metadata_bytes), metadata_bytes FROM {table} LIMIT ?",
            (cap + 1,),
        ).fetchall()
        if len(sizes) > cap:
            raise _unavailable()
        result = []
        total = 0
        count = 1 if table == "source_lifecycle" else 2
        for size in sizes:
            if (
                any(
                    size[1 + 2 * i] != "text" or size[2 + 2 * i] != 32
                    for i in range(count)
                )
                or size[-4] != "text"
                or not 0 < size[-3] <= payload_cap
                or size[-2] != "integer"
                or size[-1] != 32 * count + size[-3] + 8
            ):
                raise _unavailable()
            values = self._tx._execute(
                f"SELECT {identifiers}, payload FROM {table} WHERE rowid=?", (size[0],)
            ).fetchone()
            item = _decode(values[-1], model)
            if item.reservation_id != values[count - 1] or (
                count == 2 and item.snapshot_id != values[0]
            ):
                raise _unavailable()
            result.append(item)
            total += size[-1]
        return result, total

    def _read_metadata(
        self, records, base_bytes: int, *, now: float
    ) -> SnapshotInventory:
        from src.services.source_ingress.reservation_store import (
            MAX_METADATA_BYTES,
            MAX_RETAINED_RECORDS,
        )

        try:
            _now(now)
            if self._tx._verify_format() != 2:
                raise _unavailable()
            by_id = {record.receipt.reservation_id: record for record in records}
            lifecycle_rows, lifecycle_bytes = self._bounded_rows(
                "source_lifecycle",
                SnapshotLifecycle,
                MAX_RETAINED_RECORDS,
                MAX_LIFECYCLE_BYTES,
            )
            manifest_rows, manifest_bytes = self._bounded_rows(
                "snapshot_manifests",
                SnapshotManifest,
                MAX_COMPLETED_SNAPSHOTS,
                MAX_MANIFEST_BYTES,
            )
            lifecycles = {}
            attempts, identities = set(), set()
            for item in lifecycle_rows:
                record = by_id.get(item.reservation_id)
                if (
                    record is None
                    or item.attempt_id in attempts
                    or not item.cleanup_pending
                    and item.state not in {"complete", "failed"}
                    or not record.receipt.admitted_at
                    < item.authorization_expires_at
                    <= record.receipt.upload_expires_at
                ):
                    raise _unavailable()
                attempts.add(item.attempt_id)
                for identity in (item.raw_identity, item.normalized_identity):
                    if identity is not None:
                        if identity in identities:
                            raise _unavailable()
                        identities.add(identity)
                lifecycles[item.reservation_id] = item
            manifests = {}
            completed = set()
            for item in manifest_rows:
                lifecycle = lifecycles.get(item.reservation_id)
                if (
                    lifecycle is None
                    or lifecycle.state != "complete"
                    or item.reservation_id in completed
                    or not _matches(item, lifecycle, by_id[item.reservation_id])
                ):
                    raise _unavailable()
                completed.add(item.reservation_id)
                manifests[item.snapshot_id] = item
            if completed != {
                key for key, item in lifecycles.items() if item.state == "complete"
            }:
                raise _unavailable()
            used = base_bytes + lifecycle_bytes + manifest_bytes
            pending = sum(item.cleanup_pending for item in lifecycles.values())
            by_reservation = {item.reservation_id: item for item in manifests.values()}
            content = sum(
                item.reserved_content_bytes
                if item.cleanup_pending
                else (
                    by_reservation[item.reservation_id].raw_length
                    + by_reservation[item.reservation_id].normalized_length
                    if item.state == "complete"
                    else 0
                )
                for item in lifecycles.values()
            )
            if used > MAX_METADATA_BYTES or content > MAX_CONTENT_BYTES or pending > 2:
                raise _unavailable()
            incomplete = pending + sum(
                record.receipt.upload_expires_at > now
                for record in records
                if record.receipt.reservation_id not in lifecycles
            )
            return SnapshotInventory(
                MappingProxyType(lifecycles),
                MappingProxyType(manifests),
                used,
                content,
                incomplete,
                len(manifests),
            )
        except Exception:
            raise _unavailable() from None

    def lookup_lifecycle(self, record) -> SnapshotLifecycle | None:
        inventory = self.inventory(now=0)
        if self._tx.lookup(record.namespace) != record:
            raise _unavailable()
        return inventory.lifecycles.get(record.receipt.reservation_id)

    @_closed_errors
    def claim(
        self, record, *, generation: int, authorization_expires_at: int, now: float
    ) -> SnapshotLifecycle:
        from src.services.source_ingress.reservation_store import MAX_METADATA_BYTES

        _now(now)
        inventory = self.inventory(now=now)
        if (
            self._tx.lookup(record.namespace) != record
            or record.receipt.reservation_id in inventory.lifecycles
            or type(generation) is not int
            or generation != self._tx._conversation._generation
            or type(authorization_expires_at) is not int
            or now >= min(authorization_expires_at, record.receipt.upload_expires_at)
        ):
            raise _unavailable()
        attempt = secrets.token_hex(16)
        if any(item.attempt_id == attempt for item in inventory.lifecycles.values()):
            raise _unavailable()
        item = SnapshotLifecycle(
            reservation_id=record.receipt.reservation_id,
            attempt_id=attempt,
            generation=generation,
            state="receiving",
            authorization_expires_at=min(
                authorization_expires_at, record.receipt.upload_expires_at
            ),
            reserved_content_bytes=RESERVED_CONTENT_BYTES,
            raw_basename=attempt + ".raw",
            normalized_basename=attempt + ".normalized",
        )
        payload = _encode(item)
        size = len(payload.encode()) + 40
        if (
            len(payload.encode()) > MAX_LIFECYCLE_BYTES
            or inventory.metadata_bytes + size > MAX_METADATA_BYTES
            or inventory.content_bytes + RESERVED_CONTENT_BYTES > MAX_CONTENT_BYTES
            or inventory.incomplete_count > 2
            or inventory.completed_count >= MAX_COMPLETED_SNAPSHOTS
        ):
            raise ReservationError("source_limit_exceeded")
        self._tx._execute(
            "INSERT INTO source_lifecycle VALUES(?,?,?)",
            (item.reservation_id, payload, size),
        )
        return item

    def _current(self, attempt):
        if (
            type(attempt) is not SnapshotLifecycle
            or attempt.generation != self._tx._conversation._generation
        ):
            raise _unavailable()
        inventory = self.inventory(now=0)
        if inventory.lifecycles.get(attempt.reservation_id) != attempt:
            raise _unavailable()
        return inventory

    def _replace(self, attempt, updated, inventory):
        from src.services.source_ingress.reservation_store import MAX_METADATA_BYTES

        payload = _encode(updated)
        if (
            len(payload.encode()) > MAX_LIFECYCLE_BYTES
            or inventory.metadata_bytes
            - len(_encode(attempt).encode())
            + len(payload.encode())
            > MAX_METADATA_BYTES
        ):
            raise ReservationError("source_limit_exceeded")
        self._tx._execute(
            "UPDATE source_lifecycle SET payload=?,metadata_bytes=? WHERE reservation_id=?",
            (payload, len(payload.encode()) + 40, attempt.reservation_id),
        )
        return updated

    @_closed_errors
    def record_files(self, attempt, *, identities):
        inventory = self._current(attempt)
        if (
            attempt.state != "receiving"
            or attempt.raw_identity is not None
            or attempt.normalized_identity is not None
            or type(identities) is not tuple
            or len(identities) != 2
        ):
            raise _unavailable()
        updated = replace(
            attempt, raw_identity=identities[0], normalized_identity=identities[1]
        )
        if updated.raw_identity is None or updated.normalized_identity is None:
            raise _unavailable()
        if any(
            identity in (item.raw_identity, item.normalized_identity)
            for item in inventory.lifecycles.values()
            for identity in identities
        ):
            raise _unavailable()
        return self._replace(attempt, updated, inventory)

    @_closed_errors
    def set_phase(self, attempt, *, expected, state):
        inventory = self._current(attempt)
        if (
            type(expected) is not str
            or type(state) is not str
            or (expected, state)
            not in {
                ("receiving", "sealed"),
                ("sealed", "parsing"),
                ("parsing", "staged"),
            }
            or attempt.state != expected
        ):
            raise _unavailable()
        return self._replace(attempt, replace(attempt, state=state), inventory)

    @_closed_errors
    def complete(self, attempt, manifest):
        from src.services.source_ingress.reservation_store import MAX_METADATA_BYTES

        inventory = self._current(attempt)
        records, _ = self._tx._records(_include_snapshots=False)
        record = next(
            item
            for item in records
            if item.receipt.reservation_id == attempt.reservation_id
        )
        if (
            attempt.state != "staged"
            or type(manifest) is not SnapshotManifest
            or manifest.snapshot_id in inventory.manifests
            or not _matches(manifest, attempt, record)
        ):
            raise _unavailable()
        payload = _encode(manifest)
        updated = replace(attempt, state="complete")
        used = (
            inventory.metadata_bytes
            + len(payload.encode())
            + 72
            + len(_encode(updated).encode())
            - len(_encode(attempt).encode())
        )
        if (
            len(payload.encode()) > MAX_MANIFEST_BYTES
            or used > MAX_METADATA_BYTES
            or inventory.completed_count >= MAX_COMPLETED_SNAPSHOTS
        ):
            raise ReservationError("source_limit_exceeded")
        # Caller must roll back on any error. Neither statement grants visibility
        # outside this same still-uncommitted transaction.
        self._tx._execute(
            "INSERT INTO snapshot_manifests VALUES(?,?,?,?)",
            (
                manifest.snapshot_id,
                manifest.reservation_id,
                payload,
                len(payload.encode()) + 72,
            ),
        )
        return self._replace(attempt, updated, inventory)

    @_closed_errors
    def mark_failed(self, attempt, *, cleanup_complete):
        inventory = self._current(attempt)
        if cleanup_complete is not False or attempt.state in {"complete", "failed"}:
            raise _unavailable()
        return self._replace(attempt, replace(attempt, state="failed"), inventory)

    @_closed_errors
    def acknowledge_retirement(self, attempt, *, generation, retirement_proof):
        from src.services.source_ingress.snapshots import _RetirementProof

        inventory = self._current(attempt)
        if type(retirement_proof) is not _RetirementProof:
            raise _unavailable()
        retirement_proof.require(attempt, generation)
        if not attempt.cleanup_pending:
            return attempt
        return self._replace(
            attempt, replace(attempt, cleanup_pending=False), inventory
        )

    @_closed_errors
    def reconcile_retirement(self, attempt, *, proof):
        from src.services.source_ingress.source_store_owner import _StartupRecoveryProof

        if type(proof) is not _StartupRecoveryProof:
            raise _unavailable()
        proof.require(self._tx, attempt)
        inventory = self.inventory(now=0)
        if inventory.lifecycles.get(attempt.reservation_id) != attempt:
            raise _unavailable()
        return self._replace(
            attempt,
            replace(
                attempt,
                state="complete" if attempt.state == "complete" else "failed",
                cleanup_pending=False,
            ),
            inventory,
        )

    @_closed_errors
    def lookup_manifest(self, namespace, private_snapshot_id):
        require_private_id(private_snapshot_id)
        inventory = self.inventory(now=0)
        record = self._tx.lookup(namespace)
        manifest = inventory.manifests.get(private_snapshot_id)
        if (
            record is None
            or manifest is None
            or manifest.reservation_id != record.receipt.reservation_id
        ):
            raise _unavailable()
        return manifest
