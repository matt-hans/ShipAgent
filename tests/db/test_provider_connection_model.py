"""Tests for ProviderConnection model and migration."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderConnection


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class TestProviderConnectionModel:

    def test_create_ups_connection(self, db_session):
        """Can create a UPS connection row with all required fields."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="UPS Test", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="encrypted_blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.id is not None
        assert conn.connection_key == "ups:test"

    def test_create_shopify_connection(self, db_session):
        """Can create a Shopify connection row."""
        conn = ProviderConnection(
            connection_key="shopify:store.myshopify.com",
            provider="shopify", display_name="My Store",
            auth_mode="legacy_token", status="configured",
            encrypted_credentials="encrypted_blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.provider == "shopify"

    def test_unique_connection_key_constraint(self, db_session):
        """Duplicate connection_key raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        conn1 = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="A", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob1",
        )
        conn2 = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="B", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob2",
        )
        db_session.add(conn1)
        db_session.commit()
        db_session.add(conn2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_default_timestamps_set(self, db_session):
        """created_at and updated_at are auto-populated."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="UPS", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.created_at is not None
        assert conn.updated_at is not None

    def test_default_schema_and_key_version(self, db_session):
        """schema_version defaults to 1, key_version defaults to 1."""
        conn = ProviderConnection(
            connection_key="ups:test", provider="ups",
            display_name="UPS", auth_mode="client_credentials",
            environment="test", status="configured",
            encrypted_credentials="blob",
        )
        db_session.add(conn)
        db_session.commit()
        assert conn.schema_version == 1
        assert conn.key_version == 1


class TestProviderConnectionMigration:

    def test_migration_creates_table_on_empty_db(self):
        """Migration creates provider_connections table on fresh DB."""
        engine = create_engine("sqlite:///:memory:")
        from src.db.connection import _ensure_columns_exist
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
        inspector = inspect(engine)
        assert "provider_connections" in inspector.get_table_names()

    def test_migration_adds_missing_columns(self):
        """Migration adds missing columns to existing table."""
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE provider_connections (id TEXT PRIMARY KEY, connection_key TEXT)"
            ))
        from src.db.connection import _ensure_columns_exist
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
        inspector = inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("provider_connections")}
        assert "provider" in columns
        assert "encrypted_credentials" in columns

    def test_migration_is_idempotent(self):
        """Running migration twice produces no errors."""
        engine = create_engine("sqlite:///:memory:")
        from src.db.connection import _ensure_columns_exist
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
        with engine.begin() as conn:
            _ensure_columns_exist(conn)  # Second run — no error

    def test_migration_creates_unique_index_on_partial_table(self):
        """Migration creates unique index even if table existed without it."""
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE provider_connections ("
                "id TEXT PRIMARY KEY, connection_key TEXT, provider TEXT"
                ")"
            ))
        from src.db.connection import _ensure_columns_exist
        with engine.begin() as conn:
            _ensure_columns_exist(conn)
        inspector = inspect(engine)
        indexes = inspector.get_indexes("provider_connections")
        index_names = {idx["name"] for idx in indexes}
        assert "idx_provider_connections_connection_key" in index_names
