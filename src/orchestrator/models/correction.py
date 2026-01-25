"""Correction models for self-correction loop tracking.

These Pydantic models track self-correction attempts when Jinja2 mapping
templates fail UPS schema validation. Per CONTEXT.md Decision 4, the system
attempts up to 3 corrections before escalating to the user with options.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.orchestrator.nl_engine.template_validator import ValidationError


class CorrectionOptions(str, Enum):
    """User options after maximum correction attempts are exhausted.

    Per CONTEXT.md Decision 4, when self-correction fails after max retries,
    the user is presented with these options.
    """

    CORRECT_SOURCE = "correct_source"  # User fixes source data
    MANUAL_FIX = "manual_fix"  # User provides manual template fix
    SKIP_PROBLEMATIC = "skip_problematic"  # Skip failing rows
    ABORT = "abort"  # Abort operation


class CorrectionAttempt(BaseModel):
    """Record of a single self-correction attempt.

    Tracks what was tried during one iteration of the correction loop,
    including the original template, errors encountered, and any fixes made.

    Attributes:
        attempt_number: Which attempt this is (1, 2, or 3).
        original_template: The Jinja2 template before correction.
        validation_errors: Errors from template validation.
        corrected_template: The template after LLM correction (if any).
        changes_made: List of descriptions of changes made.
        success: Whether this attempt produced a valid template.
        timestamp: When the attempt was made.
    """

    attempt_number: int = Field(
        ...,
        ge=1,
        le=10,
        description="Attempt number (typically 1-3)",
    )
    original_template: str = Field(
        ...,
        description="Jinja2 template before correction",
    )
    validation_errors: list[Any] = Field(
        default_factory=list,
        description="Validation errors that triggered correction (ValidationError objects)",
    )
    corrected_template: Optional[str] = Field(
        default=None,
        description="Template after LLM correction",
    )
    changes_made: list[str] = Field(
        default_factory=list,
        description="Descriptions of changes made by LLM",
    )
    success: bool = Field(
        default=False,
        description="Whether corrected template passes validation",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the attempt was made",
    )


class CorrectionResult(BaseModel):
    """Overall result of the self-correction loop.

    Aggregates all correction attempts and indicates whether the loop
    ultimately succeeded in producing a valid template.

    Attributes:
        final_template: The working template if successful, None otherwise.
        attempts: List of all correction attempts made.
        success: Whether a valid template was produced.
        total_attempts: Number of attempts made.
        failure_reason: Explanation if max attempts reached without success.
    """

    final_template: Optional[str] = Field(
        default=None,
        description="Working template if successful",
    )
    attempts: list[CorrectionAttempt] = Field(
        default_factory=list,
        description="All correction attempts made",
    )
    success: bool = Field(
        default=False,
        description="Whether a valid template was produced",
    )
    total_attempts: int = Field(
        default=0,
        description="Total number of correction attempts",
    )
    failure_reason: Optional[str] = Field(
        default=None,
        description="Explanation if correction failed",
    )


class MaxCorrectionsExceeded(Exception):
    """Exception raised when self-correction exhausts all attempts.

    Provides the full correction history and available user options
    for handling the failure.

    Attributes:
        result: CorrectionResult with all attempt history.
        options: Available CorrectionOptions for user to choose.
        message: Human-readable error description.
    """

    def __init__(
        self,
        result: CorrectionResult,
        options: Optional[list[CorrectionOptions]] = None,
        message: Optional[str] = None,
    ) -> None:
        """Initialize MaxCorrectionsExceeded.

        Args:
            result: The CorrectionResult with all attempts.
            options: Available options for user (defaults to all options).
            message: Optional custom error message.
        """
        self.result = result
        self.options = options or list(CorrectionOptions)
        self.message = message or (
            f"Self-correction failed after {result.total_attempts} attempts. "
            f"Please choose an option to continue."
        )
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return formatted error string with options."""
        lines = [self.message, "", "Available options:"]
        for opt in self.options:
            if opt == CorrectionOptions.CORRECT_SOURCE:
                lines.append(f"  - {opt.value}: Fix the source data and retry")
            elif opt == CorrectionOptions.MANUAL_FIX:
                lines.append(f"  - {opt.value}: Manually fix the template")
            elif opt == CorrectionOptions.SKIP_PROBLEMATIC:
                lines.append(f"  - {opt.value}: Skip rows with validation errors")
            elif opt == CorrectionOptions.ABORT:
                lines.append(f"  - {opt.value}: Cancel the operation")
        return "\n".join(lines)


__all__ = [
    "CorrectionAttempt",
    "CorrectionResult",
    "CorrectionOptions",
    "MaxCorrectionsExceeded",
]
