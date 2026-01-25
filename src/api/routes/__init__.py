"""FastAPI route modules.

Exports all route modules for inclusion in the main application.
"""

from src.api.routes import commands, jobs, labels, logs, preview, progress

__all__ = [
    "commands",
    "jobs",
    "labels",
    "logs",
    "preview",
    "progress",
]
