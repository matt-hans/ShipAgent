"""Tests for database URL configuration precedence and migration security."""

import inspect

from src.db.connection import _migrate_provider_connections, get_database_url


def test_get_database_url_prefers_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./preferred.db")
    monkeypatch.setenv("SHIPAGENT_DB_PATH", "/tmp/fallback.db")

    assert get_database_url() == "sqlite:///./preferred.db"


def test_get_database_url_uses_shipagent_db_path_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SHIPAGENT_DB_PATH", "/tmp/shipagent.db")

    assert get_database_url() == "sqlite:////tmp/shipagent.db"


def test_get_database_url_defaults_to_platformdirs_path(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SHIPAGENT_DB_PATH", raising=False)

    url = get_database_url()
    # In dev mode, resolves to absolute path via get_default_db_path()
    assert url.startswith("sqlite:///")
    assert url.endswith("shipagent.db")


class TestMigrationParameterizedSQL:
    """Tests for CPB-3: parameterized SQL in database migration (CWE-89)."""

    def test_migration_uses_parameterized_binding(self):
        """Verify _migrate_provider_connections uses :now_utc binding, not f-string."""
        source = inspect.getsource(_migrate_provider_connections)
        assert ":now_utc" in source, "Migration must use parameterized :now_utc binding"
        assert 'f"' not in source or "now_utc" not in source.split('f"')[1] if 'f"' in source else True

