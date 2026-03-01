# src/mcp/platforms/sap/client.py
"""SAP OData client for the standalone platform MCP server.

Extracted from src/mcp/external_sources/clients/sap.py.
Handles authentication, order fetching with offset pagination, tracking write-back,
and CSRF token management for write operations.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from src.mcp.platforms.sap.constants import MAX_PAGE_SIZE
from src.mcp.platforms.sap.models import SapCredentials
from src.services.platform_models import PlatformError, PlatformErrorCode

logger = logging.getLogger(__name__)


class SapClient:
    """SAP OData API client with offset-based pagination."""

    def __init__(self, credentials: SapCredentials):
        """Initialize the SAP client with credentials.

        Args:
            credentials: SAP connection credentials.
        """
        self._credentials = credentials
        self._base_url = credentials.odata_base_url
        self._auth = (credentials.username, credentials.password)
        self._headers = {
            "sap-client": credentials.sap_client,
            "Accept": "application/json",
        }

    async def test_connection(self) -> dict[str, Any]:
        """Test connection by fetching OData service metadata.

        Returns:
            Dict with metadata status on success.

        Raises:
            PlatformError on failure.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}/$metadata",
                    auth=self._auth,
                    headers=self._headers,
                )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="SAP credentials are invalid or expired",
                        provider_status=401,
                    )
                resp.raise_for_status()
                return {"status": "ok", "base_url": self._base_url}
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="SAP OData API timeout during connection test",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"SAP OData API error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def fetch_orders(
        self,
        offset: int = 0,
        since: str | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Fetch a single page of sales orders with offset-based pagination.

        Args:
            offset: Number of records to skip ($skip).
            since: ISO datetime string for CreationDate filter.
            page_size: Number of orders per page ($top, max 100).

        Returns:
            Dict with "items", "next_cursor", "watermark" keys.
        """
        page_size = min(page_size, MAX_PAGE_SIZE)

        params: dict[str, str] = {
            "$format": "json",
            "$top": str(page_size),
            "$skip": str(offset),
            "$expand": "to_Item",
        }

        # Build OData filter for incremental sync
        odata_filter = self._build_date_filter(since)
        if odata_filter:
            params["$filter"] = odata_filter

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}/SalesOrderSet",
                    auth=self._auth,
                    headers=self._headers,
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "5"))
                    raise PlatformError(
                        error_code=PlatformErrorCode.RATE_LIMITED,
                        message="SAP OData rate limit exceeded",
                        retry_after_seconds=retry_after,
                        provider_status=429,
                    )
                if resp.status_code == 401:
                    raise PlatformError(
                        error_code=PlatformErrorCode.AUTH_EXPIRED,
                        message="SAP credentials expired",
                        provider_status=401,
                    )
                resp.raise_for_status()
            except httpx.TimeoutException:
                raise PlatformError(
                    error_code=PlatformErrorCode.TRANSIENT,
                    message="SAP OData API timeout during order fetch",
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"SAP OData API error: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

            data = resp.json()
            results = data.get("d", {}).get("results", [])

            # Determine next cursor: if we got a full page, there may be more
            next_cursor: str | None = None
            if len(results) >= page_size:
                next_cursor = str(offset + page_size)

            # Watermark: last order's CreationDate
            watermark: str | None = None
            if results:
                raw_date = results[-1].get("CreationDate", "")
                watermark = self._parse_sap_date(raw_date) or None

            return {
                "items": results,
                "next_cursor": next_cursor,
                "watermark": watermark,
            }

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch a single sales order by ID.

        Args:
            order_id: SAP Sales Order number.

        Returns:
            Order dict or None if not found.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}/SalesOrderSet('{order_id}')",
                    auth=self._auth,
                    headers=self._headers,
                    params={"$format": "json", "$expand": "to_Item"},
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json().get("d", {})
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"SAP OData error fetching order {order_id}: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def update_tracking(
        self,
        order_id: str,
        tracking_numbers: list[str],
        carrier: str = "UPS",
        tracking_url: str | None = None,
    ) -> dict[str, Any]:
        """Write tracking information to SAP delivery document.

        Uses CSRF token for write operations as required by SAP OData.

        Args:
            order_id: SAP Sales Order / Delivery ID.
            tracking_numbers: List of tracking numbers.
            carrier: Carrier name (default: "UPS").
            tracking_url: Optional tracking URL.

        Returns:
            Dict with success status.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch CSRF token (required for SAP write operations)
            csrf_token = await self._fetch_csrf_token(client)
            if not csrf_token:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message="Failed to fetch CSRF token for SAP write operation",
                )

            tracking_number = tracking_numbers[0] if tracking_numbers else ""

            payload: dict[str, Any] = {
                "TrackingNumber": tracking_number,
                "Carrier": carrier,
            }
            if tracking_url:
                payload["TrackingURL"] = tracking_url

            headers = {
                **self._headers,
                "X-CSRF-Token": csrf_token,
                "Content-Type": "application/json",
            }

            try:
                resp = await client.patch(
                    f"{self._base_url}/DeliverySet('{order_id}')",
                    auth=self._auth,
                    headers=headers,
                    json=payload,
                )
                if resp.status_code in (200, 204):
                    return {"success": True}

                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Failed to update tracking for order {order_id}: HTTP {resp.status_code}",
                    provider_status=resp.status_code,
                )
            except httpx.HTTPStatusError as e:
                raise PlatformError(
                    error_code=PlatformErrorCode.UPSTREAM_ERROR,
                    message=f"Failed to update tracking: {e.response.status_code}",
                    provider_status=e.response.status_code,
                )

    async def close(self) -> None:
        """Clean up resources. No persistent client to close."""
        logger.info("SAP client closed")

    async def _fetch_csrf_token(self, client: httpx.AsyncClient) -> str | None:
        """Fetch CSRF token for write operations.

        SAP OData services require a CSRF token for POST/PATCH/DELETE.

        Args:
            client: Active httpx async client.

        Returns:
            CSRF token string or None if fetch failed.
        """
        try:
            resp = await client.get(
                f"{self._base_url}/$metadata",
                auth=self._auth,
                headers={**self._headers, "x-csrf-token": "Fetch"},
            )
            if resp.status_code == 200:
                return resp.headers.get("x-csrf-token")

            logger.warning("Failed to fetch CSRF token: HTTP %d", resp.status_code)
            return None
        except httpx.HTTPError as e:
            logger.error("HTTP error fetching CSRF token: %s", e)
            return None

    @staticmethod
    def _build_date_filter(since: str | None) -> str:
        """Build OData $filter for incremental sync.

        Args:
            since: ISO datetime string for CreationDate filter.

        Returns:
            OData filter expression string, or empty string if no filter needed.
        """
        if not since:
            return ""
        # Escape single quotes to prevent OData filter injection (CWE-943)
        safe_since = since.replace("'", "''")
        return f"CreationDate ge datetime'{safe_since}'"

    @staticmethod
    def _parse_sap_date(sap_date: str) -> str:
        """Parse SAP OData date format to ISO format.

        SAP returns dates as /Date(milliseconds)/ format.

        Args:
            sap_date: Date string in SAP format.

        Returns:
            ISO 8601 formatted date string, or empty string on failure.
        """
        if not sap_date:
            return ""

        # Match /Date(milliseconds)/ pattern
        match = re.match(r"/Date\((\d+)\)/", sap_date)
        if not match:
            # Already ISO or other format — return as-is
            return sap_date

        try:
            milliseconds = int(match.group(1))
            dt = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
            return dt.isoformat()
        except (ValueError, OSError):
            return ""
