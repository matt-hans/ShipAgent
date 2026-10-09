"""Exclusive local coordinator ownership for one dedicated target data root."""

from __future__ import annotations

import fcntl
import os
import stat
from pathlib import Path

from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
    sync_directory,
)


class CoordinatorLease:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        require_private_directory(self.path.parent)
        self._fd: int | None = os.open(
            path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            require_private_file(self.path)
        except BaseException:
            os.close(self._fd)
            self._fd = None
            raise
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self._fd)
            self._fd = None
            raise RuntimeError("Target store already has a coordinator.") from None

        try:
            sync_directory(self.path.parent)
        except BaseException:
            self.close()
            raise

    def is_owned(self) -> bool:
        if self._fd is None:
            return False
        try:
            require_private_directory(self.path.parent)
            require_private_file(self.path)
            held = os.fstat(self._fd)
            current = os.stat(self.path, follow_symlinks=False)
            return stat.S_ISREG(current.st_mode) and (held.st_dev, held.st_ino) == (
                current.st_dev,
                current.st_ino,
            )
        except OSError:
            return False

    def require_owned(self) -> None:
        if not self.is_owned():
            raise RuntimeError("Agent run coordinator is unavailable.")

    def close(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
