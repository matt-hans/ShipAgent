"""Production desktop same-origin topology and packaging contracts."""

import json
import os
import re
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TAURI_ROOT = REPOSITORY_ROOT / "src-tauri"


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
    linker_path = REPOSITORY_ROOT / "shipagent-frontend" / "scripts" / "link-remotes.sh"
    linker = linker_path.read_text()
    assert "SHIPAGENT_FRONTEND_ROOT" in linker

    frontend_root = tmp_path / "frontend"
    shell_dist = frontend_root / "dist" / "apps" / "shell" / "browser"
    shell_dist.mkdir(parents=True)
    (shell_dist / "index.html").write_text("<app-root></app-root>")

    remote_names = (
        "chat-remote",
        "sidebar-remote",
        "settings-remote",
        "domain-remote",
    )
    for remote_name in remote_names:
        remote_dist = frontend_root / "dist" / "apps" / remote_name / "browser"
        remote_dist.mkdir(parents=True)
        (remote_dist / "remoteEntry.json").write_text(json.dumps({"name": remote_name}))

    result = subprocess.run(
        ["sh", str(linker_path)],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "SHIPAGENT_FRONTEND_ROOT": str(frontend_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for remote_name in remote_names:
        staged_remote = shell_dist / remote_name
        assert staged_remote.is_dir()
        assert not staged_remote.is_symlink()
        assert json.loads((staged_remote / "remoteEntry.json").read_text()) == {
            "name": remote_name
        }


def test_pyinstaller_collects_the_self_contained_shell_at_the_runtime_path():
    spec = (REPOSITORY_ROOT / "shipagent-core.spec").read_text()

    assert re.search(
        r"'dist'\s*/\s*'apps'\s*/\s*'shell'\s*/\s*'browser'",
        spec,
    )
    assert "'shipagent-frontend/dist/apps/shell/browser'" in spec


def test_remote_linker_fails_when_a_required_remote_is_missing(tmp_path):
    linker_path = REPOSITORY_ROOT / "shipagent-frontend" / "scripts" / "link-remotes.sh"
    frontend_root = tmp_path / "frontend"
    (frontend_root / "dist" / "apps" / "shell" / "browser").mkdir(parents=True)

    for remote_name in ("chat-remote", "sidebar-remote", "settings-remote"):
        (frontend_root / "dist" / "apps" / remote_name / "browser").mkdir(parents=True)

    result = subprocess.run(
        ["sh", str(linker_path)],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "SHIPAGENT_FRONTEND_ROOT": str(frontend_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "domain-remote dist not found" in result.stdout
