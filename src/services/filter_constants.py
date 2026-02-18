"""Canonical constants for deterministic filter resolution.

This module is the single source of truth for all filter-related canonical data:
US region maps, natural-language aliases, business predicates, state abbreviations,
tier classification, and normalization utilities.

See docs/plans/2026-02-16-filter-determinism-design.md for full architecture.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CANONICAL_DICT_VERSION = "filter_constants_v1"

# ---------------------------------------------------------------------------
# US State Abbreviations (casefolded full name → 2-letter code)
# ---------------------------------------------------------------------------

STATE_ABBREVIATIONS: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

# ---------------------------------------------------------------------------
# US Region Maps
# ---------------------------------------------------------------------------

REGIONS: dict[str, list[str]] = {
    "NORTHEAST": ["NY", "MA", "CT", "PA", "NJ", "ME", "NH", "RI", "VT"],
    "NEW_ENGLAND": ["ME", "NH", "VT", "MA", "RI", "CT"],
    "MID_ATLANTIC": ["NY", "NJ", "PA", "DE", "MD", "DC"],
    "SOUTHEAST": [
        "VA", "WV", "NC", "SC", "GA", "FL", "KY", "TN", "AL", "MS", "AR", "LA",
    ],
    "MIDWEST": [
        "OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS",
    ],
    "SOUTHWEST": ["TX", "OK", "NM", "AZ"],
    "WEST": ["MT", "WY", "CO", "ID", "UT", "NV"],
    "WEST_COAST": ["WA", "OR", "CA"],
    "PACIFIC": ["HI", "AK"],
    "ALL_US": [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "PR",
    ],
}

# ---------------------------------------------------------------------------
# NL → Canonical Region Aliases
# All keys are casefolded. Tier B terms — require confirmation before execution.
# ---------------------------------------------------------------------------

REGION_ALIASES: dict[str, str] = {
    "northeast": "NORTHEAST",
    "the northeast": "NORTHEAST",
    "northeastern": "NORTHEAST",
    "new england": "NEW_ENGLAND",
    "mid atlantic": "MID_ATLANTIC",
    "mid-atlantic": "MID_ATLANTIC",
    "midatlantic": "MID_ATLANTIC",
    "southeast": "SOUTHEAST",
    "the southeast": "SOUTHEAST",
    "southeastern": "SOUTHEAST",
    "midwest": "MIDWEST",
    "the midwest": "MIDWEST",
    "midwestern": "MIDWEST",
    "southwest": "SOUTHWEST",
    "the southwest": "SOUTHWEST",
    "southwestern": "SOUTHWEST",
    "west": "WEST",
    "the west": "WEST",
    "western": "WEST",
    "west coast": "WEST_COAST",
    "the west coast": "WEST_COAST",
    "pacific": "PACIFIC",
    "the pacific": "PACIFIC",
    "all us": "ALL_US",
    "all states": "ALL_US",
    "nationwide": "ALL_US",
}

# ---------------------------------------------------------------------------
# Business Predicates
# Tier B — require confirmation before execution.
# ---------------------------------------------------------------------------

# Shared company-like column patterns across source types.
# Includes Shopify's ``ship_to_company`` so "companies" intent resolves
# deterministically for imported Shopify orders.
_COMPANY_COLUMN_PATTERNS = [
    "company",
    "company_name",
    "business_name",
    "ship_to_company",
]

BUSINESS_PREDICATES: dict[str, dict] = {
    "BUSINESS_RECIPIENT": {
        "target_column_patterns": _COMPANY_COLUMN_PATTERNS,
        "expansion": "is_not_blank",
        "description": "Rows where company/business name is populated",
    },
    "PERSONAL_RECIPIENT": {
        "target_column_patterns": _COMPANY_COLUMN_PATTERNS,
        "expansion": "is_blank",
        "description": "Rows where company/business name is empty (personal recipients)",
    },
}

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_MULTI_SPACE = re.compile(r"\s+")


def normalize_term(term: str) -> str:
    """Normalize a natural-language term for canonical lookup.

    Applies casefold, strips hyphens, collapses whitespace.

    Args:
        term: Raw user or LLM term.

    Returns:
        Normalized string suitable for dictionary lookup.
    """
    result = term.casefold()
    result = result.replace("-", " ")
    result = _MULTI_SPACE.sub(" ", result).strip()
    return result


def _normalize_business_key(term: str) -> str:
    """Normalize business semantic keys to underscore form."""
    return normalize_term(term).replace(" ", "_")


_BUSINESS_PREDICATE_BY_NORMALIZED_KEY: dict[str, tuple[str, dict]] = {
    _normalize_business_key(key): (key, value)
    for key, value in BUSINESS_PREDICATES.items()
}


# ---------------------------------------------------------------------------
# Tier Classification
# ---------------------------------------------------------------------------

def get_tier(term: str) -> str:
    """Classify a term into ambiguity tier A, B, or C.

    Tier A: Auto-expand silently (state abbreviations, service codes).
    Tier B: Expand + mandatory confirmation (regions, business predicates).
    Tier C: Unresolved — clarification required with 2-3 options.

    Args:
        term: Raw term to classify.

    Returns:
        \"A\", \"B\", or \"C\".
    """
    normalized = normalize_term(term)

    # Tier A: state full names
    if normalized in STATE_ABBREVIATIONS:
        return "A"

    # Tier B: region aliases
    if normalized in REGION_ALIASES:
        return "B"

    # Tier B: business predicates (case-insensitive)
    if _normalize_business_key(term) in _BUSINESS_PREDICATE_BY_NORMALIZED_KEY:
        return "B"

    # Tier C: unknown
    return "C"


# ---------------------------------------------------------------------------
# Column Pattern Matching
# ---------------------------------------------------------------------------

def match_column_pattern(
    patterns: list[str],
    schema_columns: set[str],
) -> list[str]:
    """Match column patterns against a schema's column set.

    Args:
        patterns: List of column name patterns to look for.
        schema_columns: Set of actual column names in the data source.

    Returns:
        List of matched column names (may be empty).
    """
    matched: list[str] = []
    # Build deterministic case-insensitive lookup preserving source column names.
    normalized_index: dict[str, list[str]] = {}
    for column in sorted(schema_columns):
        normalized_index.setdefault(column.casefold(), []).append(column)

    for pattern in patterns:
        candidates = normalized_index.get(pattern.casefold(), [])
        matched.extend(candidates)
    return matched


def resolve_business_predicate(term: str) -> tuple[str, dict] | None:
    """Resolve business predicate key case-insensitively.

    Returns the canonical key and predicate definition when matched.
    """
    return _BUSINESS_PREDICATE_BY_NORMALIZED_KEY.get(_normalize_business_key(term))
