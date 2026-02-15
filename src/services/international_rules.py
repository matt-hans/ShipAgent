"""International shipping rules engine.

Lane-driven requirements for international shipments. Given origin country,
destination country, and service code, returns exactly which fields are
required and what InternationalForms sections must be populated.

The rules engine is deterministic and testable — compliance logic lives
here, not in prompts or conversation flow.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import date


RULE_VERSION = "1.0.0"

# UPS international service codes
SUPPORTED_INTERNATIONAL_SERVICES: frozenset[str] = frozenset({
    "07",  # Worldwide Express
    "08",  # Worldwide Expedited
    "11",  # UPS Standard (international)
    "54",  # Worldwide Express Plus
    "65",  # Worldwide Saver
})

# Domestic-only services that cannot be used for international
DOMESTIC_ONLY_SERVICES: frozenset[str] = frozenset({
    "01",  # Next Day Air
    "02",  # 2nd Day Air
    "03",  # Ground
    "12",  # 3 Day Select
    "13",  # Next Day Air Saver
    "14",  # Next Day Air Early
})

# Lanes requiring InvoiceLineTotal
INVOICE_LINE_TOTAL_LANES: frozenset[str] = frozenset({"US-CA", "US-PR"})


@dataclass
class ValidationError:
    """Structured validation error with machine and human-readable info.

    Attributes:
        machine_code: Machine-readable error code (e.g., MISSING_RECIPIENT_PHONE).
        message: Human-readable error description.
        field_path: UPS API field path (e.g., ShipTo.Phone.Number).
        error_code: ShipAgent E-code for error translation.
    """

    machine_code: str
    message: str
    field_path: str
    error_code: str = "E-2013"


@dataclass
class RequirementSet:
    """Requirements for a specific shipping lane and service.

    Attributes:
        rule_version: Version of the rules that produced this result.
        effective_date: Date these rules became effective.
        is_international: Whether shipment crosses country borders.
        requires_description: Shipment description required.
        requires_shipper_contact: Shipper AttentionName + Phone required.
        requires_recipient_contact: Recipient AttentionName + Phone required.
        requires_invoice_line_total: InvoiceLineTotal section required.
        requires_international_forms: InternationalForms section required.
        requires_commodities: Commodity-level data required.
        supported_services: Service codes valid for this lane.
        currency_code: Default currency for this lane.
        form_type: InternationalForms type code (01 = commercial invoice).
        not_shippable_reason: If set, shipment cannot be created on this lane.
    """

    rule_version: str = RULE_VERSION
    effective_date: str = field(default_factory=lambda: date.today().isoformat())
    is_international: bool = False
    requires_description: bool = False
    requires_shipper_contact: bool = False
    requires_recipient_contact: bool = False
    requires_invoice_line_total: bool = False
    requires_international_forms: bool = False
    requires_commodities: bool = False
    supported_services: list[str] = field(default_factory=list)
    currency_code: str = "USD"
    form_type: str = "01"
    not_shippable_reason: str | None = None


def is_lane_enabled(origin: str, destination: str) -> bool:
    """Check if a shipping lane is enabled via feature flag.

    Args:
        origin: Origin country code (e.g., US).
        destination: Destination country code (e.g., CA).

    Returns:
        True if the lane is enabled.
    """
    enabled = os.environ.get("INTERNATIONAL_ENABLED_LANES", "")
    if not enabled:
        return False
    lanes = {lane.strip().upper() for lane in enabled.split(",")}
    return f"{origin.upper()}-{destination.upper()}" in lanes


def get_requirements(
    origin: str,
    destination: str,
    service_code: str,
) -> RequirementSet:
    """Get international shipping requirements for a lane and service.

    Args:
        origin: Origin country code (e.g., US).
        destination: Destination country code (e.g., CA).
        service_code: UPS service code (e.g., 11).

    Returns:
        RequirementSet with all field requirements for this lane.
    """
    origin = origin.upper().strip()
    destination = destination.upper().strip()
    service_code = service_code.strip()
    lane_key = f"{origin}-{destination}"

    # Domestic shipment (same country, not PR)
    if origin == destination and destination != "PR":
        return RequirementSet(
            is_international=False,
            supported_services=list(DOMESTIC_ONLY_SERVICES | SUPPORTED_INTERNATIONAL_SERVICES),
        )

    # US→PR: US territory but requires InvoiceLineTotal for billing
    if origin == "US" and destination == "PR":
        return RequirementSet(
            is_international=False,
            requires_invoice_line_total=True,
            supported_services=list(DOMESTIC_ONLY_SERVICES | SUPPORTED_INTERNATIONAL_SERVICES),
        )

    # International: check if lane is supported
    supported_lanes = {"US-CA", "US-MX"}
    if lane_key not in supported_lanes:
        return RequirementSet(
            is_international=True,
            not_shippable_reason=(
                f"Shipping lane {origin} to {destination} is not currently supported. "
                f"Supported lanes: {', '.join(sorted(supported_lanes))}."
            ),
        )

    # P0 KILL SWITCH: Enforce feature flag BEFORE checking service codes.
    # If lane is not enabled via INTERNATIONAL_ENABLED_LANES env var,
    # return not_shippable immediately. This is the production safety gate.
    if not is_lane_enabled(origin, destination):
        return RequirementSet(
            is_international=True,
            not_shippable_reason=(
                f"International shipping to {destination} is not enabled. "
                f"Set INTERNATIONAL_ENABLED_LANES to include {lane_key} to enable."
            ),
        )

    # Check service code is valid for international
    if service_code in DOMESTIC_ONLY_SERVICES:
        return RequirementSet(
            is_international=True,
            not_shippable_reason=(
                f"Service '{service_code}' is domestic-only and cannot be used for "
                f"{origin} to {destination}. Use an international service: "
                f"{', '.join(sorted(SUPPORTED_INTERNATIONAL_SERVICES))}."
            ),
        )

    if service_code not in SUPPORTED_INTERNATIONAL_SERVICES:
        return RequirementSet(
            is_international=True,
            not_shippable_reason=(
                f"Unknown service code '{service_code}'. Supported international services: "
                f"{', '.join(sorted(SUPPORTED_INTERNATIONAL_SERVICES))}."
            ),
        )

    # Valid international lane + service
    return RequirementSet(
        is_international=True,
        requires_description=True,
        requires_shipper_contact=True,
        requires_recipient_contact=True,
        requires_invoice_line_total=lane_key in INVOICE_LINE_TOTAL_LANES,
        requires_international_forms=True,
        requires_commodities=True,
        supported_services=list(SUPPORTED_INTERNATIONAL_SERVICES),
        currency_code="USD",
        form_type="01",
    )


def validate_international_readiness(
    order_data: dict,
    requirements: RequirementSet,
) -> list[ValidationError]:
    """Validate that order data has all required international fields.

    Args:
        order_data: Order data dict (from JobRow.order_data JSON).
        requirements: Requirements from get_requirements().

    Returns:
        List of ValidationError objects (empty if valid).
    """
    if not requirements.is_international and not requirements.requires_invoice_line_total:
        return []

    errors: list[ValidationError] = []

    def _check(key: str, machine_code: str, message: str, field_path: str) -> None:
        """Check if a required field is present and non-empty."""
        val = order_data.get(key)
        if not val or (isinstance(val, str) and not val.strip()):
            errors.append(ValidationError(
                machine_code=machine_code,
                message=message,
                field_path=field_path,
            ))

    # Shipper contact
    if requirements.requires_shipper_contact:
        _check(
            "shipper_attention_name", "MISSING_SHIPPER_ATTENTION_NAME",
            "Shipper attention name is required for international shipments.",
            "Shipper.AttentionName",
        )
        _check(
            "shipper_phone", "MISSING_SHIPPER_PHONE",
            "Shipper phone number is required for international shipments.",
            "Shipper.Phone.Number",
        )

    # Recipient contact
    if requirements.requires_recipient_contact:
        _check(
            "ship_to_attention_name", "MISSING_RECIPIENT_ATTENTION_NAME",
            "Recipient attention name is required for international shipments.",
            "ShipTo.AttentionName",
        )
        _check(
            "ship_to_phone", "MISSING_RECIPIENT_PHONE",
            "Recipient phone number is required for international shipments.",
            "ShipTo.Phone.Number",
        )

    # Description
    if requirements.requires_description:
        _check(
            "shipment_description", "MISSING_SHIPMENT_DESCRIPTION",
            "Description of goods is required for international shipments.",
            "Shipment.Description",
        )

    # InvoiceLineTotal
    if requirements.requires_invoice_line_total:
        _check(
            "invoice_currency_code", "MISSING_INVOICE_CURRENCY",
            "Invoice currency code is required for this shipping lane.",
            "InvoiceLineTotal.CurrencyCode",
        )
        _check(
            "invoice_monetary_value", "MISSING_INVOICE_VALUE",
            "Invoice total monetary value is required for this shipping lane.",
            "InvoiceLineTotal.MonetaryValue",
        )

    # Extract commodities early — used by both requires_commodities and currency checks.
    # Must be assigned before either block to avoid UnboundLocalError when
    # requires_invoice_line_total=True but requires_commodities=False (e.g., US→PR).
    commodities = order_data.get("commodities") or []

    # Commodities
    if requirements.requires_commodities:
        if not commodities or not isinstance(commodities, list) or len(commodities) == 0:
            errors.append(ValidationError(
                machine_code="MISSING_COMMODITIES",
                message="At least one commodity is required for international shipments.",
                field_path="InternationalForms.Product",
            ))
        else:
            for i, comm in enumerate(commodities):
                if not comm.get("description"):
                    errors.append(ValidationError(
                        machine_code="MISSING_COMMODITY_DESCRIPTION",
                        message=f"Commodity {i+1} is missing a description.",
                        field_path=f"InternationalForms.Product[{i}].Description",
                    ))
                hs = comm.get("commodity_code", "")
                if hs and not re.match(r"^\d{6,10}$", str(hs)):
                    errors.append(ValidationError(
                        machine_code="INVALID_HS_CODE",
                        message=f"Commodity {i+1} has invalid HS code '{hs}'. Must be 6-10 digits.",
                        field_path=f"InternationalForms.Product[{i}].CommodityCode",
                        error_code="E-2014",
                    ))
                elif not hs:
                    errors.append(ValidationError(
                        machine_code="MISSING_HS_CODE",
                        message=f"Commodity {i+1} is missing HS tariff code.",
                        field_path=f"InternationalForms.Product[{i}].CommodityCode",
                    ))
                if not comm.get("origin_country"):
                    errors.append(ValidationError(
                        machine_code="MISSING_ORIGIN_COUNTRY",
                        message=f"Commodity {i+1} is missing origin country.",
                        field_path=f"InternationalForms.Product[{i}].OriginCountryCode",
                    ))
                qty = comm.get("quantity")
                if qty is None or (isinstance(qty, (int, float)) and qty <= 0):
                    errors.append(ValidationError(
                        machine_code="INVALID_COMMODITY_QUANTITY",
                        message=f"Commodity {i+1} must have a positive quantity.",
                        field_path=f"InternationalForms.Product[{i}].Unit.Number",
                    ))
                val = comm.get("unit_value")
                if val is None:
                    errors.append(ValidationError(
                        machine_code="MISSING_COMMODITY_VALUE",
                        message=f"Commodity {i+1} is missing unit value.",
                        field_path=f"InternationalForms.Product[{i}].Unit.Value",
                    ))

    # P2: Currency mismatch validation (E-2017)
    # If InvoiceLineTotal is required, verify commodity currencies match invoice currency
    if requirements.requires_invoice_line_total and commodities:
        invoice_currency = order_data.get("invoice_currency_code", "").upper()
        if invoice_currency:
            for i, comm in enumerate(commodities):
                comm_currency = str(comm.get("currency_code", invoice_currency)).upper()
                if comm_currency != invoice_currency:
                    errors.append(ValidationError(
                        machine_code="CURRENCY_MISMATCH",
                        message=(
                            f"Commodity {i+1} uses currency '{comm_currency}' "
                            f"but invoice uses '{invoice_currency}'."
                        ),
                        field_path=f"InternationalForms.Product[{i}].Unit.Value",
                        error_code="E-2017",
                    ))

    return errors
