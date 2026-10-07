"""Synthetic protocol process; target journal is not a grant/lifecycle store.

Target-owned SQLite evidence models durable acceptance. The cloud lifecycle uses
real disposable Redis. No carrier, model, credentials or external services.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import socketserver
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.control_plane.relay.protocol import (
    InvocationIdentity,
    RelayInvocationEnvelope,
    TargetAcceptanceEvidence,
    relay_invocation_input_hash,
)


class ProtocolTarget:
    def __init__(self, *, port, session_id, execution_target_id, drop_reply=False):
        self.port = port
        self.session_id = session_id
        self.execution_target_id = execution_target_id
        self.drop_reply = drop_reply
        self.sequence = 0

    async def request(self, body):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(json.dumps(body).encode() + b"\n")
            await writer.drain()
            response = json.loads(await reader.readline())
            if "error" in response:
                raise RuntimeError("synthetic_protocol_rejected")
            return response
        finally:
            writer.close()
            await writer.wait_closed()

    async def dispatch_invocation(self, *, identity, arguments, deadline_at):
        self.sequence += 1
        envelope = RelayInvocationEnvelope(
            relay_session_id=self.session_id,
            sequence=self.sequence,
            relay_invocation_id=identity.relay_invocation_id,
            tool_name=identity.tool_name,
            arguments=arguments,
            input_hash=identity.arguments_hash,
            deadline_at=deadline_at,
            idempotency_key=identity.idempotency_key,
            audit_correlation_id="sa_correlation_" + secrets.token_hex(16),
        )
        await self.request(
            {
                "operation": "send",
                "identity": identity.model_dump(mode="json"),
                "envelope": envelope.model_dump(mode="json"),
                "drop_reply": self.drop_reply,
            }
        )

    async def get_acceptance(self, identity):
        return TargetAcceptanceEvidence.model_validate(
            await self.request(
                {"operation": "query", "identity": identity.model_dump(mode="json")}
            )
        )

    async def fence(self, identity):
        return TargetAcceptanceEvidence.model_validate(
            await self.request(
                {"operation": "fence", "identity": identity.model_dump(mode="json")}
            )
        )


def target_server(args):
    with sqlite3.connect(args.journal) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS evidence (key TEXT PRIMARY KEY, identity TEXT NOT NULL, proof TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS effects (job TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS sequences (session TEXT PRIMARY KEY, sequence INTEGER NOT NULL)"
        )

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                message = json.loads(self.rfile.readline(1_000_000))
                identity = InvocationIdentity.model_validate(message["identity"])
                if identity.execution_target_id != args.target_id:
                    raise ValueError("wrong target")
                with sqlite3.connect(args.journal, timeout=2) as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute(
                        "SELECT identity, proof FROM evidence WHERE key=?",
                        (identity.idempotency_key,),
                    ).fetchone()
                    if (
                        row
                        and InvocationIdentity.model_validate_json(row[0]) != identity
                    ):
                        raise ValueError("wrong identity")
                    operation = message["operation"]
                    if operation == "send":
                        envelope = RelayInvocationEnvelope.model_validate(
                            message["envelope"]
                        )
                        if (
                            envelope.relay_session_id != args.session_id
                            or envelope.relay_invocation_id
                            != identity.relay_invocation_id
                            or envelope.tool_name != identity.tool_name
                            or envelope.input_hash != identity.arguments_hash
                            or envelope.input_hash
                            != relay_invocation_input_hash(
                                envelope.tool_name, envelope.arguments
                            )
                            or envelope.idempotency_key != identity.idempotency_key
                            or envelope.deadline_at.tzinfo is None
                            or envelope.deadline_at > identity.authorization_expires_at
                        ):
                            raise ValueError("invalid envelope")
                        if not row:
                            sequence = db.execute(
                                "SELECT sequence FROM sequences WHERE session=?",
                                (args.session_id,),
                            ).fetchone()
                            if sequence and envelope.sequence <= sequence[0]:
                                raise ValueError("stale sequence")
                            if datetime.now(UTC) >= envelope.deadline_at:
                                raise ValueError("expired envelope")
                            db.execute(
                                "INSERT OR REPLACE INTO sequences VALUES (?,?)",
                                (args.session_id, envelope.sequence),
                            )
                            local_job_id = "synthetic_job_" + secrets.token_hex(16)
                            proof = TargetAcceptanceEvidence(
                                identity=identity,
                                outcome="accepted",
                                local_job_id=local_job_id,
                                proof_id="sha256:"
                                + hashlib.sha256(local_job_id.encode()).hexdigest(),
                                accepted_at=datetime.now(UTC),
                            )
                            db.execute(
                                "INSERT INTO evidence VALUES (?,?,?)",
                                (
                                    identity.idempotency_key,
                                    identity.model_dump_json(),
                                    proof.model_dump_json(),
                                ),
                            )
                            db.execute(
                                "INSERT INTO effects VALUES (?,?)",
                                (local_job_id, identity.idempotency_key),
                            )
                            row = (identity.model_dump_json(), proof.model_dump_json())
                    elif operation == "fence" and not row:
                        proof = TargetAcceptanceEvidence(
                            identity=identity,
                            outcome="not_accepted",
                            rejection_fenced=True,
                            proof_id="sha256:" + secrets.token_hex(32),
                        )
                        db.execute(
                            "INSERT INTO evidence VALUES (?,?,?)",
                            (
                                identity.idempotency_key,
                                identity.model_dump_json(),
                                proof.model_dump_json(),
                            ),
                        )
                        row = (identity.model_dump_json(), proof.model_dump_json())
                    elif operation not in {"query", "fence"}:
                        raise ValueError("unknown operation")
                    db.commit()  # Durable proof/effect BEFORE acknowledgement.
                    result = (
                        json.loads(row[1])
                        if row
                        else TargetAcceptanceEvidence(
                            identity=identity, outcome="unknown"
                        ).model_dump(mode="json")
                    )
                if operation == "send" and message.get("drop_reply"):
                    return
                self.wfile.write(json.dumps(result).encode() + b"\n")
            except Exception:
                self.wfile.write(b'{"error":"synthetic_protocol_error"}\n')

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = False

    with Server(("127.0.0.1", 0), Handler) as server:
        Path(args.ready).write_text(
            json.dumps(
                {"port": server.server_address[1], "session_id": args.session_id}
            )
        )
        server.serve_forever(poll_interval=0.02)


class ProcessCallbacks:
    """Observable test double only; real grant authority remains issue 67."""

    def __init__(self, marker=None):
        self.calls = []
        self.marker = marker

    async def reserve(self, record):
        self.calls.append("reserve")

    async def consume_on_accept(self, record):
        self.calls.append("consume")
        if self.marker:
            Path(self.marker).write_text(record.job_ref)
            await asyncio.sleep(3600)

    async def release(self, record):
        self.calls.append("release")

    async def hold_for_reconciliation(self, record):
        self.calls.append("hold")


async def lifecycle_client(args):
    import sys

    from redis.asyncio import Redis

    from src.control_plane.relay.lifecycle import InvocationLifecycleCoordinator
    from src.control_plane.relay.lifecycle_store import (
        InvocationLifecycleStore,
        JobReferenceStore,
    )

    request = json.loads(sys.stdin.read())
    identity = InvocationIdentity.model_validate(request["identity"])
    redis = Redis(host="127.0.0.1", port=args.redis_port)
    callbacks = ProcessCallbacks(args.consume_marker)
    target = ProtocolTarget(
        port=args.target_port,
        session_id=args.session_id,
        execution_target_id=identity.execution_target_id,
        drop_reply=args.drop_reply,
    )
    coordinator = InvocationLifecycleCoordinator(
        invocation_store=InvocationLifecycleStore(redis),
        job_reference_store=JobReferenceStore(redis),
    )
    try:
        if request.get("job_ref"):
            result = await coordinator.reconcile(
                target=target,
                job_ref=request["job_ref"],
                account_id=identity.account_id,
                provider_connection_id=identity.provider_connection_id,
                grant_callbacks=callbacks,
            )
        else:
            result = await coordinator.invoke(
                target=target,
                identity=identity,
                arguments=request.get("arguments", {}),
                grant_callbacks=callbacks,
            )
        print(json.dumps({"result": result, "callbacks": callbacks.calls}), flush=True)
    finally:
        await redis.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["target", "lifecycle"])
    parser.add_argument("--journal")
    parser.add_argument("--ready")
    parser.add_argument("--target-id")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--redis-port", type=int)
    parser.add_argument("--target-port", type=int)
    parser.add_argument("--drop-reply", action="store_true")
    parser.add_argument("--consume-marker")
    args = parser.parse_args()
    if args.mode == "target":
        target_server(args)
    else:
        asyncio.run(lifecycle_client(args))


if __name__ == "__main__":
    main()
