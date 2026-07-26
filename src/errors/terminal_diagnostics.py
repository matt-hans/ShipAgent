"""Safe terminal diagnostics for failed batch rows."""

from collections.abc import Iterable
from typing import Any

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
_SAFE_TERMINAL_STATUS_MESSAGES = frozenset(
    {
        "Batch completed.",
        "Batch completed with warnings.",
        "Batch failed.",
        "Batch cancelled. You can enter a new command.",
    }
)
_COMPLETION_METADATA_KEYS = frozenset({"type", "jobId", "action", "completion"})
_COMPLETION_KEYS = frozenset(
    {
        "status",
        "outcome",
        "hasWarnings",
        "cancelled",
        "statusMessage",
        "jobName",
        "command",
        "successful",
        "failed",
        "totalCostCents",
        "dutiesTaxesCents",
        "internationalCount",
        "error",
        "row_failures",
        "omitted_failure_count",
    }
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
    if isinstance(row_number, bool) or not isinstance(row_number, int):
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
    """Validate the safe diagnostic subset of a frontend completion artifact."""
    if metadata.get("type") != "completion":
        return
    if set(metadata) - _COMPLETION_METADATA_KEYS:
        raise ValueError("Completion artifact diagnostics are invalid.")
    completion = metadata.get("completion")
    if not isinstance(completion, dict):
        raise ValueError("Completion artifact diagnostics are invalid.")
    if set(completion) - _COMPLETION_KEYS:
        raise ValueError("Completion artifact diagnostics are invalid.")
    if "rowFailures" in completion or "omittedFailureCount" in completion:
        raise ValueError("Completion artifact diagnostics are invalid.")

    raw_failures = completion.get("row_failures", [])
    if (
        not isinstance(raw_failures, list)
        or len(raw_failures) > MAX_TERMINAL_ROW_DIAGNOSTICS
    ):
        raise ValueError("Completion artifact diagnostics are invalid.")
    try:
        for raw_failure in raw_failures:
            SafeTerminalRowDiagnostic.model_validate(raw_failure)
    except ValidationError:
        raise ValueError("Completion artifact diagnostics are invalid.") from None

    omitted_failure_count = completion.get("omitted_failure_count", 0)
    failed = completion.get("failed", 0)
    if (
        isinstance(omitted_failure_count, bool)
        or not isinstance(omitted_failure_count, int)
        or omitted_failure_count < 0
        or omitted_failure_count > MAX_TERMINAL_COUNT
        or isinstance(failed, bool)
        or not isinstance(failed, int)
        or failed < 0
        or failed > MAX_TERMINAL_COUNT
        or failed != len(raw_failures) + omitted_failure_count
    ):
        raise ValueError("Completion artifact diagnostics are invalid.")

    if "error" in completion and completion["error"] is not None:
        try:
            SafeTerminalDiagnostic.model_validate(completion["error"])
        except ValidationError:
            raise ValueError("Completion artifact diagnostics are invalid.") from None
    status_message = completion.get("statusMessage")
    if (
        status_message is not None
        and status_message not in _SAFE_TERMINAL_STATUS_MESSAGES
    ):
        raise ValueError("Completion artifact diagnostics are invalid.")


def sanitize_completion_artifact_metadata(metadata: Any) -> Any:
    """Project legacy completion metadata before it can reach history clients."""
    if not isinstance(metadata, dict) or metadata.get("type") != "completion":
        return metadata
    raw_completion = metadata.get("completion")
    if not isinstance(raw_completion, dict):
        return {"type": "completion", "completion": {}}

    completion: dict[str, Any] = {}
    for key in (
        "status",
        "outcome",
        "hasWarnings",
        "cancelled",
        "successful",
        "failed",
        "totalCostCents",
        "dutiesTaxesCents",
        "internationalCount",
    ):
        value = raw_completion.get(key)
        if isinstance(value, bool) or isinstance(value, (int, str)):
            completion[key] = value
    for key in ("jobName", "command"):
        value = raw_completion.get(key)
        if isinstance(value, str) and len(value) <= 255:
            completion[key] = value
    status_message = raw_completion.get("statusMessage")
    if status_message in _SAFE_TERMINAL_STATUS_MESSAGES:
        completion["statusMessage"] = status_message

    raw_error = raw_completion.get("error")
    if raw_error is not None:
        raw_code = raw_error.get("error_code") if isinstance(raw_error, dict) else None
        if raw_code is None and isinstance(raw_error, dict):
            raw_code = raw_error.get("code")
        completion["error"] = project_terminal_diagnostic(raw_code).model_dump(
            mode="json"
        )

    raw_failures = raw_completion.get("row_failures")
    if raw_failures is None:
        raw_failures = raw_completion.get("rowFailures", [])
    diagnostics: list[SafeTerminalRowDiagnostic] = []
    if isinstance(raw_failures, list):
        for raw_failure in raw_failures:
            if not isinstance(raw_failure, dict):
                continue
            try:
                diagnostic = SafeTerminalRowDiagnostic.model_validate(raw_failure)
            except ValidationError:
                diagnostic = project_terminal_row_diagnostic(
                    raw_failure.get("row_number", raw_failure.get("rowNumber")),
                    raw_failure.get("error_code", raw_failure.get("errorCode")),
                )
            if (
                diagnostic is not None
                and len(diagnostics) < MAX_TERMINAL_ROW_DIAGNOSTICS
            ):
                diagnostics.append(diagnostic)
    if diagnostics:
        completion["row_failures"] = [d.model_dump(mode="json") for d in diagnostics]

    failed = raw_completion.get("failed")
    failed_count = (
        failed
        if isinstance(failed, int) and not isinstance(failed, bool) and failed >= 0
        else len(diagnostics)
    )
    completion["omitted_failure_count"] = max(0, failed_count - len(diagnostics))

    result: dict[str, Any] = {"type": "completion", "completion": completion}
    if isinstance(metadata.get("jobId"), str) and len(metadata["jobId"]) <= 128:
        result["jobId"] = metadata["jobId"]
    if metadata.get("action") == "complete":
        result["action"] = "complete"
    return result
