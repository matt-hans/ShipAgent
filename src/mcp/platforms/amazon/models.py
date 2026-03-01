# src/mcp/platforms/amazon/models.py
"""Amazon-specific data models."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from src.mcp.platforms.amazon.constants import BASE_URLS, SANDBOX_BASE_URLS


@dataclass
class AmazonCredentials:
    """Resolved Amazon SP-API credentials."""

    client_id: str
    client_secret: str
    refresh_token: str
    marketplace_id: str = "ATVPDKIKX0DER"  # US default
    sandbox: bool = field(default=False)

    def __post_init__(self) -> None:
        """Auto-detect sandbox mode from env var if not explicitly set."""
        if not self.sandbox:
            self.sandbox = os.environ.get("AMAZON_SP_API_SANDBOX", "").lower() in (
                "1", "true", "yes",
            )

    @property
    def region(self) -> str:
        """Derive region from marketplace ID."""
        # NA marketplaces: US, CA, MX, BR
        na_marketplaces = {"ATVPDKIKX0DER", "A2EUQ1WTGCTBG2", "A1AM78C64UM0Y8", "A2Q3Y263D00KMC"}
        # FE marketplaces: JP, AU, SG, IN
        fe_marketplaces = {"A1VC38T7YXB528", "A39IBJ37TRP1C6", "A19VAU5U5O7RUS", "A21TJRUUN4KGV"}
        if self.marketplace_id in na_marketplaces:
            return "na"
        if self.marketplace_id in fe_marketplaces:
            return "fe"
        return "eu"

    @property
    def base_url(self) -> str:
        """SP-API base URL, switching between sandbox and production."""
        urls = SANDBOX_BASE_URLS if self.sandbox else BASE_URLS
        return urls.get(self.region, urls["na"])
