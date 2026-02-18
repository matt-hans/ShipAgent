"""Centralized agent decision audit ledger service.

Canonical store is SQLite tables (agent_decision_runs + agent_decision_events).
Each write is mirrored to JSONL on a best-effort basis.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc

from src.db.connection import get_db_context
from src.db.models import (
    AgentDecisionActor,
    AgentDecisionEvent,
    AgentDecisionPhase,
    AgentDecisionRun,
    AgentDecisionRunStatus,
)
from src.services.audit_service import redact_sensitive
from src.services.decision_audit_context import get_decision_run_id

logger = logging.getLogger(__name__)

_DEFAULT_JSONL_PATH = "/app/data/agent-decision-log.jsonl"
_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_MAX_PAYLOAD_BYTES = 16384
_CLEANUP_INTERVAL_SECONDS = 3600

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|[A-Fa-f0-9]{24,})\b")

_cleanup_lock = threading.Lock()
_last_cleanup_at: float = 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "true" if default else "false").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redact_text(value: str) -> str:
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _TOKEN_RE.sub("[REDACTED_TOKEN]", redacted)
    return redacted


def _parse_int_env(name: str, default_value: int) -> int:
    raw = os.environ.get(name, str(default_value)).strip()
    try:
        parsed = int(raw)
    except ValueError:
        return default_value
    return max(1, parsed)


class _JSONLMirrorWriter:
    """Best-effort async buffered JSONL mirror writer."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._queue: queue.Queue[str] = queue.Queue(maxsize=4096)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def append(self, entry: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(_canonical_json(entry))
        except queue.Full:
            logger.warning("Agent decision JSONL mirror queue full; dropping entry")

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            batch = [item]
            while len(batch) < 100:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    for line in batch:
                        fh.write(line)
                        fh.write("\n")
            except Exception as exc:
                logger.warning("Failed writing decision JSONL mirror: %s", exc)


_writers: dict[str, _JSONLMirrorWriter] = {}
_writers_lock = threading.Lock()


def _jsonl_writer(path: Path) -> _JSONLMirrorWriter:
    key = str(path)
    with _writers_lock:
        writer = _writers.get(key)
        if writer is None:
            writer = _JSONLMirrorWriter(path)
            _writers[key] = writer
        return writer


class DecisionAuditService:
    """Service for writing/querying the centralized agent decision ledger."""

    @staticmethod
    def is_enabled() -> bool:
        return _env_bool("AGENT_AUDIT_ENABLED", True)

    @staticmethod
    def jsonl_path() -> Path:
        raw = os.environ.get("AGENT_AUDIT_JSONL_PATH", _DEFAULT_JSONL_PATH).strip()
        return Path(raw or _DEFAULT_JSONL_PATH)

    @staticmethod
    def max_payload_bytes() -> int:
        return _parse_int_env("AGENT_AUDIT_MAX_PAYLOAD_BYTES", _DEFAULT_MAX_PAYLOAD_BYTES)

    @staticmethod
    def retention_days() -> int:
        return _parse_int_env("AGENT_AUDIT_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS)

    @classmethod
    def _maybe_cleanup_retention(cls) -> None:
        global _last_cleanup_at
        now = time.monotonic()
        if now - _last_cleanup_at < _CLEANUP_INTERVAL_SECONDS:
            return
        with _cleanup_lock:
            if now - _last_cleanup_at < _CLEANUP_INTERVAL_SECONDS:
                return
            try:
                cls.cleanup_retention()
            except Exception as exc:
                logger.warning("Decision audit retention cleanup failed: %s", exc)
            _last_cleanup_at = time.monotonic()

    @classmethod
    def _mirror_append(cls, payload: dict[str, Any]) -> None:
        if not cls.is_enabled():
            return
        try:
            _jsonl_writer(cls.jsonl_path()).append(payload)
        except Exception as exc:
            logger.warning("Failed queueing decision mirror write: %s", exc)

    @classmethod
    def _prepare_payload(
        cls,
        payload: dict[str, Any] | None,
    ) -> tuple[str, str]:
        raw_payload = payload or {}
        payload_hash = _sha256_text(_canonical_json(raw_payload))
        redacted = redact_sensitive(raw_payload)
        redacted_json = _canonical_json(redacted)
        max_bytes = cls.max_payload_bytes()
        payload_bytes = len(redacted_json.encode("utf-8"))
        if payload_bytes <= max_bytes:
            return redacted_json, payload_hash

        clipped = redacted_json.encode("utf-8")[:max_bytes].decode(
            "utf-8", errors="ignore"
        )
        truncated_payload = {
            "truncated": True,
            "original_bytes": payload_bytes,
            "max_bytes": max_bytes,
            "preview": clipped,
        }
        return _canonical_json(truncated_payload), payload_hash

    @classmethod
    def start_run(
        cls,
        *,
        session_id: str | None,
        user_message: str,
        model: str | None,
        interactive_shipping: bool,
        source_signature: dict[str, Any] | None = None,
    ) -> str | None:
        if not cls.is_enabled():
            return None

        cls._maybe_cleanup_retention()

        now = _utc_now_iso()
        user_hash = _sha256_text(user_message)
        redacted_message = _redact_text(user_message)
        source_signature_json = (
            _canonical_json(redact_sensitive(source_signature))
            if source_signature is not None
            else None
        )
        try:
            with get_db_context() as db:
                try:
                    run = AgentDecisionRun(
                        session_id=session_id,
                        user_message_hash=user_hash,
                        user_message_redacted=redacted_message,
                        source_signature=source_signature_json,
                        status=AgentDecisionRunStatus.running.value,
                        model=model,
                        interactive_shipping=interactive_shipping,
                        started_at=now,
                    )
                    db.add(run)
                    db.flush()
                    run_id = run.id
                except Exception as exc:
                    logger.warning("Decision audit start_run failed: %s", exc)
                    return None
        except Exception as exc:
            logger.warning("Decision audit start_run failed before write: %s", exc)
            return None

        cls._mirror_append(
            {
                "record_type": "run",
                "timestamp": now,
                "run_id": run_id,
                "session_id": session_id,
                "status": AgentDecisionRunStatus.running.value,
                "model": model,
                "interactive_shipping": interactive_shipping,
                "user_message_hash": user_hash,
            }
        )
        return run_id

    @classmethod
    def update_run_source_signature(
        cls,
        run_id: str | None,
        source_signature: dict[str, Any] | None,
    ) -> None:
        if not cls.is_enabled() or not run_id:
            return
        signature_json = (
            _canonical_json(redact_sensitive(source_signature))
            if source_signature is not None
            else None
        )
        with get_db_context() as db:
            try:
                run = db.query(AgentDecisionRun).filter(AgentDecisionRun.id == run_id).first()
                if run is None:
                    return
                run.source_signature = signature_json
            except Exception as exc:
                logger.warning("Decision audit update_run_source_signature failed: %s", exc)

    @classmethod
    def set_run_job_id(cls, run_id: str | None, job_id: str | None) -> None:
        if not cls.is_enabled() or not run_id or not job_id:
            return
        with get_db_context() as db:
            try:
                run = db.query(AgentDecisionRun).filter(AgentDecisionRun.id == run_id).first()
                if run is None:
                    return
                run.job_id = job_id
            except Exception as exc:
                logger.warning("Decision audit set_run_job_id failed: %s", exc)

    @classmethod
    def complete_run(
        cls,
        run_id: str | None,
        *,
        status: AgentDecisionRunStatus | str,
        job_id: str | None = None,
    ) -> None:
        if not cls.is_enabled() or not run_id:
            return
        status_value = status.value if isinstance(status, AgentDecisionRunStatus) else status
        completed_at = _utc_now_iso()
        with get_db_context() as db:
            try:
                run = db.query(AgentDecisionRun).filter(AgentDecisionRun.id == run_id).first()
                if run is None:
                    return
                run.status = status_value
                run.completed_at = completed_at
                if job_id:
                    run.job_id = job_id
            except Exception as exc:
                logger.warning("Decision audit complete_run failed: %s", exc)
                return
        cls._mirror_append(
            {
                "record_type": "run_status",
                "timestamp": completed_at,
                "run_id": run_id,
                "status": status_value,
                "job_id": job_id,
            }
        )

    @classmethod
    def log_event(
        cls,
        *,
        run_id: str | None,
        phase: AgentDecisionPhase | str,
        event_name: str,
        actor: AgentDecisionActor | str,
        payload: dict[str, Any] | None = None,
        tool_name: str | None = None,
        latency_ms: int | None = None,
    ) -> str | None:
        if not cls.is_enabled() or not run_id:
            return None

        phase_value = phase.value if isinstance(phase, AgentDecisionPhase) else str(phase)
        actor_value = actor.value if isinstance(actor, AgentDecisionActor) else str(actor)
        timestamp = _utc_now_iso()
        payload_redacted_json, payload_hash = cls._prepare_payload(payload)

        with get_db_context() as db:
            try:
                latest = (
                    db.query(AgentDecisionEvent)
                    .filter(AgentDecisionEvent.run_id == run_id)
                    .order_by(desc(AgentDecisionEvent.seq))
                    .first()
                )
                seq = (latest.seq + 1) if latest else 1
                prev_hash = latest.event_hash if latest else None
                event_hash = _sha256_text(
                    _canonical_json(
                        {
                            "run_id": run_id,
                            "seq": seq,
                            "timestamp": timestamp,
                            "phase": phase_value,
                            "event_name": event_name,
                            "actor": actor_value,
                            "tool_name": tool_name or "",
                            "payload_hash": payload_hash,
                            "latency_ms": latency_ms,
                            "prev_event_hash": prev_hash or "",
                        }
                    )
                )

                event = AgentDecisionEvent(
                    run_id=run_id,
                    seq=seq,
                    timestamp=timestamp,
                    phase=phase_value,
                    event_name=event_name,
                    actor=actor_value,
                    tool_name=tool_name,
                    payload_redacted=payload_redacted_json,
                    payload_hash=payload_hash,
                    latency_ms=latency_ms,
                    prev_event_hash=prev_hash,
                    event_hash=event_hash,
                )
                db.add(event)
                db.flush()
                event_id = event.id
            except Exception as exc:
                logger.warning("Decision audit log_event failed: %s", exc)
                return None

        cls._mirror_append(
            {
                "record_type": "event",
                "timestamp": timestamp,
                "run_id": run_id,
                "event_id": event_id,
                "seq": seq,
                "phase": phase_value,
                "event_name": event_name,
                "actor": actor_value,
                "tool_name": tool_name,
                "payload_hash": payload_hash,
                "latency_ms": latency_ms,
                "prev_event_hash": prev_hash,
                "event_hash": event_hash,
            }
        )
        return event_id

    @classmethod
    def log_event_from_context(
        cls,
        *,
        phase: AgentDecisionPhase | str,
        event_name: str,
        actor: AgentDecisionActor | str,
        payload: dict[str, Any] | None = None,
        tool_name: str | None = None,
        latency_ms: int | None = None,
    ) -> str | None:
        return cls.log_event(
            run_id=get_decision_run_id(),
            phase=phase,
            event_name=event_name,
            actor=actor,
            payload=payload,
            tool_name=tool_name,
            latency_ms=latency_ms,
        )

    @classmethod
    def get_run(cls, run_id: str) -> dict[str, Any] | None:
        with get_db_context() as db:
            run = db.query(AgentDecisionRun).filter(AgentDecisionRun.id == run_id).first()
            if run is None:
                return None
            return cls._run_to_dict(run)

    @classmethod
    def list_runs(
        cls,
        *,
        limit: int = 100,
        offset: int = 0,
        session_id: str | None = None,
        job_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        with get_db_context() as db:
            query = db.query(AgentDecisionRun)
            if session_id:
                query = query.filter(AgentDecisionRun.session_id == session_id)
            if job_id:
                query = query.filter(AgentDecisionRun.job_id == job_id)
            if status:
                query = query.filter(AgentDecisionRun.status == status)

            total = query.count()
            runs = (
                query.order_by(desc(AgentDecisionRun.started_at))
                .offset(offset)
                .limit(limit)
                .all()
            )
            run_payload = [cls._run_to_dict(run) for run in runs]
        return {
            "runs": run_payload,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @classmethod
    def list_events(
        cls,
        *,
        run_id: str,
        limit: int = 500,
        offset: int = 0,
        phase: str | None = None,
        event_name: str | None = None,
    ) -> dict[str, Any]:
        with get_db_context() as db:
            query = db.query(AgentDecisionEvent).filter(AgentDecisionEvent.run_id == run_id)
            if phase:
                query = query.filter(AgentDecisionEvent.phase == phase)
            if event_name:
                query = query.filter(AgentDecisionEvent.event_name == event_name)
            total = query.count()
            rows = (
                query.order_by(AgentDecisionEvent.seq.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            events_payload = [cls._event_to_dict(row) for row in rows]

        return {
            "events": events_payload,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @classmethod
    def list_events_for_job(
        cls,
        *,
        job_id: str,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        with get_db_context() as db:
            rows = (
                db.query(AgentDecisionEvent, AgentDecisionRun.id)
                .join(AgentDecisionRun, AgentDecisionEvent.run_id == AgentDecisionRun.id)
                .filter(AgentDecisionRun.job_id == job_id)
                .order_by(desc(AgentDecisionEvent.timestamp), desc(AgentDecisionEvent.seq))
                .offset(offset)
                .limit(limit)
                .all()
            )
            total = (
                db.query(AgentDecisionEvent)
                .join(AgentDecisionRun, AgentDecisionEvent.run_id == AgentDecisionRun.id)
                .filter(AgentDecisionRun.job_id == job_id)
                .count()
            )
            events = []
            for event, _run_id in rows:
                events.append(cls._event_to_dict(event))
        return {
            "events": events,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @classmethod
    def resolve_run_id_for_job(cls, job_id: str) -> str | None:
        try:
            with get_db_context() as db:
                run = (
                    db.query(AgentDecisionRun)
                    .filter(AgentDecisionRun.job_id == job_id)
                    .order_by(desc(AgentDecisionRun.started_at))
                    .first()
                )
                return run.id if run else None
        except Exception as exc:
            logger.warning("Decision audit resolve_run_id_for_job failed: %s", exc)
            return None

    @classmethod
    def export_events(
        cls,
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_db_context() as db:
            query = db.query(AgentDecisionEvent, AgentDecisionRun)
            query = query.join(AgentDecisionRun, AgentDecisionEvent.run_id == AgentDecisionRun.id)
            if run_id:
                query = query.filter(AgentDecisionRun.id == run_id)
            if job_id:
                query = query.filter(AgentDecisionRun.job_id == job_id)
            if started_after:
                query = query.filter(AgentDecisionEvent.timestamp >= started_after)
            if started_before:
                query = query.filter(AgentDecisionEvent.timestamp <= started_before)

            rows = (
                query.order_by(AgentDecisionEvent.timestamp.asc(), AgentDecisionEvent.seq.asc())
                .all()
            )
            out: list[dict[str, Any]] = []
            for event, run in rows:
                item = cls._event_to_dict(event)
                item["run_status"] = run.status
                item["job_id"] = run.job_id
                item["session_id"] = run.session_id
                out.append(item)
        return out

    @classmethod
    def cleanup_retention(cls) -> dict[str, int]:
        """Delete stale DB rows and prune stale JSONL records."""
        retention_days = cls.retention_days()
        cutoff_dt = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff_iso = cutoff_dt.isoformat()

        deleted_events = 0
        deleted_runs = 0
        with get_db_context() as db:
            stale_run_ids = [
                row[0]
                for row in (
                    db.query(AgentDecisionRun.id)
                    .filter(
                        AgentDecisionRun.started_at < cutoff_iso,
                        AgentDecisionRun.status != AgentDecisionRunStatus.running.value,
                    )
                    .all()
                )
            ]
            if stale_run_ids:
                deleted_events = (
                    db.query(AgentDecisionEvent)
                    .filter(AgentDecisionEvent.run_id.in_(stale_run_ids))
                    .delete(synchronize_session=False)
                )
                deleted_runs = (
                    db.query(AgentDecisionRun)
                    .filter(AgentDecisionRun.id.in_(stale_run_ids))
                    .delete(synchronize_session=False)
                )

        pruned_lines = cls._prune_jsonl(cutoff_dt)
        return {
            "deleted_events": deleted_events,
            "deleted_runs": deleted_runs,
            "pruned_jsonl_lines": pruned_lines,
        }

    @classmethod
    def _prune_jsonl(cls, cutoff_dt: datetime) -> int:
        path = cls.jsonl_path()
        if not path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        payload = json.loads(stripped)
                    except json.JSONDecodeError:
                        kept.append(line)
                        continue
                    timestamp = _parse_iso(payload.get("timestamp"))
                    if timestamp is None or timestamp >= cutoff_dt:
                        kept.append(line)
                    else:
                        removed += 1
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as fh:
                fh.writelines(kept)
            os.replace(tmp_path, path)
        except Exception as exc:
            logger.warning("Failed pruning decision JSONL mirror: %s", exc)
            return 0
        return removed

    @staticmethod
    def _run_to_dict(run: AgentDecisionRun) -> dict[str, Any]:
        source_signature = None
        if run.source_signature:
            try:
                source_signature = json.loads(run.source_signature)
            except json.JSONDecodeError:
                source_signature = {"raw": run.source_signature}
        return {
            "id": run.id,
            "session_id": run.session_id,
            "job_id": run.job_id,
            "user_message_hash": run.user_message_hash,
            "user_message_redacted": run.user_message_redacted,
            "source_signature": source_signature,
            "status": run.status,
            "model": run.model,
            "interactive_shipping": run.interactive_shipping,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }

    @staticmethod
    def _event_to_dict(event: AgentDecisionEvent) -> dict[str, Any]:
        payload = {}
        if event.payload_redacted:
            try:
                payload = json.loads(event.payload_redacted)
            except json.JSONDecodeError:
                payload = {"raw": event.payload_redacted}
        return {
            "id": event.id,
            "run_id": event.run_id,
            "seq": event.seq,
            "timestamp": event.timestamp,
            "phase": event.phase,
            "event_name": event.event_name,
            "actor": event.actor,
            "tool_name": event.tool_name,
            "payload_redacted": payload,
            "payload_hash": event.payload_hash,
            "latency_ms": event.latency_ms,
            "prev_event_hash": event.prev_event_hash,
            "event_hash": event.event_hash,
        }
