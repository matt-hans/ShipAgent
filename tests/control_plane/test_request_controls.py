import time

import pytest

from src.control_plane.request_controls import RequestControlError, RequestControls


class _FakeRedis:
    def __init__(self):
        self._values: dict[str, tuple[int, float]] = {}

    async def eval(self, script: str, keys: int, *args: str) -> int:
        if keys != 1:
            raise RuntimeError("unexpected keys arg")
        key = args[0]
        max_ttl = float(args[1])
        if key not in self._values:
            self._values[key] = (0, time.monotonic() + max_ttl)
        value, expiry = self._values[key]
        if time.monotonic() > expiry:
            value = 0

        value += 1
        if value == 1:
            expiry = time.monotonic() + max_ttl
        self._values[key] = (value, expiry)
        return value


@pytest.fixture
def fake_controls():
    return RequestControls(_FakeRedis(), now_fn=lambda: 0)


@pytest.mark.asyncio
async def test_rate_limit_is_namespaced_by_connection_and_class(fake_controls):
    for index in range(10):
        await fake_controls.require_allowed(
            connection_id="connection-1",
            tool_name="get_shipment_rates",
            rate_limit_class="estimate",
            arguments_hash=f"hash-{index}",
        )
    with pytest.raises(RequestControlError, match="rate limit exceeded"):
        await fake_controls.require_allowed(
            connection_id="connection-1",
            tool_name="get_shipment_rates",
            rate_limit_class="estimate",
            arguments_hash="hash-11",
        )


@pytest.mark.asyncio
async def test_repeated_identical_calls_trip_loop_breaker(fake_controls):
    for _ in range(3):
        await fake_controls.require_allowed(
            connection_id="connection-1",
            tool_name="get_job_status",
            rate_limit_class="read",
            arguments_hash="same-hash",
        )
    with pytest.raises(RequestControlError, match="loop"):
        await fake_controls.require_allowed(
            connection_id="connection-1",
            tool_name="get_job_status",
            rate_limit_class="read",
            arguments_hash="same-hash",
        )


@pytest.mark.asyncio
async def test_fake_redis_isolation_of_namespaces(fake_controls):
    connection_one_task = fake_controls.require_allowed(
        connection_id="connection-1",
        tool_name="get_job_status",
        rate_limit_class="read",
        arguments_hash="same-hash",
    )
    await connection_one_task

    connection_two_task = fake_controls.require_allowed(
        connection_id="connection-2",
        tool_name="get_job_status",
        rate_limit_class="read",
        arguments_hash="same-hash",
    )
    await connection_two_task
