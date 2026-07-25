import pytest

from src.registry.catalog import load_registry, public_tools
from src.registry.models import ProviderExport, SideEffectClass, ToolVisibility
from src.registry.privacy import provider_schema_privacy_violations
from src.registry.tools.public import public_tool
from src.registry.tools.schema import object_schema

EXPECTED_PUBLIC = {
    "get_shipagent_status",
    "submit_one_off_shipment",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
}


def bounded_test_string_schema():
    return {
        "type": "string",
        "pattern": r"^[A-Z]{2}$",
        "minLength": 2,
        "maxLength": 2,
    }


def test_public_catalog_has_expected_tools():
    assert {tool.name for tool in public_tools()} == EXPECTED_PUBLIC


def test_public_tools_are_tenant_safe_and_provider_exportable():
    for tool in public_tools():
        assert tool.visibility == ToolVisibility.public
        assert tool.tenant_safe is True
        assert tool.implementation_status == "implemented"
        assert tool.hosted_readiness == "ready"
        assert tool.provider_export_enabled is True
        assert ProviderExport.openai_apps_public in tool.provider_exports
        assert ProviderExport.claude_remote_mcp_public in tool.provider_exports
        assert ProviderExport.generic_mcp in tool.provider_exports
        assert ProviderExport.anthropic not in tool.provider_exports


def test_public_tool_requires_explicit_provider_export_opt_in():
    # Omitting the argument exercises both the helper default and its forwarding
    # into ToolContract; either a True default or a hard-coded True forwarding
    # would make this contract observable as exportable and fail the assertion.
    tool = public_tool(
        "not_explicitly_exported",
        "Not explicitly exported",
        "A minimal public tool used to verify safe export defaults.",
        SideEffectClass.read,
        ["tools:read"],
        object_schema({}, []),
        object_schema({}, []),
    )

    assert tool.provider_export_enabled is False


def test_side_effecting_public_tools_require_confirmation():
    for tool in public_tools():
        if tool.side_effect in {
            SideEffectClass.write,
            SideEffectClass.purchase,
            SideEffectClass.external_mutation,
            SideEffectClass.destructive,
        }:
            assert tool.requires_confirmation is True


def test_execute_shipments_declares_prepare_tool_and_execution_gate():
    tool = next(tool for tool in public_tools() if tool.name == "execute_shipments")

    assert tool.prepare_tool == "prepare_shipments"
    assert tool.execution_target_required is True
    assert tool.confirmation_policy == "provider_and_shipagent"
    confirmation_schema = tool.input_schema["properties"]["confirmation_artifact_id"]
    assert confirmation_schema["pattern"].startswith("^sa_")
    assert confirmation_schema["maxLength"] <= 128


def test_public_input_schemas_are_closed():
    for tool in public_tools():
        assert tool.input_schema["additionalProperties"] is False


def test_public_provider_schemas_never_expose_sensitive_content_fields():
    violations = []
    for tool in public_tools():
        for direction, schema in (
            ("input", tool.input_schema),
            ("output", tool.output_schema),
        ):
            violations.extend(
                f"{tool.name}.{direction}.{path}"
                for path in provider_schema_privacy_violations(tool.name, schema)
            )

    assert violations == []


@pytest.mark.parametrize(
    ("tool_name", "field_name"),
    [
        ("create_label_download", "label_url"),
        ("create_label_download", "document_bytes"),
        ("create_label_download", "label_data"),
        ("execute_shipments", "provider_credentials"),
        ("execute_shipments", "confirmation_token"),
        ("get_shipment_rates", "raw_carrier_request"),
        ("get_shipment_rates", "carrier_response_body"),
    ],
)
def test_public_provider_contract_rejects_sensitive_transport_fields(
    tool_name,
    field_name,
):
    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            tool_name,
            "Unsafe provider tool",
            "A deliberately unsafe provider-visible contract used for validation.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            object_schema({field_name: bounded_test_string_schema()}, [field_name]),
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    "schema",
    [
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "oneOf": [object_schema({"api_key": {"type": "string"}}, ["api_key"])],
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "anyOf": [
                object_schema({"access_key": {"type": "string"}}, ["access_key"])
            ],
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "allOf": [
                object_schema(
                    {"authorization_header": {"type": "string"}},
                    ["authorization_header"],
                )
            ],
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "not": object_schema(
                {"bearer_value": {"type": "string"}}, ["bearer_value"]
            ),
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "$ref": "#",
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "$defs": {
                "hidden": object_schema(
                    {"credential_value": {"type": "string"}},
                    ["credential_value"],
                )
            },
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "definitions": {
                "hidden": object_schema(
                    {"customer_address": {"type": "string"}},
                    ["customer_address"],
                )
            },
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "if": object_schema({"auth_header": {"type": "string"}}, ["auth_header"]),
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "then": object_schema({"label_href": {"type": "string"}}, ["label_href"]),
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "else": object_schema(
                {"document_link": {"type": "string"}}, ["document_link"]
            ),
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "dependentSchemas": {
                "safe": object_schema(
                    {"raw_customer_row": {"type": "string"}},
                    ["raw_customer_row"],
                )
            },
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "dependentRequired": {"safe": ["api_key"]},
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "dependencies": {
                "safe": object_schema(
                    {"carrier_response_body": {"type": "string"}},
                    ["carrier_response_body"],
                )
            },
        },
        object_schema(
            {
                "values": {
                    "type": "array",
                    "prefixItems": [
                        object_schema({"api_key": {"type": "string"}}, ["api_key"])
                    ],
                    "items": {"type": "string"},
                }
            },
            ["values"],
        ),
        {
            **object_schema(
                {
                    "values": {
                        "type": "array",
                        "items": [
                            object_schema({"api_key": {"type": "string"}}, ["api_key"])
                        ],
                    }
                },
                ["values"],
            ),
            "$schema": "http://json-schema.org/draft-07/schema#",
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "patternProperties": {".*": {"type": "string"}},
        },
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "propertyNames": {"pattern": "credential"},
        },
        object_schema(
            {
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "contains": {"type": "string"},
                }
            },
            ["values"],
        ),
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "unevaluatedProperties": True,
        },
        object_schema(
            {
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "unevaluatedItems": {"type": "string"},
                }
            },
            ["values"],
        ),
        {
            "type": "object",
            "properties": {"safe": {"type": "string"}},
            "required": ["safe"],
        },
        {
            "type": "object",
            "properties": {"safe": {"type": "string"}},
            "required": ["safe"],
            "additionalProperties": True,
        },
        {
            "type": "object",
            "properties": {"safe": {"type": "string"}},
            "required": ["safe"],
            "additionalProperties": {"type": "string"},
        },
        {
            "type": "object",
            "required": [],
            "additionalProperties": False,
        },
        object_schema({"safe": True}, ["safe"]),
        object_schema({"safe": False}, ["safe"]),
        object_schema(
            {"values": {"type": "array", "items": True}},
            ["values"],
        ),
        object_schema(
            {"values": {"type": "array", "items": False}},
            ["values"],
        ),
        object_schema({"value": {"type": ["string", "null"]}}, ["value"]),
        {
            **object_schema({"safe": {"type": "string"}}, ["safe"]),
            "examples": [{"safe": "value"}],
        },
    ],
)
def test_public_provider_contract_rejects_schema_dialect_bypasses(schema):
    assert provider_schema_privacy_violations("schema_dialect_probe", schema)

    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "schema_dialect_probe",
            "Schema dialect probe",
            "A deliberately unsupported provider-visible schema dialect fixture.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            schema,
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "api_key",
        "apiKey",
        "APIKey",
        "xAPIKey",
        "access_key",
        "accessKey",
        "auth_header",
        "authHeader",
        "authorization_header",
        "authorizationHeader",
        "bearer_value",
        "bearerValue",
        "label_href",
        "labelHref",
        "document_link",
        "documentLink",
    ],
)
def test_public_provider_contract_rejects_sensitive_aliases(field_name):
    schema = object_schema(
        {field_name: bounded_test_string_schema()},
        [field_name],
    )

    assert provider_schema_privacy_violations("alias_probe", schema) == [field_name]
    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "alias_probe",
            "Sensitive alias probe",
            "A deliberately unsafe provider-visible naming alias fixture.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            schema,
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "apikey",
        "aPIkEY",
        "APIKEY",
        "accesskey",
        "aCCESSkEY",
        "ACCESSKEY",
        "authheader",
        "aUTHhEADER",
        "AUTHHEADER",
        "authorizationheader",
        "aUTHORIZATIONhEADER",
        "AUTHORIZATIONHEADER",
        "labelhref",
        "lABELhREF",
        "LABELHREF",
        "documentlink",
        "dOCUMENTlINK",
        "DOCUMENTLINK",
        "xapikey",
        "xAPIKey",
        "XAPIKEY",
        "bearervalue",
        "bearerValue",
        "BEARERVALUE",
        "customeraddress",
        "customerAddress",
        "CUSTOMERADDRESS",
        "customerpayload",
        "customerPayload",
        "CUSTOMERPAYLOAD",
        "customerrows",
        "customerRows",
        "CUSTOMERROWS",
        "confirmationtoken",
        "confirmationToken",
        "CONFIRMATIONTOKEN",
        "confirmationartifact",
        "confirmationArtifact",
        "CONFIRMATIONARTIFACT",
        "carrierrequestbody",
        "carrierRequestBody",
        "CARRIERREQUESTBODY",
        "carrierresponsebody",
        "carrierResponseBody",
        "CARRIERRESPONSEBODY",
        "labelpayload",
        "labelPayload",
        "LABELPAYLOAD",
        "documentpayload",
        "documentPayload",
        "DOCUMENTPAYLOAD",
    ],
)
def test_public_provider_contract_rejects_compact_sensitive_aliases(field_name):
    schema = object_schema(
        {field_name: bounded_test_string_schema()},
        [field_name],
    )

    assert provider_schema_privacy_violations("compact_alias_probe", schema) == [
        field_name
    ]
    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "compact_alias_probe",
            "Compact sensitive alias probe",
            "A provider-visible compact naming alias validation fixture.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            schema,
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        # Authentication-header family.
        "headerauthorization",
        "headerAuthorization",
        "HEADERAUTHORIZATION",
        # API/access-key family.
        "keyapi",
        "keyAPI",
        "KEYAPI",
        "keyaccess",
        "keyAccess",
        "KEYACCESS",
        # Label/document transfer family.
        "urllabel",
        "URLLabel",
        "URLLABEL",
        "datadocument",
        "dataDocument",
        "DATADOCUMENT",
        # Customer payload/address family.
        "payloadcustomer",
        "payloadCustomer",
        "PAYLOADCUSTOMER",
        "addresscustomer",
        "addressCustomer",
        "ADDRESSCUSTOMER",
        # Carrier exchange family.
        "bodyrequest",
        "bodyRequest",
        "BODYREQUEST",
        # Token/secret family.
        "valuetoken",
        "valueToken",
        "VALUETOKEN",
        "valuesecret",
        "valueSecret",
        "VALUESECRET",
    ],
)
def test_public_provider_contract_rejects_reversed_compact_sensitive_aliases(
    field_name,
):
    schema = object_schema(
        {field_name: bounded_test_string_schema()},
        [field_name],
    )

    assert provider_schema_privacy_violations(
        "reversed_compact_alias_probe", schema
    ) == [field_name]
    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "reversed_compact_alias_probe",
            "Reversed compact sensitive alias probe",
            "A provider-visible reversed compact naming alias validation fixture.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            schema,
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    ("field_name", "field_schema"),
    [
        (
            "validationArtifactId",
            {
                "type": "string",
                "pattern": r"^sa_validation_[A-Za-z0-9_-]{16,96}$",
                "minLength": 30,
                "maxLength": 110,
            },
        ),
        (
            "confirmationArtifactId",
            {
                "type": "string",
                "pattern": r"^sa_confirmation_[A-Za-z0-9_-]{16,96}$",
                "minLength": 32,
                "maxLength": 112,
            },
        ),
        ("serviceCode", {"type": "string", "enum": ["03"]}),
        (
            "shipmentCount",
            {"type": "integer", "minimum": 0, "maximum": 1_000_000},
        ),
        ("rowCount", {"type": "integer", "minimum": 0, "maximum": 1_000_000}),
        ("metadata", bounded_test_string_schema()),
    ],
)
def test_public_provider_contract_preserves_legitimate_compact_fields(
    field_name,
    field_schema,
):
    schema = object_schema({field_name: field_schema}, [field_name])

    assert provider_schema_privacy_violations("legitimate_probe", schema) == []


def test_shipment_content_tools_accept_only_bounded_shipagent_references():
    reference_fields = {
        "submit_one_off_shipment": "ingress_reference",
        "validate_shipment_address": "input_reference",
        "get_shipment_rates": "input_reference",
        "prepare_shipments": "input_reference",
    }

    for tool_name, field_name in reference_fields.items():
        tool = next(tool for tool in public_tools() if tool.name == tool_name)
        field_schema = tool.input_schema["properties"][field_name]
        assert field_schema["pattern"].startswith("^sa_")
        assert field_schema["maxLength"] <= 128


def test_address_validation_returns_only_an_opaque_artifact_and_guidance_codes():
    tool = next(
        tool for tool in public_tools() if tool.name == "validate_shipment_address"
    )
    properties = tool.output_schema["properties"]

    assert set(properties) == {"validation_artifact_id", "valid", "guidance_codes"}
    assert properties["validation_artifact_id"]["pattern"].startswith("^sa_")
    assert properties["guidance_codes"]["maxItems"] <= 8
    assert properties["guidance_codes"]["uniqueItems"] is True
    assert properties["guidance_codes"]["items"]["enum"]


def test_label_download_returns_only_an_opaque_handoff_artifact():
    tool = next(tool for tool in public_tools() if tool.name == "create_label_download")
    properties = tool.output_schema["properties"]

    assert set(properties) == {"label_artifact_id", "status"}
    assert properties["label_artifact_id"]["pattern"].startswith("^sa_")
    assert properties["label_artifact_id"]["maxLength"] <= 128


@pytest.mark.parametrize(
    ("tool_name", "expected_statuses"),
    [
        ("get_shipagent_status", ["ready", "degraded", "unavailable"]),
        (
            "execute_shipments",
            ["queued", "running", "completed", "failed", "cancelled"],
        ),
        (
            "get_job_status",
            ["queued", "running", "completed", "failed", "cancelled"],
        ),
        ("create_label_download", ["pending", "ready", "unavailable"]),
    ],
)
def test_public_status_outputs_are_bounded_enums(tool_name, expected_statuses):
    tool = next(tool for tool in public_tools() if tool.name == tool_name)

    assert tool.output_schema["properties"]["status"] == {
        "type": "string",
        "enum": expected_statuses,
    }


def test_prepare_tool_schema_is_strict():
    tool = next(tool for tool in public_tools() if tool.name == "prepare_shipments")

    assert set(tool.input_schema["properties"]) == {"input_reference"}
    assert "tenant_id" not in tool.input_schema["properties"]


def test_rate_results_use_closed_provider_safe_items():
    tool = next(tool for tool in public_tools() if tool.name == "get_shipment_rates")
    item_schema = tool.output_schema["properties"]["rates"]["items"]

    assert item_schema["additionalProperties"] is False
    assert set(item_schema["properties"]) == {
        "service_code",
        "service_name",
        "total_charge",
        "currency_code",
        "estimated_delivery_date",
    }


def test_submit_one_off_shipment_is_non_confirming_input_reference_entrypoint():
    tool = next(
        tool for tool in public_tools() if tool.name == "submit_one_off_shipment"
    )

    assert tool.requires_confirmation is False
    assert tool.side_effect == "estimate"
    assert tool.prepare_tool is None
    assert set(tool.input_schema["properties"]) == {"ingress_reference"}
    assert set(tool.output_schema["properties"]) == {"input_reference"}


def test_every_exported_scalar_family_is_bounded():
    violations: list[str] = []

    def audit(schema, path: str) -> None:
        schema_type = schema["type"]
        if schema_type == "object":
            for name, child in schema["properties"].items():
                audit(child, f"{path}.{name}")
        elif schema_type == "array":
            if "maxItems" not in schema:
                violations.append(f"{path}:array")
            audit(schema["items"], f"{path}[]")
        elif schema_type == "string":
            if (
                "enum" not in schema
                and not {
                    "pattern",
                    "minLength",
                    "maxLength",
                }
                <= schema.keys()
            ):
                violations.append(f"{path}:string")
        elif (
            schema_type in {"integer", "number"}
            and not {
                "minimum",
                "maximum",
            }
            <= schema.keys()
        ):
            violations.append(f"{path}:{schema_type}")

    for tool in public_tools():
        audit(tool.input_schema, f"{tool.name}.input")
        audit(tool.output_schema, f"{tool.name}.output")

    assert violations == []


def test_public_provider_contract_rejects_unbounded_string_scalar():
    schema = object_schema(
        {"display_code": {"type": "string"}},
        ["display_code"],
    )

    assert provider_schema_privacy_violations("scalar_probe", schema) == [
        "display_code"
    ]
    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "scalar_probe",
            "Scalar safety probe",
            "A provider-visible scalar constraint validation fixture.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            schema,
            provider_export_enabled=True,
        )


@pytest.mark.parametrize("schema_type", ["integer", "number"])
def test_public_provider_contract_rejects_unbounded_numeric_scalar(schema_type):
    schema = object_schema(
        {"aggregate_count": {"type": schema_type}},
        ["aggregate_count"],
    )

    assert provider_schema_privacy_violations("scalar_probe", schema) == [
        "aggregate_count"
    ]


def test_public_provider_contract_rejects_unbounded_array_scalar_family():
    schema = object_schema(
        {
            "result_codes": {
                "type": "array",
                "items": {"type": "string", "enum": ["ready"]},
            }
        },
        ["result_codes"],
    )

    assert provider_schema_privacy_violations("scalar_probe", schema) == [
        "result_codes"
    ]


def test_registry_loads_all_tools():
    registry = load_registry()
    tools_by_name = {tool.name: tool for tool in registry.tools}
    raw_ups_tool = tools_by_name["raw_ups_tool"]

    assert set(tools_by_name) == EXPECTED_PUBLIC | {"raw_ups_tool"}
    assert raw_ups_tool.visibility == ToolVisibility.private
    assert raw_ups_tool.provider_export_enabled is False
    assert raw_ups_tool.tenant_safe is False
