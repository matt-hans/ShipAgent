"""Tests for ProcessController helper."""

import pytest

from tests.helpers.process_control import ProcessController


class TestProcessController:
    """Tests for process control utilities."""

    def test_controller_initializes(self):
        """Controller should initialize without errors."""
        controller = ProcessController()
        assert controller is not None

    def test_spawn_returns_process(self):
        """Spawn should return a process handle."""
        controller = ProcessController()
        proc = controller.spawn(["python3", "-c", "import time; time.sleep(10)"])
        assert proc is not None
        assert proc.poll() is None  # Still running
        proc.kill()
        proc.wait()

    def test_kill_gracefully(self):
        """kill_gracefully should terminate process with SIGTERM first."""
        controller = ProcessController()
        proc = controller.spawn(["python3", "-c", "import time; time.sleep(60)"])
        assert proc.poll() is None  # Still running
        controller.kill_gracefully(proc, timeout=2.0)
        assert proc.poll() is not None  # Process terminated

    def test_kill_hard(self):
        """kill_hard should immediately kill process with SIGKILL."""
        controller = ProcessController()
        proc = controller.spawn(["python3", "-c", "import time; time.sleep(60)"])
        assert proc.poll() is None  # Still running
        controller.kill_hard(proc)
        assert proc.poll() is not None  # Process killed

    @pytest.mark.asyncio
    async def test_wait_for_condition_returns_true_when_met(self):
        """wait_for_condition should return True when condition is met."""
        controller = ProcessController()
        counter = {"value": 0}

        def condition():
            counter["value"] += 1
            return counter["value"] >= 3

        result = await controller.wait_for_condition(
            condition, timeout=5.0, poll_interval=0.1
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_condition_returns_false_on_timeout(self):
        """wait_for_condition should return False when timeout reached."""
        controller = ProcessController()

        def never_true():
            return False

        result = await controller.wait_for_condition(
            never_true, timeout=0.3, poll_interval=0.1
        )
        assert result is False

    def test_spawn_with_custom_env(self):
        """Spawn should accept custom environment variables."""
        controller = ProcessController()
        proc = controller.spawn(
            ["python3", "-c", "import os; print(os.environ.get('TEST_VAR', ''))"],
            env={"TEST_VAR": "test_value"},
        )
        stdout, _ = proc.communicate(timeout=5.0)
        assert b"test_value" in stdout
