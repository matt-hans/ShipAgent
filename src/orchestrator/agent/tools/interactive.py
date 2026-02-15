"""Interactive shipment tool handlers.

Handles single-shipment preview with auto-populated shipper,
address normalization, and account masking.
"""

import json
import logging
import os
from typing import Any

from src.db.connection import get_db_context
from src.services.job_service import JobService

from src.orchestrator.agent.tools.core import (
    SERVICE_CODE_NAMES,
    EventEmitterBridge,
    _build_job_row_data,
    _emit_preview_ready,
    _enrich_preview_rows_from_map,
    _err,
    _get_ups_client,
    _ok,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ship-from normalization
# ---------------------------------------------------------------------------

_SHIP_FROM_KEY_MAP: dict[str, str] = {
    "name": "name",
    "phone": "phone",
    "address1": "addressLine1",
    "address_line1": "addressLine1",
    "addressLine1": "addressLine1",
    "city": "city",
    "state": "stateProvinceCode",
    "state_province_code": "stateProvinceCode",
    "stateProvinceCode": "stateProvinceCode",
    "zip": "postalCode",
    "postal_code": "postalCode",
    "postalCode": "postalCode",
    "country": "countryCode",
    "country_code": "countryCode",
    "countryCode": "countryCode",
}


def _normalize_ship_from(raw: dict[str, Any]) -> dict[str, str]:
    """Normalize agent-facing ship_from keys and values to canonical shipper format.

    Accepts any of the mapped key variants and produces the exact keys
    expected by downstream functions (build_shipment_request, ShipperInfo).
    Values are coerced to str and normalized:
    - phone -> normalize_phone() (strip non-digits, ensure 10-digit format)
    - postalCode -> normalize_zip() (strip to 5-digit or 5+4 format)
    Unknown keys are silently dropped. Empty values are skipped.

    Args:
        raw: Agent-provided ship_from override dict.

    Returns:
        Dict with canonical shipper keys and normalized values.
    """
    from src.services.ups_payload_builder import normalize_phone, normalize_zip

    normalized: dict[str, str] = {}
    for k, v in raw.items():
        canonical = _SHIP_FROM_KEY_MAP.get(k)
        if canonical and v:
            v = str(v).strip()
            if not v:
                continue
            if canonical == "phone":
                result = normalize_phone(v)
                if not result:
                    continue  # skip invalid phone override
                v = result
            elif canonical == "postalCode":
                v = normalize_zip(v)
            normalized[canonical] = v
    return normalized


def _mask_account(acct: str) -> str:
    """Mask a UPS account number for display.

    Args:
        acct: Raw account number string.

    Returns:
        Masked string showing only first 2 and last 2 characters.
    """
    if len(acct) <= 4:
        return "****"
    return acct[:2] + "*" * (len(acct) - 4) + acct[-2:]


async def preview_interactive_shipment_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Preview a single interactive shipment with auto-populated shipper.

    Resolves shipper from env vars (with optional overrides), creates a Job
    with is_interactive=True, rates the shipment, and emits a preview_ready
    SSE event for the frontend InteractivePreviewCard.

    Args:
        args: Dict with ship_to fields, optional service/weight/ship_from override.

    Returns:
        Tool response with preview data or error.
    """
    from src.db.models import JobStatus
    from src.services.batch_engine import BatchEngine
    from src.services.ups_payload_builder import (
        build_shipment_request,
        build_shipper_from_env,
        resolve_packaging_code,
    )
    from src.services.ups_service_codes import resolve_service_code

    # Safe coercion: None -> "", non-string -> str, then strip
    def _str(val: Any, default: str = "") -> str:
        if val is None:
            return default
        return str(val).strip()

    # Required fields
    ship_to_name = _str(args.get("ship_to_name"))
    ship_to_address1 = _str(args.get("ship_to_address1"))
    ship_to_city = _str(args.get("ship_to_city"))
    ship_to_state = _str(args.get("ship_to_state"))
    ship_to_zip = _str(args.get("ship_to_zip"))
    command = _str(args.get("command"))

    if not all([ship_to_name, ship_to_address1, ship_to_city, ship_to_zip]):
        return _err(
            "Missing required fields: ship_to_name, ship_to_address1, "
            "ship_to_city, ship_to_zip are all required."
        )

    # Optional fields
    ship_to_address2 = _str(args.get("ship_to_address2"))
    ship_to_phone = _str(args.get("ship_to_phone"))
    ship_to_state = _str(args.get("ship_to_state"))
    ship_to_country = (_str(args.get("ship_to_country"), "US") or "US").upper()
    ship_to_attention_name = _str(args.get("ship_to_attention_name"))
    shipment_description = _str(args.get("shipment_description"))
    commodities = args.get("commodities")
    invoice_currency_code = _str(args.get("invoice_currency_code")).upper()
    invoice_monetary_value = _str(args.get("invoice_monetary_value"))
    reason_for_export = _str(args.get("reason_for_export")).upper()
    service = _str(args.get("service"), "Ground")
    raw_packaging = args.get("packaging_type")
    packaging_type = str(raw_packaging).strip() if raw_packaging is not None else None

    # Validate weight
    try:
        weight = float(args.get("weight", 1.0))
        if weight <= 0:
            return _err("Weight must be a positive number.")
    except (ValueError, TypeError):
        return _err(
            f"Invalid weight value: {args.get('weight')!r}. "
            "Provide a numeric weight in pounds (e.g., 1.0, 5, 10.5)."
        )

    # Config guard: ensure UPS account number is set
    account_number = os.environ.get("UPS_ACCOUNT_NUMBER", "").strip()
    if not account_number:
        return _err(
            "UPS_ACCOUNT_NUMBER environment variable is not set. "
            "Configure it in your .env file before using interactive shipping."
        )

    # Resolve shipper from env, overlay optional overrides
    shipper = build_shipper_from_env()
    ship_from_override = args.get("ship_from")
    if isinstance(ship_from_override, dict) and ship_from_override:
        normalized_overrides = _normalize_ship_from(ship_from_override)
        for k, v in normalized_overrides.items():
            if v:
                shipper[k] = v

    # Resolve service code
    service_code = resolve_service_code(service)

    # Construct order_data with canonical keys.
    order_data: dict[str, Any] = {
        "ship_to_name": ship_to_name,
        "ship_to_address1": ship_to_address1,
        "ship_to_city": ship_to_city,
        "ship_to_postal_code": ship_to_zip,
        "ship_to_country": ship_to_country,
        "service_code": service_code,
        "weight": weight,
        "packaging_type": packaging_type,
    }
    if ship_to_state:
        order_data["ship_to_state"] = ship_to_state
    if ship_to_address2:
        order_data["ship_to_address2"] = ship_to_address2
    if ship_to_phone:
        order_data["ship_to_phone"] = ship_to_phone
    if ship_to_attention_name:
        order_data["ship_to_attention_name"] = ship_to_attention_name
    if shipment_description:
        order_data["shipment_description"] = shipment_description[:35]
    if isinstance(commodities, list) and commodities:
        order_data["commodities"] = commodities
    if invoice_currency_code:
        order_data["invoice_currency_code"] = invoice_currency_code
    if invoice_monetary_value:
        order_data["invoice_monetary_value"] = invoice_monetary_value
    if reason_for_export:
        order_data["reason_for_export"] = reason_for_export

    if ship_to_country not in ("US", ""):
        shipper_attention_name = _str(os.environ.get("SHIPPER_ATTENTION_NAME"))
        shipper_phone = _str(os.environ.get("SHIPPER_PHONE"))
        if shipper_attention_name:
            order_data["shipper_attention_name"] = shipper_attention_name
        if shipper_phone:
            order_data["shipper_phone"] = shipper_phone

    # Create Job with interactive flag
    try:
        with get_db_context() as db:
            job_service = JobService(db)
            job = job_service.create_job(
                name=f"Ship to {ship_to_name}",
                original_command=command or f"Ship to {ship_to_name}",
            )
            job.is_interactive = True
            job.shipper_json = json.dumps(shipper)
            db.commit()

            # Create single row
            try:
                job_service.create_rows(
                    job.id,
                    _build_job_row_data([order_data]),
                )
            except Exception as e:
                try:
                    job_service.delete_job(job.id)
                except Exception as cleanup_err:
                    logger.warning(
                        "interactive preview cleanup failed for job %s: %s",
                        job.id,
                        cleanup_err,
                    )
                logger.error("interactive preview create_rows failed: %s", e)
                return _err(f"Failed to create shipment row: {e}")

            # Rate via BatchEngine preview
            ups = await _get_ups_client()
            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            db_rows = job_service.get_rows(job.id)
            try:
                result = await engine.preview(
                    job_id=job.id,
                    rows=db_rows,
                    shipper=shipper,
                    service_code=service_code,
                )
            except Exception as e:
                job_service.update_status(job.id, JobStatus.failed)
                logger.error("interactive preview rate failed for job %s: %s", job.id, e)
                return _err(f"Rating failed for job {job.id}: {e}")

            job_id = job.id

    except Exception as e:
        logger.error("preview_interactive_shipment failed: %s", e)
        return _err(f"Failed to create interactive shipment: {e}")

    # Enrich preview rows
    preview_rows = result.get("preview_rows", [])
    row_map = {1: order_data}
    _enrich_preview_rows_from_map(preview_rows, row_map)
    rows_with_warnings = sum(1 for r in preview_rows if r.get("warnings"))
    result["rows_with_warnings"] = rows_with_warnings

    # Build resolved payload for expandable view
    try:
        resolved_payload = build_shipment_request(
            order_data=order_data,
            shipper=shipper,
            service_code=service_code,
        )
    except Exception:
        resolved_payload = {}

    # Add interactive metadata to result
    result["interactive"] = True
    result["shipper"] = shipper
    result["ship_to"] = {
        "name": ship_to_name,
        "address1": ship_to_address1,
        "address2": ship_to_address2,
        "city": ship_to_city,
        "state": ship_to_state,
        "postal_code": ship_to_zip,
        "country": ship_to_country,
        "phone": ship_to_phone,
    }
    result["account_number"] = _mask_account(account_number)
    result["service_name"] = SERVICE_CODE_NAMES.get(service_code, f"UPS Service {service_code}")
    result["service_code"] = service_code
    result["weight_lbs"] = weight
    result["packaging_type"] = resolve_packaging_code(packaging_type)
    result["resolved_payload"] = resolved_payload

    return _emit_preview_ready(
        result=result,
        rows_with_warnings=rows_with_warnings,
        bridge=bridge,
        job_id_override=job_id,
    )
