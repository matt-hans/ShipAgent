"""Batch execution engine for ShipAgent.

Provides batch shipment processing with event-driven progress tracking,
execution modes, and crash recovery support.
"""

from src.orchestrator.batch.events import BatchEventEmitter, BatchEventObserver
from src.orchestrator.batch.models import (
    BatchPreview,
    BatchResult,
    InterruptedJobInfo,
    PreviewRow,
)
from src.orchestrator.batch.modes import ExecutionMode, SessionModeManager
from src.orchestrator.batch.recovery import (
    RecoveryChoice,
    check_interrupted_jobs,
    get_recovery_prompt,
    handle_recovery_choice,
)
from src.orchestrator.batch.sse_observer import SSEProgressObserver

__all__ = [
    "ExecutionMode",
    "SessionModeManager",
    "BatchEventObserver",
    "BatchEventEmitter",
    "BatchResult",
    "PreviewRow",
    "BatchPreview",
    "InterruptedJobInfo",
    "RecoveryChoice",
    "check_interrupted_jobs",
    "get_recovery_prompt",
    "handle_recovery_choice",
    "SSEProgressObserver",
]
