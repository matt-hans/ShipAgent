"""Pickup and location tool handlers for the orchestration agent.

Handles: schedule_pickup, cancel_pickup, rate_pickup, get_pickup_status,
find_locations, get_service_center_facilities.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import logging
import os
import time
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

# HMAC confirmation token infrastructure (H-2, CWE-347).
# Mirrors the filter token pattern in hooks.py.
_PICKUP_TOKEN_TTL_SECONDS = 600  # 10 minutes
_PICKUP_TOKEN_SECRET: str | None = None


def _get_pickup_token_secret() -> str:
    """Return the pickup confirmation token secret.

    Uses FILTER_TOKEN_SECRET env var (shared with filter enforcement).
    Falls back to a process-unique random secret.
    """
    global _PICKUP_TOKEN_SECRET
    if _PICKUP_TOKEN_SECRET is None:
        _PICKUP_TOKEN_SECRET = os.environ.get(
            "FILTER_TOKEN_SECRET", ""
        ) or hashlib.sha256(os.urandom(32)).hexdigest()
    return _PICKUP_TOKEN_SECRET


def _issue_pickup_token(action: str, details_hash: str) -> str:
    """Issue an HMAC-signed confirmation token for a pickup action.

    Args:
        action: The action being confirmed ("schedule" or "cancel").
        details_hash: SHA-256 hash of the operation details.

    Returns:
        Base64-encoded signed token string.
    """
    secret = _get_pickup_token_secret()
    payload = {
        "action": action,
        "details_hash": details_hash,
        "expires_at": time.time() + _PICKUP_TOKEN_TTL_SECONDS,
    }
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac_mod.new(
        secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()
    payload["signature"] = signature
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _validate_pickup_token(token: str, action: str, details_hash: str) -> str | None:
    """Validate an HMAC-signed pickup confirmation token.

    Args:
        token: Base64-encoded signed token.
        action: Expected action ("schedule" or "cancel").
        details_hash: Expected SHA-256 hash of operation details.

    Returns:
        None if valid, error message string if invalid.
    """
    secret = _get_pickup_token_secret()
    try:
        decoded = json.loads(base64.b64decode(token))
    except Exception:
        return "Confirmation token is malformed."

    if time.time() > decoded.get("expires_at", 0):
        return "Confirmation token has expired. Re-run the preview/rate step."

    signature = decoded.pop("signature", None)
    if signature is None:
        return "Confirmation token missing signature."

    payload_json = json.dumps(decoded, sort_keys=True)
    expected_sig = hmac_mod.new(
        secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac_mod.compare_digest(signature, expected_sig):
        return "Confirmation token signature is invalid (tampered)."

    if decoded.get("action") != action:
        return f"Token action mismatch: expected '{action}', got '{decoded.get('action')}'."

    if decoded.get("details_hash") != details_hash:
        return "Confirmation token details do not match the current request."

    return None


def _hash_pickup_details(details: dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash of pickup operation details.

    Args:
        details: Dict of pickup parameters to hash.

    Returns:
        Hex digest string.
    """
    canonical = json.dumps(details, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


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

    # Safety gate: validate HMAC confirmation token (H-2, CWE-347).
    # The token proves that rate_pickup was called and the user saw the preview.
    # Falls back to boolean confirmed=True for backward compatibility with
    # existing agent prompts, but token is preferred.
    confirmation_token = args.pop("confirmation_token", None)
    if confirmation_token:
        details_hash = _hash_pickup_details(input_details)
        token_error = _validate_pickup_token(confirmation_token, "schedule", details_hash)
        if token_error:
            return _err(f"Safety gate: {token_error}")
    elif not args.pop("confirmed", False):
        return _err(
            "Safety gate: schedule_pickup requires explicit user confirmation. "
            "Present pickup details to the user first via rate_pickup, then call "
            "again with the confirmation_token from the rate response."
        )

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
    # Safety gate: validate HMAC confirmation token (H-2, CWE-347).
    cancel_details = {
        "cancel_by": args.get("cancel_by", "prn"),
        "prn": args.get("prn", ""),
    }
    confirmation_token = args.pop("confirmation_token", None)
    if confirmation_token:
        details_hash = _hash_pickup_details(cancel_details)
        token_error = _validate_pickup_token(confirmation_token, "cancel", details_hash)
        if token_error:
            return _err(f"Safety gate: {token_error}")
    elif not args.pop("confirmed", False):
        return _err(
            "Safety gate: cancel_pickup requires explicit user confirmation. "
            "Present cancellation details to the user first, then call again "
            "with a confirmation_token."
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
        # Issue HMAC-signed confirmation token (H-2, CWE-347)
        details_hash = _hash_pickup_details(input_details)
        confirmation_token = _issue_pickup_token("schedule", details_hash)

        # Emit pickup_preview with all details + rate + token
        payload = {
            **input_details,
            "charges": result.get("charges", []),
            "grand_total": result.get("grandTotal", "0"),
            "confirmation_token": confirmation_token,
        }
        _emit_event("pickup_preview", payload, bridge=bridge)
        return _ok(
            "Pickup rate estimate displayed. Waiting for user to confirm or cancel "
            "via the preview card. Do NOT call schedule_pickup until the user confirms. "
            f"Pass confirmation_token={confirmation_token!r} when calling schedule_pickup."
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
