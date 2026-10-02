"""Seam tests for the reconciled findings + relay control-plane DB/config layers."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from src.control_plane.config import ControlPlaneSettings
from src.control_plane.db import build_session_factory

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(url: str, output: StringIO | None = None) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_settings_keep_schema_and_auth0_provider_clients():
    settings = ControlPlaneSettings(database_url=None)
    assert settings.control_plane_schema == "shipagent_private"
    assert settings.auth0_provider_clients["claude-client"] == "claude_ai"
    assert settings.auth0_provider_clients["desktop-client"] == "desktop"


def test_session_factory_normalizes_postgres_url_and_binds_schema():
    factory = build_session_factory(
        "postgresql://user:pw@localhost/db?sslmode=require",
        control_plane_schema="custom_private",
    )
    engine = factory.kw["bind"]
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.query.get("ssl") == "require"
    assert "sslmode" not in engine.url.query


def test_offline_postgres_sql_honors_env_schema_and_relay_head(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "seam_private")
    monkeypatch.delenv("SHIPAGENT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    output = StringIO()
    command.upgrade(
        _alembic_config("postgresql://u:p@localhost/db", output), "head", sql=True
    )
    sql = " ".join(output.getvalue().lower().split())
    assert "seam_private" in sql
    assert "shipagent_private" not in sql
    assert "relay_devices" in sql
    assert "suspended boolean default false not null" in sql


def test_env_database_url_overrides_placeholder_ini_url(monkeypatch):
    monkeypatch.setenv(
        "SHIPAGENT_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db"
    )
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "env_private")
    output = StringIO()
    command.upgrade(_alembic_config("CONFIGURE_ME", output), "head", sql=True)
    assert "env_private" in output.getvalue()


def test_explicit_config_url_beats_ambient_env_database_url(monkeypatch, tmp_path):
    """A caller-supplied sqlalchemy.url must not be redirected by ambient env."""
    ambient = tmp_path / "ambient.db"
    explicit = tmp_path / "explicit.db"
    monkeypatch.setenv("SHIPAGENT_DATABASE_URL", f"sqlite:///{ambient}")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ambient}")
    command.upgrade(_alembic_config(f"sqlite:///{explicit}"), "head")
    assert explicit.exists()
    assert not ambient.exists()


def test_sqlite_upgrade_to_head_has_relay_and_control_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'seam.db'}"
    command.upgrade(_alembic_config(url), "head")
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {
        "cloud_accounts",
        "provider_connections",
        "audit_events",
        "relay_devices",
    } <= tables
