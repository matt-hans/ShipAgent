"""Delete TTL-less ephemeral keys atomically, without refreshing valid lifetimes."""

from dataclasses import dataclass

from src.control_plane.redis_keys import RedisKey

_DELETE_TTLLESS = """
if redis.call('PTTL', KEYS[1]) == -1 then return redis.call('DEL', KEYS[1]) end
return 0
"""


@dataclass(frozen=True)
class RedisSweepResult:
    scanned: int
    deleted: int


async def sweep_ephemeral_redis_keys(redis_client) -> RedisSweepResult:
    scanned = deleted = 0
    for pattern in RedisKey.ephemeral_patterns():
        async for key in redis_client.scan_iter(match=pattern, count=100):
            scanned += 1
            deleted += await redis_client.eval(_DELETE_TTLLESS, 1, key)
    return RedisSweepResult(scanned=scanned, deleted=deleted)
