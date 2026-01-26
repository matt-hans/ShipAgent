"""SAP platform client for External Sources Gateway.

Implements the PlatformClient interface for SAP S/4HANA and ECC systems
using OData services for sales order access and delivery updates.
"""

import logging
import re
from datetime import UTC, datetime

import httpx

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)

logger = logging.getLogger(__name__)


class SAPClient(PlatformClient):
    """SAP OData client for order management.

    Connects to SAP systems via OData services to:
    - Fetch sales orders with filtering
    - Update delivery documents with tracking information

    Example usage:
        client = SAPClient()
        await client.authenticate({
            "base_url": "https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
            "username": "user",
            "password": "pass",
            "client": "100"
        })
        orders = await client.fetch_orders(OrderFilters(limit=10))
    """

    def __init__(self):
        """Initialize SAP client in disconnected state."""
        self._client: httpx.AsyncClient | None = None
        self._base_url: str | None = None
        self._authenticated: bool = False
        self._sap_client_id: str | None = None

    @property
    def platform_name(self) -> str:
        """Return the platform identifier.

        Returns:
            'sap' as the platform name
        """
        return "sap"

    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate with SAP system using Basic Auth.

        Args:
            credentials: Dictionary containing:
                - base_url: SAP OData service URL
                - username: SAP username
                - password: SAP password
                - client: SAP client ID (e.g., '100')

        Returns:
            True if authentication successful, False otherwise

        Raises:
            ValueError: If required credentials are missing
        """
        required_keys = ["base_url", "username", "password", "client"]
        missing = [k for k in required_keys if k not in credentials or not credentials[k]]
        if missing:
            raise ValueError(f"Missing required credentials: {', '.join(missing)}")

        self._base_url = credentials["base_url"].rstrip("/")
        self._sap_client_id = credentials["client"]

        try:
            self._client = self._create_client(
                username=credentials["username"],
                password=credentials["password"],
                sap_client=credentials["client"],
            )

            # Test connection by fetching metadata
            response = await self._client.get("/$metadata")

            if response.status_code == 200:
                self._authenticated = True
                logger.info("Successfully authenticated with SAP at %s", self._base_url)
                return True
            else:
                logger.warning(
                    "SAP authentication failed with status %d", response.status_code
                )
                self._authenticated = False
                return False

        except httpx.ConnectError as e:
            logger.error("Failed to connect to SAP: %s", e)
            self._authenticated = False
            return False

    def _create_client(
        self, username: str, password: str, sap_client: str
    ) -> httpx.AsyncClient:
        """Create configured httpx async client.

        Args:
            username: SAP username for Basic Auth
            password: SAP password for Basic Auth
            sap_client: SAP client ID

        Returns:
            Configured httpx.AsyncClient
        """
        if not self._base_url:
            raise RuntimeError("Base URL not configured")
        return httpx.AsyncClient(
            base_url=self._base_url,
            auth=(username, password),
            headers={
                "sap-client": sap_client,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def test_connection(self) -> bool:
        """Test that the connection is still valid.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self._authenticated or not self._client:
            return False

        try:
            response = await self._client.get("/$metadata")
            return response.status_code == 200
        except httpx.HTTPError as e:
            logger.error("SAP connection test failed: %s", e)
            return False

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        """Fetch orders from SAP using OData query.

        Args:
            filters: Order filtering criteria (status, date range, limit, offset)

        Returns:
            List of orders in normalized ExternalOrder format

        Raises:
            RuntimeError: If not authenticated
        """
        if not self._authenticated or not self._client:
            raise RuntimeError("Not authenticated with SAP")

        # Build OData query parameters
        params: dict[str, str] = {
            "$format": "json",
            "$top": str(filters.limit),
            "$skip": str(filters.offset),
            "$expand": "to_Item",
        }

        # Add filter conditions
        odata_filter = self._build_odata_filter(filters)
        if odata_filter:
            params["$filter"] = odata_filter

        try:
            response = await self._client.get("/SalesOrderSet", params=params)

            if response.status_code != 200:
                logger.error("Failed to fetch orders: HTTP %d", response.status_code)
                return []

            data = response.json()
            results = data.get("d", {}).get("results", [])

            orders = []
            for order_data in results:
                order = self._map_to_external_order(order_data)
                if order:
                    orders.append(order)

            logger.info("Fetched %d orders from SAP", len(orders))
            return orders

        except httpx.HTTPError as e:
            logger.error("HTTP error fetching orders: %s", e)
            return []

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        """Get a single order by ID.

        Args:
            order_id: SAP Sales Order number

        Returns:
            Order if found, None otherwise

        Raises:
            RuntimeError: If not authenticated
        """
        if not self._authenticated or not self._client:
            raise RuntimeError("Not authenticated with SAP")

        try:
            # OData single entity access pattern
            url = f"/SalesOrderSet('{order_id}')"
            params = {
                "$format": "json",
                "$expand": "to_Item",
            }

            response = await self._client.get(url, params=params)

            if response.status_code == 404:
                logger.info("Order %s not found in SAP", order_id)
                return None

            if response.status_code != 200:
                logger.error(
                    "Failed to get order %s: HTTP %d", order_id, response.status_code
                )
                return None

            data = response.json()
            order_data = data.get("d", {})

            return self._map_to_external_order(order_data)

        except httpx.HTTPError as e:
            logger.error("HTTP error getting order %s: %s", order_id, e)
            return None

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Write tracking information to SAP delivery document.

        Uses CSRF token for write operations as required by SAP OData.

        Args:
            update: Tracking information to write

        Returns:
            True if update successful, False otherwise

        Raises:
            RuntimeError: If not authenticated
        """
        if not self._authenticated or not self._client:
            raise RuntimeError("Not authenticated with SAP")

        try:
            # Fetch CSRF token (required for SAP write operations)
            csrf_token = await self._fetch_csrf_token()
            if not csrf_token:
                logger.error("Failed to fetch CSRF token")
                return False

            # Update delivery with tracking information
            # SAP typically stores tracking on delivery documents
            delivery_id = update.order_id  # May need mapping in real implementation
            url = f"/DeliverySet('{delivery_id}')"

            payload = {
                "TrackingNumber": update.tracking_number,
                "Carrier": update.carrier,
            }
            if update.tracking_url:
                payload["TrackingURL"] = update.tracking_url

            headers = {
                "X-CSRF-Token": csrf_token,
                "Content-Type": "application/json",
            }

            response = await self._client.patch(url, json=payload, headers=headers)

            if response.status_code in (200, 204):
                logger.info(
                    "Updated tracking for delivery %s: %s",
                    delivery_id,
                    update.tracking_number,
                )
                return True
            else:
                logger.error(
                    "Failed to update tracking: HTTP %d", response.status_code
                )
                return False

        except httpx.HTTPError as e:
            logger.error("HTTP error updating tracking: %s", e)
            return False

    async def _fetch_csrf_token(self) -> str | None:
        """Fetch CSRF token for write operations.

        SAP OData services require a CSRF token for POST/PATCH/DELETE.

        Returns:
            CSRF token string or None if fetch failed
        """
        if not self._client:
            return None
        try:
            response = await self._client.get(
                "/$metadata",
                headers={"x-csrf-token": "Fetch"},
            )

            if response.status_code == 200:
                return response.headers.get("x-csrf-token")

            logger.warning("Failed to fetch CSRF token: HTTP %d", response.status_code)
            return None

        except httpx.HTTPError as e:
            logger.error("HTTP error fetching CSRF token: %s", e)
            return None

    def _build_odata_filter(self, filters: OrderFilters) -> str:
        """Build OData $filter query string.

        Args:
            filters: Order filtering criteria

        Returns:
            OData filter expression string
        """
        conditions = []

        if filters.status:
            conditions.append(f"OverallSDProcessStatus eq '{filters.status}'")

        if filters.date_from:
            # Convert ISO date to OData datetime format
            conditions.append(f"CreationDate ge datetime'{filters.date_from}T00:00:00'")

        if filters.date_to:
            conditions.append(f"CreationDate le datetime'{filters.date_to}T23:59:59'")

        return " and ".join(conditions)

    def _parse_sap_date(self, sap_date: str) -> str:
        """Parse SAP OData date format to ISO format.

        SAP returns dates as /Date(milliseconds)/ format.

        Args:
            sap_date: Date string in SAP format

        Returns:
            ISO 8601 formatted date string
        """
        if not sap_date:
            return ""

        # Match /Date(milliseconds)/ pattern
        match = re.match(r"/Date\((\d+)\)/", sap_date)
        if not match:
            return ""

        try:
            milliseconds = int(match.group(1))
            dt = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
            return dt.isoformat()
        except (ValueError, OSError):
            return ""

    def _map_to_external_order(self, order_data: dict) -> ExternalOrder | None:
        """Map SAP order data to ExternalOrder model.

        Args:
            order_data: Raw SAP order dictionary

        Returns:
            Normalized ExternalOrder or None if mapping fails
        """
        if not order_data:
            return None

        try:
            # Extract items from nested structure
            items = []
            to_item = order_data.get("to_Item", {})
            if isinstance(to_item, dict):
                items = to_item.get("results", [])

            return ExternalOrder(
                platform="sap",
                order_id=order_data.get("SalesOrder", ""),
                order_number=order_data.get("SalesOrder"),
                status=order_data.get("OverallSDProcessStatus", ""),
                created_at=self._parse_sap_date(order_data.get("CreationDate", "")),
                customer_name=order_data.get("CustomerName", ""),
                customer_email=order_data.get("CustomerEmail"),
                ship_to_name=order_data.get("ShipToName", ""),
                ship_to_company=order_data.get("ShipToCompany"),
                ship_to_address1=order_data.get("ShipToStreet", ""),
                ship_to_address2=order_data.get("ShipToStreet2"),
                ship_to_city=order_data.get("ShipToCity", ""),
                ship_to_state=order_data.get("ShipToRegion", ""),
                ship_to_postal_code=order_data.get("ShipToPostalCode", ""),
                ship_to_country=order_data.get("ShipToCountry", "US"),
                ship_to_phone=order_data.get("ShipToPhone"),
                items=items,
                raw_data=order_data,
            )
        except Exception as e:
            logger.error("Failed to map SAP order: %s", e)
            return None

    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

        self._authenticated = False
        logger.info("SAP client closed")

    async def __aenter__(self) -> "SAPClient":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and clean up."""
        await self.close()
