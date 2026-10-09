"""Fail-closed Linux file checks for a pre-provisioned private target directory.

These checks do not provision encryption or defend against an operator with the
same OS identity replacing files concurrently. That trust boundary is explicit.
"""

import os
import stat
from pathlib import Path


def require_private_directory(path: Path) -> None:
    info = path.stat(follow_symlinks=False)
    if (
        path.absolute() != path.resolve()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PermissionError("Target storage directory must be private and owned.")


def require_private_file(
    path: Path, *, identity: tuple[int, int] | None = None
) -> tuple[int, int]:
    info = path.stat(follow_symlinks=False)
    current = (info.st_dev, info.st_ino)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or (identity is not None and identity != current)
    ):
        raise PermissionError("Target storage file must be private and owned.")
    return current


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
