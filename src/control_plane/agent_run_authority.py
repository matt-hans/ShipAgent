"""Captured local qualification authority; no production app opts into this module.

Local SQLite commit and the original PostgreSQL commit are independent facts.
An exact owner's tasks and handles survive timeout/cancellation until explicit
retirement; no clock check, cancelled waiter or replacement connection proves it.
"""

from __future__ import annotations

import asyncio
import math
import os
import threading
import time
import weakref

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.auth.jwt_verifier import TokenPrincipal
from src.control_plane.auth.provider_clients import ProviderClientRegistry
from src.control_plane.auth.service import STRICT_LINK_SCOPES, AuthorizationService
from src.control_plane.models import CloudAccount, ProviderConnection
from src.services.agent_runs.authority import (
    AuthorizedRunDispatch,
    RunDispatchPermit,
    RunRequestAuthority,
)
from src.services.agent_runs.store import AgentRun

_UNAVAILABLE = "Agent run authority is unavailable."
_CLEANUP_SECONDS = 1.0
_SAFE_ACTION_ERRORS = frozenset(
    {
        "Invalid source-free task.",
        "Request key was already used for a different task.",
        "Agent run capacity is unavailable.",
        "Conversation revision or follow-up is unavailable.",
        "Conversation turn limit reached.",
        "Conversation continuation is unavailable.",
    }
)


class _RetirementBusy(RuntimeError):
    pass


class PostgresAgentRunAuthority:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        account_id: str,
        execution_target_id: str,
        issuer: str,
        clients: dict[str, str],
        clock=time.time,
        monotonic=time.monotonic,
    ):
        if (
            type(engine) is not AsyncEngine
            or engine.dialect.name != "postgresql"
            or engine.dialect.driver != "asyncpg"
        ):
            raise ValueError("Unsupported authority database.")
        self._engine = engine
        self._account_id = account_id
        self._target_id = execution_target_id
        self._issuer = issuer
        self._clients = ProviderClientRegistry(clients)
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._clock, self._monotonic = clock, monotonic

    def begin_http_operation(self, service, deadline: float):
        if (
            service.store.account_id != self._account_id
            or service.store.execution_target_id != self._target_id
        ):
            raise PermissionError(_UNAVAILABLE)
        owner = AgentRunAuthorityOwner(self, service, deadline)
        service._admit_authority_operation(owner)
        try:
            owner._borrow, owner._generation = service.borrow_coordinator()
            owner._identity_session = self._sessions()
            owner._identity_service = AuthorizationService(
                owner._identity_session,
                self._clients,
                link_allowed_scopes=STRICT_LINK_SCOPES,
            )
            owner._remaining()
        except BaseException:
            owner._latch()
            # No async effects have started. Captured session/borrow still belong
            # to this installed owner and explicit service cleanup can retire it.
            raise
        return owner

    def _request_owner(self, service, request):
        owner = service._authority_operation
        if (
            type(owner) is not AgentRunAuthorityOwner
            or owner._authority is not self
            or owner._service is not service
            or owner._request is not request
            or type(request) is not RunRequestAuthority
        ):
            raise PermissionError(_UNAVAILABLE)
        owner._identity()
        if owner._used or owner._retired or owner._failed:
            raise PermissionError(_UNAVAILABLE)
        return owner

    async def submit(self, service, request, *, task, mode, request_key):
        return await self._request_owner(service, request)._run(
            "accept", {"task": task, "mode": mode, "request_key": request_key}
        )

    async def continue_turn(
        self,
        service,
        request,
        *,
        conversation_reference,
        run_reference,
        expected_revision,
        task,
        request_key,
    ):
        return await self._request_owner(service, request)._run(
            "continue_turn",
            {
                "conversation_reference": conversation_reference,
                "run_reference": run_reference,
                "expected_revision": expected_revision,
                "task": task,
                "request_key": request_key,
            },
        )

    async def read(self, service, request, *, run_reference):
        return await self._request_owner(service, request)._run(
            "read", {"run_reference": run_reference}
        )

    async def cancel(self, service, request, *, run_reference):
        return await self._request_owner(service, request)._run(
            "cancel", {"run_reference": run_reference}
        )

    def _begin_worker(self, service, run):
        if (
            type(run) is not AgentRun
            or service._active_run is not run
            or service.store.account_id != self._account_id
            or service.store.execution_target_id != self._target_id
            or run.state != "running"
            or run.link_epoch is None
            or run.claim_generation != service._generation
        ):
            raise PermissionError(_UNAVAILABLE)
        try:
            now, utc = self._monotonic(), self._clock()
            expiry = run.turn_authority_expires_at
            if any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in (now, utc, expiry, run.expires_at)
            ):
                raise ValueError
            remaining = min(expiry, run.expires_at) - utc
            if remaining <= 0:
                raise ValueError
        except Exception:
            raise PermissionError(_UNAVAILABLE) from None
        owner = AgentRunAuthorityOwner(self, service, now + min(2, remaining))
        owner._worker_run = run
        owner._identity_retired = True
        owner._dispatch_deadline = now + min(remaining, service._model_timeout_seconds)
        service._admit_authority_operation(owner)
        try:
            owner._borrow, owner._generation = service.borrow_coordinator()
            owner._remaining()
        except BaseException as exc:
            owner._retain(exc)
            raise
        return owner

    async def admit_dispatch(self, service, run):
        if service._authority_dispatch_run is run:
            raise PermissionError(_UNAVAILABLE)
        owner = self._begin_worker(service, run)
        service._authority_dispatch_run = run
        history = await owner._run("dispatch", {})
        permit = RunDispatchPermit(
            service=service,
            run=run,
            generation=owner._generation,
            deadline=owner._dispatch_deadline,
            clock=self._clock,
            monotonic=self._monotonic,
        )
        return AuthorizedRunDispatch(permit, history)

    async def publish(
        self, service, run, *, outcome, private_history, clarification=None
    ):
        owner = self._begin_worker(service, run)
        await owner._run(
            "publish",
            {
                "outcome": outcome,
                "private_history": private_history,
                "clarification": clarification,
            },
        )


class AgentRunAuthorityOwner:
    def __init__(self, authority, service, deadline):
        self._self = weakref.ref(self)
        self._pid, self._thread = os.getpid(), threading.get_ident()
        self._authority, self._service = authority, service
        self._deadline = deadline
        self._borrow = None
        self._generation = 0
        self._identity_session = self._identity_service = None
        self._identity_retired = False
        self._context = self._request = None
        self._worker_run = None
        self._pending = None
        self._pending_name = None
        self._failed = False
        self._failure = None
        self._used = self._retired = False
        self._target = None
        self._connection = self._transaction = self._evidence_transaction = None
        self._driver = self._raw = self._sync = None
        self._backend = self._xid = None
        self._connect_attempted = self._connected = False
        self._pg_attempted = self._pg_known = False
        self._pg_rollback_known = False
        self._local_attempted = self._local_known = False
        self._reference_expiry = None
        self._result = None
        self._safe_error = None
        self._retiring = False
        self._remaining()

    def _identity(self):
        if (
            self._self() is not self
            or self._pid != os.getpid()
            or self._thread != threading.get_ident()
        ):
            raise RuntimeError(_UNAVAILABLE)

    @property
    def retirement_completed(self):
        self._identity()
        return self._retired

    @property
    def local_commit_attempted(self):
        return self._local_attempted

    @property
    def local_commit_known(self):
        return self._local_known

    @property
    def postgres_commit_known(self):
        return self._pg_known

    @property
    def original_xid(self):
        return self._xid

    def _remaining(self, *, response=False):
        self._identity()
        try:
            now = self._authority._monotonic()
            utc = self._authority._clock()
            if any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (now, utc, self._deadline)
            ):
                raise ValueError
            remaining = self._deadline - now
            if remaining <= 0 or remaining > 2.001:
                raise ValueError
            if self._request is not None:
                remaining = min(remaining, self._request.token_expires_at - utc)
            if self._worker_run is not None:
                remaining = min(
                    remaining,
                    self._worker_run.turn_authority_expires_at - utc,
                    self._worker_run.expires_at - utc,
                )
            if response and self._reference_expiry is not None:
                remaining = min(remaining, self._reference_expiry - utc)
            if remaining <= 0:
                raise ValueError
            return remaining
        except Exception:
            raise PermissionError(_UNAVAILABLE) from None

    def _latch(self, failure=None):
        self._failed = True
        if self._failure is None and failure is not None:
            self._failure = failure

    def _retain(self, failure=None):
        self._latch(failure)
        self._service._unhealthy = True

    async def _stage(self, name, coroutine, *, deadline):
        self._identity()
        if self._pending is not None:
            coroutine.close()
            raise RuntimeError(_UNAVAILABLE)
        self._pending_name = name
        self._pending = asyncio.create_task(coroutine)
        task = self._pending
        try:
            left = max(0, deadline - self._authority._monotonic())
            done, _ = await asyncio.wait({task}, timeout=left)
            if not done:
                task.cancel()
                self._retain()
                raise RuntimeError(_UNAVAILABLE)
            self._pending = self._pending_name = None
            return task.result()
        except BaseException as exc:
            self._latch(exc)
            if self._pending is not None:
                task.cancel()
                self._retain(exc)
            raise

    async def resolve(self, principal: TokenPrincipal):
        self._identity()
        if (
            self._context is not None
            or self._request is not None
            or self._failed
            or self._retired
        ):
            raise PermissionError(_UNAVAILABLE)
        if (
            type(principal) is not TokenPrincipal
            or principal.issuer != self._authority._issuer
        ):
            raise PermissionError(_UNAVAILABLE)
        try:
            self._context = await self._stage(
                "identity",
                self._identity_service.resolve(
                    subject=principal.subject,
                    client_id=principal.client_id,
                    scopes=set(principal.scopes),
                    auth_time=principal.auth_time,
                    issuer=principal.issuer,
                    issuer_link_id=principal.issuer_link_id,
                    token_expires_at=principal.expires_at,
                    operation_deadline=self._deadline,
                ),
                deadline=self._deadline,
            )
            await self._stage(
                "identity-close", self._close_identity(), deadline=self._deadline
            )
            self._remaining()
            return self._context
        except BaseException as exc:
            self._latch(exc)
            try:
                await self.close(deadline=self._deadline)
            except BaseException:
                self._retain(exc)
            if isinstance(exc, Exception):
                raise PermissionError(_UNAVAILABLE) from None
            raise

    def bind_request(self, context: AuthorizationContext):
        self._identity()
        if (
            type(context) is not AuthorizationContext
            or context is not self._context
            or self._request is not None
            or self._failed
            or self._retired
        ):
            raise PermissionError(_UNAVAILABLE)
        if (
            context.account_id != self._authority._account_id
            or context.issuer != self._authority._issuer
            or context.operation_deadline != self._deadline
        ):
            raise PermissionError(_UNAVAILABLE)
        self._request = RunRequestAuthority(
            account_id=context.account_id,
            connection_id=context.provider_connection_id,
            expected_epoch=context.link_epoch,
            issuer=context.issuer,
            surface=context.provider_surface,
            scopes=context.scopes,
            execution_target_id=self._authority._target_id,
            token_expires_at=context.token_expires_at,
            operation_deadline=self._deadline,
        )
        self._remaining()
        return self._request

    async def _connect(self):
        self._connect_attempted = True
        await self._connection.start()
        self._connected = True
        self._sync = self._connection.sync_connection
        if self._connection.closed or self._connection.invalidated:
            raise RuntimeError(_UNAVAILABLE)
        self._raw = await self._connection.get_raw_connection()
        self._driver = self._raw.driver_connection
        if type(self._driver).__module__ != "asyncpg.connection":
            raise RuntimeError(_UNAVAILABLE)
        self._backend = self._driver.get_server_pid()

    def _physical(self, sync):
        if (
            sync is not self._sync
            or sync.closed
            or sync.invalidated
            or self._driver is None
            or self._driver.is_closed()
            or self._raw.driver_connection is not self._driver
            or sync.connection is not self._raw
            or self._driver.get_server_pid() != self._backend
        ):
            raise RuntimeError(_UNAVAILABLE)

    def _query(self, sync, statement, parameters=None):
        self._physical(sync)
        self._remaining()
        result = sync.execute(statement, parameters or {})
        try:
            value = result.mappings().first()
        finally:
            result.close()
        self._physical(sync)
        self._remaining()
        return value

    def _validate(self, sync, *, scope):
        if self._failed:
            raise PermissionError(_UNAVAILABLE)
        self._borrow.require_owned()
        if self._service._generation != self._generation or self._service._closing:
            raise PermissionError(_UNAVAILABLE)
        request = self._request
        account_id = self._authority._account_id
        connection_id = (
            request.connection_id
            if request is not None
            else self._worker_run.connection_id
        )
        epoch = (
            request.expected_epoch
            if request is not None
            else self._worker_run.link_epoch
        )
        ms = str(max(1, int(self._remaining() * 1000)))
        self._query(
            sync,
            text(
                "SELECT set_config('statement_timeout',:ms,true),set_config('lock_timeout',:ms,true)"
            ),
            {"ms": ms},
        )
        account = self._query(
            sync,
            select(CloudAccount.__table__)
            .where(CloudAccount.id == account_id)
            .with_for_update(),
        )
        link = self._query(
            sync,
            select(ProviderConnection.__table__)
            .where(ProviderConnection.id == connection_id)
            .with_for_update(),
        )
        if (
            account is None
            or account["suspended"] is not False
            or account["issuer"] != self._authority._issuer
            or link is None
            or link["account_id"] != account["id"]
            or link["status"] != "active"
            or link["link_epoch"] != epoch
            or link["issuer_link_id"] is None
            or (request is not None and link["surface"] != request.surface)
            or link["allowed_scopes_text"] is None
        ):
            raise PermissionError(_UNAVAILABLE)
        if self._authority._clients.surface_for(link["client_id"]) != link["surface"]:
            raise PermissionError(_UNAVAILABLE)
        ceiling = frozenset(link["allowed_scopes_text"].split())
        if not ceiling <= STRICT_LINK_SCOPES or scope not in ceiling & (
            request.scopes if request is not None else STRICT_LINK_SCOPES
        ):
            raise PermissionError(_UNAVAILABLE)
        row = self._query(
            sync,
            text(
                "SELECT pg_backend_pid() AS pid, pg_current_xact_id() AS xid, current_setting('server_version_num')::int AS version"
            ),
        )
        if row["pid"] != self._backend or not 170000 <= row["version"] < 180000:
            raise PermissionError(_UNAVAILABLE)
        if self._xid is None:
            self._xid = row["xid"]
        elif self._xid != row["xid"]:
            raise PermissionError(_UNAVAILABLE)
        return True

    async def _core(self, action, arguments):
        self._target = self._service.store.transaction(
            borrow=self._borrow,
            generation=self._generation,
            monotonic=self._authority._monotonic,
        )
        self._target.acquire(deadline=self._deadline)
        self._connection = self._authority._engine.connect()
        await self._connect()
        self._transaction = self._connection.begin()
        await self._transaction.start()
        scope = "shipagent.status" if action == "read" else "shipagent.preview"

        def perform(sync):
            def current():
                return self._validate(sync, scope=scope)

            current()
            args = {**arguments, "authority": current}
            if self._request is not None:
                args.update(
                    connection_id=self._request.connection_id,
                    link_epoch=self._request.expected_epoch,
                )
                if action in {"accept", "continue_turn"}:
                    args["token_expires_at"] = self._request.token_expires_at
            try:
                try:
                    if action == "dispatch":
                        self._result = self._target.history(
                            self._worker_run, authority=current
                        )
                    elif action == "publish":
                        self._target.finish(self._worker_run, **args)
                    else:
                        self._result = getattr(self._target, action)(**args)
                except ValueError as exc:
                    if type(exc) is ValueError and str(exc) in _SAFE_ACTION_ERRORS:
                        self._safe_error = exc
                    raise
                current()
                self._target.commit()
            finally:
                self._local_attempted = self._target.commit_attempted
                self._local_known = self._target.commit_known
                self._reference_expiry = self._target.reference_expires_at

        await self._connection.run_sync(perform)
        await self._connection.run_sync(lambda sync: self._validate(sync, scope=scope))
        self._pg_attempted = True
        await self._commit_postgres()
        self._physical(self._sync)
        self._remaining()
        self._evidence_transaction = self._connection.begin()
        await self._evidence_transaction.start()

        def status(sync):
            row = self._query(
                sync,
                text(
                    "SELECT pg_backend_pid() AS pid, pg_xact_status(CAST(:x AS xid8)) AS status"
                ),
                {"x": self._xid},
            )
            if row["pid"] != self._backend or row["status"] != "committed":
                raise RuntimeError(_UNAVAILABLE)
            self._pg_known = True

        await self._connection.run_sync(status)

    async def _commit_postgres(self):
        await self._transaction.commit()

    async def _run(self, action, arguments):
        self._used = True
        failure = None
        retirement_failed = False
        try:
            self._remaining()
            await self._stage(
                "authority", self._core(action, arguments), deadline=self._deadline
            )
        except BaseException as exc:
            failure = exc
            self._latch(exc)
        try:
            await self.close(deadline=self._deadline)
        except BaseException as exc:
            retirement_failed = True
            if self._retired or isinstance(exc, _RetirementBusy):
                self._latch(exc)
            else:
                self._retain(exc)
            if failure is None or (
                isinstance(failure, Exception) and not isinstance(exc, Exception)
            ):
                failure = exc
        if failure is not None and not isinstance(failure, Exception):
            raise failure
        self._remaining(response=True)
        if not self._retired or retirement_failed:
            raise RuntimeError(_UNAVAILABLE) from None
        if failure is not None:
            if (
                failure is self._safe_error
                and not self._local_attempted
                and not self._pg_attempted
                and self._pg_rollback_known
            ):
                raise ValueError(str(self._safe_error)) from None
            if isinstance(failure, PermissionError):
                raise PermissionError(_UNAVAILABLE) from None
            raise RuntimeError(_UNAVAILABLE) from None
        if (
            self._failed
            or not self._local_known
            or not self._pg_known
            or not self._retired
        ):
            raise RuntimeError(_UNAVAILABLE)
        return self._result

    async def _close_identity(self):
        if self._identity_session is not None:
            await self._identity_session.close()
        self._identity_retired = True

    async def _close_pg(self):
        if self._connection is not None:
            original_rollback = False
            try:
                self._physical(self._sync)
                original_rollback = (
                    self._transaction is not None
                    and self._transaction.is_active
                    and self._connection.get_transaction() is self._transaction
                    and self._driver.is_in_transaction()
                    and not self._pg_attempted
                )
            except Exception:
                # Cleanup still closes the captured object. This cannot prove
                # authorization for a descriptive precommit denial.
                pass
            await self._connection.rollback()
            if original_rollback:
                self._physical(self._sync)
                if (
                    not self._driver.is_in_transaction()
                    and not self._transaction.is_active
                    and not self._connection.in_transaction()
                ):
                    self._pg_rollback_known = True
            await self._connection.close()
            if not self._connection.closed:
                raise RuntimeError(_UNAVAILABLE)
            self._connection = None

    async def close(self, *, deadline=None):
        self._identity()
        if self._retiring:
            raise _RetirementBusy("Agent run authority cleanup is busy.")
        self._retiring = True
        try:
            await self._retire(deadline=deadline)
        except Exception:
            raise RuntimeError(_UNAVAILABLE) from None
        finally:
            self._retiring = False

    async def _retire(self, *, deadline=None):
        if self._retired:
            if self._service._authority_operation is self:
                self._service._release_authority_operation(self)
            return
        if deadline is None:
            deadline = self._authority._monotonic() + _CLEANUP_SECONDS
        try:
            if self._pending is not None:
                task = self._pending
                done, _ = await asyncio.wait(
                    {task}, timeout=max(0, deadline - self._authority._monotonic())
                )
                if not done:
                    raise RuntimeError(_UNAVAILABLE)
                self._pending = self._pending_name = None
                try:
                    task.result()
                except BaseException as exc:
                    self._latch(exc)
            if not self._identity_retired:
                await self._stage(
                    "identity-close", self._close_identity(), deadline=deadline
                )
            if self._connect_attempted and not self._connected:
                raise RuntimeError(_UNAVAILABLE)
            if self._connection is not None:
                await self._stage("postgres-close", self._close_pg(), deadline=deadline)
            if self._target is not None:
                self._local_attempted = self._target.commit_attempted
                self._local_known = self._target.commit_known
                self._reference_expiry = self._target.reference_expires_at
                self._target.retire()
                self._target = None
            if self._borrow is not None:
                try:
                    self._borrow.retire()
                except BaseException:
                    if self._borrow.retirement_completed:
                        self._borrow = None
                        self._retired = True
                        self._service._release_authority_operation(self)
                    raise
                self._borrow = None
            self._retired = True
            self._service._release_authority_operation(self)
        except BaseException as exc:
            if self._retired:
                self._latch(exc)
            else:
                self._retain(exc)
            raise
