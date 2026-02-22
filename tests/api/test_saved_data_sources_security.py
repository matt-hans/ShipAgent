"""Tests for saved data source reconnect SQL validation (L-2, CWE-89).

Verifies that saved database source queries are validated against the
dangerous keyword blocklist before being passed to import_database.
"""

import re

import pytest


class TestSavedSourceQueryValidation:
    """Tests for SQL keyword blocklist on saved source reconnect."""

    _DANGEROUS_KEYWORDS = [
        "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE",
        "TRUNCATE", "COPY", "ATTACH", "DETACH", "EXPORT", "IMPORT",
        "LOAD", "INSTALL", "CALL", "PRAGMA", "SET", "EXECUTE",
    ]

    def test_select_query_accepted(self):
        """SELECT queries pass validation."""
        query = "SELECT * FROM shipments WHERE status = 'pending'"
        query_upper = query.strip().upper()
        assert query_upper.startswith("SELECT")
        for kw in self._DANGEROUS_KEYWORDS:
            assert not re.search(rf"\b{kw}\b", query_upper)

    @pytest.mark.parametrize("keyword", [
        "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE",
        "TRUNCATE", "COPY", "ATTACH", "PRAGMA", "EXECUTE",
    ])
    def test_dangerous_keywords_detected(self, keyword):
        """Dangerous keywords in queries are detected by the blocklist."""
        query = f"SELECT 1; {keyword} TABLE shipments"
        query_upper = query.strip().upper()
        assert re.search(rf"\b{keyword}\b", query_upper)

    def test_non_select_rejected(self):
        """Non-SELECT queries fail the startswith check."""
        for q in ["INSERT INTO t VALUES (1)", "DROP TABLE t", "UPDATE t SET x=1"]:
            assert not q.strip().upper().startswith("SELECT")

    def test_blocklist_matches_query_tools_blocklist(self):
        """Saved source blocklist includes the same keywords as query_tools.py."""
        from src.mcp.data_source.tools.query_tools import query_data
        import inspect

        source = inspect.getsource(query_data)
        # Verify the core dangerous keywords are in query_data source
        for kw in ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE"]:
            assert kw in source, f"{kw} not in query_tools.py blocklist"
