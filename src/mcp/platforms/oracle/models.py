# src/mcp/platforms/oracle/models.py
"""Oracle-specific data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OracleCredentials:
    """Resolved Oracle database credentials for a connection.

    Uses oracledb thin mode (no Oracle client installation required).

    Attributes:
        host: Database server hostname or IP.
        port: Listener port (default 1521).
        service_name: Oracle service name (e.g., "ORCL").
        user: Database username.
        password: Database password.
        orders_table: Table name containing orders (default "SALES_ORDERS").
        tracking_table: Table name for shipment tracking (default "SHIPMENT_TRACKING").
    """

    host: str
    port: int
    service_name: str
    user: str
    password: str
    orders_table: str = "SALES_ORDERS"
    tracking_table: str = "SHIPMENT_TRACKING"

    @property
    def dsn(self) -> str:
        """Build the Oracle DSN string."""
        return f"{self.host}:{self.port}/{self.service_name}"
