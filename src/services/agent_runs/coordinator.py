"""Exclusive local coordinator ownership for one dedicated target data root."""

from __future__ import annotations

import fcntl
import io
import os
import stat
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from weakref import WeakSet, ref

from src.services.agent_runs.private_storage import (
    require_private_directory,
    require_private_file,
    sync_directory,
)


class SourceWorkKind(Enum):
    """Closed trusted work classes; never derived from model/request input."""

    RECEIVER = "receiver"
    PARSER = "parser"
    PRIVATE_READ = "private_read"


_SOURCE_WORK_LIMITS = {
    SourceWorkKind.RECEIVER: 2,
    SourceWorkKind.PARSER: 1,
    SourceWorkKind.PRIVATE_READ: 1,
}


@dataclass(frozen=True, slots=True, repr=False)
class SourceStorageBinding:
    """Verified immutable storage pins, never operator or conversation authority."""

    account_id: str
    execution_target_id: str
    store_path: Path
    store_identity: tuple[int, int]
    generation: int
    root_path: Path
    root_identity: tuple[int, int]

    def __post_init__(self) -> None:
        def denied():
            return RuntimeError("Agent run coordinator is unavailable.")

        for value in (self.account_id, self.execution_target_id):
            if type(value) is not str or not value or "\0" in value:
                raise denied()
            try:
                size = len(value.encode("utf-8"))
            except UnicodeError:
                raise denied() from None
            if size > 256:
                raise denied()
        for path in (self.store_path, self.root_path):
            if (
                type(path) is not type(Path())
                or not path.is_absolute()
                or ".." in path.parts
            ):
                raise denied()
            try:
                encoded = str(path).encode("utf-8")
            except UnicodeError:
                raise denied() from None
            if b"\0" in encoded or len(encoded) > 4096:
                raise denied()
        if type(self.generation) is not int or not 1 <= self.generation < 2**63:
            raise denied()
        for identity in (self.store_identity, self.root_identity):
            if (
                type(identity) is not tuple
                or len(identity) != 2
                or any(
                    type(item) is not int or not 0 <= item < 2**63 for item in identity
                )
            ):
                raise denied()


class CoordinatorLease:
    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._pid = os.getpid()
        self._state_lock = threading.Lock()
        self._closing = False
        self._source_quarantined = False
        self._source_tagged_ever = False
        self._source_startup: CoordinatorSourceStartup | None = None
        self._source_binding: SourceStorageBinding | None = None
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

    def source_storage_binding(self) -> SourceStorageBinding:
        """Read the exact ready storage facts without SQL or provider work."""
        self._require_process()
        with self._state_lock:
            if (
                self._closing
                or self._source_quarantined
                or not self._is_owned_locked()
                or self._source_startup is None
                or self._source_startup._state != "ready"
                or self._source_binding is None
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            return self._source_binding

    def borrow(
        self,
        *,
        source_work: SourceWorkKind | None = None,
        source_binding: SourceStorageBinding | None = None,
    ) -> CoordinatorBorrow:
        """Pin this exact lease until an admitted operation actually retires."""
        self._require_process()
        if source_work is not None and type(source_work) is not SourceWorkKind:
            raise RuntimeError("Agent run coordinator is unavailable.")
        if source_binding is not None:
            if type(source_binding) is not SourceStorageBinding or source_work is None:
                raise RuntimeError("Agent run coordinator is unavailable.")
            source_binding.__post_init__()
        with self._state_lock:
            if self._closing or self._source_quarantined or not self._is_owned_locked():
                raise RuntimeError("Agent run coordinator is unavailable.")
            if source_work is not None:
                if self._source_startup is None:
                    if source_binding is not None:
                        raise RuntimeError("Agent run coordinator is unavailable.")
                elif (
                    self._source_startup._state != "ready"
                    or source_binding is None
                    or source_binding != self._source_binding
                ):
                    raise RuntimeError("Agent run coordinator is unavailable.")
            if (
                source_work is not None
                and sum(token._source_work is source_work for token in self._borrows)
                >= _SOURCE_WORK_LIMITS[source_work]
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            token = CoordinatorBorrow(self, source_work=source_work)
            self._borrows.add(token)
            try:
                self._registered_borrows.add(token)
            except BaseException:
                # Failed admission must never create completed-retirement proof.
                # Remove its weak identity before dropping active membership.
                self._registered_borrows.discard(token)
                self._borrows.discard(token)
                raise
            if source_work is not None:
                self._source_tagged_ever = True
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

    def __init__(
        self, lease: CoordinatorLease, *, source_work: SourceWorkKind | None = None
    ) -> None:
        self._lease = lease
        self._source_work = source_work
        self._process_pin: CoordinatorProcessPin | None = None
        self._startup_registration: CoordinatorSourceStartup | None = None

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

    def allocate_source_startup(self, *, owner: object) -> CoordinatorSourceStartup:
        """Capture the inert private registration before any startup effects."""
        self._lease._require_process()
        try:
            ref(owner)
        except TypeError:
            raise RuntimeError("Agent run coordinator is unavailable.") from None
        with self._lease._state_lock:
            self._require_owned_locked()
            if (
                self._source_work is not None
                or self._startup_registration is not None
                or self._lease._closing
                or self._lease._source_quarantined
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._startup_registration = CoordinatorSourceStartup(self, owner)
            return self._startup_registration

    def allocate_process_pin(self) -> CoordinatorProcessPin:
        """Capture one parser-only descriptor owner before it performs I/O."""
        self._lease._require_process()
        with self._lease._state_lock:
            self._require_owned_locked()
            if (
                self._source_work is not SourceWorkKind.PARSER
                or self._lease._source_quarantined
                or self._process_pin is not None
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._process_pin = CoordinatorProcessPin(self)
            return self._process_pin

    def retire(self) -> None:
        """Call only after every resource retained by this operation retires."""
        self._lease._require_process()
        with self._lease._state_lock:
            if self._process_pin is not None and not self._process_pin._retired:
                raise RuntimeError("Agent run coordinator is unavailable.")
            # The original admitted identity remains weakly registered. This
            # single mutation leaves either an active token or positive proof
            # that it completed retirement, without retaining tombstones.
            self._lease._borrows.discard(self)


class CoordinatorSourceStartup:
    """One exact maintenance registration; it never proves file/SQL cleanup.

    The original trusted source-store owner must prove all retained resources
    retired before calling publish. This primitive proves only the token/lease
    transition and immutable binding. It never invokes owner callbacks.
    """

    def __init__(self, borrow: CoordinatorBorrow, owner: object) -> None:
        self._borrow = borrow
        self._owner = owner
        self._self = ref(self)
        self._attempted = False
        self._state = "allocated"

    def _require_identity(self) -> None:
        self._borrow._lease._require_process()
        if self._self() is not self or self._borrow._startup_registration is not self:
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _register_locked(self) -> None:
        self._borrow._lease._source_startup = self
        self._state = "pending"

    def _fail_locked(self) -> None:
        self._state = "failed"
        self._borrow._lease._source_quarantined = True

    def acquire(self) -> None:
        self._require_identity()
        lease = self._borrow._lease
        with lease._state_lock:
            if self._attempted:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._attempted = True
            self._borrow._require_owned_locked()
            if (
                lease._closing
                or lease._source_quarantined
                or lease._source_tagged_ever
                or lease._source_startup is not None
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            try:
                self._register_locked()
            except BaseException as error:
                # The captured attempt remains the denying owner even if the
                # transition failed immediately before its visible effect.
                lease._source_startup = self
                self._fail_locked()
                if isinstance(error, Exception):
                    raise RuntimeError(
                        "Agent run coordinator is unavailable."
                    ) from None
                raise

    def _publish_locked(self, binding: SourceStorageBinding) -> None:
        self._borrow._lease._source_binding = binding
        self._state = "ready"

    def publish(self, binding: SourceStorageBinding, *, owner: object) -> None:
        self._require_identity()
        if owner is not self._owner or type(binding) is not SourceStorageBinding:
            raise RuntimeError("Agent run coordinator is unavailable.")
        binding.__post_init__()
        lease = self._borrow._lease
        with lease._state_lock:
            if (
                lease._source_startup is not self
                or self._state != "pending"
                or self._borrow not in lease._registered_borrows
                or self._borrow in lease._borrows
                or lease._closing
                or lease._source_quarantined
                or not lease._is_owned_locked()
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            try:
                self._publish_locked(binding)
            except BaseException as error:
                self._fail_locked()
                if isinstance(error, Exception):
                    raise RuntimeError(
                        "Agent run coordinator is unavailable."
                    ) from None
                raise

    def fail(self, *, owner: object) -> None:
        """Latch denial without requiring new positive filesystem evidence."""
        self._require_identity()
        lease = self._borrow._lease
        with lease._state_lock:
            if owner is not self._owner or lease._source_startup is not self:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._fail_locked()


class CoordinatorProcessPin:
    """One duplicate of the actual flock description, never an unlock owner.

    This helper proves only parent descriptor retirement, not child exit. The
    trusted parser owner must wait for its exact child before retiring this pin,
    then retire the parser borrow. It alone may pass child_fd to the fixed child.
    """

    def __init__(self, borrow: CoordinatorBorrow) -> None:
        self._borrow = borrow
        self._file: io.FileIO | None = None
        self._unadopted_fd: int | None = None
        self._opener_returned = False
        self._attempted = False
        self._active = False
        self._running = False
        self._retired = False
        self._uncertain = False

    def _require_identity(self) -> None:
        self._borrow._lease._require_process()
        if self._borrow._process_pin is not self:
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _require_usable_locked(self) -> None:
        self._borrow._require_owned_locked()
        if self._borrow._lease._source_quarantined or self._retired or self._uncertain:
            raise RuntimeError("Agent run coordinator is unavailable.")

    def _duplicate_descriptor(self) -> None:
        self._unadopted_fd = os.dup(self._borrow._lease._fd)

    def _opener(self, _path: str, _flags: int) -> int:
        self._duplicate_descriptor()
        self._opener_returned = True
        return self._unadopted_fd

    def _adopt_descriptor(self) -> None:
        # FileIO owns an opener-returned descriptor on constructor failure too.
        # Keep our raw slot until the real wrapper has been positively captured.
        self._file = io.FileIO(self._borrow.coordinator_path, "rb", opener=self._opener)
        self._unadopted_fd = None

    def acquire(self) -> None:
        self._require_identity()
        with self._borrow._lease._state_lock:
            self._require_usable_locked()
            if self._attempted or self._running:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._attempted = True
            self._running = True
        try:
            # The active parser token pins the actual descriptor while this
            # one action owns I/O. Shutdown may still close admission promptly.
            self._adopt_descriptor()
            fd = self._file.fileno()
            if os.get_inheritable(fd):
                raise RuntimeError("Agent run coordinator is unavailable.")
            with self._borrow._lease._state_lock:
                self._active = True
        except BaseException as error:
            # If FileIO received the FD but no wrapper was captured, its
            # constructor may already have closed/reused that integer.
            if self._opener_returned and self._file is None:
                self._mark_uncertain()
            if isinstance(error, Exception):
                raise RuntimeError("Agent run coordinator is unavailable.") from None
            raise
        finally:
            with self._borrow._lease._state_lock:
                self._running = False

    def _mark_uncertain(self) -> None:
        with self._borrow._lease._state_lock:
            self._uncertain = True
            self._borrow._lease._source_quarantined = True

    @property
    def child_fd(self) -> int:
        """For the trusted fixed child's pass_fds only; no child-exit proof."""
        self._require_identity()
        with self._borrow._lease._state_lock:
            self._require_usable_locked()
            if (
                self._running
                or not self._active
                or self._file is None
                or self._file.closed
            ):
                raise RuntimeError("Agent run coordinator is unavailable.")
            return self._file.fileno()

    def _close_descriptor(self) -> None:
        if self._file is not None:
            if not self._file.closed:
                self._file.close()
            if not self._file.closed:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._file = None
            self._unadopted_fd = None
        elif self._unadopted_fd is not None:
            # FileIO never received this duplicate. A raw-close failure has an
            # unknown effect, so never retry an integer that may be reused.
            try:
                os.close(self._unadopted_fd)
            except BaseException:
                self._mark_uncertain()
                raise
            self._unadopted_fd = None

    def retire(self) -> None:
        """Close captured parent descriptors only, after actual parser wait."""
        self._require_identity()
        with self._borrow._lease._state_lock:
            if self._retired:
                return
            if self._running or self._uncertain:
                raise RuntimeError("Agent run coordinator is unavailable.")
            self._active = False
            self._running = True
        try:
            self._close_descriptor()
            with self._borrow._lease._state_lock:
                self._retired = True
        except Exception:
            raise RuntimeError("Agent run coordinator is unavailable.") from None
        finally:
            with self._borrow._lease._state_lock:
                self._running = False
