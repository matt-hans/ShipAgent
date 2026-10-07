"""Dormant Redis lifecycle and the single opaque Job Reference mapping.

These primitives are not authorization. Only an explicitly supplied, fenced
GrantCallbacks implementation may authorize a dispatch. Local applications do
not construct these stores or require Redis.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.control_plane.redis_keys import RedisKey, RedisTtl
from src.control_plane.relay.protocol import (
    InvocationIdentity,
    TargetAcceptanceEvidence,
)
from src.registry.identifiers import (
    ShipAgentIdFamily,
    parse_shipagent_id,
)


class InvocationState(StrEnum):
    QUEUED = "queued"
    SENT_TO_TARGET = "sent_to_target"
    ACCEPTED = "accepted"
    RUNNING = "running"
    RESULT_RETURNED = "result_returned"
    TARGET_OFFLINE_BEFORE_ACCEPT = "target_offline_before_accept"
    TARGET_DISCONNECTED_MID_CALL = "target_disconnected_mid_call"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    ABANDONED = "abandoned"
    RECOVERED_BY_POLL = "recovered_by_poll"


_ALLOWED_TRANSITIONS = {
    InvocationState.QUEUED: {InvocationState.SENT_TO_TARGET, InvocationState.ABANDONED},
    InvocationState.SENT_TO_TARGET: {
        InvocationState.ACCEPTED,
        InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT,
        InvocationState.TARGET_DISCONNECTED_MID_CALL,
        InvocationState.DEADLINE_EXCEEDED,
    },
    InvocationState.ACCEPTED: {
        InvocationState.RUNNING,
        InvocationState.RESULT_RETURNED,
        InvocationState.RECOVERED_BY_POLL,
    },
    InvocationState.RUNNING: {
        InvocationState.RESULT_RETURNED,
        InvocationState.RECOVERED_BY_POLL,
    },
    InvocationState.TARGET_DISCONNECTED_MID_CALL: {
        InvocationState.RECOVERED_BY_POLL,
        InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT,
    },
    InvocationState.DEADLINE_EXCEEDED: {
        InvocationState.RECOVERED_BY_POLL,
        InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT,
    },
    InvocationState.ABANDONED: {
        InvocationState.RECOVERED_BY_POLL,
        InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT,
    },
    InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT: set(),
    InvocationState.RESULT_RETURNED: set(),
    InvocationState.RECOVERED_BY_POLL: set(),
}


class InvocationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: InvocationIdentity
    job_ref: str = Field(pattern=r"^sa_job_[0-9a-f]{32}$")
    created_at_ms: int = Field(gt=0, strict=True)
    expires_at_ms: int = Field(gt=0, strict=True)
    state: InvocationState = InvocationState.QUEUED
    revision: int = Field(default=0, ge=0, strict=True)

    evidence: TargetAcceptanceEvidence | None = None

    @model_validator(mode="after")
    def validate_record(self):
        if (
            not 0
            < self.expires_at_ms - self.created_at_ms
            <= RedisTtl.INVOCATION_SECONDS * 1000
        ):
            raise ValueError("invalid original invocation lifetime")
        accepted_states = {
            InvocationState.ACCEPTED,
            InvocationState.RUNNING,
            InvocationState.RESULT_RETURNED,
            InvocationState.RECOVERED_BY_POLL,
        }
        if self.evidence is not None and self.evidence.identity != self.identity:
            raise ValueError("evidence identity mismatch")
        if self.state in accepted_states:
            if self.evidence is None or self.evidence.outcome != "accepted":
                raise ValueError("accepted state requires durable evidence")
        elif self.state == InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT:
            if self.evidence is None or self.evidence.outcome != "not_accepted":
                raise ValueError("preaccept failure requires durable rejection fence")
        elif self.evidence is not None:
            raise ValueError("evidence conflicts with invocation state")
        return self

    @property
    def local_job_id(self) -> str | None:
        return self.evidence.local_job_id if self.evidence else None

    @property
    def relay_invocation_id(self) -> str:
        return self.identity.relay_invocation_id


class _JobReferencePointer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_ref: str
    relay_invocation_id: str
    account_id: str
    provider_connection_id: str
    execution_target_id: str
    created_at_ms: int
    expires_at_ms: int

    @classmethod
    def for_record(cls, record: InvocationRecord):
        return cls(
            job_ref=record.job_ref,
            relay_invocation_id=record.relay_invocation_id,
            account_id=record.identity.account_id,
            provider_connection_id=record.identity.provider_connection_id,
            execution_target_id=record.identity.execution_target_id,
            created_at_ms=record.created_at_ms,
            expires_at_ms=record.expires_at_ms,
        )


class LifecycleUnavailable(Exception):
    """Closed error: never disclose raw Redis data or target details."""

    def __init__(self):
        super().__init__("invocation_state_unavailable")


_CREATE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
if tonumber(ARGV[3]) > now or tonumber(ARGV[4]) <= now then return -1 end
if tonumber(ARGV[4]) - tonumber(ARGV[3]) > 86400000 then return -1 end
if tonumber(ARGV[5]) <= now or tonumber(ARGV[5]) - now > 900000 then return -1 end
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
if redis.call('EXISTS', KEYS[2]) == 1 then return -1 end
redis.call('SET', KEYS[1], ARGV[1], 'PXAT', ARGV[4])
redis.call('SET', KEYS[2], ARGV[2], 'PXAT', ARGV[4])
return 1
"""
_READ = """
local raw = redis.call('GET', KEYS[1])
if not raw or redis.call('PTTL', KEYS[1]) <= 0 then return nil end
local ok, value = pcall(cjson.decode, raw)
if not ok or type(value) ~= 'table' or type(value.job_ref) ~= 'string' then return nil end
local pointer_key = 'sa:jobref:' .. value.job_ref
local pointer = redis.call('GET', pointer_key)
if not pointer or redis.call('PTTL', pointer_key) <= 0 then return nil end
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
return {raw, pointer, redis.call('PEXPIRETIME', KEYS[1]), redis.call('PEXPIRETIME', pointer_key), now}
"""


_REPLACE = """
if redis.call('PTTL', KEYS[1]) <= 0 or redis.call('PTTL', KEYS[2]) <= 0 then return 0 end
if redis.call('GET', KEYS[1]) ~= ARGV[1] or redis.call('GET', KEYS[2]) ~= ARGV[3] then return 0 end
if redis.call('PEXPIRETIME', KEYS[1]) > tonumber(ARGV[4]) or redis.call('PEXPIRETIME', KEYS[2]) > tonumber(ARGV[4]) then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'XX', 'KEEPTTL')
return 1
"""


class InvocationLifecycleStore:
    """One lifecycle per server key. Atomic pairs, scoped reads, no TTL refresh."""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def _eval(self, script, keys, *args):
        from redis.exceptions import RedisError

        try:
            return await self.redis.eval(script, len(keys), *keys, *args)
        except RedisError:
            raise LifecycleUnavailable() from None

    async def create(
        self, identity: InvocationIdentity
    ) -> tuple[InvocationRecord, bool]:
        from redis.exceptions import RedisError

        if type(identity) is not InvocationIdentity:
            raise ValueError("invalid invocation identity")
        identity = InvocationIdentity.model_validate_json(identity.model_dump_json())
        try:
            seconds, micros = await self.redis.time()
        except RedisError:
            raise LifecycleUnavailable() from None
        now = seconds * 1000 + micros // 1000
        candidate = InvocationRecord(
            identity=identity,
            # Domain separation keeps the public reference opaque and stable if
            # only one half of a pair is lost. A surviving pointer must deny a
            # replacement pair, not become an orphan beside a newly minted job.
            job_ref="sa_job_"
            + hashlib.sha256(
                ("shipagent-job-reference:" + identity.idempotency_key).encode()
            ).hexdigest()[:32],
            created_at_ms=now,
            expires_at_ms=now + RedisTtl.INVOCATION_SECONDS * 1000,
        )
        outcome = await self._eval(
            _CREATE,
            [
                RedisKey.invocation(candidate.relay_invocation_id),
                RedisKey.job_reference(candidate.job_ref),
            ],
            candidate.model_dump_json(),
            _JobReferencePointer.for_record(candidate).model_dump_json(),
            candidate.created_at_ms,
            candidate.expires_at_ms,
            int(identity.authorization_expires_at.timestamp() * 1000),
        )
        if outcome == -1:
            raise LifecycleUnavailable()
        record = await self.get(
            identity.relay_invocation_id,
            account_id=identity.account_id,
            provider_connection_id=identity.provider_connection_id,
        )
        if record.identity != identity:
            raise LifecycleUnavailable()
        return record, outcome == 1

    async def get(
        self, relay_invocation_id, *, account_id, provider_connection_id
    ) -> InvocationRecord:
        result = await self._eval(_READ, [RedisKey.invocation(relay_invocation_id)])
        if result is None:
            raise LifecycleUnavailable()
        try:
            raw, pointer_raw, invocation_expiry, pointer_expiry, now = result
            record = InvocationRecord.model_validate_json(raw)
            pointer = _JobReferencePointer.model_validate_json(pointer_raw)
            if not (
                record.relay_invocation_id == relay_invocation_id
                and record.identity.account_id == account_id
                and record.identity.provider_connection_id == provider_connection_id
                and pointer == _JobReferencePointer.for_record(record)
                and record.created_at_ms
                <= now
                < invocation_expiry
                <= record.expires_at_ms
                and now < pointer_expiry <= record.expires_at_ms
                and 0
                < record.expires_at_ms - record.created_at_ms
                <= RedisTtl.INVOCATION_SECONDS * 1000
            ):
                raise ValueError("invalid invocation state")
            return record
        except (ValueError, TypeError, KeyError, OverflowError):
            raise LifecycleUnavailable() from None

    async def transition(
        self, original: InvocationRecord, state: InvocationState
    ) -> InvocationRecord | None:
        """Non-evidence transitions cannot skip durable acceptance."""
        if state in {
            InvocationState.ACCEPTED,
            InvocationState.RECOVERED_BY_POLL,
            InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT,
        }:
            raise ValueError("target evidence required")
        return await self._replace(original, state=state, evidence=original.evidence)

    async def record_evidence(
        self, original: InvocationRecord, evidence: TargetAcceptanceEvidence
    ) -> InvocationRecord | None:
        if (
            type(evidence) is not TargetAcceptanceEvidence
            or evidence.identity != original.identity
        ):
            raise LifecycleUnavailable()
        evidence = TargetAcceptanceEvidence.model_validate_json(
            evidence.model_dump_json()
        )
        current = await self.get(
            original.relay_invocation_id,
            account_id=original.identity.account_id,
            provider_connection_id=original.identity.provider_connection_id,
        )
        if current.evidence == evidence:
            return current
        if current != original:
            return None
        if evidence.outcome == "unknown":
            return original
        if original.evidence is not None and original.evidence != evidence:
            raise LifecycleUnavailable()
        if evidence.outcome == "accepted":
            state = (
                InvocationState.ACCEPTED
                if original.state == InvocationState.SENT_TO_TARGET
                else InvocationState.RECOVERED_BY_POLL
            )
        else:
            state = InvocationState.TARGET_OFFLINE_BEFORE_ACCEPT
        return await self._replace(original, state=state, evidence=evidence)

    async def _replace(self, original, *, state, evidence):
        if state not in _ALLOWED_TRANSITIONS[original.state]:
            raise ValueError("invalid invocation transition")
        updated = original.model_copy(
            update={
                "state": state,
                "evidence": evidence,
                "revision": original.revision + 1,
            }
        )
        updated = InvocationRecord.model_validate_json(updated.model_dump_json())
        outcome = await self._eval(
            _REPLACE,
            [
                RedisKey.invocation(original.relay_invocation_id),
                RedisKey.job_reference(original.job_ref),
            ],
            original.model_dump_json(),
            updated.model_dump_json(),
            _JobReferencePointer.for_record(original).model_dump_json(),
            original.expires_at_ms,
        )
        return updated if outcome else None


class JobReferenceStore:
    """Account/connection-scoped pointer to the sole lifecycle, not another state machine."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.invocations = InvocationLifecycleStore(redis_client)

    async def resolve(
        self, job_ref, *, account_id, provider_connection_id
    ) -> InvocationRecord:
        from redis.exceptions import RedisError

        try:
            parse_shipagent_id(job_ref, expected_family=ShipAgentIdFamily.JOB)
            raw = await self.redis.get(RedisKey.job_reference(job_ref))
            pointer = _JobReferencePointer.model_validate_json(raw)
            record = await self.invocations.get(
                pointer.relay_invocation_id,
                account_id=account_id,
                provider_connection_id=provider_connection_id,
            )
            if record.job_ref != job_ref:
                raise ValueError("invalid job reference")
            return record
        except (RedisError, ValueError, TypeError):
            raise LifecycleUnavailable() from None
