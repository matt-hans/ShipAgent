"""Keep local MCP fixture files inside their explicit per-test allowed root."""

import tempfile

import pytest


@pytest.fixture(autouse=True)
def _owned_temporary_source_files(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
