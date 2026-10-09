"""Exclusive local coordinator ownership for one dedicated target data root."""

from __future__ import annotations

import fcntl
import os
import stat
import threading
from pathlib import Path
from weakref import WeakSet

from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
    sync_directory,
)


class CoordinatorLease:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._pid = os.getpid()
        self._state_lock = threading.Lock()
        self._closing = False
        self._source_quarantined = False
        self._borrows: set[CoordinatorBorrow] = set()
        self._registered_borrows: WeakSet[CoordinatorBorrow] = WeakSet()
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
        # Never acquire a mutex copied from another process: its owner may no
        # longer exist there, and flock's inherited descriptor is not a lease.
        if os.getpid() != self._pid:
            return False
        with self._state_lock:
            return self._is_owned_locked()

    def _is_owned_locked(self) -> bool:
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

    def _require_process(self) -> None:
        if os.getpid() != self._pid:
            raise RuntimeError("Agent run coordinator is unavailable.")

    def begin_close(self) -> None:
        """Stop borrow admission while retaining physical cleanup ownership."""
        self._require_process()
        with self._state_lock:
            self._closing = True

    def borrow(self) -> CoordinatorBorrow:
        """Pin this exact lease until an admitted operation actually retires."""
        self._require_process()
        with self._state_lock:
            if self._closing or self._source_quarantined or not self._is_owned_locked():
                raise RuntimeError("Agent run coordinator is unavailable.")
            token = CoordinatorBorrow(self)
            self._borrows.add(token)
            try:
                self._registered_borrows.add(token)
            except BaseException:
                # Failed admission must never create completed-retirement proof.
                # Remove its weak identity before dropping active membership.
                self._registered_borrows.discard(token)
                self._borrows.discard(token)
                raise
            return token

    def close(self) -> None:
        """Mark closing immediately; a live borrow requires a later close."""
        self._require_process()
        with self._state_lock:
            self._closing = True
            if self._borrows:
                raise RuntimeError("Agent run coordinator is unavailable.")
            if self._fd is not None:
                fd, self._fd = self._fd, None
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)


class CoordinatorBorrow:
    """A process-local lifetime pin; retirement never unlocks its owner."""

    def __init__(self, lease: CoordinatorLease) -> None:
        self._lease = lease

    @property
    def coordinator_path(self) -> Path:
        """Describe the owner path; this alone is not proof of ownership."""
        return self._lease.path

    @property
    def retirement_completed(self) -> bool:
        """Positive cleanup evidence for this exact admitted token, not authority."""
        self._lease._require_process()
        with self._lease._state_lock:
            return (
                self in self._lease._registered_borrows
                and self not in self._lease._borrows
            )

    def _require_owned_locked(self) -> None:
        if self not in self._lease._borrows or not self._lease._is_owned_locked():
            raise RuntimeError("Agent run coordinator is unavailable.")

    def require_owned(self) -> None:
        self._lease._require_process()
        with self._lease._state_lock:
            self._require_owned_locked()

    def require_source_usable(self) -> None:
        self._lease._require_process()
        with self._lease._state_lock:
            self._require_owned_locked()
            if self._lease._source_quarantined:
                raise RuntimeError("Agent run coordinator is unavailable.")

    def quarantine(self) -> None:
        """Fence every source operation sharing this lease until owner restart."""
        self._lease._require_process()
        with self._lease._state_lock:
            # An ownership-check outage may be precisely why cleanup is
            # uncertain. An admitted token must still be able to deny new use.
            if self not in self._lease._borrows:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._lease._source_quarantined = True

    def retire(self) -> None:
        """Call only after every resource retained by this operation retires."""
        self._lease._require_process()
        with self._lease._state_lock:
            # The original admitted identity remains weakly registered. This
            # single mutation leaves either an active token or positive proof
            # that it completed retirement, without retaining tombstones.
            self._lease._borrows.discard(self)
