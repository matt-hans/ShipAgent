import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass

from src.control_plane.redis_keys import RedisKey

DEFAULT_WINDOW_SECONDS = 60
LOOP_DETECTION_LIMIT = 3

RATE_LIMIT_BY_CLASS: dict[str, int] = {
    "default": 10,
    "read": 30,
    "estimate": 10,
    "write": 20,
    "purchase": 5,
}


def _normalize_rate_limit_class(rate_limit_class: str | None) -> str:
    return rate_limit_class if rate_limit_class in RATE_LIMIT_BY_CLASS else "default"


def _canonicalize_argument_value(value):
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if key.lower() in _SENSITIVE_ARGUMENT_KEYS
                else _canonicalize_argument_value(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_argument_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize_argument_value(item) for item in value]
    return value


_SENSITIVE_ARGUMENT_KEYS = frozenset(
    {
        "secret",
        "api_secret",
        "api_key",
        "access_token",
        "token",
        "password",
        "provider_file_url",
        "file_url",
    }
)


def hash_arguments(arguments: Mapping[str, object]) -> str:
    normalized = _canonicalize_argument_value(dict(arguments))
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass
class RequestControlError(PermissionError):
    code: str
    message: str
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        if self.retry_after_seconds is None:
            return self.message
        return f"{self.message} (retry_after={self.retry_after_seconds})"


class RequestControls:
    """Redis-backed request controls for rate and loop protection."""

    _RATE_LIMIT_LUA = """
    -- SA_RATE_LIMIT
    local key = KEYS[1]
    local limit = tonumber(ARGV[1])
    local ttl = tonumber(ARGV[2])
    local count = redis.call('INCR', key)
    if count == 1 then
        redis.call('EXPIRE', key, ttl)
    end
    return count
    """

    _LOOP_GUARD_LUA = """
    -- SA_LOOP_GUARD
    local key = KEYS[1]
    local ttl = tonumber(ARGV[1])
    local count = redis.call('INCR', key)
    if count == 1 then
        redis.call('EXPIRE', key, ttl)
    end
    return count
    """

    def __init__(self, redis_client, now_fn=None) -> None:
        self.redis = redis_client
        self._now = now_fn or time.time

    async def require_allowed(
        self,
        *,
        connection_id: str,
        tool_name: str,
        rate_limit_class: str,
        arguments_hash: str,
    ) -> None:
        await self._require_rate_limit(
            connection_id=connection_id,
            rate_limit_class=rate_limit_class,
        )
        await self._require_loop_guard(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )

    async def _require_rate_limit(
        self,
        *,
        connection_id: str,
        rate_limit_class: str,
    ) -> None:
        normalized_class = _normalize_rate_limit_class(rate_limit_class)
        limit = RATE_LIMIT_BY_CLASS[normalized_class]
        minute_bucket = int(self._now() // DEFAULT_WINDOW_SECONDS)
        key = RedisKey.rate_limit(
            connection_id,
            normalized_class,
            str(minute_bucket),
        )

        count = int(await self.redis.eval(self._RATE_LIMIT_LUA, 1, key, str(limit), str(DEFAULT_WINDOW_SECONDS)))
        if count > limit:
            elapsed = int(self._now() % DEFAULT_WINDOW_SECONDS)
            raise RequestControlError(
                code="rate_limited",
                message="rate limit exceeded",
                retry_after_seconds=DEFAULT_WINDOW_SECONDS - elapsed,
            )

    async def _require_loop_guard(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
    ) -> None:
        key = RedisKey.loop_guard(connection_id, tool_name, arguments_hash)
        count = int(
            await self.redis.eval(
                self._LOOP_GUARD_LUA,
                1,
                key,
                str(DEFAULT_WINDOW_SECONDS),
            )
        )
        if count > LOOP_DETECTION_LIMIT:
            raise RequestControlError(
                code="provider_loop_detected",
                message="identical call loop detected",
            )
