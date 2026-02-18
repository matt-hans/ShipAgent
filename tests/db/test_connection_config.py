"""Tests for database URL configuration precedence."""

from src.db.connection import get_database_url


def test_get_database_url_prefers_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./preferred.db")
    monkeypatch.setenv("SHIPAGENT_DB_PATH", "/tmp/fallback.db")

    assert get_database_url() == "sqlite:///./preferred.db"


def test_get_database_url_uses_shipagent_db_path_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SHIPAGENT_DB_PATH", "/tmp/shipagent.db")

    assert get_database_url() == "sqlite:////tmp/shipagent.db"


def test_get_database_url_defaults_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SHIPAGENT_DB_PATH", raising=False)

    assert get_database_url() == "sqlite:///./shipagent.db"

