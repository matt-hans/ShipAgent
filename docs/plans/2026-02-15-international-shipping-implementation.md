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

**Step 5: Add SQLite migration entries for existing databases**

Modify `src/db/connection.py` — in `_ensure_columns_exist()` at the `migrations` list (line 217), add entries for both `jobs` and `job_rows` tables:

```python
    migrations: list[tuple[str, str]] = [
        ("shipper_json", "ALTER TABLE jobs ADD COLUMN shipper_json TEXT"),
        (
            "is_interactive",
            "ALTER TABLE jobs ADD COLUMN is_interactive BOOLEAN NOT NULL DEFAULT 0",
        ),
        # International shipping columns — jobs table
        (
            "total_duties_taxes_cents",
            "ALTER TABLE jobs ADD COLUMN total_duties_taxes_cents INTEGER",
        ),
        (
            "international_row_count",
            "ALTER TABLE jobs ADD COLUMN international_row_count INTEGER NOT NULL DEFAULT 0",
        ),
    ]

    for col_name, ddl in migrations:
        if col_name not in existing:
            try:
                conn.execute(text(ddl))
            except OperationalError as e:
                if "duplicate column" in str(e).lower():
                    log.debug("Column %s already exists (concurrent add).", col_name)
                else:
                    log.error("Failed to add column %s: %s", col_name, e)
                    raise

    # job_rows table migrations
    result_rows = conn.execute(text("PRAGMA table_info(job_rows)"))
    existing_rows = {row[1] for row in result_rows.fetchall()}

    row_migrations: list[tuple[str, str]] = [
        (
            "destination_country",
            "ALTER TABLE job_rows ADD COLUMN destination_country VARCHAR(2)",
        ),
        (
            "duties_taxes_cents",
            "ALTER TABLE job_rows ADD COLUMN duties_taxes_cents INTEGER",
        ),
        (
            "charge_breakdown",
            "ALTER TABLE job_rows ADD COLUMN charge_breakdown TEXT",
        ),
    ]

    for col_name, ddl in row_migrations:
        if col_name not in existing_rows:
            try:
                conn.execute(text(ddl))
            except OperationalError as e:
                if "duplicate column" in str(e).lower():
                    log.debug("Column %s already exists (concurrent add).", col_name)
                else:
                    log.error("Failed to add column %s: %s", col_name, e)
                    raise
```

**Step 6: Write migration test on existing DB file**

Add to `tests/db/test_international_columns.py`:

```python
import tempfile
import os
from sqlalchemy import create_engine, text


class TestMigrationOnExistingDB:
    """Verify columns are added to an existing database without the new columns."""

    def test_migration_adds_columns_to_existing_db(self):
        """Simulate an existing DB that lacks international columns."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Create a DB with the OLD schema (no international columns)
            engine = create_engine(f"sqlite:///{db_path}")
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        original_command TEXT,
                        status TEXT,
                        total_cost_cents INTEGER,
                        shipper_json TEXT,
                        is_interactive BOOLEAN NOT NULL DEFAULT 0
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE job_rows (
                        id TEXT PRIMARY KEY,
                        job_id TEXT,
                        row_number INTEGER,
                        row_checksum TEXT,
                        cost_cents INTEGER
                    )
                """))

            # Run migration
            from src.db.connection import _ensure_columns_exist
            with engine.begin() as conn:
                _ensure_columns_exist(conn)

            # Verify new columns exist
            with engine.begin() as conn:
                cols_jobs = {r[1] for r in conn.execute(text("PRAGMA table_info(jobs)")).fetchall()}
                assert "total_duties_taxes_cents" in cols_jobs
                assert "international_row_count" in cols_jobs

                cols_rows = {r[1] for r in conn.execute(text("PRAGMA table_info(job_rows)")).fetchall()}
                assert "destination_country" in cols_rows
                assert "duties_taxes_cents" in cols_rows
                assert "charge_breakdown" in cols_rows

            # Verify idempotent — running again doesn't crash
            with engine.begin() as conn:
                _ensure_columns_exist(conn)
        finally:
            os.unlink(db_path)
```

**Step 7: Run all DB tests**

Run: `python3 -m pytest tests/db/test_international_columns.py -v`
Expected: ALL PASS (7 tests)

**Step 8: Commit**

```bash
git add src/db/models.py src/db/connection.py tests/db/test_international_columns.py
git commit -m "feat: add international columns to Job/JobRow models with SQLite migration"
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
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
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
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
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
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "CA", "03")  # Ground is domestic only
            assert req.not_shippable_reason is not None

    def test_all_international_services_accepted_for_ca(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            for code in SUPPORTED_INTERNATIONAL_SERVICES:
                req = get_requirements("US", "CA", code)
                assert req.not_shippable_reason is None, f"Service {code} rejected for US→CA"

    def test_requirement_set_has_rule_version(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.rule_version is not None
            assert req.effective_date is not None

    def test_kill_switch_blocks_enabled_lane(self):
        """P0: get_requirements() must enforce is_lane_enabled() kill switch."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": ""}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is not None
            assert "disabled" in req.not_shippable_reason.lower() or "not enabled" in req.not_shippable_reason.lower()

    def test_kill_switch_allows_when_enabled(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is None
            assert req.is_international is True


class TestValidateInternationalReadiness:
    """Test pre-submit validation of order data."""

    def test_valid_international_order(self):
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
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
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
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
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
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
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
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

    def test_currency_mismatch_e2017(self):
        """P2: E-2017 must fire when commodity currency differs from invoice currency."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA"}, clear=False):
            order = {
                "ship_to_country": "CA",
                "ship_to_phone": "6045551234",
                "ship_to_attention_name": "Jane",
                "shipper_phone": "2125551234",
                "shipper_attention_name": "Acme",
                "shipment_description": "Goods",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "50.00",
                "commodities": [
                    {"description": "Widget", "commodity_code": "999999",
                     "origin_country": "US", "quantity": 1, "unit_value": "50.00",
                     "currency_code": "CAD"},  # Mismatch!
                ],
            }
            req = get_requirements("US", "CA", "11")
            errors = validate_international_readiness(order, req)
            codes = [e.machine_code for e in errors]
            assert "CURRENCY_MISMATCH" in codes
            # Verify it maps to E-2017
            mismatch_error = next(e for e in errors if e.machine_code == "CURRENCY_MISMATCH")
            assert mismatch_error.error_code == "E-2017"

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
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/services/test_international_rules.py -v`
Expected: ALL PASS (14 tests)

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

    def test_standard_alias_not_present(self):
        """P1: bare 'standard' must NOT map to international service 11."""
        assert "standard" not in SERVICE_ALIASES

    def test_ups_standard_alias(self):
        assert SERVICE_ALIASES["ups standard"] == ServiceCode.UPS_STANDARD

    def test_international_standard_alias(self):
        assert SERVICE_ALIASES["international standard"] == ServiceCode.UPS_STANDARD

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
    # NOTE: Do NOT add "standard" → UPS_STANDARD here.
    # "standard" is ambiguous — domestic users mean UPS Ground.
    # Only unambiguous aliases are allowed.
    "worldwide express": ServiceCode.WORLDWIDE_EXPRESS,
    "international express": ServiceCode.WORLDWIDE_EXPRESS,
    "worldwide expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    "international expedited": ServiceCode.WORLDWIDE_EXPEDITED,
    "ups standard": ServiceCode.UPS_STANDARD,
    "international standard": ServiceCode.UPS_STANDARD,
    "ups standard international": ServiceCode.UPS_STANDARD,
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
        assert SERVICE_NAME_TO_CODE.get("ups standard") == "11"

    def test_bare_standard_not_mapped(self):
        """P1: bare 'standard' must NOT map to international service."""
        assert "standard" not in SERVICE_NAME_TO_CODE

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
    # NOTE: Do NOT add bare "standard" → "11" here.
    # "standard" is ambiguous — domestic users mean UPS Ground.
    "worldwide express": "07",
    "international express": "07",
    "worldwide expedited": "08",
    "international expedited": "08",
    "ups standard": "11",
    "international standard": "11",
    "ups standard international": "11",
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
1. International detection + enrichment in `build_shipment_request()` (the layer that has access to raw `order_data`), with `build_ups_api_payload()` reading enriched fields from the simplified dict
2. `build_international_forms()` function for InternationalForms section
3. Removal of hardcoded "US" defaults (replaced with explicit missing-field errors)
4. Updated `normalize_phone()` for international numbers
5. Removal of bare `"standard"` from `resolve_service_code()` internal map

**Step 1: Write the failing tests**

Create `tests/services/test_payload_builder_international.py`:

```python
"""Tests for international payload builder enrichment."""

import json

from src.services.ups_payload_builder import (
    build_international_forms,
    build_shipment_request,
    build_ups_api_payload,
    normalize_phone,
    normalize_zip,
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

6. **P0: Wire rules engine call INTO `build_shipment_request()`.** This is the correct enrichment layer because it has access to raw `order_data`. The simplified dict it returns is the interface between data-access and payload-building. In `build_shipment_request()`, **after** constructing the base `simplified` dict (the `return {...}` block), add enrichment before returning:

```python
    from src.services.international_rules import get_requirements

    # Determine international requirements
    origin_country = shipper.get("countryCode", "US")
    dest_country = order_data.get("ship_to_country", "")
    requirements = get_requirements(origin_country, dest_country, service_code)

    if requirements.not_shippable_reason:
        raise ValueError(f"Cannot ship: {requirements.not_shippable_reason}")

    # Enrich simplified dict with international data for downstream consumption
    simplified["destinationCountry"] = dest_country

    # Contact fields → inject into existing shipper/shipTo sub-dicts
    if requirements.requires_shipper_contact:
        if order_data.get("shipper_attention_name"):
            simplified["shipper"]["attentionName"] = order_data["shipper_attention_name"]
        if order_data.get("shipper_phone"):
            simplified["shipper"]["phone"] = normalize_phone(order_data["shipper_phone"])

    if requirements.requires_recipient_contact:
        if order_data.get("ship_to_attention_name"):
            simplified["shipTo"]["attentionName"] = order_data["ship_to_attention_name"]
        if order_data.get("ship_to_phone"):
            simplified["shipTo"]["phone"] = normalize_phone(order_data["ship_to_phone"])

    # InvoiceLineTotal → add as top-level key in simplified
    if requirements.requires_invoice_line_total:
        simplified["invoiceLineTotal"] = {
            "currencyCode": order_data.get("invoice_currency_code", "USD"),
            "monetaryValue": order_data.get("invoice_monetary_value", "0"),
        }

    # Description → add as top-level key in simplified
    if requirements.requires_description:
        desc = order_data.get("shipment_description", "")
        if desc:
            simplified["description"] = desc[:35]

    # InternationalForms → build from commodities and add to simplified
    if requirements.requires_international_forms:
        commodities = order_data.get("commodities", [])
        if commodities:
            simplified["internationalForms"] = build_international_forms(
                commodities=commodities,
                currency_code=requirements.currency_code,
                form_type=requirements.form_type,
            )

    return simplified
```

Then in `build_ups_api_payload()`, **read** enriched fields from the simplified dict (this function does NOT access raw `order_data`):

```python
    # --- International enrichment (reads from simplified, set by build_shipment_request) ---

    # InvoiceLineTotal
    invoice_lt = simplified.get("invoiceLineTotal")
    if invoice_lt:
        payload["ShipmentRequest"]["Shipment"]["InvoiceLineTotal"] = {
            "CurrencyCode": invoice_lt["currencyCode"],
            "MonetaryValue": invoice_lt["monetaryValue"],
        }

    # Description
    desc = simplified.get("description")
    if desc:
        payload["ShipmentRequest"]["Shipment"]["Description"] = desc

    # Shipper contact
    shipper_data = simplified.get("shipper", {})
    if shipper_data.get("attentionName"):
        payload["ShipmentRequest"]["Shipment"]["Shipper"]["AttentionName"] = shipper_data["attentionName"]
    if shipper_data.get("phone"):
        payload["ShipmentRequest"]["Shipment"]["Shipper"]["Phone"] = {"Number": shipper_data["phone"]}

    # ShipTo contact
    ship_to_data = simplified.get("shipTo", {})
    if ship_to_data.get("attentionName"):
        payload["ShipmentRequest"]["Shipment"]["ShipTo"]["AttentionName"] = ship_to_data["attentionName"]
    if ship_to_data.get("phone"):
        payload["ShipmentRequest"]["Shipment"]["ShipTo"]["Phone"] = {"Number": ship_to_data["phone"]}

    # InternationalForms
    intl_forms = simplified.get("internationalForms")
    if intl_forms:
        sso = payload["ShipmentRequest"]["Shipment"].get("ShipmentServiceOptions", {})
        sso["InternationalForms"] = intl_forms
        payload["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"] = sso
```

7. **Rate payload parity.** Apply the same read-from-simplified logic to `build_ups_rate_payload()` — InvoiceLineTotal, Description, contact fields. InternationalForms is NOT needed for rating but InvoiceLineTotal IS required for accurate rate quotes on US→CA. Since `build_shipment_request()` already enriches the simplified dict, both `build_ups_rate_payload()` and `build_ups_api_payload()` read the same data.

8. **P1: Remove bare `"standard"` from `resolve_service_code()`.** In `src/services/ups_payload_builder.py`, find `resolve_service_code()` (around line 370) and its internal `service_name_map` dict. Remove the line `"standard": "11"`. Only `"ups standard"` and `"international standard"` should map to `"11"`. Add a comment:

```python
    # NOTE: Do NOT add bare "standard" → "11" here.
    # "standard" is ambiguous — domestic users mean UPS Ground.
    # Only unambiguous aliases are allowed.
```

**Step 4: Write payload integration tests using the correct two-step call chain**

**IMPORTANT:** The enrichment happens in `build_shipment_request()` (which has raw `order_data`).
Then `build_ups_api_payload()` reads enriched fields from the simplified dict.
Tests MUST call `build_shipment_request()` → `build_ups_api_payload()` — never pass `order_data` directly to `build_ups_api_payload()`.

Add to `tests/services/test_payload_builder_international.py`:

```python
import os
from unittest.mock import patch

from src.services.ups_payload_builder import (
    build_shipment_request,
    build_ups_api_payload,
)


class TestPayloadIntegration:
    """P0: Assert actual final UPS payload JSON using the correct two-step chain.

    Call chain: build_shipment_request(order_data, shipper, service_code)
               → simplified dict (enriched with international fields)
               → build_ups_api_payload(simplified, account_number)
               → final UPS API payload
    """

    def test_us_to_ca_payload_has_international_forms(self):
        """Full payload for US→CA must contain InternationalForms + InvoiceLineTotal."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            order_data = {
                "ship_to_name": "Jane Doe",
                "ship_to_address1": "100 Queen St W",
                "ship_to_city": "Toronto",
                "ship_to_state": "ON",
                "ship_to_zip": "M5H 2N2",
                "ship_to_country": "CA",
                "ship_to_phone": "4165551234",
                "ship_to_attention_name": "Jane Doe",
                "shipper_attention_name": "Acme Corp",
                "shipper_phone": "2125551234",
                "shipment_description": "Coffee Beans",
                "invoice_currency_code": "USD",
                "invoice_monetary_value": "150.00",
                "weight": "5.0",
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
            shipper = {
                "name": "Acme Corp",
                "addressLine1": "123 Main St",
                "city": "New York",
                "stateProvinceCode": "NY",
                "postalCode": "10001",
                "countryCode": "US",
                "shipperNumber": "ABC123",
            }

            # Step 1: build_shipment_request enriches simplified with intl fields
            simplified = build_shipment_request(
                order_data=order_data, shipper=shipper, service_code="11",
            )
            # Verify enrichment happened at this layer
            assert simplified.get("internationalForms") is not None
            assert simplified.get("invoiceLineTotal") is not None
            assert simplified.get("destinationCountry") == "CA"

            # Step 2: build_ups_api_payload reads from simplified (no order_data)
            payload = build_ups_api_payload(simplified, account_number="ABC123")

            shipment = payload["ShipmentRequest"]["Shipment"]
            # InvoiceLineTotal present for US→CA
            assert "InvoiceLineTotal" in shipment
            assert shipment["InvoiceLineTotal"]["CurrencyCode"] == "USD"
            # InternationalForms present
            sso = shipment.get("ShipmentServiceOptions", {})
            assert "InternationalForms" in sso
            forms = sso["InternationalForms"]
            assert forms["FormType"] == "01"
            assert len(forms["Product"]) == 1
            assert forms["Product"][0]["CommodityCode"] == "090111"
            # Contact fields
            assert "AttentionName" in shipment["ShipTo"]
            assert "Phone" in shipment["ShipTo"]
            # Description
            assert shipment.get("Description") == "Coffee Beans"

    def test_us_to_mx_payload_no_invoice_line_total(self):
        """US→MX does NOT require InvoiceLineTotal."""
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": "US-CA,US-MX"}, clear=False):
            order_data = {
                "ship_to_name": "Carlos Garcia",
                "ship_to_address1": "Av Insurgentes Sur 1000",
                "ship_to_city": "Mexico City",
                "ship_to_zip": "06600",
                "ship_to_country": "MX",
                "ship_to_phone": "5255551234",
                "ship_to_attention_name": "Carlos Garcia",
                "shipper_attention_name": "Acme Corp",
                "shipper_phone": "2125551234",
                "shipment_description": "Electronics",
                "weight": "3.0",
                "commodities": [
                    {
                        "description": "Laptop",
                        "commodity_code": "847130",
                        "origin_country": "US",
                        "quantity": 1,
                        "unit_value": "999.00",
                    }
                ],
            }
            shipper = {
                "name": "Acme Corp",
                "addressLine1": "123 Main St",
                "city": "New York",
                "stateProvinceCode": "NY",
                "postalCode": "10001",
                "countryCode": "US",
                "shipperNumber": "ABC123",
            }

            simplified = build_shipment_request(
                order_data=order_data, shipper=shipper, service_code="07",
            )
            payload = build_ups_api_payload(simplified, account_number="ABC123")

            shipment = payload["ShipmentRequest"]["Shipment"]
            # NO InvoiceLineTotal for US→MX
            assert "InvoiceLineTotal" not in shipment
            # InternationalForms still present
            sso = shipment.get("ShipmentServiceOptions", {})
            assert "InternationalForms" in sso

    def test_domestic_payload_unchanged(self):
        """Domestic US→US payload must NOT contain any international sections."""
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_address1": "456 Oak Ave",
            "ship_to_city": "Los Angeles",
            "ship_to_state": "CA",
            "ship_to_zip": "90001",
            "ship_to_country": "US",
            "weight": "2.0",
        }
        shipper = {
            "name": "Acme Corp",
            "addressLine1": "123 Main St",
            "city": "New York",
            "stateProvinceCode": "NY",
            "postalCode": "10001",
            "countryCode": "US",
            "shipperNumber": "ABC123",
        }

        simplified = build_shipment_request(
            order_data=order_data, shipper=shipper, service_code="03",
        )
        payload = build_ups_api_payload(simplified, account_number="ABC123")

        shipment = payload["ShipmentRequest"]["Shipment"]
        assert "InvoiceLineTotal" not in shipment
        assert "InternationalForms" not in shipment.get("ShipmentServiceOptions", {})
```

**Step 5: Run all payload tests**

Run: `python3 -m pytest tests/services/test_payload_builder_international.py tests/services/test_ups_payload_builder.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/services/ups_payload_builder.py tests/services/test_payload_builder_international.py
git commit -m "feat: add international payload enrichment with rules-engine integration and InternationalForms"
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

### Task 8: Update API Schemas and Preview Route Wiring

**Files:**
- Modify: `src/api/schemas.py` (PreviewRowResponse, BatchPreviewResponse, JobRowResponse, JobResponse)
- Modify: `src/api/routes/preview.py` (SERVICE_CODE_NAMES dict, PreviewRowResponse construction, BatchPreviewResponse construction)
- Test: `tests/api/test_preview_international.py`

**Step 1:** Add optional international fields to each response model in `src/api/schemas.py`:

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

**Step 2: Add international services to SERVICE_CODE_NAMES**

In `src/api/routes/preview.py`, update the `SERVICE_CODE_NAMES` dict (line 38):

```python
SERVICE_CODE_NAMES = {
    "01": "UPS Next Day Air",
    "02": "UPS 2nd Day Air",
    "03": "UPS Ground",
    "07": "UPS Worldwide Express",
    "08": "UPS Worldwide Expedited",
    "11": "UPS Standard",
    "12": "UPS 3 Day Select",
    "13": "UPS Next Day Air Saver",
    "14": "UPS Next Day Air Early",
    "54": "UPS Worldwide Express Plus",
    "59": "UPS 2nd Day Air A.M.",
    "65": "UPS Worldwide Saver",
}
```

**Step 3: Wire international fields into PreviewRowResponse construction**

In `src/api/routes/preview.py`, update the `preview_rows.append(...)` block (lines 118-128) to include international data from the JobRow:

```python
        # Extract international data from row
        destination_country = getattr(row, "destination_country", None)
        duties_taxes_cents = getattr(row, "duties_taxes_cents", None)
        charge_breakdown_raw = getattr(row, "charge_breakdown", None)
        charge_breakdown = None
        if charge_breakdown_raw:
            try:
                charge_breakdown = json.loads(charge_breakdown_raw)
            except json.JSONDecodeError:
                pass

        preview_rows.append(
            PreviewRowResponse(
                row_number=row.row_number,
                recipient_name=recipient_name,
                city_state=city_state,
                service=service,
                estimated_cost_cents=estimated_cost,
                warnings=warnings,
                order_data=order_data_dict,
                destination_country=destination_country,
                duties_taxes_cents=duties_taxes_cents,
                charge_breakdown=charge_breakdown,
            )
        )
```

**Step 4: Wire international aggregates into BatchPreviewResponse**

Update the return statement (lines 130-137):

```python
    # Compute international aggregates
    total_duties_taxes = 0
    international_count = 0
    for row in rows:
        if getattr(row, "duties_taxes_cents", None):
            total_duties_taxes += row.duties_taxes_cents
        if getattr(row, "destination_country", None) and row.destination_country not in ("US", "PR"):
            international_count += 1

    return BatchPreviewResponse(
        job_id=job_id,
        total_rows=len(rows),
        preview_rows=preview_rows,
        additional_rows=0,
        total_estimated_cost_cents=total_estimated_cost,
        rows_with_warnings=rows_with_warnings,
        total_duties_taxes_cents=total_duties_taxes if total_duties_taxes > 0 else None,
        international_row_count=international_count,
    )
```

**Step 5: Write preview route contract test**

Create `tests/api/test_preview_international.py`:

```python
"""Tests for international fields in preview route responses."""

import json
from unittest.mock import MagicMock, patch

from src.api.routes.preview import SERVICE_CODE_NAMES
from src.api.schemas import PreviewRowResponse, BatchPreviewResponse


class TestServiceCodeNames:
    """Verify SERVICE_CODE_NAMES includes international services."""

    def test_worldwide_express(self):
        assert "07" in SERVICE_CODE_NAMES
        assert "Worldwide Express" in SERVICE_CODE_NAMES["07"]

    def test_worldwide_expedited(self):
        assert "08" in SERVICE_CODE_NAMES

    def test_ups_standard(self):
        assert "11" in SERVICE_CODE_NAMES

    def test_worldwide_express_plus(self):
        assert "54" in SERVICE_CODE_NAMES

    def test_worldwide_saver(self):
        assert "65" in SERVICE_CODE_NAMES

    def test_domestic_services_unchanged(self):
        assert SERVICE_CODE_NAMES["03"] == "UPS Ground"
        assert SERVICE_CODE_NAMES["01"] == "UPS Next Day Air"
        assert SERVICE_CODE_NAMES["02"] == "UPS 2nd Day Air"


class TestPreviewRowResponseInternationalFields:
    """P1: Verify PreviewRowResponse includes actual international fields."""

    def test_destination_country_field_exists(self):
        row = PreviewRowResponse(
            row_number=1, recipient_name="Jane Doe",
            city_state="Toronto, ON", service="UPS Standard",
            estimated_cost_cents=4550,
            destination_country="CA",
        )
        assert row.destination_country == "CA"

    def test_duties_taxes_cents_field_exists(self):
        row = PreviewRowResponse(
            row_number=1, recipient_name="Jane Doe",
            city_state="Toronto, ON", service="UPS Standard",
            estimated_cost_cents=4550,
            duties_taxes_cents=1200,
        )
        assert row.duties_taxes_cents == 1200

    def test_charge_breakdown_field_exists(self):
        breakdown = {
            "version": "1.0",
            "transportationCharges": {"monetaryValue": "45.50", "currencyCode": "USD"},
            "dutiesAndTaxes": {"monetaryValue": "12.00", "currencyCode": "USD"},
        }
        row = PreviewRowResponse(
            row_number=1, recipient_name="Jane Doe",
            city_state="Toronto, ON", service="UPS Standard",
            estimated_cost_cents=4550,
            charge_breakdown=breakdown,
        )
        assert row.charge_breakdown["version"] == "1.0"
        assert row.charge_breakdown["dutiesAndTaxes"]["monetaryValue"] == "12.00"

    def test_domestic_row_has_none_international_fields(self):
        row = PreviewRowResponse(
            row_number=1, recipient_name="John Doe",
            city_state="Los Angeles, CA", service="UPS Ground",
            estimated_cost_cents=1550,
        )
        assert row.destination_country is None
        assert row.duties_taxes_cents is None
        assert row.charge_breakdown is None


class TestBatchPreviewResponseInternationalAggregates:
    """P1: Verify BatchPreviewResponse includes international aggregates."""

    def test_total_duties_taxes_cents_field(self):
        resp = BatchPreviewResponse(
            job_id="test-123",
            total_rows=5,
            preview_rows=[],
            total_estimated_cost_cents=10000,
            total_duties_taxes_cents=2400,
            international_row_count=2,
        )
        assert resp.total_duties_taxes_cents == 2400
        assert resp.international_row_count == 2

    def test_domestic_only_batch_no_international_aggregates(self):
        resp = BatchPreviewResponse(
            job_id="test-456",
            total_rows=3,
            preview_rows=[],
            total_estimated_cost_cents=5000,
        )
        assert resp.total_duties_taxes_cents is None
        assert resp.international_row_count == 0
```

**Step 6: Run tests**

Run: `python3 -m pytest tests/api/test_preview_international.py -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add src/api/schemas.py src/api/routes/preview.py tests/api/test_preview_international.py
git commit -m "feat: wire international fields through API schemas and preview route"
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

### Task 11: MCP Commodity Data Pipeline (Multi-Table Support)

**Context:** The current MCP data source uses a single hardcoded `imported_data` table. International shipping requires a second `imported_commodities` table linked by `order_id`. This task extends the MCP to support auxiliary table import while preserving the existing single-table contract.

**Files:**
- Create: `src/mcp/data_source/tools/commodity_tools.py`
- Modify: `src/mcp/data_source/server.py` (register new tools)
- Modify: `src/mcp/data_source/tools/query_tools.py` (add `get_commodities_bulk()`)
- Test: `tests/mcp/test_commodity_tools.py`

**Step 1: Write failing tests**

Create `tests/mcp/test_commodity_tools.py`:

```python
"""Tests for commodity import and query tools."""

import duckdb
import pytest


class TestCommodityImport:
    """Verify commodity data can be imported as auxiliary table."""

    def setup_method(self):
        self.db = duckdb.connect(":memory:")
        # Simulate existing order import
        self.db.execute("""
            CREATE TABLE imported_data (
                order_id INTEGER, customer_name VARCHAR, ship_to_country VARCHAR
            )
        """)
        self.db.execute("""
            INSERT INTO imported_data VALUES
            (1001, 'Jane Doe', 'CA'),
            (1002, 'Carlos Garcia', 'MX')
        """)

    def teardown_method(self):
        self.db.close()

    def test_import_commodities_creates_table(self):
        from src.mcp.data_source.tools.commodity_tools import import_commodities_sync
        result = import_commodities_sync(
            self.db,
            [
                {"order_id": 1001, "description": "Coffee", "commodity_code": "090111",
                 "origin_country": "CO", "quantity": 5, "unit_value": "30.00"},
                {"order_id": 1001, "description": "Tea", "commodity_code": "090210",
                 "origin_country": "CN", "quantity": 10, "unit_value": "15.00"},
                {"order_id": 1002, "description": "Laptop", "commodity_code": "847130",
                 "origin_country": "US", "quantity": 1, "unit_value": "999.00"},
            ],
        )
        assert result["row_count"] == 3
        assert result["table_name"] == "imported_commodities"
        # Verify table exists
        tables = [r[0] for r in self.db.execute("SHOW TABLES").fetchall()]
        assert "imported_commodities" in tables

    def test_import_commodities_replaces_previous(self):
        from src.mcp.data_source.tools.commodity_tools import import_commodities_sync
        import_commodities_sync(self.db, [
            {"order_id": 1, "description": "Old", "commodity_code": "000000",
             "origin_country": "US", "quantity": 1, "unit_value": "1.00"},
        ])
        import_commodities_sync(self.db, [
            {"order_id": 2, "description": "New", "commodity_code": "111111",
             "origin_country": "US", "quantity": 1, "unit_value": "2.00"},
        ])
        count = self.db.execute("SELECT COUNT(*) FROM imported_commodities").fetchone()[0]
        assert count == 1  # Replaced, not appended


class TestGetCommoditiesBulk:
    """Verify bulk commodity retrieval grouped by order_id."""

    def setup_method(self):
        self.db = duckdb.connect(":memory:")
        self.db.execute("""
            CREATE TABLE imported_commodities (
                order_id INTEGER, description VARCHAR, commodity_code VARCHAR,
                origin_country VARCHAR, quantity INTEGER, unit_value VARCHAR,
                unit_of_measure VARCHAR DEFAULT 'PCS'
            )
        """)
        self.db.execute("""
            INSERT INTO imported_commodities VALUES
            (1001, 'Coffee', '090111', 'CO', 5, '30.00', 'PCS'),
            (1001, 'Tea', '090210', 'CN', 10, '15.00', 'PCS'),
            (1002, 'Laptop', '847130', 'US', 1, '999.00', 'PCS')
        """)

    def teardown_method(self):
        self.db.close()

    def test_get_commodities_for_single_order(self):
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync
        result = get_commodities_bulk_sync(self.db, [1001])
        assert 1001 in result
        assert len(result[1001]) == 2
        descs = {c["description"] for c in result[1001]}
        assert descs == {"Coffee", "Tea"}

    def test_get_commodities_for_multiple_orders(self):
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync
        result = get_commodities_bulk_sync(self.db, [1001, 1002])
        assert len(result[1001]) == 2
        assert len(result[1002]) == 1

    def test_missing_order_returns_empty(self):
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync
        result = get_commodities_bulk_sync(self.db, [9999])
        assert result.get(9999, []) == []

    def test_no_commodities_table_returns_empty(self):
        db = duckdb.connect(":memory:")
        from src.mcp.data_source.tools.commodity_tools import get_commodities_bulk_sync
        result = get_commodities_bulk_sync(db, [1001])
        assert result == {}
        db.close()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/mcp/test_commodity_tools.py -v`
Expected: FAIL — module does not exist

**Step 3: Implement commodity tools**

Create `src/mcp/data_source/tools/commodity_tools.py`:

```python
"""Commodity import and query tools for international shipping.

Manages the `imported_commodities` auxiliary table alongside the
primary `imported_data` table. Follows the same ephemeral session
model — import replaces previous commodities data.
"""

from collections import defaultdict
from typing import Any

from fastmcp import Context


COMMODITIES_TABLE = "imported_commodities"

# Required columns for commodity data
COMMODITY_COLUMNS = [
    ("order_id", "INTEGER"),
    ("description", "VARCHAR"),
    ("commodity_code", "VARCHAR"),
    ("origin_country", "VARCHAR(2)"),
    ("quantity", "INTEGER"),
    ("unit_value", "VARCHAR"),
    ("unit_of_measure", "VARCHAR DEFAULT 'PCS'"),
]


def import_commodities_sync(
    db: Any,
    commodities: list[dict],
) -> dict:
    """Import commodity data into the imported_commodities table.

    Replaces any existing commodity data (same ephemeral model as
    imported_data). Links to orders via order_id.

    Args:
        db: DuckDB connection.
        commodities: List of commodity dicts, each with order_id,
            description, commodity_code, origin_country, quantity,
            unit_value, and optional unit_of_measure.

    Returns:
        Dict with row_count and table_name.
    """
    col_defs = ", ".join(f"{name} {dtype}" for name, dtype in COMMODITY_COLUMNS)
    db.execute(f"CREATE OR REPLACE TABLE {COMMODITIES_TABLE} ({col_defs})")

    for comm in commodities:
        db.execute(
            f"""INSERT INTO {COMMODITIES_TABLE}
            (order_id, description, commodity_code, origin_country, quantity, unit_value, unit_of_measure)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                comm["order_id"],
                str(comm["description"])[:35],
                str(comm.get("commodity_code", "")),
                str(comm.get("origin_country", "")).upper(),
                int(comm.get("quantity", 1)),
                str(comm.get("unit_value", "0")),
                str(comm.get("unit_of_measure", "PCS")).upper(),
            ],
        )

    count = db.execute(f"SELECT COUNT(*) FROM {COMMODITIES_TABLE}").fetchone()[0]
    return {"row_count": count, "table_name": COMMODITIES_TABLE}


def get_commodities_bulk_sync(
    db: Any,
    order_ids: list[int | str],
) -> dict[int | str, list[dict]]:
    """Get commodities for multiple orders, grouped by order_id.

    Args:
        db: DuckDB connection.
        order_ids: List of order IDs to look up.

    Returns:
        Dict mapping order_id → list of commodity dicts.
        Missing orders are omitted from the result.
    """
    # Check if commodities table exists
    try:
        tables = [r[0] for r in db.execute("SHOW TABLES").fetchall()]
    except Exception:
        return {}

    if COMMODITIES_TABLE not in tables:
        return {}

    if not order_ids:
        return {}

    placeholders = ", ".join("?" for _ in order_ids)
    rows = db.execute(
        f"SELECT * FROM {COMMODITIES_TABLE} WHERE order_id IN ({placeholders})",
        order_ids,
    ).fetchall()

    # Get column names
    schema = db.execute(f"DESCRIBE {COMMODITIES_TABLE}").fetchall()
    columns = [col[0] for col in schema]

    result: dict[int | str, list[dict]] = defaultdict(list)
    for row in rows:
        row_dict = dict(zip(columns, row))
        oid = row_dict.pop("order_id")
        result[oid].append(row_dict)

    return dict(result)


async def import_commodities(
    commodities: list[dict],
    ctx: Context,
) -> dict:
    """MCP tool: Import commodity data for international shipments.

    Each commodity must have an order_id matching the primary imported_data.
    Replaces any previously imported commodities.

    Args:
        commodities: List of commodity dicts with order_id, description,
            commodity_code, origin_country, quantity, unit_value.

    Returns:
        Dict with row_count and table_name.
    """
    db = ctx.request_context.lifespan_context["db"]
    await ctx.info(f"Importing {len(commodities)} commodities")
    result = import_commodities_sync(db, commodities)

    # Track auxiliary table in session state
    ctx.request_context.lifespan_context["commodities_loaded"] = True

    await ctx.info(f"Imported {result['row_count']} commodities")
    return result


async def get_commodities_bulk(
    order_ids: list[int | str],
    ctx: Context,
) -> dict:
    """MCP tool: Get commodities for multiple orders.

    Args:
        order_ids: List of order IDs to retrieve commodities for.

    Returns:
        Dict mapping order_id → list of commodity dicts.
    """
    db = ctx.request_context.lifespan_context["db"]
    await ctx.info(f"Fetching commodities for {len(order_ids)} orders")
    result = get_commodities_bulk_sync(db, order_ids)
    await ctx.info(f"Found commodities for {len(result)} orders")
    return result
```

**Step 4: Register tools in MCP server**

In `src/mcp/data_source/server.py`, import and register the new tools:

```python
from src.mcp.data_source.tools.commodity_tools import (
    import_commodities,
    get_commodities_bulk,
)

# Register alongside existing tools (note: use mcp.tool()(func) pattern,
# matching the existing registration style in this server)
mcp.tool()(import_commodities)
mcp.tool()(get_commodities_bulk)
```

**Step 5: Run tests**

Run: `python3 -m pytest tests/mcp/test_commodity_tools.py -v`
Expected: ALL PASS (9 tests — 7 commodity + 2 seam)

**Step 6: Commit**

```bash
git add src/mcp/data_source/tools/commodity_tools.py src/mcp/data_source/server.py \
    src/services/data_source_gateway.py src/services/data_source_mcp_client.py \
    tests/mcp/test_commodity_tools.py
git commit -m "feat: add commodity import/query tools with full hydration seam"
```

**Step 7: Wire the commodity hydration seam (P0 — execution blocker)**

The MCP tools above handle DuckDB-level operations. The BatchEngine needs a way to call `get_commodities_bulk` through the gateway chain. Add methods to `DataSourceGateway`, `DataSourceMCPClient`, and register a helper on `BatchEngine`.

**7a. Add to `DataSourceGateway` protocol** (`src/services/data_source_gateway.py`):

```python
    async def get_commodities_bulk(
        self, order_ids: list[int | str],
    ) -> dict[int | str, list[dict[str, Any]]]:
        """Get commodities grouped by order_id for international shipments.

        Args:
            order_ids: List of order IDs to retrieve commodities for.

        Returns:
            Dict mapping order_id → list of commodity dicts.
            Missing orders are omitted from the result.
        """
        ...
```

**7b. Add to `DataSourceMCPClient`** (`src/services/data_source_mcp_client.py`):

```python
    async def get_commodities_bulk(
        self, order_ids: list[int | str],
    ) -> dict[int | str, list[dict[str, Any]]]:
        """Get commodities for multiple orders via MCP tool.

        Args:
            order_ids: List of order IDs to retrieve commodities for.

        Returns:
            Dict mapping order_id → list of commodity dicts.
        """
        await self._ensure_connected()
        result = await self._mcp.call_tool("get_commodities_bulk", {
            "order_ids": order_ids,
        })
        # MCP returns dict with string keys; normalize to match input type
        return {
            (int(k) if isinstance(order_ids[0], int) else k): v
            for k, v in result.items()
        } if result else {}
```

**7c. Write tests for the seam:**

Add to `tests/mcp/test_commodity_tools.py`:

```python
class TestGatewaySeam:
    """Verify the full chain: BatchEngine → DataSourceMCPClient → MCP tool."""

    def test_data_source_gateway_has_get_commodities_bulk(self):
        """Protocol must define get_commodities_bulk."""
        from src.services.data_source_gateway import DataSourceGateway
        assert hasattr(DataSourceGateway, "get_commodities_bulk")

    def test_data_source_mcp_client_implements_method(self):
        """DataSourceMCPClient must implement get_commodities_bulk."""
        from src.services.data_source_mcp_client import DataSourceMCPClient
        client = DataSourceMCPClient.__new__(DataSourceMCPClient)
        assert hasattr(client, "get_commodities_bulk")
        assert callable(getattr(client, "get_commodities_bulk"))
```

**Design note:** The existing `imported_data` table and all 50+ hardcoded references to it are **NOT modified**. The commodity pipeline uses a parallel `imported_commodities` table with its own import/query tools. The `query_data` MCP tool already allows arbitrary SQL, so the agent can JOIN the two tables if needed. This avoids touching the adapter protocol or breaking existing flows.

---

### Task 12: Batch Engine International Integration

**Files:**
- Modify: `src/services/batch_engine.py`
- Test: `tests/services/test_batch_engine_international.py`

**Step 1: Fix Decimal money conversion (P2)**

In `src/services/batch_engine.py`, replace `int(float(amount) * 100)` (line 143) with Decimal-safe conversion:

```python
from decimal import Decimal, ROUND_HALF_UP

def _dollars_to_cents(amount: str) -> int:
    """Convert dollar string to cents using Decimal to avoid float drift.

    Args:
        amount: Dollar amount as string (e.g., "45.50").

    Returns:
        Integer cents value.
    """
    return int(Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
```

Replace all `int(float(amount) * 100)` calls with `_dollars_to_cents(amount)`.

**Step 2: Write failing test for Decimal precision**

Add to `tests/services/test_batch_engine_international.py`:

```python
"""Tests for batch engine international integration."""

from decimal import Decimal
from src.services.batch_engine import _dollars_to_cents


class TestDollarsToCents:
    """Verify Decimal-based money conversion avoids float drift."""

    def test_simple_conversion(self):
        assert _dollars_to_cents("45.50") == 4550

    def test_problematic_float_value(self):
        # 33.33 * 100 = 3332.9999... with float
        assert _dollars_to_cents("33.33") == 3333

    def test_zero(self):
        assert _dollars_to_cents("0") == 0
        assert _dollars_to_cents("0.00") == 0

    def test_large_value(self):
        assert _dollars_to_cents("99999.99") == 9999999

    def test_no_decimal(self):
        assert _dollars_to_cents("100") == 10000

    def test_rounding(self):
        # Values with more than 2 decimal places
        assert _dollars_to_cents("10.555") == 1056  # ROUND_HALF_UP
        assert _dollars_to_cents("10.554") == 1055
```

**Step 3: Implement international batch logic**

In `src/services/batch_engine.py`:

1. Before preview, detect international rows by checking `ship_to_country` against rules engine:

```python
from src.services.international_rules import get_requirements, validate_international_readiness

# In the preview/execute loop, after loading order_data:
dest_country = order_data.get("ship_to_country", "US")
service_code = order_data.get("service_code", "03")
requirements = get_requirements("US", dest_country, service_code)

if requirements.not_shippable_reason:
    # Mark row as failed with descriptive error
    row.status = "failed"
    row.error_message = requirements.not_shippable_reason
    row.error_code = "E-2015"
    continue
```

2. Add `_get_commodities_bulk()` helper to BatchEngine (P0 — completes the hydration seam from Task 11):

```python
    async def _get_commodities_bulk(
        self, order_ids: list[int | str],
    ) -> dict[int | str, list[dict]]:
        """Fetch commodities for orders via the data source gateway.

        Delegates to DataSourceGateway.get_commodities_bulk() which calls
        the MCP get_commodities_bulk tool. Returns empty dict if gateway
        doesn't support commodities (pre-international code path).

        Args:
            order_ids: List of order IDs to retrieve commodities for.

        Returns:
            Dict mapping order_id → list of commodity dicts.
        """
        try:
            return await self._gateway.get_commodities_bulk(order_ids)
        except Exception as e:
            logger.warning("Commodity fetch failed (non-critical): %s", e)
            return {}
```

3. Before processing international rows, bulk-fetch and inject commodities:

```python
# Before processing international rows, bulk-fetch commodities
if any_international_rows:
    order_ids = [row_data.get("order_id") for row_data in international_rows]
    commodities_map = await self._get_commodities_bulk(order_ids)
    # Inject into each row's order_data
    for row_data in international_rows:
        oid = row_data.get("order_id")
        if oid in commodities_map:
            row_data["commodities"] = commodities_map[oid]
```

4. Run `validate_international_readiness()` before sending to UPS:

```python
if requirements.is_international or requirements.requires_invoice_line_total:
    validation_errors = validate_international_readiness(order_data, requirements)
    if validation_errors:
        row.status = "failed"
        row.error_message = "; ".join(e.message for e in validation_errors)
        row.error_code = validation_errors[0].error_code
        continue
```

5. Store `destination_country`, `duties_taxes_cents`, and `charge_breakdown` on JobRow after processing:

```python
row.destination_country = dest_country if dest_country != "US" else None
if result.get("chargeBreakdown"):
    import json
    row.charge_breakdown = json.dumps(result["chargeBreakdown"])
    duties = result["chargeBreakdown"].get("dutiesAndTaxes", {})
    if duties.get("monetaryValue"):
        row.duties_taxes_cents = _dollars_to_cents(duties["monetaryValue"])
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/services/test_batch_engine_international.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/services/batch_engine.py tests/services/test_batch_engine_international.py
git commit -m "feat: integrate international validation, commodity hydration, and Decimal money in batch engine"
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

**Step 1:** Write a test with proper CI gating. Tests that hit real UPS API require `RUN_UPS_INTEGRATION=1` env var:

```python
"""End-to-end mixed domestic + international batch integration test."""

import os
import pytest

# P2: CI gating — skip if no UPS credentials available
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_UPS_INTEGRATION"),
    reason="Set RUN_UPS_INTEGRATION=1 and provide UPS credentials to run",
)


class TestMixedBatch:
    """Test batch with mixed domestic + international rows."""

    @pytest.mark.integration
    def test_domestic_rows_process_normally(self):
        """Domestic rows should not require international fields."""
        # ... test implementation using real or mocked UPS API

    @pytest.mark.integration
    def test_international_rows_with_valid_data_succeed(self):
        """International rows with all required fields should succeed."""
        # ... test implementation

    @pytest.mark.integration
    def test_international_rows_missing_fields_fail(self):
        """International rows missing required fields fail with correct error codes."""
        # ... test implementation — does NOT need UPS API, purely validation

    @pytest.mark.integration
    def test_aggregate_totals_correct(self):
        """Aggregate totals include shipping + duties for international."""
        # ... test implementation
```

**Step 2:** For tests that don't need UPS credentials (pure validation), use a separate class without the skipif:

```python
class TestMixedBatchValidation:
    """Validation-only tests that don't require UPS API."""

    def test_international_row_missing_commodities_fails(self):
        """Row to CA without commodities should fail with E-2013."""
        from src.services.international_rules import get_requirements, validate_international_readiness
        req = get_requirements("US", "CA", "11")
        errors = validate_international_readiness({"ship_to_country": "CA"}, req)
        codes = [e.machine_code for e in errors]
        assert "MISSING_COMMODITIES" in codes

    def test_domestic_row_no_validation_needed(self):
        """Domestic US→US row should pass with no errors."""
        from src.services.international_rules import get_requirements, validate_international_readiness
        req = get_requirements("US", "US", "03")
        errors = validate_international_readiness({"ship_to_country": "US"}, req)
        assert errors == []

    def test_kill_switch_blocks_international(self):
        """With INTERNATIONAL_ENABLED_LANES empty, international rows are rejected."""
        from unittest.mock import patch
        from src.services.international_rules import get_requirements
        with patch.dict(os.environ, {"INTERNATIONAL_ENABLED_LANES": ""}, clear=False):
            req = get_requirements("US", "CA", "11")
            assert req.not_shippable_reason is not None
```

**Step 3: Commit**

```bash
git add tests/integration/test_international_batch.py
git commit -m "test: add mixed domestic+international batch integration test with CI gating"
```

---

### Task 17: Domestic Regression Test

**Files:**
- Create: `tests/integration/test_domestic_regression.py`

**Step 1:** Write a regression test. Most assertions can run without UPS credentials (using mocked responses):

```python
"""Domestic regression test — verify no behavioral change from international additions."""

import os
import pytest


class TestDomesticRegression:
    """Verify domestic-only batches are completely unaffected by international code."""

    def test_domestic_no_international_fields_required(self):
        """US→US shipment must not require any international fields."""
        from src.services.international_rules import get_requirements
        req = get_requirements("US", "US", "03")
        assert req.is_international is False
        assert req.requires_international_forms is False
        assert req.requires_commodities is False
        assert req.requires_invoice_line_total is False
        assert req.requires_description is False
        assert req.requires_shipper_contact is False
        assert req.requires_recipient_contact is False
        assert req.not_shippable_reason is None

    def test_domestic_payload_has_no_international_sections(self):
        """Domestic payload must NOT contain InternationalForms or InvoiceLineTotal."""
        from src.services.ups_payload_builder import build_shipment_request, build_ups_api_payload
        order_data = {
            "ship_to_name": "John Doe",
            "ship_to_address1": "456 Oak Ave",
            "ship_to_city": "Los Angeles",
            "ship_to_state": "CA",
            "ship_to_zip": "90001",
            "ship_to_country": "US",
            "weight": "2.0",
        }
        shipper = {
            "name": "Acme", "addressLine1": "123 Main",
            "city": "NYC", "stateProvinceCode": "NY",
            "postalCode": "10001", "countryCode": "US",
            "shipperNumber": "ABC",
        }
        simplified = build_shipment_request(order_data=order_data, shipper=shipper, service_code="03")
        payload = build_ups_api_payload(simplified, account_number="ABC")
        shipment = payload["ShipmentRequest"]["Shipment"]
        assert "InvoiceLineTotal" not in shipment
        sso = shipment.get("ShipmentServiceOptions", {})
        assert "InternationalForms" not in sso

    def test_domestic_charge_breakdown_not_in_response(self):
        """Domestic UPS response should not produce charge breakdown."""
        from src.services.ups_mcp_client import UPSMCPClient
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
        assert result.get("chargeBreakdown") is None

    def test_service_aliases_domestic_unchanged(self):
        """Existing domestic aliases must still work."""
        from src.orchestrator.models.intent import SERVICE_ALIASES, ServiceCode
        # These should still map to domestic services
        assert SERVICE_ALIASES.get("ground") == ServiceCode.GROUND
        assert SERVICE_ALIASES.get("next day air") == ServiceCode.NEXT_DAY_AIR
        # "standard" must NOT be hijacked to international
        assert "standard" not in SERVICE_ALIASES

    @pytest.mark.skipif(
        not os.environ.get("RUN_UPS_INTEGRATION"),
        reason="Set RUN_UPS_INTEGRATION=1 to run live UPS tests",
    )
    @pytest.mark.integration
    def test_live_domestic_batch_unchanged(self):
        """Live domestic batch should produce identical results to pre-international code."""
        # ... live API test
        pass
```

**Step 2: Run regression tests**

Run: `python3 -m pytest tests/integration/test_domestic_regression.py -v`
Expected: ALL PASS (skip live test without credentials)

**Step 3: Commit**

```bash
git add tests/integration/test_domestic_regression.py
git commit -m "test: add domestic regression test verifying no behavioral change"
```

---

## Execution Notes

**Migration order**: Tasks 1-3 (foundation) → Tasks 4-7 (backend core) → Tasks 8-10 (API/agent) → Tasks 11-12 (data pipeline) → Tasks 13-15 (frontend) → Tasks 16-17 (integration)

**Kill switch**: Set `INTERNATIONAL_ENABLED_LANES=""` to disable all international paths immediately. The kill switch is enforced inside `get_requirements()` — no separate check needed by callers. Test `test_kill_switch_blocks_enabled_lane` proves this.

**DB migration**: `_ensure_columns_exist()` in `src/db/connection.py` handles both `jobs` and `job_rows` table migrations. Idempotent — safe on fresh and existing DBs. Test `test_migration_adds_columns_to_existing_db` proves columns are added to pre-existing databases.

**Commodity data model**: Uses a parallel `imported_commodities` DuckDB table — does NOT modify the existing `imported_data` table or the 50+ references to it. The `import_commodities` MCP tool creates/replaces `imported_commodities`; `get_commodities_bulk` queries it grouped by order_id. Full hydration seam: `BatchEngine._get_commodities_bulk()` → `DataSourceMCPClient.get_commodities_bulk()` → MCP `get_commodities_bulk` tool → DuckDB.

**Enrichment architecture**: International enrichment happens in `build_shipment_request()` (which has raw `order_data`). It adds international fields to the `simplified` dict (e.g., `internationalForms`, `invoiceLineTotal`, contact fields in `shipper`/`shipTo` sub-dicts). `build_ups_api_payload()` reads these enriched fields from the simplified dict — it never receives raw `order_data`.

**Money precision**: All dollar-to-cents conversions use `Decimal` via `_dollars_to_cents()`. The previous `int(float(amount) * 100)` pattern is replaced everywhere.

**Service alias safety**: Bare `"standard"` is NOT mapped to any service in three locations: `SERVICE_ALIASES` (intent.py), `SERVICE_NAME_TO_CODE` (column_mapping.py), and `resolve_service_code()` (ups_payload_builder.py). Only `"ups standard"` and `"international standard"` map to service code `"11"`. Domestic aliases are unchanged.

**CI gating**: Integration tests requiring UPS credentials use `pytest.mark.skipif(not os.environ.get("RUN_UPS_INTEGRATION"))`. Validation-only tests run unconditionally.

**Rollback**: Each task has its own commit. Revert individual commits to roll back specific changes.

**Observability**: `rule_version` logged on every international validation. Error code metrics per lane. Raw UPS charge fragments in audit logs.

## Review Issue Resolution Matrix

### Round 1

| # | Severity | Issue | Resolution | Task |
|---|----------|-------|------------|------|
| 1 | P0 | DB migration incomplete | Added `_ensure_columns_exist()` entries for 5 columns + migration test | Task 2 |
| 2 | P0 | MCP multi-table not addressed | New `commodity_tools.py` with `imported_commodities` table, import + bulk query | Task 11 |
| 3 | P0 | Kill switch not enforced | `get_requirements()` calls `is_lane_enabled()` before returning valid requirements | Task 3 |
| 4 | P1 | "standard" alias regression | Removed bare `"standard"` from SERVICE_ALIASES and SERVICE_NAME_TO_CODE | Tasks 4, 5 |
| 5 | P1 | Payload enrichment incomplete | Added rules-engine call, InvoiceLineTotal/contact/forms injection, integration tests | Task 6 |
| 6 | P1 | Preview route wiring missing | Added SERVICE_CODE_NAMES updates, PreviewRowResponse/BatchPreviewResponse wiring | Task 8 |
| 7 | P2 | Money precision risk | Replaced `int(float(x)*100)` with `_dollars_to_cents()` using Decimal | Task 12 |
| 8 | P2 | Integration test CI gating | Added `RUN_UPS_INTEGRATION` env skipif + separated validation-only tests | Tasks 16, 17 |

### Round 2

| # | Severity | Issue | Resolution | Task |
|---|----------|-------|------------|------|
| 9 | P0 | Payload builder interface mismatch — enrichment in `build_ups_api_payload()` which lacks `order_data` | Moved enrichment to `build_shipment_request()` (has `order_data`); `build_ups_api_payload()` reads enriched fields from simplified dict; integration tests use two-step chain | Task 6 |
| 10 | P0 | Commodity hydration seam undefined — `_get_commodities_bulk()` called but never defined | Added `get_commodities_bulk()` to DataSourceGateway protocol + DataSourceMCPClient + BatchEngine helper with seam tests | Tasks 11, 12 |
| 11 | P1 | Preview route test only checks SERVICE_CODE_NAMES dict | Added TestPreviewRowResponseInternationalFields and TestBatchPreviewResponseInternationalAggregates asserting `destination_country`, `duties_taxes_cents`, `charge_breakdown` fields | Task 8 |
| 12 | P1 | "standard" alias in payload builder `resolve_service_code()` at line 407 | Added step 8 to Task 6: remove bare `"standard": "11"` from `resolve_service_code()` internal map | Task 6 |
| 13 | P2 | MCP tool registration uses `mcp.tool(func)` but server uses `mcp.tool()(func)` | Fixed registration to `mcp.tool()(import_commodities)` / `mcp.tool()(get_commodities_bulk)` | Task 11 |
| 14 | P2 | E-2017 currency mismatch error defined but no validator enforces it | Added currency mismatch check to `validate_international_readiness()` + test `test_currency_mismatch_e2017` | Task 3 |
