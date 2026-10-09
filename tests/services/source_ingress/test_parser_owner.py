"""The parser has one owned child and retains the actual coordinator lifetime."""

import hashlib
import importlib
import importlib.util
import os
import time
from contextlib import asynccontextmanager

import pytest

from src.services.agent_runs.coordinator import SourceWorkKind
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.source_ingress.reservation_contracts import ReservationRequest
from src.services.source_ingress.snapshot_codec import decode_snapshot
from src.services.source_ingress.snapshot_contracts import (
    RESERVED_CONTENT_BYTES,
    SnapshotLifecycle,
)
from src.services.source_ingress.snapshot_files import SnapshotFiles


def implementation():
    name = "src.services.source_ingress.parser_owner"
    assert importlib.util.find_spec(name) is not None, "owned bounded parser is absent"
    return importlib.import_module(name)


async def test_actual_fixed_child_preserves_exact_values_and_retires_parser_slot(
    tmp_path,
):
    module = implementation()
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )

    def forbidden():
        raise AssertionError("parser must not call a model provider")

    service = AgentRunService(store=store, provider_factory=forbidden)
    await service.start()
    root = tmp_path / "content"
    root.mkdir(mode=0o700)
    files = SnapshotFiles(root)
    files.open_root()
    attempt = SnapshotLifecycle(
        "1" * 32,
        "2" * 32,
        1,
        "receiving",
        int(time.time()) + 300,
        RESERVED_CONTENT_BYTES,
        "2" * 32 + ".raw",
        "2" * 32 + ".normalized",
    )
    owner = files.allocate(attempt)
    parser = module.OwnedParser(agent_runs=service)
    raw = b'Zip,Note,Formula\n00123,"line1\n\xe9\x9b\xaa",=2+2\n'
    request = ReservationRequest("request-a", len(raw), hashlib.sha256(raw).hexdigest())
    try:
        owner.create()
        owner.append(expected_offset=0, chunk=raw)
        owner.seal_raw(content_length=len(raw), content_sha256=request.content_sha256)
        result = parser.run(owner, request, deadline=time.monotonic() + 5)
        assert result.raw_content_sha256 == request.content_sha256
        assert result.raw_length == len(raw)
        assert result.row_count == 1 and result.column_count == 3
        normalized = os.pread(owner.normalized_fd, result.normalized_length, 0)
        snapshot = decode_snapshot(
            normalized,
            raw_content_sha256=result.raw_content_sha256,
            expected_identity=result.normalized_sha256,
            row_count=result.row_count,
            column_count=result.column_count,
        )
        assert snapshot.rows == (("00123", "line1\n雪", "=2+2"),)
        assert "00123" not in repr(result) and result.normalized_sha256 not in repr(
            result
        )
        borrow, _ = service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
        borrow.retire()
    finally:
        parser.close()
        owner.retire(remove_incomplete=True)
        files.close()
        await service.close()


@asynccontextmanager
async def prepared(tmp_path, raw):
    store = AgentRunStore(
        tmp_path / "runs.sqlite3",
        account_id="account-a",
        execution_target_id="target-a",
        create=True,
    )

    def forbidden():
        raise AssertionError("no provider work")

    service = AgentRunService(store=store, provider_factory=forbidden)
    await service.start()
    root = tmp_path / "content"
    root.mkdir(mode=0o700)
    files = SnapshotFiles(root)
    files.open_root()
    value = SnapshotLifecycle(
        "1" * 32,
        "2" * 32,
        1,
        "receiving",
        int(time.time()) + 300,
        RESERVED_CONTENT_BYTES,
        "2" * 32 + ".raw",
        "2" * 32 + ".normalized",
    )
    owner = files.allocate(value)
    parser = implementation().OwnedParser(agent_runs=service)
    request = ReservationRequest("request-a", len(raw), hashlib.sha256(raw).hexdigest())
    try:
        owner.create()
        for offset in range(0, len(raw), 65536):
            owner.append(expected_offset=offset, chunk=raw[offset : offset + 65536])
        owner.seal_raw(content_length=len(raw), content_sha256=request.content_sha256)
        yield service, owner, parser, request
    finally:
        parser.close()
        owner.retire(remove_incomplete=True)
        files.close()
        await service.close()


def boundary_raw(case):
    if case == "raw_cap":
        start = b"H\n" + (b"x" * 16384 + b"\n") * 63
        return start + b"y" * (1024 * 1024 - len(start) - 1) + b"\n"
    if case == "rows":
        return b"H\n" + b"ab\n" * 10000
    headers = ",".join(f"h{i}" for i in range(64)).encode() + b"\n"
    if case == "exact_normalized_cap":
        import csv
        import io

        names = [f"h{i}" for i in range(64)]
        base = 16 + 4 + sum(4 + len(value) for value in names) + 8000 * (4 + 64 * 4)
        gap = 2 * 1024 * 1024 - base
        first = min(gap, 16384)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(names)
        writer.writerow(["x" * first, "y" * (gap - first), *([""] * 62)])
        writer.writerows([[""] * 64] * 7999)
        return stream.getvalue().encode()
    if case == "unicode_columns":
        return headers + (("雪" * 5000 + ",") * 63 + "雪" * 5000 + "\n").encode()
    if case == "normalized_cap":
        return headers + (b"ab," * 63 + b"ab\n") * 5400
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    ["raw_cap", "rows", "unicode_columns", "normalized_cap", "exact_normalized_cap"],
)
async def test_legitimate_boundary_shapes_fit_actual_child_profile(
    tmp_path, monkeypatch, record_property, case
):
    import threading
    from pathlib import Path

    from src.services.source_ingress.csv_snapshot import parse_csv_snapshot

    raw = boundary_raw(case)
    expected = parse_csv_snapshot(
        raw,
        content_length=len(raw),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="text/csv",
    )
    observed = []
    stop = threading.Event()
    sampler = None
    async with prepared(tmp_path, raw) as (_service, owner, parser, request):
        original = parser._spawn

        def spawn(files, declared):
            nonlocal sampler
            original(files, declared)
            pid = parser._child.pid

            def sample():
                while not stop.wait(0.002):
                    try:
                        limits = Path(f"/proc/{pid}/limits").read_text()
                        status = Path(f"/proc/{pid}/status").read_text()
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    address_line = next(
                        (
                            line
                            for line in limits.splitlines()
                            if line.startswith("Max address space")
                        ),
                        "",
                    )
                    file_line = next(
                        (
                            line
                            for line in limits.splitlines()
                            if line.startswith("Max file size")
                        ),
                        "",
                    )
                    cpu_line = next(
                        (
                            line
                            for line in status.splitlines()
                            if line.startswith("Cpus_allowed_list:")
                        ),
                        "",
                    )
                    rss_line = next(
                        (
                            line
                            for line in status.splitlines()
                            if line.startswith("VmRSS:")
                        ),
                        "VmRSS: 0 kB",
                    )
                    if (
                        "67108864" in address_line
                        and "2097152" in file_line
                        and cpu_line
                        and "," not in cpu_line
                        and "-" not in cpu_line
                    ):
                        observed.append(int(rss_line.split()[1]))

            sampler = threading.Thread(target=sample)
            sampler.start()

        monkeypatch.setattr(parser, "_spawn", spawn)
        try:
            start = time.monotonic()
            result = parser.run(owner, request, deadline=start + 5)
            elapsed = time.monotonic() - start
        finally:
            stop.set()
            if sampler is not None:
                sampler.join(timeout=1)
                assert not sampler.is_alive()
        assert result.row_count == expected.row_count
        assert result.column_count == expected.column_count
        assert result.normalized_sha256 == expected.snapshot_identity
        assert elapsed < 5
        assert observed, "actual child limits/one-CPU profile was not observed"
        record_property("case", case)
        record_property("raw_bytes", len(raw))
        record_property("normalized_bytes", result.normalized_length)
        record_property("enforced_address_space_bytes", 64 * 1024 * 1024)
        record_property("sampled_child_rss_kib", max(observed))
        record_property("wall_seconds", elapsed)


@pytest.mark.parametrize("after_setup", [100.75, 102.0])
def test_worker_timer_uses_remaining_original_deadline_after_setup(
    monkeypatch, after_setup
):
    from src.services.source_ingress import parser_worker

    class TimerInstalled(BaseException):
        pass

    clock = [100.0]
    timers = []
    monkeypatch.setattr(
        parser_worker.sys,
        "argv",
        ["fixed-worker", "10", "11", "12", "8", "0" * 64, "101.0"],
    )
    monkeypatch.setattr(parser_worker.time, "monotonic", lambda: clock[0])

    def configure(*_args):
        clock[0] = after_setup

    monkeypatch.setattr(parser_worker.resource, "setrlimit", configure)
    monkeypatch.setattr(parser_worker.os, "sched_getaffinity", lambda _pid: {0})
    monkeypatch.setattr(parser_worker.os, "sched_setaffinity", lambda *_args: None)
    monkeypatch.setattr(parser_worker.signal, "signal", lambda *_args: None)

    def install(_kind, remaining):
        timers.append(remaining)
        raise TimerInstalled()

    monkeypatch.setattr(parser_worker.signal, "setitimer", install)
    if after_setup > 101:
        with pytest.raises(SystemExit):
            parser_worker.main()
        assert not timers
    else:
        with pytest.raises(TimerInstalled):
            parser_worker.main()
        assert timers == [0.25]


def copied_worker(tmp_path, monkeypatch, transform=lambda value: value):
    from pathlib import Path

    module = implementation()
    origin = Path(module.__file__).parent
    target = tmp_path / "isolated-package" / "src" / "services" / "source_ingress"
    target.mkdir(parents=True)
    for name in ("parser_worker.py", "csv_snapshot.py", "snapshot_codec.py"):
        data = (origin / name).read_bytes()
        if name == "parser_worker.py":
            data = transform(data.decode()).encode()
        (target / name).write_bytes(data)
    monkeypatch.setattr(module, "__file__", str(target / "parser_owner.py"))
    return target


async def test_real_child_excludes_eager_application_and_ambient_settings(
    tmp_path, monkeypatch
):
    import subprocess
    from pathlib import Path

    target = copied_worker(tmp_path, monkeypatch)
    marker = tmp_path / "unexpected-import"
    trap = f"from pathlib import Path\nPath({str(marker)!r}).write_text('unexpected')\nraise RuntimeError('eager initialization must not execute')\n"
    for directory in (target, target.parent, target.parent.parent):
        (directory / "__init__.py").write_text(trap)
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "sitecustomize.py").write_text(trap)
    monkeypatch.setenv("PYTHONPATH", str(ambient))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SYNTHETIC_ENVIRONMENT_CANARY")
    monkeypatch.setenv("SHIPAGENT_AGENT_MODEL", "SYNTHETIC_MODEL_CANARY")
    observed = []
    original = subprocess.Popen.__init__

    def inspect_spawn(child, *args, **kwargs):
        observed.append(kwargs.get("env"))
        return original(child, *args, **kwargs)

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (_service, owner, parser, request):
        with monkeypatch.context() as patch:
            patch.setattr(subprocess.Popen, "__init__", inspect_spawn)
            result = parser.run(owner, request, deadline=time.monotonic() + 5)
        assert result.row_count == 1
    assert observed == [{"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}]
    assert not marker.exists()
    origin = Path(__file__).resolve().parents[3] / "src" / "services" / "source_ingress"
    for name in ("parser_worker.py", "csv_snapshot.py", "snapshot_codec.py"):
        assert (target / name).read_bytes() == (origin / name).read_bytes()


@pytest.mark.parametrize(
    "case",
    [
        "zero",
        "oversized",
        "truncated",
        "extra",
        "duplicate",
        "unknown",
        "nested",
        "exit7",
        "full_pipe",
        "memory",
        "file_cap",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "utf-32",
        "utf-32-le",
        "utf-32-be",
        "utf-8-sig",
    ],
)
async def test_owned_child_failures_and_closed_result_frames_are_private(
    tmp_path, monkeypatch, case
):
    replacements = {
        "zero": "frame = b'\\x00\\x00\\x00\\x00'",
        "oversized": "frame = (1025).to_bytes(4, 'big')",
        "truncated": "frame = (1024).to_bytes(4, 'big') + b'PRIVATE_TRUNCATED_CANARY'",
        "extra": "frame += b'PRIVATE_EXTRA_CANARY'",
        "duplicate": 'payload = b\'{"status":"ok","status":"ok"}\'; frame = len(payload).to_bytes(4,\'big\') + payload',
        "unknown": "result['PRIVATE_UNKNOWN_CANARY'] = 'private'; encoded = json.dumps(result).encode(); frame = len(encoded).to_bytes(4,'big') + encoded",
        "nested": "result['row_count'] = {'PRIVATE_NESTED_CANARY': 1}; encoded = json.dumps(result).encode(); frame = len(encoded).to_bytes(4,'big') + encoded",
        "full_pipe": "frame = (1025).to_bytes(4,'big') + b'x' * (2*1024*1024)",
        "memory": "frame = bytearray(128*1024*1024)",
        "file_cap": "os.pwrite(normalized_fd, b'x' * (2*1024*1024+1), 0); os.pwrite(normalized_fd, b'x', 2*1024*1024)",
    }

    def transform(text):
        if case.startswith("utf-"):
            # The child emits otherwise valid facts, but the channel is UTF-8 only.
            replacement = (
                f"encoded = json.dumps(result, separators=(',', ':')).encode({case!r}); "
                "frame = len(encoded).to_bytes(4, 'big') + encoded"
            )
            return text.replace(
                "    if os.write(1, frame)",
                "    " + replacement + "\n    if os.write(1, frame)",
            )
        if case == "exit7":
            return text.replace(
                "    # The actual inherited",
                "    raise SystemExit(7)\n    # The actual inherited",
            )
        return text.replace(
            "    if os.write(1, frame)",
            "    " + replacements[case] + "\n    if os.write(1, frame)",
        )

    copied_worker(tmp_path, monkeypatch, transform)
    raw = b"Zip\n00123\n"
    from src.services.source_ingress.reservation_contracts import ReservationError

    async with prepared(tmp_path, raw) as (service, owner, parser, request):
        with pytest.raises(ReservationError) as error:
            parser.run(owner, request, deadline=time.monotonic() + 5)
        assert "PRIVATE_" not in str(error.value)
        assert parser._child.returncode is not None
        if case == "file_cap":
            assert os.fstat(owner.normalized_fd).st_size <= 2 * 1024 * 1024
        borrow, _ = service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
        borrow.retire()


async def test_parent_sigkill_cannot_release_a_live_parser_pin(
    tmp_path, monkeypatch, record_property
):
    import json
    import select
    import signal
    import subprocess
    import sys
    from pathlib import Path

    from src.services.agent_runs.coordinator import CoordinatorLease

    def delayed(text):
        return text.replace(
            "    resource.setrlimit(resource.RLIMIT_AS",
            "    time.sleep(0.6)\n    resource.setrlimit(resource.RLIMIT_AS",
            1,
        ).replace("    import hashlib", "    time.sleep(10)\n    import hashlib", 1)

    target = copied_worker(tmp_path, monkeypatch, delayed)
    data_root = tmp_path / "owner"
    data_root.mkdir(mode=0o700)
    script = r"""
import asyncio, hashlib, json, sys, time
from pathlib import Path
from src.services.agent_runs.service import AgentRunService
from src.services.agent_runs.store import AgentRunStore
from src.services.source_ingress import parser_owner
from src.services.source_ingress.snapshot_files import SnapshotFiles
from src.services.source_ingress.snapshot_contracts import SnapshotLifecycle, RESERVED_CONTENT_BYTES
from src.services.source_ingress.reservation_contracts import ReservationRequest
async def main():
    root = Path(sys.argv[1])
    parser_owner.__file__ = str(Path(sys.argv[2]) / 'parser_owner.py')
    store = AgentRunStore(root/'runs.sqlite3', account_id='account-a', execution_target_id='target-a', create=True)
    service = AgentRunService(store=store, provider_factory=lambda: None)
    await service.start()
    content = root/'content'; content.mkdir(mode=0o700)
    files = SnapshotFiles(content); files.open_root()
    value = SnapshotLifecycle('1'*32,'2'*32,1,'receiving',int(time.time())+300,RESERVED_CONTENT_BYTES,'2'*32+'.raw','2'*32+'.normalized')
    owner = files.allocate(value); owner.create()
    raw = b'Zip\n00123\n'; request = ReservationRequest('request-a',len(raw),hashlib.sha256(raw).hexdigest())
    owner.append(expected_offset=0,chunk=raw); owner.seal_raw(content_length=len(raw),content_sha256=request.content_sha256)
    parser = parser_owner.OwnedParser(agent_runs=service)
    original = parser._spawn
    def spawned(files, request):
        original(files, request)
        print(json.dumps({'child':parser._child.pid,'deadline':parser._deadline,'generation':service._generation,'lock':str(parser._borrow.coordinator_path)}),flush=True)
    parser._spawn = spawned
    parser.run(owner,request,deadline=time.monotonic()+2)
asyncio.run(main())
"""
    parent = subprocess.Popen(
        [sys.executable, "-c", script, str(data_root), str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child = None
    acquired = None
    try:
        ready, _, _ = select.select([parent.stdout], [], [], 6)
        assert ready, "owned parent did not report its captured child"
        line = parent.stdout.readline()
        assert line, parent.stderr.read()
        info = json.loads(line)
        child = info["child"]
        while time.monotonic() < info["deadline"]:
            limits = Path(f"/proc/{child}/limits").read_text()
            if "Max address space         67108864" in limits:
                break
            time.sleep(0.005)
        else:
            raise AssertionError("live child bootstrap was not observed")
        # The fixed test worker remains asleep after installing its original timer.
        assert Path(f"/proc/{child}/stat").read_text().split()[2] != "Z"
        parent.kill()
        assert parent.wait(timeout=2) == -signal.SIGKILL
        with pytest.raises(RuntimeError, match="already has a coordinator"):
            CoordinatorLease(Path(info["lock"]))
        while time.monotonic() < info["deadline"] + 0.5:
            try:
                acquired = CoordinatorLease(Path(info["lock"]))
                break
            except RuntimeError:
                time.sleep(0.005)
        assert acquired is not None, (
            "replacement remained blocked beyond the original child deadline"
        )
        record_property(
            "remaining_budget_seconds_after_parent_death",
            info["deadline"] - time.monotonic(),
        )
        acquired.close()
        acquired = None
        store = AgentRunStore(
            data_root / "runs.sqlite3",
            account_id="account-a",
            execution_target_id="target-a",
        )
        service = AgentRunService(store=store, provider_factory=lambda: None)
        await service.start()
        try:
            assert service._generation > info["generation"]
        finally:
            await service.close()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        parent.stdout.close()
        parent.stderr.close()
        if acquired is not None:
            acquired.close()
        # No guessed PID cleanup: the fixed child's own absolute timer bounds it.
        if child is not None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                path = Path(f"/proc/{child}/stat")
                if not path.exists() or path.read_text().split()[2] == "Z":
                    break
                time.sleep(0.01)


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("interrupt", [False, True])
async def test_spawn_hook_before_or_after_effect_retires_captured_ownership(
    tmp_path, monkeypatch, after, interrupt
):
    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (service, owner, parser, request):
        original = parser._spawn

        def fail(files, declared):
            if after:
                original(files, declared)
            if interrupt:
                raise KeyboardInterrupt("synthetic spawn interruption")
            raise OSError("PRIVATE_SPAWN_ERROR")

        monkeypatch.setattr(parser, "_spawn", fail)
        with pytest.raises(KeyboardInterrupt if interrupt else ReservationError):
            parser.run(owner, request, deadline=time.monotonic() + 5)
        assert parser._retired
        if after:
            assert parser._child.returncode is not None
        borrow, _ = service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
        borrow.retire()


async def test_signaling_failure_retains_slot_and_unrelated_provider_child(
    tmp_path, monkeypatch
):
    copied_worker(
        tmp_path,
        monkeypatch,
        lambda text: text.replace(
            "    import hashlib", "    time.sleep(1)\n    import hashlib", 1
        ),
    )
    import subprocess
    import sys

    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    provider = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        async with prepared(tmp_path, raw) as (service, owner, parser, request):

            def fail(*_args):
                raise OSError("PRIVATE_SIGNAL_FAILURE")

            with monkeypatch.context() as patch:
                patch.setattr(parser, "_read_result", fail)
                patch.setattr(parser, "_signal", fail)
                with pytest.raises(ReservationError):
                    parser.run(owner, request, deadline=time.monotonic() + 5)
            assert not parser._retired
            assert not parser._borrow.retirement_completed
            assert provider.poll() is None
            with pytest.raises(RuntimeError):
                service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
            parser.close()
            assert parser._child.returncode is not None
            assert parser._borrow.retirement_completed
            assert provider.poll() is None
            with pytest.raises(RuntimeError):
                service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
    finally:
        provider.terminate()
        provider.wait(timeout=2)


async def test_parent_deadline_kills_only_owned_resistant_child_before_pin_retirement(
    tmp_path, monkeypatch
):
    from src.services.source_ingress.reservation_contracts import ReservationError

    def resistant(text):
        return text.replace(
            "    import hashlib",
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n    signal.signal(signal.SIGALRM, signal.SIG_IGN)\n    time.sleep(10)\n    import hashlib",
            1,
        )

    copied_worker(tmp_path, monkeypatch, resistant)
    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (_service, owner, parser, request):
        started = time.monotonic()
        with pytest.raises(ReservationError):
            parser.run(owner, request, deadline=started + 0.3)
        assert time.monotonic() - started < 1
        until = time.monotonic() + 1
        while True:
            try:
                parser.close()
                break
            except ReservationError:
                assert not parser._borrow.retirement_completed
                assert time.monotonic() < until
                time.sleep(0.005)
        assert parser._child.returncode is not None
        assert parser._borrow.retirement_completed


@pytest.mark.parametrize("after", [False, True])
async def test_wait_failure_keeps_positive_child_retirement_separate(
    tmp_path, monkeypatch, after
):
    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (service, owner, parser, request):
        original_spawn = parser._spawn
        original_wait = None

        def spawned(files, declared):
            nonlocal original_wait
            original_spawn(files, declared)
            original_wait = parser._child.wait

            def fail(*args, **kwargs):
                if after:
                    original_wait(*args, **kwargs)
                raise OSError("PRIVATE_WAIT_ERROR")

            monkeypatch.setattr(parser._child, "wait", fail)

        monkeypatch.setattr(parser, "_spawn", spawned)
        with pytest.raises(ReservationError):
            parser.run(owner, request, deadline=time.monotonic() + 5)
        assert not parser._borrow.retirement_completed
        with pytest.raises(RuntimeError):
            service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
        monkeypatch.setattr(parser._child, "wait", original_wait)
        parser.close()
        assert parser._borrow.retirement_completed
        with pytest.raises(RuntimeError):
            service.borrow_coordinator(source_work=SourceWorkKind.PARSER)


@pytest.mark.parametrize("after", [False, True])
def test_unknown_constructor_spawn_retains_physical_ownership_until_process_exit(
    tmp_path, after
):
    import select
    import subprocess
    import sys

    from src.services.agent_runs.coordinator import CoordinatorLease

    root = tmp_path / "unknown-owner"
    root.mkdir(mode=0o700)
    script = r"""
import hashlib, sys, time, subprocess
from pathlib import Path
from unittest.mock import patch
from src.services.agent_runs.coordinator import CoordinatorLease, SourceWorkKind
from src.services.source_ingress.parser_owner import OwnedParser
from src.services.source_ingress.snapshot_files import SnapshotFiles
from src.services.source_ingress.snapshot_contracts import SnapshotLifecycle, RESERVED_CONTENT_BYTES
from src.services.source_ingress.reservation_contracts import ReservationRequest, ReservationError
root=Path(sys.argv[1]); lease=CoordinatorLease(root/'owner.lock')
class Broker:
    def borrow_coordinator(self, **kwargs): return lease.borrow(**kwargs), 1
content=root/'content'; content.mkdir(mode=0o700)
files=SnapshotFiles(content); files.open_root()
owner=files.allocate(SnapshotLifecycle('1'*32,'2'*32,1,'receiving',int(time.time())+300,RESERVED_CONTENT_BYTES,'2'*32+'.raw','2'*32+'.normalized'))
owner.create(); raw=b'Zip\n00123\n'; request=ReservationRequest('request-a',len(raw),hashlib.sha256(raw).hexdigest())
owner.append(expected_offset=0,chunk=raw); owner.seal_raw(content_length=len(raw),content_sha256=request.content_sha256)
parser=OwnedParser(agent_runs=Broker()); original=subprocess.Popen.__init__
def interrupted(child,*args,**kwargs):
    if sys.argv[2]=='True': original(child,*args,**kwargs)
    raise KeyboardInterrupt('synthetic unknown spawn')
with patch.object(subprocess.Popen,'__init__',interrupted):
    try: parser.run(owner,request,deadline=time.monotonic()+5)
    except KeyboardInterrupt: pass
    else: raise AssertionError('spawn interruption was swallowed')
assert parser._spawn_uncertain and not parser._borrow.retirement_completed
try: parser.close()
except ReservationError: pass
else: raise AssertionError('unknown spawn retired')
try: lease.borrow(source_work=SourceWorkKind.PARSER)
except RuntimeError: pass
else: raise AssertionError('quarantine bypassed')
if sys.argv[2]=='True': parser._child.wait(timeout=5)
print('retained',flush=True)
assert sys.stdin.readline().strip()=='exit'
# Intentionally uncertain owned descriptors remain pinned until this process exits.
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root), str(after)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 7)
        assert ready
        line = process.stdout.readline()
        assert line.strip() == "retained", process.stderr.read()
        with pytest.raises(RuntimeError):
            CoordinatorLease(root / "owner.lock")
        out, err = process.communicate("exit\n", timeout=3)
        assert process.returncode == 0, err
        assert not out
        replacement = CoordinatorLease(root / "owner.lock")
        replacement.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@pytest.mark.parametrize("after", [False, True])
async def test_result_pipe_close_fault_uses_real_closed_state_before_retry(
    tmp_path, monkeypatch, after
):
    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (_service, owner, parser, request):
        original_spawn = parser._spawn
        original_close = None
        calls = []

        def spawned(files, declared):
            nonlocal original_close
            original_spawn(files, declared)
            original_close = parser._child.stdout.close

            def fail():
                calls.append(1)
                if after:
                    original_close()
                raise OSError("PRIVATE_PIPE_CLOSE_ERROR")

            monkeypatch.setattr(parser._child.stdout, "close", fail)

        monkeypatch.setattr(parser, "_spawn", spawned)
        try:
            with pytest.raises(ReservationError):
                parser.run(owner, request, deadline=time.monotonic() + 5)
            if after:
                assert parser._borrow.retirement_completed
                assert len(calls) == 1
            else:
                assert not parser._borrow.retirement_completed
        finally:
            monkeypatch.setattr(parser._child.stdout, "close", original_close)
            parser.close()


async def test_response_deadline_crossed_during_retirement_keeps_no_fresh_result(
    tmp_path, monkeypatch
):
    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (_service, owner, parser, request):
        original = parser._retire

        def delayed():
            original()
            parser._monotonic = lambda: parser._deadline + 1

        monkeypatch.setattr(parser, "_retire", delayed)
        with pytest.raises(ReservationError):
            parser.run(owner, request, deadline=time.monotonic() + 5)
        assert parser._borrow.retirement_completed
        assert parser._child.returncode == 0


async def test_concurrent_close_and_copied_owner_cannot_retire_a_live_child(
    tmp_path, monkeypatch
):
    import concurrent.futures
    import copy
    import threading

    from src.services.source_ingress.reservation_contracts import ReservationError

    copied_worker(
        tmp_path,
        monkeypatch,
        lambda text: text.replace(
            "    import hashlib", "    time.sleep(0.3)\n    import hashlib", 1
        ),
    )
    raw = b"Zip\n00123\n"
    spawned = threading.Event()
    retired = []
    async with prepared(tmp_path, raw) as (service, owner, parser, request):
        original = parser._spawn

        def traced(files, declared):
            original(files, declared)
            original_retire = parser._pin.retire

            def checked():
                assert parser._child.returncode is not None
                assert parser._child.stdout.closed
                retired.append(True)
                return original_retire()

            monkeypatch.setattr(parser._pin, "retire", checked)
            spawned.set()

        monkeypatch.setattr(parser, "_spawn", traced)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(
                parser.run, owner, request, deadline=time.monotonic() + 5
            )
            assert spawned.wait(2)
            assert parser._child.poll() is None
            replacement = implementation().OwnedParser(agent_runs=service)
            with pytest.raises(ReservationError):
                replacement.run(owner, request, deadline=time.monotonic() + 5)
            replacement.close()
            assert parser._child.poll() is None
            with pytest.raises(ReservationError):
                parser.close()
            clone = copy.copy(parser)
            with pytest.raises(ReservationError):
                clone.close()
            with pytest.raises(RuntimeError):
                service._lease.close()
            assert service._lease.is_owned()
            assert not parser._borrow.retirement_completed
            assert not retired
            assert running.result(timeout=3).row_count == 1
        assert retired == [True]
        assert parser._borrow.retirement_completed


async def test_inherited_parser_rejects_before_its_copied_mutex(tmp_path):
    import select
    import signal

    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (_service, _owner, parser, _request):
        read_fd, write_fd = os.pipe()
        parser._lock.acquire()
        child = os.fork()
        if child == 0:
            try:
                os.close(read_fd)
                try:
                    parser.close()
                except ReservationError:
                    os.write(write_fd, b"denied")
            finally:
                os._exit(0)
        os.close(write_fd)
        try:
            ready, _, _ = select.select([read_fd], [], [], 1)
            if not ready:
                os.kill(child, signal.SIGKILL)
            assert ready and os.read(read_fd, 16) == b"denied"
        finally:
            os.waitpid(child, 0)
            os.close(read_fd)
            parser._lock.release()


async def test_fixed_worker_does_not_create_bytecode_outside_owned_output(
    tmp_path, monkeypatch
):
    target = copied_worker(tmp_path, monkeypatch)
    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (_service, owner, parser, request):
        assert parser.run(owner, request, deadline=time.monotonic() + 5).row_count == 1
    assert not list(target.rglob("__pycache__"))


async def test_admitted_parser_reserves_slot_without_spawning_and_keeps_deadline(
    tmp_path,
):
    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (service, owner, parser, request):
        deadline = time.monotonic() + 4
        parser.admit(deadline=deadline)
        assert parser._child is None
        assert parser._deadline == deadline
        contender = implementation().OwnedParser(agent_runs=service)
        try:
            with pytest.raises(ReservationError):
                contender.admit(deadline=time.monotonic() + 5)
            assert contender._child is None
        finally:
            contender.close()
        with pytest.raises(ReservationError):
            parser.admit(deadline=time.monotonic() + 5)
        assert parser.run(owner, request, deadline=time.monotonic() + 5).row_count == 1
        assert parser._deadline == deadline
        assert parser._borrow.retirement_completed


async def test_expired_admission_cannot_spawn_or_renew_budget(tmp_path, monkeypatch):
    from src.services.source_ingress.reservation_contracts import ReservationError

    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (service, owner, parser, request):
        now = [time.monotonic()]
        monkeypatch.setattr(parser, "_monotonic", lambda: now[0])
        parser.admit(deadline=now[0] + 2)
        now[0] += 3
        with pytest.raises(ReservationError):
            parser.run(owner, request, deadline=now[0] + 5)
        assert parser._child is None
        assert parser._borrow.retirement_completed
        borrow, _ = service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
        borrow.retire()


async def test_unconsumed_parser_admission_retires_without_child(tmp_path):
    raw = b"Zip\n00123\n"
    async with prepared(tmp_path, raw) as (service, _owner, parser, _request):
        parser.admit(deadline=time.monotonic() + 5)
        parser.close()
        assert parser._child is None
        assert parser._borrow.retirement_completed
        borrow, _ = service.borrow_coordinator(source_work=SourceWorkKind.PARSER)
        borrow.retire()
