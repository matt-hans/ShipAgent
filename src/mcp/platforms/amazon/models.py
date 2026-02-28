# src/mcp/platforms/amazon/models.py
"""Amazon-specific data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AmazonCredentials:
    """Resolved Amazon SP-API credentials."""

    client_id: str
    client_secret: str
    refresh_token: str
    marketplace_id: str = "ATVPDKIKX0DER"  # US default

    @property
    def base_url(self) -> str:
        """SP-API base URL for the marketplace."""
        return "https://sellingpartnerapi-na.amazon.com"
