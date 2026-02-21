"""Test EDI data models."""


from src.mcp.data_source.edi.models import (
    EDIFormat,
    EDILineItem,
    EDITransactionType,
    NormalizedOrder,
)


def test_edi_format_enum():
    """Test EDI format detection."""
    assert EDIFormat.X12.value == "x12"
    assert EDIFormat.EDIFACT.value == "edifact"


def test_edi_transaction_type_enum():
    """Test transaction type values."""
    assert EDITransactionType.X12_850.value == "850"
    assert EDITransactionType.X12_856.value == "856"
    assert EDITransactionType.X12_810.value == "810"
    assert EDITransactionType.EDIFACT_ORDERS.value == "ORDERS"
    assert EDITransactionType.EDIFACT_DESADV.value == "DESADV"
    assert EDITransactionType.EDIFACT_INVOIC.value == "INVOIC"


def test_edi_line_item_model():
    """Test line item model."""
    item = EDILineItem(
        line_number=1,
        product_id="SKU-123",
        description="Widget",
        quantity=10,
        unit_price_cents=1500,
        weight_lbs=2.5,
    )
    assert item.line_number == 1
    assert item.quantity == 10
    assert item.weight_lbs == 2.5


def test_normalized_order_model():
    """Test normalized order model."""
    order = NormalizedOrder(
        po_number="PO-12345",
        recipient_name="John Doe",
        recipient_company="Acme Corp",
        address_line1="123 Main St",
        city="Springfield",
        state="IL",
        postal_code="62701",
        country="US",
        items=[
            EDILineItem(
                line_number=1,
                product_id="SKU-001",
                quantity=5,
            )
        ],
    )
    assert order.po_number == "PO-12345"
    assert len(order.items) == 1
