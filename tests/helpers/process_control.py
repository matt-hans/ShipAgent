"""Process control utilities for crash recovery testing.

Provides helpers for spawning, monitoring, and killing processes
to simulate crash scenarios in integration tests.
"""

import asyncio
import os
import subprocess
from dataclasses import dataclass
from typing import Callable


@dataclass
class ProcessController:
    """Controller for managing test processes.

    Enables crash recovery testing by providing precise control
    over subprocess lifecycle.

    Example:
        controller = ProcessController()
        proc = controller.spawn(["python3", "my_script.py"])

        # Wait for some condition
        await controller.wait_for_condition(lambda: some_check())

        # Simulate crash
        controller.kill_hard(proc)
    """

    def spawn(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """Spawn a subprocess.

        Args:
            command: Command and arguments to run.
            env: Environment variables (merged with current env).

        Returns:
            Popen process handle for the spawned subprocess.

        Raises:
            FileNotFoundError: If the command executable is not found.
            OSError: If process spawning fails.
        """
        merged_env = {**os.environ, **(env or {})}

        return subprocess.Popen(
            command,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def kill_gracefully(self, process: subprocess.Popen, timeout: float = 5.0) -> None:
        """Kill a process gracefully with SIGTERM, then SIGKILL if needed.

        Sends SIGTERM first to allow the process to clean up. If the process
        does not terminate within the timeout, sends SIGKILL to force termination.

        Args:
            process: Process to kill.
            timeout: Seconds to wait before SIGKILL.
        """
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def kill_hard(self, process: subprocess.Popen) -> None:
        """Kill a process immediately with SIGKILL.

        Does not give the process any opportunity to clean up.
        Use this to simulate abrupt crashes.

        Args:
            process: Process to kill.
        """
        process.kill()
        process.wait()

    async def wait_for_condition(
        self,
        condition: Callable[[], bool],
        timeout: float = 30.0,
        poll_interval: float = 0.1,
    ) -> bool:
        """Wait for a condition to become true.

        Polls the condition at regular intervals until it returns True
        or the timeout is reached.

        Args:
            condition: Callable that returns True when condition is met.
            timeout: Maximum seconds to wait.
            poll_interval: Seconds between condition checks.

        Returns:
            True if condition was met, False if timeout expired.
        """
        elapsed = 0.0
        while elapsed < timeout:
            if condition():
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return False
