"""Safe terminal diagnostics for failed batch rows."""

import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.errors.registry import ERROR_REGISTRY, ErrorCategory

MAX_TERMINAL_ROW_NUMBER = 2_147_483_647
MAX_TERMINAL_ROW_DIAGNOSTICS = 20
MAX_TERMINAL_DIAGNOSTIC_MESSAGE_LENGTH = 96
MAX_TERMINAL_COUNT = 2_147_483_647

_SAFE_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.DATA: "The row contains invalid or missing data.",
    ErrorCategory.VALIDATION: "The row did not pass shipment validation.",
    ErrorCategory.UPS_API: "The carrier could not process this shipment.",
    ErrorCategory.SYSTEM: "The row could not be processed because of a system error.",
    ErrorCategory.AUTH: "The carrier connection could not authenticate.",
}
_TERMINAL_COMPLETION_MAPPINGS: dict[str, tuple[str, bool, bool, str]] = {
    "completed": ("complete", False, False, "Batch completed."),
    "completed_with_warnings": (
        "complete",
        True,
        False,
        "Batch completed with warnings.",
    ),
    "failed": ("failed", False, False, "Batch failed."),
    "cancelled": (
        "failed",
        False,
        True,
        "Batch cancelled. You can enter a new command.",
    ),
}
_CANONICAL_JOB_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def canonical_terminal_error_code(error_code: Any) -> str:
    """Return an allowlisted code without retaining untrusted error text."""
    if isinstance(error_code, str) and error_code in ERROR_REGISTRY:
        return error_code
    return "E-4001"


def safe_terminal_message(error_code: str) -> str:
    """Return the fixed safe message mapped to an allowlisted error code."""
    return _SAFE_MESSAGES[ERROR_REGISTRY[error_code].category]


class SafeTerminalDiagnostic(BaseModel):
    """Bounded provider- and user-safe terminal failure detail."""

    error_code: str = Field(min_length=6, max_length=6)
    error_category: ErrorCategory
    message: str = Field(
        min_length=1, max_length=MAX_TERMINAL_DIAGNOSTIC_MESSAGE_LENGTH
    )

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def _matches_canonical_mapping(self) -> "SafeTerminalDiagnostic":
        error = ERROR_REGISTRY.get(self.error_code)
        if error is None or error.category is not self.error_category:
            raise ValueError("Terminal diagnostic code/category is not allowlisted.")
        if self.message != safe_terminal_message(self.error_code):
            raise ValueError("Terminal diagnostic message is not canonical.")
        return self


class SafeTerminalRowDiagnostic(SafeTerminalDiagnostic):
    """The only row-level diagnostic allowed in terminal progress artifacts."""

    row_number: int = Field(ge=1, le=MAX_TERMINAL_ROW_NUMBER)


class CompletionArtifactPayload(BaseModel):
    """Closed terminal completion payload accepted at persistence ingress."""

    status: Literal[
        "completed",
        "completed_with_warnings",
        "failed",
        "cancelled",
    ]
    outcome: Literal["complete", "failed"]
    has_warnings: bool = Field(alias="hasWarnings")
    cancelled: bool
    status_message: str = Field(alias="statusMessage")
    job_name: Literal["Shipping batch"] | None = Field(
        default=None,
        alias="jobName",
    )
    successful: int = Field(ge=0, le=MAX_TERMINAL_COUNT)
    failed: int = Field(ge=0, le=MAX_TERMINAL_COUNT)
    total_cost_cents: int = Field(
        ge=0,
        le=MAX_TERMINAL_COUNT,
        alias="totalCostCents",
    )
    duties_taxes_cents: int = Field(
        default=0,
        ge=0,
        le=MAX_TERMINAL_COUNT,
        alias="dutiesTaxesCents",
    )
    international_count: int = Field(
        default=0,
        ge=0,
        le=MAX_TERMINAL_COUNT,
        alias="internationalCount",
    )
    error: SafeTerminalDiagnostic | None = None
    row_failures: list[SafeTerminalRowDiagnostic] = Field(
        default_factory=list,
        max_length=MAX_TERMINAL_ROW_DIAGNOSTICS,
    )
    omitted_failure_count: int = Field(ge=0, le=MAX_TERMINAL_COUNT)

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def _matches_terminal_state_and_counts(self) -> "CompletionArtifactPayload":
        expected = _TERMINAL_COMPLETION_MAPPINGS[self.status]
        if (
            self.outcome,
            self.has_warnings,
            self.cancelled,
            self.status_message,
        ) != expected:
            raise ValueError("Completion terminal fields are not canonical.")
        if self.failed != len(self.row_failures) + self.omitted_failure_count:
            raise ValueError("Completion failure counts are inconsistent.")
        if self.international_count > self.successful:
            raise ValueError("Completion international count is inconsistent.")
        return self


class CompletionArtifactMetadata(BaseModel):
    """Closed metadata envelope for a completion artifact."""

    artifact_type: Literal["completion"] = Field(alias="type")
    job_id: str = Field(
        alias="jobId",
        min_length=36,
        max_length=36,
        pattern=_CANONICAL_JOB_ID.pattern,
    )
    action: Literal["complete"]
    completion: CompletionArtifactPayload

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def project_terminal_diagnostic(error_code: Any) -> SafeTerminalDiagnostic:
    """Project any internal failure code to the canonical safe contract."""
    canonical_code = canonical_terminal_error_code(error_code)
    error = ERROR_REGISTRY[canonical_code]
    return SafeTerminalDiagnostic(
        error_code=canonical_code,
        error_category=error.category,
        message=safe_terminal_message(canonical_code),
    )


def project_terminal_row_diagnostic(
    row_number: Any,
    error_code: Any,
) -> SafeTerminalRowDiagnostic | None:
    """Project a row failure or omit it when its row index is invalid."""
    if (
        isinstance(row_number, bool)
        or not isinstance(row_number, int)
        or row_number < 1
        or row_number > MAX_TERMINAL_ROW_NUMBER
    ):
        return None
    diagnostic = project_terminal_diagnostic(error_code)
    return SafeTerminalRowDiagnostic(row_number=row_number, **diagnostic.model_dump())


def project_terminal_row_diagnostics(
    failures: Iterable[tuple[Any, Any]],
) -> tuple[list[SafeTerminalRowDiagnostic], int]:
    """Bound terminal row diagnostics and report how many were not retained."""
    diagnostics: list[SafeTerminalRowDiagnostic] = []
    omitted_failure_count = 0
    for row_number, error_code in failures:
        diagnostic = project_terminal_row_diagnostic(row_number, error_code)
        if diagnostic is None or len(diagnostics) >= MAX_TERMINAL_ROW_DIAGNOSTICS:
            omitted_failure_count += 1
        else:
            diagnostics.append(diagnostic)
    return diagnostics, omitted_failure_count


def validate_completion_artifact_diagnostics(metadata: dict[str, Any]) -> None:
    """Validate the complete closed frontend completion-artifact contract."""
    if metadata.get("type") != "completion":
        return
    try:
        CompletionArtifactMetadata.model_validate(metadata)
    except ValidationError:
        raise ValueError("Completion artifact diagnostics are invalid.") from None


def _bounded_legacy_count(value: Any) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_TERMINAL_COUNT
    ):
        return None
    return value


def sanitize_completion_artifact_metadata(metadata: Any) -> Any:
    """Project legacy completion metadata before it can reach history clients."""
    if not isinstance(metadata, dict) or metadata.get("type") != "completion":
        return metadata
    raw_completion = metadata.get("completion")
    if not isinstance(raw_completion, dict):
        raw_completion = {}

    try:
        parsed = CompletionArtifactMetadata.model_validate(metadata)
    except ValidationError:
        parsed = None
    if parsed is not None:
        return parsed.model_dump(mode="json", by_alias=True, exclude_none=True)

    raw_error = raw_completion.get("error")
    raw_failures = raw_completion.get("row_failures")
    if raw_failures is None:
        raw_failures = raw_completion.get("rowFailures", [])
    failure_inputs: list[tuple[Any, Any]] = []
    if isinstance(raw_failures, list):
        for raw_failure in raw_failures:
            if isinstance(raw_failure, dict):
                failure_inputs.append(
                    (
                        raw_failure.get(
                            "row_number",
                            raw_failure.get("rowNumber"),
                        ),
                        raw_failure.get(
                            "error_code",
                            raw_failure.get("errorCode"),
                        ),
                    )
                )
            else:
                failure_inputs.append((None, None))
    diagnostics, projected_omitted = project_terminal_row_diagnostics(failure_inputs)
    explicit_omitted = (
        _bounded_legacy_count(raw_completion.get("omitted_failure_count")) or 0
    )
    observed_failure_count = min(
        MAX_TERMINAL_COUNT,
        len(diagnostics) + projected_omitted + explicit_omitted,
    )
    failed_count = max(
        _bounded_legacy_count(raw_completion.get("failed")) or 0,
        observed_failure_count,
    )
    omitted_failure_count = failed_count - len(diagnostics)
    successful = _bounded_legacy_count(raw_completion.get("successful")) or 0
    total_cost_cents = _bounded_legacy_count(raw_completion.get("totalCostCents")) or 0
    duties_taxes_cents = (
        _bounded_legacy_count(raw_completion.get("dutiesTaxesCents")) or 0
    )
    international_count = min(
        successful,
        _bounded_legacy_count(raw_completion.get("internationalCount")) or 0,
    )

    status = raw_completion.get("status")
    if status not in _TERMINAL_COMPLETION_MAPPINGS:
        status = "failed" if failed_count > 0 or raw_error is not None else "completed"
    if status == "completed" and failed_count > 0:
        status = "failed"
    outcome, has_warnings, cancelled, status_message = _TERMINAL_COMPLETION_MAPPINGS[
        status
    ]
    completion: dict[str, Any] = {
        "status": status,
        "outcome": outcome,
        "hasWarnings": has_warnings,
        "cancelled": cancelled,
        "statusMessage": status_message,
        "jobName": "Shipping batch",
        "successful": successful,
        "failed": failed_count,
        "totalCostCents": total_cost_cents,
        "dutiesTaxesCents": duties_taxes_cents,
        "internationalCount": international_count,
        "row_failures": [
            diagnostic.model_dump(mode="json") for diagnostic in diagnostics
        ],
        "omitted_failure_count": omitted_failure_count,
    }
    if raw_error is not None:
        raw_code = raw_error.get("error_code") if isinstance(raw_error, dict) else None
        if raw_code is None and isinstance(raw_error, dict):
            raw_code = raw_error.get("code")
        completion["error"] = project_terminal_diagnostic(raw_code).model_dump(
            mode="json"
        )

    result: dict[str, Any] = {
        "type": "completion",
        "action": "complete",
        "completion": completion,
    }
    job_id = metadata.get("jobId")
    if isinstance(job_id, str) and _CANONICAL_JOB_ID.fullmatch(job_id):
        result["jobId"] = metadata["jobId"]
    return result
