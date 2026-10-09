"""Persistent account/link identity, distinct from accepted-run authority."""

import asyncio
import math
import time
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import LINK_ID_PATTERN, timestamp
from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.models import CloudAccount, ProviderConnection, new_id, utc_now

STRICT_LINK_SCOPES = frozenset({"shipagent.status", "shipagent.preview"})
IDENTITY_OPERATION_SECONDS = 2.0


class AuthorizationService:
    def __init__(
        self,
        db: AsyncSession,
        clients: ProviderClientRegistry,
        *,
        link_allowed_scopes: frozenset[str] | None = None,
    ) -> None:
        if link_allowed_scopes is not None and (
            type(link_allowed_scopes) is not frozenset
            or not link_allowed_scopes <= STRICT_LINK_SCOPES
        ):
            raise ValueError("invalid trusted provider link policy")
        self.db = db
        self.clients = clients
        self.link_allowed_scopes = link_allowed_scopes
        self._cleanup_pending = False
        self._failure: BaseException | None = None
        self._cleanup_failure: BaseException | None = None

    @property
    def cleanup_pending(self) -> bool:
        """The exact session still needs its enclosing owner's retirement."""
        return self._cleanup_pending

    def _require_available(self) -> None:
        if self._cleanup_pending or self._failure is not None:
            raise PermissionError("identity service unavailable")

    async def _rollback_after_failure(self, original: BaseException) -> None:
        # Keep the exact session and failure on this object. The strict HTTP
        # composition must capture this service before effects and own bounded
        # rollback/close; this identity primitive alone does not bound cleanup.
        self._cleanup_pending = True
        try:
            await self.db.rollback()
        except BaseException as cleanup:
            self._failure = original
            self._cleanup_failure = cleanup
            if isinstance(original, Exception) and not isinstance(cleanup, Exception):
                raise
        else:
            self._cleanup_pending = False

    @staticmethod
    def _remaining(deadline: float, expiry: float | None) -> float:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise PermissionError("invalid authorization deadline")
        remaining = deadline - time.monotonic()
        if expiry is not None:
            remaining = min(remaining, timestamp(expiry) - time.time())
        if remaining <= 0:
            raise PermissionError("authorization expired")
        return remaining

    async def _timeouts(self, deadline: float, expiry: float | None) -> None:
        remaining = self._remaining(deadline, expiry)
        if self.db.get_bind().dialect.name == "postgresql":
            # Connection acquisition and these statements also remain inside the
            # caller's original asyncio timeout. No per-query budget renewal.
            milliseconds = str(max(1, int(remaining * 1000)))
            await self.db.execute(
                text(
                    "SELECT set_config('statement_timeout', :ms, true), "
                    "set_config('lock_timeout', :ms, true)"
                ),
                {"ms": milliseconds},
            )
        self._remaining(deadline, expiry)

    async def _ensure_account(self, subject: str, issuer: str | None):
        dialect = self.db.get_bind().dialect.name
        insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
        if insert is None:
            raise PermissionError("unsupported identity store")
        # The unique subject is the creation race arbiter. No existing account
        # is updated or rebound by this insertion, including a legacy account.
        await self.db.execute(
            insert(CloudAccount)
            .values(
                id=new_id(),
                auth0_subject=subject,
                issuer=issuer,
                suspended=False,
                created_at=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["auth0_subject"])
        )
        return await self.db.scalar(
            select(CloudAccount)
            .where(
                CloudAccount.auth0_subject == subject,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def resolve(
        self,
        *,
        subject: str,
        client_id: str,
        scopes: set[str],
        auth_time: datetime | None = None,
        issuer: str | None = None,
        issuer_link_id: str | None = None,
        token_expires_at: float | None = None,
        operation_deadline: float | None = None,
    ) -> AuthorizationContext:
        self._require_available()
        strict = issuer_link_id is not None
        if any(
            type(value) is not str or not value.strip() or len(value) > 255
            for value in (subject, client_id)
        ):
            raise PermissionError("invalid identity")
        if issuer is not None and (
            type(issuer) is not str or not issuer or len(issuer) > 2048
        ):
            raise PermissionError("invalid issuer")
        if strict and (
            self.link_allowed_scopes is None
            or issuer is None
            or type(issuer_link_id) is not str
            or not LINK_ID_PATTERN.fullmatch(issuer_link_id)
            or token_expires_at is None
            or operation_deadline is None
        ):
            raise PermissionError("strict provider link proof required")
        deadline = (
            time.monotonic() + IDENTITY_OPERATION_SECONDS
            if operation_deadline is None
            else operation_deadline
        )
        remaining = self._remaining(deadline, token_expires_at)
        if remaining > IDENTITY_OPERATION_SECONDS:
            raise PermissionError("invalid authorization deadline")
        surface = self.clients.surface_for(client_id)
        try:
            async with asyncio.timeout(remaining):
                await self._timeouts(deadline, token_expires_at)
                account = await self._ensure_account(
                    subject, issuer if strict else None
                )
                self._remaining(deadline, token_expires_at)
                if account.suspended:
                    raise PermissionError("ShipAgent Cloud Account is suspended")
                if (strict and account.issuer is None) or (
                    account.issuer is not None and account.issuer != issuer
                ):
                    raise PermissionError("account issuer is not bound to this request")
                statement = (
                    select(ProviderConnection)
                    .where(
                        ProviderConnection.account_id == account.id,
                        ProviderConnection.client_id == client_id,
                        ProviderConnection.surface == surface,
                        ProviderConnection.issuer_link_id == issuer_link_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                connection = await self.db.scalar(statement)
                self._remaining(deadline, token_expires_at)
                if connection is None:
                    connection = ProviderConnection(
                        account_id=account.id,
                        client_id=client_id,
                        surface=surface,
                        status="active",
                        issuer_link_id=issuer_link_id,
                        link_epoch=uuid4().hex if strict else None,
                        allowed_scopes_text=(
                            " ".join(sorted(self.link_allowed_scopes))
                            if strict
                            else None
                        ),
                    )
                    self.db.add(connection)
                    await self.db.flush()
                if connection.status != "active":
                    raise PermissionError("Provider Connection is not active")
                if strict:
                    if (
                        not connection.link_epoch
                        or connection.allowed_scopes_text is None
                    ):
                        raise PermissionError("provider link is unbound")
                    ceiling = frozenset(connection.allowed_scopes_text.split())
                    if not ceiling <= STRICT_LINK_SCOPES:
                        raise PermissionError("invalid provider link policy")
                    effective = frozenset(scopes) & ceiling & self.link_allowed_scopes
                else:
                    connection.scopes_text = " ".join(sorted(scopes))
                    effective = frozenset(scopes)
                result = AuthorizationContext(
                    account_id=account.id,
                    provider_connection_id=connection.id,
                    provider_surface=surface,
                    subject=subject,
                    client_id=client_id,
                    scopes=effective,
                    auth_time=auth_time,
                    issuer=issuer,
                    link_epoch=connection.link_epoch,
                    token_expires_at=token_expires_at,
                    operation_deadline=deadline,
                )
                self._remaining(deadline, token_expires_at)
                await self.db.commit()
                self._remaining(deadline, token_expires_at)
                return result
        except BaseException as exc:
            await self._rollback_after_failure(exc)
            if isinstance(exc, (TimeoutError, SQLAlchemyError)):
                raise PermissionError("identity resolution unavailable") from None
            raise

    async def _change_link(
        self, account_id: str, connection_id: str, allowed_scopes: frozenset[str] | None
    ) -> None:
        self._require_available()
        deadline = time.monotonic() + IDENTITY_OPERATION_SECONDS
        try:
            async with asyncio.timeout(IDENTITY_OPERATION_SECONDS):
                await self._timeouts(deadline, None)
                account = await self.db.scalar(
                    select(CloudAccount)
                    .where(
                        CloudAccount.id == account_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if account is None or account.issuer is None:
                    raise PermissionError("provider link unavailable")
                connection = await self.db.scalar(
                    select(ProviderConnection)
                    .where(
                        ProviderConnection.id == connection_id,
                        ProviderConnection.account_id == account_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if connection is None or connection.link_epoch is None:
                    raise PermissionError("provider link unavailable")
                if allowed_scopes is None:
                    connection.status = "revoked"
                else:
                    ceiling = frozenset(connection.allowed_scopes_text.split())
                    if connection.status != "active" or not allowed_scopes <= ceiling:
                        raise PermissionError("provider link policy cannot expand")
                    connection.allowed_scopes_text = " ".join(sorted(allowed_scopes))
                self._remaining(deadline, None)
                await self.db.commit()
                self._remaining(deadline, None)
        except BaseException as exc:
            await self._rollback_after_failure(exc)
            if isinstance(exc, (TimeoutError, SQLAlchemyError)):
                raise PermissionError("provider link unavailable") from None
            raise

    async def revoke_link(self, account_id: str, connection_id: str) -> None:
        """Trusted management only; a revoked tuple is a permanent tombstone."""
        await self._change_link(account_id, connection_id, None)

    async def reduce_link_scopes(
        self, account_id: str, connection_id: str, allowed_scopes: frozenset[str]
    ) -> None:
        if (
            type(allowed_scopes) is not frozenset
            or not allowed_scopes <= STRICT_LINK_SCOPES
        ):
            raise PermissionError("invalid provider link policy")
        await self._change_link(account_id, connection_id, allowed_scopes)
