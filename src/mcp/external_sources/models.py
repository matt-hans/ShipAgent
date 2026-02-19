"""Models for External Sources Gateway MCP."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlatformType(str, Enum):
    """Supported external platforms."""

    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"
    SAP = "sap"
    ORACLE = "oracle"


class ConnectionStatus(str, Enum):
    """Platform connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    AUTHENTICATING = "authenticating"


class PlatformConnection(BaseModel):
    """Represents a connection to an external platform."""

    platform: str = Field(..., description="Platform identifier")
    store_url: str | None = Field(None, description="Store/instance URL")
    status: str = Field(default="disconnected", description="Connection status")
    last_connected: str | None = Field(None, description="ISO timestamp of last connection")
    error_message: str | None = Field(None, description="Error message if status is error")


class OrderFilters(BaseModel):
    """Filters for fetching orders from external platforms."""

    status: str | None = Field(None, description="Order status filter")
    date_from: str | None = Field(None, description="Start date (ISO format)")
    date_to: str | None = Field(None, description="End date (ISO format)")
    limit: int = Field(default=100, ge=1, le=1000, description="Max orders to fetch")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class ExternalOrder(BaseModel):
    """Order from external platform, normalized format."""

    platform: str = Field(..., description="Source platform")
    order_id: str = Field(..., description="Platform order ID")
    order_number: str | None = Field(None, description="Human-readable order number")
    status: str = Field(..., description="Order status")
    created_at: str = Field(..., description="Order creation timestamp")

    # Customer info
    customer_name: str = Field(..., description="Customer name")
    customer_email: str | None = Field(None, description="Customer email")

    # Shipping address
    ship_to_name: str = Field(..., description="Recipient name")
    ship_to_company: str | None = Field(None, description="Company name")
    ship_to_address1: str = Field(..., description="Address line 1")
    ship_to_address2: str | None = Field(None, description="Address line 2")
    ship_to_city: str = Field(..., description="City")
    ship_to_state: str = Field(..., description="State/province")
    ship_to_postal_code: str = Field(..., description="Postal code")
    ship_to_country: str = Field(default="US", description="Country code")
    ship_to_phone: str | None = Field(None, description="Phone number")

    # Financials
    total_price: str | None = Field(None, description="Order total price as decimal string (e.g. '149.99')")

    # Status breakdown (standalone, in addition to composite 'status' field)
    financial_status: str | None = Field(None, description="Financial status (e.g. 'paid', 'pending', 'refunded')")
    fulfillment_status: str | None = Field(None, description="Fulfillment status (e.g. 'unfulfilled', 'fulfilled', 'partial')")

    # Tags
    tags: str | None = Field(None, description="Comma-separated tags (e.g. 'VIP, wholesale, priority')")

    # Weight & dimensions
    total_weight_grams: float | None = Field(None, description="Total order weight in grams (sum of line item weights)")

    # Shipping
    shipping_method: str | None = Field(None, description="Selected shipping method (e.g. 'Standard Shipping', 'Express')")

    # Item count
    item_count: int | None = Field(None, description="Total number of items (sum of line item quantities)")

    # Customer enrichment (enables VIP routing, customer-tier filtering)
    customer_tags: str | None = Field(None, description="Customer tags (comma-separated)")
    customer_order_count: int | None = Field(None, description="Customer historical order count")
    customer_total_spent: str | None = Field(None, description="Customer lifetime spend as decimal string")

    # Order enrichment (enables note-based routing, risk filtering)
    order_note: str | None = Field(None, description="Order note from customer/merchant")
    risk_level: str | None = Field(None, description="Platform risk assessment (LOW/MEDIUM/HIGH)")

    # Shipping enrichment (enables rate-code-based routing)
    shipping_rate_code: str | None = Field(None, description="Checkout-selected shipping rate code")

    # Product enrichment
    line_item_types: str | None = Field(None, description="Distinct product types (comma-separated)")
    discount_codes: str | None = Field(None, description="Applied discount codes (comma-separated)")

    # Arbitrary extensibility
    custom_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Platform-specific custom fields for filtering (e.g., note_attributes)",
    )

    # Items
    items: list[dict[str, Any]] = Field(default_factory=list, description="Order line items")

    # Raw data for reference
    raw_data: dict[str, Any] | None = Field(None, description="Original platform data")


class TrackingUpdate(BaseModel):
    """Tracking information to write back to platform."""

    order_id: str = Field(..., description="Platform order ID")
    tracking_number: str = Field(..., description="Carrier tracking number")
    carrier: str = Field(default="UPS", description="Carrier name")
    tracking_url: str | None = Field(None, description="Tracking URL")
