"""Dormant safe metadata persistence; not an Execution Grant authority."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.control_plane.audit.authorization_ledger import AuthorizationMetadata
from src.control_plane.grant_models import GrantRecord
from src.control_plane.redis_keys import RedisTtl


@dataclass(frozen=True, repr=False)
class AuthorizationState:
    """Immutable original deadline. No token, executable credential or raw preview."""

    metadata: AuthorizationMetadata
    created_at: datetime
    expires_at: datetime
    revision: int = 0
    grant: GrantRecord | None = None

    def __post_init__(self) -> None:
        if type(self.metadata) is not AuthorizationMetadata:
            raise ValueError("invalid authorization metadata")
        self.metadata.__post_init__()
        for value in (self.created_at, self.expires_at):
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError("authorization time must be timezone aware")
        lifetime = (self.expires_at - self.created_at).total_seconds()
        if not 0 < lifetime <= RedisTtl.APPROVAL_REQUEST_SECONDS:
            raise ValueError("invalid original authorization lifetime")
        if type(self.revision) is not int or not 0 <= self.revision < 2**31:
            raise ValueError("invalid authorization revision")

        if self.grant is not None:
            grant = GrantRecord.model_validate_json(self.grant.model_dump_json())
            if (
                grant.purchase.account_id != self.metadata.account_id
                or grant.purchase.provider_connection_id
                != self.metadata.provider_connection_id
                or grant.purchase.preview_hash != self.metadata.preview_hash
                or grant.purchase.scope_hash != self.metadata.purchase_scope_hash
                or (
                    grant.lease_expires_at is not None
                    and grant.lease_expires_at > self.expires_at
                )
            ):
                raise ValueError("grant metadata mismatch")

    @classmethod
    def new(
        cls, *, metadata: AuthorizationMetadata, now: datetime
    ) -> "AuthorizationState":
        return cls(
            metadata=metadata,
            created_at=now,
            expires_at=now + timedelta(seconds=RedisTtl.APPROVAL_REQUEST_SECONDS),
        )


class AuthorizationStateError(Exception):
    """Closed error without Redis/SQL payloads or connection details."""

    def __init__(self):
        super().__init__("authorization_state_unavailable")


def _encode(state: AuthorizationState) -> str:
    import json
    from dataclasses import asdict

    if type(state) is not AuthorizationState:
        raise ValueError("invalid authorization state")
    state.__post_init__()
    return json.dumps(
        {
            "metadata": asdict(state.metadata),
            "created_at": state.created_at.isoformat(),
            "expires_at": state.expires_at.isoformat(),
            "revision": state.revision,
            **(
                {"grant": state.grant.model_dump(mode="json")}
                if state.grant is not None
                else {}
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode(raw: bytes | str) -> AuthorizationState:
    import json

    value = json.loads(raw)
    if set(value) not in (
        {"metadata", "created_at", "expires_at", "revision"},
        {"metadata", "created_at", "expires_at", "revision", "grant"},
    ):
        raise ValueError("invalid authorization state")
    return AuthorizationState(
        metadata=AuthorizationMetadata(**value["metadata"]),
        created_at=datetime.fromisoformat(value["created_at"]),
        expires_at=datetime.fromisoformat(value["expires_at"]),
        revision=value["revision"],
        grant=GrantRecord.model_validate(value["grant"]) if "grant" in value else None,
    )


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


_CREATE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local created = tonumber(ARGV[2])
local expires = tonumber(ARGV[3])
if created > now or expires <= now or expires - created > 900000 then return 0 end
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PXAT', expires) then return 1 end
return 0
"""
_READ = """
local ttl = redis.call('PTTL', KEYS[1])
if ttl <= 0 then return nil end
local value = redis.call('GET', KEYS[1])
if not value then return nil end
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
return {value, redis.call('PEXPIRETIME', KEYS[1]), now}
"""
_REPLACE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
if now >= tonumber(ARGV[4]) then return 0 end
if redis.call('PTTL', KEYS[1]) <= 0 then return 0 end
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('PEXPIRETIME', KEYS[1]) > tonumber(ARGV[3]) then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'XX', 'KEEPTTL')
return 1
"""
_DELETE_ACCOUNT = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local ok, value = pcall(cjson.decode, raw)
if ok and type(value) == 'table' and type(value.metadata) == 'table'
    and value.metadata.account_id == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class AuthorizationStateStore:
    """Low-level CAS/TTL primitives only. Never restores SQL state or grants access.

    Callers must commit required SQL audit before publishing enabling state. A
    create/CAS result is not approval, reservation, consumption or reconciliation.
    Missing keys deny; only new approvals with new IDs may create new state.
    """

    def __init__(self, redis_client):
        self.redis = redis_client

    @staticmethod
    def _key(kind: str, approval_request_id: str) -> str:
        from src.control_plane.audit.hash_validation import require_reference
        from src.control_plane.redis_keys import RedisKey
        from src.registry.identifiers import ShipAgentIdFamily

        require_reference(approval_request_id, ShipAgentIdFamily.APPROVAL_REQUEST)
        if kind == "approval_request":
            return RedisKey.approval_request(approval_request_id)
        if kind == "execution_grant":
            return RedisKey.execution_grant(approval_request_id)
        raise ValueError("unsupported authorization state kind")

    async def _eval(self, script, key, *args):
        from redis.exceptions import RedisError

        try:
            return await self.redis.eval(script, 1, key, *args)
        except RedisError:
            raise AuthorizationStateError() from None

    async def create(self, kind: str, record: AuthorizationState) -> bool:
        raw = _encode(record)
        key = self._key(kind, record.metadata.approval_request_id)
        return bool(
            await self._eval(
                _CREATE,
                key,
                raw,
                _milliseconds(record.created_at),
                _milliseconds(record.expires_at),
            )
        )

    async def read(
        self, kind: str, approval_request_id: str, *, account_id: str
    ) -> AuthorizationState:
        from src.control_plane.audit.hash_validation import require_account_id

        require_account_id(account_id)
        result = await self._eval(_READ, self._key(kind, approval_request_id))
        if result is None:
            raise AuthorizationStateError()
        try:
            raw, key_expiry, now = result
            record = _decode(raw)
            if not (
                record.metadata.account_id == account_id
                and record.metadata.approval_request_id == approval_request_id
                and _milliseconds(record.created_at) <= now < key_expiry
                and key_expiry <= _milliseconds(record.expires_at)
            ):
                raise ValueError("invalid authorization state")
            return record
        except (ValueError, TypeError, KeyError, OverflowError):
            raise AuthorizationStateError() from None

    async def replace_existing(
        self,
        kind: str,
        *,
        original: AuthorizationState,
        updated: AuthorizationState,
        not_after: datetime | None = None,
    ) -> bool:
        if (
            original.created_at != updated.created_at
            or original.expires_at != updated.expires_at
            or original.metadata.account_id != updated.metadata.account_id
            or original.metadata.provider_connection_id
            != updated.metadata.provider_connection_id
            or original.metadata.approval_request_id
            != updated.metadata.approval_request_id
            or updated.revision != original.revision + 1
        ):
            raise ValueError(
                "original authorization lifetime and ownership are immutable"
            )
        return bool(
            await self._eval(
                _REPLACE,
                self._key(kind, original.metadata.approval_request_id),
                _encode(original),
                _encode(updated),
                _milliseconds(original.expires_at),
                _milliseconds(
                    min(not_after, original.expires_at)
                    if not_after
                    else original.expires_at
                ),
            )
        )

    async def cleanup_for_account(self, account_id: str) -> int:
        """Delete only this account's ephemeral metadata; legal holds apply to SQL."""
        from redis.exceptions import RedisError

        from src.control_plane.audit.hash_validation import require_account_id

        require_account_id(account_id)
        count = 0
        try:
            for pattern in ("sa:approval:request:*", "sa:approval:grant:*"):
                async for key in self.redis.scan_iter(match=pattern, count=100):
                    count += await self._eval(_DELETE_ACCOUNT, key, account_id)
        except RedisError:
            raise AuthorizationStateError() from None
        return count
