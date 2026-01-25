"""Batch execution engine for ShipAgent.

Provides batch shipment processing with preview mode, fail-fast error
handling, and crash recovery support.
"""

from src.orchestrator.batch.events import BatchEventEmitter, BatchEventObserver
from src.orchestrator.batch.modes import ExecutionMode, SessionModeManager
from src.orchestrator.batch.models import (
    BatchPreview,
    BatchResult,
    InterruptedJobInfo,
    PreviewRow,
)

__all__ = [
    "ExecutionMode",
    "SessionModeManager",
    "BatchEventObserver",
    "BatchEventEmitter",
    "BatchResult",
    "PreviewRow",
    "BatchPreview",
    "InterruptedJobInfo",
]
