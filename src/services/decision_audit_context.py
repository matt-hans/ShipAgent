"""Context propagation for agent decision audit correlation."""

from __future__ import annotations

from contextvars import ContextVar, Token

_decision_run_id: ContextVar[str | None] = ContextVar("decision_run_id", default=None)
_decision_job_id: ContextVar[str | None] = ContextVar("decision_job_id", default=None)


def get_decision_run_id() -> str | None:
    """Return the current decision run ID from context."""
    return _decision_run_id.get()


def set_decision_run_id(run_id: str | None) -> Token[str | None]:
    """Bind decision run ID in current context and return reset token."""
    return _decision_run_id.set(run_id)


def reset_decision_run_id(token: Token[str | None]) -> None:
    """Reset decision run ID to prior context state."""
    _decision_run_id.reset(token)


def get_decision_job_id() -> str | None:
    """Return the current decision-linked job ID from context."""
    return _decision_job_id.get()


def set_decision_job_id(job_id: str | None) -> Token[str | None]:
    """Bind decision-linked job ID in current context and return reset token."""
    return _decision_job_id.set(job_id)


def reset_decision_job_id(token: Token[str | None]) -> None:
    """Reset decision-linked job ID to prior context state."""
    _decision_job_id.reset(token)
