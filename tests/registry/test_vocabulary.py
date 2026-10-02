"""Canonical shared vocabularies for privacy keys and status capabilities."""

from src.control_plane import execution_targets, request_controls, result_projection
from src.registry import privacy, vocabulary
from src.registry.catalog import public_tools
from src.services import desktop_relay_client


def test_status_capabilities_have_one_canonical_home():
    assert execution_targets.PUBLIC_STATUS_CAPABILITIES is (
        vocabulary.PUBLIC_STATUS_CAPABILITIES
    )
    codes = vocabulary.SHIPAGENT_CAPABILITY_CODES
    assert len(codes) == len(set(codes))
    assert set(vocabulary.RELAY_TOOL_CAPABILITIES) <= set(codes)
    assert set(vocabulary.WORKFLOW_CAPABILITY_CODES) <= set(codes)
    assert vocabulary.PUBLIC_STATUS_CAPABILITIES == set(
        vocabulary.RELAY_TOOL_CAPABILITIES
    )


def test_relay_version_metadata_publishes_only_canonical_capabilities():
    published = desktop_relay_client.default_relay_version_metadata().capabilities
    assert set(published) <= vocabulary.PUBLIC_STATUS_CAPABILITIES


def test_status_schema_enum_is_the_canonical_vocabulary():
    tool = next(t for t in public_tools() if t.name == "get_shipagent_status")
    enum = tool.output_schema["properties"]["executionTarget"]["properties"][
        "capabilities"
    ]["items"]["enum"]
    assert enum == list(vocabulary.SHIPAGENT_CAPABILITY_CODES)


def test_sensitive_key_vocabularies_are_canonical():
    assert request_controls.CREDENTIAL_ARGUMENT_KEYS is privacy.CREDENTIAL_ARGUMENT_KEYS
    assert result_projection.FORBIDDEN_AGGREGATE_KEYS == (
        privacy.ALWAYS_FORBIDDEN_RESULT_KEYS | privacy.LOCAL_DATA_RESULT_KEYS
    )
    assert not privacy.ALWAYS_FORBIDDEN_RESULT_KEYS & privacy.LOCAL_DATA_RESULT_KEYS
