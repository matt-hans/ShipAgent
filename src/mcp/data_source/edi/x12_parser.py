"""X12 EDI parser for 850 (PO), 856 (ASN), and 810 (Invoice).

Parses X12 EDI documents and normalizes to common order schema.
Uses simple regex-based parsing rather than full X12 library
for lighter dependency footprint.
"""

import re

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
                if len(elements) > 1:
                    current_order["address_line2"] = elements[1]

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
                        address_line2=current_order.get("address_line2"),
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
                if len(elements) > 1:
                    current_order["address_line2"] = elements[1]

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
                        address_line2=current_order.get("address_line2"),
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
