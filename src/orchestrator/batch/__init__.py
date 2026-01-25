"""Batch execution engine for ShipAgent.

Provides batch shipment processing with preview mode, fail-fast error
handling, and crash recovery support.
"""

from src.orchestrator.batch.events import BatchEventEmitter, BatchEventObserver
from src.orchestrator.batch.executor import BatchExecutor
from src.orchestrator.batch.modes import ExecutionMode, SessionModeManager
from src.orchestrator.batch.models import (
    BatchPreview,
    BatchResult,
    InterruptedJobInfo,
    PreviewRow,
)
from src.orchestrator.batch.preview import PreviewGenerator
from src.orchestrator.batch.recovery import (
    RecoveryChoice,
    check_interrupted_jobs,
    get_recovery_prompt,
    handle_recovery_choice,
)

__all__ = [
    "ExecutionMode",
    "SessionModeManager",
    "BatchEventObserver",
    "BatchEventEmitter",
    "BatchExecutor",
    "BatchResult",
    "PreviewRow",
    "BatchPreview",
    "InterruptedJobInfo",
    "PreviewGenerator",
    "RecoveryChoice",
    "check_interrupted_jobs",
    "get_recovery_prompt",
    "handle_recovery_choice",
]
