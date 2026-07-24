import pytest

from src.control_plane.database_url import normalize_control_plane_database_url
from src.control_plane.db import build_session_factory


def test_normalizes_conventional_postgresql_url_for_async_control_plane():
    assert normalize_control_plane_database_url(
        "postgresql://user:password@db.example.com:5432/shipagent?sslmode=require"
    ) == (
        "postgresql+asyncpg://"
        "user:password@db.example.com:5432/shipagent?sslmode=require"
    )


@pytest.mark.parametrize(
    "scheme",
    [
        "postgres",
        "postgresql+psycopg",
        "postgresql+psycopg2",
        "postgresql+pg8000",
    ],
)
def test_normalizes_supported_sync_postgresql_driver_urls(scheme):
    assert (
        normalize_control_plane_database_url(
            f"{scheme}://user:password@db.example.com/shipagent"
        )
        == "postgresql+asyncpg://user:password@db.example.com/shipagent"
    )


def test_preserves_already_async_postgresql_url():
    database_url = (
        "postgresql+asyncpg://user:password@db.example.com/shipagent?ssl=require"
    )

    assert normalize_control_plane_database_url(database_url) == database_url


def test_session_factory_accepts_conventional_postgresql_url():
    session_factory = build_session_factory(
        "postgresql://user:password@db.example.com/shipagent"
    )

    assert session_factory.kw["bind"].url.drivername == "postgresql+asyncpg"
