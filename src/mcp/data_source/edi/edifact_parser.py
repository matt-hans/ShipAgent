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

        for segment in segments:
            tag = segment.tag

            if tag == "BGM":
                # Beginning of Message
                current_order["po_number"] = self._get_element(segment, 1)

            elif tag == "NAD":
                # Name and Address
                qualifier = self._get_element(segment, 0)
                if qualifier == "ST":  # Ship To
                    # NAD+ST+++Name+Address+City+State+Postal+Country
                    current_order["recipient_name"] = self._get_element(segment, 3)
                    current_order["address_line1"] = self._get_element(segment, 4)
                    current_order["city"] = self._get_element(segment, 5)
                    current_order["state"] = self._get_element(segment, 6)
                    current_order["postal_code"] = self._get_element(segment, 7)
                    current_order["country"] = self._get_element(segment, 8) or "US"

            elif tag == "LIN":
                # Line Item
                if current_item:
                    current_items.append(EDILineItem(**current_item))
                current_item = {
                    "line_number": len(current_items) + 1,
                }
                # LIN+linenum++productid:qualifier - pydifact splits to ['SKU-100', 'VP']
                product_id = self._get_element(segment, 2, 0)
                if product_id:
                    current_item["product_id"] = product_id

            elif tag == "QTY":
                # Quantity - pydifact already splits components, so elements[0] is ['21', '10']
                qty_value = self._get_element(segment, 0, 1)
                if qty_value:
                    try:
                        current_item["quantity"] = int(qty_value)
                    except ValueError:
                        pass

            elif tag == "PRI":
                # Price - pydifact already splits components, so elements[0] is ['AAA', '25.00']
                price_value = self._get_element(segment, 0, 1)
                if price_value:
                    try:
                        current_item["unit_price_cents"] = int(float(price_value) * 100)
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
