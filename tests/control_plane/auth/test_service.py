import time
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


STRICT_POLICY = frozenset({"shipagent.status", "shipagent.preview"})
STRICT_ISSUER = "https://synthetic.shipagent.invalid/"


def strict_service(db):
    return AuthorizationService(
        db,
        ProviderClientRegistry({"chatgpt-client": "chatgpt"}),
        link_allowed_scopes=STRICT_POLICY,
    )


def strict_request(link="link_a", **changes):
    values = {
        "subject": "strict-owner",
        "client_id": "chatgpt-client",
        "scopes": set(STRICT_POLICY),
        "issuer": STRICT_ISSUER,
        "issuer_link_id": link,
        "token_expires_at": time.time() + 60,
        "operation_deadline": time.monotonic() + 2,
    }
    values.update(changes)
    return values


async def test_strict_independent_links_refresh_and_original_request_lifetime(
    control_db,
):
    service = strict_service(control_db)
    request = strict_request()
    first = await service.resolve(**request)
    refresh = await service.resolve(**strict_request())
    other = await service.resolve(**strict_request("link_b"))
    assert first.account_id == refresh.account_id == other.account_id
    assert first.provider_connection_id == refresh.provider_connection_id
    assert first.link_epoch == refresh.link_epoch
    assert other.provider_connection_id != first.provider_connection_id
    assert other.link_epoch != first.link_epoch
    assert first.token_expires_at == request["token_expires_at"]
    assert first.operation_deadline == request["operation_deadline"]
    account = await control_db.get(CloudAccount, first.account_id)
    assert account.issuer == STRICT_ISSUER


@pytest.mark.parametrize(
    "token_order",
    [
        [STRICT_POLICY, frozenset({"shipagent.status"})],
        [frozenset({"shipagent.status"}), STRICT_POLICY],
    ],
)
async def test_token_scopes_never_restore_or_reduce_durable_policy(
    control_db, token_order
):
    service = strict_service(control_db)
    first = await service.resolve(**strict_request())
    await service.reduce_link_scopes(
        first.account_id, first.provider_connection_id, frozenset({"shipagent.status"})
    )
    for token_scopes in token_order:
        result = await service.resolve(**strict_request(scopes=set(token_scopes)))
        assert result.scopes == frozenset({"shipagent.status"})
    connection = await control_db.get(ProviderConnection, first.provider_connection_id)
    assert connection.allowed_scopes_text == "shipagent.status"
    assert connection.scopes_text == ""
    with pytest.raises(PermissionError):
        await service.reduce_link_scopes(
            first.account_id, first.provider_connection_id, STRICT_POLICY
        )


async def test_revoked_tuple_stays_denied_and_new_grant_is_distinct(control_db):
    service = strict_service(control_db)
    first = await service.resolve(**strict_request())
    await service.revoke_link(first.account_id, first.provider_connection_id)
    with pytest.raises(PermissionError):
        await service.resolve(**strict_request())
    new = await service.resolve(**strict_request("new_grant"))
    assert new.provider_connection_id != first.provider_connection_id
    assert new.link_epoch != first.link_epoch
    old = await control_db.get(ProviderConnection, first.provider_connection_id)
    assert old.status == "revoked" and old.link_epoch == first.link_epoch


async def test_legacy_account_cannot_be_implicitly_issuer_bound(control_db):
    legacy = AuthorizationService(
        control_db, ProviderClientRegistry({"chatgpt-client": "chatgpt"})
    )
    old = await legacy.resolve(
        subject="strict-owner", client_id="chatgpt-client", scopes={"jobs:read"}
    )
    with pytest.raises(PermissionError):
        await strict_service(control_db).resolve(**strict_request())
    account = await control_db.get(CloudAccount, old.account_id)
    assert account.issuer is None
    connection = await control_db.get(ProviderConnection, old.provider_connection_id)
    assert connection.link_epoch is None


@pytest.mark.parametrize("strict", [True, False])
async def test_bound_account_rejects_wrong_issuer_through_either_path(
    control_db, strict
):
    service = strict_service(control_db)
    first = await service.resolve(**strict_request())
    args = strict_request(issuer="https://another.invalid/")
    if not strict:
        args["issuer_link_id"] = None
    with pytest.raises(PermissionError):
        await service.resolve(**args)
    assert (
        await control_db.get(CloudAccount, first.account_id)
    ).issuer == STRICT_ISSUER


async def test_strict_resolution_requires_explicit_trusted_policy(control_db):
    service = AuthorizationService(
        control_db, ProviderClientRegistry({"chatgpt-client": "chatgpt"})
    )
    with pytest.raises(PermissionError):
        await service.resolve(**strict_request())
    assert await control_db.scalar(select(CloudAccount)) is None


@pytest.mark.parametrize(
    "change",
    [
        {"operation_deadline": 0},
        {"operation_deadline": float("inf")},
        {"token_expires_at": True},
        {"token_expires_at": 0},
        {"issuer_link_id": "../bad"},
        {"issuer": None},
    ],
)
async def test_invalid_strict_request_denied_before_account_creation(
    control_db, change
):
    with pytest.raises(PermissionError):
        await strict_service(control_db).resolve(**strict_request(**change))
    assert await control_db.scalar(select(CloudAccount)) is None


async def test_narrow_initial_token_does_not_set_policy(control_db):
    service = strict_service(control_db)
    first = await service.resolve(**strict_request(scopes={"shipagent.status"}))
    second = await service.resolve(**strict_request())
    assert first.scopes == frozenset({"shipagent.status"})
    assert second.scopes == STRICT_POLICY
    assert first.link_epoch == second.link_epoch


@pytest.mark.parametrize(
    "policy",
    [set(STRICT_POLICY), frozenset({"shipagent.execute"}), frozenset({"unknown"})],
)
def test_untrusted_policy_is_rejected(control_db, policy):
    with pytest.raises(ValueError):
        AuthorizationService(
            control_db,
            ProviderClientRegistry({"chatgpt-client": "chatgpt"}),
            link_allowed_scopes=policy,
        )


async def test_missing_issuer_cannot_bypass_bound_account(control_db):
    service = strict_service(control_db)
    await service.resolve(**strict_request())
    with pytest.raises(PermissionError):
        await service.resolve(
            subject="strict-owner",
            client_id="chatgpt-client",
            scopes={"shipagent.status"},
        )


async def test_management_cannot_modify_foreign_or_legacy_connection(control_db):
    service = strict_service(control_db)
    current = await service.resolve(**strict_request())
    for method in (service.revoke_link,):
        with pytest.raises(PermissionError):
            await method("foreign-account", current.provider_connection_id)
    await service.revoke_link(current.account_id, current.provider_connection_id)
    await service.revoke_link(current.account_id, current.provider_connection_id)
    with pytest.raises(PermissionError):
        await service.reduce_link_scopes(
            current.account_id, current.provider_connection_id, frozenset()
        )


class _IdentityInterrupted(BaseException):
    pass


@pytest.mark.parametrize("interrupted", [False, True])
async def test_failed_rollback_retains_session_and_original_failure(
    control_db, monkeypatch, interrupted
):
    service = strict_service(control_db)
    original = (
        _IdentityInterrupted("private-interruption")
        if interrupted
        else PermissionError("original-denial")
    )

    async def fail_account(*args):
        raise original

    async def fail_rollback():
        raise RuntimeError("private-cleanup-failure")

    monkeypatch.setattr(service, "_ensure_account", fail_account)
    monkeypatch.setattr(control_db, "rollback", fail_rollback)
    with pytest.raises(type(original)) as caught:
        await service.resolve(**strict_request())
    assert caught.value is original
    assert service.db is control_db
    assert service.cleanup_pending
    # Restoring rollback cannot make an uncertain service usable again.
    monkeypatch.undo()
    with pytest.raises(PermissionError, match="unavailable"):
        await service.resolve(**strict_request())


async def test_timed_out_lookup_keeps_original_deadline_during_cleanup(
    control_db, monkeypatch
):
    import asyncio

    service = strict_service(control_db)
    release = asyncio.Event()
    entered = asyncio.Event()
    original_rollback = control_db.rollback

    async def stalled_account(*args):
        await asyncio.Event().wait()

    async def stalled_rollback():
        entered.set()
        await release.wait()
        await original_rollback()

    monkeypatch.setattr(service, "_ensure_account", stalled_account)
    monkeypatch.setattr(control_db, "rollback", stalled_rollback)
    deadline = time.monotonic() + 0.03
    task = asyncio.create_task(
        service.resolve(**strict_request(operation_deadline=deadline))
    )
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        assert not task.done()
        # Task 1 retains the exact session while cleanup is pending. Bounded
        # HTTP retirement is the later captured pre-auth owner's obligation.
        assert service.db is control_db
        assert service.cleanup_pending
    finally:
        release.set()
        with pytest.raises(PermissionError):
            await task
    assert not service.cleanup_pending
