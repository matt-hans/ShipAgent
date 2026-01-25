"""Execution modes for batch processing.

Defines the execution modes (CONFIRM vs AUTO) and provides session-level
mode management with locking during active batch execution.
"""

from enum import Enum


class ExecutionMode(str, Enum):
    """Batch execution mode.

    CONFIRM: Preview batch before execution (default)
    AUTO: Execute immediately without preview
    """

    CONFIRM = "confirm"
    AUTO = "auto"


class SessionModeManager:
    """Manages execution mode for a session.

    Tracks the current execution mode and provides locking to prevent
    mode changes during active batch execution.

    Per CONTEXT.md Decision 2:
    - Default mode: confirm
    - Mid-preview switch: allowed (not locked during preview)
    - Mid-execution switch: not allowed (locked during execution)
    """

    def __init__(self) -> None:
        """Initialize manager with CONFIRM mode."""
        self._mode: ExecutionMode = ExecutionMode.CONFIRM
        self._locked: bool = False

    @property
    def mode(self) -> ExecutionMode:
        """Return current execution mode."""
        return self._mode

    def set_mode(self, mode: ExecutionMode) -> None:
        """Set execution mode.

        Args:
            mode: The execution mode to set.

        Raises:
            ValueError: If mode change is attempted while locked.
        """
        if self._locked:
            raise ValueError(
                "Cannot change execution mode while batch is executing. "
                "Wait for current batch to complete."
            )
        self._mode = mode

    def lock(self) -> None:
        """Lock mode changes (called when batch starts executing)."""
        self._locked = True

    def unlock(self) -> None:
        """Unlock mode changes (called when batch ends)."""
        self._locked = False

    def is_locked(self) -> bool:
        """Return whether mode changes are currently locked."""
        return self._locked

    def reset(self) -> None:
        """Reset to default state (CONFIRM mode, unlocked).

        Called when starting a new session.
        """
        self._mode = ExecutionMode.CONFIRM
        self._locked = False
