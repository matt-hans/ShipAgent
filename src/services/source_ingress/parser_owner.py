"""One retained fixed parser child; no transport, source or publication authority."""

from __future__ import annotations

import hashlib
import json
import math
import os
import select
import signal
import subprocess
import sys
import threading
import time
import weakref
from dataclasses import dataclass, fields
from pathlib import Path

from src.services.agent_runs.coordinator import SourceWorkKind
from src.services.source_ingress.csv_snapshot import (
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_NORMALIZED_BYTES,
    PARSER_PROFILE,
)
from src.services.source_ingress.reservation_contracts import (
    ReservationError,
    ReservationRequest,
)
from src.services.source_ingress.snapshot_codec import decode_snapshot
from src.services.source_ingress.snapshot_files import OwnedSnapshotFiles


@dataclass(frozen=True, slots=True, repr=False)
class ParserManifest:
    raw_content_sha256: str
    normalized_sha256: str
    raw_length: int
    normalized_length: int
    row_count: int
    column_count: int
    parser_profile: str = PARSER_PROFILE


def _unavailable():
    return ReservationError("reservation_unavailable")


class OwnedParser:
    """Capture before run. An uncertain spawn/wait retains its physical lease pin."""

    def __init__(self, *, agent_runs, monotonic=time.monotonic, source_binding=None):
        self._agent_runs = agent_runs
        self._monotonic = monotonic
        self._source_binding = source_binding
        self._pid = os.getpid()
        self._self = weakref.ref(self)
        self._lock = threading.Lock()
        self._running = False
        self._attempted = False
        self._admission_attempted = False
        self._admitted = False
        self._retired = False
        self._borrow = None
        self._pin = None
        self._child = None
        self._spawn_attempted = False
        self._spawn_uncertain = False
        self._deadline = 0.0

    def _require_identity(self):
        if self._pid != os.getpid() or self._self() is not self:
            raise _unavailable()

    def _remaining(self):
        now = self._monotonic()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or now >= self._deadline
        ):
            raise _unavailable()
        return self._deadline - now

    def _spawn(self, files, request):
        raw_fd, normalized_fd, pin_fd = (
            files.raw_fd,
            files.normalized_fd,
            self._pin.child_fd,
        )
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(Path(__file__).with_name("parser_worker.py")),
            str(raw_fd),
            str(normalized_fd),
            str(pin_fd),
            str(request.content_length),
            request.content_sha256,
            repr(self._deadline),
        ]
        # Capture the exact Popen owner before constructor pipe/spawn effects.
        self._child = subprocess.Popen.__new__(subprocess.Popen)
        self._spawn_attempted = True
        try:
            self._child.__init__(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                close_fds=True,
                pass_fds=(raw_fd, normalized_fd, pin_fd),
                start_new_session=True,
            )
        except BaseException:
            self._spawn_uncertain = True
            raise
        os.set_blocking(self._child.stdout.fileno(), False)

    def _read_bytes(self, count):
        result = bytearray()
        fd = self._child.stdout.fileno()
        while len(result) < count:
            ready, _, _ = select.select([fd], [], [], self._remaining())
            if not ready:
                raise _unavailable()
            try:
                block = os.read(fd, count - len(result))
            except BlockingIOError:
                continue
            if not block:
                raise _unavailable()
            result.extend(block)
        return bytes(result)

    def _read_result(self):
        length = int.from_bytes(self._read_bytes(4), "big")
        if not 0 < length <= 1024:
            raise _unavailable()
        payload = self._read_bytes(length)
        fd = self._child.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], self._remaining())
            if not ready:
                raise _unavailable()
            try:
                extra = os.read(fd, 1)
            except BlockingIOError:
                continue
            if extra:
                raise _unavailable()
            break

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise _unavailable()
                result[key] = value
            return result

        result = json.loads(
            payload.decode("utf-8", errors="strict"), object_pairs_hook=pairs
        )
        if (
            type(result) is not dict
            or result.pop("status", None) != "ok"
            or set(result) != {field.name for field in fields(ParserManifest)}
        ):
            raise _unavailable()
        return ParserManifest(**result)

    def _verify(self, files, request, result):
        if (
            result.parser_profile != PARSER_PROFILE
            or result.raw_length != request.content_length
            or result.raw_content_sha256 != request.content_sha256
        ):
            raise _unavailable()
        for value, maximum in (
            (result.row_count, MAX_DATA_ROWS),
            (result.column_count, MAX_COLUMNS),
            (result.normalized_length, MAX_NORMALIZED_BYTES),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise _unavailable()
        raw_fd, normalized_fd = files.raw_fd, files.normalized_fd
        if (
            os.fstat(raw_fd).st_size != result.raw_length
            or os.fstat(normalized_fd).st_size != result.normalized_length
        ):
            raise _unavailable()
        raw = os.pread(raw_fd, result.raw_length + 1, 0)
        normalized = os.pread(normalized_fd, result.normalized_length + 1, 0)
        if (
            len(raw) != result.raw_length
            or len(normalized) != result.normalized_length
            or hashlib.sha256(raw).hexdigest() != request.content_sha256
        ):
            raise _unavailable()
        decode_snapshot(
            normalized,
            raw_content_sha256=result.raw_content_sha256,
            expected_identity=result.normalized_sha256,
            row_count=result.row_count,
            column_count=result.column_count,
        )
        if files.raw_fd != raw_fd or files.normalized_fd != normalized_fd:
            raise _unavailable()

    def _quarantine(self):
        if self._borrow is not None and not self._borrow.retirement_completed:
            self._borrow.quarantine()

    def _signal(self, kind):
        if self._child.poll() is None:
            os.killpg(self._child.pid, kind)

    def _retire(self):
        if self._spawn_uncertain:
            raise _unavailable()
        if self._child is not None:
            if self._child.poll() is None:
                self._signal(signal.SIGTERM)
                remaining = max(0, self._deadline - self._monotonic())
                try:
                    self._child.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    self._signal(signal.SIGKILL)
                    self._child.wait(timeout=max(0, self._deadline - self._monotonic()))
            self._child.wait(timeout=0)
            if self._child.stdout is not None:
                if not self._child.stdout.closed:
                    self._child.stdout.close()
                if not self._child.stdout.closed:
                    raise _unavailable()
        if self._pin is not None:
            self._pin.retire()
        if self._borrow is not None:
            self._borrow.retire()
            if not self._borrow.retirement_completed:
                raise _unavailable()
        self._retired = True

    def _admit(self, deadline):
        self._admission_attempted = True
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise _unavailable()
        self._deadline = min(deadline, self._monotonic() + 5)
        self._remaining()
        if self._source_binding is None:
            self._borrow, _ = self._agent_runs.borrow_coordinator(
                source_work=SourceWorkKind.PARSER
            )
        else:
            self._borrow, _ = self._agent_runs.borrow_coordinator(
                source_work=SourceWorkKind.PARSER, source_binding=self._source_binding
            )
        self._pin = self._borrow.allocate_process_pin()
        self._pin.acquire()
        self._remaining()
        self._admitted = True

    def admit(self, *, deadline: float) -> None:
        """Pin a parser slot before a separate, known parsing-phase COMMIT."""
        self._require_identity()
        with self._lock:
            if self._admission_attempted or self._running or self._retired:
                raise _unavailable()
            self._running = True
        try:
            self._admit(deadline)
        except BaseException as error:
            try:
                self._retire()
            except BaseException:
                self._quarantine()
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        finally:
            with self._lock:
                self._running = False

    def run(
        self, files: OwnedSnapshotFiles, request: ReservationRequest, *, deadline: float
    ) -> ParserManifest:
        self._require_identity()
        with self._lock:
            if self._attempted or self._running or self._retired:
                raise _unavailable()
            self._attempted = self._running = True
        try:
            if (
                type(files) is not OwnedSnapshotFiles
                or type(request) is not ReservationRequest
                or type(deadline) not in (int, float)
                or not math.isfinite(deadline)
            ):
                raise _unavailable()
            request.__post_init__()
            if not self._admission_attempted:
                self._admit(deadline)
            elif not self._admitted:
                raise _unavailable()
            else:
                self._deadline = min(self._deadline, deadline)
            self._remaining()
            self._borrow.require_source_usable()
            self._spawn(files, request)
            result = self._read_result()
            if self._child.wait(timeout=self._remaining()) != 0:
                raise _unavailable()
            self._verify(files, request, result)
            self._remaining()
            self._retire()
            self._remaining()
            return result
        except BaseException as error:
            try:
                self._retire()
            except BaseException:
                self._quarantine()
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        finally:
            with self._lock:
                self._running = False

    def close(self) -> None:
        self._require_identity()
        with self._lock:
            if self._retired:
                return
            if self._running:
                raise _unavailable()
            self._running = True
        try:
            self._retire()
        except BaseException as error:
            self._quarantine()
            if isinstance(error, Exception):
                raise _unavailable() from None
            raise
        finally:
            with self._lock:
                self._running = False
