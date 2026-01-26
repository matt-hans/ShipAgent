"""EDI data models for parsing and normalization.

Supports:
- X12: 850 (PO), 856 (ASN), 810 (Invoice)
- EDIFACT: ORDERS, DESADV, INVOIC

All formats normalize to a common shipping-relevant schema.
"""

from enum import Enum

from pydantic import BaseModel, Field


class EDIFormat(str, Enum):
    """EDI standard format."""

    X12 = "x12"
    EDIFACT = "edifact"


class EDITransactionType(str, Enum):
    """Supported EDI transaction types."""

    # X12 transactions
    X12_850 = "850"  # Purchase Order
    X12_856 = "856"  # ASN (Advance Ship Notice)
    X12_810 = "810"  # Invoice

    # EDIFACT transactions
    EDIFACT_ORDERS = "ORDERS"  # Purchase Order
    EDIFACT_DESADV = "DESADV"  # Dispatch Advice (ASN equivalent)
    EDIFACT_INVOIC = "INVOIC"  # Invoice


class EDILineItem(BaseModel):
    """A line item within an EDI document."""

    line_number: int = Field(..., ge=1, description="Line item sequence number")
    product_id: str | None = Field(None, description="SKU or product identifier")
    description: str | None = Field(None, description="Item description")
    quantity: int = Field(default=1, ge=1, description="Ordered quantity")
    unit_price_cents: int | None = Field(None, description="Unit price in cents")
    weight_lbs: float | None = Field(None, description="Item weight in pounds")
    upc: str | None = Field(None, description="UPC barcode")


class EDIDocument(BaseModel):
    """Parsed EDI document metadata."""

    format: EDIFormat = Field(..., description="X12 or EDIFACT")
    transaction_type: EDITransactionType = Field(..., description="Transaction type")
    sender_id: str | None = Field(None, description="Sender identification")
    receiver_id: str | None = Field(None, description="Receiver identification")
    control_number: str | None = Field(None, description="Interchange control number")
    raw_content: str | None = Field(None, description="Original EDI content")


class NormalizedOrder(BaseModel):
    """Normalized order data from any EDI format.

    This is the common schema that all EDI formats normalize to,
    containing shipping-relevant fields for ShipAgent processing.
    """

    # Order identification
    po_number: str = Field(..., description="Purchase order number")
    reference_number: str | None = Field(None, description="Additional reference")

    # Recipient info
    recipient_name: str = Field(..., description="Ship-to contact name")
    recipient_company: str | None = Field(None, description="Ship-to company")
    recipient_phone: str | None = Field(None, description="Contact phone")
    recipient_email: str | None = Field(None, description="Contact email")

    # Ship-to address
    address_line1: str = Field(..., description="Street address line 1")
    address_line2: str | None = Field(None, description="Street address line 2")
    city: str = Field(..., description="City")
    state: str = Field(..., description="State/province code")
    postal_code: str = Field(..., description="ZIP/postal code")
    country: str = Field(default="US", description="Country code")

    # Items
    items: list[EDILineItem] = Field(
        default_factory=list, description="Line items in order"
    )

    # Metadata from source document
    source_document: EDIDocument | None = Field(
        None, description="Original EDI document metadata"
    )
