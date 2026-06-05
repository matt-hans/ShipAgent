"""Neutral UPS read-only tool handlers for the orchestration agent."""

from __future__ import annotations

import logging
from typing import Any

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _err,
    _get_ups_client,
    _ok,
)
from src.services.errors import UPSServiceError

logger = logging.getLogger(__name__)


async def rate_shipment_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Get a UPS rate quote through the shared UPS gateway."""
    _ = bridge
    request_body = args.get("request_body")
    if not isinstance(request_body, dict):
        return _err("Missing required object parameter: request_body")

    requestoption = str(args.get("requestoption") or "Rate")
    try:
        client = await _get_ups_client()
        result = await client.get_rate(
            request_body=request_body,
            requestoption=requestoption,
        )
        return _ok(result)
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in rate_shipment_tool")
        return _err(f"Unexpected error: {e}")


async def validate_address_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Validate a shipping address through the shared UPS gateway."""
    _ = bridge
    required = (
        "addressLine1",
        "city",
        "stateProvinceCode",
        "postalCode",
        "countryCode",
    )
    missing = [name for name in required if not str(args.get(name) or "").strip()]
    if missing:
        return _err(f"Missing required parameter(s): {', '.join(missing)}")

    try:
        client = await _get_ups_client()
        result = await client.validate_address(
            addressLine1=str(args["addressLine1"]),
            addressLine2=str(args.get("addressLine2") or ""),
            city=str(args["city"]),
            stateProvinceCode=str(args["stateProvinceCode"]),
            postalCode=str(args["postalCode"]),
            countryCode=str(args["countryCode"]),
        )
        return _ok(result)
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in validate_address_tool")
        return _err(f"Unexpected error: {e}")


async def get_time_in_transit_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Get UPS time-in-transit estimates through the shared UPS gateway."""
    _ = bridge
    request_body = args.get("request_body")
    if not isinstance(request_body, dict):
        return _err("Missing required object parameter: request_body")

    try:
        client = await _get_ups_client()
        result = await client.get_time_in_transit(request_body=request_body)
        return _ok(result)
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_time_in_transit_tool")
        return _err(f"Unexpected error: {e}")
