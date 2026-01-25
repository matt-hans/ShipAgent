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
]
