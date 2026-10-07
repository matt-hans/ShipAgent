"""Optional control-plane-only cleanup; failures retry without logging payloads."""

import asyncio
import logging
from dataclasses import dataclass

from src.control_plane.redis_keys import RedisTtl
from src.control_plane.retention.redis_sweeper import (
    RedisSweepResult,
    sweep_ephemeral_redis_keys,
)
from src.control_plane.retention.sql_purge import (
    SqlPurgeResult,
    purge_expired_authorization_audit,
)

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionRunResult:
    redis: RedisSweepResult
    sql: SqlPurgeResult


class ControlPlaneRetentionWorker:
    redis_sweep_interval_seconds = RedisTtl.SWEEP_INTERVAL_SECONDS
    sql_purge_interval_seconds = 86400

    def __init__(
        self,
        *,
        redis_client,
        session_factory,
        audit_retention_days: int = 90,
        enabled: bool = False,
    ):
        if (
            type(audit_retention_days) is not int
            or not 30 <= audit_retention_days <= 365
        ):
            raise ValueError("retention must be between 30 and 365 days")
        self.redis_client = redis_client
        self.session_factory = session_factory
        self.audit_retention_days = audit_retention_days
        self.enabled = enabled
        self._tasks: list[asyncio.Task] = []

    @property
    def running_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks)

    async def _redis_once(self):
        return await sweep_ephemeral_redis_keys(self.redis_client)

    async def _sql_once(self):
        async with self.session_factory() as session:
            result = await purge_expired_authorization_audit(
                session=session, retention_days=self.audit_retention_days
            )
            await session.commit()
            return result

    async def run_once(self) -> RetentionRunResult:
        return RetentionRunResult(
            redis=await self._redis_once(), sql=await self._sql_once()
        )

    async def _loop(self, operation, interval):
        while True:
            try:
                await operation()
            except Exception:
                # Never include exception text, connection URLs, SQL parameters or traces.
                _LOG.warning("retention_pass_failed")
            await asyncio.sleep(interval)

    async def start(self) -> None:
        if not self.enabled or self._tasks:
            return
        self._tasks = [
            asyncio.create_task(
                self._loop(self._redis_once, self.redis_sweep_interval_seconds)
            ),
            asyncio.create_task(
                self._loop(self._sql_once, self.sql_purge_interval_seconds)
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
