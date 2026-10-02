import pytest
from jsonschema import ValidationError

from src.control_plane.result_projection import project_result
from src.registry.catalog import public_tools
from src.registry.identifiers import (
    PROVIDER_VISIBLE_FIELD_FAMILIES,
    PROVIDER_VISIBLE_ID_FAMILIES,
    mint_shipagent_id,
    shipagent_id_prefix,
    shipagent_id_schema,
)
from src.registry.models import ToolContract
from src.registry.tools.schema import object_schema

VALID_HEX_BODY = "0123456789abcdef0123456789abcdef"
VALID_DEVICE_ID = f"sa_device_{VALID_HEX_BODY}"
VALID_INPUT_ID = f"sa_input_{VALID_HEX_BODY}"
VALID_VALIDATION_ID = f"sa_validation_{VALID_HEX_BODY}"
VALID_PREVIEW_ID = f"sa_preview_{VALID_HEX_BODY}"
VALID_JOB_ID = f"sa_job_{VALID_HEX_BODY}"
VALID_LABEL_ID = f"sa_label_{VALID_HEX_BODY}"

PREFIXED_COMPACT_CANARY_BODIES = (
    "ApiKeyLiveValue01",
    "BearerTokenValue1",
    "JaneDoeCustomer01",
    "PrivateRecipient1",
    "742MainStreetCity",
    "QXBpS2V5TGl2ZVZhbHVl",
)


def _contract(**overrides) -> ToolContract:
    base = {
        "name": "execute_shipments",
        "title": "Execute shipments",
        "description": "Execute shipment previews created from prepared data.",
        "contract_version": "1.0.0",
        "visibility": "public",
        "availability": ["hosted", "local"],
        "implementation_status": "implemented",
        "hosted_readiness": "ready",
        "tenant_safe": True,
        # Projection tests exercise defense-in-depth independently from the
        # canonical provider-export schema privacy gate.
        "provider_export_enabled": False,
        "side_effect": "purchase",
        "requires_confirmation": True,
        "prepare_tool": "prepare_shipments",
        "auth_scopes": ["shipments:execute"],
        "provider_exports": ["openai_apps_public", "generic_mcp"],
        "audit_level": "full",
        "result_sensitivity": "business",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    }
    base.update(overrides)
    return ToolContract.model_validate(base)


def test_project_result_allows_safe_aggregate_response():
    contract = _contract()
    result = {"job_id": "job-1"}

    assert project_result(contract, result) == result


def test_project_result_rejects_forbidden_nested_keys_for_aggregate_profile():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {"recipient_name": {"type": "string"}},
                    "additionalProperties": False,
                }
            },
            "required": ["payload"],
            "additionalProperties": False,
        }
    )
    result = {"payload": {"recipient_name": "Jane Doe", "rows": [{"x": 1}]}}

    with pytest.raises(ValueError, match="aggregate result contains forbidden keys"):
        project_result(contract, result)


def test_project_result_enforces_closed_output_shape_for_aggregate_profile():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                }
            },
            "required": ["summary"],
            "additionalProperties": False,
        }
    )
    result = {"summary": {"status": "ok", "note": "should be rejected"}}

    with pytest.raises(ValueError, match="additionalProperties=False"):
        project_result(contract, result)


def test_project_result_rejects_open_object_schema_inside_array():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "rates": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["rates"],
            "additionalProperties": False,
        }
    )

    with pytest.raises(ValueError, match="additionalProperties=False"):
        project_result(contract, {"rates": [{"customer_payload": "private"}]})


def test_project_result_rejects_container_when_array_schema_omits_items():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "rates": {"type": "array"},
            },
            "required": ["rates"],
            "additionalProperties": False,
        }
    )

    with pytest.raises(ValueError, match="container requires a schema object"):
        project_result(contract, {"rates": [{"customer_payload": "private"}]})


def test_project_result_rejects_container_with_boolean_array_item_schema():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "rates": {"type": "array", "items": True},
            },
            "required": ["rates"],
            "additionalProperties": False,
        }
    )

    with pytest.raises(ValueError, match="container requires a schema object"):
        project_result(contract, {"rates": [{"customer_payload": "private"}]})


def test_project_result_rejects_dictionary_with_boolean_property_schema():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {
                "payload": True,
            },
            "required": ["payload"],
            "additionalProperties": False,
        }
    )

    with pytest.raises(ValueError, match="container requires a schema object"):
        project_result(contract, {"payload": {"customer_payload": "private"}})


@pytest.mark.parametrize(
    ("nested_schema", "value"),
    [
        ({"type": "array"}, ["safe"]),
        ({"type": "array", "items": True}, ["safe"]),
        (True, "safe"),
    ],
)
def test_project_result_allows_scalars_without_mapping_nested_schema(
    nested_schema,
    value,
):
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {"payload": nested_schema},
            "required": ["payload"],
            "additionalProperties": False,
        }
    )
    result = {"payload": value}

    assert project_result(contract, result) == result


def test_project_result_skips_forbidden_check_for_non_aggregate_profile():
    contract = _contract(
        result_profile="provider_ingress_echo",
        output_schema={
            "type": "object",
            "properties": {"recipient_name": {"type": "string"}},
            "required": ["recipient_name"],
            "additionalProperties": False,
        },
    )
    result = {"recipient_name": "Jane Doe"}

    assert project_result(contract, result) == result


def test_project_result_validates_against_schema():
    contract = _contract(
        output_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        }
    )
    with pytest.raises(ValidationError):
        project_result(contract, {"count": "not-integer"})


@pytest.mark.parametrize(
    ("tool_name", "safe_result"),
    [
        (
            "get_shipagent_status",
            {
                "status": "ready",
                "executionTarget": {
                    "state": "ready",
                    "capabilities": ["shipment_ingress"],
                },
            },
        ),
        (
            "execute_shipments",
            {"job_id": VALID_JOB_ID, "status": "running"},
        ),
        (
            "get_job_status",
            {"job_id": VALID_JOB_ID, "status": "completed"},
        ),
        (
            "create_label_download",
            {
                "label_artifact_id": VALID_LABEL_ID,
                "status": "ready",
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "smuggled_status",
    [
        "https://labels.example/customer-label",
        "Bearer credential-secret-value",
        "Jane Doe, 742 Main Street",
    ],
)
def test_real_public_contract_rejects_data_smuggled_in_status(
    tool_name,
    safe_result,
    smuggled_status,
):
    contract = next(tool for tool in public_tools() if tool.name == tool_name)
    unsafe_result = {**safe_result, "status": smuggled_status}

    with pytest.raises(ValidationError):
        project_result(contract, unsafe_result)


@pytest.mark.parametrize(
    ("tool_name", "safe_result", "unsafe_result"),
    [
        (
            "get_shipagent_status",
            {
                "status": "ready",
                "executionTarget": {
                    "state": "ready",
                    "capabilities": ["shipment_ingress"],
                },
            },
            {
                "status": "ready",
                "executionTarget": {
                    "state": "https://private.invalid/device",
                    "capabilities": ["shipment_ingress"],
                },
            },
        ),
        (
            "get_shipagent_status",
            {
                "status": "ready",
                "executionTarget": {
                    "state": "ready",
                    "capabilities": ["shipment_ingress"],
                },
            },
            {
                "status": "ready",
                "executionTarget": {
                    "state": "ready",
                    "capabilities": ["Bearer projection-credential"],
                },
            },
        ),
        (
            "validate_shipment_address",
            {
                "validation_artifact_id": VALID_VALIDATION_ID,
                "valid": True,
                "guidance_codes": ["no_action_required"],
            },
            {
                "validation_artifact_id": "https://private.invalid/validation",
                "valid": True,
                "guidance_codes": ["no_action_required"],
            },
        ),
        (
            "get_shipment_rates",
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
            {
                "rates": [
                    {
                        "service_code": "https://private.invalid/service",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
        ),
        (
            "get_shipment_rates",
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "Private Recipient",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
        ),
        (
            "get_shipment_rates",
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "credential=projection-token",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
        ),
        (
            "get_shipment_rates",
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "17 Confidential Avenue",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
        ),
        (
            "get_shipment_rates",
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "2026-07-25",
                    }
                ],
                "selected": "03",
            },
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                        "estimated_delivery_date": "https://private.invalid/date",
                    }
                ],
                "selected": "03",
            },
        ),
        (
            "get_shipment_rates",
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                    }
                ],
                "selected": "03",
            },
            {
                "rates": [
                    {
                        "service_code": "03",
                        "service_name": "UPS Ground",
                        "total_charge": "12.34",
                        "currency_code": "USD",
                    }
                ],
                "selected": "Bearer projection-credential",
            },
        ),
        (
            "prepare_shipments",
            {
                "preview_id": VALID_PREVIEW_ID,
                "summary": {"shipment_count": 1},
            },
            {
                "preview_id": "Private Recipient at 17 Confidential Avenue",
                "summary": {"shipment_count": 1},
            },
        ),
        (
            "prepare_shipments",
            {
                "preview_id": VALID_PREVIEW_ID,
                "summary": {"shipment_count": 1},
            },
            {
                "preview_id": VALID_PREVIEW_ID,
                "summary": {"shipment_count": 1_000_001},
            },
        ),
        (
            "execute_shipments",
            {"job_id": VALID_JOB_ID, "status": "running"},
            {
                "job_id": "https://private.invalid/job?token=projection-credential",
                "status": "running",
            },
        ),
        (
            "create_label_download",
            {"label_artifact_id": VALID_LABEL_ID, "status": "ready"},
            {
                "label_artifact_id": "Private Recipient at 17 Confidential Avenue",
                "status": "ready",
            },
        ),
    ],
)
def test_real_public_contract_rejects_canaries_in_every_scalar_family(
    tool_name,
    safe_result,
    unsafe_result,
):
    contract = next(tool for tool in public_tools() if tool.name == tool_name)

    assert project_result(contract, safe_result) == safe_result
    with pytest.raises(ValidationError):
        project_result(contract, unsafe_result)


@pytest.mark.parametrize("family", PROVIDER_VISIBLE_ID_FAMILIES)
@pytest.mark.parametrize("canary_body", PREFIXED_COMPACT_CANARY_BODIES)
def test_direct_projection_rejects_prefixed_compact_canaries_for_every_id_family(
    family,
    canary_body,
):
    field_name = next(
        field_name
        for field_name, field_family in PROVIDER_VISIBLE_FIELD_FAMILIES.items()
        if field_family is family
    )
    contract = _contract(
        output_schema=object_schema(
            {
                field_name: shipagent_id_schema(
                    family,
                    "Canonical provider-visible ShipAgent identifier.",
                )
            },
            [field_name],
        )
    )
    valid_result = {field_name: mint_shipagent_id(family)}
    unsafe_result = {
        field_name: f"{shipagent_id_prefix(family)}{canary_body}",
    }

    assert project_result(contract, valid_result) == valid_result
    with pytest.raises(ValidationError):
        project_result(contract, unsafe_result)


def test_project_result_rejects_over_size_results():
    contract = _contract(max_result_bytes=1024)
    large = {"job_id": "x" * 2048}

    with pytest.raises(ValueError, match="exceeds contract size"):
        project_result(contract, large)


_ORIGIN_CANARY = "742 Canary Provider Way"


def _echo_contract():
    return _contract(
        result_profile="provider_ingress_echo",
        provider_originated_fields=["address_text"],
        output_schema={
            "type": "object",
            "properties": {"address_text": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
    )


def test_provider_originated_echo_requires_provider_origin_metadata():
    from src.registry.privacy import DataOrigin

    contract = _echo_contract()
    result = {"address_text": _ORIGIN_CANARY}

    assert (
        project_result(
            contract,
            result,
            field_origins={"address_text": DataOrigin.provider_supplied},
        )
        == result
    )
    for origins in (None, {}, {"address_text": DataOrigin.local_import}):
        with pytest.raises(ValueError, match="origin"):
            project_result(contract, result, field_origins=origins)


def test_origin_error_never_echoes_the_value():
    with pytest.raises(ValueError) as excinfo:
        project_result(_echo_contract(), {"address_text": _ORIGIN_CANARY})
    assert _ORIGIN_CANARY not in str(excinfo.value)


def test_absent_provider_originated_field_needs_no_origin():
    assert project_result(_echo_contract(), {}) == {}


@pytest.mark.parametrize("profile", ["provider_ingress_echo", "artifact_action"])
@pytest.mark.parametrize(
    "key",
    ["label_bytes", "credentials", "account_number", "raw_response", "request_body"],
)
def test_never_visible_keys_rejected_in_every_profile(profile, key):
    contract = _contract(
        result_profile=profile,
        output_schema={
            "type": "object",
            "properties": {key: {"type": "string"}},
            "required": [key],
            "additionalProperties": False,
        },
    )
    with pytest.raises(ValueError, match="forbidden"):
        project_result(contract, {key: "canary-value"})


def _label_contract():
    return _contract(
        result_profile="artifact_action",
        signed_download_fields=["download_url"],
        output_schema={
            "type": "object",
            "properties": {
                "download_url": {
                    "type": "string",
                    "pattern": "^https://",
                    "maxLength": 2048,
                },
                "expires_in_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                },
                "status": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
    )


def test_signed_download_url_must_be_plain_https_without_credentials():
    contract = _label_contract()
    good = {
        "download_url": "https://relay.example.invalid/d/opaque?sig=canary",
        "expires_in_seconds": 120,
        "status": "ready",
    }
    assert project_result(contract, good) == good
    for bad in (
        "http://relay.example.invalid/d/x",
        "file:///labels/canary.pdf",
        "data:application/pdf;base64,Q0FOQVJZ",
    ):
        with pytest.raises(ValidationError):
            project_result(
                contract,
                {"download_url": bad, "status": "ready", "expires_in_seconds": 60},
            )
    for bad in (
        "https://user:pw@relay.example.invalid/d/x",
        "https://relay.example.invalid/d/x#frag",
        "https:///nohost",
    ):
        with pytest.raises(ValueError, match="signed download"):
            project_result(
                contract,
                {"download_url": bad, "status": "ready", "expires_in_seconds": 60},
            )


# --- PR #52 review fixes: real registry contracts, realistic values -----------


def _registry_contract(name: str) -> ToolContract:
    return next(t for t in public_tools() if t.name == name)


def _provider_origin():
    from src.registry.privacy import DataOrigin

    return {"address_text": DataOrigin.provider_supplied}


def _address_result(text: str) -> dict:
    return {
        "validation_artifact_id": VALID_VALIDATION_ID,
        "valid": True,
        "guidance_codes": [],
        "address_text": text,
    }


@pytest.mark.parametrize(
    "text",
    ["123 Main St", "Maple Road", "742 Evergreen Terrace, Springfield, IL 62704"],
)
def test_real_address_contract_accepts_realistic_provider_echo(text):
    contract = _registry_contract("validate_shipment_address")
    result = _address_result(text)
    assert project_result(contract, result, field_origins=_provider_origin()) == result


@pytest.mark.parametrize(
    "text", ["12 Main\x00St", "12 Main\tSt", "12 Main\nSt", "12 Main St\n"]
)
def test_real_address_contract_rejects_control_characters(text):
    contract = _registry_contract("validate_shipment_address")
    with pytest.raises((ValueError, ValidationError)):
        project_result(
            contract, _address_result(text), field_origins=_provider_origin()
        )


def test_echo_origin_must_be_a_data_origin_not_a_string():
    contract = _registry_contract("validate_shipment_address")
    with pytest.raises(ValueError, match="origin"):
        project_result(
            contract,
            _address_result("123 Main St"),
            field_origins={"address_text": "provider_supplied"},
        )


def _label_result(**overrides) -> dict:
    result = {
        "label_artifact_id": VALID_LABEL_ID,
        "status": "ready",
        "download_url": "https://dl.example.com/labels/a.pdf?sig=abc123&exp=1893456000",
        "expires_in_seconds": 120,
    }
    result.update(overrides)
    return {k: v for k, v in result.items() if v is not None}


def test_real_label_contract_accepts_realistic_signed_url():
    contract = _registry_contract("create_label_download")
    result = _label_result()
    assert project_result(contract, result) == result


@pytest.mark.parametrize(
    "url",
    [
        "https://dl.example.com/a b.pdf?sig=abc",
        "https://dl.example.com/a.pdf?sig=abc\n",
        "https://dl.example.com/a.pdf\t?sig=abc",
        "https://dl.example.com/a.pdf\x00?sig=abc",
        "https://dl.example.com/a.pdf\x7f",
    ],
)
def test_real_label_contract_rejects_whitespace_and_control_in_url(url):
    contract = _registry_contract("create_label_download")
    with pytest.raises((ValueError, ValidationError)):
        project_result(contract, _label_result(download_url=url))


def test_real_label_contract_requires_expiry_with_url():
    contract = _registry_contract("create_label_download")
    with pytest.raises((ValueError, ValidationError)):
        project_result(contract, _label_result(expires_in_seconds=None))


@pytest.mark.parametrize("status", ["pending", "unavailable"])
def test_real_label_contract_allows_url_only_when_ready(status):
    contract = _registry_contract("create_label_download")
    with pytest.raises((ValueError, ValidationError)):
        project_result(contract, _label_result(status=status))


def test_real_label_contract_allows_not_ready_without_url():
    contract = _registry_contract("create_label_download")
    result = _label_result(status="pending", download_url=None, expires_in_seconds=None)
    assert project_result(contract, result) == result


def test_synthetic_label_contract_enforces_expiry_and_ready_status():
    contract = _label_contract()
    url = "https://relay.example.invalid/d/opaque?sig=canary"
    with pytest.raises((ValueError, ValidationError)):
        project_result(contract, {"download_url": url, "status": "ready"})
    with pytest.raises((ValueError, ValidationError)):
        project_result(
            contract,
            {"download_url": url, "status": "pending", "expires_in_seconds": 60},
        )
