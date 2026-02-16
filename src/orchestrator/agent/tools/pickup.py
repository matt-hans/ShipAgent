"""Pickup and location tool handlers for the orchestration agent.

Handles: schedule_pickup, cancel_pickup, rate_pickup, get_pickup_status,
find_locations, get_service_center_facilities.
"""

from __future__ import annotations

import logging
from typing import Any

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _emit_event,
    _err,
    _get_ups_client,
    _ok,
)
from src.services.errors import UPSServiceError

logger = logging.getLogger(__name__)


async def schedule_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Schedule a UPS pickup and emit pickup_result event.

    Args:
        args: Dict with pickup_date, ready_time, close_time, address fields,
              contact_name, phone_number, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with PRN on success, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.schedule_pickup(**args)
        payload = {"action": "scheduled", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok({"prn": result.get("prn"), "success": True, "action": "scheduled"})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in schedule_pickup_tool")
        return _err(f"Unexpected error: {e}")


async def cancel_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Cancel a previously scheduled pickup and emit pickup_result event.

    Args:
        args: Dict with cancel_by ("prn" or "account") and optional prn.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with cancellation status, or error envelope.
    """
    try:
        client = await _get_ups_client()
        cancel_by = args.get("cancel_by", "prn")
        prn = args.get("prn", "")
        result = await client.cancel_pickup(cancel_by=cancel_by, prn=prn)
        payload = {"action": "cancelled", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "cancelled"})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in cancel_pickup_tool")
        return _err(f"Unexpected error: {e}")


async def rate_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Get a pickup cost estimate and emit pickup_result event.

    Args:
        args: Dict with pickup_type, address fields, pickup_date,
              ready_time, close_time, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with rate estimate, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.rate_pickup(**args)
        payload = {"action": "rated", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "rated", **result})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in rate_pickup_tool")
        return _err(f"Unexpected error: {e}")


async def get_pickup_status_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Get pending pickup status and emit pickup_result event.

    Args:
        args: Dict with pickup_type and optional account_number.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with pickup status data, or error envelope.
    """
    try:
        client = await _get_ups_client()
        pickup_type = args.get("pickup_type", "oncall")
        account_number = args.get("account_number", "")
        result = await client.get_pickup_status(
            pickup_type=pickup_type,
            account_number=account_number,
        )
        payload = {"action": "status", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "status", **result})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_pickup_status_tool")
        return _err(f"Unexpected error: {e}")


async def find_locations_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Find nearby UPS locations and emit location_result event.

    Args:
        args: Dict with location_type, address fields, and optional radius.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with location list, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.find_locations(**args)
        payload = {"action": "locations", "success": True, **result}
        _emit_event("location_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "locations", **result})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in find_locations_tool")
        return _err(f"Unexpected error: {e}")


async def get_service_center_facilities_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Find UPS service center drop-off locations and emit location_result event.

    Args:
        args: Dict with city, state, postal_code, country_code.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with facility list, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.get_service_center_facilities(**args)
        payload = {"action": "service_centers", "success": True, **result}
        _emit_event("location_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "service_centers", **result})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_service_center_facilities_tool")
        return _err(f"Unexpected error: {e}")
