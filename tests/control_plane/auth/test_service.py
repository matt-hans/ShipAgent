from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.auth.service import AuthorizationService
from src.control_plane.models import CloudAccount, ProviderConnection


@pytest.mark.asyncio
async def test_resolve_upserts_account_and_independent_connection(control_db):
    service = AuthorizationService(
        control_db,
        ProviderClientRegistry(
            {"chatgpt-client": "chatgpt", "claude-client": "claude_ai"}
        ),
    )
    first = await service.resolve(
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes={"shipments:preview"},
    )
    second = await service.resolve(
        subject="auth0|owner-1",
        client_id="claude-client",
        scopes={"jobs:read"},
    )

    assert first.account_id == second.account_id
    assert first.provider_connection_id != second.provider_connection_id
    assert first.provider_surface == "chatgpt"
    assert second.provider_surface == "claude_ai"


@pytest.mark.asyncio
async def test_resolve_reuses_active_connection_and_updates_scopes(control_db):
    service = AuthorizationService(
        control_db,
        ProviderClientRegistry({"chatgpt-client": "chatgpt"}),
    )
    first = await service.resolve(
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes={"shipments:preview"},
    )
    second = await service.resolve(
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes={"jobs:read"},
    )

    assert first.provider_connection_id == second.provider_connection_id

    connection = await control_db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == second.provider_connection_id
        )
    )
    assert connection is not None
    assert connection.scopes_text == "jobs:read"


@pytest.mark.asyncio
async def test_resolve_preserves_auth_time_in_authorization_context(control_db):
    service = AuthorizationService(
        control_db,
        ProviderClientRegistry({"chatgpt-client": "chatgpt"}),
    )
    auth_time = datetime(2026, 7, 2, 12, 30, tzinfo=UTC)

    context = await service.resolve(
        subject="auth0|owner-1",
        client_id="chatgpt-client",
        scopes={"relay:manage"},
        auth_time=auth_time,
    )

    assert context.auth_time == auth_time


@pytest.mark.asyncio
async def test_resolve_rejects_suspended_account(control_db):
    suspended = CloudAccount(auth0_subject="auth0|owner-2", suspended=True)
    control_db.add(suspended)
    await control_db.commit()

    service = AuthorizationService(
        control_db,
        ProviderClientRegistry({"chatgpt-client": "chatgpt"}),
    )
    with pytest.raises(PermissionError, match="suspended"):
        await service.resolve(
            subject="auth0|owner-2",
            client_id="chatgpt-client",
            scopes={"jobs:read"},
        )


@pytest.mark.asyncio
async def test_resolve_rejects_inactive_connection(control_db):
    account = CloudAccount(auth0_subject="auth0|owner-3")
    control_db.add(account)
    await control_db.flush()
    control_db.add(
        ProviderConnection(
            account_id=account.id,
            client_id="chatgpt-client",
            surface="chatgpt",
            status="revoked",
            scopes_text="shipments:preview",
        )
    )
    await control_db.commit()

    service = AuthorizationService(
        control_db,
        ProviderClientRegistry({"chatgpt-client": "chatgpt"}),
    )
    with pytest.raises(PermissionError, match="not active"):
        await service.resolve(
            subject="auth0|owner-3",
            client_id="chatgpt-client",
            scopes={"jobs:read"},
        )
