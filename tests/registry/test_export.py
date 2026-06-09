import json
from pathlib import Path

from src.registry.catalog import load_registry
from src.registry.export import registry_to_json_dict, write_registry_snapshot

ROOT = Path(__file__).resolve().parents[2]
GENERATED_REGISTRY_SNAPSHOT = (
    ROOT / "generated" / "provider_artifacts" / "registry.json"
)
EXPECTED_TOOL_NAMES = [
    "get_shipagent_status",
    "submit_one_off_shipment",
    "validate_shipment_address",
    "get_shipment_rates",
    "prepare_shipments",
    "execute_shipments",
    "get_job_status",
    "create_label_download",
    "raw_ups_tool",
]


def expected_registry_text() -> str:
    return (
        json.dumps(registry_to_json_dict(load_registry()), indent=2, sort_keys=True)
        + "\n"
    )


def test_registry_to_json_dict_is_stable():
    payload = registry_to_json_dict(load_registry())

    assert payload["schema_version"] == "1.0.0"
    assert len(payload["tools"]) == len(EXPECTED_TOOL_NAMES)
    assert [tool["name"] for tool in payload["tools"]] == EXPECTED_TOOL_NAMES
    assert "input_schema" in payload["tools"][0]


def test_write_registry_snapshot(tmp_path):
    out = tmp_path / "registry.json"

    write_registry_snapshot(out, load_registry())

    assert out.read_text(encoding="utf-8") == expected_registry_text()


def test_checked_in_registry_snapshot_matches_current_export():
    assert (
        GENERATED_REGISTRY_SNAPSHOT.read_text(encoding="utf-8")
        == expected_registry_text()
    )
