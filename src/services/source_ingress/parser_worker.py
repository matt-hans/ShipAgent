"""Fixed isolated stdlib worker. It never publishes a manifest or releases a lease."""

import os
import resource
import signal
import sys
import time


def main() -> None:
    # No application import or request-selected module/path precedes these limits.
    if len(sys.argv) != 7 or any(len(value) > 128 for value in sys.argv[1:]):
        raise SystemExit(2)
    raw_fd, normalized_fd, pin_fd, raw_length = (int(value) for value in sys.argv[1:5])
    raw_digest = sys.argv[5]
    deadline = float(sys.argv[6])
    remaining = deadline - time.monotonic()
    if (
        not 0 < remaining <= 5
        or len({raw_fd, normalized_fd, pin_fd}) != 3
        or min(raw_fd, normalized_fd, pin_fd) < 3
    ):
        raise SystemExit(2)
    resource.setrlimit(resource.RLIMIT_AS, (64 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    remaining = deadline - time.monotonic()
    if not 0 < remaining <= 5:
        raise SystemExit(2)
    signal.setitimer(signal.ITIMER_REAL, remaining)

    import hashlib
    import json
    import stat
    import types
    from pathlib import Path

    # Normal src.services initialization imports the application/SDK layer.
    # These child-local namespace shells have only fixed installed source paths.
    here = Path(__file__).resolve().parent
    for name, path in (
        ("src", here.parent.parent),
        ("src.services", here.parent),
        ("src.services.source_ingress", here),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    from src.services.source_ingress.csv_snapshot import (
        MAX_RAW_BYTES,
        CsvSnapshotError,
        parse_csv_snapshot,
    )
    from src.services.source_ingress.snapshot_codec import encode_snapshot

    if not 0 < raw_length <= MAX_RAW_BYTES or len(raw_digest) != 64:
        raise SystemExit(2)
    for fd in (raw_fd, normalized_fd, pin_fd):
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SystemExit(2)
    if os.fstat(raw_fd).st_size != raw_length or os.fstat(normalized_fd).st_size != 0:
        raise SystemExit(2)
    raw = os.pread(raw_fd, raw_length + 1, 0)
    try:
        snapshot = parse_csv_snapshot(
            raw,
            content_length=raw_length,
            content_sha256=raw_digest,
            media_type="text/csv",
        )
        normalized = encode_snapshot(snapshot)
    except CsvSnapshotError as error:
        result = {"status": "rejected", "code": error.code}
    else:
        view = memoryview(normalized)
        offset = 0
        while offset < len(view):
            written = os.pwrite(normalized_fd, view[offset:], offset)
            if written <= 0:
                raise SystemExit(2)
            offset += written
        result = {
            "status": "ok",
            "parser_profile": "synthetic_csv_v1",
            "raw_length": raw_length,
            "normalized_length": len(normalized),
            "raw_content_sha256": snapshot.raw_content_sha256,
            "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
            "row_count": snapshot.row_count,
            "column_count": snapshot.column_count,
        }
    encoded = json.dumps(result, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > 1024:
        raise SystemExit(2)
    frame = len(encoded).to_bytes(4, "big") + encoded
    if os.write(1, frame) != len(frame):
        raise SystemExit(2)
    # The actual inherited flock description stays open until process exit.


if __name__ == "__main__":
    main()
