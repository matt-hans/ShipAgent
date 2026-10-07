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
    """Reject model execution; the preview card owns the confirmation action."""
    return _err(
        "Safety gate: pickups are scheduled only when the user presses Confirm "
        "on a priced pickup preview. Call rate_pickup to prepare that preview."
    )


async def cancel_pickup_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Prepare cancellation; a model call can never cancel the pickup."""
    if bridge is None or not bridge.session_id:
        return _err("A conversation is required to confirm a pickup cancellation.")
    bridge.workflow_actions.invalidate("cancel_pickup")
    cancel_by = args.get("cancel_by", "prn")
    prn = args.get("prn", "")
    if cancel_by not in {"prn", "account"} or not isinstance(prn, str):
        return _err("Specify a valid pickup request number (PRN) to cancel.")
    prn = prn.strip()
    if cancel_by == "prn" and not prn:
        return _err("Specify the pickup request number (PRN) to preview cancellation.")
    try:
        client = await _get_ups_client()
        if cancel_by == "account":
            result = await client.get_pickup_status(
                pickup_type=_ON_CALL_PICKUP_TYPE, account_number=""
            )
            pickups = result.get("pickups", [])
            # Never bind authority to a moving 'latest pickup' target. Resolve
            # a single pending PRN now or ask the user to choose explicitly.
            if (
                result.get("success") is not True
                or not isinstance(pickups, list)
                or len(pickups) != 1
            ):
                return _err(
                    "Choose a specific PRN from pickup status before cancelling."
                )
            prn = pickups[0].get("prn")
            if not isinstance(prn, str) or not prn.strip():
                return _err("No specific pickup PRN was returned. Check pickup status.")
            prn = prn.strip()
    except Exception as exc:
        logger.warning(
            "Pickup cancellation preparation failed exception_type=%s",
            type(exc).__name__,
        )
        return _err(
            "Pickup cancellation preview failed. Check pickup status and try again."
        )
    details = {"cancel_by": "prn", "prn": prn}
    token = bridge.workflow_actions.prepare("cancel_pickup", details, client)
    _emit_event(
        "pickup_preview",
        {
            "action": "cancel",
            **details,
            "confirmation_token": token,
            "session_id": bridge.session_id,
        },
        bridge=bridge,
    )
    return _ok(
        "Pickup cancellation preview displayed. Waiting for the user to confirm or cancel."
    )


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
    from pydantic import ValidationError

    from src.services.workflow_confirmation import PickupDetails, valid_pickup_quote

    if bridge is None or not bridge.session_id:
        return _err("A conversation is required to confirm a pickup.")
    # Re-preview intent revokes old authority even if validation or pricing fails.
    bridge.workflow_actions.invalidate("schedule_pickup")
    try:
        details = PickupDetails.model_validate(
            {key: value for key, value in args.items() if key != "pickup_type"}
        ).model_dump()
    except ValidationError:
        return _err(
            "Invalid pickup details. Provide an address, contact, phone, YYYYMMDD date and valid ready/close times."
        )
    try:
        client = await _get_ups_client()
        result = await client.rate_pickup(**details, pickup_type=_ON_CALL_PICKUP_TYPE)
        if not valid_pickup_quote(result):
            return _err(
                "No valid pickup rate was returned. Request a new quote before scheduling."
            )
        token = bridge.workflow_actions.prepare("schedule_pickup", details, client)
        _emit_event(
            "pickup_preview",
            {
                **details,
                "pickup_type": _ON_CALL_PICKUP_TYPE,
                "charges": result.get("charges", []),
                "grand_total": str(result["grandTotal"]),
                "confirmation_token": token,
                "session_id": bridge.session_id,
                "action": "schedule",
            },
            bridge=bridge,
        )
        return _ok(
            "Pickup rate estimate displayed. Waiting for the user to confirm or cancel via the preview card."
        )
    except UPSServiceError as exc:
        return _err(f"[{exc.code}] Pickup pricing failed. Request a new quote.")
    except Exception as exc:
        logger.warning("Pickup pricing failed exception_type=%s", type(exc).__name__)
        return _err("Pickup pricing failed. Request a new quote.")


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
        logger.warning(
            "Unexpected error in get_pickup_status_tool exception_type=%s",
            type(e).__name__,
        )
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
        logger.warning(
            "Unexpected error in find_locations_tool exception_type=%s",
            type(e).__name__,
        )
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
        logger.warning(
            "Unexpected error in get_service_center_facilities_tool exception_type=%s",
            type(e).__name__,
        )
        return _err(f"Unexpected error: {e}")
