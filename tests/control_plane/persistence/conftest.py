"""Opt-in real services, created here and never pointed at existing databases."""

import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def disposable_control_stores():
    configured = os.environ.get("SHIPAGENT_TEST_SERVICE_ROOT")
    if not configured:
        pytest.skip("real Redis/PostgreSQL requires SHIPAGENT_TEST_SERVICE_ROOT")
    root = Path(configured)
    pg = root / "usr/lib/postgresql/17/bin"
    redis = root / "usr/bin/redis-server"
    assert (pg / "postgres").is_file() and redis.is_file(), (
        "real-service binaries missing"
    )
    env = {**os.environ, "LD_LIBRARY_PATH": str(root / "usr/lib/x86_64-linux-gnu")}

    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return str(sock.getsockname()[1])

    with tempfile.TemporaryDirectory(prefix="shipagent-stores-") as directory:
        path = Path(directory)
        path.chmod(0o700)
        pg_port, redis_port = free_port(), free_port()
        assert pg_port != redis_port
        subprocess.run(
            [
                str(pg / "initdb"),
                "-D",
                str(path / "data"),
                "-L",
                str(root / "usr/share/postgresql/17"),
                "-U",
                "shipagent_test",
                "-A",
                "trust",
                "--no-locale",
                "-E",
                "UTF8",
            ],
            env=env,
            check=True,
            capture_output=True,
            timeout=15,
        )
        processes = []
        with (path / "services.log").open("w") as log:
            try:
                processes.append(
                    subprocess.Popen(
                        [
                            str(pg / "postgres"),
                            "-D",
                            str(path / "data"),
                            "-k",
                            "",
                            "-h",
                            "127.0.0.1",
                            "-p",
                            pg_port,
                            "-c",
                            "shared_buffers=16MB",
                            "-c",
                            "max_connections=20",
                            "-c",
                            "jit=off",
                        ],
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                processes.append(
                    subprocess.Popen(
                        [
                            str(redis),
                            "--bind",
                            "127.0.0.1",
                            "--port",
                            redis_port,
                            "--save",
                            "",
                            "--appendonly",
                            "no",
                            "--dir",
                            directory,
                        ],
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                for _ in range(200):
                    assert all(p.poll() is None for p in processes), (
                        "disposable service exited"
                    )
                    ready = (
                        subprocess.run(
                            [
                                str(pg / "pg_isready"),
                                "-h",
                                "127.0.0.1",
                                "-p",
                                pg_port,
                            ],
                            env=env,
                            capture_output=True,
                            timeout=2,
                        ).returncode
                        == 0
                    )
                    if ready:
                        break
                    time.sleep(0.025)
                else:
                    pytest.fail("disposable PostgreSQL startup timed out")
                yield {
                    "postgres_url": f"postgresql+asyncpg://shipagent_test@127.0.0.1:{pg_port}/postgres",
                    "redis_port": int(redis_port),
                    "log_path": path / "services.log",
                }
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.send_signal(signal.SIGTERM)
                for process in processes:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


@pytest.fixture
async def real_redis(disposable_control_stores):
    client = Redis(host="127.0.0.1", port=disposable_control_stores["redis_port"])
    assert await client.ping()
    await client.flushdb()  # This process owns this new server exclusively.
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def postgres_db(disposable_control_stores):
    from src.control_plane.audit import models  # noqa: F401
    from src.control_plane.models import ControlPlaneBase

    engine = create_async_engine(disposable_control_stores["postgres_url"])
    async with engine.begin() as connection:
        await connection.run_sync(ControlPlaneBase.metadata.drop_all)
        await connection.run_sync(ControlPlaneBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
