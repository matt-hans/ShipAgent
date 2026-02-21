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
from src.mcp.data_source.models import SOURCE_ROW_NUM_COLUMN, ImportResult, SchemaColumn
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
        # _source_row_num BIGINT matches the standard used by all other adapters
        # (SOURCE_ROW_NUM_COLUMN from models.py) for deterministic row tracking.
        conn.execute(f"""
            CREATE OR REPLACE TABLE imported_data (
                {SOURCE_ROW_NUM_COLUMN} BIGINT,
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
        """Get schema columns from DuckDB table.

        Excludes the internal _source_row_num tracking column from the
        user-facing schema, matching the behaviour of all other adapters.
        """
        schema_rows = conn.execute("DESCRIBE imported_data").fetchall()
        columns = []

        for row in schema_rows:
            col_name = row[0]
            # Skip internal row-tracking column — not exposed to users
            if col_name == SOURCE_ROW_NUM_COLUMN:
                continue
            col_type = row[1]
            nullable = row[2] if len(row) > 2 else "YES"

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
