import pytest

from src.control_plane.database_url import normalize_control_plane_database_url
from src.control_plane.db import build_session_factory


def test_normalizes_conventional_postgresql_url_for_async_control_plane():
    assert normalize_control_plane_database_url(
        "postgresql://user:password@db.example.com:5432/shipagent?sslmode=require"
    ) == (
        "postgresql+asyncpg://user:password@db.example.com:5432/shipagent?ssl=require"
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


def test_normalizes_tls_on_already_async_url_without_reencoding_components():
    database_url = (
        "postgresql+asyncpg://user:p%40ss%2Fword@db.example.com/"
        "shipagent%2Ftenant?application_name=ship%20agent&sslmode=verify-full"
        "&options=-c%20statement_timeout%3D5000"
    )

    assert normalize_control_plane_database_url(database_url) == (
        "postgresql+asyncpg://user:p%40ss%2Fword@db.example.com/"
        "shipagent%2Ftenant?application_name=ship%20agent&ssl=verify-full"
        "&options=-c%20statement_timeout%3D5000"
    )


def test_preserves_explicit_asyncpg_ssl_and_unrelated_query_parameters():
    database_url = (
        "postgresql+asyncpg://user:password@db.example.com/shipagent"
        "?application_name=shipagent%2Frelay&ssl=require"
    )

    assert normalize_control_plane_database_url(database_url) == database_url


def test_rejects_conflicting_asyncpg_tls_query_options():
    with pytest.raises(ValueError, match="conflicting PostgreSQL TLS options"):
        normalize_control_plane_database_url(
            "postgresql://user:password@db.example.com/shipagent"
            "?sslmode=require&ssl=disable"
        )


def test_session_factory_accepts_conventional_postgresql_url():
    session_factory = build_session_factory(
        "postgresql://user:password@db.example.com/shipagent"
    )

    assert session_factory.kw["bind"].url.drivername == "postgresql+asyncpg"
