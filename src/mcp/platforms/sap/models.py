# src/mcp/platforms/sap/models.py
"""SAP-specific data models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SapCredentials:
    """Resolved SAP OData credentials for a connection."""

    base_url: str
    username: str
    password: str
    sap_client: str

    @property
    def odata_base_url(self) -> str:
        """Normalize the base URL for OData requests."""
        return self.base_url.rstrip("/")
