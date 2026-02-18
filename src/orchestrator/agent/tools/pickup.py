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
_ON_CALL_PICKUP_TYPE = "oncall"


async def schedule_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Schedule a UPS pickup and emit enriched pickup_result event.

    Requires ``confirmed=True`` in args as a safety gate — scheduling a
    pickup is a financial commitment.  The agent must first present
    pickup details to the user via rate_pickup and obtain explicit
    confirmation before calling this tool with ``confirmed=True``.

    Args:
        args: Dict with pickup_date, ready_time, close_time, address fields,
              contact_name, phone_number, confirmed flag, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with PRN on success, or error envelope.
    """
    if not args.pop("confirmed", False):
        return _err(
            "Safety gate: schedule_pickup requires explicit user confirmation. "
            "Present pickup details to the user first, then call again with "
            "confirmed=True."
        )
    # Capture input details for enriched completion event
    input_details = {
        "address_line": args.get("address_line", ""),
        "city": args.get("city", ""),
        "state": args.get("state", ""),
        "postal_code": args.get("postal_code", ""),
        "country_code": args.get("country_code", "US"),
        "pickup_date": args.get("pickup_date", ""),
        "ready_time": args.get("ready_time", ""),
        "close_time": args.get("close_time", ""),
        "contact_name": args.get("contact_name", ""),
        "phone_number": args.get("phone_number", ""),
    }
    try:
        client = await _get_ups_client()
        result = await client.schedule_pickup(**args)
        prn = result.get("prn", "unknown")
        payload = {
            "action": "scheduled",
            "success": True,
            "prn": prn,
            **input_details,
        }
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok(f"Pickup scheduled successfully. PRN: {prn}")
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

    Requires ``confirmed=True`` in args as a safety gate — cancelling a
    pickup is irreversible.

    Args:
        args: Dict with cancel_by ("prn" or "account"), optional prn,
              and confirmed flag.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with cancellation status, or error envelope.
    """
    if not args.pop("confirmed", False):
        return _err(
            "Safety gate: cancel_pickup requires explicit user confirmation. "
            "Present cancellation details to the user first, then call again "
            "with confirmed=True."
        )
    try:
        client = await _get_ups_client()
        cancel_by = args.get("cancel_by", "prn")
        prn = args.get("prn", "")
        result = await client.cancel_pickup(cancel_by=cancel_by, prn=prn)
        payload = {"action": "cancelled", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok("Pickup cancelled successfully.")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in cancel_pickup_tool")
        return _err(f"Unexpected error: {e}")


async def rate_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Get a pickup cost estimate and emit pickup_preview event.

    Emits a ``pickup_preview`` event containing the full pickup details
    (address, schedule, contact) alongside the rate charges, so the
    frontend can render a rich preview card with Confirm/Cancel buttons.

    Args:
        args: Dict with address fields, pickup_date, ready_time,
              close_time, contact_name, phone_number, and optional kwargs.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with rate estimate, or error envelope.
    """
    try:
        client = await _get_ups_client()
        # Extract input details before passing to client
        input_details = {
            "pickup_type": _ON_CALL_PICKUP_TYPE,
            "address_line": args.get("address_line", ""),
            "city": args.get("city", ""),
            "state": args.get("state", ""),
            "postal_code": args.get("postal_code", ""),
            "country_code": args.get("country_code", "US"),
            "pickup_date": args.get("pickup_date", ""),
            "ready_time": args.get("ready_time", ""),
            "close_time": args.get("close_time", ""),
            "contact_name": args.get("contact_name", ""),
            "phone_number": args.get("phone_number", ""),
        }
        rate_args = {
            **args,
            "pickup_type": _ON_CALL_PICKUP_TYPE,
        }
        result = await client.rate_pickup(**rate_args)
        # Emit pickup_preview with all details + rate
        payload = {
            **input_details,
            "charges": result.get("charges", []),
            "grand_total": result.get("grandTotal", "0"),
        }
        _emit_event("pickup_preview", payload, bridge=bridge)
        return _ok(
            "Pickup rate estimate displayed. Waiting for user to confirm or cancel "
            "via the preview card. Do NOT call schedule_pickup until the user confirms."
        )
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
        args: Dict with optional account_number.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with pickup status data, or error envelope.
    """
    try:
        client = await _get_ups_client()
        pickup_type = _ON_CALL_PICKUP_TYPE
        account_number = args.get("account_number", "")
        result = await client.get_pickup_status(
            pickup_type=pickup_type,
            account_number=account_number,
        )
        payload = {"action": "status", "success": True, **result}
        _emit_event("pickup_result", payload, bridge=bridge)
        return _ok("Pickup status displayed.")
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
        # Normalize and harden location search inputs so UPS receives a
        # location-returning query shape for drop-off searches.
        location_type_raw = str(args.get("location_type", "general")).strip().lower()
        location_type = location_type_raw if location_type_raw in {
            "access_point", "retail", "general", "services",
        } else "general"
        if location_type == "services":
            # Locator reqOption=8 returns available service attributes, not
            # DropLocation rows. For drop-off UX, prefer location-returning mode.
            location_type = "general"

        unit = str(args.get("unit_of_measure", "MI")).strip().upper() or "MI"
        if unit not in {"MI", "KM"}:
            unit = "MI"

        radius_raw = args.get("radius", 15.0)
        try:
            radius = float(radius_raw)
        except (TypeError, ValueError):
            radius = 15.0
        radius = max(1.0, radius)

        max_results_raw = args.get("max_results", 10)
        try:
            max_results = int(max_results_raw)
        except (TypeError, ValueError):
            max_results = 10
        max_results = max(1, min(max_results, 50))

        call_args = {
            "location_type": location_type,
            "address_line": str(args.get("address_line", "")).strip(),
            "city": str(args.get("city", "")).strip(),
            "state": str(args.get("state", "")).strip(),
            "postal_code": str(args.get("postal_code", "")).strip(),
            "country_code": str(args.get("country_code", "US")).strip().upper() or "US",
            "radius": radius,
            "unit_of_measure": unit,
            "max_results": max_results,
        }

        result = await client.find_locations(**call_args)

        # If a narrower mode returns nothing, retry once in general mode
        # to maximize location coverage for the UI card.
        if (
            (result.get("locations") or []) == []
            and call_args["location_type"] != "general"
        ):
            fallback_args = {**call_args, "location_type": "general"}
            fallback = await client.find_locations(**fallback_args)
            if fallback.get("locations"):
                result = fallback

        payload = {"action": "locations", "success": True, **result}
        _emit_event("location_result", payload, bridge=bridge)
        return _ok("Location results displayed.")
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
        return _ok("Service center results displayed.")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in get_service_center_facilities_tool")
        return _err(f"Unexpected error: {e}")
