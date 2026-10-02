import pytest

from src.registry.catalog import public_tools
from src.registry.identifiers import (
    PROVIDER_VISIBLE_FIELD_FAMILIES,
    PROVIDER_VISIBLE_ID_FAMILIES,
    mint_shipagent_id,
    parse_shipagent_id,
    shipagent_id_pattern,
    shipagent_id_prefix,
    shipagent_id_schema,
)
from src.registry.models import SideEffectClass
from src.registry.tools.public import public_tool
from src.registry.tools.schema import object_schema


def test_server_minted_provider_identifiers_round_trip_for_every_family():
    for family in PROVIDER_VISIBLE_ID_FAMILIES:
        identifier = mint_shipagent_id(family)

        parsed = parse_shipagent_id(identifier)

        assert parsed.family is family
        assert parsed.hex_body == identifier.removeprefix(f"sa_{family.value}_")
        assert len(parsed.hex_body) == 32
        assert parsed.hex_body == parsed.hex_body.lower()
        assert all(character in "0123456789abcdef" for character in parsed.hex_body)


def test_every_provider_visible_identifier_schema_uses_its_exact_family_format():
    seen_fields: set[str] = set()

    def assert_identifiers(schema: dict[str, object]) -> None:
        if schema["type"] == "object":
            properties = schema["properties"]
            assert isinstance(properties, dict)
            for field_name, field_schema in properties.items():
                assert isinstance(field_name, str)
                assert isinstance(field_schema, dict)
                if field_name.endswith(("_id", "_reference")):
                    family = PROVIDER_VISIBLE_FIELD_FAMILIES[field_name]
                    prefix = shipagent_id_prefix(family)
                    assert field_schema["pattern"] == shipagent_id_pattern(family)
                    assert field_schema["minLength"] == len(prefix) + 32
                    assert field_schema["maxLength"] == len(prefix) + 32
                    seen_fields.add(field_name)
                assert_identifiers(field_schema)
        elif schema["type"] == "array":
            items = schema["items"]
            assert isinstance(items, dict)
            assert_identifiers(items)

    for contract in public_tools():
        assert_identifiers(contract.input_schema)
        assert_identifiers(contract.output_schema)

    # The relay status tool replaced active_device_id with executionTarget.state, so
    # the registered device field is reserved until a public tool exposes it again.
    reserved_unused_fields = {"active_device_id"}
    assert seen_fields == set(PROVIDER_VISIBLE_FIELD_FAMILIES) - reserved_unused_fields


def test_public_provider_contract_rejects_handwritten_permissive_identifier_schema():
    permissive_job_id = {
        "type": "string",
        "pattern": r"^sa_job_[A-Za-z0-9_-]{16,96}$",
        "minLength": 23,
        "maxLength": 103,
    }

    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "identifier_schema_probe",
            "Identifier schema probe",
            "A provider-visible contract used to verify canonical identifier schemas.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            object_schema({"job_id": permissive_job_id}, ["job_id"]),
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    "field_name",
    ["artifactId", "ArtifactReference", "artifactID"],
)
def test_public_provider_contract_rejects_unregistered_cased_identifier_aliases(
    field_name: str,
):
    permissive_identifier = {
        "type": "string",
        "pattern": r"^[A-Za-z0-9_-]+$",
        "minLength": 1,
        "maxLength": 128,
    }

    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "identifier_alias_probe",
            "Identifier alias probe",
            "A provider-visible contract used to reject unregistered identifier aliases.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            object_schema({field_name: permissive_identifier}, [field_name]),
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "artifact_id",
        "artifact-ids",
        "artifact.references",
        "artifactid",
        "artifactreferences",
        "job_ids",
    ],
)
def test_public_provider_contract_rejects_unregistered_identifier_shapes(
    field_name: str,
):
    permissive_identifier = {
        "type": "string",
        "pattern": r"^[A-Za-z0-9_-]+$",
        "minLength": 1,
        "maxLength": 128,
    }

    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "identifier_shape_probe",
            "Identifier shape probe",
            "A provider-visible contract used to reject unregistered identifier shapes.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            object_schema({field_name: permissive_identifier}, [field_name]),
            provider_export_enabled=True,
        )


def test_public_provider_contract_requires_array_schema_for_plural_identifiers():
    job_id = shipagent_id_schema(
        PROVIDER_VISIBLE_FIELD_FAMILIES["job_id"],
        "Canonical shipment job identifier.",
    )

    with pytest.raises(ValueError, match="provider privacy"):
        public_tool(
            "plural_identifier_probe",
            "Plural identifier probe",
            "A provider-visible contract used to enforce plural identifier shapes.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            object_schema({"job_ids": job_id}, ["job_ids"]),
            provider_export_enabled=True,
        )


def test_public_provider_contract_rejects_unregistered_identifiers_recursively():
    permissive_identifier = {
        "type": "string",
        "pattern": r"^[A-Za-z0-9_-]+$",
        "minLength": 1,
        "maxLength": 128,
    }
    nested_output = object_schema(
        {
            "groups": {
                "type": "array",
                "items": object_schema(
                    {"ArtifactReferences": permissive_identifier},
                    ["ArtifactReferences"],
                ),
                "maxItems": 10,
            }
        },
        ["groups"],
    )

    with pytest.raises(ValueError, match=r"output\.groups\.ArtifactReferences"):
        public_tool(
            "nested_identifier_probe",
            "Nested identifier probe",
            "A provider-visible contract used to reject nested identifier aliases.",
            SideEffectClass.read,
            ["tools:read"],
            object_schema({}, []),
            nested_output,
            provider_export_enabled=True,
        )


@pytest.mark.parametrize(
    ("field_name", "family_field", "plural"),
    [
        ("job_id", "job_id", False),
        ("jobId", "job_id", False),
        ("JobID", "job_id", False),
        ("job-id", "job_id", False),
        ("job.id", "job_id", False),
        ("jobid", "job_id", False),
        ("job_ids", "job_id", True),
        ("inputReferences", "input_reference", True),
    ],
)
def test_public_provider_contract_accepts_registered_identifier_aliases_with_exact_schema(
    field_name: str,
    family_field: str,
    plural: bool,
):
    identifier_schema = shipagent_id_schema(
        PROVIDER_VISIBLE_FIELD_FAMILIES[family_field],
        "Canonical provider-visible identifier.",
    )
    field_schema = (
        {
            "type": "array",
            "items": identifier_schema,
            "maxItems": 10,
        }
        if plural
        else identifier_schema
    )

    tool = public_tool(
        "registered_identifier_probe",
        "Registered identifier probe",
        "A provider-visible contract used to admit registered identifier aliases.",
        SideEffectClass.read,
        ["tools:read"],
        object_schema({}, []),
        object_schema({field_name: field_schema}, [field_name]),
        provider_export_enabled=True,
    )

    assert tool.output_schema["properties"][field_name] == field_schema
