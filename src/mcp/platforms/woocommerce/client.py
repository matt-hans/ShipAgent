# src/mcp/platforms/woocommerce/client.py
"""WooCommerce platform client (standalone, no legacy imports).

Thin wrapper around httpx for WooCommerce REST API v3 with Basic Auth.
Handles order fetching with offset-based pagination and tracking write-back.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from src.mcp.platforms.woocommerce.constants import MAX_PAGE_SIZE
from src.mcp.platforms.woocommerce.models import WooCommerceCredentials
from src.services.platform_models import PlatformError, PlatformErrorCode

logger = logging.getLogger(__name__)


class WooCommerceClient:
    """WooCommerce REST API v3 client for the standalone platform MCP."""

    def __init__(self, credentials: WooCommerceCredentials) -> None:
        """Initialize with resolved credentials.

        Args:
            credentials: WooCommerce site URL and consumer key/secret.
        """
        self._creds = credentials
        self._http: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily create or return the httpx client.

        Returns:
            Active httpx.AsyncClient with Basic Auth configured.
        """
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                auth=(self._creds.consumer_key, self._creds.consumer_secret),
                timeout=30.0,
            )
        return self._http

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection by calling the system_status endpoint.

        Returns:
            System status dict on success.

        Raises:
            PlatformError: On auth failure or transient error.
        """
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self._creds.base_url}/system_status")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise PlatformError(
                    error_code=PlatformErrorCode.AUTH_EXPIRED,
                    message=f"WooCommerce auth failed: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )
            raise PlatformError(
                error_code=PlatformErrorCode.TRANSIENT,
                message=f"WooCommerce API error: {e.response.status_code}",
                provider_status=e.response.status_code,
            )
        except httpx.RequestError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.TRANSIENT,
                message=f"WooCommerce connection error: {e}",
            )

    async def fetch_orders_page(
        self,
        page: int = 1,
        since: str | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Fetch a single page of orders with offset-based pagination.

        Args:
            page: Page number (1-based).
            since: ISO datetime string for modified_after filter.
            page_size: Number of orders per page (max 100).

        Returns:
            Dict with "items", "next_cursor", "watermark" keys
            matching the platform contract.
        """
        page_size = min(page_size, MAX_PAGE_SIZE)
        client = await self._ensure_client()

        params: dict[str, Any] = {
            "page": page,
            "per_page": page_size,
            "orderby": "date",
            "order": "asc",
        }
        if since:
            params["modified_after"] = since

        try:
            resp = await client.get(
                f"{self._creds.base_url}/orders",
                params=params,
            )
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "2"))
                raise PlatformError(
                    error_code=PlatformErrorCode.RATE_LIMITED,
                    message="WooCommerce rate limit exceeded",
                    retry_after_seconds=retry_after,
                    provider_status=429,
                )
            if resp.status_code in (401, 403):
                raise PlatformError(
                    error_code=PlatformErrorCode.AUTH_EXPIRED,
                    message="WooCommerce consumer key/secret expired or invalid",
                    provider_status=resp.status_code,
                )
            resp.raise_for_status()
        except httpx.TimeoutException:
            raise PlatformError(
                error_code=PlatformErrorCode.TRANSIENT,
                message="WooCommerce API timeout during order fetch",
            )
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"WooCommerce API error: {e.response.status_code}",
                provider_status=e.response.status_code,
            )

        orders = resp.json()
        total = resp.headers.get("X-WP-Total")
        total_pages = resp.headers.get("X-WP-TotalPages")

        # Determine next cursor: next page number or None
        has_next = False
        if total_pages:
            has_next = page < int(total_pages)
        elif len(orders) == page_size:
            has_next = True

        next_cursor = str(page + 1) if has_next else None

        # Watermark: last order's date_modified
        watermark = None
        if orders:
            watermark = orders[-1].get("date_modified")

        return {
            "items": orders,
            "next_cursor": next_cursor,
            "watermark": watermark,
        }

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch a single order by ID.

        Args:
            order_id: WooCommerce order ID.

        Returns:
            Order dict or None if not found.

        Raises:
            PlatformError: On API errors other than 404.
        """
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self._creds.base_url}/orders/{order_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"WooCommerce API error fetching order {order_id}: {e.response.status_code}",
                provider_status=e.response.status_code,
            )

    async def update_tracking(
        self,
        order_id: str,
        tracking_numbers: list[str],
        carrier: str = "UPS",
        tracking_url: str | None = None,
    ) -> dict[str, Any]:
        """Write tracking info back to WooCommerce via order meta_data.

        Compatible with the WooCommerce Shipment Tracking plugin which
        reads _tracking_number and _tracking_provider meta keys.

        Args:
            order_id: WooCommerce order ID to update.
            tracking_numbers: List of tracking numbers to write.
            carrier: Carrier name (default: "UPS").
            tracking_url: Optional tracking URL.

        Returns:
            Dict with "success": True on success.

        Raises:
            PlatformError: On API errors.
        """
        client = await self._ensure_client()
        meta_data: list[dict[str, str]] = [
            {"key": "_tracking_number", "value": tn} for tn in tracking_numbers
        ]
        meta_data.append({"key": "_tracking_provider", "value": carrier})
        if tracking_url:
            meta_data.append({"key": "_tracking_link", "value": tracking_url})

        try:
            resp = await client.put(
                f"{self._creds.base_url}/orders/{order_id}",
                json={"meta_data": meta_data},
            )
            resp.raise_for_status()
            return {"success": True}
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"Failed to update tracking for order {order_id}: {e.response.status_code}",
                provider_status=e.response.status_code,
            )

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
