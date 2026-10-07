"""Installed and frozen carrier contracts are complete, read-only resources."""

from pathlib import Path
from unittest.mock import patch

import pytest
from ups_mcp.openapi_registry import DEFAULT_SPEC_FILES, OpenAPIRegistry

from src.services.ups_specs import ensure_ups_specs_dir


def test_installed_specs_work_read_only_and_include_real_transit():
    """No writes into the bundle, and no empty replacement for transit."""
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("read-only install")):
        result = Path(ensure_ups_specs_dir())
    assert all((result / name).is_file() for name in DEFAULT_SPEC_FILES)
    registry = OpenAPIRegistry.from_spec_files(result / name for name in DEFAULT_SPEC_FILES)
    assert registry.get_operation("TimeInTransit").path == "/shipments/{version}/transittimes"
    assert len(registry.list_operations(include_deprecated=True)) == 25


@pytest.mark.parametrize("missing", DEFAULT_SPEC_FILES)
def test_incomplete_installed_contract_fails_without_creating_placeholders(tmp_path, missing):
    specs = tmp_path / "specs"
    specs.mkdir()
    for name in DEFAULT_SPEC_FILES:
        if name != missing:
            (specs / name).write_text("openapi: 3.0.3\npaths: {}\n")
    with patch("src.services.ups_specs.files", return_value=tmp_path):
        with pytest.raises(RuntimeError, match=missing):
            ensure_ups_specs_dir()
    assert not (specs / missing).exists()


def test_pinned_resources_preserve_every_interpreted_project_operation():
    """The former docs cache's 24 routes/parameters survive resource selection."""
    docs = Path(__file__).resolve().parents[2] / "docs"
    project_names = {"Rating.yaml": "rating.yaml", "Shipping.yaml": "shipping.yaml"}
    previous = OpenAPIRegistry.from_spec_texts(
        (name, (docs / project_names.get(name, name)).read_text())
        for name in DEFAULT_SPEC_FILES
        if name != "TimeInTransit.yaml"
    )
    installed = Path(ensure_ups_specs_dir())
    current = OpenAPIRegistry.from_spec_files(installed / name for name in DEFAULT_SPEC_FILES)
    prior_operations = previous.list_operations(include_deprecated=True)
    assert len(prior_operations) == 24
    for operation in prior_operations:
        assert current.get_operation(operation.operation_id) == operation
