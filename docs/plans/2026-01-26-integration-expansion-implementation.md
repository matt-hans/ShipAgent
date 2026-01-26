# Integration Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add EDI adapter and External Sources Gateway MCP to support ~90% of UPS customers.

**Architecture:** EDI adapter extends `BaseSourceAdapter` pattern (like CSV/Excel). External Sources Gateway is a new FastMCP server that acts as client to external platform MCPs (Shopify, WooCommerce, SAP, Oracle).

**Tech Stack:** Python 3.11+, FastMCP, DuckDB, pyx12 (X12 parser), pydifact (EDIFACT parser), httpx (async HTTP)

---

## Phase 1: EDI Adapter

### Task 1.1: Add EDI Parser Dependencies

**Files:**
- Modify: `pyproject.toml:11-30`

**Step 1: Add pyx12 and pydifact to dependencies**

Edit `pyproject.toml` to add EDI parser libraries:

```toml
dependencies = [
    "sqlalchemy>=2.0",
    "aiosqlite>=0.19.0",
    "pydantic>=2.0",
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
    # Data Source MCP dependencies
    "fastmcp<3",
    "duckdb>=1.3.0",
    "openpyxl>=3.1.0",
    "python-dateutil>=2.9.0",
    # EDI parser dependencies
    "pydifact>=0.1.8",
    # NL Engine dependencies
    "sqlglot>=26.0.0",
    "anthropic>=0.42.0",
    "jsonschema>=4.0.0",
    "jinja2>=3.0.0",
    # Web interface dependencies
    "sse-starlette>=2.0.0",
    "zipstream-ng>=1.7.0",
]
```

Note: pyx12 requires separate installation due to its dependencies. We'll use a simpler X12 parser approach.

**Step 2: Install updated dependencies**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pip install -e ".[dev]"`

Expected: Successfully installed pydifact

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat(edi): add pydifact dependency for EDIFACT parsing"
```

---

### Task 1.2: Create EDI Models

**Files:**
- Create: `src/mcp/data_source/edi/__init__.py`
- Create: `src/mcp/data_source/edi/models.py`

**Step 1: Write the test for EDI models**

Create `tests/mcp/test_edi_models.py`:

```python
"""Test EDI data models."""

import pytest

from src.mcp.data_source.edi.models import (
    EDIFormat,
    EDITransactionType,
    EDIDocument,
    EDILineItem,
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edi_models.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.mcp.data_source.edi'"

**Step 3: Create the edi package**

Create `src/mcp/data_source/edi/__init__.py`:

```python
"""EDI parsing module for X12 and EDIFACT formats."""
```

**Step 4: Write the models implementation**

Create `src/mcp/data_source/edi/models.py`:

```python
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
```

**Step 5: Run test to verify it passes**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edi_models.py -v`

Expected: PASS (all 4 tests)

**Step 6: Commit**

```bash
git add src/mcp/data_source/edi/ tests/mcp/test_edi_models.py
git commit -m "feat(edi): add EDI data models for X12 and EDIFACT"
```

---

### Task 1.3: Create X12 Parser

**Files:**
- Create: `src/mcp/data_source/edi/x12_parser.py`
- Create: `tests/mcp/test_x12_parser.py`
- Create: `tests/fixtures/edi/sample_850.edi`

**Step 1: Create sample X12 850 fixture**

Create `tests/fixtures/edi/sample_850.edi`:

```
ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *260126*1200*U*00401*000000001*0*P*>~
GS*PO*SENDER*RECEIVER*20260126*1200*1*X*004010~
ST*850*0001~
BEG*00*NE*PO-12345**20260126~
N1*ST*John Doe*92*SHIP001~
N3*123 Main Street~
N4*Springfield*IL*62701*US~
PO1*1*5*EA*1500**UP*012345678901*VP*SKU-001~
PID*F****Widget Blue~
PO1*2*3*EA*2500**UP*012345678902*VP*SKU-002~
PID*F****Gadget Red~
CTT*2~
SE*11*0001~
GE*1*1~
IEA*1*000000001~
```

**Step 2: Write failing test for X12 parser**

Create `tests/mcp/test_x12_parser.py`:

```python
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
    with pytest.raises(ValueError, match="Invalid X12"):
        parser.parse("This is not EDI content")


def test_parse_unsupported_transaction():
    """Test error handling for unsupported transaction type."""
    parser = X12Parser()
    # 997 is Functional Acknowledgment, not supported
    content = "ISA*00*          *00*          *ZZ*SENDER*ZZ*RECEIVER*260126*1200*U*00401*1*0*P*>~GS*FA*SENDER*RECEIVER*20260126*1200*1*X*004010~ST*997*0001~"
    with pytest.raises(ValueError, match="Unsupported.*997"):
        parser.parse(content)
```

**Step 3: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_x12_parser.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.mcp.data_source.edi.x12_parser'"

**Step 4: Implement X12 parser**

Create `src/mcp/data_source/edi/x12_parser.py`:

```python
"""X12 EDI parser for 850 (PO), 856 (ASN), and 810 (Invoice).

Parses X12 EDI documents and normalizes to common order schema.
Uses simple regex-based parsing rather than full X12 library
for lighter dependency footprint.
"""

import re
from typing import Iterator

from src.mcp.data_source.edi.models import (
    EDIDocument,
    EDIFormat,
    EDILineItem,
    EDITransactionType,
    NormalizedOrder,
)


class X12Parser:
    """Parser for X12 EDI documents.

    Supports:
    - 850: Purchase Order
    - 856: Advance Ship Notice
    - 810: Invoice
    """

    # Segment terminators (common ones)
    SEGMENT_TERMINATORS = ["~", "\n"]

    # Supported transaction types
    SUPPORTED_TYPES = {"850", "856", "810"}

    def detect_format(self, content: str) -> EDIFormat:
        """Detect if content is X12 format.

        Args:
            content: Raw EDI file content

        Returns:
            EDIFormat.X12 if valid X12 format

        Raises:
            ValueError: If not X12 format
        """
        if content.strip().startswith("ISA"):
            return EDIFormat.X12
        raise ValueError("Not X12 format: must start with ISA segment")

    def detect_transaction_type(self, content: str) -> EDITransactionType:
        """Detect the transaction type from X12 content.

        Args:
            content: Raw X12 EDI content

        Returns:
            EDITransactionType enum value

        Raises:
            ValueError: If transaction type not found or unsupported
        """
        # Find ST segment which contains transaction type
        st_match = re.search(r"ST\*(\d{3})\*", content)
        if not st_match:
            raise ValueError("Invalid X12: ST segment not found")

        tx_type = st_match.group(1)
        if tx_type == "850":
            return EDITransactionType.X12_850
        elif tx_type == "856":
            return EDITransactionType.X12_856
        elif tx_type == "810":
            return EDITransactionType.X12_810
        else:
            raise ValueError(f"Unsupported X12 transaction type: {tx_type}")

    def parse(self, content: str) -> list[NormalizedOrder]:
        """Parse X12 content into normalized orders.

        Args:
            content: Raw X12 EDI file content

        Returns:
            List of NormalizedOrder objects

        Raises:
            ValueError: If content is invalid or unsupported
        """
        # Validate format
        self.detect_format(content)
        tx_type = self.detect_transaction_type(content)

        # Parse based on transaction type
        if tx_type == EDITransactionType.X12_850:
            return self._parse_850(content)
        elif tx_type == EDITransactionType.X12_856:
            return self._parse_856(content)
        elif tx_type == EDITransactionType.X12_810:
            return self._parse_810(content)
        else:
            raise ValueError(f"Unsupported transaction type: {tx_type}")

    def _split_segments(self, content: str) -> list[str]:
        """Split X12 content into segments."""
        # Detect segment terminator from ISA
        # ISA is fixed length, terminator is at position 105
        if len(content) >= 106:
            terminator = content[105]
        else:
            terminator = "~"

        segments = content.split(terminator)
        return [s.strip() for s in segments if s.strip()]

    def _parse_segment(self, segment: str) -> tuple[str, list[str]]:
        """Parse a segment into ID and elements."""
        # Detect element separator (usually * but can vary)
        if "*" in segment:
            sep = "*"
        elif "^" in segment:
            sep = "^"
        else:
            sep = "*"

        parts = segment.split(sep)
        return parts[0], parts[1:] if len(parts) > 1 else []

    def _parse_850(self, content: str) -> list[NormalizedOrder]:
        """Parse X12 850 Purchase Order."""
        segments = self._split_segments(content)
        orders: list[NormalizedOrder] = []

        # State for current order being parsed
        current_order: dict = {}
        current_items: list[EDILineItem] = []
        current_item: dict = {}
        in_ship_to = False

        for segment in segments:
            seg_id, elements = self._parse_segment(segment)

            if seg_id == "BEG":
                # Beginning segment: PO number is element 2 (index 2)
                if len(elements) > 2:
                    current_order["po_number"] = elements[2]

            elif seg_id == "N1":
                # Name segment: check if ship-to (ST)
                if elements and elements[0] == "ST":
                    in_ship_to = True
                    if len(elements) > 1:
                        current_order["recipient_name"] = elements[1]
                else:
                    in_ship_to = False

            elif seg_id == "N3" and in_ship_to:
                # Address line
                if elements:
                    current_order["address_line1"] = elements[0]
                if len(elements) > 1:
                    current_order["address_line2"] = elements[1]

            elif seg_id == "N4" and in_ship_to:
                # City, state, zip, country
                if elements:
                    current_order["city"] = elements[0]
                if len(elements) > 1:
                    current_order["state"] = elements[1]
                if len(elements) > 2:
                    current_order["postal_code"] = elements[2]
                if len(elements) > 3:
                    current_order["country"] = elements[3]

            elif seg_id == "PO1":
                # Line item - save previous item if exists
                if current_item:
                    current_items.append(EDILineItem(**current_item))
                    current_item = {}

                # PO1 elements: line#, qty, unit, price, ..., qualifier, value pairs
                current_item["line_number"] = int(elements[0]) if elements else 1
                if len(elements) > 1:
                    current_item["quantity"] = int(elements[1])
                if len(elements) > 3:
                    try:
                        current_item["unit_price_cents"] = int(float(elements[3]) * 100)
                    except ValueError:
                        pass

                # Parse qualifier/value pairs for product IDs
                i = 5
                while i + 1 < len(elements):
                    qualifier = elements[i]
                    value = elements[i + 1]
                    if qualifier == "VP":  # Vendor Product Number
                        current_item["product_id"] = value
                    elif qualifier == "UP":  # UPC
                        current_item["upc"] = value
                    i += 2

            elif seg_id == "PID":
                # Product description
                if len(elements) > 4:
                    current_item["description"] = elements[4]

            elif seg_id == "SE":
                # End of transaction - save last item and order
                if current_item:
                    current_items.append(EDILineItem(**current_item))

                if current_order.get("po_number"):
                    order = NormalizedOrder(
                        po_number=current_order.get("po_number", ""),
                        recipient_name=current_order.get("recipient_name", "Unknown"),
                        recipient_company=current_order.get("recipient_company"),
                        address_line1=current_order.get("address_line1", ""),
                        address_line2=current_order.get("address_line2"),
                        city=current_order.get("city", ""),
                        state=current_order.get("state", ""),
                        postal_code=current_order.get("postal_code", ""),
                        country=current_order.get("country", "US"),
                        items=current_items,
                        source_document=EDIDocument(
                            format=EDIFormat.X12,
                            transaction_type=EDITransactionType.X12_850,
                        ),
                    )
                    orders.append(order)

                # Reset for next transaction
                current_order = {}
                current_items = []
                current_item = {}

        return orders

    def _parse_856(self, content: str) -> list[NormalizedOrder]:
        """Parse X12 856 ASN (Advance Ship Notice)."""
        # Similar structure to 850 but with shipment-specific segments
        # For now, extract shipping info into normalized format
        segments = self._split_segments(content)
        orders: list[NormalizedOrder] = []

        current_order: dict = {}
        current_items: list[EDILineItem] = []
        in_ship_to = False

        for segment in segments:
            seg_id, elements = self._parse_segment(segment)

            if seg_id == "BSN":
                # Beginning Segment for Ship Notice
                if len(elements) > 1:
                    current_order["reference_number"] = elements[1]

            elif seg_id == "PRF":
                # Purchase Order Reference
                if elements:
                    current_order["po_number"] = elements[0]

            elif seg_id == "N1":
                if elements and elements[0] == "ST":
                    in_ship_to = True
                    if len(elements) > 1:
                        current_order["recipient_name"] = elements[1]
                else:
                    in_ship_to = False

            elif seg_id == "N3" and in_ship_to:
                if elements:
                    current_order["address_line1"] = elements[0]

            elif seg_id == "N4" and in_ship_to:
                if elements:
                    current_order["city"] = elements[0]
                if len(elements) > 1:
                    current_order["state"] = elements[1]
                if len(elements) > 2:
                    current_order["postal_code"] = elements[2]
                if len(elements) > 3:
                    current_order["country"] = elements[3]

            elif seg_id == "SN1":
                # Item detail
                item = EDILineItem(
                    line_number=len(current_items) + 1,
                    quantity=int(elements[1]) if len(elements) > 1 else 1,
                )
                current_items.append(item)

            elif seg_id == "SE":
                if current_order.get("po_number") or current_order.get("reference_number"):
                    order = NormalizedOrder(
                        po_number=current_order.get("po_number", current_order.get("reference_number", "")),
                        reference_number=current_order.get("reference_number"),
                        recipient_name=current_order.get("recipient_name", "Unknown"),
                        address_line1=current_order.get("address_line1", ""),
                        city=current_order.get("city", ""),
                        state=current_order.get("state", ""),
                        postal_code=current_order.get("postal_code", ""),
                        country=current_order.get("country", "US"),
                        items=current_items,
                        source_document=EDIDocument(
                            format=EDIFormat.X12,
                            transaction_type=EDITransactionType.X12_856,
                        ),
                    )
                    orders.append(order)

                current_order = {}
                current_items = []

        return orders

    def _parse_810(self, content: str) -> list[NormalizedOrder]:
        """Parse X12 810 Invoice."""
        segments = self._split_segments(content)
        orders: list[NormalizedOrder] = []

        current_order: dict = {}
        current_items: list[EDILineItem] = []
        in_ship_to = False

        for segment in segments:
            seg_id, elements = self._parse_segment(segment)

            if seg_id == "BIG":
                # Beginning Segment for Invoice
                if len(elements) > 1:
                    current_order["reference_number"] = elements[1]
                if len(elements) > 3:
                    current_order["po_number"] = elements[3]

            elif seg_id == "N1":
                if elements and elements[0] == "ST":
                    in_ship_to = True
                    if len(elements) > 1:
                        current_order["recipient_name"] = elements[1]
                else:
                    in_ship_to = False

            elif seg_id == "N3" and in_ship_to:
                if elements:
                    current_order["address_line1"] = elements[0]

            elif seg_id == "N4" and in_ship_to:
                if elements:
                    current_order["city"] = elements[0]
                if len(elements) > 1:
                    current_order["state"] = elements[1]
                if len(elements) > 2:
                    current_order["postal_code"] = elements[2]
                if len(elements) > 3:
                    current_order["country"] = elements[3]

            elif seg_id == "IT1":
                # Invoice line item
                item_data = {"line_number": len(current_items) + 1}
                if len(elements) > 1:
                    item_data["quantity"] = int(elements[1])
                if len(elements) > 3:
                    try:
                        item_data["unit_price_cents"] = int(float(elements[3]) * 100)
                    except ValueError:
                        pass
                current_items.append(EDILineItem(**item_data))

            elif seg_id == "SE":
                if current_order.get("po_number") or current_order.get("reference_number"):
                    order = NormalizedOrder(
                        po_number=current_order.get("po_number", current_order.get("reference_number", "")),
                        reference_number=current_order.get("reference_number"),
                        recipient_name=current_order.get("recipient_name", "Unknown"),
                        address_line1=current_order.get("address_line1", ""),
                        city=current_order.get("city", ""),
                        state=current_order.get("state", ""),
                        postal_code=current_order.get("postal_code", ""),
                        country=current_order.get("country", "US"),
                        items=current_items,
                        source_document=EDIDocument(
                            format=EDIFormat.X12,
                            transaction_type=EDITransactionType.X12_810,
                        ),
                    )
                    orders.append(order)

                current_order = {}
                current_items = []

        return orders
```

**Step 5: Create fixture directory and file**

```bash
mkdir -p tests/fixtures/edi
```

Then create the fixture file as shown in Step 1.

**Step 6: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_x12_parser.py -v`

Expected: PASS (all 5 tests)

**Step 7: Commit**

```bash
git add src/mcp/data_source/edi/x12_parser.py tests/mcp/test_x12_parser.py tests/fixtures/edi/
git commit -m "feat(edi): add X12 parser for 850, 856, 810 transactions"
```

---

### Task 1.4: Create EDIFACT Parser

**Files:**
- Create: `src/mcp/data_source/edi/edifact_parser.py`
- Create: `tests/mcp/test_edifact_parser.py`
- Create: `tests/fixtures/edi/sample_orders.edi`

**Step 1: Create sample EDIFACT ORDERS fixture**

Create `tests/fixtures/edi/sample_orders.edi`:

```
UNB+UNOC:3+SENDER+RECEIVER+260126:1200+1'
UNH+1+ORDERS:D:96A:UN'
BGM+220+ORDER-001+9'
NAD+BY+++Buyer Company'
NAD+ST+++John Smith+123 Oak Avenue+Chicago+IL+60601+US'
LIN+1++SKU-100:VP'
QTY+21:10'
PRI+AAA:25.00'
LIN+2++SKU-200:VP'
QTY+21:5'
PRI+AAA:50.00'
UNS+S'
UNT+12+1'
UNZ+1+1'
```

**Step 2: Write failing test for EDIFACT parser**

Create `tests/mcp/test_edifact_parser.py`:

```python
"""Test EDIFACT EDI parser."""

from pathlib import Path

import pytest

from src.mcp.data_source.edi.models import EDIFormat, EDITransactionType
from src.mcp.data_source.edi.edifact_parser import EDIFACTParser


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
    with pytest.raises(ValueError, match="Invalid EDIFACT"):
        parser.parse("This is not EDI content")
```

**Step 3: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edifact_parser.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.mcp.data_source.edi.edifact_parser'"

**Step 4: Implement EDIFACT parser**

Create `src/mcp/data_source/edi/edifact_parser.py`:

```python
"""EDIFACT EDI parser for ORDERS, DESADV, and INVOIC.

Parses EDIFACT documents and normalizes to common order schema.
Uses pydifact library for segment parsing.
"""

from pydifact.segments import Segment
from pydifact.parser import Parser

from src.mcp.data_source.edi.models import (
    EDIDocument,
    EDIFormat,
    EDILineItem,
    EDITransactionType,
    NormalizedOrder,
)


class EDIFACTParser:
    """Parser for EDIFACT EDI documents.

    Supports:
    - ORDERS: Purchase Order (equivalent to X12 850)
    - DESADV: Dispatch Advice (equivalent to X12 856)
    - INVOIC: Invoice (equivalent to X12 810)
    """

    SUPPORTED_TYPES = {"ORDERS", "DESADV", "INVOIC"}

    def detect_format(self, content: str) -> EDIFormat:
        """Detect if content is EDIFACT format.

        Args:
            content: Raw EDI file content

        Returns:
            EDIFormat.EDIFACT if valid EDIFACT format

        Raises:
            ValueError: If not EDIFACT format
        """
        if content.strip().startswith("UNB"):
            return EDIFormat.EDIFACT
        raise ValueError("Not EDIFACT format: must start with UNB segment")

    def detect_transaction_type(self, content: str) -> EDITransactionType:
        """Detect the message type from EDIFACT content.

        Args:
            content: Raw EDIFACT content

        Returns:
            EDITransactionType enum value

        Raises:
            ValueError: If message type not found or unsupported
        """
        # Parse to find UNH segment
        try:
            segments = Parser().parse(content)
            for segment in segments:
                if segment.tag == "UNH":
                    # UNH format: UNH+ref+type:version:release:agency
                    # Element 1 contains message type info
                    if len(segment.elements) > 1:
                        type_info = segment.elements[1]
                        if isinstance(type_info, list) and type_info:
                            msg_type = type_info[0]
                        else:
                            msg_type = str(type_info).split(":")[0]

                        if msg_type == "ORDERS":
                            return EDITransactionType.EDIFACT_ORDERS
                        elif msg_type == "DESADV":
                            return EDITransactionType.EDIFACT_DESADV
                        elif msg_type == "INVOIC":
                            return EDITransactionType.EDIFACT_INVOIC
                        else:
                            raise ValueError(f"Unsupported EDIFACT message type: {msg_type}")

            raise ValueError("Invalid EDIFACT: UNH segment not found")
        except Exception as e:
            if "Invalid EDIFACT" in str(e) or "Unsupported" in str(e):
                raise
            raise ValueError(f"Invalid EDIFACT: {e}")

    def parse(self, content: str) -> list[NormalizedOrder]:
        """Parse EDIFACT content into normalized orders.

        Args:
            content: Raw EDIFACT file content

        Returns:
            List of NormalizedOrder objects

        Raises:
            ValueError: If content is invalid or unsupported
        """
        # Validate format
        self.detect_format(content)
        tx_type = self.detect_transaction_type(content)

        try:
            segments = list(Parser().parse(content))
        except Exception as e:
            raise ValueError(f"Invalid EDIFACT: {e}")

        if tx_type == EDITransactionType.EDIFACT_ORDERS:
            return self._parse_orders(segments)
        elif tx_type == EDITransactionType.EDIFACT_DESADV:
            return self._parse_desadv(segments)
        elif tx_type == EDITransactionType.EDIFACT_INVOIC:
            return self._parse_invoic(segments)
        else:
            raise ValueError(f"Unsupported message type: {tx_type}")

    def _get_element(self, segment: Segment, index: int, sub_index: int = 0) -> str | None:
        """Safely get element from segment."""
        try:
            if index >= len(segment.elements):
                return None
            elem = segment.elements[index]
            if isinstance(elem, list):
                if sub_index >= len(elem):
                    return None
                return str(elem[sub_index]) if elem[sub_index] else None
            return str(elem) if elem else None
        except (IndexError, TypeError):
            return None

    def _parse_orders(self, segments: list[Segment]) -> list[NormalizedOrder]:
        """Parse EDIFACT ORDERS message."""
        orders: list[NormalizedOrder] = []
        current_order: dict = {}
        current_items: list[EDILineItem] = []
        current_item: dict = {}
        in_ship_to = False

        for segment in segments:
            tag = segment.tag

            if tag == "BGM":
                # Beginning of Message
                current_order["po_number"] = self._get_element(segment, 1)

            elif tag == "NAD":
                # Name and Address
                qualifier = self._get_element(segment, 0)
                if qualifier == "ST":  # Ship To
                    in_ship_to = True
                    # NAD+ST+++Name+Address+City+State+Postal+Country
                    current_order["recipient_name"] = self._get_element(segment, 3)
                    current_order["address_line1"] = self._get_element(segment, 4)
                    current_order["city"] = self._get_element(segment, 5)
                    current_order["state"] = self._get_element(segment, 6)
                    current_order["postal_code"] = self._get_element(segment, 7)
                    current_order["country"] = self._get_element(segment, 8) or "US"
                else:
                    in_ship_to = False

            elif tag == "LIN":
                # Line Item
                if current_item:
                    current_items.append(EDILineItem(**current_item))
                current_item = {
                    "line_number": len(current_items) + 1,
                }
                # LIN+linenum++productid:qualifier
                product_info = self._get_element(segment, 2)
                if product_info:
                    # Parse "SKU-100:VP" format
                    parts = product_info.split(":")
                    current_item["product_id"] = parts[0]

            elif tag == "QTY":
                # Quantity
                qty_info = self._get_element(segment, 0)
                if qty_info:
                    parts = qty_info.split(":")
                    if len(parts) > 1:
                        current_item["quantity"] = int(parts[1])

            elif tag == "PRI":
                # Price
                price_info = self._get_element(segment, 0)
                if price_info:
                    parts = price_info.split(":")
                    if len(parts) > 1:
                        try:
                            current_item["unit_price_cents"] = int(float(parts[1]) * 100)
                        except ValueError:
                            pass

            elif tag == "UNT":
                # End of message
                if current_item:
                    current_items.append(EDILineItem(**current_item))

                if current_order.get("po_number"):
                    order = NormalizedOrder(
                        po_number=current_order.get("po_number", ""),
                        recipient_name=current_order.get("recipient_name", "Unknown"),
                        address_line1=current_order.get("address_line1", ""),
                        city=current_order.get("city", ""),
                        state=current_order.get("state", ""),
                        postal_code=current_order.get("postal_code", ""),
                        country=current_order.get("country", "US"),
                        items=current_items,
                        source_document=EDIDocument(
                            format=EDIFormat.EDIFACT,
                            transaction_type=EDITransactionType.EDIFACT_ORDERS,
                        ),
                    )
                    orders.append(order)

                current_order = {}
                current_items = []
                current_item = {}

        return orders

    def _parse_desadv(self, segments: list[Segment]) -> list[NormalizedOrder]:
        """Parse EDIFACT DESADV (Dispatch Advice) message."""
        orders: list[NormalizedOrder] = []
        current_order: dict = {}
        current_items: list[EDILineItem] = []

        for segment in segments:
            tag = segment.tag

            if tag == "BGM":
                current_order["reference_number"] = self._get_element(segment, 1)

            elif tag == "RFF":
                # Reference - may contain PO number
                ref_info = self._get_element(segment, 0)
                if ref_info and ref_info.startswith("ON:"):
                    current_order["po_number"] = ref_info.split(":")[1]

            elif tag == "NAD":
                qualifier = self._get_element(segment, 0)
                if qualifier == "ST":
                    current_order["recipient_name"] = self._get_element(segment, 3)
                    current_order["address_line1"] = self._get_element(segment, 4)
                    current_order["city"] = self._get_element(segment, 5)
                    current_order["state"] = self._get_element(segment, 6)
                    current_order["postal_code"] = self._get_element(segment, 7)
                    current_order["country"] = self._get_element(segment, 8) or "US"

            elif tag == "LIN":
                item = EDILineItem(line_number=len(current_items) + 1)
                current_items.append(item)

            elif tag == "UNT":
                if current_order.get("po_number") or current_order.get("reference_number"):
                    order = NormalizedOrder(
                        po_number=current_order.get("po_number", current_order.get("reference_number", "")),
                        reference_number=current_order.get("reference_number"),
                        recipient_name=current_order.get("recipient_name", "Unknown"),
                        address_line1=current_order.get("address_line1", ""),
                        city=current_order.get("city", ""),
                        state=current_order.get("state", ""),
                        postal_code=current_order.get("postal_code", ""),
                        country=current_order.get("country", "US"),
                        items=current_items,
                        source_document=EDIDocument(
                            format=EDIFormat.EDIFACT,
                            transaction_type=EDITransactionType.EDIFACT_DESADV,
                        ),
                    )
                    orders.append(order)

                current_order = {}
                current_items = []

        return orders

    def _parse_invoic(self, segments: list[Segment]) -> list[NormalizedOrder]:
        """Parse EDIFACT INVOIC message."""
        orders: list[NormalizedOrder] = []
        current_order: dict = {}
        current_items: list[EDILineItem] = []

        for segment in segments:
            tag = segment.tag

            if tag == "BGM":
                current_order["reference_number"] = self._get_element(segment, 1)

            elif tag == "RFF":
                ref_info = self._get_element(segment, 0)
                if ref_info and ref_info.startswith("ON:"):
                    current_order["po_number"] = ref_info.split(":")[1]

            elif tag == "NAD":
                qualifier = self._get_element(segment, 0)
                if qualifier == "ST":
                    current_order["recipient_name"] = self._get_element(segment, 3)
                    current_order["address_line1"] = self._get_element(segment, 4)
                    current_order["city"] = self._get_element(segment, 5)
                    current_order["state"] = self._get_element(segment, 6)
                    current_order["postal_code"] = self._get_element(segment, 7)
                    current_order["country"] = self._get_element(segment, 8) or "US"

            elif tag == "LIN":
                item = EDILineItem(line_number=len(current_items) + 1)
                current_items.append(item)

            elif tag == "UNT":
                if current_order.get("po_number") or current_order.get("reference_number"):
                    order = NormalizedOrder(
                        po_number=current_order.get("po_number", current_order.get("reference_number", "")),
                        reference_number=current_order.get("reference_number"),
                        recipient_name=current_order.get("recipient_name", "Unknown"),
                        address_line1=current_order.get("address_line1", ""),
                        city=current_order.get("city", ""),
                        state=current_order.get("state", ""),
                        postal_code=current_order.get("postal_code", ""),
                        country=current_order.get("country", "US"),
                        items=current_items,
                        source_document=EDIDocument(
                            format=EDIFormat.EDIFACT,
                            transaction_type=EDITransactionType.EDIFACT_INVOIC,
                        ),
                    )
                    orders.append(order)

                current_order = {}
                current_items = []

        return orders
```

**Step 5: Create fixture file**

Create the `tests/fixtures/edi/sample_orders.edi` file as shown in Step 1.

**Step 6: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edifact_parser.py -v`

Expected: PASS (all 4 tests)

**Step 7: Commit**

```bash
git add src/mcp/data_source/edi/edifact_parser.py tests/mcp/test_edifact_parser.py tests/fixtures/edi/sample_orders.edi
git commit -m "feat(edi): add EDIFACT parser for ORDERS, DESADV, INVOIC messages"
```

---

### Task 1.5: Create EDI Adapter

**Files:**
- Create: `src/mcp/data_source/adapters/edi_adapter.py`
- Create: `tests/mcp/test_edi_adapter.py`

**Step 1: Write failing test for EDI adapter**

Create `tests/mcp/test_edi_adapter.py`:

```python
"""Test EDI adapter for Data Source MCP."""

from pathlib import Path
import tempfile

import duckdb
import pytest

from src.mcp.data_source.adapters.edi_adapter import EDIAdapter
from src.mcp.data_source.models import ImportResult


@pytest.fixture
def sample_x12_850():
    """Create temporary X12 850 file."""
    content = """ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *260126*1200*U*00401*000000001*0*P*>~
GS*PO*SENDER*RECEIVER*20260126*1200*1*X*004010~
ST*850*0001~
BEG*00*NE*PO-12345**20260126~
N1*ST*John Doe*92*SHIP001~
N3*123 Main Street~
N4*Springfield*IL*62701*US~
PO1*1*5*EA*1500**UP*012345678901*VP*SKU-001~
CTT*1~
SE*8*0001~
GE*1*1~
IEA*1*000000001~"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def sample_edifact_orders():
    """Create temporary EDIFACT ORDERS file."""
    content = """UNB+UNOC:3+SENDER+RECEIVER+260126:1200+1'
UNH+1+ORDERS:D:96A:UN'
BGM+220+ORDER-001+9'
NAD+ST+++Jane Smith+456 Oak Ave+Chicago+IL+60601+US'
LIN+1++PROD-100:VP'
QTY+21:3'
UNS+S'
UNT+7+1'
UNZ+1+1'"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def duckdb_conn():
    """Create in-memory DuckDB connection."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


def test_edi_adapter_source_type():
    """Test EDIAdapter returns correct source type."""
    adapter = EDIAdapter()
    assert adapter.source_type == "edi"


def test_import_x12_850(sample_x12_850, duckdb_conn):
    """Test importing X12 850 file."""
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_x12_850)

    assert isinstance(result, ImportResult)
    assert result.source_type == "edi"
    assert result.row_count == 1  # 1 order

    # Verify data loaded into DuckDB
    rows = duckdb_conn.execute("SELECT * FROM imported_data").fetchall()
    assert len(rows) == 1

    # Verify normalized columns
    columns = duckdb_conn.execute("DESCRIBE imported_data").fetchall()
    col_names = [c[0] for c in columns]
    assert "po_number" in col_names
    assert "recipient_name" in col_names
    assert "city" in col_names


def test_import_edifact_orders(sample_edifact_orders, duckdb_conn):
    """Test importing EDIFACT ORDERS file."""
    adapter = EDIAdapter()
    result = adapter.import_data(duckdb_conn, file_path=sample_edifact_orders)

    assert isinstance(result, ImportResult)
    assert result.source_type == "edi"
    assert result.row_count == 1

    # Verify PO number parsed correctly
    po = duckdb_conn.execute(
        "SELECT po_number FROM imported_data"
    ).fetchone()[0]
    assert po == "ORDER-001"


def test_import_file_not_found(duckdb_conn):
    """Test error handling for missing file."""
    adapter = EDIAdapter()
    with pytest.raises(FileNotFoundError, match="EDI file not found"):
        adapter.import_data(duckdb_conn, file_path="/nonexistent/file.edi")


def test_import_invalid_content(duckdb_conn):
    """Test error handling for invalid EDI content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write("This is not EDI content")
        invalid_path = f.name

    adapter = EDIAdapter()
    with pytest.raises(ValueError, match="Unsupported EDI format"):
        adapter.import_data(duckdb_conn, file_path=invalid_path)


def test_get_metadata(sample_x12_850, duckdb_conn):
    """Test get_metadata returns correct info after import."""
    adapter = EDIAdapter()

    # Before import
    metadata = adapter.get_metadata(duckdb_conn)
    assert "error" in metadata

    # After import
    adapter.import_data(duckdb_conn, file_path=sample_x12_850)
    metadata = adapter.get_metadata(duckdb_conn)

    assert metadata["row_count"] == 1
    assert metadata["source_type"] == "edi"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edi_adapter.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.mcp.data_source.adapters.edi_adapter'"

**Step 3: Implement EDI adapter**

Create `src/mcp/data_source/adapters/edi_adapter.py`:

```python
"""EDI adapter for importing X12 and EDIFACT files via DuckDB.

Detects EDI format (X12 or EDIFACT), parses the document,
normalizes to common schema, and loads into DuckDB.

Supported formats:
- X12: 850 (PO), 856 (ASN), 810 (Invoice)
- EDIFACT: ORDERS, DESADV, INVOIC
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.models import ImportResult, SchemaColumn
from src.mcp.data_source.edi.x12_parser import X12Parser
from src.mcp.data_source.edi.edifact_parser import EDIFACTParser
from src.mcp.data_source.edi.models import NormalizedOrder


class EDIAdapter(BaseSourceAdapter):
    """Adapter for importing EDI files (X12 and EDIFACT).

    Automatically detects format from file content and uses
    appropriate parser. Normalizes all formats to common
    shipping-relevant schema.

    Example:
        >>> adapter = EDIAdapter()
        >>> result = adapter.import_data(conn, file_path="/path/to/orders.edi")
        >>> print(result.row_count)
        5
    """

    def __init__(self):
        """Initialize with X12 and EDIFACT parsers."""
        self._x12_parser = X12Parser()
        self._edifact_parser = EDIFACTParser()
        self._last_file_path: str | None = None

    @property
    def source_type(self) -> str:
        """Return adapter source type identifier."""
        return "edi"

    def import_data(
        self,
        conn: "DuckDBPyConnection",
        file_path: str,
        **kwargs,
    ) -> ImportResult:
        """Import EDI file into DuckDB.

        Detects format, parses content, normalizes to common schema,
        and loads into the 'imported_data' table.

        Args:
            conn: DuckDB connection (in-memory)
            file_path: Absolute path to the EDI file

        Returns:
            ImportResult with row count, schema, and warnings

        Raises:
            FileNotFoundError: If EDI file doesn't exist
            ValueError: If EDI format is invalid or unsupported
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"EDI file not found: {file_path}")

        self._last_file_path = file_path
        content = path.read_text()
        warnings: list[str] = []

        # Detect format and parse
        orders = self._parse_content(content)

        if not orders:
            warnings.append("No orders found in EDI file")

        # Create table and load data
        self._load_to_duckdb(conn, orders)

        # Build schema from normalized order structure
        columns = self._get_schema_columns(conn)

        return ImportResult(
            row_count=len(orders),
            columns=columns,
            warnings=warnings,
            source_type="edi",
        )

    def _parse_content(self, content: str) -> list[NormalizedOrder]:
        """Parse EDI content using appropriate parser."""
        content = content.strip()

        # Try X12 first
        if content.startswith("ISA"):
            return self._x12_parser.parse(content)

        # Try EDIFACT
        if content.startswith("UNB"):
            return self._edifact_parser.parse(content)

        raise ValueError(
            "Unsupported EDI format. File must start with ISA (X12) or UNB (EDIFACT)"
        )

    def _load_to_duckdb(
        self, conn: "DuckDBPyConnection", orders: list[NormalizedOrder]
    ) -> None:
        """Load normalized orders into DuckDB table."""
        # Create table with normalized schema
        conn.execute("""
            CREATE OR REPLACE TABLE imported_data (
                row_number INTEGER,
                po_number VARCHAR,
                reference_number VARCHAR,
                recipient_name VARCHAR,
                recipient_company VARCHAR,
                recipient_phone VARCHAR,
                recipient_email VARCHAR,
                address_line1 VARCHAR,
                address_line2 VARCHAR,
                city VARCHAR,
                state VARCHAR,
                postal_code VARCHAR,
                country VARCHAR,
                items JSON,
                edi_format VARCHAR,
                edi_transaction_type VARCHAR
            )
        """)

        # Insert each order
        for i, order in enumerate(orders, 1):
            items_json = json.dumps(
                [item.model_dump() for item in order.items]
            )

            edi_format = (
                order.source_document.format.value
                if order.source_document
                else None
            )
            edi_tx_type = (
                order.source_document.transaction_type.value
                if order.source_document
                else None
            )

            conn.execute(
                """
                INSERT INTO imported_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    i,
                    order.po_number,
                    order.reference_number,
                    order.recipient_name,
                    order.recipient_company,
                    order.recipient_phone,
                    order.recipient_email,
                    order.address_line1,
                    order.address_line2,
                    order.city,
                    order.state,
                    order.postal_code,
                    order.country,
                    items_json,
                    edi_format,
                    edi_tx_type,
                ],
            )

    def _get_schema_columns(
        self, conn: "DuckDBPyConnection"
    ) -> list[SchemaColumn]:
        """Get schema columns from DuckDB table."""
        schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
        columns = []

        for col_name, col_type, nullable, key, default, extra in schema_rows:
            columns.append(
                SchemaColumn(
                    name=col_name,
                    type=col_type,
                    nullable=(nullable == "YES"),
                    warnings=[],
                )
            )

        return columns

    def get_metadata(self, conn: "DuckDBPyConnection") -> dict:
        """Return metadata about imported EDI data.

        Args:
            conn: DuckDB connection

        Returns:
            Dictionary with row_count, column_count, source_type
        """
        try:
            row_count = conn.execute(
                "SELECT COUNT(*) FROM imported_data"
            ).fetchone()[0]
            columns = conn.execute("DESCRIBE imported_data").fetchall()
            return {
                "row_count": row_count,
                "column_count": len(columns),
                "source_type": "edi",
                "file_path": self._last_file_path,
            }
        except Exception:
            return {"error": "No data imported"}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edi_adapter.py -v`

Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add src/mcp/data_source/adapters/edi_adapter.py tests/mcp/test_edi_adapter.py
git commit -m "feat(edi): add EDI adapter extending BaseSourceAdapter pattern"
```

---

### Task 1.6: Register EDI Import Tool

**Files:**
- Create: `src/mcp/data_source/tools/edi_tools.py`
- Modify: `src/mcp/data_source/server.py:64-100`

**Step 1: Write failing test for import_edi tool**

Create `tests/mcp/test_edi_tools.py`:

```python
"""Test EDI MCP tools."""

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp.data_source.tools.edi_tools import import_edi


@pytest.fixture
def sample_x12_file():
    """Create temporary X12 850 file."""
    content = """ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *260126*1200*U*00401*000000001*0*P*>~
GS*PO*SENDER*RECEIVER*20260126*1200*1*X*004010~
ST*850*0001~
BEG*00*NE*PO-TEST**20260126~
N1*ST*Test User~
N3*100 Test St~
N4*TestCity*TS*12345*US~
PO1*1*1*EA*100**VP*TEST-SKU~
CTT*1~
SE*8*0001~
GE*1*1~
IEA*1*000000001~"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".edi", delete=False) as f:
        f.write(content)
        return f.name


@pytest.fixture
def mock_context():
    """Create mock FastMCP context."""
    import duckdb

    ctx = MagicMock()
    ctx.info = AsyncMock()

    # Create real DuckDB connection for testing
    conn = duckdb.connect(":memory:")
    ctx.request_context.lifespan_context = {
        "db": conn,
        "current_source": None,
    }
    return ctx


@pytest.mark.asyncio
async def test_import_edi_x12(sample_x12_file, mock_context):
    """Test import_edi tool with X12 file."""
    result = await import_edi(sample_x12_file, mock_context)

    assert result["source_type"] == "edi"
    assert result["row_count"] == 1
    assert len(result["columns"]) > 0

    # Verify context was updated
    assert mock_context.request_context.lifespan_context["current_source"]["type"] == "edi"


@pytest.mark.asyncio
async def test_import_edi_logs_info(sample_x12_file, mock_context):
    """Test that import_edi logs import progress."""
    await import_edi(sample_x12_file, mock_context)

    # Should have logged import start and completion
    assert mock_context.info.call_count >= 2
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edi_tools.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'src.mcp.data_source.tools.edi_tools'"

**Step 3: Create EDI tools module**

Create `src/mcp/data_source/tools/edi_tools.py`:

```python
"""EDI import tools for Data Source MCP.

Provides MCP tools for importing X12 and EDIFACT EDI files.
Automatically detects format and transaction type.
"""

from fastmcp import Context

from src.mcp.data_source.adapters.edi_adapter import EDIAdapter


async def import_edi(
    file_path: str,
    ctx: Context,
) -> dict:
    """Import EDI file and discover schema.

    Imports an X12 or EDIFACT EDI file into DuckDB.
    Automatically detects format from file content.

    Supported formats:
    - X12: 850 (Purchase Order), 856 (ASN), 810 (Invoice)
    - EDIFACT: ORDERS, DESADV, INVOIC

    Args:
        file_path: Absolute path to the EDI file

    Returns:
        Dictionary with:
        - row_count: Number of orders/documents imported
        - columns: Normalized schema columns
        - warnings: Any parsing warnings
        - source_type: 'edi'

    Example:
        >>> result = await import_edi("/path/to/orders.edi", ctx)
        >>> print(result["row_count"])
        10
        >>> print(result["columns"][0])
        {"name": "po_number", "type": "VARCHAR", ...}
    """
    db = ctx.request_context.lifespan_context["db"]

    await ctx.info(f"Importing EDI from {file_path}")

    adapter = EDIAdapter()
    result = adapter.import_data(conn=db, file_path=file_path)

    # Update session state
    ctx.request_context.lifespan_context["current_source"] = {
        "type": "edi",
        "path": file_path,
        "row_count": result.row_count,
    }

    await ctx.info(
        f"Imported {result.row_count} orders with {len(result.columns)} columns"
    )

    return result.model_dump()
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/test_edi_tools.py -v`

Expected: PASS (both tests)

**Step 5: Register tool in server.py**

Modify `src/mcp/data_source/server.py` to add the import:

Add after line 85 (after writeback_tools import):
```python
from src.mcp.data_source.tools.edi_tools import import_edi
```

Add after line 100 (after write_back registration):
```python
mcp.tool()(import_edi)
```

**Step 6: Verify all tests still pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/ -v`

Expected: All MCP tests pass

**Step 7: Commit**

```bash
git add src/mcp/data_source/tools/edi_tools.py src/mcp/data_source/server.py tests/mcp/test_edi_tools.py
git commit -m "feat(edi): register import_edi tool in Data Source MCP server"
```

---

### Task 1.7: Run Full Test Suite

**Step 1: Run all tests**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest -v`

Expected: All tests pass (654+ tests)

**Step 2: Commit phase completion**

```bash
git add -A
git commit -m "feat(edi): complete Phase 1 - EDI Adapter implementation

- Add pydifact dependency for EDIFACT parsing
- Create EDI data models (NormalizedOrder, EDILineItem, etc.)
- Implement X12 parser for 850, 856, 810 transactions
- Implement EDIFACT parser for ORDERS, DESADV, INVOIC messages
- Create EDIAdapter extending BaseSourceAdapter pattern
- Register import_edi tool in Data Source MCP

Closes Phase 1 of integration expansion."
```

---

## Phase 2: External Sources Gateway MCP (Foundation)

### Task 2.1: Create Gateway MCP Package Structure

**Files:**
- Create: `src/mcp/external_sources/__init__.py`
- Create: `src/mcp/external_sources/server.py`
- Create: `src/mcp/external_sources/models.py`

**Step 1: Write failing test for gateway server**

Create `tests/mcp/external_sources/__init__.py`:
```python
"""Tests for External Sources Gateway MCP."""
```

Create `tests/mcp/external_sources/test_server.py`:

```python
"""Test External Sources Gateway MCP server."""

import pytest

from src.mcp.external_sources.server import mcp
from src.mcp.external_sources.models import PlatformConnection, OrderFilters


def test_mcp_server_exists():
    """Test that MCP server is properly configured."""
    assert mcp is not None
    assert mcp.name == "ExternalSources"


def test_platform_connection_model():
    """Test PlatformConnection model."""
    conn = PlatformConnection(
        platform="shopify",
        store_url="https://mystore.myshopify.com",
        status="connected",
    )
    assert conn.platform == "shopify"
    assert conn.status == "connected"


def test_order_filters_model():
    """Test OrderFilters model."""
    filters = OrderFilters(
        status="pending",
        date_from="2026-01-01",
        limit=50,
    )
    assert filters.status == "pending"
    assert filters.limit == 50
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/external_sources/test_server.py -v`

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Create package structure**

Create `src/mcp/external_sources/__init__.py`:
```python
"""External Sources Gateway MCP.

Provides unified access to external platform MCP servers:
- Shopify
- WooCommerce
- SAP
- Oracle
"""
```

Create `src/mcp/external_sources/models.py`:
```python
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
```

Create `src/mcp/external_sources/server.py`:
```python
"""FastMCP server for External Sources Gateway.

Provides unified access to external platform MCP servers
(Shopify, WooCommerce, SAP, Oracle) through a consistent interface.
"""

from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from src.mcp.external_sources.models import PlatformConnection


@asynccontextmanager
async def lifespan(app: Any):
    """Initialize gateway state.

    Manages:
    - Platform client instances
    - Connection status tracking
    - Credential storage (in-memory only)
    """
    yield {
        "connections": {},  # platform -> PlatformConnection
        "clients": {},  # platform -> PlatformClient instance
        "credentials": {},  # platform -> credentials dict
    }


# Create the FastMCP server
mcp = FastMCP("ExternalSources", lifespan=lifespan)


# Tools will be registered here in subsequent tasks
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/external_sources/test_server.py -v`

Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add src/mcp/external_sources/ tests/mcp/external_sources/
git commit -m "feat(gateway): create External Sources Gateway MCP package structure"
```

---

### Task 2.2: Create Platform Client Interface

**Files:**
- Create: `src/mcp/external_sources/clients/__init__.py`
- Create: `src/mcp/external_sources/clients/base.py`

**Step 1: Write failing test for platform client interface**

Create `tests/mcp/external_sources/test_clients.py`:

```python
"""Test platform client interface."""

import pytest
from abc import ABC

from src.mcp.external_sources.clients.base import PlatformClient
from src.mcp.external_sources.models import OrderFilters, ExternalOrder, TrackingUpdate


def test_platform_client_is_abstract():
    """Test that PlatformClient is an abstract base class."""
    assert issubclass(PlatformClient, ABC)

    # Cannot instantiate directly
    with pytest.raises(TypeError):
        PlatformClient()


def test_platform_client_required_methods():
    """Test that PlatformClient defines required abstract methods."""
    required_methods = [
        "platform_name",
        "authenticate",
        "test_connection",
        "fetch_orders",
        "get_order",
        "update_tracking",
    ]

    for method in required_methods:
        assert hasattr(PlatformClient, method)


class MockPlatformClient(PlatformClient):
    """Mock implementation for testing."""

    @property
    def platform_name(self) -> str:
        return "mock"

    async def authenticate(self, credentials: dict) -> bool:
        return True

    async def test_connection(self) -> bool:
        return True

    async def fetch_orders(self, filters: OrderFilters) -> list[ExternalOrder]:
        return []

    async def get_order(self, order_id: str) -> ExternalOrder | None:
        return None

    async def update_tracking(self, update: TrackingUpdate) -> bool:
        return True


def test_concrete_client_can_instantiate():
    """Test that concrete implementation can be instantiated."""
    client = MockPlatformClient()
    assert client.platform_name == "mock"


@pytest.mark.asyncio
async def test_concrete_client_methods():
    """Test that concrete implementation methods work."""
    client = MockPlatformClient()

    assert await client.authenticate({}) is True
    assert await client.test_connection() is True
    assert await client.fetch_orders(OrderFilters()) == []
    assert await client.get_order("123") is None
    assert await client.update_tracking(
        TrackingUpdate(order_id="123", tracking_number="1Z999")
    ) is True
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/external_sources/test_clients.py -v`

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Create client interface**

Create `src/mcp/external_sources/clients/__init__.py`:
```python
"""Platform client implementations."""

from src.mcp.external_sources.clients.base import PlatformClient

__all__ = ["PlatformClient"]
```

Create `src/mcp/external_sources/clients/base.py`:
```python
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
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/external_sources/test_clients.py -v`

Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add src/mcp/external_sources/clients/ tests/mcp/external_sources/test_clients.py
git commit -m "feat(gateway): add PlatformClient abstract interface"
```

---

### Task 2.3: Add Gateway Tools

**Files:**
- Create: `src/mcp/external_sources/tools.py`
- Modify: `src/mcp/external_sources/server.py`

**Step 1: Write failing test for gateway tools**

Create `tests/mcp/external_sources/test_tools.py`:

```python
"""Test External Sources Gateway tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp.external_sources.tools import (
    list_connections,
    connect_platform,
    list_orders,
)


@pytest.fixture
def mock_context():
    """Create mock FastMCP context."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.request_context.lifespan_context = {
        "connections": {},
        "clients": {},
        "credentials": {},
    }
    return ctx


@pytest.mark.asyncio
async def test_list_connections_empty(mock_context):
    """Test list_connections with no connections."""
    result = await list_connections(mock_context)

    assert result["connections"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_connections_with_platforms(mock_context):
    """Test list_connections with configured platforms."""
    from src.mcp.external_sources.models import PlatformConnection

    mock_context.request_context.lifespan_context["connections"] = {
        "shopify": PlatformConnection(
            platform="shopify",
            store_url="https://test.myshopify.com",
            status="connected",
        ),
    }

    result = await list_connections(mock_context)

    assert result["count"] == 1
    assert result["connections"][0]["platform"] == "shopify"
    assert result["connections"][0]["status"] == "connected"


@pytest.mark.asyncio
async def test_connect_platform_unsupported(mock_context):
    """Test connect_platform with unsupported platform."""
    result = await connect_platform(
        platform="unsupported_platform",
        credentials={"key": "value"},
        ctx=mock_context,
    )

    assert result["success"] is False
    assert "Unsupported platform" in result["error"]
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/external_sources/test_tools.py -v`

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Create gateway tools**

Create `src/mcp/external_sources/tools.py`:
```python
"""MCP tools for External Sources Gateway.

Provides unified interface for connecting to and fetching
data from external platforms (Shopify, WooCommerce, SAP, Oracle).
"""

from fastmcp import Context

from src.mcp.external_sources.models import (
    PlatformConnection,
    PlatformType,
    OrderFilters,
)


SUPPORTED_PLATFORMS = {p.value for p in PlatformType}


async def list_connections(ctx: Context) -> dict:
    """List all configured platform connections.

    Returns status of each connected platform including
    connection health and last sync time.

    Returns:
        Dictionary with:
        - connections: List of PlatformConnection objects
        - count: Number of configured connections

    Example:
        >>> result = await list_connections(ctx)
        >>> print(result["connections"])
        [{"platform": "shopify", "status": "connected", ...}]
    """
    connections = ctx.request_context.lifespan_context.get("connections", {})

    await ctx.info(f"Listing {len(connections)} platform connections")

    return {
        "connections": [c.model_dump() for c in connections.values()],
        "count": len(connections),
    }


async def connect_platform(
    platform: str,
    credentials: dict,
    ctx: Context,
    store_url: str | None = None,
) -> dict:
    """Connect to an external platform.

    Authenticates with the platform and stores connection for reuse.

    Args:
        platform: Platform identifier (shopify, woocommerce, sap, oracle)
        credentials: Platform-specific credentials
            - shopify: {"access_token": str}
            - woocommerce: {"consumer_key": str, "consumer_secret": str}
            - sap: {"username": str, "password": str, "client": str}
            - oracle: {"username": str, "password": str} or OCI config
        store_url: Store/instance URL (required for most platforms)

    Returns:
        Dictionary with:
        - success: Boolean indicating connection success
        - platform: Platform identifier
        - error: Error message if failed

    Example:
        >>> result = await connect_platform(
        ...     "shopify",
        ...     {"access_token": "shpat_xxx"},
        ...     ctx,
        ...     store_url="https://mystore.myshopify.com"
        ... )
        >>> print(result["success"])
        True
    """
    await ctx.info(f"Connecting to platform: {platform}")

    if platform not in SUPPORTED_PLATFORMS:
        return {
            "success": False,
            "platform": platform,
            "error": f"Unsupported platform: {platform}. Supported: {SUPPORTED_PLATFORMS}",
        }

    connections = ctx.request_context.lifespan_context["connections"]
    clients = ctx.request_context.lifespan_context["clients"]
    creds_store = ctx.request_context.lifespan_context["credentials"]

    # Platform-specific client creation will be added in Phase 3-6
    # For now, just track the connection attempt
    try:
        # Store connection info (actual client created in platform-specific tasks)
        connection = PlatformConnection(
            platform=platform,
            store_url=store_url,
            status="connected",  # Will be validated when client is implemented
        )
        connections[platform] = connection
        creds_store[platform] = credentials  # In-memory only, never logged

        await ctx.info(f"Connected to {platform}")

        return {
            "success": True,
            "platform": platform,
            "store_url": store_url,
        }

    except Exception as e:
        await ctx.info(f"Failed to connect to {platform}: {e}")
        return {
            "success": False,
            "platform": platform,
            "error": str(e),
        }


async def list_orders(
    platform: str,
    ctx: Context,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> dict:
    """Fetch orders from an external platform.

    Args:
        platform: Platform to fetch from
        status: Filter by order status (pending, processing, shipped, etc.)
        date_from: Start date filter (ISO format)
        date_to: End date filter (ISO format)
        limit: Maximum orders to return (1-1000)

    Returns:
        Dictionary with:
        - orders: List of normalized order objects
        - count: Number of orders returned
        - platform: Source platform

    Example:
        >>> result = await list_orders("shopify", ctx, status="pending", limit=50)
        >>> print(result["count"])
        25
    """
    await ctx.info(f"Fetching orders from {platform}")

    connections = ctx.request_context.lifespan_context.get("connections", {})
    clients = ctx.request_context.lifespan_context.get("clients", {})

    if platform not in connections:
        return {
            "success": False,
            "error": f"Platform not connected: {platform}. Call connect_platform first.",
            "orders": [],
            "count": 0,
        }

    client = clients.get(platform)
    if not client:
        # Client will be created in platform-specific tasks
        return {
            "success": False,
            "error": f"Platform client not implemented: {platform}",
            "orders": [],
            "count": 0,
        }

    filters = OrderFilters(
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )

    orders = await client.fetch_orders(filters)

    await ctx.info(f"Fetched {len(orders)} orders from {platform}")

    return {
        "success": True,
        "orders": [o.model_dump() for o in orders],
        "count": len(orders),
        "platform": platform,
    }


async def get_order_details(
    platform: str,
    order_id: str,
    ctx: Context,
) -> dict:
    """Get detailed information for a specific order.

    Args:
        platform: Platform to fetch from
        order_id: Platform-specific order identifier

    Returns:
        Dictionary with order details or error
    """
    await ctx.info(f"Fetching order {order_id} from {platform}")

    clients = ctx.request_context.lifespan_context.get("clients", {})
    client = clients.get(platform)

    if not client:
        return {
            "success": False,
            "error": f"Platform not connected or not implemented: {platform}",
        }

    order = await client.get_order(order_id)

    if order:
        return {
            "success": True,
            "order": order.model_dump(),
        }
    else:
        return {
            "success": False,
            "error": f"Order not found: {order_id}",
        }


async def write_back_tracking(
    platform: str,
    order_id: str,
    tracking_number: str,
    ctx: Context,
    carrier: str = "UPS",
    tracking_url: str | None = None,
) -> dict:
    """Write tracking information back to the source platform.

    Args:
        platform: Platform to update
        order_id: Platform order ID
        tracking_number: Carrier tracking number
        carrier: Carrier name (default: UPS)
        tracking_url: Optional tracking URL

    Returns:
        Dictionary with success status
    """
    await ctx.info(f"Writing tracking {tracking_number} to {platform} order {order_id}")

    clients = ctx.request_context.lifespan_context.get("clients", {})
    client = clients.get(platform)

    if not client:
        return {
            "success": False,
            "error": f"Platform not connected or not implemented: {platform}",
        }

    from src.mcp.external_sources.models import TrackingUpdate

    update = TrackingUpdate(
        order_id=order_id,
        tracking_number=tracking_number,
        carrier=carrier,
        tracking_url=tracking_url,
    )

    try:
        success = await client.update_tracking(update)
        return {
            "success": success,
            "order_id": order_id,
            "tracking_number": tracking_number,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "order_id": order_id,
        }
```

**Step 4: Register tools in server.py**

Update `src/mcp/external_sources/server.py`:
```python
"""FastMCP server for External Sources Gateway.

Provides unified access to external platform MCP servers
(Shopify, WooCommerce, SAP, Oracle) through a consistent interface.
"""

from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from src.mcp.external_sources.models import PlatformConnection


@asynccontextmanager
async def lifespan(app: Any):
    """Initialize gateway state.

    Manages:
    - Platform client instances
    - Connection status tracking
    - Credential storage (in-memory only)
    """
    yield {
        "connections": {},  # platform -> PlatformConnection
        "clients": {},  # platform -> PlatformClient instance
        "credentials": {},  # platform -> credentials dict
    }


# Create the FastMCP server
mcp = FastMCP("ExternalSources", lifespan=lifespan)

# Import and register tools
from src.mcp.external_sources.tools import (
    list_connections,
    connect_platform,
    list_orders,
    get_order_details,
    write_back_tracking,
)

mcp.tool()(list_connections)
mcp.tool()(connect_platform)
mcp.tool()(list_orders)
mcp.tool()(get_order_details)
mcp.tool()(write_back_tracking)


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/matthewhans/Desktop/Programming/ShipAgent/.worktrees/integration-expansion && source .venv/bin/activate && pytest tests/mcp/external_sources/ -v`

Expected: PASS (all tests)

**Step 6: Commit**

```bash
git add src/mcp/external_sources/ tests/mcp/external_sources/
git commit -m "feat(gateway): add gateway tools (list_connections, connect_platform, list_orders, write_back_tracking)"
```

---

## Phase 3-6: Platform Connectors (Summary)

The remaining phases follow the same TDD pattern for each platform:

### Phase 3: WooCommerce Connector
- Create `src/mcp/external_sources/clients/woocommerce.py`
- Integrate with techspawn/woocommerce-mcp-server
- Implement `WooCommerceClient(PlatformClient)`
- Test order fetch and tracking write-back

### Phase 4: Shopify Connector
- Fork GeLi2001/shopify-mcp
- Add fulfillment tools to fork
- Create `src/mcp/external_sources/clients/shopify.py`
- Implement `ShopifyClient(PlatformClient)`

### Phase 5: SAP Connector
- Create `src/mcp/external_sources/clients/sap.py`
- Integrate with SAP OData MCP server
- Implement `SAPClient(PlatformClient)`
- Map sales order entities

### Phase 6: Oracle Connector
- Create `src/mcp/external_sources/clients/oracle.py`
- Integrate with Oracle DB MCP
- Implement `OracleClient(PlatformClient)`
- Configurable table mapping

---

## Completion Checklist

After completing all phases:

- [ ] Run full test suite: `pytest -v` (should pass 700+ tests)
- [ ] Run linting: `ruff check src/ tests/`
- [ ] Run type checking: `mypy src/`
- [ ] Update CLAUDE.md with new MCP tools
- [ ] Create PR to merge feature branch
