"""Dormant safe metadata persistence; not an Execution Grant authority."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.control_plane.audit.authorization_ledger import AuthorizationMetadata
from src.control_plane.redis_keys import RedisTtl


@dataclass(frozen=True, repr=False)
class AuthorizationState:
    """Immutable original deadline. No token, executable credential or raw preview."""

    metadata: AuthorizationMetadata
    created_at: datetime
    expires_at: datetime
    revision: int = 0

    def __post_init__(self) -> None:
        if type(self.metadata) is not AuthorizationMetadata:
            raise ValueError("invalid authorization metadata")
        self.metadata.__post_init__()
        for value in (self.created_at, self.expires_at):
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("authorization time must be timezone aware")
        lifetime = (self.expires_at - self.created_at).total_seconds()
        if not 0 < lifetime <= RedisTtl.APPROVAL_REQUEST_SECONDS:
            raise ValueError("invalid original authorization lifetime")
        if type(self.revision) is not int or not 0 <= self.revision < 2**31:
            raise ValueError("invalid authorization revision")

    @classmethod
    def new(cls, *, metadata: AuthorizationMetadata, now: datetime) -> "AuthorizationState":
        return cls(metadata=metadata, created_at=now, expires_at=now + timedelta(seconds=RedisTtl.APPROVAL_REQUEST_SECONDS))
