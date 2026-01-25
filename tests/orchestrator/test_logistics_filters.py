"""Tests for Jinja2 logistics filter library.

This module tests all 9 logistics filters for shipping data transformations.
"""

import math
from datetime import date, datetime

import pytest

from src.orchestrator.filters.logistics import (
    LOGISTICS_FILTERS,
    convert_weight,
    default_value,
    format_us_zip,
    get_logistics_environment,
    lookup_service_code,
    round_weight,
    split_name,
    to_ups_date,
    to_ups_phone,
    truncate_address,
)


class TestTruncateAddress:
    """Tests for truncate_address filter."""

    def test_short_string_unchanged(self):
        """Short strings under max_length return as-is."""
        result = truncate_address("Short", 35)
        assert result == "Short"

    def test_truncate_at_word_boundary(self):
        """Long strings truncate at word boundary."""
        result = truncate_address("123 Main Street Suite 400", 20)
        assert result == "123 Main Street"
        assert len(result) <= 20

    def test_single_long_word(self):
        """Single word longer than max truncates at exact length."""
        result = truncate_address("Supercalifragilisticexpialidocious", 10)
        assert result == "Supercalif"
        assert len(result) == 10

    def test_trailing_space_stripped(self):
        """Trailing spaces are stripped after truncation."""
        result = truncate_address("Hello World Test", 12)
        assert result == "Hello World"
        assert not result.endswith(" ")

    def test_exact_length_unchanged(self):
        """String exactly at max_length returns as-is."""
        result = truncate_address("12345678901234567890", 20)
        assert result == "12345678901234567890"

    def test_default_max_length_35(self):
        """Default max_length is 35 (UPS standard)."""
        result = truncate_address("A" * 40)
        assert len(result) == 35

    def test_empty_string(self):
        """Empty string returns empty."""
        result = truncate_address("", 35)
        assert result == ""

    def test_whitespace_stripped(self):
        """Leading and trailing whitespace is stripped."""
        result = truncate_address("  Hello World  ", 35)
        assert result == "Hello World"


class TestFormatUsZip:
    """Tests for format_us_zip filter."""

    def test_five_digit_unchanged(self):
        """5-digit ZIP codes return as-is."""
        result = format_us_zip("90001")
        assert result == "90001"

    def test_nine_digit_formatted(self):
        """9-digit ZIP codes format as ZIP+4."""
        result = format_us_zip("900011234")
        assert result == "90001-1234"

    def test_strips_non_digits(self):
        """Non-digit characters are stripped."""
        result = format_us_zip("90001-1234")
        assert result == "90001-1234"

    def test_short_zip_padded(self):
        """Short ZIPs are padded with zeros."""
        result = format_us_zip("123")
        assert result == "12300"

    def test_more_than_nine_digits(self):
        """ZIP with 10+ digits uses first 9."""
        result = format_us_zip("900011234567")
        assert result == "90001-1234"

    def test_with_spaces(self):
        """Spaces are stripped."""
        result = format_us_zip("90001 1234")
        assert result == "90001-1234"

    def test_six_to_eight_digits(self):
        """6-8 digit ZIPs return just first 5."""
        result = format_us_zip("9000123")
        assert result == "90001"


class TestRoundWeight:
    """Tests for round_weight filter."""

    def test_rounds_to_one_decimal(self):
        """Default rounds to 1 decimal place."""
        result = round_weight(5.678)
        assert result == 5.7

    def test_minimum_weight_enforced(self):
        """Weights under 0.1 are raised to 0.1."""
        result = round_weight(0.02)
        assert result == 0.1

    def test_custom_decimal_places(self):
        """Custom decimal places work correctly."""
        result = round_weight(5.6789, 2)
        assert result == 5.68

    def test_integer_input(self):
        """Integer inputs work correctly."""
        result = round_weight(5)
        assert result == 5.0

    def test_zero_weight(self):
        """Zero weight returns minimum 0.1."""
        result = round_weight(0)
        assert result == 0.1


class TestConvertWeight:
    """Tests for convert_weight filter."""

    def test_kg_to_lbs(self):
        """Kilograms to pounds conversion."""
        result = convert_weight(1.0, "kg", "lbs")
        assert abs(result - 2.20462) < 0.001

    def test_oz_to_lbs(self):
        """Ounces to pounds conversion."""
        result = convert_weight(16, "oz", "lbs")
        assert abs(result - 1.0) < 0.001

    def test_g_to_lbs(self):
        """Grams to pounds conversion."""
        result = convert_weight(1000, "g", "lbs")
        assert abs(result - 2.20462) < 0.001

    def test_lbs_to_kg(self):
        """Pounds to kilograms conversion."""
        result = convert_weight(2.20462, "lbs", "kg")
        assert abs(result - 1.0) < 0.001

    def test_unsupported_source_unit_raises(self):
        """Unsupported source unit raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            convert_weight(1.0, "stone", "lbs")
        assert "Unsupported source unit" in str(exc_info.value)

    def test_unsupported_target_unit_raises(self):
        """Unsupported target unit raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            convert_weight(1.0, "kg", "stone")
        assert "Unsupported target unit" in str(exc_info.value)

    def test_lb_alias(self):
        """'lb' works as alias for 'lbs'."""
        result = convert_weight(1.0, "lb", "kg")
        assert abs(result - 0.453592) < 0.001

    def test_case_insensitive(self):
        """Unit comparison is case-insensitive."""
        result = convert_weight(1.0, "KG", "LBS")
        assert abs(result - 2.20462) < 0.001


class TestToUpsPhone:
    """Tests for to_ups_phone filter."""

    def test_ten_digit_unchanged(self):
        """10-digit phone numbers return as-is."""
        result = to_ups_phone("5551234567")
        assert result == "5551234567"

    def test_strips_formatting(self):
        """Formatting characters are stripped."""
        result = to_ups_phone("(555) 123-4567")
        assert result == "5551234567"

    def test_removes_leading_one(self):
        """Leading country code '1' is removed."""
        result = to_ups_phone("1-555-123-4567")
        assert result == "5551234567"

    def test_invalid_length_raises(self):
        """Phone with wrong digit count raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            to_ups_phone("555-1234")
        assert "Invalid phone number" in str(exc_info.value)
        assert "got 7 digits" in str(exc_info.value)

    def test_with_dots(self):
        """Dots are stripped."""
        result = to_ups_phone("555.123.4567")
        assert result == "5551234567"

    def test_with_spaces(self):
        """Spaces are stripped."""
        result = to_ups_phone("555 123 4567")
        assert result == "5551234567"


class TestToUpsDate:
    """Tests for to_ups_date filter."""

    def test_iso_date_string(self):
        """ISO date strings are parsed correctly."""
        result = to_ups_date("2024-01-15")
        assert result == "20240115"

    def test_datetime_object(self):
        """datetime objects are formatted correctly."""
        result = to_ups_date(datetime(2024, 1, 15, 10, 30))
        assert result == "20240115"

    def test_date_object(self):
        """date objects are formatted correctly."""
        result = to_ups_date(date(2024, 1, 15))
        assert result == "20240115"

    def test_human_readable_date(self):
        """Human-readable dates are parsed correctly."""
        result = to_ups_date("January 15, 2024")
        assert result == "20240115"

    def test_slash_format(self):
        """Slash-formatted dates are parsed correctly."""
        result = to_ups_date("01/15/2024")
        assert result == "20240115"

    def test_invalid_date_raises(self):
        """Invalid date strings raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            to_ups_date("not a date")
        assert "Cannot parse date" in str(exc_info.value)


class TestDefaultValue:
    """Tests for default_value filter."""

    def test_none_returns_default(self):
        """None values return the default."""
        result = default_value(None, "N/A")
        assert result == "N/A"

    def test_empty_string_returns_default(self):
        """Empty strings return the default."""
        result = default_value("", "Unknown")
        assert result == "Unknown"

    def test_whitespace_only_returns_default(self):
        """Whitespace-only strings return the default."""
        result = default_value("   ", "Unknown")
        assert result == "Unknown"

    def test_nan_returns_default(self):
        """NaN values return the default."""
        result = default_value(float("nan"), 0.0)
        assert result == 0.0

    def test_valid_value_unchanged(self):
        """Valid values are returned unchanged."""
        result = default_value("Alice", "Unknown")
        assert result == "Alice"

    def test_zero_not_replaced(self):
        """Zero is not considered empty."""
        result = default_value(0, 999)
        assert result == 0

    def test_false_not_replaced(self):
        """False is not considered empty."""
        result = default_value(False, True)
        assert result is False


class TestSplitName:
    """Tests for split_name filter."""

    def test_first_name(self):
        """First name extraction works."""
        result = split_name("John Doe", "first")
        assert result == "John"

    def test_last_name(self):
        """Last name extraction works."""
        result = split_name("John Doe", "last")
        assert result == "Doe"

    def test_single_name_first(self):
        """Single name returns same for 'first'."""
        result = split_name("Madonna", "first")
        assert result == "Madonna"

    def test_single_name_last(self):
        """Single name returns same for 'last'."""
        result = split_name("Madonna", "last")
        assert result == "Madonna"

    def test_three_names_last(self):
        """Last name with three names returns final name."""
        result = split_name("Mary Jane Watson", "last")
        assert result == "Watson"

    def test_all_part(self):
        """'all' returns the full name."""
        result = split_name("John Doe", "all")
        assert result == "John Doe"

    def test_invalid_part_raises(self):
        """Invalid part raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            split_name("John Doe", "middle")
        assert "Invalid name part" in str(exc_info.value)


class TestLookupServiceCode:
    """Tests for lookup_service_code filter."""

    def test_ground_alias(self):
        """'ground' maps to '03'."""
        result = lookup_service_code("ground")
        assert result == "03"

    def test_overnight_alias(self):
        """'overnight' maps to '01'."""
        result = lookup_service_code("overnight")
        assert result == "01"

    def test_two_day_alias(self):
        """'2-day' maps to '02'."""
        result = lookup_service_code("2-day")
        assert result == "02"

    def test_three_day_alias(self):
        """'3-day' maps to '12'."""
        result = lookup_service_code("3-day")
        assert result == "12"

    def test_saver_alias(self):
        """'saver' maps to '13'."""
        result = lookup_service_code("saver")
        assert result == "13"

    def test_direct_code_passthrough(self):
        """Direct codes pass through."""
        result = lookup_service_code("03")
        assert result == "03"

    def test_case_insensitive(self):
        """Lookup is case-insensitive."""
        result = lookup_service_code("GROUND")
        assert result == "03"

    def test_unknown_passthrough(self):
        """Unknown values pass through unchanged."""
        result = lookup_service_code("express")
        assert result == "express"


class TestLogisticsFiltersRegistry:
    """Tests for LOGISTICS_FILTERS registry."""

    def test_all_filters_registered(self):
        """All 9 filters are registered."""
        expected_filters = [
            "truncate_address",
            "format_us_zip",
            "round_weight",
            "convert_weight",
            "lookup_service_code",
            "to_ups_date",
            "to_ups_phone",
            "default_value",
            "split_name",
        ]
        for name in expected_filters:
            assert name in LOGISTICS_FILTERS, f"Missing filter: {name}"

    def test_filter_functions_callable(self):
        """All registered filters are callable."""
        for name, func in LOGISTICS_FILTERS.items():
            assert callable(func), f"Filter {name} is not callable"


class TestGetLogisticsEnvironment:
    """Tests for get_logistics_environment factory."""

    def test_returns_sandboxed_environment(self):
        """Returns a SandboxedEnvironment instance."""
        from jinja2.sandbox import SandboxedEnvironment

        env = get_logistics_environment()
        assert isinstance(env, SandboxedEnvironment)

    def test_filters_registered_in_environment(self):
        """All logistics filters are registered in the environment."""
        env = get_logistics_environment()
        for name in LOGISTICS_FILTERS:
            assert name in env.filters, f"Filter {name} not in environment"

    def test_template_rendering_with_filter(self):
        """Templates can use registered filters."""
        env = get_logistics_environment()
        template = env.from_string("{{ name | truncate_address(10) }}")
        result = template.render(name="123 Main Street Suite 400")
        assert result == "123 Main"

    def test_autoescape_disabled(self):
        """Autoescape is disabled for JSON output."""
        env = get_logistics_environment()
        assert env.autoescape is False

    def test_multiple_filters_in_template(self):
        """Multiple filters can be chained."""
        env = get_logistics_environment()
        template = env.from_string("{{ phone | to_ups_phone }}")
        result = template.render(phone="(555) 123-4567")
        assert result == "5551234567"
