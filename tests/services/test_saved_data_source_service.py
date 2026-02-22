"""Tests for SavedDataSourceService — including generic file-based types."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base, SavedDataSource
from src.services.saved_data_source_service import SavedDataSourceService


@pytest.fixture
def db_session() -> Session:
    """In-memory SQLite for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --- save_or_update_csv ---


def test_save_csv_creates_new(db_session: Session):
    """First save creates a new CSV record."""
    result = SavedDataSourceService.save_or_update_csv(
        db_session, "/data/orders.csv", 100, 8
    )
    assert result.source_type == "csv"
    assert result.file_path == "/data/orders.csv"
    assert result.name == "orders.csv"
    assert result.row_count == 100
    assert result.column_count == 8


def test_save_csv_upsert(db_session: Session):
    """Second save for same file updates existing record."""
    SavedDataSourceService.save_or_update_csv(db_session, "/data/orders.csv", 100, 8)
    result = SavedDataSourceService.save_or_update_csv(db_session, "/data/orders.csv", 200, 10)
    assert result.row_count == 200
    assert result.column_count == 10
    count = db_session.query(SavedDataSource).filter_by(source_type="csv").count()
    assert count == 1


# --- save_or_update_file (generic) ---


def test_save_file_json_creates_new(db_session: Session):
    """save_or_update_file creates a new JSON record."""
    result = SavedDataSourceService.save_or_update_file(
        db_session, "/data/products.json", "json", 50, 6
    )
    assert result.source_type == "json"
    assert result.file_path == "/data/products.json"
    assert result.name == "products.json"
    assert result.row_count == 50
    assert result.column_count == 6


def test_save_file_xml_creates_new(db_session: Session):
    """save_or_update_file creates a new XML record."""
    result = SavedDataSourceService.save_or_update_file(
        db_session, "/data/shipments.xml", "xml", 75, 12
    )
    assert result.source_type == "xml"
    assert result.name == "shipments.xml"


def test_save_file_edi_creates_new(db_session: Session):
    """save_or_update_file creates a new EDI record."""
    result = SavedDataSourceService.save_or_update_file(
        db_session, "/data/invoice.edi", "edi", 30, 15
    )
    assert result.source_type == "edi"
    assert result.name == "invoice.edi"


def test_save_file_fixed_width_creates_new(db_session: Session):
    """save_or_update_file creates a new fixed_width record."""
    result = SavedDataSourceService.save_or_update_file(
        db_session, "/data/legacy.fwf", "fixed_width", 200, 20
    )
    assert result.source_type == "fixed_width"
    assert result.name == "legacy.fwf"


def test_save_file_upsert_same_type_and_path(db_session: Session):
    """Second save for same type+path updates existing record."""
    SavedDataSourceService.save_or_update_file(
        db_session, "/data/products.json", "json", 50, 6
    )
    result = SavedDataSourceService.save_or_update_file(
        db_session, "/data/products.json", "json", 100, 8
    )
    assert result.row_count == 100
    assert result.column_count == 8
    count = db_session.query(SavedDataSource).filter_by(source_type="json").count()
    assert count == 1


def test_save_file_different_types_same_path(db_session: Session):
    """Different source_type for same file_path creates separate records."""
    SavedDataSourceService.save_or_update_file(
        db_session, "/data/mixed.dat", "json", 10, 3
    )
    SavedDataSourceService.save_or_update_file(
        db_session, "/data/mixed.dat", "xml", 20, 5
    )
    total = db_session.query(SavedDataSource).filter_by(file_path="/data/mixed.dat").count()
    assert total == 2


# --- list_sources with type filter ---


def test_list_sources_filters_by_type(db_session: Session):
    """list_sources respects source_type filter for new types."""
    SavedDataSourceService.save_or_update_csv(db_session, "/data/a.csv", 10, 3)
    SavedDataSourceService.save_or_update_file(db_session, "/data/b.json", "json", 20, 4)
    SavedDataSourceService.save_or_update_file(db_session, "/data/c.xml", "xml", 30, 5)

    all_sources = SavedDataSourceService.list_sources(db_session)
    assert len(all_sources) == 3

    json_only = SavedDataSourceService.list_sources(db_session, source_type="json")
    assert len(json_only) == 1
    assert json_only[0].source_type == "json"

    csv_only = SavedDataSourceService.list_sources(db_session, source_type="csv")
    assert len(csv_only) == 1


# --- delete ---


def test_delete_generic_file_source(db_session: Session):
    """Deleting a generic file source works correctly."""
    record = SavedDataSourceService.save_or_update_file(
        db_session, "/data/items.xml", "xml", 15, 4
    )
    assert SavedDataSourceService.delete_source(db_session, record.id) is True
    assert db_session.query(SavedDataSource).count() == 0
