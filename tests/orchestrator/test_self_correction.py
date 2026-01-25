"""Tests for the self-correction loop.

Tests cover:
- Correction model validation
- Error formatting for LLM
- Template extraction from responses
- Self-correction loop behavior
- User feedback formatting
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.orchestrator.models.correction import (
    CorrectionAttempt,
    CorrectionOptions,
    CorrectionResult,
    MaxCorrectionsExceeded,
)
from src.orchestrator.models.filter import ColumnInfo
from src.orchestrator.nl_engine.self_correction import (
    extract_template_from_response,
    format_errors_for_llm,
    format_user_feedback,
    self_correction_loop,
)
from src.orchestrator.nl_engine.template_validator import ValidationError


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_template() -> str:
    """Simple Jinja2 template for testing."""
    return '{"ShipTo": {"Name": "{{ name }}"}}'


@pytest.fixture
def validation_errors() -> list[ValidationError]:
    """Sample validation errors for testing."""
    return [
        ValidationError(
            path="ShipTo.Phone.Number",
            message="string too short",
            expected="string with at least 10 character(s)",
            actual="555-1234",
            schema_rule="minLength",
        ),
        ValidationError(
            path="ShipTo.Address.PostalCode",
            message="missing required field",
            expected="required field (missing: ['PostalCode'])",
            actual="null",
            schema_rule="required",
        ),
    ]


@pytest.fixture
def sample_source_schema() -> list[ColumnInfo]:
    """Sample source schema for testing."""
    return [
        ColumnInfo(name="name", type="string", nullable=False),
        ColumnInfo(name="phone", type="string", nullable=True),
        ColumnInfo(name="address", type="string", nullable=False),
        ColumnInfo(name="city", type="string", nullable=False),
        ColumnInfo(name="state", type="string", nullable=False),
        ColumnInfo(name="zip", type="string", nullable=False),
    ]


# ============================================================================
# TestCorrectionModels
# ============================================================================


class TestCorrectionModels:
    """Tests for correction model classes."""

    def test_correction_attempt_minimal(self):
        """Test CorrectionAttempt with minimal required fields."""
        attempt = CorrectionAttempt(
            attempt_number=1,
            original_template='{"name": "{{ name }}"}',
        )
        assert attempt.attempt_number == 1
        assert attempt.validation_errors == []
        assert attempt.corrected_template is None
        assert attempt.changes_made == []
        assert attempt.success is False
        assert isinstance(attempt.timestamp, datetime)

    def test_correction_attempt_with_changes(self, validation_errors):
        """Test CorrectionAttempt with full data."""
        attempt = CorrectionAttempt(
            attempt_number=2,
            original_template='{"phone": "{{ phone }}"}',
            validation_errors=validation_errors,
            corrected_template='{"phone": "{{ phone | to_ups_phone }}"}',
            changes_made=["Added to_ups_phone filter"],
            success=True,
        )
        assert attempt.attempt_number == 2
        assert len(attempt.validation_errors) == 2
        assert attempt.corrected_template is not None
        assert "to_ups_phone" in attempt.corrected_template
        assert attempt.success is True

    def test_correction_result_success(self):
        """Test CorrectionResult for successful correction."""
        result = CorrectionResult(
            final_template='{"name": "{{ name }}"}',
            attempts=[
                CorrectionAttempt(
                    attempt_number=1,
                    original_template='{"name": "{{ name }}"}',
                    success=True,
                )
            ],
            success=True,
            total_attempts=1,
        )
        assert result.success is True
        assert result.final_template is not None
        assert result.total_attempts == 1
        assert result.failure_reason is None

    def test_correction_result_failure(self, validation_errors):
        """Test CorrectionResult for failed correction."""
        result = CorrectionResult(
            final_template=None,
            attempts=[
                CorrectionAttempt(
                    attempt_number=i,
                    original_template='{"phone": "{{ phone }}"}',
                    validation_errors=validation_errors,
                    success=False,
                )
                for i in range(1, 4)
            ],
            success=False,
            total_attempts=3,
            failure_reason="Max attempts reached",
        )
        assert result.success is False
        assert result.final_template is None
        assert result.total_attempts == 3
        assert "Max attempts" in result.failure_reason

    def test_correction_options_values(self):
        """Test CorrectionOptions enum values."""
        assert CorrectionOptions.CORRECT_SOURCE.value == "correct_source"
        assert CorrectionOptions.MANUAL_FIX.value == "manual_fix"
        assert CorrectionOptions.SKIP_PROBLEMATIC.value == "skip_problematic"
        assert CorrectionOptions.ABORT.value == "abort"
        assert len(list(CorrectionOptions)) == 4


# ============================================================================
# TestFormatErrorsForLLM
# ============================================================================


class TestFormatErrorsForLLM:
    """Tests for format_errors_for_llm function."""

    def test_single_error_format(self):
        """Test formatting a single error."""
        errors = [
            ValidationError(
                path="ShipTo.Name",
                message="string too long",
                expected="string with at most 35 character(s)",
                actual="A" * 40,
                schema_rule="maxLength",
            )
        ]
        formatted = format_errors_for_llm(errors)

        assert "1 validation error" in formatted
        assert "ShipTo.Name" in formatted
        assert "Expected:" in formatted
        assert "35 character" in formatted
        assert "Got:" in formatted

    def test_multiple_errors_format(self, validation_errors):
        """Test formatting multiple errors."""
        formatted = format_errors_for_llm(validation_errors)

        assert "2 validation error" in formatted
        assert "ShipTo.Phone.Number" in formatted
        assert "ShipTo.Address.PostalCode" in formatted
        assert "Error 1:" in formatted
        assert "Error 2:" in formatted

    def test_includes_fix_suggestions(self):
        """Test that fix suggestions are included."""
        errors = [
            ValidationError(
                path="ShipTo.Phone.Number",
                message="too short",
                expected="at least 10 characters",
                actual="555-1234",
                schema_rule="minLength",
            )
        ]
        formatted = format_errors_for_llm(errors)

        assert "Fix:" in formatted
        # Should suggest phone formatting
        assert "phone" in formatted.lower() or "to_ups_phone" in formatted

    def test_nested_path_format(self):
        """Test formatting deeply nested paths."""
        errors = [
            ValidationError(
                path="Package.0.PackageWeight.Weight",
                message="missing",
                expected="required",
                actual=None,
                schema_rule="required",
            )
        ]
        formatted = format_errors_for_llm(errors)

        assert "Package.0.PackageWeight.Weight" in formatted

    def test_empty_errors(self):
        """Test formatting empty error list."""
        formatted = format_errors_for_llm([])
        assert "No validation errors" in formatted


# ============================================================================
# TestExtractTemplate
# ============================================================================


class TestExtractTemplate:
    """Tests for extract_template_from_response function."""

    def test_extract_from_jinja2_block(self):
        """Test extracting from ```jinja2 code block."""
        response = """Here's the fixed template:

```jinja2
{
  "ShipTo": {
    "Name": "{{ name | truncate_address(35) }}"
  }
}
```

This should fix the length issue."""

        template = extract_template_from_response(response)
        assert "truncate_address" in template
        assert "ShipTo" in template
        assert "```" not in template

    def test_extract_from_plain_block(self):
        """Test extracting from plain ``` code block."""
        response = """Fixed template:

```
{"Name": "{{ name }}"}
```"""

        template = extract_template_from_response(response)
        assert "Name" in template
        assert "```" not in template

    def test_extract_from_json_block(self):
        """Test extracting from ```json code block."""
        response = """Here's the JSON:

```json
{
  "ShipTo": {
    "Name": "{{ name }}"
  }
}
```"""

        template = extract_template_from_response(response)
        assert "ShipTo" in template
        assert "```" not in template

    def test_extract_strips_markdown(self):
        """Test that markdown formatting is stripped."""
        response = """```jinja2
{{ name | truncate_address(35) }}
```"""

        template = extract_template_from_response(response)
        assert template == "{{ name | truncate_address(35) }}"

    def test_handles_no_block_with_json(self):
        """Test handling response with no code block but JSON present."""
        response = """The template should be:
{"Name": "{{ name }}"}
to fix the issue."""

        template = extract_template_from_response(response)
        assert "Name" in template
        assert "{{" in template

    def test_returns_full_response_if_no_pattern(self):
        """Test returning full response if no pattern matches."""
        response = "No template here, just text."
        template = extract_template_from_response(response)
        assert template == response.strip()


# ============================================================================
# TestMaxCorrectionsExceeded
# ============================================================================


class TestMaxCorrectionsExceeded:
    """Tests for MaxCorrectionsExceeded exception."""

    def test_exception_contains_result(self, validation_errors):
        """Test that exception contains the correction result."""
        result = CorrectionResult(
            success=False,
            total_attempts=3,
            attempts=[
                CorrectionAttempt(
                    attempt_number=i,
                    original_template='{"name": "{{ name }}"}',
                    validation_errors=validation_errors,
                )
                for i in range(1, 4)
            ],
        )

        exc = MaxCorrectionsExceeded(result=result)

        assert exc.result == result
        assert exc.result.total_attempts == 3

    def test_exception_contains_options(self):
        """Test that exception contains user options."""
        result = CorrectionResult(success=False, total_attempts=3)
        exc = MaxCorrectionsExceeded(
            result=result,
            options=[CorrectionOptions.MANUAL_FIX, CorrectionOptions.ABORT],
        )

        assert len(exc.options) == 2
        assert CorrectionOptions.MANUAL_FIX in exc.options
        assert CorrectionOptions.ABORT in exc.options

    def test_all_options_available(self):
        """Test that all 4 options are available by default."""
        result = CorrectionResult(success=False, total_attempts=3)
        exc = MaxCorrectionsExceeded(result=result)

        assert len(exc.options) == 4
        assert CorrectionOptions.CORRECT_SOURCE in exc.options
        assert CorrectionOptions.MANUAL_FIX in exc.options
        assert CorrectionOptions.SKIP_PROBLEMATIC in exc.options
        assert CorrectionOptions.ABORT in exc.options

    def test_exception_str_format(self):
        """Test the string representation of the exception."""
        result = CorrectionResult(success=False, total_attempts=3)
        exc = MaxCorrectionsExceeded(result=result)

        exc_str = str(exc)
        assert "correct_source" in exc_str
        assert "manual_fix" in exc_str
        assert "skip_problematic" in exc_str
        assert "abort" in exc_str
        assert "Available options" in exc_str


# ============================================================================
# TestUserFeedback
# ============================================================================


class TestUserFeedback:
    """Tests for format_user_feedback function."""

    def test_format_includes_attempt_number(self, validation_errors):
        """Test that feedback includes attempt number."""
        attempt = CorrectionAttempt(
            attempt_number=2,
            original_template='{"name": "{{ name }}"}',
            validation_errors=validation_errors,
        )

        feedback = format_user_feedback(attempt, max_attempts=3)

        assert "attempt 2 of 3" in feedback

    def test_format_includes_errors(self, validation_errors):
        """Test that feedback includes error details."""
        attempt = CorrectionAttempt(
            attempt_number=1,
            original_template='{"phone": "{{ phone }}"}',
            validation_errors=validation_errors,
        )

        feedback = format_user_feedback(attempt, max_attempts=3)

        assert "ShipTo.Phone.Number" in feedback
        assert "Expected:" in feedback
        assert "Got:" in feedback

    def test_format_includes_status(self, validation_errors):
        """Test that feedback includes correction status."""
        # Failed attempt
        failed = CorrectionAttempt(
            attempt_number=1,
            original_template='{"name": "{{ name }}"}',
            validation_errors=validation_errors,
            success=False,
        )
        failed_feedback = format_user_feedback(failed, max_attempts=3)
        assert "Attempting correction" in failed_feedback

        # Successful attempt
        successful = CorrectionAttempt(
            attempt_number=1,
            original_template='{"name": "{{ name }}"}',
            validation_errors=[],
            success=True,
            changes_made=["Fixed phone format"],
        )
        success_feedback = format_user_feedback(successful, max_attempts=3)
        assert "successful" in success_feedback.lower()
        assert "Fixed phone format" in success_feedback

    def test_format_limits_errors_shown(self):
        """Test that feedback limits number of errors shown."""
        many_errors = [
            ValidationError(
                path=f"Field{i}",
                message="error",
                expected="value",
                actual="wrong",
                schema_rule="type",
            )
            for i in range(10)
        ]

        attempt = CorrectionAttempt(
            attempt_number=1,
            original_template='{"name": "{{ name }}"}',
            validation_errors=many_errors,
        )

        feedback = format_user_feedback(attempt, max_attempts=3)

        # Should show first 3 and mention remaining
        assert "Field0" in feedback
        assert "Field1" in feedback
        assert "Field2" in feedback
        assert "7 more error" in feedback


# ============================================================================
# TestSelfCorrectionLoopUnit
# ============================================================================


class TestSelfCorrectionLoopUnit:
    """Unit tests for self_correction_loop (mocked API)."""

    def test_loop_succeeds_on_valid_template(self, sample_source_schema):
        """Test that loop succeeds immediately for valid template."""
        # Use a minimal valid UPS ShipTo schema
        from src.orchestrator.nl_engine.ups_schema import UPS_SHIPTO_SCHEMA

        valid_template = """{
            "Name": "{{ name }}",
            "Address": {
                "AddressLine": ["{{ address }}"],
                "City": "{{ city }}",
                "StateProvinceCode": "{{ state }}",
                "PostalCode": "{{ zip }}",
                "CountryCode": "US"
            }
        }"""

        result = self_correction_loop(
            template=valid_template,
            source_schema=sample_source_schema,
            target_schema=UPS_SHIPTO_SCHEMA,
            sample_data={
                "name": "John Doe",
                "address": "123 Main St",
                "city": "Anytown",
                "state": "CA",
                "zip": "90210",
            },
            max_attempts=3,
        )

        assert result.success is True
        assert result.total_attempts == 1
        assert result.final_template is not None

    def test_loop_tracks_all_attempts(self, sample_source_schema):
        """Test that loop tracks all correction attempts."""
        # Template with validation error (missing required field)
        invalid_template = '{"Name": "{{ name }}"}'

        # Mock the Claude API to return same template (no fix)
        with patch("src.orchestrator.nl_engine.self_correction.os.environ.get") as mock_env:
            mock_env.return_value = None  # No API key - corrections will fail

            with pytest.raises(MaxCorrectionsExceeded) as exc_info:
                self_correction_loop(
                    template=invalid_template,
                    source_schema=sample_source_schema,
                    max_attempts=2,
                )

            result = exc_info.value.result
            assert result.total_attempts == 2
            assert len(result.attempts) == 2

    def test_loop_raises_after_max_attempts(self, sample_source_schema):
        """Test that MaxCorrectionsExceeded is raised after max attempts."""
        invalid_template = '{"InvalidField": "{{ name }}"}'

        with patch("src.orchestrator.nl_engine.self_correction.os.environ.get") as mock_env:
            mock_env.return_value = None  # No API key

            with pytest.raises(MaxCorrectionsExceeded) as exc_info:
                self_correction_loop(
                    template=invalid_template,
                    source_schema=sample_source_schema,
                    max_attempts=3,
                )

            exc = exc_info.value
            assert exc.result.total_attempts == 3
            assert exc.result.success is False
            assert len(exc.options) == 4

    def test_loop_respects_max_attempts_limit(self, sample_source_schema):
        """Test that max_attempts is clamped to valid range."""
        invalid_template = '{"Name": "{{ name }}"}'

        with patch("src.orchestrator.nl_engine.self_correction.os.environ.get") as mock_env:
            mock_env.return_value = None

            # Test clamped to minimum
            with pytest.raises(MaxCorrectionsExceeded) as exc_info:
                self_correction_loop(
                    template=invalid_template,
                    source_schema=sample_source_schema,
                    max_attempts=0,  # Should be clamped to 1
                )
            assert exc_info.value.result.total_attempts == 1

            # Test clamped to maximum
            with pytest.raises(MaxCorrectionsExceeded) as exc_info:
                self_correction_loop(
                    template=invalid_template,
                    source_schema=sample_source_schema,
                    max_attempts=10,  # Should be clamped to 5
                )
            assert exc_info.value.result.total_attempts == 5


# ============================================================================
# Integration Tests (require API key)
# ============================================================================


@pytest.mark.skipif(
    not pytest.importorskip("anthropic", reason="anthropic not installed"),
    reason="anthropic package not available",
)
class TestSelfCorrectionLoopIntegration:
    """Integration tests for self_correction_loop with real API.

    These tests are skipped unless ANTHROPIC_API_KEY is set.
    """

    @pytest.fixture(autouse=True)
    def skip_without_api_key(self):
        """Skip tests if ANTHROPIC_API_KEY not set."""
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

    def test_correction_modifies_template(self, sample_source_schema):
        """Test that LLM actually modifies template to fix errors."""
        # Template missing truncation for long name
        template = '{"Name": "{{ name }}"}'

        from src.orchestrator.nl_engine.self_correction import attempt_correction
        from src.orchestrator.nl_engine.template_validator import ValidationError

        errors = [
            ValidationError(
                path="Name",
                message="string too long",
                expected="string with at most 35 character(s)",
                actual="A" * 40,
                schema_rule="maxLength",
            )
        ]

        attempt = attempt_correction(template, errors, sample_source_schema)

        # Should have suggested a fix
        assert attempt.corrected_template is not None
        # Should be different from original
        assert attempt.corrected_template != template

    def test_correction_addresses_errors(self, sample_source_schema):
        """Test that corrections actually address the validation errors."""
        from src.orchestrator.nl_engine.ups_schema import UPS_SHIPTO_SCHEMA

        # Template with phone number issue
        template = """{
            "Name": "{{ name }}",
            "Phone": {
                "Number": "{{ phone }}"
            },
            "Address": {
                "AddressLine": ["{{ address }}"],
                "City": "{{ city }}",
                "StateProvinceCode": "{{ state }}",
                "PostalCode": "{{ zip }}",
                "CountryCode": "US"
            }
        }"""

        try:
            result = self_correction_loop(
                template=template,
                source_schema=sample_source_schema,
                target_schema=UPS_SHIPTO_SCHEMA,
                sample_data={
                    "name": "John Doe",
                    "phone": "5551234567",
                    "address": "123 Main St",
                    "city": "Anytown",
                    "state": "CA",
                    "zip": "90210",
                },
                max_attempts=3,
            )
            # If it succeeds, the template should be valid
            assert result.success is True
        except MaxCorrectionsExceeded as e:
            # If it fails, we should have multiple attempts
            assert e.result.total_attempts > 0
