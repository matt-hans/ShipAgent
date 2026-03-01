"""Abstract base class for platform clients.

Each platform (Shopify, WooCommerce, SAP, Oracle) implements
this interface to provide consistent order access.
"""

from abc import ABC, abstractmethod

from src.mcp.external_sources.models import (
    ExternalOrder,
    OrderFilters,
    TrackingUpdate,
)


class PlatformClient(ABC):
    """Abstract base class for external platform clients.

    Concrete implementations must handle:
    - Authentication with the platform
    - Fetching orders with filtering
    - Updating tracking information

    Example implementation:
        class ShopifyClient(PlatformClient):
            @property
            def platform_name(self) -> str:
                return "shopify"

            async def authenticate(self, credentials: dict) -> bool:
                # Connect to Shopify Admin API
                ...
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier.

        Returns:
            Platform name: 'shopify', 'woocommerce', 'sap', 'oracle'
        """
        ...

    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool:
        """Authenticate with the platform.

        Args:
            credentials: Platform-specific credentials
                - Shopify: {"store_url": str, "access_token": str}
                - WooCommerce: {"site_url": str, "consumer_key": str, "consumer_secret": str}
                - SAP: {"base_url": str, "username": str, "password": str, "client": str}
                - Oracle: {"connection_string": str} or OCI profile

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If credentials invalid
        """
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test that the connection is still valid.

        Returns:
            True if connection is healthy
        """
        ...

    @abstractmethod
    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        """Fetch orders from the platform.

        Args:
            filters: Order filtering criteria (status, date range, limit)

        Returns:
            List of orders in normalized format
        """
        ...

    @abstractmethod
    async def get_order(self, order_id: str) -> ExternalOrder | None:
        """Get a single order by ID.

        Args:
            order_id: Platform-specific order identifier

        Returns:
            Order if found, None otherwise
        """
        ...

    @abstractmethod
    async def update_tracking(self, update: TrackingUpdate) -> bool:
        """Write tracking information back to the platform.

        Args:
            update: Tracking number and carrier info

        Returns:
            True if update successful

        Raises:
            WriteBackError: If platform rejects the update
        """
        ...
