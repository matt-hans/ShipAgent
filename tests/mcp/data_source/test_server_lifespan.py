"""A local data-source process must not need network database extensions."""

import duckdb
import pytest

from src.mcp.data_source import server


@pytest.mark.asyncio
async def test_local_startup_works_with_external_access_disabled(monkeypatch):
    # Use the real engine with a hard network/filesystem boundary. Eager
    # INSTALL/LOAD is rejected, even when an extension is cached on the host.
    connection = duckdb.connect(":memory:", config={"enable_external_access": False})
    monkeypatch.setattr(server.duckdb, "connect", lambda _: connection)
    async with server.lifespan(None) as state:
        assert state["current_source"] is None
        assert state["db"].execute("SELECT 40 + 2").fetchone() == (42,)
    with pytest.raises(duckdb.ConnectionException):
        connection.execute("SELECT 1")
