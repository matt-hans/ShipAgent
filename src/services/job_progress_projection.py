"""Authoritative safe job progress derived from persisted row state."""

from dataclasses import dataclass
from typing import Any

from src.db.models import RowStatus
from src.errors.terminal_diagnostics import (
    MAX_TERMINAL_COUNT,
    SafeTerminalRowDiagnostic,
    project_terminal_row_diagnostics,
)

_FAILURE_STATUSES = {
    RowStatus.failed.value,
    RowStatus.needs_review.value,
}
_PROCESSED_STATUSES = {
    RowStatus.completed.value,
    RowStatus.failed.value,
    RowStatus.needs_review.value,
    RowStatus.skipped.value,
}


def _bounded_nonnegative_int(value: Any, upper_bound: int) -> int:
    """Clamp an int to [0, upper_bound]; non-int and bool values become 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, upper_bound))


def _bounded_sum(values: list[Any]) -> int:
    """Sum positive ints, ignoring malformed values and saturating at the cap."""
    total = 0
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        total = min(MAX_TERMINAL_COUNT, total + value)
    return total


@dataclass(frozen=True, slots=True)
class AuthoritativeJobProgress:
    """Closed aggregate shared by REST progress and completion artifacts."""

    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int
    total_duties_taxes_cents: int
    international_row_count: int
    row_failures: list[SafeTerminalRowDiagnostic]
    omitted_failure_count: int

    def row_failures_json(self) -> list[dict[str, Any]]:
        """Return row failure diagnostics as JSON-ready dicts."""
        return [diagnostic.model_dump(mode="json") for diagnostic in self.row_failures]


def project_authoritative_job_progress(
    job: Any,
    rows: list[Any],
) -> AuthoritativeJobProgress:
    """Derive bounded counts and diagnostics from one persisted row snapshot."""
    if not rows:
        total_rows = _bounded_nonnegative_int(
            getattr(job, "total_rows", 0),
            MAX_TERMINAL_COUNT,
        )
        successful_rows = min(
            total_rows,
            _bounded_nonnegative_int(
                getattr(job, "successful_rows", 0),
                MAX_TERMINAL_COUNT,
            ),
        )
        failed_rows = min(
            total_rows - successful_rows,
            _bounded_nonnegative_int(
                getattr(job, "failed_rows", 0),
                MAX_TERMINAL_COUNT,
            ),
        )
        processed_rows = min(
            total_rows,
            max(
                successful_rows + failed_rows,
                _bounded_nonnegative_int(
                    getattr(job, "processed_rows", 0),
                    MAX_TERMINAL_COUNT,
                ),
            ),
        )
        total_cost_cents = _bounded_nonnegative_int(
            getattr(job, "total_cost_cents", 0),
            MAX_TERMINAL_COUNT,
        )
        total_duties_taxes_cents = _bounded_nonnegative_int(
            getattr(job, "total_duties_taxes_cents", 0),
            MAX_TERMINAL_COUNT,
        )
        international_row_count = min(
            successful_rows,
            _bounded_nonnegative_int(
                getattr(job, "international_row_count", 0),
                MAX_TERMINAL_COUNT,
            ),
        )
        return AuthoritativeJobProgress(
            total_rows=total_rows,
            processed_rows=processed_rows,
            successful_rows=successful_rows,
            failed_rows=failed_rows,
            total_cost_cents=total_cost_cents,
            total_duties_taxes_cents=total_duties_taxes_cents,
            international_row_count=international_row_count,
            row_failures=[],
            omitted_failure_count=failed_rows,
        )

    total_rows = min(len(rows), MAX_TERMINAL_COUNT)
    successful = [
        row for row in rows if getattr(row, "status", None) == RowStatus.completed.value
    ]
    failed = [row for row in rows if getattr(row, "status", None) in _FAILURE_STATUSES]
    processed_rows = min(
        total_rows,
        sum(1 for row in rows if getattr(row, "status", None) in _PROCESSED_STATUSES),
    )
    row_failures, omitted_failure_count = project_terminal_row_diagnostics(
        (
            getattr(row, "row_number", None),
            getattr(row, "error_code", None),
        )
        for row in failed
    )
    successful_rows = len(successful)
    international_from_rows = sum(
        1
        for row in successful
        if isinstance(
            country := getattr(row, "destination_country", None),
            str,
        )
        and country.upper() not in {"US", "PR"}
    )
    recorded_international = _bounded_nonnegative_int(
        getattr(job, "international_row_count", 0),
        MAX_TERMINAL_COUNT,
    )

    return AuthoritativeJobProgress(
        total_rows=total_rows,
        processed_rows=processed_rows,
        successful_rows=successful_rows,
        failed_rows=len(failed),
        total_cost_cents=_bounded_sum(
            [getattr(row, "cost_cents", None) for row in successful]
        ),
        total_duties_taxes_cents=_bounded_sum(
            [getattr(row, "duties_taxes_cents", None) for row in successful]
        ),
        international_row_count=min(
            successful_rows,
            max(international_from_rows, recorded_international),
        ),
        row_failures=row_failures,
        omitted_failure_count=omitted_failure_count,
    )
