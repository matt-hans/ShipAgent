# src/mcp/platforms/woocommerce/models.py
"""WooCommerce-specific data models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WooCommerceCredentials:
    """Resolved WooCommerce credentials for a connection."""

    site_url: str
    consumer_key: str
    consumer_secret: str

    @property
    def base_url(self) -> str:
        """Build the WooCommerce REST API base URL."""
        from src.mcp.platforms.woocommerce.constants import API_VERSION

        url = self.site_url.rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"
        return f"{url}/wp-json/{API_VERSION}"
