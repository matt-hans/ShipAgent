"""Opt-in, test-owned database for cross-provider privacy acceptance."""

import pytest


@pytest.fixture
def privacy_db(monkeypatch, tmp_path):
    """Only test-owned local persistence and deterministic carrier data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.db.models import Base
    from src.services.contact_service import ContactService
    from tests.services.batch_acceptance_support import SHIPPER_ENV

    engine = create_engine(f"sqlite:///{tmp_path / 'privacy.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("src.db.connection.SessionLocal", factory)
    monkeypatch.setenv("SHIPAGENT_KEYRING_DISABLED", "1")
    monkeypatch.setenv("UPS_LABELS_OUTPUT_DIR", str(tmp_path / "labels"))
    monkeypatch.setenv("AGENT_AUDIT_JSONL_PATH", str(tmp_path / "audit.jsonl"))
    for key, value in SHIPPER_ENV.items():
        monkeypatch.setenv(key, value)
    with factory() as db:
        for handle in ("saved-person", "saved-office"):
            ContactService(db).create_contact(
                handle=handle,
                display_name="LOCAL-CONTACT-RECIPIENT",
                address_line_1="88 LOCAL-CONTACT-STREET",
                city="Oakland",
                state_province="CA",
                postal_code="94607",
            )
        db.commit()
    yield factory
    engine.dispose()
