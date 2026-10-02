"""ADR 0007 origin-based visibility: registry contracts and privacy validators.

All values are synthetic canaries; nothing here is real customer data.
"""

import pytest
from pydantic import ValidationError

from src.registry.catalog import public_tools
from src.registry.models import SideEffectClass
from src.registry.privacy import (
    MAX_SIGNED_DOWNLOAD_TTL_SECONDS,
    provider_schema_privacy_violations,
)
from src.registry.tools.public import public_tool
from src.registry.tools.schema import object_schema

ECHO_TEXT = {
    "type": "string",
    "pattern": r"^[A-Za-z0-9 ,.#-]{1,200}$",
    "minLength": 1,
    "maxLength": 200,
}
SIGNED_URL = {
    "type": "string",
    "pattern": r"^https://[^\s]{1,2040}$",
    "minLength": 9,
    "maxLength": 2048,
}
TTL = {"type": "integer", "minimum": 1, "maximum": MAX_SIGNED_DOWNLOAD_TTL_SECONDS}


def _echo_tool(**overrides):
    kwargs = {
        "result_profile": "provider_ingress_echo",
        "provider_originated_fields": ["address_text"],
        "provider_export_enabled": True,
    }
    kwargs.update(overrides)
    schema = kwargs.pop("output_schema", object_schema({"address_text": ECHO_TEXT}, []))
    return public_tool(
        "echo_probe",
        "Echo probe",
        "Echo provider supplied text back to the provider conversation.",
        SideEffectClass.read,
        ["tools:read"],
        object_schema({}, []),
        schema,
        **kwargs,
    )


def _label_tool(**overrides):
    kwargs = {
        "result_profile": "artifact_action",
        "signed_download_fields": ["download_url"],
        "provider_export_enabled": True,
    }
    kwargs.update(overrides)
    schema = kwargs.pop(
        "output_schema",
        object_schema({"download_url": SIGNED_URL, "expires_in_seconds": TTL}, []),
    )
    return public_tool(
        "create_label_download",
        "Create label download",
        "Create a short-lived signed label download for the account.",
        SideEffectClass.read,
        ["labels:read"],
        object_schema({}, []),
        schema,
        **kwargs,
    )


def test_declared_provider_originated_address_text_is_permitted():
    assert _echo_tool().output_schema["properties"]["address_text"]


def test_undeclared_address_text_is_still_rejected():
    with pytest.raises(ValueError, match="provider privacy"):
        _echo_tool(provider_originated_fields=[])


def test_origin_declaration_requires_echo_profile():
    with pytest.raises(ValueError, match="provider_ingress_echo"):
        _echo_tool(result_profile="aggregate")


def test_origin_declaration_must_name_an_output_property():
    with pytest.raises(ValueError, match="not an output property"):
        _echo_tool(provider_originated_fields=["missing_text"])


@pytest.mark.parametrize("field", ["customer_rows", "request_payload", "api_key"])
def test_origin_declaration_never_lifts_other_privacy_families(field):
    schema = object_schema({field: ECHO_TEXT}, [])
    with pytest.raises(ValueError, match="provider privacy"):
        _echo_tool(output_schema=schema, provider_originated_fields=[field])


def test_declared_signed_label_url_is_permitted_with_short_ttl():
    assert _label_tool().signed_download_fields == ["download_url"]


def test_undeclared_label_url_is_still_rejected():
    schema = object_schema({"label_url": SIGNED_URL, "expires_in_seconds": TTL}, [])
    with pytest.raises(ValueError, match="provider privacy"):
        _label_tool(output_schema=schema, signed_download_fields=[])


@pytest.mark.parametrize("field", ["label_bytes", "label_base64", "label_data"])
def test_signed_url_declaration_never_permits_label_bytes(field):
    schema = object_schema({field: SIGNED_URL, "expires_in_seconds": TTL}, [])
    with pytest.raises(ValueError, match="provider privacy"):
        _label_tool(output_schema=schema, signed_download_fields=[field])


def test_signed_url_requires_artifact_action_profile():
    with pytest.raises(ValueError, match="artifact_action"):
        _label_tool(result_profile="aggregate")


def test_signed_url_requires_https_bounded_string_schema():
    http_url = {**SIGNED_URL, "pattern": r"^http://[^\s]{1,2040}$"}
    schema = object_schema({"download_url": http_url, "expires_in_seconds": TTL}, [])
    with pytest.raises(ValueError, match="https"):
        _label_tool(output_schema=schema)


def test_signed_url_requires_short_ttl_sibling():
    schema = object_schema({"download_url": SIGNED_URL}, [])
    with pytest.raises(ValueError, match="expires_in_seconds"):
        _label_tool(output_schema=schema)

    long_ttl = {**TTL, "maximum": MAX_SIGNED_DOWNLOAD_TTL_SECONDS + 1}
    schema = object_schema(
        {"download_url": SIGNED_URL, "expires_in_seconds": long_ttl}, []
    )
    with pytest.raises(ValueError, match="expires_in_seconds"):
        _label_tool(output_schema=schema)


def test_origin_fields_must_be_lists_of_paths():
    with pytest.raises(ValidationError):
        _echo_tool(provider_originated_fields="address_text")


def test_registry_label_contract_carries_signed_url_and_stays_dormant():
    tool = next(t for t in public_tools() if t.name == "create_label_download")
    props = tool.output_schema["properties"]
    assert {"label_artifact_id", "status", "download_url", "expires_in_seconds"} <= set(
        props
    )
    assert tool.signed_download_fields == ["download_url"]
    assert tool.result_profile == "artifact_action"
    assert tool.provider_export_enabled is False
    assert provider_schema_privacy_violations(tool.name, tool.output_schema) == [
        "download_url"
    ]


def test_registry_address_validation_declares_provider_originated_echo():
    tool = next(t for t in public_tools() if t.name == "validate_shipment_address")
    assert tool.result_profile == "provider_ingress_echo"
    assert tool.provider_originated_fields == ["address_text"]
    assert tool.provider_export_enabled is False


def test_only_status_tool_is_exported():
    exported = [t.name for t in public_tools() if t.provider_export_enabled]
    assert exported == ["get_shipagent_status"]
