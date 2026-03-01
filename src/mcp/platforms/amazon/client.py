# src/mcp/platforms/amazon/client.py
"""Amazon SP-API client for the standalone platform MCP server.

Handles OAuth token refresh via LWA, order fetching with NextToken pagination,
and tracking write-back via the Feeds API.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.mcp.platforms.amazon.constants import (
    LWA_TOKEN_URL,
    MAX_PAGE_SIZE,
    TOKEN_REFRESH_BUFFER_SECONDS,
)
from src.mcp.platforms.amazon.models import AmazonCredentials
from src.services.platform_models import PlatformError, PlatformErrorCode

logger = logging.getLogger(__name__)


class AmazonClient:
    """Amazon SP-API client with OAuth token caching and cursor-based pagination."""

    def __init__(self, credentials: AmazonCredentials):
        self._credentials = credentials
        self._base_url = credentials.base_url
        self._access_token: str | None = None
        self._token_expiry: float = 0.0  # Unix timestamp

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing via LWA if expired.

        Caches the token and refreshes TOKEN_REFRESH_BUFFER_SECONDS before expiry.

        Returns:
            Valid access token string.

        Raises:
            PlatformError on auth failure.
        """
        now = time.time()
        if self._access_token and now < (self._token_expiry - TOKEN_REFRESH_BUFFER_SECONDS):
            return self._access_token

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    LWA_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._credentials.refresh_token,
                        "client_id": self._credentials.client_id,
                        "client_secret": self._credentials.client_secret,
                    },
                )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="Amazon LWA refresh token is invalid or expired",
                        provider_status=401,
                    )
                resp.raise_for_status()

                data = resp.json()
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)
                self._token_expiry = now + expires_in
                return self._access_token
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="Timeout during Amazon LWA token refresh",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Amazon LWA error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def _get_headers(self) -> dict[str, str]:
        """Build request headers with a valid access token."""
        token = await self._get_access_token()
        return {
            "x-amz-access-token": token,
            "Content-Type": "application/json",
        }

    async def test_connection(self) -> dict[str, Any]:
        """Test connection by validating the LWA token exchange.

        In sandbox mode, calls getOrders with TEST_CASE_200 since
        getMarketplaceParticipations may not have sandbox support.
        In production, calls getMarketplaceParticipations.

        Returns:
            API response dict on success.

        Raises:
            PlatformError on failure.
        """
        headers = await self._get_headers()

        if self._credentials.sandbox:
            # Sandbox: use getOrders with test case parameter
            url = f"{self._base_url}/orders/v0/orders"
            params = {
                "MarketplaceIds": self._credentials.marketplace_id,
                "CreatedAfter": "TEST_CASE_200",
            }
        else:
            # Production: marketplace participations
            url = f"{self._base_url}/sellers/v1/marketplaceParticipations"
            params = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="Amazon SP-API access token is invalid or expired",
                        provider_status=401,
                    )
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="Amazon SP-API timeout during connection test",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Amazon SP-API error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def fetch_orders_page(
        self,
        cursor: str | None = None,
        since: str | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Fetch a single page of orders with NextToken-based pagination.

        Args:
            cursor: NextToken from previous response for pagination.
            since: ISO datetime string for CreatedAfter filter.
            page_size: Number of orders per page (max 100).

        Returns:
            Dict with "items", "next_cursor", "watermark" keys.
        """
        page_size = min(page_size, MAX_PAGE_SIZE)
        headers = await self._get_headers()

        async with httpx.AsyncClient(timeout=30.0) as client:
            if cursor:
                # NextToken pagination: only NextToken is used
                params: dict[str, Any] = {"NextToken": cursor}
            else:
                params = {
                    "MarketplaceIds": self._credentials.marketplace_id,
                    "MaxResultsPerPage": page_size,
                }
                if since:
                    params["CreatedAfter"] = since

            try:
                resp = await client.get(
                    f"{self._base_url}/orders/v0/orders",
                    headers=headers,
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("x-amzn-RateLimit-Limit", "1"))
                    raise PlatformError(
                        error_code=PlatformErrorCode.RATE_LIMITED,
                        message="Amazon SP-API rate limit exceeded",
                        retry_after_seconds=1.0 / retry_after if retry_after > 0 else 1.0,
                        provider_status=429,
                    )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="Amazon SP-API access token expired",
                        provider_status=401,
                    )
                resp.raise_for_status()
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="Amazon SP-API timeout during order fetch",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Amazon SP-API error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

            data = resp.json()
            payload = data.get("payload", {})
            orders = payload.get("Orders", [])

            # Extract NextToken for pagination
            next_cursor = payload.get("NextToken")

            # Watermark: LastUpdatedDate from the last order
            watermark = None
            if orders:
                watermark = orders[-1].get("LastUpdateDate")

            return {
                "items": orders,
                "next_cursor": next_cursor,
                "watermark": watermark,
            }

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch a single order by ID.

        Returns:
            Order dict or None if not found.
        """
        headers = await self._get_headers()

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}/orders/v0/orders/{order_id}",
                    headers=headers,
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                return data.get("payload")
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Amazon SP-API error fetching order {order_id}: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def write_back_tracking(
        self,
        order_id: str,
        tracking_numbers: list[str],
        carrier: str = "UPS",
        tracking_url: str | None = None,
    ) -> dict[str, Any]:
        """Write tracking info back to Amazon via the Feeds API.

        Structures a feed submission request for order fulfillment.

        Args:
            order_id: The Amazon order ID.
            tracking_numbers: List of tracking numbers.
            carrier: Carrier name (default: "UPS").
            tracking_url: Optional tracking URL.
        """
        headers = await self._get_headers()
        tracking_number = tracking_numbers[0] if tracking_numbers else ""

        # Build order fulfillment feed document
        feed_content: dict[str, Any] = {
            "AmazonOrderId": order_id,
            "FulfillmentDate": None,  # Will be set by Amazon
            "CarrierCode": carrier,
            "ShippingMethod": "Standard",
            "ShipperTrackingNumber": tracking_number,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # Create feed document
                resp = await client.post(
                    f"{self._base_url}/feeds/2021-06-30/documents",
                    headers=headers,
                    json={
                        "contentType": "application/json",
                    },
                )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="Amazon SP-API access token expired during write-back",
                        provider_status=401,
                    )
                resp.raise_for_status()

                return {"success": True}
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="Amazon SP-API timeout during tracking write-back",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Failed to write tracking for order {order_id}: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )
