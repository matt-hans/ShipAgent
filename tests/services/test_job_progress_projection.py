"""Direct tests for the authoritative job progress projection."""

from types import SimpleNamespace

from src.errors.terminal_diagnostics import (
    MAX_TERMINAL_COUNT,
    MAX_TERMINAL_ROW_DIAGNOSTICS,
)
from src.services.job_progress_projection import project_authoritative_job_progress


def _row(status, row_number=1, **kw):
    """Build a persisted-row stand-in."""
    return SimpleNamespace(
        status=status,
        row_number=row_number,
        error_code=kw.get("error_code"),
        destination_country=kw.get("destination_country"),
        cost_cents=kw.get("cost_cents"),
        duties_taxes_cents=kw.get("duties_taxes_cents"),
    )


def _job(**kw):
    """Build a job stand-in with aggregate counters."""
    base = {
        "total_rows": 0,
        "successful_rows": 0,
        "failed_rows": 0,
        "processed_rows": 0,
        "total_cost_cents": 0,
        "total_duties_taxes_cents": 0,
        "international_row_count": 0,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_row_snapshot_counts_and_costs_come_from_rows_not_job():
    rows = [
        _row("completed", 1, cost_cents=500, destination_country="US"),
        _row(
            "completed",
            2,
            cost_cents=900,
            duties_taxes_cents=100,
            destination_country="ca",
        ),
        _row("failed", 3, error_code="E-3001"),
        _row("needs_review", 4),
        _row("skipped", 5),
        _row("pending", 6),
    ]
    # Job aggregates deliberately disagree; rows are authoritative.
    progress = project_authoritative_job_progress(
        _job(total_rows=99, successful_rows=99), rows
    )

    assert progress.total_rows == 6
    assert progress.successful_rows == 2
    assert progress.failed_rows == 2
    assert progress.processed_rows == 5
    assert progress.total_cost_cents == 1400
    assert progress.total_duties_taxes_cents == 100
    assert progress.international_row_count == 1
    assert [d.row_number for d in progress.row_failures] == [3, 4]
    assert progress.omitted_failure_count == 0


def test_us_and_pr_destinations_are_not_international():
    rows = [
        _row("completed", 1, destination_country="us"),
        _row("completed", 2, destination_country="PR"),
        _row("completed", 3, destination_country=None),
    ]
    assert project_authoritative_job_progress(_job(), rows).international_row_count == 0


def test_recorded_international_count_is_capped_by_successful_rows():
    rows = [_row("completed", 1, destination_country="US")]
    progress = project_authoritative_job_progress(
        _job(international_row_count=50), rows
    )
    assert progress.international_row_count == 1


def test_invalid_row_numbers_are_omitted_but_counted_as_failures():
    rows = [_row("failed", 0), _row("failed", True), _row("failed", 2)]
    progress = project_authoritative_job_progress(_job(), rows)

    assert progress.failed_rows == 3
    assert [d.row_number for d in progress.row_failures] == [2]
    assert progress.omitted_failure_count == 2


def test_failure_diagnostics_are_bounded():
    count = MAX_TERMINAL_ROW_DIAGNOSTICS + 5
    rows = [_row("failed", n) for n in range(1, count + 1)]
    progress = project_authoritative_job_progress(_job(), rows)

    assert len(progress.row_failures) == MAX_TERMINAL_ROW_DIAGNOSTICS
    assert progress.omitted_failure_count == 5
    assert progress.failed_rows == count


def test_malformed_money_values_are_ignored():
    rows = [
        _row("completed", 1, cost_cents=True),
        _row("completed", 2, cost_cents="12"),
        _row("completed", 3, cost_cents=-5),
        _row("completed", 4, cost_cents=250),
    ]
    assert project_authoritative_job_progress(_job(), rows).total_cost_cents == 250


def test_cost_sum_saturates_at_contract_maximum():
    rows = [
        _row("completed", 1, cost_cents=MAX_TERMINAL_COUNT),
        _row("completed", 2, cost_cents=MAX_TERMINAL_COUNT),
    ]
    assert (
        project_authoritative_job_progress(_job(), rows).total_cost_cents
        == MAX_TERMINAL_COUNT
    )


def test_no_rows_falls_back_to_clamped_job_counters():
    job = _job(
        total_rows=10,
        successful_rows=8,
        failed_rows=9,  # clamped to remaining capacity (10 - 8)
        processed_rows=1,
        total_cost_cents=1234,
        international_row_count=20,  # capped by successful rows
    )
    progress = project_authoritative_job_progress(job, [])

    assert (progress.total_rows, progress.successful_rows, progress.failed_rows) == (
        10,
        8,
        2,
    )
    assert progress.processed_rows == 10
    assert progress.total_cost_cents == 1234
    assert progress.international_row_count == 8
    assert progress.row_failures == []
    assert progress.omitted_failure_count == 2


def test_no_rows_with_garbage_counters_yields_zeros():
    job = _job(
        total_rows="many", successful_rows=True, failed_rows=-3, total_cost_cents=None
    )
    progress = project_authoritative_job_progress(job, [])

    assert progress.total_rows == 0
    assert progress.successful_rows == 0
    assert progress.failed_rows == 0
    assert progress.total_cost_cents == 0


def test_row_failures_json_is_json_serialisable_dicts():
    progress = project_authoritative_job_progress(
        _job(), [_row("failed", 7, error_code="E-3001")]
    )
    payload = progress.row_failures_json()

    assert len(payload) == 1
    assert payload[0]["row_number"] == 7
    assert isinstance(payload[0]["error_code"], str)
