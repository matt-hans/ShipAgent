# International Shipping (CA/MX) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable ShipAgent to create international shipments to Canada and Mexico, including InternationalForms with multi-commodity support, itemized cost breakdown, and all UPS-required contact/invoice fields.

**Architecture:** Payload-centric approach — a new `international_rules.py` module provides lane-driven requirements, the payload builder gains an international enrichment stage that builds InternationalForms from commodity data, and the response parser extracts duty/tax charges. The agent learns international services and guidance but does not own compliance logic.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, React/TypeScript, DuckDB (data source MCP), UPS MCP (stdio)

**Design doc:** `docs/plans/2026-02-15-international-shipping-design.md`

---

## Phase 1: Foundation (DB, Errors, Rules Engine)

### Task 1: Add International Error Codes

**Files:**
- Modify: `src/errors/registry.py` (after line 130, before E-3xxx section)
- Test: `tests/errors/test_international_error_codes.py`

**Step 1: Write the failing test**

Create `tests/errors/test_international_error_codes.py`:

```python
"""Tests for international shipping error codes."""

from src.errors.registry import get_error, ErrorCategory


class TestInternationalErrorCodes:
    """Verify international error codes are registered and well-formed."""

    def test_e2013_missing_international_field(self):
        err = get_error("E-2013")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{field_name}" in err.message_template
        assert err.is_retryable is False

    def test_e2014_invalid_hs_code(self):
        err = get_error("E-2014")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{hs_code}" in err.message_template

    def test_e2015_unsupported_lane(self):
        err = get_error("E-2015")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{origin}" in err.message_template
        assert "{destination}" in err.message_template

    def test_e2016_service_not_available_for_lane(self):
        err = get_error("E-2016")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "{service}" in err.message_template

    def test_e2017_currency_mismatch(self):
        err = get_error("E-2017")
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION

    def test_e3006_customs_validation_failed(self):
        err = get_error("E-3006")
        assert err is not None
        assert err.category == ErrorCategory.UPS_API
        assert "{ups_message}" in err.message_template

    def test_all_international_codes_have_remediation(self):
        for code in ["E-2013", "E-2014", "E-2015", "E-2016", "E-2017", "E-3006"]:
            err = get_error(code)
            assert err is not None, f"{code} not registered"
            assert err.remediation, f"{code} missing remediation"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/errors/test_international_error_codes.py -v`
Expected: FAIL — error codes not yet registered

**Step 3: Add error codes to registry**

In `src/errors/registry.py`, add after the `E-2012` block (line 130):

```python
    # International shipping validation errors (E-2013 – E-2017)
    "E-2013": ErrorCode(
        code="E-2013",
        category=ErrorCategory.VALIDATION,
        title="Missing International Field",
        message_template="Missing required international field: {field_name}",
        remediation="Add the missing field to your source data or provide it during shipment creation.",
    ),
    "E-2014": ErrorCode(
        code="E-2014",
        category=ErrorCategory.VALIDATION,
        title="Invalid HS Tariff Code",
        message_template="Invalid HS tariff code: '{hs_code}'. Must be 6-10 digits.",
        remediation="Check the harmonized system code against your country's tariff schedule.",
    ),
    "E-2015": ErrorCode(
        code="E-2015",
        category=ErrorCategory.VALIDATION,
        title="Unsupported Shipping Lane",
        message_template="Unsupported shipping lane: {origin} to {destination}.",
        remediation="Currently supported lanes: US to CA, US to MX. Contact support for other destinations.",
    ),
    "E-2016": ErrorCode(
        code="E-2016",
        category=ErrorCategory.VALIDATION,
        title="International Service Unavailable",
        message_template="Service '{service}' is not available for {origin} to {destination}.",
        remediation="Use one of the supported international services for this destination.",
    ),
    "E-2017": ErrorCode(
        code="E-2017",
        category=ErrorCategory.VALIDATION,
        title="Currency Mismatch",
        message_template="Currency mismatch: commodity uses '{commodity_currency}' but invoice uses '{invoice_currency}'.",
        remediation="All commodity values must use the same currency as the invoice total.",
    ),
```

And add after `E-3005` (line 168):

```python
    "E-3006": ErrorCode(
        code="E-3006",
        category=ErrorCategory.UPS_API,
        title="Customs Validation Failed",
        message_template="UPS customs validation failed: {ups_message}",
        remediation="Review commodity descriptions, HS codes, and declared values for accuracy.",
    ),
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/errors/test_international_error_codes.py -v`
Expected: ALL PASS (7 tests)

**Step 5: Update error translation map**

In `src/errors/ups_translation.py`, add to `UPS_ERROR_MAP` (after line 44):

```python
    # International/customs UPS error codes
    "CUSTOMS_MISSING_DATA": "E-2013",
    "CUSTOMS_INVALID_HS": "E-2014",
    "CUSTOMS_VALIDATION_FAILED": "E-3006",
```

And add to `UPS_MESSAGE_PATTERNS` (after line 54):

```python
    "customs": "E-3006",
    "export control": "E-3006",
    "commercial invoice": "E-3006",
    "duty": "E-3006",
```

**Step 6: Commit**

```bash
git add src/errors/registry.py src/errors/ups_translation.py tests/errors/test_international_error_codes.py
git commit -m "feat: add international shipping error codes E-2013..E-2017, E-3006"
```

---

### Task 2: Add International DB Columns

**Files:**
- Modify: `src/db/models.py` (Job class ~line 143, JobRow class ~line 222)
- Test: `tests/db/test_international_columns.py`

**Step 1: Write the failing test**

Create `tests/db/test_international_columns.py`:

```python
"""Tests for international shipping database columns."""

import json

from src.db.models import Job, JobRow


class TestJobInternationalColumns:
    """Verify Job model has international columns."""

    def test_job_has_total_duties_taxes_cents(self):
        job = Job(name="test", original_command="test", status="pending")
        assert hasattr(job, "total_duties_taxes_cents")
        assert job.total_duties_taxes_cents is None

    def test_job_has_international_row_count(self):
        job = Job(name="test", original_command="test", status="pending")
        assert hasattr(job, "international_row_count")
        assert job.international_row_count == 0


class TestJobRowInternationalColumns:
    """Verify JobRow model has international columns."""

    def test_row_has_destination_country(self):
        row = JobRow(job_id="test", row_number=1, row_checksum="abc")
        assert hasattr(row, "destination_country")
        assert row.destination_country is None

    def test_row_has_duties_taxes_cents(self):
        row = JobRow(job_id="test", row_number=1, row_checksum="abc")
        assert hasattr(row, "duties_taxes_cents")
        assert row.duties_taxes_cents is None

    def test_row_has_charge_breakdown(self):
        row = JobRow(job_id="test", row_number=1, row_checksum="abc")
        assert hasattr(row, "charge_breakdown")
        assert row.charge_breakdown is None

    def test_charge_breakdown_stores_json(self):
        breakdown = {
            "version": "1.0",
            "transportationCharges": {"monetaryValue": "45.50", "currencyCode": "USD"},
            "dutiesAndTaxes": {"monetaryValue": "12.00", "currencyCode": "USD"},
        }
        row = JobRow(
            job_id="test", row_number=1, row_checksum="abc",
            charge_breakdown=json.dumps(breakdown),
        )
        parsed = json.loads(row.charge_breakdown)
        assert parsed["version"] == "1.0"
        assert parsed["transportationCharges"]["monetaryValue"] == "45.50"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/db/test_international_columns.py -v`
Expected: FAIL — attributes not found

**Step 3: Add columns to models**

In `src/db/models.py`, add to `Job` class after `total_cost_cents` (line 143):

```python
    # International shipping aggregates
    total_duties_taxes_cents: Mapped[Optional[int]] = mapped_column(nullable=True)
    international_row_count: Mapped[int] = mapped_column(default=0, nullable=False)
```

In `JobRow` class, add after `cost_cents` (line 222):

```python
    # International shipping data
    destination_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    duties_taxes_cents: Mapped[Optional[int]] = mapped_column(nullable=True)
    charge_breakdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/db/test_international_columns.py -v`
Expected: ALL PASS (6 tests)

**Step 5: Commit**

```bash
git add src/db/models.py tests/db/test_international_columns.py
git commit -m "feat: add international columns to Job and JobRow models"
```

---

### Task 3: Create International Rules Engine

**Files:**
- Create: `src/services/international_rules.py`
- Test: `tests/services/test_international_rules.py`

**Step 1: Write the failing tests**

Create `tests/services/test_international_rules.py`:

```python
"""Tests for international shipping rules engine."""

import os
from unittest.mock import patch

from src.services.international_rules import (
    RequirementSet,
    ValidationError,
    get_requirements,
    validate_international_readiness,
    is_lane_enabled,
    SUPPORTED_INTERNATIONAL_SERVICES,
)


class TestGetRequirements:
    """Test lane-driven requirement determination."""

    def test_domestic_us_to_us(self):
        req = get_requirements("US", "US", "03")
        assert req.is_international is False
        assert req.requires_international_forms is False

    def test_us_to_ca_is_international(self):
        req = get_requirements("US", "CA", "11")
        assert req.is_international is True
        assert req.requires_description is True
        assert req.requires_shipper_contact is True
        assert req.requires_recipient_contact is True
        assert req.requires_invoice_line_total is True
        assert req.requires_international_forms is True
        assert req.requires_commodities is True
        assert req.form_type == "01"
        assert req.currency_code == "USD"

    def test_us_to_mx_no_invoice_line_total(self):
        req = get_requirements("US", "MX", "07")
        assert req.is_international is True
        assert req.requires_invoice_line_total is False
        assert req.requires_international_forms is True

    def test_us_to_pr_requires_invoice_line_total(self):
        req = get_requirements("US", "PR", "03")
        assert req.is_international is False  # PR is US territory
        assert req.requires_invoice_line_total is True

    def test_unsupported_lane_returns_not_shippable(self):
        req = get_requirements("US", "GB", "07")
        assert req.not_shippable_reason is not None
        assert "not supported" in req.not_shippable_reason.lower()

    def test_invalid_service_for_lane(self):
        req = get_requirements("US", "CA", "03")  # Ground is domestic only
        assert req.not_shippable_reason is not None

    def test_all_international_services_accepted_for_ca(self):
        for code in SUPPORTED_INTERNATIONAL_SERVICES:
            req = get_requirements("US", "CA", code)
            assert req.not_shippable_reason is None, f"Service {code} rejected for US→CA"

    def test_requirement_set_has_rule_version(self):
        req = get_requirements("US", "CA", "11")
        assert req.rule_version is not None
        assert req.effective_date is not None


class TestValidateInternationalReadiness:
    """Test pre-submit validation of order data."""

    def test_valid_international_order(self):
        order = {
            "ship_to_country": "CA",
            "ship_to_phone": "6045551234",
            "ship_to_attention_name": "Jane Doe",
            "shipper_phone": "2125551234",
            "shipper_attention_name": "Acme Corp",
            "shipment_description": "Coffee Beans",
            "invoice_currency_code": "USD",
            "invoice_monetary_value": "150.00",
            "commodities": [
                {
                    "description": "Coffee Beans",
                    "commodity_code": "090111",
                    "origin_country": "CO",
                    "quantity": 5,
                    "unit_value": "30.00",
                }
            ],
        }
        req = get_requirements("US", "CA", "11")
        errors = validate_international_readiness(order, req)
        assert errors == []

    def test_missing_recipient_phone(self):
        order = {
            "ship_to_country": "CA",
            "ship_to_attention_name": "Jane Doe",
            "shipper_phone": "2125551234",
            "shipper_attention_name": "Acme Corp",
            "shipment_description": "Coffee Beans",
            "invoice_currency_code": "USD",
            "invoice_monetary_value": "150.00",
            "commodities": [{"description": "Coffee", "commodity_code": "090111",
                            "origin_country": "CO", "quantity": 1, "unit_value": "30.00"}],
        }
        req = get_requirements("US", "CA", "11")
        errors = validate_international_readiness(order, req)
        assert len(errors) == 1
        assert errors[0].machine_code == "MISSING_RECIPIENT_PHONE"
        assert errors[0].field_path == "ShipTo.Phone.Number"

    def test_missing_commodities(self):
        order = {
            "ship_to_country": "CA",
            "ship_to_phone": "6045551234",
            "ship_to_attention_name": "Jane",
            "shipper_phone": "2125551234",
            "shipper_attention_name": "Acme",
            "shipment_description": "Goods",
            "invoice_currency_code": "USD",
            "invoice_monetary_value": "50.00",
        }
        req = get_requirements("US", "CA", "11")
        errors = validate_international_readiness(order, req)
        codes = [e.machine_code for e in errors]
        assert "MISSING_COMMODITIES" in codes

    def test_invalid_hs_code_format(self):
        order = {
            "ship_to_country": "CA",
            "ship_to_phone": "6045551234",
            "ship_to_attention_name": "Jane",
            "shipper_phone": "2125551234",
            "shipper_attention_name": "Acme",
            "shipment_description": "Goods",
            "invoice_currency_code": "USD",
            "invoice_monetary_value": "50.00",
            "commodities": [{"description": "Widget", "commodity_code": "ABC",
                            "origin_country": "US", "quantity": 1, "unit_value": "10.00"}],
        }
        req = get_requirements("US", "CA", "11")
        errors = validate_international_readiness(order, req)
        codes = [e.machine_code for e in errors]
        assert "INVALID_HS_CODE" in codes

    def test_domestic_returns_no_errors(self):
        order = {"ship_to_country": "US"}
        req = get_requirements("US", "US", "03")
        errors = validate_international_readiness(order, req)
        assert errors == []


class TestLaneEnabled:
    """Test feature flag gating."""

    def test_default_lanes_disabled(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": ""}, clear=False):
            assert is_lane_enabled("US", "CA") is False

    def test_ca_lane_enabled(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            assert is_lane_enabled("US", "CA") is True
            assert is_lane_enabled("US", "MX") is True
            assert is_lane_enabled("US", "GB") is False
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/services/test_international_rules.py -v`
Expected: FAIL — module does not exist

**Step 3: Implement the rules engine**

Create `src/services/international_rules.py`:

```python
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

    # Commodities
    if requirements.requires_commodities:
        commodities = order_data.get("commodities")
        if not commodities or not isinstance(commodities, list) or len(commodities) == 0:
            errors.append(ValidationError(
                machine_code="MISSING_COMMODITIES",
                message="At least one commodity is required for international shipments.",
                field_path="InternationalForms.Product",
            ))
        else:
            for i, comm in enumerate(commodities):
                prefix = f"commodity[{i}]"
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

    return errors
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/services/test_international_rules.py -v`
Expected: ALL PASS (13 tests)

**Step 5: Commit**

```bash
git add src/services/international_rules.py tests/services/test_international_rules.py
git commit -m "feat: add international rules engine with lane-driven requirements"
```

---

## Phase 2: Backend Core (Service Codes, Payload, Response Parsing)

### Task 4: Expand Service Codes

**Files:**
- Modify: `src/orchestrator/models/intent.py` (ServiceCode enum + SERVICE_ALIASES)
- Test: `tests/orchestrator/test_intent_international_services.py`

**Step 1: Write the failing test**

Create `tests/orchestrator/test_intent_international_services.py`:

```python
"""Tests for international service code support."""

from src.orchestrator.models.intent import (
    ServiceCode,
    SERVICE_ALIASES,
    CODE_TO_SERVICE,
)


class TestInternationalServiceCodes:
    """Verify international services are in the enum."""

    def test_worldwide_express(self):
        assert ServiceCode.WORLDWIDE_EXPRESS.value == "07"

    def test_worldwide_expedited(self):
        assert ServiceCode.WORLDWIDE_EXPEDITED.value == "08"

    def test_ups_standard(self):
        assert ServiceCode.UPS_STANDARD.value == "11"

    def test_worldwide_express_plus(self):
        assert ServiceCode.WORLDWIDE_EXPRESS_PLUS.value == "54"

    def test_worldwide_saver(self):
        assert ServiceCode.WORLDWIDE_SAVER.value == "65"


class TestInternationalServiceAliases:
    """Verify international aliases map correctly."""

    def test_worldwide_express_alias(self):
        assert SERVICE_ALIASES["worldwide express"] == ServiceCode.WORLDWIDE_EXPRESS

    def test_international_express_alias(self):
        assert SERVICE_ALIASES["international express"] == ServiceCode.WORLDWIDE_EXPRESS

    def test_worldwide_expedited_alias(self):
        assert SERVICE_ALIASES["worldwide expedited"] == ServiceCode.WORLDWIDE_EXPEDITED

    def test_worldwide_saver_alias(self):
        assert SERVICE_ALIASES["worldwide saver"] == ServiceCode.WORLDWIDE_SAVER

    def test_express_plus_alias(self):
        assert SERVICE_ALIASES["express plus"] == ServiceCode.WORLDWIDE_EXPRESS_PLUS

    def test_code_to_service_reverse_mapping(self):
        assert CODE_TO_SERVICE["07"] == ServiceCode.WORLDWIDE_EXPRESS
        assert CODE_TO_SERVICE["08"] == ServiceCode.WORLDWIDE_EXPEDITED
        assert CODE_TO_SERVICE["11"] == ServiceCode.UPS_STANDARD
        assert CODE_TO_SERVICE["54"] == ServiceCode.WORLDWIDE_EXPRESS_PLUS
        assert CODE_TO_SERVICE["65"] == ServiceCode.WORLDWIDE_SAVER
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_intent_international_services.py -v`
Expected: FAIL — enum members not found

**Step 3: Add international services to intent model**

In `src/orchestrator/models/intent.py`, extend `ServiceCode` enum (after line 23):

```python
    # International services
    WORLDWIDE_EXPRESS = "07"
    WORLDWIDE_EXPEDITED = "08"
    UPS_STANDARD = "11"
    WORLDWIDE_EXPRESS_PLUS = "54"
    WORLDWIDE_SAVER = "65"
```

Add to `SERVICE_ALIASES` dict (after line 52):

```python
    # International service aliases
    "worldwide express": ServiceCode.WORLDWIDE_EXPRESS,
    "international express": ServiceCode.WORLDWIDE_EXPRESS,
    "international": ServiceCode.WORLDWIDE_EXPRESS,
    "worldwide expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    "international expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    "expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    "standard": ServiceCode.UPS_STANDARD,
    "ups standard": ServiceCode.UPS_STANDARD,
    "worldwide saver": ServiceCode.WORLDWIDE_SAVER,
    "international saver": ServiceCode.WORLDWIDE_SAVER,
    "worldwide express plus": ServiceCode.WORLDWIDE_EXPRESS_PLUS,
    "express plus": ServiceCode.WORLDWIDE_EXPRESS_PLUS,
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_intent_international_services.py -v`
Expected: ALL PASS (11 tests)

**Step 5: Commit**

```bash
git add src/orchestrator/models/intent.py tests/orchestrator/test_intent_international_services.py
git commit -m "feat: add international UPS service codes and aliases"
```

---

### Task 5: Add International Column Mappings

**Files:**
- Modify: `src/services/column_mapping.py` (field mappings, auto-map rules, context-aware validation)
- Test: `tests/services/test_column_mapping_international.py`

**Step 1: Write the failing test**

Create `tests/services/test_column_mapping_international.py`:

```python
"""Tests for international column mapping support."""

from src.services.column_mapping import (
    _FIELD_TO_ORDER_DATA,
    validate_mapping,
    apply_mapping,
    SERVICE_NAME_TO_CODE,
)


class TestInternationalFieldMappings:
    """Verify international fields are mappable."""

    def test_shipper_attention_name_mappable(self):
        assert "shipper.attentionName" in _FIELD_TO_ORDER_DATA
        assert _FIELD_TO_ORDER_DATA["shipper.attentionName"] == "shipper_attention_name"

    def test_ship_to_attention_name_mappable(self):
        assert "shipTo.attentionName" in _FIELD_TO_ORDER_DATA

    def test_invoice_currency_mappable(self):
        assert "invoiceLineTotal.currencyCode" in _FIELD_TO_ORDER_DATA
        assert _FIELD_TO_ORDER_DATA["invoiceLineTotal.currencyCode"] == "invoice_currency_code"

    def test_invoice_value_mappable(self):
        assert "invoiceLineTotal.monetaryValue" in _FIELD_TO_ORDER_DATA

    def test_shipment_description_mappable(self):
        assert "shipmentDescription" in _FIELD_TO_ORDER_DATA


class TestContextAwareValidation:
    """Verify validation adapts for international shipments."""

    def test_domestic_does_not_require_state(self):
        # Domestic still requires state
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }
        errors = validate_mapping(mapping, destination_country="US")
        field_errors = [e for e in errors if "stateProvinceCode" in e]
        assert len(field_errors) == 1

    def test_international_state_optional(self):
        mapping = {
            "shipTo.name": "name",
            "shipTo.addressLine1": "addr",
            "shipTo.city": "city",
            "shipTo.postalCode": "zip",
            "shipTo.countryCode": "country",
            "packages[0].weight": "weight",
        }
        errors = validate_mapping(mapping, destination_country="CA")
        field_errors = [e for e in errors if "stateProvinceCode" in e]
        assert len(field_errors) == 0  # State optional for international


class TestInternationalServiceCodes:
    """Verify international service name mapping."""

    def test_worldwide_express_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide express") == "07"

    def test_worldwide_expedited_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide expedited") == "08"

    def test_ups_standard_code(self):
        assert SERVICE_NAME_TO_CODE.get("standard") == "11"

    def test_worldwide_saver_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide saver") == "65"

    def test_worldwide_express_plus_code(self):
        assert SERVICE_NAME_TO_CODE.get("worldwide express plus") == "54"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/services/test_column_mapping_international.py -v`
Expected: FAIL — fields not found

**Step 3: Add international mappings to column_mapping.py**

In `src/services/column_mapping.py`:

1. Add to `_FIELD_TO_ORDER_DATA` (after line 62):
```python
    # International shipping fields
    "shipper.attentionName": "shipper_attention_name",
    "shipTo.attentionName": "ship_to_attention_name",
    "invoiceLineTotal.currencyCode": "invoice_currency_code",
    "invoiceLineTotal.monetaryValue": "invoice_monetary_value",
    "shipmentDescription": "shipment_description",
```

2. Update `validate_mapping()` signature and logic (replace lines 66-79):
```python
def validate_mapping(
    mapping: dict[str, str],
    destination_country: str | None = None,
) -> list[str]:
    """Validate that all required fields have mapping entries.

    Args:
        mapping: Dict of {simplified_path: source_column_name}.
        destination_country: If provided, adjusts required fields.
            For non-US destinations, stateProvinceCode is optional.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []
    is_international = destination_country and destination_country.upper() not in ("US", "PR")
    for field in REQUIRED_FIELDS:
        if field == "shipTo.stateProvinceCode" and is_international:
            continue  # State/province optional for international
        if field not in mapping:
            errors.append(f"Missing required field mapping: '{field}'")
    return errors
```

3. Add international services to `SERVICE_NAME_TO_CODE` (find the existing dict and add):
```python
    # International services
    "worldwide express": "07",
    "international express": "07",
    "international": "07",
    "worldwide expedited": "08",
    "international expedited": "08",
    "standard": "11",
    "ups standard": "11",
    "worldwide express plus": "54",
    "express plus": "54",
    "worldwide saver": "65",
    "international saver": "65",
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/services/test_column_mapping_international.py -v`
Expected: ALL PASS

**Step 5: Run existing column mapping tests for regression**

Run: `python3 -m pytest tests/services/test_column_mapping*.py -v`
Expected: ALL PASS (existing + new)

**Step 6: Commit**

```bash
git add src/services/column_mapping.py tests/services/test_column_mapping_international.py
git commit -m "feat: add international field mappings and context-aware validation"
```

---

### Task 6: Payload Builder International Enrichment

**Files:**
- Modify: `src/services/ups_payload_builder.py`
- Test: `tests/services/test_payload_builder_international.py`

This is the largest task. The payload builder gains:
1. International detection + enrichment in `build_ups_api_payload()` and `build_ups_rate_payload()`
2. `build_international_forms()` function for InternationalForms section
3. Removal of hardcoded "US" defaults (replaced with explicit missing-field errors)
4. Updated `normalize_phone()` for international numbers

**Step 1: Write the failing tests**

Create `tests/services/test_payload_builder_international.py`:

```python
"""Tests for international payload builder enrichment."""

import json

from src.services.ups_payload_builder import (
    build_international_forms,
    normalize_phone,
    normalize_zip,
    build_ups_api_payload,
)


class TestNormalizePhoneInternational:
    """Verify phone normalization handles international numbers."""

    def test_us_10_digit(self):
        assert normalize_phone("212-555-1234") == "2125551234"

    def test_international_with_country_code(self):
        result = normalize_phone("+44 20 7946 0958")
        assert result == "442079460958"

    def test_short_international_accepted(self):
        # 7-digit numbers valid in some countries
        result = normalize_phone("1234567")
        assert len(result) >= 7

    def test_none_returns_empty(self):
        # No more placeholder — missing phone should be caught by validation
        result = normalize_phone(None)
        assert result == ""

    def test_empty_returns_empty(self):
        result = normalize_phone("")
        assert result == ""


class TestNormalizeZipInternational:
    """Verify ZIP normalization passes through international codes."""

    def test_us_5_digit(self):
        assert normalize_zip("10001") == "10001"

    def test_canadian_postal_code(self):
        assert normalize_zip("V6B 3K9") == "V6B 3K9"

    def test_uk_postal_code(self):
        assert normalize_zip("W1A 2HH") == "W1A 2HH"

    def test_mexican_postal_code(self):
        assert normalize_zip("06600") == "06600"


class TestBuildInternationalForms:
    """Verify InternationalForms construction."""

    def test_builds_commercial_invoice(self):
        commodities = [
            {
                "description": "Coffee Beans",
                "commodity_code": "090111",
                "origin_country": "CO",
                "quantity": 5,
                "unit_value": "30.00",
                "unit_of_measure": "PCS",
            }
        ]
        forms = build_international_forms(
            commodities=commodities,
            currency_code="USD",
            form_type="01",
            reason_for_export="SALE",
        )
        assert forms["FormType"] == "01"
        assert forms["CurrencyCode"] == "USD"
        assert forms["ReasonForExport"] == "SALE"
        assert len(forms["Product"]) == 1
        product = forms["Product"][0]
        assert product["Description"] == "Coffee Beans"
        assert product["CommodityCode"] == "090111"
        assert product["OriginCountryCode"] == "CO"
        assert product["Unit"]["Number"] == "5"
        assert product["Unit"]["Value"] == "30.00"

    def test_multi_commodity(self):
        commodities = [
            {"description": "Item A", "commodity_code": "090111",
             "origin_country": "US", "quantity": 2, "unit_value": "10.00"},
            {"description": "Item B", "commodity_code": "123456",
             "origin_country": "MX", "quantity": 1, "unit_value": "25.00"},
        ]
        forms = build_international_forms(
            commodities=commodities,
            currency_code="USD",
        )
        assert len(forms["Product"]) == 2
        assert forms["Product"][0]["Description"] == "Item A"
        assert forms["Product"][1]["Description"] == "Item B"

    def test_default_unit_of_measure(self):
        commodities = [
            {"description": "Widget", "commodity_code": "999999",
             "origin_country": "US", "quantity": 1, "unit_value": "5.00"},
        ]
        forms = build_international_forms(commodities=commodities, currency_code="USD")
        uom = forms["Product"][0]["Unit"]["UnitOfMeasurement"]
        assert uom["Code"] == "PCS"

    def test_idempotent_call(self):
        commodities = [
            {"description": "Widget", "commodity_code": "999999",
             "origin_country": "US", "quantity": 1, "unit_value": "5.00"},
        ]
        forms1 = build_international_forms(commodities=commodities, currency_code="USD")
        forms2 = build_international_forms(commodities=commodities, currency_code="USD")
        assert forms1 == forms2
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/services/test_payload_builder_international.py -v`
Expected: FAIL — functions not found

**Step 3: Implement international enrichment**

Modifications to `src/services/ups_payload_builder.py`:

1. Update `normalize_phone()` (replace lines 23-45):
```python
def normalize_phone(phone: str | None) -> str:
    """Normalize phone number to digits only.

    UPS requires 7-15 digit phone numbers. Handles both domestic
    and international formats (strips formatting, preserves country code).

    Args:
        phone: Raw phone number string (may contain dashes, spaces, parens, +)

    Returns:
        Digits-only phone number, or empty string if invalid/missing.
    """
    if not phone:
        return ""

    # Strip all non-digit characters
    digits = re.sub(r"\D", "", phone)

    # Accept 7-15 digits (international range)
    if len(digits) < 7:
        return ""

    # Truncate to 15 digits (UPS max)
    return digits[:15]
```

2. Update `normalize_zip()` (replace lines 48-76):
```python
def normalize_zip(postal_code: str | None) -> str:
    """Normalize postal code.

    For US codes: handles 5-digit and ZIP+4 formats.
    For international codes: passes through with whitespace trimmed.

    Args:
        postal_code: Raw postal code string.

    Returns:
        Normalized postal code.
    """
    if not postal_code:
        return ""

    postal_code = postal_code.strip()

    # Extract digits to check if this is a US ZIP
    digits = re.sub(r"\D", "", postal_code)

    # If all digits and 5+ chars, treat as US ZIP
    if postal_code.isdigit() or (len(digits) >= 5 and digits == postal_code.replace("-", "")):
        if len(digits) >= 9:
            return f"{digits[:5]}-{digits[5:9]}"
        elif len(digits) >= 5:
            return digits[:5]

    # International postal codes: return as-is (trimmed)
    return postal_code
```

3. Add `build_international_forms()` function (add before `build_shipment_request()`):
```python
def build_international_forms(
    commodities: list[dict],
    currency_code: str = "USD",
    form_type: str = "01",
    reason_for_export: str = "SALE",
    invoice_date: str | None = None,
) -> dict:
    """Build UPS InternationalForms section for customs documentation.

    Args:
        commodities: List of commodity dicts with description, commodity_code,
            origin_country, quantity, unit_value, and optional unit_of_measure.
        currency_code: ISO 4217 currency code (default USD).
        form_type: InternationalForms type (01 = commercial invoice).
        reason_for_export: Export reason code (SALE, GIFT, SAMPLE, etc.).
        invoice_date: Invoice date in YYYYMMDD format. Defaults to today.

    Returns:
        Dict ready to embed as InternationalForms in UPS payload.
    """
    from datetime import date as date_type

    if invoice_date is None:
        invoice_date = date_type.today().strftime("%Y%m%d")

    products = []
    for comm in commodities:
        uom_code = str(comm.get("unit_of_measure", "PCS")).upper()
        products.append({
            "Description": str(comm["description"])[:35],
            "CommodityCode": str(comm["commodity_code"]),
            "OriginCountryCode": str(comm["origin_country"]).upper(),
            "Unit": {
                "Number": str(int(comm["quantity"])),
                "UnitOfMeasurement": {
                    "Code": uom_code,
                    "Description": uom_code,
                },
                "Value": str(comm["unit_value"]),
            },
        })

    return {
        "FormType": form_type,
        "InvoiceDate": invoice_date,
        "ReasonForExport": reason_for_export,
        "CurrencyCode": currency_code,
        "Product": products,
    }
```

4. In `build_ups_api_payload()`, remove hardcoded `"US"` defaults. Replace occurrences of:
   - `shipper.get("countryCode", "US")` → `shipper.get("countryCode", "")`
   - `ship_to.get("countryCode", "US")` → `ship_to.get("countryCode", "")`

   Same for `build_ups_rate_payload()`.

5. In `build_ship_to()` (around line 205), remove:
   - `"countryCode": order_data.get("ship_to_country", "US")` → `"countryCode": order_data.get("ship_to_country", "")`

**Step 4: Run tests**

Run: `python3 -m pytest tests/services/test_payload_builder_international.py tests/services/test_ups_payload_builder.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/services/ups_payload_builder.py tests/services/test_payload_builder_international.py
git commit -m "feat: add international payload enrichment and InternationalForms builder"
```

---

### Task 7: Response Parsing — Charge Breakdown Extraction

**Files:**
- Modify: `src/services/ups_mcp_client.py` (response normalizers)
- Test: `tests/services/test_response_parsing_international.py`

**Step 1: Write the failing test**

Create `tests/services/test_response_parsing_international.py`:

```python
"""Tests for international charge breakdown parsing."""

from src.services.ups_mcp_client import UPSMCPClient


class TestShipmentResponseChargeBreakdown:
    """Verify itemized charge extraction from shipment response."""

    def test_domestic_response_no_breakdown(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z999",
                    "PackageResults": {"TrackingNumber": "1Z999", "ShippingLabel": {"GraphicImage": "base64"}},
                    "ShipmentCharges": {
                        "TotalCharges": {"MonetaryValue": "15.50", "CurrencyCode": "USD"},
                    },
                }
            }
        }
        result = client._normalize_shipment_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "15.50"
        assert "chargeBreakdown" not in result or result.get("chargeBreakdown") is None

    def test_international_response_with_breakdown(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1Z999",
                    "PackageResults": {"TrackingNumber": "1Z999", "ShippingLabel": {"GraphicImage": "base64"}},
                    "ShipmentCharges": {
                        "TransportationCharges": {"MonetaryValue": "45.50", "CurrencyCode": "USD"},
                        "ServiceOptionsCharges": {"MonetaryValue": "5.00", "CurrencyCode": "USD"},
                        "TotalCharges": {"MonetaryValue": "62.50", "CurrencyCode": "USD"},
                        "DutyAndTaxCharges": {"MonetaryValue": "12.00", "CurrencyCode": "USD"},
                    },
                }
            }
        }
        result = client._normalize_shipment_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "62.50"
        breakdown = result.get("chargeBreakdown")
        assert breakdown is not None
        assert breakdown["version"] == "1.0"
        assert breakdown["transportationCharges"]["monetaryValue"] == "45.50"
        assert breakdown["dutiesAndTaxes"]["monetaryValue"] == "12.00"


class TestRateResponseChargeBreakdown:
    """Verify itemized charge extraction from rate response."""

    def test_domestic_rate_no_breakdown(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "TotalCharges": {"MonetaryValue": "20.00", "CurrencyCode": "USD"},
                }
            }
        }
        result = client._normalize_rate_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "20.00"

    def test_international_rate_with_duties(self):
        client = UPSMCPClient.__new__(UPSMCPClient)
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "TransportationCharges": {"MonetaryValue": "35.00", "CurrencyCode": "USD"},
                    "ServiceOptionsCharges": {"MonetaryValue": "3.00", "CurrencyCode": "USD"},
                    "TotalCharges": {"MonetaryValue": "50.00", "CurrencyCode": "USD"},
                }
            }
        }
        result = client._normalize_rate_response(raw)
        assert result["totalCharges"]["monetaryValue"] == "50.00"
        breakdown = result.get("chargeBreakdown")
        assert breakdown is not None
        assert breakdown["transportationCharges"]["monetaryValue"] == "35.00"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/services/test_response_parsing_international.py -v`
Expected: FAIL — chargeBreakdown not in response

**Step 3: Update response normalizers**

In `src/services/ups_mcp_client.py`, update `_normalize_shipment_response()` (around line 428):

After the existing charges extraction (line 465), add charge breakdown extraction:

```python
        # Extract itemized charge breakdown (international shipments)
        shipment_charges = results.get("ShipmentCharges", {})
        charge_breakdown = None
        transportation = shipment_charges.get("TransportationCharges", {})
        if transportation.get("MonetaryValue"):
            charge_breakdown = {
                "version": "1.0",
                "transportationCharges": {
                    "monetaryValue": transportation.get("MonetaryValue", "0"),
                    "currencyCode": transportation.get("CurrencyCode", "USD"),
                },
            }
            service_opts = shipment_charges.get("ServiceOptionsCharges", {})
            if service_opts.get("MonetaryValue"):
                charge_breakdown["serviceOptionsCharges"] = {
                    "monetaryValue": service_opts["MonetaryValue"],
                    "currencyCode": service_opts.get("CurrencyCode", "USD"),
                }
            duties = shipment_charges.get("DutyAndTaxCharges", {})
            if duties.get("MonetaryValue"):
                charge_breakdown["dutiesAndTaxes"] = {
                    "monetaryValue": duties["MonetaryValue"],
                    "currencyCode": duties.get("CurrencyCode", "USD"),
                }
```

And add `"chargeBreakdown": charge_breakdown` to the return dict.

Apply similar logic to `_normalize_rate_response()`.

**Step 4: Run tests**

Run: `python3 -m pytest tests/services/test_response_parsing_international.py -v`
Expected: ALL PASS

**Step 5: Run existing UPS client tests for regression**

Run: `python3 -m pytest tests/services/test_ups_mcp_client.py -v -k "not stream and not sse"`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/services/ups_mcp_client.py tests/services/test_response_parsing_international.py
git commit -m "feat: extract itemized charge breakdown from UPS international responses"
```

---

## Phase 3: API & Agent Updates

### Task 8: Update API Schemas

**Files:**
- Modify: `src/api/schemas.py` (PreviewRowResponse, BatchPreviewResponse, JobRowResponse, JobResponse)

**Step 1:** Add optional international fields to each response model:

```python
# In PreviewRowResponse (after warnings field):
    destination_country: str | None = None
    duties_taxes_cents: int | None = None
    charge_breakdown: dict | None = None

# In BatchPreviewResponse (after rows_with_warnings):
    total_duties_taxes_cents: int | None = None
    international_row_count: int = 0

# In JobRowResponse (after cost_cents):
    destination_country: str | None = None
    duties_taxes_cents: int | None = None
    charge_breakdown: dict | None = None

# In JobResponse (after total_cost_cents):
    total_duties_taxes_cents: int | None = None
    international_row_count: int = 0
```

**Step 2: Commit**

```bash
git add src/api/schemas.py
git commit -m "feat: add international fields to API response schemas"
```

---

### Task 9: Update Agent System Prompt

**Files:**
- Modify: `src/orchestrator/agent/system_prompt.py`

**Step 1:** Update the service table builder (`_build_service_table()`) to include international services with a domestic/international indicator.

**Step 2:** Add an international shipping guidance section to the system prompt:
- Enabled lanes (gated by `INTERNATIONAL_ENABLED_LANES` env var)
- Required fields for international (description, contact info, commodities)
- Filter examples for country-based queries
- Negative guidance: never silently default country to US

**Step 3: Commit**

```bash
git add src/orchestrator/agent/system_prompt.py
git commit -m "feat: add international shipping guidance to agent system prompt"
```

---

### Task 10: Fix Row Normalization and Update Agent Tools

**Files:**
- Modify: `src/orchestrator/agent/tools/core.py` (remove US default at line 253-254)
- Modify: `src/orchestrator/agent/tools/__init__.py` (interactive tool schema)
- Modify: `src/orchestrator/agent/tools/interactive.py` (international field handling)
- Modify: `src/orchestrator/agent/tools/pipeline.py` (pass international context)

**Step 1:** In `core.py`, remove the silent US default:

Replace:
```python
if not out.get("ship_to_country"):
    out["ship_to_country"] = "US"
```
With: (remove these lines entirely — missing country will be caught by rules engine validation)

**Step 2:** In `__init__.py`, update interactive tool schema to add optional international fields.

**Step 3:** In `interactive.py`, pass through international fields from tool input to order_data.

**Step 4:** In `pipeline.py`, query international requirements before preview/execute.

**Step 5: Commit**

```bash
git add src/orchestrator/agent/tools/core.py src/orchestrator/agent/tools/__init__.py \
    src/orchestrator/agent/tools/interactive.py src/orchestrator/agent/tools/pipeline.py
git commit -m "feat: remove US default, add international field support to agent tools"
```

---

## Phase 4: Data Pipeline & Batch Engine

### Task 11: Add Commodities Query Tool to Data Source MCP

**Files:**
- Modify: `src/mcp/data_source/tools/query_tools.py`
- Test: `tests/mcp/test_commodities_query.py`

**Step 1:** Add `get_commodities_bulk()` function that queries the commodities table for a list of order IDs and returns grouped results.

**Step 2:** Register the tool in the MCP server.

**Step 3: Commit**

```bash
git add src/mcp/data_source/tools/query_tools.py tests/mcp/test_commodities_query.py
git commit -m "feat: add get_commodities_bulk tool for international shipments"
```

---

### Task 12: Batch Engine International Integration

**Files:**
- Modify: `src/services/batch_engine.py`

**Step 1:** Before preview, detect international rows by checking `ship_to_country` against rules engine.

**Step 2:** For international rows, hydrate commodity data via `get_commodities_bulk()`.

**Step 3:** Run `validate_international_readiness()` before sending to UPS. Rows that fail validation are marked failed with descriptive error codes.

**Step 4:** Store `destination_country`, `duties_taxes_cents`, and `charge_breakdown` on JobRow after processing.

**Step 5: Commit**

```bash
git add src/services/batch_engine.py
git commit -m "feat: integrate international validation and commodity hydration in batch engine"
```

---

## Phase 5: Frontend

### Task 13: Update Frontend Types

**Files:**
- Modify: `frontend/src/types/api.ts`

**Step 1:** Add international fields to TypeScript interfaces:

```typescript
// In PreviewRow
destination_country?: string;
duties_taxes_cents?: number;
charge_breakdown?: ChargeBreakdown;

// In BatchPreview
total_duties_taxes_cents?: number;
international_row_count?: number;

// In JobRow
destination_country?: string;
duties_taxes_cents?: number;
charge_breakdown?: ChargeBreakdown;

// In Job
total_duties_taxes_cents?: number;
international_row_count?: number;

// New shared type
interface ChargeBreakdownEntry {
  monetaryValue: string;
  currencyCode: string;
}

interface ChargeBreakdown {
  version: string;
  transportationCharges?: ChargeBreakdownEntry;
  serviceOptionsCharges?: ChargeBreakdownEntry;
  dutiesAndTaxes?: ChargeBreakdownEntry;
  brokerageCharges?: ChargeBreakdownEntry;
}
```

**Step 2: Commit**

```bash
cd frontend && git add src/types/api.ts
git commit -m "feat: add international shipping TypeScript types"
```

---

### Task 14: Update PreviewCard with Charge Breakdown

**Files:**
- Modify: `frontend/src/components/command-center/PreviewCard.tsx`

**Step 1:** When `charge_breakdown` is present on a preview row, render itemized cost lines:
- Transportation: $X.XX
- Duties & Taxes: $X.XX (if present)
- Brokerage: $X.XX (if present)
- **Total: $X.XX**

**Step 2:** Add country badge next to destination address when `destination_country` is non-US.

**Step 3:** Add international count to stats row when `international_row_count > 0`.

**Step 4: Commit**

```bash
cd frontend && git add src/components/command-center/PreviewCard.tsx
git commit -m "feat: display international charge breakdown and country badge in PreviewCard"
```

---

### Task 15: Update CompletionArtifact, ProgressDisplay, JobDetailPanel

**Files:**
- Modify: `frontend/src/components/command-center/CompletionArtifact.tsx`
- Modify: `frontend/src/components/command-center/ProgressDisplay.tsx`
- Modify: `frontend/src/components/JobDetailPanel.tsx`

**Step 1:** CompletionArtifact: Show international indicator badge when `international_row_count > 0`. Include duties/taxes in cost display.

**Step 2:** ProgressDisplay: Add duties/taxes metric when processing international batches.

**Step 3:** JobDetailPanel: Show `destination_country` and charge breakdown in row detail expansion.

**Step 4: Commit**

```bash
cd frontend && git add src/components/command-center/CompletionArtifact.tsx \
    src/components/command-center/ProgressDisplay.tsx \
    src/components/JobDetailPanel.tsx
git commit -m "feat: add international indicators to CompletionArtifact, ProgressDisplay, JobDetailPanel"
```

---

## Phase 6: Integration Testing

### Task 16: End-to-End Mixed Batch Test

**Files:**
- Create: `tests/integration/test_international_batch.py`

**Step 1:** Write a test that creates a batch with mixed domestic + international rows. Verify:
- Domestic rows process normally (no international fields required)
- International rows with valid data succeed
- International rows missing fields fail with correct error codes
- Aggregate totals are correct (shipping + duties)

**Step 2: Commit**

```bash
git add tests/integration/test_international_batch.py
git commit -m "test: add mixed domestic+international batch integration test"
```

---

### Task 17: Domestic Regression Test

**Files:**
- Create: `tests/integration/test_domestic_regression.py`

**Step 1:** Write a test that runs a fully domestic batch end-to-end. Verify:
- No international fields required
- No charge breakdown in response
- Identical behavior to pre-international code
- `international_row_count` is 0

**Step 2: Commit**

```bash
git add tests/integration/test_domestic_regression.py
git commit -m "test: add domestic regression test to verify no behavioral change"
```

---

## Execution Notes

**Migration order**: Tasks 1-3 (foundation) → Tasks 4-7 (backend core) → Tasks 8-10 (API/agent) → Tasks 11-12 (data pipeline) → Tasks 13-15 (frontend) → Tasks 16-17 (integration)

**Kill switch**: Set `INTERNATIONAL_ENABLED_LANES=""` to disable all international paths immediately.

**Rollback**: Each task has its own commit. Revert individual commits to roll back specific changes.

**Observability**: `rule_version` logged on every international validation. Error code metrics per lane. Raw UPS charge fragments in audit logs.
