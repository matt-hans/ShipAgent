"""Tests for filter canonical constants."""

import pytest


class TestRegions:
    """Tests for US region maps."""

    def test_all_us_has_52_entries(self):
        """50 states + DC + PR."""
        from src.services.filter_constants import REGIONS

        assert len(REGIONS["ALL_US"]) == 52

    def test_northeast_states(self):
        from src.services.filter_constants import REGIONS

        assert set(REGIONS["NORTHEAST"]) == {
            "NY", "MA", "CT", "PA", "NJ", "ME", "NH", "RI", "VT",
        }

    def test_dc_in_mid_atlantic_only(self):
        """DC is in MID_ATLANTIC and ALL_US but no other region."""
        from src.services.filter_constants import REGIONS

        for name, states in REGIONS.items():
            if name in ("MID_ATLANTIC", "ALL_US"):
                assert "DC" in states, f"DC missing from {name}"
            else:
                assert "DC" not in states, f"DC should not be in {name}"

    def test_pr_in_all_us_only(self):
        from src.services.filter_constants import REGIONS

        for name, states in REGIONS.items():
            if name == "ALL_US":
                assert "PR" in states
            else:
                assert "PR" not in states, f"PR should not be in {name}"

    def test_no_duplicate_states_within_region(self):
        from src.services.filter_constants import REGIONS

        for name, states in REGIONS.items():
            assert len(states) == len(set(states)), f"Duplicates in {name}"

    def test_all_region_states_are_in_all_us(self):
        from src.services.filter_constants import REGIONS

        all_us = set(REGIONS["ALL_US"])
        for name, states in REGIONS.items():
            for state in states:
                assert state in all_us, f"{state} in {name} but not ALL_US"


class TestRegionAliases:
    """Tests for NL → canonical key aliases."""

    def test_northeast_aliases(self):
        from src.services.filter_constants import REGION_ALIASES

        assert REGION_ALIASES["northeast"] == "NORTHEAST"
        assert REGION_ALIASES["the northeast"] == "NORTHEAST"

    def test_the_south_not_in_aliases(self):
        """'the south' is Tier C — deliberately excluded."""
        from src.services.filter_constants import REGION_ALIASES

        assert "the south" not in REGION_ALIASES


class TestBusinessPredicates:
    """Tests for business predicate definitions."""

    def test_business_recipient_exists(self):
        from src.services.filter_constants import BUSINESS_PREDICATES

        pred = BUSINESS_PREDICATES["BUSINESS_RECIPIENT"]
        assert "company" in pred["target_column_patterns"]
        assert pred["expansion"] == "is_not_blank"

    def test_personal_recipient_exists(self):
        from src.services.filter_constants import BUSINESS_PREDICATES

        pred = BUSINESS_PREDICATES["PERSONAL_RECIPIENT"]
        assert pred["expansion"] == "is_blank"


class TestAmbiguityTiers:
    """Tests for tier classification."""

    def test_state_abbreviations_are_tier_a(self):
        from src.services.filter_constants import get_tier

        assert get_tier("california") == "A"

    def test_regions_are_tier_b(self):
        from src.services.filter_constants import get_tier

        assert get_tier("northeast") == "B"

    def test_business_predicates_are_tier_b(self):
        from src.services.filter_constants import get_tier

        assert get_tier("BUSINESS_RECIPIENT") == "B"

    def test_unknown_term_is_tier_c(self):
        from src.services.filter_constants import get_tier

        assert get_tier("the south") == "C"
        assert get_tier("random_garbage") == "C"


class TestNormalization:
    """Tests for the normalize_term function."""

    def test_casefold(self):
        from src.services.filter_constants import normalize_term

        assert normalize_term("NORTHEAST") == "northeast"

    def test_strip_hyphens(self):
        from src.services.filter_constants import normalize_term

        assert normalize_term("Mid-Atlantic") == "mid atlantic"

    def test_strip_extra_spaces(self):
        from src.services.filter_constants import normalize_term

        assert normalize_term("  the   northeast  ") == "the northeast"


class TestColumnPatternMatching:
    """Tests for match_column_pattern."""

    def test_exact_match(self):
        from src.services.filter_constants import match_column_pattern

        result = match_column_pattern(
            patterns=["company", "company_name"],
            schema_columns={"company", "state", "city"},
        )
        assert result == ["company"]

    def test_no_match_returns_empty(self):
        from src.services.filter_constants import match_column_pattern

        result = match_column_pattern(
            patterns=["company", "company_name"],
            schema_columns={"state", "city"},
        )
        assert result == []

    def test_multiple_matches(self):
        from src.services.filter_constants import match_column_pattern

        result = match_column_pattern(
            patterns=["company", "company_name"],
            schema_columns={"company", "company_name", "state"},
        )
        assert set(result) == {"company", "company_name"}


class TestDictVersion:
    """Tests for the canonical dict version."""

    def test_version_format(self):
        from src.services.filter_constants import CANONICAL_DICT_VERSION

        assert CANONICAL_DICT_VERSION.startswith("filter_constants_v")


class TestStateAbbreviations:
    """Tests for state abbreviation lookup."""

    def test_california_resolves(self):
        from src.services.filter_constants import STATE_ABBREVIATIONS

        assert STATE_ABBREVIATIONS["california"] == "CA"

    def test_new_york_resolves(self):
        from src.services.filter_constants import STATE_ABBREVIATIONS

        assert STATE_ABBREVIATIONS["new york"] == "NY"
