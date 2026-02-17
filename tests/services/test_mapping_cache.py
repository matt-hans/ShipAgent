"""Tests for verified column mapping cache."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import src.services.mapping_cache as mapping_cache


@pytest.fixture(autouse=True)
def _cache_env(monkeypatch, tmp_path):
    cache_file = tmp_path / ".cache" / "column_mapping" / "active.json"
    monkeypatch.setenv("COLUMN_MAPPING_CACHE_ENABLED", "true")
    monkeypatch.setenv("COLUMN_MAPPING_CACHE_FILE", str(cache_file))
    mapping_cache.invalidate()
    yield cache_file
    mapping_cache.invalidate()


def _source_columns() -> list[str]:
    return ["Name", "Address", "City", "State", "ZIP", "Country", "Weight"]


def _sample_rows() -> list[dict[str, str]]:
    return [
        {
            "Name": "Alice",
            "Address": "123 Main",
            "City": "Los Angeles",
            "State": "CA",
            "ZIP": "90001",
            "Country": "US",
            "Weight": "2.5",
        }
    ]


def test_cache_miss_computes_and_persists(_cache_env):
    mapping = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-1",
        sample_rows=_sample_rows(),
    )

    assert mapping.get("shipTo.name") == "Name"
    assert _cache_env.exists()


def test_cache_hit_returns_memory_cached_mapping(monkeypatch):
    calls = {"count": 0}
    real = mapping_cache.auto_map_columns

    def _counting(columns):
        calls["count"] += 1
        return real(columns)

    monkeypatch.setattr(mapping_cache, "auto_map_columns", _counting)
    first = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-2",
        sample_rows=_sample_rows(),
    )
    second = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-2",
        sample_rows=_sample_rows(),
    )

    assert calls["count"] == 1
    assert first == second


def test_cold_process_loads_from_disk_cache(monkeypatch):
    first = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-3",
        sample_rows=_sample_rows(),
    )

    mapping_cache._cached_fingerprint = None
    mapping_cache._cached_columns = None
    mapping_cache._cached_mapping = None

    def _fail(_columns):
        raise AssertionError("auto_map_columns should not run for disk cache hit")

    monkeypatch.setattr(mapping_cache, "auto_map_columns", _fail)
    second = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-3",
        sample_rows=_sample_rows(),
    )

    assert second == first


def test_fingerprint_change_forces_recompute(monkeypatch):
    calls = {"count": 0}
    real = mapping_cache.auto_map_columns

    def _counting(columns):
        calls["count"] += 1
        return real(columns)

    monkeypatch.setattr(mapping_cache, "auto_map_columns", _counting)
    mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-a",
        sample_rows=_sample_rows(),
    )
    mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-b",
        sample_rows=_sample_rows(),
    )

    assert calls["count"] == 2


def test_invalid_cache_file_is_ignored_and_recomputed(_cache_env, monkeypatch):
    _cache_env.parent.mkdir(parents=True, exist_ok=True)
    _cache_env.write_text("not-json")

    calls = {"count": 0}
    real = mapping_cache.auto_map_columns

    def _counting(columns):
        calls["count"] += 1
        return real(columns)

    monkeypatch.setattr(mapping_cache, "auto_map_columns", _counting)
    mapping = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-4",
        sample_rows=_sample_rows(),
    )

    assert calls["count"] == 1
    assert mapping.get("shipTo.name") == "Name"


def test_verification_failure_is_not_persisted(_cache_env, monkeypatch):
    calls = {"count": 0}

    def _bad_mapping(_columns):
        calls["count"] += 1
        return {"shipTo.name": "Name"}  # missing required paths

    monkeypatch.setattr(mapping_cache, "auto_map_columns", _bad_mapping)
    first = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-bad",
        sample_rows=[],
    )
    second = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-bad",
        sample_rows=[],
    )

    assert first == {"shipTo.name": "Name"}
    assert second == {"shipTo.name": "Name"}
    assert calls["count"] == 2
    assert not _cache_env.exists()


def test_valid_mapping_persists_even_when_sample_values_are_blank(_cache_env, monkeypatch):
    calls = {"count": 0}

    def _mapping(_columns):
        calls["count"] += 1
        return {
            "shipTo.name": "Name",
            "shipTo.addressLine1": "Address",
            "shipTo.city": "City",
            "shipTo.stateProvinceCode": "State",
            "shipTo.postalCode": "ZIP",
            "shipTo.countryCode": "Country",
            "packages[0].weight": "Weight",
        }

    monkeypatch.setattr(mapping_cache, "auto_map_columns", _mapping)
    blank_sample = [
        {
            "Name": "",
            "Address": "",
            "City": "",
            "State": "",
            "ZIP": "",
            "Country": "",
            "Weight": "",
        }
    ]

    first = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-blank",
        sample_rows=blank_sample,
    )
    second = mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-blank",
        sample_rows=blank_sample,
    )

    assert first == second
    assert calls["count"] == 1
    assert _cache_env.exists()


def test_invalidate_clears_cache_and_file(_cache_env):
    mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-5",
        sample_rows=_sample_rows(),
    )
    assert _cache_env.exists()

    mapping_cache.invalidate()
    assert not _cache_env.exists()


def test_thread_safety_returns_consistent_results():
    barrier = threading.Barrier(8)
    results: list[dict[str, str]] = []

    def _run():
        barrier.wait()
        return mapping_cache.get_or_compute_mapping(
            source_columns=_source_columns(),
            schema_fingerprint="sig-thread",
            sample_rows=_sample_rows(),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(lambda _: _run(), range(8)):
            results.append(result)

    assert len(results) == 8
    assert all(r == results[0] for r in results)


def test_verification_sample_rows_are_capped(monkeypatch):
    """Verification should only inspect a bounded sample for O(1) behavior."""
    observed = {"rows": 0}
    real_verify = mapping_cache._verify_mapping

    def _capturing_verify(mapping, source_columns, sample_rows):
        observed["rows"] = len(sample_rows)
        return real_verify(mapping, source_columns, sample_rows)

    monkeypatch.setattr(mapping_cache, "_verify_mapping", _capturing_verify)
    monkeypatch.setenv("COLUMN_MAPPING_VERIFY_MAX_ROWS", "5")

    sample_rows = [{"Name": f"User {idx}", "Address": "A"} for idx in range(50)]
    mapping_cache.get_or_compute_mapping(
        source_columns=_source_columns(),
        schema_fingerprint="sig-cap",
        sample_rows=sample_rows,
    )

    assert observed["rows"] == 5
