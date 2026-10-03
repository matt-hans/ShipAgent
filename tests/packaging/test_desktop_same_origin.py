"""Production desktop same-origin topology and packaging contracts."""

import json
import os
import re
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TAURI_ROOT = REPOSITORY_ROOT / "src-tauri"
LINKER_PATH = REPOSITORY_ROOT / "shipagent-frontend" / "scripts" / "link-remotes.sh"
REMOTE_NAMES = (
    "chat-remote",
    "sidebar-remote",
    "settings-remote",
    "domain-remote",
)


def _create_frontend_root(tmp_path: Path) -> Path:
    frontend_root = tmp_path / "frontend"
    shell_dist = frontend_root / "dist" / "apps" / "shell" / "browser"
    shell_dist.mkdir(parents=True)
    (shell_dist / "index.html").write_text("<app-root></app-root>")
    return frontend_root


def _remote_dist(frontend_root: Path, remote_name: str) -> Path:
    return frontend_root / "dist" / "apps" / remote_name / "browser"


def _write_valid_remote(
    frontend_root: Path,
    remote_name: str,
    *,
    include_chunk: bool = True,
) -> dict:
    remote_dist = _remote_dist(frontend_root, remote_name)
    remote_dist.mkdir(parents=True, exist_ok=True)
    chunk_name = f"{remote_name}.js"
    manifest = {
        "name": remote_name,
        "exposes": [{"key": "./Remote", "outFileName": chunk_name}],
        "shared": [],
    }
    (remote_dist / "remoteEntry.json").write_text(json.dumps(manifest))
    if include_chunk:
        (remote_dist / chunk_name).write_text("export const remote = true;")
    return manifest


def _run_linker(frontend_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(LINKER_PATH)],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "SHIPAGENT_FRONTEND_ROOT": str(frontend_root)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_tauri_bootstrap_can_reach_sidecar_without_remote_ipc_privilege():
    config = json.loads((TAURI_ROOT / "tauri.conf.json").read_text())
    capability = json.loads((TAURI_ROOT / "capabilities" / "default.json").read_text())

    assert config["app"]["withGlobalTauri"] is True
    assert "http://127.0.0.1:*" in config["app"]["security"]["csp"]
    assert capability["local"] is True
    assert "remote" not in capability

    rust_main = (TAURI_ROOT / "src" / "main.rs").read_text()
    assert "#[tauri::command]" in rust_main
    assert "tauri::generate_handler![start_sidecar]" in rust_main


def test_backend_bundler_links_remotes_before_pyinstaller():
    bundler = (REPOSITORY_ROOT / "scripts" / "bundle_backend.sh").read_text()

    remote_link = bundler.index("./scripts/link-remotes.sh")
    pyinstaller = bundler.index("-m PyInstaller")

    assert remote_link < pyinstaller


def test_remote_linker_stages_a_self_contained_production_shell(tmp_path):
    linker = LINKER_PATH.read_text()
    assert "SHIPAGENT_FRONTEND_ROOT" in linker

    frontend_root = _create_frontend_root(tmp_path)
    shell_dist = frontend_root / "dist" / "apps" / "shell" / "browser"

    manifests = {
        remote_name: _write_valid_remote(frontend_root, remote_name)
        for remote_name in REMOTE_NAMES
    }

    result = _run_linker(frontend_root)

    assert result.returncode == 0, result.stderr
    for remote_name in REMOTE_NAMES:
        staged_remote = shell_dist / remote_name
        assert staged_remote.is_dir()
        assert not staged_remote.is_symlink()
        assert (
            json.loads((staged_remote / "remoteEntry.json").read_text())
            == manifests[remote_name]
        )
        assert (staged_remote / f"{remote_name}.js").is_file()


def test_pyinstaller_collects_the_self_contained_shell_at_the_runtime_path():
    spec = (REPOSITORY_ROOT / "shipagent-core.spec").read_text()

    assert re.search(
        r"'dist'\s*/\s*'apps'\s*/\s*'shell'\s*/\s*'browser'",
        spec,
    )
    assert "'shipagent-frontend/dist/apps/shell/browser'" in spec


def test_pyinstaller_spec_does_not_exclude_setuptools_vendored_distutils():
    """Python 3.12 builds alias setuptools' distutils; excluding it aborts analysis."""
    spec = (REPOSITORY_ROOT / "shipagent-core.spec").read_text()
    excludes = re.search(r"excludes=\[(.*?)\]", spec, re.DOTALL)

    assert excludes is not None
    assert "'distutils'" not in excludes.group(1)


def test_pyinstaller_spec_collects_the_app_module_uvicorn_imports_by_string():
    """bundle_entry serves "src.api.main:app" by string, so analysis cannot see it."""
    spec = (REPOSITORY_ROOT / "shipagent-core.spec").read_text()
    hidden_imports = re.search(
        r"hiddenimports=.*?\[(.*?)\],\s*hookspath", spec, re.DOTALL
    )

    assert hidden_imports is not None
    assert "'src.api.main'" in hidden_imports.group(1)


def test_pyinstaller_spec_bundles_metadata_read_at_import_time():
    """fastmcp reads its own metadata on import; /health reports shipagent's."""
    spec = (REPOSITORY_ROOT / "shipagent-core.spec").read_text()
    packages = re.search(r"METADATA_PACKAGES = \[(.*?)\]", spec, re.DOTALL)

    assert packages is not None
    assert "'fastmcp'" in packages.group(1)
    assert "'shipagent'" in packages.group(1)
    assert "+ package_metadata" in spec


def test_remote_linker_fails_when_a_required_remote_is_missing(tmp_path):
    frontend_root = _create_frontend_root(tmp_path)

    for remote_name in ("chat-remote", "sidebar-remote", "settings-remote"):
        _write_valid_remote(frontend_root, remote_name)

    result = _run_linker(frontend_root)

    assert result.returncode != 0
    assert "domain-remote dist not found" in result.stdout


def test_remote_linker_fails_when_a_remote_output_directory_is_empty(tmp_path):
    frontend_root = _create_frontend_root(tmp_path)

    for remote_name in REMOTE_NAMES:
        remote_dist = _remote_dist(frontend_root, remote_name)
        remote_dist.mkdir(parents=True)
        if remote_name != "chat-remote":
            _write_valid_remote(frontend_root, remote_name)

    result = _run_linker(frontend_root)

    assert result.returncode != 0
    assert "chat-remote remoteEntry.json not found" in result.stdout


def test_remote_linker_fails_when_a_remote_entry_is_malformed_json(tmp_path):
    frontend_root = _create_frontend_root(tmp_path)

    for remote_name in REMOTE_NAMES:
        _write_valid_remote(frontend_root, remote_name)
    (_remote_dist(frontend_root, "chat-remote") / "remoteEntry.json").write_text(
        "<!doctype html><title>SPA fallback</title>"
    )

    result = _run_linker(frontend_root)

    assert result.returncode != 0
    assert "chat-remote remoteEntry.json is not valid JSON" in result.stderr


def test_remote_linker_fails_when_remote_entry_has_no_exposed_chunk(tmp_path):
    frontend_root = _create_frontend_root(tmp_path)

    for remote_name in REMOTE_NAMES:
        _write_valid_remote(frontend_root, remote_name)
    (_remote_dist(frontend_root, "chat-remote") / "remoteEntry.json").write_text(
        json.dumps({"name": "chat-remote"})
    )

    result = _run_linker(frontend_root)

    assert result.returncode != 0
    assert (
        "chat-remote remoteEntry.json must expose at least one chunk" in result.stderr
    )


def test_remote_linker_fails_when_remote_entry_references_a_missing_chunk(tmp_path):
    frontend_root = _create_frontend_root(tmp_path)

    for remote_name in REMOTE_NAMES:
        _write_valid_remote(
            frontend_root,
            remote_name,
            include_chunk=remote_name != "chat-remote",
        )

    result = _run_linker(frontend_root)

    assert result.returncode != 0
    assert "chat-remote remoteEntry.json referenced chunk is missing" in result.stderr


def test_remote_linker_fails_when_remote_entry_is_missing_from_nonempty_output(
    tmp_path,
):
    frontend_root = _create_frontend_root(tmp_path)
    for remote_name in REMOTE_NAMES:
        _write_valid_remote(frontend_root, remote_name)
    chat_dist = _remote_dist(frontend_root, "chat-remote")
    (chat_dist / "remoteEntry.json").unlink()

    result = _run_linker(frontend_root)

    assert result.returncode != 0
    assert "chat-remote remoteEntry.json not found" in result.stdout


def test_pyinstaller_spec_bundles_frozen_dynamic_imports():
    spec = (REPOSITORY_ROOT / "shipagent-core.spec").read_text()

    # rich imports rich._unicode_data.unicodeNN-N-N via importlib; without them
    # every bundled stdio MCP child dies in the fastmcp banner.
    assert "collect_submodules('rich._unicode_data')" in spec
    assert "hiddenimports=rich_unicode_data + lupa_runtime + [" in spec
    # fastmcp -> docket -> fakeredis: lua runtime by name + commands.json on disk.
    assert "lupa_runtime = ['lupa.lua51']" in spec
    assert "collect_data_files('fakeredis', include_py_files=True)" in spec
    # The Excel adapter imports python_calamine, not "calamine".
    assert "'python_calamine'" in spec
    assert "'calamine'" not in spec


def test_tauri_kills_owned_sidecar_on_exit_and_sigterm():
    rust_main = (TAURI_ROOT / "src" / "main.rs").read_text()

    assert "RunEvent::Exit" in rust_main
    assert ".build(context)" in rust_main
    # Kills the retained child handle, never a process found by name.
    assert "guard.take()" in rust_main and "child.kill()" in rust_main
    assert "pkill" not in rust_main and "killall" not in rust_main
    assert "SignalKind::terminate()" in rust_main
    assert '"signal"' in (TAURI_ROOT / "Cargo.toml").read_text()
    assert "auto-kills on parent crash" not in rust_main


def test_bundle_smoke_requires_data_source_status_and_excel_import():
    bundler = (REPOSITORY_ROOT / "scripts" / "bundle_backend.sh").read_text()

    assert "/api/v1/data-sources/status" in bundler
    assert '"$STATUS_CODE" = "200"' in bundler
    assert "/api/v1/data-sources/import" in bundler
    assert '"row_count": *2[^0-9]' in bundler
    # Hermetic: synthetic workbook in the throwaway data dir.
    assert "$SMOKE_DATA_DIR/smoke.xlsx" in bundler
