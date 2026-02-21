"""Data Source MCP package.

Provides MCP server for importing and querying shipment data.
"""

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.adapters.csv_adapter import CSVAdapter
from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter
from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter
from src.mcp.data_source.models import (
    ChecksumResult,
    DateWarning,
    ImportResult,
    QueryResult,
    RowData,
    SchemaColumn,
    ValidationError,
)
from src.mcp.data_source.server import mcp

__all__ = [
    "mcp",
    "SchemaColumn",
    "ImportResult",
    "RowData",
    "QueryResult",
    "ChecksumResult",
    "DateWarning",
    "ValidationError",
    "BaseSourceAdapter",
    "CSVAdapter",
    "ExcelAdapter",
    "DatabaseAdapter",
]
