"""An explicit target worker owns accepted source-free model turns."""

from __future__ import annotations

import asyncio
import logging
import math
import weakref
from collections.abc import Callable
from contextlib import aclosing, suppress

from src.services.agent_runs.coordinator import CoordinatorLease
from src.services.agent_runs.store import AgentRun, AgentRunStore
from src.services.agent_session_manager import AgentSessionManager
from src.services.conversation_handler import process_message
from src.services.conversation_runtime.models import ModelProviderClient
from src.services.source_free_conversation import SourceFreeConversationConfig

logger = logging.getLogger(__name__)


class AgentRunService:
    def __init__(
        self,
        *,
        store: AgentRunStore,
        provider_factory: Callable[[str], ModelProviderClient],
        model_timeout_seconds: float = 30,
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

    async def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("Agent run service is already started.")
        self._lease = CoordinatorLease(self.store.path.with_suffix(".coordinator.lock"))
        try:
            self._lease.require_owned()
            self._generation = self.store.begin_coordinator(lease=self._lease)
        except BaseException:
            self._lease.close()
            self._lease = None
            raise
        self._unhealthy = False
        self._worker = asyncio.create_task(self._drain())
        self._worker.add_done_callback(self._observe_worker)

    def _observe_worker(self, task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            self._unhealthy = True
            logger.error("Agent run coordinator is unavailable.")

    async def close(self) -> None:
        try:
            if self._worker is not None:
                self._worker.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self._worker
                self._worker = None
        finally:
            if self._lease is not None:
                self._lease.close()
                self._lease = None

    def submit(self, *, connection_id: str, arguments: dict) -> dict[str, object]:
        self._require_worker()
        self._require_coordinator()
        run = self.store.accept(
            connection_id=connection_id,
            task=arguments["task"],
            mode=arguments["mode"],
            request_key=arguments["request_key"],
            generation=self._generation,
        )
        self._wake.set()
        return run.public_result()

    def read(self, *, connection_id: str, run_reference: str) -> dict[str, object]:
        run = self.store.read(connection_id=connection_id, run_reference=run_reference)
        if run.state in {"queued", "running"}:
            self._require_worker()
            self._require_coordinator()
        return run.public_result()

    def _require_worker(self) -> None:
        if self._worker is None or self._worker.done() or self._unhealthy:
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _require_coordinator(self) -> None:
        if self._lease is None:
            raise RuntimeError("Agent run coordinator is unavailable.")
        self._lease.require_owned()
        if not self.store.is_current_generation(self._generation):
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _run_active(self, run: AgentRun) -> bool:
        try:
            self._require_coordinator()
            return self.store.is_active(run)
        except Exception:
            return False

    def _activity_guard(self, run: AgentRun) -> Callable[[], bool]:
        authority_lost = False

        def active() -> bool:
            nonlocal authority_lost
            if not authority_lost and not self._run_active(run):
                authority_lost = True
            return not authority_lost

        return active

    async def _drain(self) -> None:
        while True:
            self._wake.clear()
            self._require_coordinator()
            run = self.store.claim_next(generation=self._generation)
            if run is None:
                await self._wake.wait()
                continue
            session = None
            outcome = "provider_failed"
            active = self._activity_guard(run)

            try:
                async with asyncio.timeout(self._model_timeout_seconds):
                    provider = self._provider_factory(run.conversation_reference)
                    if self._owned_providers.get(id(provider)) is provider:
                        raise RuntimeError(
                            "Provider instance already belongs to another conversation."
                        )
                    self._owned_providers[id(provider)] = provider
                    session = self._sessions.get_or_create_session(
                        run.conversation_reference,
                        source_free_config=SourceFreeConversationConfig(
                            provider=provider, is_run_active=active
                        ),
                    )
                    session.add_message(
                        "user", run.task, turn_id=run.run_reference, queued=True
                    )
                    saw_text = False
                    async with aclosing(
                        process_message(session, run.task, turn_id=run.run_reference)
                    ) as stream:
                        async for event in stream:
                            if event.get("event") == "error":
                                break
                            if event.get("event") == "agent_message":
                                saw_text = True
                        else:
                            if (
                                not active()
                                or session.source_free_completed_turn
                                != run.run_reference
                            ):
                                outcome = "interrupted"
                            elif saw_text:
                                outcome = "planning_completed"
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
                        )
                finally:
                    if session is not None:
                        try:
                            await self._sessions.stop_session_agent(
                                run.conversation_reference
                            )
                        finally:
                            self._sessions.remove_session(run.conversation_reference)
