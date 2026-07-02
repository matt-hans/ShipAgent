from pathlib import Path

from alembic.config import Config
from sqlalchemy import select

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
        select(CloudAccount).where(
            CloudAccount.auth0_subject == "auth0|owner-1"
        )
    )
    assert loaded.id == account.id


def test_provider_connection_never_owns_account_identity():
    columns = ProviderConnection.__table__.columns
    assert "account_id" in columns
    assert "provider_subject" not in columns


def test_relay_device_is_control_plane_metadata():
    table = ControlPlaneBase.metadata.tables["relay_devices"]

    assert table.c.account_id.foreign_keys
    assert {
        "id",
        "account_id",
        "device_name",
        "public_key_pem",
        "fingerprint",
        "revoked",
        "active",
    }.issubset(table.c.keys())


def test_control_plane_schema_is_unqualified_only_for_sqlite(monkeypatch):
    monkeypatch.delenv("SHIPAGENT_CONTROL_PLANE_SCHEMA", raising=False)

    assert control_plane_schema_for_database_url("sqlite+aiosqlite:///:memory:") is None
    assert (
        control_plane_schema_for_database_url(
            "postgresql+asyncpg://shipagent:shipagent@localhost/shipagent"
        )
        == "shipagent_private"
    )


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
