# src/mcp/platforms/shopify/client.py
"""Shopify API client for the standalone platform MCP server.

Extracted from src/mcp/external_sources/clients/shopify.py.
Handles authentication, order fetching with cursor pagination, and tracking write-back.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from src.mcp.platforms.shopify.constants import API_VERSION, MAX_PAGE_SIZE
from src.mcp.platforms.shopify.models import ShopifyCredentials
from src.services.platform_models import PlatformError, PlatformErrorCode

logger = logging.getLogger(__name__)


class ShopifyClient:
    """Shopify Admin API client with cursor-based pagination."""

    def __init__(self, credentials: ShopifyCredentials):
        self._credentials = credentials
        self._base_url = credentials.base_url
        self._headers = {
            "X-Shopify-Access-Token": credentials.access_token,
            "Content-Type": "application/json",
        }

    async def test_connection(self) -> dict[str, Any]:
        """Test connection by fetching shop info.

        Returns:
            Shop info dict on success.

        Raises:
            PlatformError on failure.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}/shop.json",
                    headers=self._headers,
                )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="Shopify access token is invalid or expired",
                        provider_status=401,
                    )
                resp.raise_for_status()
                return resp.json().get("shop", {})
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="Shopify API timeout during connection test",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Shopify API error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def fetch_orders_page(
        self,
        cursor: str | None = None,
        since: str | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Fetch a single page of orders with cursor-based pagination.

        Args:
            cursor: page_info cursor from previous response Link header.
            since: ISO datetime string for updated_at_min filter.
            page_size: Number of orders per page (max 250).

        Returns:
            Dict with "items", "next_cursor", "watermark" keys.
        """
        page_size = min(page_size, MAX_PAGE_SIZE)

        async with httpx.AsyncClient(timeout=30.0) as client:
            if cursor:
                # Cursor-based pagination: only page_info and limit allowed
                params = {"page_info": cursor, "limit": page_size}
            else:
                params: dict[str, Any] = {
                    "limit": page_size,
                    "status": "any",
                    "order": "updated_at asc",
                }
                if since:
                    params["updated_at_min"] = since

            try:
                resp = await client.get(
                    f"{self._base_url}/orders.json",
                    headers=self._headers,
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "2"))
                    raise PlatformError(
                        error_code=PlatformErrorCode.RATE_LIMITED,
                        message="Shopify rate limit exceeded",
                        retry_after_seconds=retry_after,
                        provider_status=429,
                    )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="Shopify access token expired",
                        provider_status=401,
                    )
                resp.raise_for_status()
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="Shopify API timeout during order fetch",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Shopify API error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

            orders = resp.json().get("orders", [])

            # Extract next cursor from Link header
            next_cursor = self._extract_next_cursor(resp.headers.get("Link", ""))

            # Watermark: last order's updated_at
            watermark = None
            if orders:
                watermark = orders[-1].get("updated_at")

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
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}/orders/{order_id}.json",
                    headers=self._headers,
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json().get("order")
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Shopify API error fetching order {order_id}: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def write_back_tracking(
        self,
        order_id: str,
        tracking_numbers: list[str],
        carrier: str = "UPS",
        tracking_url: str | None = None,
    ) -> dict[str, Any]:
        """Write tracking info back to Shopify as a fulfillment.

        Creates a new fulfillment or updates existing one.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            # First check if order is already fulfilled
            try:
                order_resp = await client.get(
                    f"{self._base_url}/orders/{order_id}.json",
                    headers=self._headers,
                )
                order_resp.raise_for_status()
                order_data = order_resp.json().get("order", {})
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Failed to fetch order {order_id} for write-back",
                    provider_status=e.response.status_code,
                )

            tracking_number = tracking_numbers[0] if tracking_numbers else ""

            if order_data.get("fulfillment_status") == "fulfilled":
                # Update existing fulfillment
                return await self._update_fulfillment_tracking(
                    client, order_data, tracking_number, carrier, tracking_url
                )
            else:
                # Create new fulfillment
                return await self._create_fulfillment(
                    client, order_id, order_data, tracking_number, carrier, tracking_url
                )

    async def _create_fulfillment(
        self,
        client: httpx.AsyncClient,
        order_id: str,
        order_data: dict,
        tracking_number: str,
        carrier: str,
        tracking_url: str | None,
    ) -> dict[str, Any]:
        """Create a new fulfillment with tracking info."""
        line_items = [
            {"id": item["id"]}
            for item in order_data.get("line_items", [])
        ]

        fulfillment: dict[str, Any] = {
            "tracking_number": tracking_number,
            "tracking_company": carrier,
            "notify_customer": True,
            "line_items": line_items,
        }
        if tracking_url:
            fulfillment["tracking_url"] = tracking_url

        try:
            resp = await client.post(
                f"{self._base_url}/orders/{order_id}/fulfillments.json",
                headers=self._headers,
                json={"fulfillment": fulfillment},
            )
            resp.raise_for_status()
            return {"success": True}
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"Failed to create fulfillment for order {order_id}: {e.response.status_code}",
                provider_status=e.response.status_code,
            )

    async def _update_fulfillment_tracking(
        self,
        client: httpx.AsyncClient,
        order_data: dict,
        tracking_number: str,
        carrier: str,
        tracking_url: str | None,
    ) -> dict[str, Any]:
        """Update tracking on an existing fulfillment (idempotency path)."""
        fulfillments = order_data.get("fulfillments", [])
        if not fulfillments:
            return {"success": False, "error": "No fulfillments found to update"}

        fulfillment_id = fulfillments[0]["id"]
        order_id = order_data["id"]

        update: dict[str, Any] = {
            "tracking_number": tracking_number,
            "tracking_company": carrier,
            "notify_customer": False,
        }
        if tracking_url:
            update["tracking_url"] = tracking_url

        try:
            resp = await client.put(
                f"{self._base_url}/orders/{order_id}/fulfillments/{fulfillment_id}.json",
                headers=self._headers,
                json={"fulfillment": update},
            )
            resp.raise_for_status()
            return {"success": True}
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                error_code=PlatformErrorCode.UPSTREAM_ERROR,
                message=f"Failed to update fulfillment tracking: {e.response.status_code}",
                provider_status=e.response.status_code,
            )

    @staticmethod
    def _extract_next_cursor(link_header: str) -> str | None:
        """Extract the next page cursor from Shopify's Link header.

        Shopify uses RFC 5988 Link headers with page_info query param:
        <https://store.myshopify.com/admin/api/.../orders.json?page_info=xyz>; rel="next"
        """
        if not link_header:
            return None

        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                # Extract URL between < and >
                url_part = part.split(";")[0].strip().strip("<>")
                # Extract page_info param
                if "page_info=" in url_part:
                    return url_part.split("page_info=")[1].split("&")[0]
        return None
