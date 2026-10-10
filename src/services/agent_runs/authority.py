"""Private immutable inputs for the explicitly injected authenticated profile."""

from __future__ import annotations

import math
import os
import threading
import weakref
from dataclasses import dataclass
from typing import Protocol

_SCOPES = frozenset({"shipagent.status", "shipagent.preview"})


@dataclass(frozen=True, slots=True, repr=False)
class RunRequestAuthority:
    account_id: str
    connection_id: str
    expected_epoch: str
    issuer: str
    surface: str
    scopes: frozenset[str]
    execution_target_id: str
    token_expires_at: float
    operation_deadline: float

    def __post_init__(self):
        for name, limit in (
            ("account_id", 256),
            ("connection_id", 256),
            ("expected_epoch", 128),
            ("issuer", 2048),
            ("surface", 64),
            ("execution_target_id", 256),
        ):
            value = getattr(self, name)
            try:
                size = len(value.encode("utf-8")) if type(value) is str else 0
            except UnicodeError:
                raise PermissionError("Agent run authority is unavailable.") from None
            if type(value) is not str or not value or "\0" in value or size > limit:
                raise PermissionError("Agent run authority is unavailable.")
        if (
            type(self.scopes) is not frozenset
            or any(type(scope) is not str for scope in self.scopes)
            or not self.scopes <= _SCOPES
        ):
            raise PermissionError("Agent run authority is unavailable.")
        for value in (self.token_expires_at, self.operation_deadline):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise PermissionError("Agent run authority is unavailable.")
        if self.token_expires_at >= 253402300800:
            raise PermissionError("Agent run authority is unavailable.")


class AgentRunAuthority(Protocol):
    async def submit(self, service, request: RunRequestAuthority, **arguments): ...
    async def continue_turn(
        self, service, request: RunRequestAuthority, **arguments
    ): ...
    async def read(self, service, request: RunRequestAuthority, **arguments): ...
    async def cancel(self, service, request: RunRequestAuthority, **arguments): ...
    async def admit_dispatch(self, service, run): ...
    async def publish(self, service, run, **arguments): ...


class RunDispatchPermit:
    """Private one-shot permission; provider entry is qualified in Task 4."""

    def __init__(self, *, service, run, generation, deadline, clock, monotonic):
        self._self = weakref.ref(self)
        self._pid = os.getpid()
        self._thread = threading.get_ident()
        self._service, self._run = service, run
        self._generation, self._deadline = generation, deadline
        self._clock, self._monotonic = clock, monotonic
        self._provider_owner = None
        self._consumed = False

    @property
    def deadline(self):
        return self._deadline

    def _identity(self, service, run):
        if (
            self._self() is not self
            or self._pid != os.getpid()
            or self._thread != threading.get_ident()
            or service is not self._service
            or run is not self._run
            or service._active_run is not run
            or service._generation != self._generation
            or service._closing
            or service._unhealthy
            or self._consumed
        ):
            raise PermissionError("Agent run dispatch is unavailable.")
        try:
            service._lease.require_owned()
            now, utc = self._monotonic(), self._clock()
            if any(
                type(v) not in (int, float) or not math.isfinite(v) for v in (now, utc)
            ):
                raise ValueError
            if now >= self._deadline or utc >= min(
                run.expires_at, run.turn_authority_expires_at
            ):
                raise ValueError
        except Exception:
            raise PermissionError("Agent run dispatch is unavailable.") from None

    def bind_provider_owner(self, service, run, owner):
        self._identity(service, run)
        if owner is None or self._provider_owner is not None:
            raise PermissionError("Agent run dispatch is unavailable.")
        self._provider_owner = owner

    def consume(self, service, run, owner):
        self._identity(service, run)
        if self._provider_owner is None or owner is not self._provider_owner:
            raise PermissionError("Agent run dispatch is unavailable.")
        self._consumed = True


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedRunDispatch:
    permit: RunDispatchPermit
    private_history_json: bytes

    def __post_init__(self):
        if (
            type(self.permit) is not RunDispatchPermit
            or type(self.private_history_json) is not bytes
            or len(self.private_history_json) > 1024 * 1024
        ):
            raise PermissionError("Agent run dispatch is unavailable.")
