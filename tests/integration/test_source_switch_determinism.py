"""Integration coverage for source-switch determinism (A -> B -> A)."""

from __future__ import annotations

import hashlib
import json

from src.orchestrator.binding_hash import build_binding_fingerprint
from src.orchestrator.filter_compiler import COMPILER_VERSION
from src.services.column_mapping import NORMALIZER_VERSION
from src.services.mapping_cache import MAPPING_VERSION


def _binding(source_type: str, source_ref: str, schema_fingerprint: str) -> str:
    return build_binding_fingerprint(
        source_signature={
            "source_type": source_type,
            "source_ref": source_ref,
            "schema_fingerprint": schema_fingerprint,
        },
        compiler_version=COMPILER_VERSION,
        mapping_version=MAPPING_VERSION,
        normalizer_version=NORMALIZER_VERSION,
    )


def _compute_compiled_hash(
    where_sql: str,
    params: list[object],
    binding_fingerprint: str,
) -> str:
    canonical = json.dumps(
        {
            "where_sql": where_sql,
            "params": params,
            "binding_fingerprint": binding_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def test_source_switch_compiled_hash_isolation_a_b_a() -> None:
    """Same query only reuses hash when source binding fingerprint matches."""
    where_sql = "state IN ($1,$2)"
    params = ["CA", "NY"]

    binding_a = _binding("csv", "/tmp/a.csv", "sig-a")
    binding_b = _binding("csv", "/tmp/b.csv", "sig-b")

    hash_a1 = _compute_compiled_hash(where_sql, params, binding_fingerprint=binding_a)
    hash_b = _compute_compiled_hash(where_sql, params, binding_fingerprint=binding_b)
    hash_a2 = _compute_compiled_hash(where_sql, params, binding_fingerprint=binding_a)

    assert hash_a1 == hash_a2
    assert hash_a1 != hash_b
