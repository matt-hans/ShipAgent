import pytest
from jsonschema import ValidationError

from src.control_plane.result_projection import project_result
from src.registry.models import ToolContract


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


def test_project_result_rejects_over_size_results():
    contract = _contract(max_result_bytes=1024)
    large = {"job_id": "x" * 2048}

    with pytest.raises(ValueError, match="exceeds contract size"):
        project_result(contract, large)
