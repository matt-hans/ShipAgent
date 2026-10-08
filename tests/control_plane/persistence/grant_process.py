"""Synthetic independent authority client, using real Redis/PostgreSQL only."""

import asyncio
import json
import sys
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.control_plane.auth.context import AuthorizationContext
from src.control_plane.execution_grants import ExecutionGrantError
from src.control_plane.grant_ledger import GrantLedger
from src.control_plane.grant_models import ApprovedPurchase
from src.control_plane.redis_grant_authority import RedisExecutionGrantAuthority
from tests.control_plane.persistence.lifecycle_process import ProtocolTarget
from tests.control_plane.persistence.test_grant_authority import LivePreview
from tests.control_plane.persistence.test_invocation_lifecycle import coordinator


async def main():
    request = json.loads(sys.stdin.read())
    redis = Redis(
        host="127.0.0.1",
        port=request["redis_port"],
        socket_timeout=1,
        socket_connect_timeout=1,
    )
    engine = create_async_engine(request["postgres_url"])
    context = AuthorizationContext(
        **{**request["context"], "scopes": frozenset(request["context"]["scopes"])}
    )
    purchase = ApprovedPurchase.model_validate(request["purchase"])
    ledger = GrantLedger(async_sessionmaker(engine, expire_on_commit=False))
    authority = RedisExecutionGrantAuthority(
        redis_client=redis, ledger=ledger, live_preview=LivePreview(purchase)
    )
    target = ProtocolTarget(
        port=request["target_port"],
        session_id=request["session_id"],
        execution_target_id=purchase.execution_target_id,
        drop_reply=request.get("drop_reply", False),
    )
    if request.get("consume_marker"):
        original = ledger.record

        async def blocked(metadata, transition, **kwargs):
            if transition == "consumed":
                Path(request["consume_marker"]).write_text(
                    "accepted-before-grant-consume"
                )
                await asyncio.sleep(100)
            return await original(metadata, transition, **kwargs)

        ledger.record = blocked
    try:
        if request.get("job_ref"):
            callbacks = await authority.recovery_callbacks(
                context=context, job_ref=request["job_ref"]
            )
            result = await coordinator(redis).reconcile(
                target=target,
                job_ref=request["job_ref"],
                account_id=context.account_id,
                provider_connection_id=context.provider_connection_id,
                grant_callbacks=callbacks,
            )
        else:
            reservation = await authority.reserve(
                context=context,
                tool_name=purchase.tool_name,
                prepare_tool=purchase.prepare_tool,
                approval_request_id=request["approval_request_id"],
                preview_id=purchase.preview_id,
            )
            result = await coordinator(redis).invoke(
                target=target,
                identity=reservation.identity,
                arguments={},
                grant_callbacks=reservation.callbacks(),
            )
        print(json.dumps({"result": result}), flush=True)
    except ExecutionGrantError as exc:
        print(json.dumps({"denial": exc.denial.value}), flush=True)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
