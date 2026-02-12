"""Shared service-layer error types.

Provides error dataclasses used across service modules (UPS, batch engine, etc.).
Centralised here to avoid circular imports between service modules.
"""

from dataclasses import dataclass


@dataclass
class UPSServiceError(Exception):
    """Error from UPS service layer.

    Attributes:
        code: ShipAgent error code (E-XXXX format)
        message: Human-readable error message
        remediation: Suggested fix
        details: Raw error details
    """

    code: str
    message: str
    remediation: str = ""
    details: dict | None = None

    def __str__(self) -> str:
        """Return formatted error message."""
        return f"[{self.code}] {self.message}"
