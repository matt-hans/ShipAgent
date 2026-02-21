"""Interactive shipment tool handlers.

Handles single-shipment preview with auto-populated shipper,
address normalization, and account masking.
"""

import json
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any

from src.db.connection import get_db_context
from src.orchestrator.agent.tools.core import (
    SERVICE_CODE_NAMES,
    EventEmitterBridge,
    _build_job_row_data,
    _emit_event,
    _emit_preview_ready,
    _enrich_preview_rows_from_map,
    _err,
    _get_ups_client,
)
from src.services.job_service import JobService

logger = logging.getLogger(__name__)

_COUNTRY_CODE_ALIASES: dict[str, str] = {
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "ENGLAND": "GB",
}
_STATE_REQUIRED_COUNTRIES: frozenset[str] = frozenset({"US", "CA", "PR"})


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


def _to_cents(amount: Any) -> int:
    """Convert UPS monetary values to integer cents with safe fallback."""
    try:
        value = Decimal(str(amount if amount is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    return int((value * 100).quantize(Decimal("1")))


def _extract_available_services(shop_result: Any) -> list[dict[str, Any]]:
    """Extract and normalize available service options from UPS Shop response."""
    if not isinstance(shop_result, dict):
        return []
    rated = shop_result.get("ratedShipments", [])
    if not isinstance(rated, list):
        return []

    deduped: dict[str, dict[str, Any]] = {}
    for item in rated:
        if not isinstance(item, dict):
            continue
        code = str(item.get("serviceCode", "")).strip()
        if not code:
            continue
        total = item.get("totalCharges", {}) if isinstance(item.get("totalCharges"), dict) else {}
        monetary = str(total.get("monetaryValue", "0"))
        svc = {
            "code": code,
            "name": str(item.get("serviceName") or SERVICE_CODE_NAMES.get(code, f"UPS Service {code}")),
            "description": str(item.get("serviceDescription") or ""),
            "estimated_cost_cents": _to_cents(monetary),
            "total_charges": {
                "monetary_value": monetary,
                "currency_code": str(total.get("currencyCode", "USD")),
            },
            "delivery_days": item.get("deliveryDays"),
            "selected": False,
        }
        prev = deduped.get(code)
        if prev is None or svc["estimated_cost_cents"] < prev["estimated_cost_cents"]:
            deduped[code] = svc

    return sorted(deduped.values(), key=lambda s: (s["estimated_cost_cents"], s["code"]))


def _format_services_for_error(services: list[dict[str, Any]], limit: int = 6) -> str:
    """Render a short, human-readable service list for validation errors."""
    labels: list[str] = []
    for svc in services[:limit]:
        labels.append(f"{svc['name']} ({svc['code']})")
    return ", ".join(labels)


def _normalize_country_code(raw: str, default: str) -> str:
    """Normalize destination country to an uppercase ISO-like code."""
    upper = raw.strip().upper()
    if not upper:
        return default
    return _COUNTRY_CODE_ALIASES.get(upper, upper)


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
    from src.services.errors import UPSServiceError
    from src.services.international_rules import (
        get_requirements,
        recipient_state_required,
        validate_international_readiness,
    )
    from src.services.ups_constants import DEFAULT_ORIGIN_COUNTRY, UPS_ADDRESS_MAX_LEN
    from src.services.ups_payload_builder import (
        build_shipment_request,
        build_shipper,
        build_ups_rate_payload,
        resolve_packaging_code,
    )
    from src.services.ups_service_codes import (
        SUPPORTED_INTERNATIONAL_SERVICES,
        resolve_service_code,
        upgrade_to_international,
    )

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
    raw_service = _str(args.get("service"))
    raw_weight = args.get("weight")

    missing_fields: list[str] = []
    if not ship_to_name:
        missing_fields.append("ship_to_name")
    if not ship_to_address1:
        missing_fields.append("ship_to_address1")
    if not ship_to_city:
        missing_fields.append("ship_to_city")
    if not ship_to_zip:
        missing_fields.append("ship_to_zip")
    if not raw_service:
        missing_fields.append("service")
    if raw_weight is None or (isinstance(raw_weight, str) and not raw_weight.strip()):
        missing_fields.append("weight")
    if missing_fields:
        return _err(
            "Missing required fields: "
            f"{', '.join(missing_fields)}."
        )

    # Optional fields
    ship_to_address2 = _str(args.get("ship_to_address2"))
    ship_to_phone = _str(args.get("ship_to_phone"))
    ship_to_state = _str(args.get("ship_to_state"))
    raw_ship_to_country = _str(args.get("ship_to_country")).upper()
    ship_to_country = _normalize_country_code(
        raw_ship_to_country,
        DEFAULT_ORIGIN_COUNTRY,
    )
    ship_to_attention_name = _str(args.get("ship_to_attention_name"))
    # Operational default: if user gives a recipient, use that same name
    # for attention unless they explicitly provide an alternate contact.
    effective_attention_name = ship_to_attention_name or ship_to_name
    shipment_description = _str(args.get("shipment_description")) or _str(args.get("description"))
    commodities = args.get("commodities")
    invoice_currency_code = _str(args.get("invoice_currency_code")).upper()
    invoice_monetary_value = _str(args.get("invoice_monetary_value"))
    invoice_number = _str(
        args.get("invoice_number") or args.get("intl_forms_invoice_number")
    )
    reason_for_export = _str(args.get("reason_for_export")).upper()
    service = raw_service
    raw_packaging = args.get("packaging_type")
    packaging_type = str(raw_packaging).strip() if raw_packaging is not None else None

    # Validate weight
    try:
        weight = float(raw_weight)
        if weight <= 0:
            return _err("Weight must be a positive number.")
    except (ValueError, TypeError):
        return _err(
            f"Invalid weight value: {raw_weight!r}. "
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
    shipper = build_shipper()
    ship_from_override = args.get("ship_from")
    if isinstance(ship_from_override, dict) and ship_from_override:
        normalized_overrides = _normalize_ship_from(ship_from_override)
        for k, v in normalized_overrides.items():
            if v:
                shipper[k] = v

    # Resolve service code, auto-upgrade for international destinations
    requested_service_code = resolve_service_code(service)
    if (
        not raw_ship_to_country
        and requested_service_code in SUPPORTED_INTERNATIONAL_SERVICES
    ):
        return _err(
            "ship_to_country is required when using an international service. "
            "Provide a 2-letter destination country code (e.g., GB for UK)."
        )
    shipper_country = (
        _str(shipper.get("countryCode"), DEFAULT_ORIGIN_COUNTRY)
        or DEFAULT_ORIGIN_COUNTRY
    ).upper()
    service_code = upgrade_to_international(
        requested_service_code,
        shipper_country,
        ship_to_country,
    )

    # Auto-derive shipment_description from commodities if not provided
    if not shipment_description and isinstance(commodities, list) and commodities:
        first_desc = _str(commodities[0].get("description") if isinstance(commodities[0], dict) else None)
        if first_desc:
            shipment_description = first_desc[:UPS_ADDRESS_MAX_LEN]

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
    if effective_attention_name:
        order_data["ship_to_attention_name"] = effective_attention_name
    if shipment_description:
        order_data["shipment_description"] = shipment_description[:UPS_ADDRESS_MAX_LEN]
    if isinstance(commodities, list) and commodities:
        order_data["commodities"] = commodities
    if invoice_currency_code:
        order_data["invoice_currency_code"] = invoice_currency_code
    if invoice_monetary_value:
        order_data["invoice_monetary_value"] = invoice_monetary_value
    if invoice_number:
        order_data["invoice_number"] = invoice_number[:UPS_ADDRESS_MAX_LEN]
    if reason_for_export:
        order_data["reason_for_export"] = reason_for_export

    if (
        not ship_to_state
        and (
            ship_to_country in _STATE_REQUIRED_COUNTRIES
            or recipient_state_required(ship_to_country)
        )
    ):
        return _err(
            "Recipient state/province code is required for shipments "
            f"to {ship_to_country}."
        )

    if ship_to_country not in (DEFAULT_ORIGIN_COUNTRY, ""):
        shipper_attention_name = _str(os.environ.get("SHIPPER_ATTENTION_NAME"))
        shipper_phone = _str(os.environ.get("SHIPPER_PHONE"))
        if shipper_attention_name:
            order_data["shipper_attention_name"] = shipper_attention_name
        if shipper_phone:
            order_data["shipper_phone"] = shipper_phone

    # Deterministic pre-validation: fail fast on missing required fields
    # before any external discovery/rating calls.
    requirements = get_requirements(shipper_country, ship_to_country, service_code)
    if requirements.not_shippable_reason:
        return _err(requirements.not_shippable_reason)

    if requirements.is_international or requirements.requires_invoice_line_total:
        validation_errors = validate_international_readiness(order_data, requirements)
        if validation_errors:
            unique_messages: list[str] = []
            for err in validation_errors:
                if err.message not in unique_messages:
                    unique_messages.append(err.message)
            return _err("; ".join(unique_messages))

    # Reuse one UPS client for service discovery and preview rating.
    ups = await _get_ups_client()

    # Discover route-available services via UPS Shop.
    available_services: list[dict[str, Any]] = []
    try:
        shop_simplified = build_shipment_request(
            order_data=order_data,
            shipper=shipper,
            service_code=service_code,
        )
        shop_payload = build_ups_rate_payload(
            shop_simplified,
            account_number=account_number,
            request_option="Shop",
            include_service=False,
        )
        shop_result = await ups.get_rate(
            request_body=shop_payload,
            requestoption="Shop",
        )
        available_services = _extract_available_services(shop_result)
    except UPSServiceError as e:
        logger.warning("interactive service discovery failed: %s", e)
    except Exception as e:
        logger.warning("interactive service discovery error: %s", e)

    if available_services:
        available_codes = {svc["code"] for svc in available_services}
        if service_code not in available_codes:
            options = _format_services_for_error(available_services)
            return _err(
                f"Requested service '{service}' is not available for this route. "
                f"Available services: {options}."
            )

        for svc in available_services:
            svc["selected"] = svc["code"] == service_code

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
            engine = BatchEngine(
                ups_service=ups,
                db_session=db,
                account_number=account_number,
            )
            db_rows = job_service.get_rows(job.id)
            def _emit_preview_partial(payload: dict[str, Any]) -> None:
                _emit_event("preview_partial", payload, bridge=bridge)
            try:
                result = await engine.preview(
                    job_id=job.id,
                    rows=db_rows,
                    shipper=shipper,
                    service_code=service_code,
                    on_preview_partial=_emit_preview_partial,
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
        "attention_name": effective_attention_name,
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
    result["available_services"] = available_services
    result["weight_lbs"] = weight
    result["packaging_type"] = resolve_packaging_code(packaging_type)
    result["resolved_payload"] = resolved_payload

    return _emit_preview_ready(
        result=result,
        rows_with_warnings=rows_with_warnings,
        bridge=bridge,
        job_id_override=job_id,
    )
