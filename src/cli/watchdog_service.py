"""HotFolderService — filesystem watcher for zero-touch automation.

Monitors configured directories for new CSV/Excel files.
When a file lands, it is debounced, claimed, imported, and
processed through the agent with auto-confirm rules.

Runs inside the daemon process using the watchdog library.
Thread events are bridged to the async loop via call_soon_threadsafe.
"""

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.cli.config import WatchFolderConfig

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 2.0


def _ensure_subdirs(folder_path: str) -> None:
    """Create .processing, processed, and failed subdirectories.

    Args:
        folder_path: The watch folder root path.
    """
    root = Path(folder_path)
    for subdir in [".processing", "processed", "failed"]:
        (root / subdir).mkdir(parents=True, exist_ok=True)


def _get_file_extension(filename: str) -> str:
    """Get lowercase file extension from filename.

    Args:
        filename: The filename to extract extension from.

    Returns:
        Lowercase extension including dot (e.g., ".csv").
    """
    return Path(filename).suffix.lower()


def _should_process_file(filename: str, config: WatchFolderConfig) -> bool:
    """Check if a file should be processed based on config rules.

    Args:
        filename: The filename to check.
        config: The watch folder configuration.

    Returns:
        True if the file matches the configured file types and isn't hidden/temp.
    """
    if filename.startswith("."):
        return False
    if filename.endswith("~"):
        return False
    ext = _get_file_extension(filename)
    return ext in config.file_types


class _DebouncingHandler(FileSystemEventHandler):
    """Filesystem event handler with debouncing.

    Waits DEBOUNCE_SECONDS after the last event for a file before
    triggering processing. This handles partial uploads and large files.
    """

    def __init__(
        self,
        config: WatchFolderConfig,
        loop: asyncio.AbstractEventLoop,
        callback: Any,
    ):
        """Initialize handler with config, event loop, and async callback.

        Args:
            config: Watch folder configuration.
            loop: The asyncio event loop to bridge events to.
            callback: Async function(file_path, config) called after debounce.
        """
        self._config = config
        self._loop = loop
        self._callback = callback
        self._pending: dict[str, float] = {}
        self._timers: dict[str, Any] = {}

    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            self._debounce(event.src_path)

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            self._debounce(event.src_path)

    def _debounce(self, file_path: str) -> None:
        """Debounce file events — wait for writes to settle.

        THREAD SAFETY: This method runs on the watchdog observer thread.
        ALL event loop interaction MUST go through call_soon_threadsafe.
        We use a threading.Timer for the debounce delay (runs on a thread),
        then bridge to the async loop only when firing the callback.

        Args:
            file_path: Path of the file that triggered the event.
        """
        import threading

        filename = Path(file_path).name
        if not _should_process_file(filename, self._config):
            return

        self._pending[file_path] = time.time()

        # Cancel existing timer (threading.Timer, safe from any thread)
        if file_path in self._timers:
            self._timers[file_path].cancel()

        def _on_timer_expired(fp=file_path):
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._fire(fp))
            )

        timer = threading.Timer(DEBOUNCE_SECONDS, _on_timer_expired)
        timer.daemon = True
        self._timers[file_path] = timer
        timer.start()

    async def _fire(self, file_path: str) -> None:
        """Fire the callback after debounce period.

        This runs on the async event loop (bridged via call_soon_threadsafe).

        Args:
            file_path: Path of the file to process.
        """
        self._pending.pop(file_path, None)
        self._timers.pop(file_path, None)
        try:
            await self._callback(file_path, self._config)
        except Exception:
            logger.exception("Error processing file %s", file_path)


class HotFolderService:
    """Watches configured directories and processes incoming files.

    Runs inside the daemon process. Uses the watchdog library for
    filesystem monitoring with thread->async bridging.
    """

    def __init__(self, configs: list[WatchFolderConfig]):
        """Initialize the hot folder service.

        Args:
            configs: List of watch folder configurations.
        """
        self._configs = configs
        self._observer: Observer | None = None
        # GLOBAL lock — serializes ALL file processing across ALL folders.
        # Required because DataSourceMCPClient is a process-global singleton
        # that holds one active data source. Per-directory locks would still
        # allow cross-folder concurrency against the single data source.
        self._global_processing_lock = asyncio.Lock()

        for config in configs:
            _ensure_subdirs(config.path)

    def scan_existing_files(self) -> list[Path]:
        """Scan watch folders for files dropped while daemon was down.

        Returns:
            List of file paths that need processing.
        """
        backlog = []
        for config in self._configs:
            root = Path(config.path)
            if not root.exists():
                continue
            for entry in root.iterdir():
                if entry.is_file() and _should_process_file(entry.name, config):
                    backlog.append(entry)
        return backlog

    async def start(self, process_callback) -> None:
        """Start watching all configured directories.

        Args:
            process_callback: Async function(file_path, config) to handle files.
        """
        loop = asyncio.get_running_loop()
        self._observer = Observer()

        for config in self._configs:
            folder_path = Path(config.path)
            if not folder_path.exists():
                logger.warning("Watch folder does not exist: %s", config.path)
                continue

            handler = _DebouncingHandler(config, loop, process_callback)
            self._observer.schedule(handler, str(folder_path), recursive=False)
            logger.info("Watching: %s -> \"%s\"", config.path, config.command)

        self._observer.start()
        logger.info("HotFolderService started (%d folders)", len(self._configs))

    async def stop(self) -> None:
        """Stop the filesystem observer."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("HotFolderService stopped")

    def _collision_safe_name(self, dest_dir: Path, filename: str) -> Path:
        """Generate a collision-safe destination path.

        If filename already exists in dest_dir, appends a timestamp suffix.

        Args:
            dest_dir: Target directory.
            filename: Original filename.

        Returns:
            Path that does not collide with existing files.
        """
        dest = dest_dir / filename
        if not dest.exists():
            return dest
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        ts = time.strftime("%Y%m%d-%H%M%S")
        return dest_dir / f"{stem}_{ts}{suffix}"

    @property
    def processing_lock(self) -> asyncio.Lock:
        """Global processing lock — serializes ALL file processing.

        Returns:
            The global asyncio.Lock.
        """
        return self._global_processing_lock

    def claim_file(self, file_path: str) -> Path | None:
        """Move a file to .processing/ to claim it.

        Args:
            file_path: Path to the file to claim.

        Returns:
            New path in .processing/, or None if file doesn't exist.
        """
        src = Path(file_path)
        if not src.exists():
            return None
        parent = src.parent
        processing_dir = parent / ".processing"
        dest = self._collision_safe_name(processing_dir, src.name)
        shutil.move(str(src), str(dest))
        return dest

    def complete_file(self, processing_path: Path) -> None:
        """Move a processed file to processed/ directory.

        Args:
            processing_path: Path in .processing/ to move.
        """
        processed_dir = processing_path.parent.parent / "processed"
        dest = self._collision_safe_name(processed_dir, processing_path.name)
        shutil.move(str(processing_path), str(dest))

    def fail_file(self, processing_path: Path, error: dict) -> None:
        """Move a failed file to failed/ with error sidecar.

        Args:
            processing_path: Path in .processing/ to move.
            error: Error details to write to .error sidecar file.
        """
        failed_dir = processing_path.parent.parent / "failed"
        dest = self._collision_safe_name(failed_dir, processing_path.name)
        shutil.move(str(processing_path), str(dest))

        error_file = dest.with_suffix(dest.suffix + ".error")
        error_file.write_text(json.dumps(error, indent=2))
