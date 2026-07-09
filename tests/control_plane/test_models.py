from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from alembic import command
from src.control_plane.db import (
    build_session_factory,
    control_plane_schema_for_database_url,
)
from src.control_plane.models import (
    CloudAccount,
    ControlPlaneBase,
    ProviderConnection,
    RelayDevice,
)


async def test_auth0_subject_maps_to_one_cloud_account(control_db):
    account = CloudAccount(auth0_subject="auth0|owner-1")
    control_db.add(account)
    await control_db.commit()

    loaded = await control_db.scalar(
        select(CloudAccount).where(CloudAccount.auth0_subject == "auth0|owner-1")
    )
    assert loaded.id == account.id


def test_provider_connection_never_owns_account_identity():
    columns = ProviderConnection.__table__.columns
    assert "account_id" in columns
    assert "provider_subject" not in columns


def test_relay_device_is_control_plane_metadata():
    table = ControlPlaneBase.metadata.tables["relay_devices"]

    assert table.c.account_id.foreign_keys
    constraint_names = {
        constraint.name for constraint in table.constraints if constraint.name
    }
    index_names = {index.name for index in table.indexes}
    assert {
        "id",
        "account_id",
        "device_name",
        "public_key_pem",
        "fingerprint",
        "revoked",
        "active",
    }.issubset(table.c.keys())
    assert "uq_relay_devices_account_fingerprint" in constraint_names
    assert "uq_relay_devices_one_active_per_account" in index_names


def test_control_plane_schema_is_unqualified_only_for_sqlite(monkeypatch):
    monkeypatch.delenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", raising=False)

    assert control_plane_schema_for_database_url("sqlite+aiosqlite:///:memory:") is None
    assert (
        control_plane_schema_for_database_url(
            "postgresql+asyncpg://shipagent:shipagent@localhost/shipagent"
        )
        == "shipagent_private"
    )


def test_control_plane_schema_env_overrides_runtime_config(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "custom_private")

    assert (
        control_plane_schema_for_database_url(
            "postgresql+asyncpg://shipagent:shipagent@localhost/shipagent",
            configured_schema="configured_private",
        )
        == "custom_private"
    )


def test_alembic_offline_upgrade_uses_custom_schema_env(monkeypatch):
    monkeypatch.setenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", "custom_private")
    repo_root = Path(__file__).resolve().parents[2]
    output = StringIO()
    config = Config(str(repo_root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql://shipagent:shipagent@localhost/shipagent",
    )

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert "custom_private" in sql
    assert "shipagent_private" not in sql


async def test_relay_device_fingerprint_is_unique_per_account(control_db):
    control_db.add(CloudAccount(id="acct-1", auth0_subject="auth0|owner-1"))
    control_db.add(
        RelayDevice(
            id="relay_device_1",
            account_id="acct-1",
            device_name="Dock Mac",
            public_key_pem="public-key",
            fingerprint="sha256:duplicate",
        )
    )
    await control_db.commit()

    control_db.add(
        RelayDevice(
            id="relay_device_2",
            account_id="acct-1",
            device_name="Warehouse Mac",
            public_key_pem="other-public-key",
            fingerprint="sha256:duplicate",
        )
    )
    with pytest.raises(IntegrityError):
        await control_db.commit()


async def test_relay_device_allows_only_one_active_unrevoked_device_per_account(
    control_db,
):
    control_db.add(CloudAccount(id="acct-1", auth0_subject="auth0|owner-1"))
    control_db.add(
        RelayDevice(
            id="relay_device_1",
            account_id="acct-1",
            device_name="Dock Mac",
            public_key_pem="public-key",
            fingerprint="sha256:first",
            active=True,
            revoked=False,
        )
    )
    await control_db.commit()

    control_db.add(
        RelayDevice(
            id="relay_device_2",
            account_id="acct-1",
            device_name="Warehouse Mac",
            public_key_pem="other-public-key",
            fingerprint="sha256:second",
            active=True,
            revoked=False,
        )
    )
    with pytest.raises(IntegrityError):
        await control_db.commit()


async def test_alembic_upgrade_matches_runtime_model_namespace(tmp_path):
    database_path = tmp_path / "control-plane.db"
    database_url = f"sqlite:///{database_path}"
    async_database_url = f"sqlite+aiosqlite:///{database_path}"
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    session_factory = build_session_factory(async_database_url)
    async with session_factory() as session:
        account = CloudAccount(id="acct-1", auth0_subject="auth0|owner-1")
        device = RelayDevice(
            id="relay_device_1",
            account_id="acct-1",
            device_name="Dock Mac",
            public_key_pem="public-key",
            fingerprint="sha256:test",
        )
        session.add_all([account, device])
        await session.commit()

    async with session_factory() as session:
        loaded = await session.scalar(
            select(RelayDevice).where(RelayDevice.id == "relay_device_1")
        )

    assert loaded is not None
    assert loaded.account_id == "acct-1"
