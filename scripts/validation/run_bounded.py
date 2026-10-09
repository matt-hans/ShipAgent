#!/usr/bin/env python3
"""Run cooperative Linux validation with bounded resources and owned cleanup.

Promotes the recovered validation prototype into reproducible repository code.
This is not a hostile-code sandbox. See docs/acceptance/mcp-clients.md.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import resource
import shutil
import signal
import site
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

LIMITATIONS = (
    "sampled RSS can miss short peaks; CPU affinity bounds parallelism, not a cgroup quota; "
    "not a kernel network sandbox; native clients, Python -I/-S, or a stripped child environment "
    "using a different interpreter can omit the Python guard; alternate absolute interpreters and "
    "console-script shebangs are not rewritten; supervisor SIGKILL/uninterruptible children may defeat cleanup"
)


def processes():
    result = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            stat = path.read_text().rsplit(")", 1)[1].split()
            result[int(path.parent.name)] = (
                int(stat[1]),
                stat[0],
                int(stat[21]) * os.sysconf("SC_PAGE_SIZE"),
            )
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return result


def descendants():
    snapshot = processes()
    owned = {os.getpid()}
    while True:
        added = {pid for pid, (ppid, _, _) in snapshot.items() if ppid in owned} - owned
        if not added:
            break
        owned |= added
    owned.remove(os.getpid())
    return {pid: snapshot[pid] for pid in owned}


def reap(child):
    child.poll()
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            return
        if pid == child.pid:
            child.returncode = os.waitstatus_to_exitcode(status)


def cleanup(child):
    reap(child)
    forced = bool(descendants())
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in descendants():
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        until = time.monotonic() + 2
        while time.monotonic() < until:
            reap(child)
            if not descendants():
                break
            time.sleep(0.05)
        if not descendants():
            break
    return forced, sorted(descendants())


def source_receipt(cwd, *, excluded=()):
    # An ancestor exclusion would erase the entire source manifest. Only
    # dedicated output descendants may be excluded, never cwd or its parents.
    excluded = tuple(
        path for path in excluded if path != cwd and path.is_relative_to(cwd)
    )

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(cwd), *args],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stderr=subprocess.DEVNULL,
            timeout=10,
        )

    paths = sorted(
        set(git("ls-files", "-c", "-o", "--exclude-standard", "-z").split(b"\0"))
        - {b""}
    )
    paths = [
        name
        for name in paths
        if not any(
            (cwd / os.fsdecode(name)) == excluded_path
            or (cwd / os.fsdecode(name)).is_relative_to(excluded_path)
            for excluded_path in excluded
        )
    ]
    manifest = hashlib.sha256()
    for name in paths:
        path = cwd / os.fsdecode(name)
        # Hash link text rather than following a link out of the worktree.
        if path.is_symlink():
            data = os.fsencode(os.readlink(path))
        elif path.is_file():
            data = path.read_bytes()
        else:
            data = b"<missing-or-directory>"
        manifest.update(name + b"\0" + hashlib.sha256(data).digest())
    return {
        "head": git("rev-parse", "HEAD").decode().strip(),
        "worktree_changes": git(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            *(
                f":(exclude){path.relative_to(cwd)}"
                for path in excluded
                if path.is_relative_to(cwd)
            ),
        )
        .decode()
        .splitlines(),
        "file_count": len(paths),
        "file_manifest_sha256": manifest.hexdigest(),
        "config_sha256": {
            name: hashlib.sha256((cwd / name).read_bytes()).hexdigest()
            for name in (
                "pyproject.toml",
                "uv.lock",
                "scripts/control_plane_test_packages.json",
            )
            if (cwd / name).is_file()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--rss-mib", type=int, default=768)
    parser.add_argument("--service-root", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", args.name):
        parser.error("name must be a short filename-safe identifier")
    if not 0 < args.seconds <= 3600 or not 1 <= args.rss_mib <= 1536:
        parser.error("positive limits required: at most 3600 seconds and 1536 MiB")
    if args.command[:1] == ["--"]:
        args.command.pop(0)
    if not args.command:
        parser.error("a validation command is required")
    if sys.platform != "linux" or not hasattr(os, "sched_getaffinity"):
        parser.error(
            "this runner requires Linux /proc, affinity and child-subreaper support"
        )
    cwd, output = args.cwd.resolve(), args.output_dir.resolve()
    if cwd.is_relative_to(output):
        parser.error("output must not be the checkout root or its ancestor")
    if output.is_relative_to(cwd):
        tracked_output = subprocess.check_output(
            [
                "git",
                "-C",
                str(cwd),
                "ls-files",
                "-z",
                "--",
                str(output.relative_to(cwd)),
            ],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if tracked_output:
            parser.error("output must not contain tracked source files")
    service_binaries = {}
    if args.service_root is not None:
        args.service_root = args.service_root.resolve()
        for name in (
            "usr/lib/postgresql/17/bin/postgres",
            "usr/lib/postgresql/17/bin/initdb",
            "usr/bin/redis-server",
        ):
            binary = args.service_root / name
            if not binary.is_file():
                parser.error(
                    "missing task-local test binaries; run scripts/setup_control_plane_test_services.py first"
                )
            service_binaries[name] = hashlib.sha256(binary.read_bytes()).hexdigest()
    os.umask(0o077)
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Never overwrite a previous receipt or log, including a symlink.
    receipt_path, log_path = output / f"{args.name}.json", output / f"{args.name}.log"
    if receipt_path.exists() or log_path.exists():
        parser.error(
            "receipt/log already exists; choose a new output directory or name"
        )
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cpus = sorted(os.sched_getaffinity(0))[:2]
        os.sched_setaffinity(0, cpus)
        if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
            raise RuntimeError("failed to configure Linux child subreaper")
        # The lock file is only flocked, never written; keep it in the manifest
        # when it is inside the checkout rather than hiding a selected source.
        source_excluded = (output,)
        source = source_receipt(cwd, excluded=source_excluded)
        runtime = Path(tempfile.mkdtemp(prefix=f"{args.name}-runtime-", dir=output))
        home, startup, temporary = (
            runtime / "home",
            runtime / "startup",
            runtime / "tmp",
        )
        for directory in (home, startup, temporary):
            directory.mkdir(mode=0o700)
        guard = Path(__file__).with_name("shipagent_offline_guard.py")
        shutil.copyfile(guard, startup / guard.name)
        observations = runtime / "guard-observations"
        observations.mkdir(mode=0o700)
        (startup / "sitecustomize.py").write_text(
            "import hashlib, json, os\n"
            "from pathlib import Path\n"
            "import shipagent_offline_guard\n"
            "guard_path = Path(shipagent_offline_guard.__file__).resolve()\n"
            f"observation = Path({str(observations)!r}) / (str(os.getpid()) + '.json')\n"
            "observation.write_text(json.dumps({'pid': os.getpid(), 'file': str(guard_path), 'sha256': hashlib.sha256(guard_path.read_bytes()).hexdigest()}))\n"
        )
        # A disposable interpreter hook also protects env={} descendants. Reuse
        # prepared dependency directories without executing their .pth hooks,
        # installing packages, or modifying the caller's virtual environment.
        dependency_sites = sorted(
            {
                str(Path(path).resolve())
                for path in [*site.getsitepackages(), *sys.path]
                if path and Path(path).name == "site-packages" and Path(path).is_dir()
            }
        )
        overlay = runtime / "venv"
        venv.EnvBuilder(with_pip=False, symlinks=True).create(overlay)
        overlay_site = (
            overlay
            / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        )
        hook = overlay_site / "shipagent_validation_guard.pth"
        hook.write_text(
            "\n".join(
                [*dependency_sites, str(startup), "import shipagent_offline_guard", ""]
            )
        )
        qualified_python = overlay / "bin/python"
        command = list(args.command)
        mapped_python = Path(command[0]).absolute() == Path(sys.executable).absolute()
        if mapped_python:
            command[0] = str(qualified_python)
        env = {
            "PATH": str(qualified_python.parent) + ":/usr/bin:/bin",
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "LANG": "C.UTF-8",
            "PYTHONPATH": os.pathsep.join(
                (str(startup), str(Path(__file__).parent), str(cwd))
            ),
            "PYTHONNOUSERSITE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        if args.service_root is not None:
            env["SHIPAGENT_TEST_SERVICE_ROOT"] = str(args.service_root)
        environment = {
            "dependency_python_executable": sys.executable,
            "python_executable": str(qualified_python),
            "python_version": sys.version.split()[0],
            "dependency_site_packages": dependency_sites,
            "qualified_startup_hook_sha256": hashlib.sha256(
                hook.read_bytes()
            ).hexdigest(),
            "packages": dict(
                sorted(
                    (dist.metadata["Name"], dist.version)
                    for dist in importlib.metadata.distributions()
                    if dist.metadata["Name"]
                )
            ),
            "allowed_names": sorted(env),
            "guard_sha256": hashlib.sha256(guard.read_bytes()).hexdigest(),
            "test_service_binaries_sha256": service_binaries,
            "python_startup_hooks_sha256": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for root in site.getsitepackages()
                for path in sorted(Path(root).glob("*.pth"))
            },
        }
        received_signal = []

        def on_signal(signum, _frame):
            received_signal.append(signum)

        previous = {
            sig: signal.signal(sig, on_signal)
            for sig in (signal.SIGINT, signal.SIGTERM)
        }
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started, peak, reason, child = time.monotonic(), 0, None, None
        forced, survivors, launch_error = False, [], None
        loaded_guards = []
        try:
            with log_path.open("x") as log:
                try:
                    child = subprocess.Popen(
                        command,
                        cwd=cwd,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    while child.poll() is None:
                        rss = sum(row[2] for row in descendants().values())
                        peak = max(peak, rss)
                        if rss > args.rss_mib * 1024**2:
                            reason = "aggregate_rss_limit"
                            break
                        if time.monotonic() - started > args.seconds:
                            reason = "wall_time_limit"
                            break
                        if received_signal:
                            reason = "supervisor_interrupted"
                            break
                        time.sleep(0.05)
                except OSError as error:
                    # No environment, command content or potentially secret exception text.
                    launch_error = type(error).__name__
                finally:
                    if child is not None:
                        forced, survivors = cleanup(child)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            loaded_guards = [
                json.loads(path.read_text())
                for path in sorted(observations.glob("*.json"))
            ]
            if not survivors:
                shutil.rmtree(runtime)
        source_after = source_receipt(cwd, excluded=source_excluded)
        source_changed = source_after != source
        root_guard_missing = (
            mapped_python
            and child is not None
            and not any(item["pid"] == child.pid for item in loaded_guards)
        )
        guard_mismatch = root_guard_missing or any(
            item["sha256"] != environment["guard_sha256"] for item in loaded_guards
        )
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "name": args.name,
            "cwd": str(cwd),
            "source": source,
            "source_after": source_after,
            "source_changed_during_run": source_changed,
            "command_executable": command[0],
            "python_command_mapped_to_overlay": mapped_python,
            "command_sha256": hashlib.sha256(
                json.dumps(args.command).encode()
            ).hexdigest(),
            "environment": environment,
            "loaded_python_guards": loaded_guards,
            "loaded_guard_mismatch": guard_mismatch,
            "wall_seconds": round(time.monotonic() - started, 3),
            "reaped_child_cpu_seconds": round(
                usage.ru_utime
                + usage.ru_stime
                - usage_before.ru_utime
                - usage_before.ru_stime,
                3,
            ),
            "peak_sampled_rss_mib": round(peak / 1024**2, 3),
            "sample_interval_seconds": 0.05,
            "limit_rss_mib": args.rss_mib,
            "limit_seconds": args.seconds,
            "cpu_affinity": cpus,
            "root_exit": child.returncode if child else None,
            "launch_error": launch_error,
            "limit_failure": reason,
            "forced_cleanup": forced,
            "survivors": survivors,
            "runtime_directory_removed": not runtime.exists(),
            "limitations": LIMITATIONS,
        }
        with receipt_path.open("x") as receipt_file:
            receipt_file.write(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "receipt": str(receipt_path),
                    "root_exit": result["root_exit"],
                    "limit_failure": reason,
                    "forced_cleanup": forced,
                    "survivors": survivors,
                }
            ),
            flush=True,
        )
        return (
            1
            if reason
            or survivors
            or forced
            or launch_error
            or source_changed
            or guard_mismatch
            else child.returncode
        )


if __name__ == "__main__":
    raise SystemExit(main())
