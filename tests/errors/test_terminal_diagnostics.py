"""Totality tests for safe terminal diagnostic projection."""

import pytest

from src.errors.terminal_diagnostics import (
    MAX_TERMINAL_ROW_NUMBER,
    project_terminal_row_diagnostic,
    project_terminal_row_diagnostics,
)


@pytest.mark.parametrize(
    "row_number",
    [None, "1", True, 0, -1, MAX_TERMINAL_ROW_NUMBER + 1],
)
def test_invalid_row_numbers_are_omitted_without_raising(row_number: object) -> None:
    assert project_terminal_row_diagnostic(row_number, "E-3001") is None
    diagnostics, omitted = project_terminal_row_diagnostics([(row_number, "E-3001")])
    assert diagnostics == []
    assert omitted == 1
