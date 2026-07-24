"""Control-plane database URL compatibility helpers."""

_SYNC_POSTGRESQL_SCHEMES = {
    "postgres",
    "postgresql",
    "postgresql+pg8000",
    "postgresql+psycopg",
    "postgresql+psycopg2",
}


def normalize_control_plane_database_url(database_url: str) -> str:
    """Return a PostgreSQL URL suitable for SQLAlchemy's async engine."""
    scheme, separator, remainder = database_url.partition("://")
    if separator and scheme.lower() in _SYNC_POSTGRESQL_SCHEMES:
        return f"postgresql+asyncpg://{remainder}"
    return database_url
