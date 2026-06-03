import shutil
import subprocess
import sys
from pathlib import Path

ARTIFACT_DIR = Path("generated/provider_artifacts")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def _remove_artifact_dir() -> None:
    if ARTIFACT_DIR.exists():
        shutil.rmtree(ARTIFACT_DIR)


def _restore_artifact_dir(backup_dir: Path, existed: bool) -> None:
    _remove_artifact_dir()
    if existed:
        shutil.copytree(backup_dir, ARTIFACT_DIR)


def _assert_artifact_status_clean() -> None:
    status = _run(["git", "status", "--porcelain", "--", str(ARTIFACT_DIR)])
    assert status.returncode == 0, status.stderr
    assert status.stdout == "", status.stdout


def test_provider_artifacts_are_current(tmp_path: Path):
    backup_dir = tmp_path / "provider_artifacts"
    artifact_dir_existed = ARTIFACT_DIR.exists()
    if artifact_dir_existed:
        shutil.copytree(ARTIFACT_DIR, backup_dir)

    try:
        _assert_artifact_status_clean()
        _remove_artifact_dir()

        result = _run([sys.executable, "scripts/generate_provider_artifacts.py"])
        assert result.returncode == 0, result.stderr

        diff = _run(["git", "diff", "--", str(ARTIFACT_DIR)])
        assert diff.returncode == 0, diff.stderr
        assert diff.stdout == "", diff.stdout

        _assert_artifact_status_clean()
    finally:
        _restore_artifact_dir(backup_dir, artifact_dir_existed)
