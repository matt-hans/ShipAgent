"""Deterministic stand-ins for the batch confirmation acceptance scenarios.

Only the two process boundaries are simulated:

* ``ImportedCsvSource`` is the Data Source MCP gateway. It is the real
  ``DataSourceMCPClient`` whose transport routes straight into the real server
  tool functions (``import_csv``/``get_rows_by_filter``/``get_source_info``)
  over an in-memory DuckDB, so the imported file, deterministic filter
  compilation, row identity and checksums are the production code paths.
* ``SimulatedUPS`` is the UPS MCP gateway. It rates and "creates" shipments
  deterministically and counts every call, so tests assert purchase side
  effects instead of method sequences.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import duckdb
import pytest

from src.mcp.data_source.tools import (
    import_tools,
    query_tools,
    source_info_tools,
    writeback_tools,
)
from src.services.data_source_mcp_client import DataSourceMCPClient
from src.services.errors import UPSServiceError

CANARY_PREFIX = "CANARY"

# Rows an operator would import: three CA orders and one TX order.
IMPORTED_ORDERS_CSV = """\
order_id,ship_to_name,ship_to_address1,ship_to_city,ship_to_state,ship_to_postal_code,ship_to_country,ship_to_phone,weight
1001,CANARY Alice Adams,100 Market St,San Francisco,CA,94105,US,4155550101,2.0
1002,CANARY Bob Brown,200 Pine St,Los Angeles,CA,90001,US,2135550102,3.5
1003,CANARY Cara Cole,300 Oak Ave,Austin,TX,78701,US,5125550103,1.0
1004,CANARY Dan Diaz,400 Elm Rd,San Diego,CA,92101,US,6195550104,5.0
"""

SHIPPER_ENV = {
    "SHIPPER_NAME": "Acceptance Shipper",
    "SHIPPER_PHONE": "4155550000",
    "SHIPPER_ADDRESS1": "1 Warehouse Way",
    "SHIPPER_CITY": "Oakland",
    "SHIPPER_STATE": "CA",
    "SHIPPER_ZIP": "94607",
    "SHIPPER_COUNTRY": "US",
    "UPS_CLIENT_ID": "synthetic-client-id",
    "UPS_CLIENT_SECRET": "synthetic-client-secret",
    "UPS_ACCOUNT_NUMBER": "A1B2C3",
}


class _Ctx:
    """Minimal FastMCP ``Context`` for calling server tool functions in-process."""

    def __init__(self, lifespan: dict[str, Any]) -> None:
        self.request_context = SimpleNamespace(lifespan_context=lifespan)

    async def info(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class ImportedCsvSource(DataSourceMCPClient):
    """Real data-source gateway over real server tools; no subprocess."""

    def __init__(self) -> None:  # noqa: D107 - no MCP transport
        self._lifespan: dict[str, Any] = {
            "db": duckdb.connect(":memory:"),
            "current_source": None,
        }
        self.tool_calls: list[str] = []

    async def import_csv_file(self, path: Path) -> None:
        await import_tools.import_csv(str(path), _Ctx(self._lifespan))

    def close(self) -> None:
        """Release the test-owned in-memory database."""
        self._lifespan["db"].close()

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.tool_calls.append(name)
        ctx = _Ctx(self._lifespan)
        if name == "get_source_info":
            return await source_info_tools.get_source_info(ctx)
        if name == "get_rows_by_filter":
            return await query_tools.get_rows_by_filter(ctx=ctx, **arguments)
        if name == "write_back":
            return await writeback_tools.write_back(ctx=ctx, **arguments)
        raise AssertionError(f"unexpected data source tool {name!r}")


def _find(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find(item, key)
            if found is not None:
                return found
    return None


def recipient_of(request_body: dict[str, Any]) -> str:
    return str(
        _find(
            request_body,
            "ShipTo",
        ).get("Name", "")
    )


Behavior = Callable[[dict[str, Any]], dict[str, Any]]


class SimulatedUPS:
    """UPS gateway stand-in. ``behaviors`` map a recipient name to a callable
    (or exception to raise) used instead of the happy-path shipment."""

    def __init__(self, *, rate: str = "12.34") -> None:
        self.rate = rate
        self.rate_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.behaviors: dict[str, BaseException | Behavior] = {}
        self._gate: asyncio.Event | None = None
        self.in_create: asyncio.Event = asyncio.Event()

    # -- context-manager protocol so it can replace ``UPSMCPClient(...)`` --
    def __call__(self, *_args: Any, **_kwargs: Any) -> SimulatedUPS:
        return self

    async def __aenter__(self) -> SimulatedUPS:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    def hold_creates(self) -> asyncio.Event:
        """Block ``create_shipment`` until the returned event is set."""
        self._gate = asyncio.Event()
        return self._gate

    async def get_rate(
        self, request_body: dict[str, Any], requestoption: str = "Rate"
    ) -> dict[str, Any]:
        self.rate_calls.append(request_body)
        return {
            "success": True,
            "totalCharges": {"monetaryValue": self.rate, "currencyCode": "USD"},
        }

    async def create_shipment(self, request_body: dict[str, Any]) -> dict[str, Any]:
        self.create_calls.append(request_body)
        self.in_create.set()
        if self._gate is not None:
            await self._gate.wait()
        behavior = self.behaviors.get(recipient_of(request_body))
        if isinstance(behavior, BaseException):
            raise behavior
        if behavior is not None:
            return behavior(request_body)
        number = len(self.create_calls)
        tracking = f"1ZSIM{number:013d}"
        return {
            "success": True,
            "trackingNumbers": [tracking],
            "shipmentIdentificationNumber": tracking,
            "labelData": [base64.b64encode(b"%PDF-simulated-label").decode()],
            "totalCharges": {"monetaryValue": self.rate, "currencyCode": "USD"},
        }

    @property
    def recipients_purchased(self) -> list[str]:
        return [recipient_of(body) for body in self.create_calls]


def hard_rejection() -> UPSServiceError:
    """A carrier rejection that proves no shipment was created."""
    return UPSServiceError(code="E-3003", message="Invalid address")


def synthetic_source_info() -> dict[str, Any]:
    """Metadata-only source fixture using the production identity projection."""
    from src.services.source_identity import source_binding_digest

    info = {
        "active": True,
        "source_type": "csv",
        "path": "/synthetic/orders.csv",
        "signature": "schema-v1",
        "source_instance": "import-test",
        "row_key_columns": ["_source_row_num"],
    }
    info["binding_digest"] = source_binding_digest(info)
    return info


def bind_job_source(db: Any, job_id: str, info: dict[str, Any]) -> None:
    """Persist the same safe source metadata used by production job creation."""
    from src.services.audit_service import AuditService, EventType

    AuditService(db).log_info(
        job_id=job_id,
        event_type=EventType.row_event,
        message="job_source_signature",
        details={
            "source_signature": {
                "source_type": info["source_type"],
                "source_ref": info.get("path", ""),
                "schema_fingerprint": info.get("signature", ""),
                "binding_digest": info["binding_digest"],
            }
        },
    )


# Legacy engine unit tests exercise row processing without a connected source.
# Explicit write-back tests replace this seam with their bound source fixture.


@pytest.fixture(autouse=True)
def offline_batch_gateways(monkeypatch, tmp_path):
    gateway = AsyncMock()
    gateway.get_source_info.return_value = None
    monkeypatch.setattr(
        "src.services.batch_engine.get_data_gateway", AsyncMock(return_value=gateway)
    )
    monkeypatch.setenv("UPS_LABELS_OUTPUT_DIR", str(tmp_path / "labels"))
