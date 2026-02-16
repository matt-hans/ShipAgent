"""Unit tests for src/services/ups_specs.py.

Tests verify:
- Optional spec files are copied when source exists
- Missing optional spec files are silently skipped
- Required specs still work when optional specs are absent
"""

from pathlib import Path
from unittest.mock import patch


def test_ensure_ups_specs_dir_creates_optional_specs(tmp_path):
    """Optional spec files are copied when source exists."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "rating.yaml").write_text(
        "openapi: 3.0.3\ninfo:\n  title: Rating\npaths: {}"
    )
    (docs_dir / "shipping.yaml").write_text(
        "openapi: 3.0.3\ninfo:\n  title: Shipping\npaths: {}"
    )
    (docs_dir / "landed_cost.yaml").write_text(
        "openapi: 3.0.3\ninfo:\n  title: LandedCost\npaths: {}"
    )

    runtime_dir = tmp_path / ".cache" / "ups_mcp_specs"

    with (
        patch("src.services.ups_specs._SOURCE_DOCS_DIR", docs_dir),
        patch("src.services.ups_specs._RUNTIME_SPECS_DIR", runtime_dir),
    ):
        from src.services.ups_specs import ensure_ups_specs_dir

        result = ensure_ups_specs_dir()

    assert (Path(result) / "LandedCost.yaml").exists()


def test_ensure_ups_specs_dir_skips_missing_optional_specs(tmp_path):
    """Missing optional spec files are silently skipped."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "rating.yaml").write_text(
        "openapi: 3.0.3\ninfo:\n  title: Rating\npaths: {}"
    )
    (docs_dir / "shipping.yaml").write_text(
        "openapi: 3.0.3\ninfo:\n  title: Shipping\npaths: {}"
    )
    # No landed_cost.yaml, paperless.yaml, etc.

    runtime_dir = tmp_path / ".cache" / "ups_mcp_specs"

    with (
        patch("src.services.ups_specs._SOURCE_DOCS_DIR", docs_dir),
        patch("src.services.ups_specs._RUNTIME_SPECS_DIR", runtime_dir),
    ):
        from src.services.ups_specs import ensure_ups_specs_dir

        result = ensure_ups_specs_dir()

    assert not (Path(result) / "LandedCost.yaml").exists()
    # Required specs still work
    assert (Path(result) / "Rating.yaml").exists()
