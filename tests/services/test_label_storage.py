"""Tests for label storage backend selection."""

from pathlib import Path

import pytest

from src.services.label_storage import LocalLabelStorage, build_label_storage


def test_build_label_storage_defaults_to_local(tmp_path: Path, monkeypatch):
    """Without explicit backend, local filesystem storage is used."""
    monkeypatch.delenv("LABEL_STORAGE_BACKEND", raising=False)
    storage = build_label_storage(tmp_path / "labels")
    assert isinstance(storage, LocalLabelStorage)


def test_build_label_storage_requires_bucket_for_s3(tmp_path: Path, monkeypatch):
    """S3 backend without bucket should fail fast with clear error."""
    monkeypatch.setenv("LABEL_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("LABEL_STORAGE_S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        build_label_storage(tmp_path / "labels")
