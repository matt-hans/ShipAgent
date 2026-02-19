"""Verified process-global cache for auto_map_columns results.

Caches one active mapping keyed by schema fingerprint and source columns.
Persists a verified snapshot to a temp file for warm restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services.column_mapping import (
    REQUIRED_FIELDS,
    auto_map_columns,
    auto_map_columns_with_trace,
)

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1
MAPPING_VERSION = "mapping_cache_v2"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_VERIFY_SAMPLE_ROWS = 5
_DEFAULT_MAX_DISK_CACHE_FILES = 10

_lock = threading.Lock()
_cached_fingerprint: str | None = None
_cached_columns: tuple[str, ...] | None = None
_cached_mapping: dict[str, str] | None = None
_cached_mapping_hash: str | None = None
_cached_selection_trace: dict[str, Any] | None = None

_REQUIRED_PATH_TO_CANONICAL: dict[str, str] = {
    "shipTo.name": "ship_to_name",
    "shipTo.addressLine1": "ship_to_address1",
    "shipTo.city": "ship_to_city",
    "shipTo.stateProvinceCode": "ship_to_state",
    "shipTo.postalCode": "ship_to_postal_code",
    "shipTo.countryCode": "ship_to_country",
    "packages[0].weight": "weight",
}


def _is_cache_enabled() -> bool:
    raw = os.environ.get("COLUMN_MAPPING_CACHE_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _cache_dir() -> Path:
    """Return the directory used for per-fingerprint cache files."""
    raw = os.environ.get(
        "COLUMN_MAPPING_CACHE_FILE",
        ".cache/column_mapping/active.json",
    ).strip()
    path = Path(raw) if raw else Path(".cache/column_mapping/active.json")
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path.parent


def _fingerprint_cache_path(schema_fingerprint: str) -> Path:
    """Return per-fingerprint disk cache path inside the cache directory."""
    short = schema_fingerprint[:8]
    medium = schema_fingerprint[:12]
    return _cache_dir() / f"{short}_{medium}.json"


def _resolve_verify_sample_limit() -> int:
    """Resolve verification sample cap with a safe constant fallback."""
    raw = os.environ.get(
        "COLUMN_MAPPING_VERIFY_MAX_ROWS",
        str(_DEFAULT_VERIFY_SAMPLE_ROWS),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_VERIFY_SAMPLE_ROWS
    return max(1, value)


def _verify_mapping(
    mapping: dict[str, str],
    source_columns: list[str],
    sample_rows: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Validate mapping structure against source schema.

    Verification is intentionally schema-based (not row-value-based) so cache
    persistence remains stable across filtered subsets where required fields may
    be blank in the sampled rows.
    """
    # sample_rows is intentionally unused for data-value checks.
    # Verification is schema-structural only: we confirm mapped column names
    # exist in the source and required UPS fields are covered. Checking whether
    # individual row values are non-empty would cause valid mappings to be
    # rejected for filtered subsets where required fields are legitimately blank.
    # See: test_valid_mapping_persists_even_when_sample_values_are_blank
    logger.debug(
        "mapping_verify schema_columns=%d sample_rows=%d",
        len(source_columns),
        len(sample_rows),
    )
    column_set = set(source_columns)
    for mapped_col in mapping.values():
        if mapped_col not in column_set:
            return False, [f"mapped column not in source: {mapped_col!r}"]

    missing_required: list[str] = []
    for required_path in REQUIRED_FIELDS:
        canonical_key = _REQUIRED_PATH_TO_CANONICAL.get(required_path)
        mapped_col = mapping.get(required_path)
        if mapped_col in column_set:
            continue
        if canonical_key and canonical_key in column_set:
            continue
        if required_path not in mapping:
            missing_required.append(required_path)
    return len(missing_required) == 0, missing_required


def compute_mapping_hash(mapping: dict[str, str]) -> str:
    """Compute a deterministic hash for a mapping object."""
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_from_disk(
    schema_fingerprint: str,
    source_columns: list[str],
) -> tuple[dict[str, str], str, dict[str, Any]] | None:
    path = _fingerprint_cache_path(schema_fingerprint)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.info("mapping_cache_recompute reason=file_read_error error=%s", e)
        return None

    if raw.get("version") != _CACHE_VERSION:
        logger.info("mapping_cache_recompute reason=version_mismatch")
        return None
    if raw.get("schema_fingerprint") != schema_fingerprint:
        logger.info("mapping_cache_recompute reason=fingerprint_mismatch")
        return None

    cached_columns = raw.get("source_columns")
    if not isinstance(cached_columns, list) or cached_columns != source_columns:
        logger.info("mapping_cache_recompute reason=columns_mismatch")
        return None

    cached_mapping = raw.get("mapping")
    if not isinstance(cached_mapping, dict):
        logger.info("mapping_cache_recompute reason=mapping_shape_invalid")
        return None

    mapping: dict[str, str] = {}
    for k, v in cached_mapping.items():
        if not isinstance(k, str) or not isinstance(v, str):
            logger.info("mapping_cache_recompute reason=mapping_entry_invalid")
            return None
        mapping[k] = v
    mapping_hash = raw.get("mapping_hash")
    if not isinstance(mapping_hash, str) or not mapping_hash:
        mapping_hash = compute_mapping_hash(mapping)
    selection_trace_raw = raw.get("selection_trace")
    selection_trace: dict[str, Any] = {}
    if isinstance(selection_trace_raw, dict):
        selection_trace = selection_trace_raw
    return mapping, mapping_hash, selection_trace


def _persist_to_disk(
    schema_fingerprint: str,
    source_columns: list[str],
    mapping: dict[str, str],
    mapping_hash: str,
    selection_trace: dict[str, Any],
) -> None:
    path = _fingerprint_cache_path(schema_fingerprint)
    payload = {
        "version": _CACHE_VERSION,
        "schema_fingerprint": schema_fingerprint,
        "source_columns": source_columns,
        "mapping": mapping,
        "mapping_hash": mapping_hash,
        "selection_trace": selection_trace,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, sort_keys=True))
    os.replace(tmp_path, path)
    _evict_old_cache_files(path)


def _evict_old_cache_files(just_written: Path) -> None:
    """Remove oldest *.json files if the cache directory exceeds the max limit."""
    raw = os.environ.get(
        "COLUMN_MAPPING_MAX_DISK_CACHE_FILES",
        str(_DEFAULT_MAX_DISK_CACHE_FILES),
    ).strip()
    try:
        max_files = max(1, int(raw))
    except ValueError:
        max_files = _DEFAULT_MAX_DISK_CACHE_FILES
    try:
        existing = sorted(
            just_written.parent.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
        )
    except Exception:
        return
    while len(existing) > max_files:
        oldest = existing.pop(0)
        try:
            oldest.unlink(missing_ok=True)
            logger.info("mapping_cache_evict file=%s", oldest.name)
        except Exception as exc:
            logger.info("mapping_cache_evict_error file=%s error=%s", oldest.name, exc)


def get_or_compute_mapping(
    source_columns: list[str],
    schema_fingerprint: str | None,
    sample_rows: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Return cached mapping for this schema+columns, or compute safely."""
    mapping, _ = get_or_compute_mapping_with_metadata(
        source_columns=source_columns,
        schema_fingerprint=schema_fingerprint,
        sample_rows=sample_rows,
    )
    return mapping


def get_or_compute_mapping_with_metadata(
    source_columns: list[str],
    schema_fingerprint: str | None,
    sample_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], str]:
    """Return mapping plus stable mapping_hash for this schema+columns."""
    mapping, mapping_hash, _ = get_or_compute_mapping_with_diagnostics(
        source_columns=source_columns,
        schema_fingerprint=schema_fingerprint,
        sample_rows=sample_rows,
    )
    return mapping, mapping_hash


def get_or_compute_mapping_with_diagnostics(
    source_columns: list[str],
    schema_fingerprint: str | None,
    sample_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], str, dict[str, Any]]:
    """Return mapping, hash, and cache/selection diagnostics."""
    global _cached_fingerprint, _cached_columns, _cached_mapping
    global _cached_mapping_hash, _cached_selection_trace

    normalized_columns = sorted({str(col) for col in source_columns})
    verify_limit = _resolve_verify_sample_limit()
    sample = (sample_rows or [])[:verify_limit]

    if not schema_fingerprint or not _is_cache_enabled():
        mapping = auto_map_columns(normalized_columns)
        _, selection_trace = auto_map_columns_with_trace(normalized_columns)
        return (
            mapping,
            compute_mapping_hash(mapping),
            {
                "cache_hit": False,
                "cache_source": "disabled",
                "schema_fingerprint": schema_fingerprint or "",
                "selection_trace": selection_trace,
            },
        )

    cols_key = tuple(normalized_columns)
    with _lock:
        if (
            _cached_fingerprint == schema_fingerprint
            and _cached_columns == cols_key
            and _cached_mapping is not None
            and _cached_mapping_hash is not None
        ):
            logger.debug(
                "mapping_cache_hit source=memory fingerprint=%s",
                schema_fingerprint[:12],
            )
            return (
                _cached_mapping,
                _cached_mapping_hash,
                {
                    "cache_hit": True,
                    "cache_source": "memory",
                    "schema_fingerprint": schema_fingerprint,
                    "selection_trace": _cached_selection_trace or {},
                },
            )

    cached_from_disk = _load_from_disk(schema_fingerprint, normalized_columns)
    if cached_from_disk is not None:
        cached_mapping, cached_hash, cached_trace = cached_from_disk
        with _lock:
            _cached_fingerprint = schema_fingerprint
            _cached_columns = cols_key
            _cached_mapping = cached_mapping
            _cached_mapping_hash = cached_hash
            _cached_selection_trace = cached_trace
        logger.info(
            "mapping_cache_hit source=disk fingerprint=%s mapped_fields=%d",
            schema_fingerprint[:12],
            len(cached_mapping),
        )
        return (
            cached_mapping,
            cached_hash,
            {
                "cache_hit": True,
                "cache_source": "disk",
                "schema_fingerprint": schema_fingerprint,
                "selection_trace": cached_trace,
            },
        )

    mapping = auto_map_columns(normalized_columns)
    _, selection_trace = auto_map_columns_with_trace(normalized_columns)
    mapping_hash = compute_mapping_hash(mapping)
    verified, details = _verify_mapping(mapping, normalized_columns, sample)
    if verified:
        try:
            _persist_to_disk(
                schema_fingerprint,
                normalized_columns,
                mapping,
                mapping_hash,
                selection_trace,
            )
        except Exception as e:
            logger.info("mapping_cache_recompute reason=file_write_error error=%s", e)
        with _lock:
            _cached_fingerprint = schema_fingerprint
            _cached_columns = cols_key
            _cached_mapping = mapping
            _cached_mapping_hash = mapping_hash
            _cached_selection_trace = selection_trace
        logger.info(
            "mapping_cache_miss fingerprint=%s mapped_fields=%d rows_sampled=%d mapping_hash=%s",
            schema_fingerprint[:12],
            len(mapping),
            len(sample),
            mapping_hash[:12],
        )
        return (
            mapping,
            mapping_hash,
            {
                "cache_hit": False,
                "cache_source": "computed",
                "schema_fingerprint": schema_fingerprint,
                "selection_trace": selection_trace,
            },
        )

    logger.warning(
        "mapping_cache_verify_fail fingerprint=%s details=%s rows_sampled=%d",
        schema_fingerprint[:12],
        "; ".join(details) if details else "unknown",
        len(sample),
    )
    logger.info("mapping_cache_recompute reason=verification_failed")
    return (
        mapping,
        mapping_hash,
        {
            "cache_hit": False,
            "cache_source": "verification_failed",
            "schema_fingerprint": schema_fingerprint,
            "selection_trace": selection_trace,
        },
    )


def invalidate() -> None:
    """Clear in-memory cache and all per-fingerprint disk cache files."""
    global _cached_fingerprint, _cached_columns, _cached_mapping, _cached_mapping_hash
    global _cached_selection_trace
    with _lock:
        _cached_fingerprint = None
        _cached_columns = None
        _cached_mapping = None
        _cached_mapping_hash = None
        _cached_selection_trace = None

    try:
        for file_path in _cache_dir().glob("*.json"):
            file_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.info("mapping_cache_invalidate dir_error=%s", exc)
    logger.info("mapping_cache_invalidate")


def should_invalidate(new_fingerprint: str | None) -> bool:
    """Return True when the cache should be invalidated for a new import.

    Returns False only when ``new_fingerprint`` is non-empty and matches
    the currently cached fingerprint exactly.

    Callers that cannot supply a fingerprint (e.g. disconnect) should call
    ``invalidate()`` unconditionally rather than using this function.
    """
    if not new_fingerprint:
        return True
    with _lock:
        return _cached_fingerprint != new_fingerprint
