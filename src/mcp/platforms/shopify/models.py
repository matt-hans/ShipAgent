# src/mcp/platforms/shopify/models.py
"""Shopify-specific data models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShopifyCredentials:
    """Resolved Shopify credentials for a connection."""

    access_token: str
    store_domain: str

    @property
    def base_url(self) -> str:
        """Build the Shopify Admin API base URL."""
        from src.mcp.platforms.shopify.constants import API_VERSION
        domain = self.store_domain.rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return f"{domain}/admin/api/{API_VERSION}"
