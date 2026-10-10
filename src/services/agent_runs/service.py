"""An explicit target worker owns accepted source-free model turns."""

from __future__ import annotations

import asyncio
import logging
import math
import weakref
from collections.abc import Callable
from contextlib import aclosing, suppress

from src.services.agent_runs.clarification import ClarificationProvider
from src.services.agent_runs.coordinator import (
    CoordinatorBorrow,
    CoordinatorLease,
    SourceStorageBinding,
    SourceWorkKind,
)
from src.services.agent_runs.store import AgentRun, AgentRunStore
from src.services.agent_session_manager import AgentSession, AgentSessionManager
from src.services.conversation_handler import process_message
from src.services.conversation_runtime.models import ModelProviderClient
from src.services.source_free_conversation import SourceFreeConversationConfig

logger = logging.getLogger(__name__)

# Synthetic trusted shutdown budget; no claim of aborting in-flight billing.
_CLEANUP_TIMEOUT_SECONDS = 1.0


class AgentRunService:
    def __init__(
        self,
        *,
        store: AgentRunStore,
        provider_factory: Callable[[str], ModelProviderClient],
        model_timeout_seconds: float = 30,
        connection_epoch: Callable[[str], str | None] | None = None,
    ) -> None:
        if (
            isinstance(model_timeout_seconds, bool)
            or not isinstance(model_timeout_seconds, (int, float))
            or not math.isfinite(model_timeout_seconds)
            or not 0 < model_timeout_seconds <= 120
        ):
            raise ValueError("Model deadline must be positive and at most 120 seconds.")
        self._model_timeout_seconds = model_timeout_seconds
        self.store = store
        self._connection_epoch = connection_epoch
        self._provider_factory = provider_factory
        self._owned_providers: weakref.WeakValueDictionary[int, ModelProviderClient] = (
            weakref.WeakValueDictionary()
        )
        self._sessions = AgentSessionManager()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._lease: CoordinatorLease | None = None
        self._unhealthy = False
        self._generation = 0
        self._active_run: AgentRun | None = None
        self._active_task: asyncio.Task | None = None
        self._cancel_requested = asyncio.Event()
        self._owned_tasks: set[asyncio.Task] = set()
        self._closing = False

    async def start(self) -> None:
        if self._worker is not None or self._lease is not None or self._owned_tasks:
            raise RuntimeError("Agent run service is already started.")
        self._lease = CoordinatorLease(self.store.path.with_suffix(".coordinator.lock"))
        try:
            self._lease.require_owned()
            self.store.upgrade(lease=self._lease)
            self._generation = self.store.begin_coordinator(lease=self._lease)
        except BaseException:
            # A retained migration borrow must outlive failed SQL cleanup.
            # Preserve the original interruption even if lease close also denies.
            try:
                self._lease.close()
            except BaseException:
                self._unhealthy = True
            else:
                self._lease = None
            raise
        self._unhealthy = False
        self._closing = False
        self._worker = asyncio.create_task(self._drain())
        self._worker.add_done_callback(self._observe_worker)

    def _observe_worker(self, task: asyncio.Task) -> None:
        if (
            not task.cancelled()
            and task.exception() is not None
            and task is self._worker
        ):
            self._unhealthy = True
            logger.error("Agent run coordinator is unavailable.")

    async def close(self) -> None:
        """Bound shutdown without releasing a lease above still-live owned work."""
        self._closing = True
        if self._lease is not None:
            self._lease.begin_close()
        self._signal_active_cancel()
        self._wake.set()
        tasks = {task for task in self._owned_tasks if not task.done()}
        if self._worker is not None and not self._worker.done():
            tasks.add(self._worker)
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=_CLEANUP_TIMEOUT_SECONDS)
            if pending or any(not task.done() for task in self._owned_tasks):
                self._unhealthy = True
                raise RuntimeError("Agent run cleanup is unavailable.")
        self._active_run = None
        self._active_task = None
        self._worker = None
        if self._lease is not None:
            self.store.retire_upgrade()
            self._lease.close()
            self._lease = None

    def source_storage_binding(self) -> SourceStorageBinding:
        """Read current exact storage readiness without opening a transaction."""
        self._require_worker()
        if self._lease is None:
            raise RuntimeError("Agent run coordinator is unavailable.")
        binding = self._lease.source_storage_binding()
        self._require_source_binding(binding)
        return binding

    def _require_source_binding(self, binding: SourceStorageBinding) -> None:
        if (
            type(binding) is not SourceStorageBinding
            or binding.generation != self._generation
            or binding.account_id != self.store.account_id
            or binding.execution_target_id != self.store.execution_target_id
        ):
            raise RuntimeError("Agent run coordinator is unavailable.")

    def borrow_coordinator(
        self,
        *,
        source_work: SourceWorkKind | None = None,
        source_binding: SourceStorageBinding | None = None,
    ) -> tuple[CoordinatorBorrow, int]:
        """Pin available ownership without database, authority or model work.

        The consumer must validate the captured generation in its own bounded
        transaction. This accessor deliberately does not open that transaction.
        """
        self._require_worker()
        if self._lease is None:
            raise RuntimeError("Agent run coordinator is unavailable.")
        if source_binding is None:
            return self._lease.borrow(source_work=source_work), self._generation
        self._require_source_binding(source_binding)
        return self._lease.borrow(
            source_work=source_work, source_binding=source_binding
        ), self._generation

    def _own_task(self, task: asyncio.Task) -> asyncio.Task:
        self._owned_tasks.add(task)

        def observe(done: asyncio.Task) -> None:
            self._owned_tasks.discard(done)
            if not done.cancelled():
                # Retained quarantined work may finish after its coordinator.
                # Retrieve failures without exposing provider exception text.
                done.exception()

        task.add_done_callback(observe)
        return task

    def _signal_active_cancel(self) -> None:
        if (
            self._active_task is not None
            and not self._active_task.done()
            and not self._cancel_requested.is_set()
        ):
            self._cancel_requested.set()
            self._active_task.cancel()

    def _authority(self, connection_id: str) -> tuple[str | None, Callable[[], bool]]:
        if self._connection_epoch is None:
            return None, lambda: self._connection_epoch is None
        try:
            epoch = self._connection_epoch(connection_id)
            if not isinstance(epoch, str) or not 1 <= len(epoch) <= 128:
                raise ValueError
        except Exception:
            raise PermissionError("Provider Connection is unavailable.") from None

        def current() -> bool:
            try:
                return (
                    self._connection_epoch is not None
                    and self._connection_epoch(connection_id) == epoch
                )
            except Exception:
                return False

        return epoch, current

    def submit(self, *, connection_id: str, arguments: dict) -> dict[str, object]:
        self._require_worker()
        self._require_coordinator()
        epoch, authority = self._authority(connection_id)
        run = self.store.accept(
            connection_id=connection_id,
            task=arguments["task"],
            mode=arguments["mode"],
            request_key=arguments["request_key"],
            generation=self._generation,
            link_epoch=epoch,
            authority=authority,
        )
        self._wake.set()
        return run.public_result()

    def continue_turn(
        self, *, connection_id: str, arguments: dict
    ) -> dict[str, object]:
        self._require_worker()
        self._require_coordinator()
        epoch, authority = self._authority(connection_id)
        if epoch is None:
            raise PermissionError("Continuation authority is unavailable.")
        run = self.store.continue_turn(
            connection_id=connection_id,
            link_epoch=epoch,
            authority=authority,
            generation=self._generation,
            conversation_reference=arguments["conversation_reference"],
            run_reference=arguments["run_reference"],
            expected_revision=arguments["expected_revision"],
            task=arguments["task"],
            request_key=arguments["request_key"],
        )
        self._wake.set()
        return run.public_result()

    def read(self, *, connection_id: str, run_reference: str) -> dict[str, object]:
        epoch, authority = self._authority(connection_id)
        run = self.store.read(
            connection_id=connection_id,
            run_reference=run_reference,
            link_epoch=epoch,
            authority=authority,
        )
        if run.state in {"queued", "running"}:
            self._require_worker()
            self._require_coordinator()
        return run.public_result()

    def cancel(self, *, connection_id: str, run_reference: str) -> dict[str, object]:
        """Fence future work durably before signaling the exact owned turn.

        This synchronous seam never makes cleanup depend on the MCP caller's
        lifetime. Cancellation does not undo an in-flight provider charge.
        """
        self._require_coordinator()
        epoch, authority = self._authority(connection_id)
        run = self.store.cancel(
            connection_id=connection_id,
            run_reference=run_reference,
            generation=self._generation,
            link_epoch=epoch,
            authority=authority,
        )
        if (
            run.state == "cancelled"
            and self._active_run is not None
            and self._active_run.run_reference == run.run_reference
        ):
            self._signal_active_cancel()
        return run.public_result()

    def _require_worker(self) -> None:
        if (
            self._worker is None
            or self._worker.done()
            or self._unhealthy
            or self._closing
        ):
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _require_coordinator(self) -> None:
        if self._lease is None:
            raise RuntimeError("Agent run coordinator is unavailable.")
        self._lease.require_owned()
        if not self.store.is_current_generation(self._generation):
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _epoch_active(self, run: AgentRun) -> bool:
        try:
            epoch, authority = self._authority(run.connection_id)
            return epoch == run.link_epoch and authority()
        except Exception:
            return False

    def _run_active(self, run: AgentRun) -> bool:
        if self._closing or self._unhealthy:
            return False
        try:
            self._require_coordinator()
            epoch, authority = self._authority(run.connection_id)
            return epoch == run.link_epoch and authority() and self.store.is_active(run)
        except Exception:
            return False

    def _activity_guard(self, run: AgentRun, *, deadline: float) -> Callable[[], bool]:
        authority_lost = False
        loop = asyncio.get_running_loop()

        def active() -> bool:
            nonlocal authority_lost
            if not authority_lost and (
                loop.time() >= deadline or not self._run_active(run)
            ):
                authority_lost = True
            return not authority_lost

        return active

    async def _drain(self) -> None:
        while not self._closing:
            if self._unhealthy:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._wake.clear()
            self._require_coordinator()
            run = self.store.claim_next(generation=self._generation)
            if run is None:
                await self._wake.wait()
                continue
            self._active_run = run
            self._cancel_requested = asyncio.Event()
            task = self._own_task(asyncio.create_task(self._execute(run)))
            self._active_task = task
            cancelled = asyncio.create_task(self._cancel_requested.wait())
            try:
                done, _ = await asyncio.wait(
                    {task, cancelled},
                    timeout=self._model_timeout_seconds + _CLEANUP_TIMEOUT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    # An in-process timeout relies on cancellation cooperation.
                    # This independent owner deadline fences even resistant I/O.
                    self._unhealthy = True
                    self._signal_active_cancel()
                    if self._lease is not None and self._lease.is_owned():
                        self.store.finish(
                            run, outcome="model_timeout", private_history=[]
                        )
                if not task.done():
                    _, pending = await asyncio.wait(
                        {task}, timeout=_CLEANUP_TIMEOUT_SECONDS
                    )
                    if pending:
                        self._unhealthy = True
                        raise RuntimeError("Agent run cleanup is unavailable.")
                # Run cancellation is expected and never cancels the coordinator.
                with suppress(asyncio.CancelledError):
                    task.result()
            finally:
                cancelled.cancel()
                with suppress(asyncio.CancelledError):
                    await cancelled
                if task.done():
                    self._active_run = None
                    self._active_task = None

    async def _execute(self, run: AgentRun) -> None:
        session = None
        outcome = "provider_failed"
        clarification = None
        deadline = asyncio.get_running_loop().time() + self._model_timeout_seconds
        active = self._activity_guard(run, deadline=deadline)

        try:
            async with asyncio.timeout(self._model_timeout_seconds):
                if not active():
                    outcome = "interrupted"
                    return
                provider = self._provider_factory(run.conversation_reference)
                if self._owned_providers.get(id(provider)) is provider:
                    raise RuntimeError(
                        "Provider instance already belongs to another conversation."
                    )
                self._owned_providers[id(provider)] = provider
                guarded_provider = ClarificationProvider(provider)
                session = self._sessions.get_or_create_session(
                    run.conversation_reference,
                    source_free_config=SourceFreeConversationConfig(
                        provider=guarded_provider,
                        is_run_active=active,
                        clarification_enabled=run.link_epoch is not None,
                    ),
                )
                session.history = self.store.prior_history(
                    run, authority=lambda: self._epoch_active(run)
                )
                session.add_message(
                    "user", run.task, turn_id=run.run_reference, queued=True
                )
                blocks = []
                async with aclosing(
                    process_message(session, run.task, turn_id=run.run_reference)
                ) as stream:
                    async for event in stream:
                        if event.get("event") == "error":
                            break
                        if event.get("event") == "agent_message":
                            blocks.append(event.get("data", {}).get("text", ""))
                            if len(blocks) > 1:
                                raise ValueError("Planning output is unavailable.")
                    else:
                        if (
                            not active()
                            or session.source_free_completed_turn != run.run_reference
                        ):
                            outcome = "interrupted"
                        elif blocks:
                            clarification = guarded_provider.clarification
                            if clarification is not None and run.link_epoch is None:
                                raise PermissionError(
                                    "Clarification authority is unavailable."
                                )
                            outcome = (
                                "clarification_required"
                                if clarification
                                else "planning_completed"
                            )
        except asyncio.CancelledError:
            outcome = "interrupted"
            raise
        except TimeoutError:
            outcome = "model_timeout"
        except Exception:
            outcome = "provider_failed"
        finally:
            try:
                if self._lease is not None and self._lease.is_owned():
                    self.store.finish(
                        run,
                        outcome=outcome,
                        private_history=session.history if session else [],
                        clarification=clarification,
                        authority=lambda: self._epoch_active(run),
                    )
            except BaseException:
                # Publication failure must fence admission before asynchronous
                # cleanup yields. The worker-done callback runs too late.
                self._unhealthy = True
                raise
            finally:
                if session is not None:
                    await self._cleanup_session(session)

    async def _cleanup_session(self, session: AgentSession) -> None:
        # Capture the original runtime before any asynchronous cleanup. Never
        # re-resolve an active runtime from a mutable session or provider slot.
        agent = session.agent
        session.terminating = True
        session.invalidate_active_turn_generation()

        async def cleanup() -> None:
            try:
                if agent is not None:
                    await agent.stop(timeout=_CLEANUP_TIMEOUT_SECONDS)
            finally:
                self._sessions.remove_session(session.session_id)

        task = self._own_task(asyncio.create_task(cleanup()))
        try:
            _, pending = await asyncio.wait({task}, timeout=_CLEANUP_TIMEOUT_SECONDS)
            if pending:
                self._unhealthy = True
                task.cancel()
                raise RuntimeError("Agent run cleanup is unavailable.")
            task.result()
        except asyncio.CancelledError:
            self._unhealthy = True
            task.cancel()
            raise
