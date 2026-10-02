"""Control-plane database URL compatibility helpers."""

from urllib.parse import unquote_plus, urlsplit, urlunsplit

_SYNC_POSTGRESQL_SCHEMES = {
    "postgres",
    "postgresql",
    "postgresql+pg8000",
    "postgresql+psycopg",
    "postgresql+psycopg2",
}
_ASYNC_POSTGRESQL_SCHEME = "postgresql+asyncpg"


def normalize_control_plane_database_url(database_url: str) -> str:
    """Return a PostgreSQL URL suitable for SQLAlchemy's async engine."""
    parsed = urlsplit(database_url)
    scheme = parsed.scheme.lower()
    if scheme not in {*_SYNC_POSTGRESQL_SCHEMES, _ASYNC_POSTGRESQL_SCHEME}:
        return database_url

    query_parts = parsed.query.split("&") if parsed.query else []
    query_keys = {
        unquote_plus(query_part.partition("=")[0]).lower() for query_part in query_parts
    }
    if {"sslmode", "ssl"} <= query_keys:
        raise ValueError("conflicting PostgreSQL TLS options: sslmode and ssl")

    normalized_query_parts = []
    for query_part in query_parts:
        raw_key, separator, raw_value = query_part.partition("=")
        if unquote_plus(raw_key).lower() == "sslmode":
            query_part = f"ssl{separator}{raw_value}"
        normalized_query_parts.append(query_part)

    return urlunsplit(
        (
            _ASYNC_POSTGRESQL_SCHEME,
            parsed.netloc,
            parsed.path,
            "&".join(normalized_query_parts),
            parsed.fragment,
        )
    )
