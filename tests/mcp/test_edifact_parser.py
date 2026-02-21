"""Test EDIFACT EDI parser."""

from pathlib import Path

import pytest

from src.mcp.data_source.edi.edifact_parser import EDIFACTParser
from src.mcp.data_source.edi.models import EDIFormat, EDITransactionType


@pytest.fixture
def sample_orders_path():
    """Path to sample EDIFACT ORDERS file."""
    return Path(__file__).parent.parent / "fixtures" / "edi" / "sample_orders.edi"


@pytest.fixture
def sample_orders_content(sample_orders_path):
    """Content of sample EDIFACT ORDERS file."""
    return sample_orders_path.read_text()


def test_detect_format_edifact(sample_orders_content):
    """Test EDIFACT format detection."""
    parser = EDIFACTParser()
    assert parser.detect_format(sample_orders_content) == EDIFormat.EDIFACT


def test_detect_transaction_type_orders(sample_orders_content):
    """Test ORDERS transaction type detection."""
    parser = EDIFACTParser()
    assert parser.detect_transaction_type(sample_orders_content) == EDITransactionType.EDIFACT_ORDERS


def test_parse_orders_basic(sample_orders_content):
    """Test parsing EDIFACT ORDERS."""
    parser = EDIFACTParser()
    orders = parser.parse(sample_orders_content)

    assert len(orders) == 1
    order = orders[0]

    # Check order identification
    assert order.po_number == "ORDER-001"

    # Check recipient
    assert order.recipient_name == "John Smith"
    assert order.address_line1 == "123 Oak Avenue"
    assert order.city == "Chicago"
    assert order.state == "IL"
    assert order.postal_code == "60601"
    assert order.country == "US"

    # Check items
    assert len(order.items) == 2
    assert order.items[0].product_id == "SKU-100"
    assert order.items[0].quantity == 10
    assert order.items[0].unit_price_cents == 2500
    assert order.items[1].product_id == "SKU-200"
    assert order.items[1].quantity == 5


def test_parse_invalid_content():
    """Test error handling for invalid EDIFACT."""
    parser = EDIFACTParser()
    with pytest.raises(ValueError, match="Not EDIFACT format"):
        parser.parse("This is not EDI content")
