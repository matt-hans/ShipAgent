"""Unit tests for batch execution modes.

Tests cover:
- Default mode behavior
- Mode switching
- Lock/unlock during execution
- Reset behavior
"""

import pytest

from src.orchestrator.batch.modes import ExecutionMode, SessionModeManager


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_confirm_value(self) -> None:
        """Test CONFIRM mode has correct string value."""
        assert ExecutionMode.CONFIRM.value == "confirm"

    def test_auto_value(self) -> None:
        """Test AUTO mode has correct string value."""
        assert ExecutionMode.AUTO.value == "auto"

    def test_enum_is_str(self) -> None:
        """Test ExecutionMode inherits from str for JSON serialization."""
        assert isinstance(ExecutionMode.CONFIRM, str)
        assert isinstance(ExecutionMode.AUTO, str)


class TestSessionModeManager:
    """Tests for SessionModeManager class."""

    def test_default_mode_is_confirm(self) -> None:
        """Test that default mode is CONFIRM per CONTEXT.md Decision 2."""
        manager = SessionModeManager()
        assert manager.mode == ExecutionMode.CONFIRM

    def test_default_not_locked(self) -> None:
        """Test that manager starts unlocked."""
        manager = SessionModeManager()
        assert not manager.is_locked()

    def test_set_mode_to_auto(self) -> None:
        """Test switching mode to AUTO."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        assert manager.mode == ExecutionMode.AUTO

    def test_set_mode_to_confirm(self) -> None:
        """Test switching mode back to CONFIRM."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        manager.set_mode(ExecutionMode.CONFIRM)
        assert manager.mode == ExecutionMode.CONFIRM

    def test_locked_mode_raises_error(self) -> None:
        """Test that changing mode while locked raises ValueError."""
        manager = SessionModeManager()
        manager.lock()

        with pytest.raises(ValueError) as exc_info:
            manager.set_mode(ExecutionMode.AUTO)

        assert "Cannot change execution mode" in str(exc_info.value)
        assert "batch is executing" in str(exc_info.value)

    def test_lock_sets_locked(self) -> None:
        """Test that lock() sets locked state."""
        manager = SessionModeManager()
        manager.lock()
        assert manager.is_locked()

    def test_unlock_allows_change(self) -> None:
        """Test that unlock() allows mode changes again."""
        manager = SessionModeManager()
        manager.lock()
        manager.unlock()

        # Should not raise
        manager.set_mode(ExecutionMode.AUTO)
        assert manager.mode == ExecutionMode.AUTO

    def test_unlock_clears_locked(self) -> None:
        """Test that unlock() clears locked state."""
        manager = SessionModeManager()
        manager.lock()
        manager.unlock()
        assert not manager.is_locked()

    def test_reset_returns_to_confirm(self) -> None:
        """Test that reset() returns mode to CONFIRM."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        manager.reset()
        assert manager.mode == ExecutionMode.CONFIRM

    def test_reset_unlocks(self) -> None:
        """Test that reset() unlocks the manager."""
        manager = SessionModeManager()
        manager.lock()
        manager.reset()
        assert not manager.is_locked()

    def test_reset_full_state(self) -> None:
        """Test that reset() fully restores initial state."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        manager.lock()
        manager.reset()

        assert manager.mode == ExecutionMode.CONFIRM
        assert not manager.is_locked()

    def test_multiple_mode_changes(self) -> None:
        """Test multiple mode changes in sequence."""
        manager = SessionModeManager()

        manager.set_mode(ExecutionMode.AUTO)
        assert manager.mode == ExecutionMode.AUTO

        manager.set_mode(ExecutionMode.CONFIRM)
        assert manager.mode == ExecutionMode.CONFIRM

        manager.set_mode(ExecutionMode.AUTO)
        assert manager.mode == ExecutionMode.AUTO

    def test_locked_preserves_mode(self) -> None:
        """Test that locking preserves the current mode."""
        manager = SessionModeManager()
        manager.set_mode(ExecutionMode.AUTO)
        manager.lock()
        assert manager.mode == ExecutionMode.AUTO
