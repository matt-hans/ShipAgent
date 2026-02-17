"""Tests for filter-specific error codes in the registry."""


class TestFilterErrorCodes:
    """Verify E-2030 through E-2043 are registered."""

    def test_unknown_column_registered(self):
        from src.errors.registry import get_error

        err = get_error("E-2030")
        assert err is not None
        assert err.title == "Unknown Filter Column"

    def test_unknown_canonical_term_registered(self):
        from src.errors.registry import get_error

        err = get_error("E-2031")
        assert err is not None
        assert "Canonical Term" in err.title

    def test_all_fourteen_codes_registered(self):
        from src.errors.registry import get_error

        for code_num in range(2030, 2044):
            code = f"E-{code_num}"
            assert get_error(code) is not None, f"{code} not registered"

    def test_codes_are_validation_category(self):
        from src.errors.registry import ErrorCategory, get_error

        for code_num in range(2030, 2044):
            err = get_error(f"E-{code_num}")
            assert err.category == ErrorCategory.VALIDATION
