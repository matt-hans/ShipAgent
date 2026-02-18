"""Unit tests for centralized decision audit ledger service."""

from __future__ import annotations

import json
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.services.decision_audit_service import DecisionAuditService


def _canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_hash_chain_and_payload_hash(monkeypatch, tmp_path):
    """Events should have stable payload hashes and chained integrity hashes."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _ctx():
        db = SessionLocal()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr("src.services.decision_audit_service.get_db_context", _ctx)
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "decision.jsonl"))

    run_id = DecisionAuditService.start_run(
        session_id="s1",
        user_message="Ship all unfulfilled orders",
        model="test-model",
        interactive_shipping=False,
    )
    assert run_id

    payload_one = {"a": 1, "b": "x"}
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="pipeline",
        event_name="event.one",
        actor="tool",
        payload=payload_one,
    )
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="pipeline",
        event_name="event.two",
        actor="tool",
        payload={"c": 3},
    )

    events = DecisionAuditService.list_events(run_id=run_id, limit=10)["events"]
    assert len(events) == 2
    assert events[0]["seq"] == 1
    assert events[1]["seq"] == 2
    assert events[1]["prev_event_hash"] == events[0]["event_hash"]
    assert events[0]["payload_hash"] == _sha256(_canonical_json(payload_one))


def test_truncation_behavior(monkeypatch, tmp_path):
    """Large payloads should be truncated with metadata."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _ctx():
        db = SessionLocal()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr("src.services.decision_audit_service.get_db_context", _ctx)
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUDIT_MAX_PAYLOAD_BYTES", "64")
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "decision.jsonl"))

    run_id = DecisionAuditService.start_run(
        session_id="s2",
        user_message="hello",
        model="test-model",
        interactive_shipping=False,
    )
    assert run_id
    DecisionAuditService.log_event(
        run_id=run_id,
        phase="resolution",
        event_name="event.large",
        actor="tool",
        payload={"text": "x" * 400},
    )

    events = DecisionAuditService.list_events(run_id=run_id, limit=10)["events"]
    assert len(events) == 1
    payload = events[0]["payload_redacted"]
    assert payload["truncated"] is True
    assert payload["original_bytes"] > payload["max_bytes"]


def test_redaction_on_message_and_payload(monkeypatch, tmp_path):
    """User message and payload should redact sensitive data."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _ctx():
        db = SessionLocal()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr("src.services.decision_audit_service.get_db_context", _ctx)
    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "decision.jsonl"))

    run_id = DecisionAuditService.start_run(
        session_id="s3",
        user_message="email me at test@example.com and use sk-ant-abc123456789",
        model="test-model",
        interactive_shipping=False,
    )
    run = DecisionAuditService.get_run(run_id)
    assert run is not None
    assert "[REDACTED_EMAIL]" in run["user_message_redacted"]
    assert "[REDACTED_TOKEN]" in run["user_message_redacted"]

    DecisionAuditService.log_event(
        run_id=run_id,
        phase="tool_call",
        event_name="event.redact",
        actor="tool",
        payload={
            "email": "person@example.com",
            "client_secret": "secret",
            "nested": {"phone": "415-555-1212"},
        },
    )
    events = DecisionAuditService.list_events(run_id=run_id, limit=10)["events"]
    payload = events[0]["payload_redacted"]
    assert payload["email"] == "[REDACTED]"
    assert payload["client_secret"] == "[REDACTED]"
    assert payload["nested"]["phone"] == "[REDACTED]"
