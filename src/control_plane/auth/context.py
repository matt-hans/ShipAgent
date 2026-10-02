from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuthorizationContext:
    account_id: str
    provider_connection_id: str
    provider_surface: str
    subject: str
    client_id: str
    scopes: frozenset[str]
    auth_time: datetime | None = None


_AUTHORIZATION_CONTEXT: ContextVar[AuthorizationContext | None] = ContextVar(
    "authorization_context", default=None
)


def get_authorization_context() -> AuthorizationContext | None:
    """Return the current request authorization context, if set."""
    return _AUTHORIZATION_CONTEXT.get()


def set_authorization_context(context: AuthorizationContext | None):
    """Set the current request authorization context."""
    return _AUTHORIZATION_CONTEXT.set(context)


def clear_authorization_context(token) -> None:
    """Reset the authorization context context manager token."""
    _AUTHORIZATION_CONTEXT.reset(token)
