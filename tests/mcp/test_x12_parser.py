"""Test X12 EDI parser."""

from pathlib import Path

import pytest

from src.mcp.data_source.edi.models import EDIFormat, EDITransactionType
from src.mcp.data_source.edi.x12_parser import X12Parser


@pytest.fixture
def sample_850_path():
    """Path to sample X12 850 file."""
    return Path(__file__).parent.parent / "fixtures" / "edi" / "sample_850.edi"


@pytest.fixture
def sample_850_content(sample_850_path):
    """Content of sample X12 850 file."""
    return sample_850_path.read_text()


def test_detect_format_x12(sample_850_content):
    """Test X12 format detection."""
    parser = X12Parser()
    assert parser.detect_format(sample_850_content) == EDIFormat.X12


def test_detect_transaction_type_850(sample_850_content):
    """Test 850 transaction type detection."""
    parser = X12Parser()
    assert parser.detect_transaction_type(sample_850_content) == EDITransactionType.X12_850


def test_parse_850_basic(sample_850_content):
    """Test parsing X12 850 purchase order."""
    parser = X12Parser()
    orders = parser.parse(sample_850_content)

    assert len(orders) == 1
    order = orders[0]

    # Check order identification
    assert order.po_number == "PO-12345"

    # Check recipient
    assert order.recipient_name == "John Doe"
    assert order.address_line1 == "123 Main Street"
    assert order.city == "Springfield"
    assert order.state == "IL"
    assert order.postal_code == "62701"
    assert order.country == "US"

    # Check items
    assert len(order.items) == 2
    assert order.items[0].product_id == "SKU-001"
    assert order.items[0].quantity == 5
    assert order.items[0].unit_price_cents == 1500
    assert order.items[1].product_id == "SKU-002"
    assert order.items[1].quantity == 3


def test_parse_invalid_content():
    """Test error handling for invalid EDI."""
    parser = X12Parser()
    with pytest.raises(ValueError, match="Not X12 format"):
        parser.parse("This is not EDI content")


def test_parse_unsupported_transaction():
    """Test error handling for unsupported transaction type."""
    parser = X12Parser()
    # 997 is Functional Acknowledgment, not supported
    content = "ISA*00*          *00*          *ZZ*SENDER*ZZ*RECEIVER*260126*1200*U*00401*1*0*P*>~GS*FA*SENDER*RECEIVER*20260126*1200*1*X*004010~ST*997*0001~"
    with pytest.raises(ValueError, match="Unsupported.*997"):
        parser.parse(content)
