"""Tests for CustomCommandService CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_create_command(db: Session):
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    cmd = svc.create_command(
        name="daily-restock",
        body="Ship 3 boxes to @nyc-warehouse via UPS Ground",
    )
    db.commit()
    assert cmd.name == "daily-restock"
    assert "@nyc-warehouse" in cmd.body


def test_create_command_invalid_name(db: Session):
    from src.errors.domain import ValidationError
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    with pytest.raises(ValidationError, match="Invalid command name"):
        svc.create_command(name="Bad Name", body="test")


def test_create_command_duplicate(db: Session):
    from src.errors.domain import DuplicateCommandNameError
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    svc.create_command(name="test-cmd", body="body")
    db.commit()
    with pytest.raises(DuplicateCommandNameError, match="already exists"):
        svc.create_command(name="test-cmd", body="other body")


def test_get_by_name(db: Session):
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    svc.create_command(name="test-cmd", body="body")
    db.commit()
    assert svc.get_by_name("test-cmd") is not None
    assert svc.get_by_name("/test-cmd") is not None  # with prefix
    assert svc.get_by_name("nonexistent") is None


def test_list_commands(db: Session):
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    svc.create_command(name="alpha", body="body a")
    svc.create_command(name="beta", body="body b")
    db.commit()
    cmds = svc.list_commands()
    assert len(cmds) == 2


def test_update_command(db: Session):
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    cmd = svc.create_command(name="test", body="old body")
    db.commit()
    updated = svc.update_command(cmd.id, body="new body")
    assert updated.body == "new body"


def test_delete_command(db: Session):
    from src.services.custom_command_service import CustomCommandService
    svc = CustomCommandService(db)
    cmd = svc.create_command(name="test", body="body")
    db.commit()
    assert svc.delete_command(cmd.id) is True
    assert svc.get_by_name("test") is None
