# Data source adapters for all supported import formats

from src.mcp.data_source.adapters.base import BaseSourceAdapter
from src.mcp.data_source.adapters.csv_adapter import CSVAdapter, DelimitedAdapter
from src.mcp.data_source.adapters.db_adapter import DatabaseAdapter
from src.mcp.data_source.adapters.excel_adapter import ExcelAdapter
from src.mcp.data_source.adapters.fixed_width_adapter import FixedWidthAdapter
from src.mcp.data_source.adapters.json_adapter import JSONAdapter
from src.mcp.data_source.adapters.xml_adapter import XMLAdapter

# EDIAdapter requires the optional pydifact dependency. Guard the import so that
# environments without pydifact installed can still use all other adapters.
try:
    from src.mcp.data_source.adapters.edi_adapter import EDIAdapter
    _EDI_AVAILABLE = True
except ImportError:
    EDIAdapter = None  # type: ignore[assignment,misc]
    _EDI_AVAILABLE = False

__all__ = [
    "BaseSourceAdapter",
    "CSVAdapter",
    "DatabaseAdapter",
    "DelimitedAdapter",
    "EDIAdapter",
    "ExcelAdapter",
    "FixedWidthAdapter",
    "JSONAdapter",
    "XMLAdapter",
]
