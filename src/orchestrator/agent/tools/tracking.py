"""Tracking tool handler for the orchestration agent.

Wraps UPS track_package via UPSMCPClient and emits a tracking_result
event for the frontend TrackingCard. Includes mismatch detection for
sandbox environments where UPS may return a different tracking number.
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


async def track_package_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Track a UPS package and emit tracking_result event.

    Calls UPS track_package via the MCP client, extracts activity data,
    and detects tracking number mismatches (common in sandbox mode).

    Args:
        args: Dict with tracking_number (required).
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with tracking data on success, or error envelope.
    """
    tracking_number = args.get("tracking_number", "").strip()
    if not tracking_number:
        return _err("Missing required parameter: tracking_number")

    try:
        client = await _get_ups_client()
        raw = await client.track_package(tracking_number=tracking_number)

        # Extract tracking details from UPS response
        shipment = (
            raw.get("trackResponse", {})
            .get("shipment", [{}])
        )
        if isinstance(shipment, list):
            shipment = shipment[0] if shipment else {}

        package = shipment.get("package", [{}])
        if isinstance(package, list):
            package = package[0] if package else {}

        # Extract returned tracking number
        returned_number = package.get("trackingNumber", "")

        # Extract current status
        current_status = package.get("currentStatus", {})
        status_desc = current_status.get("description", "")
        status_code = current_status.get("code", "")

        # Extract delivery date
        delivery_date = package.get("deliveryDate", [{}])
        if isinstance(delivery_date, list):
            delivery_date = delivery_date[0] if delivery_date else {}
        delivery_date_str = delivery_date.get("date", "") if isinstance(delivery_date, dict) else ""

        # Extract activity history
        activities_raw = package.get("activity", [])
        if isinstance(activities_raw, dict):
            activities_raw = [activities_raw]

        activities = []
        for act in activities_raw[:20]:  # Cap at 20 most recent
            location = act.get("location", {})
            address = location.get("address", {})
            location_str = ", ".join(
                p for p in [
                    address.get("city", ""),
                    address.get("stateProvince", ""),
                    address.get("countryCode", ""),
                ] if p
            )
            status = act.get("status", {})
            activities.append({
                "date": act.get("date", ""),
                "time": act.get("time", ""),
                "location": location_str,
                "status": status.get("description", ""),
            })

        # Detect mismatch (sandbox returns different tracking numbers)
        mismatch = bool(
            returned_number
            and returned_number != tracking_number
        )

        payload: dict[str, Any] = {
            "action": "tracked",
            "success": True,
            "trackingNumber": returned_number or tracking_number,
            "currentStatus": status_code,
            "statusDescription": status_desc,
            "activities": activities,
        }

        if delivery_date_str:
            payload["deliveryDate"] = delivery_date_str

        if mismatch:
            payload["mismatch"] = True
            payload["requestedNumber"] = tracking_number

        _emit_event("tracking_result", payload, bridge=bridge)

        # Return minimal response — the TrackingCard already displays
        # all details. A verbose response here causes the LLM to
        # paraphrase the same info as redundant text.
        summary = f"Tracking result displayed for {returned_number or tracking_number}."
        if mismatch:
            summary += f" Note: sandbox returned {returned_number} instead of {tracking_number}."
        return _ok(summary)

    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in track_package_tool")
        return _err(f"Unexpected error: {e}")
