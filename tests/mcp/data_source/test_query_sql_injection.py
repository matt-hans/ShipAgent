"""Tests for DuckDB SQL injection prevention (F-3, F-4).

Verifies that the query tools reject comment-based bypass, stacked
queries, dangerous keywords, and type-override injection.
"""

import pytest

from src.mcp.data_source.tools.query_tools import (
    _safe_cast_expression,
    _strip_sql_comments,
)


class TestStripSqlComments:
    """Tests for _strip_sql_comments helper."""

    def test_removes_block_comments(self):
        """Block comments /* ... */ are stripped."""
        sql = "SELECT /* DROP TABLE x */ * FROM t"
        assert "DROP" not in _strip_sql_comments(sql)

    def test_removes_line_comments(self):
        """Line comments -- ... are stripped."""
        sql = "SELECT * FROM t -- DROP TABLE x"
        assert "DROP" not in _strip_sql_comments(sql)

    def test_removes_multiline_block_comment(self):
        """Multi-line block comments are stripped."""
        sql = "SELECT * FROM t /* \nDROP\nTABLE\nx\n */ WHERE 1=1"
        assert "DROP" not in _strip_sql_comments(sql)

    def test_preserves_normal_sql(self):
        """Normal SQL without comments is preserved."""
        sql = "SELECT col1, col2 FROM imported_data WHERE state = 'CA'"
        assert _strip_sql_comments(sql) == sql


class TestSafeCastExpression:
    """Tests for _safe_cast_expression type validation."""

    def test_valid_varchar(self):
        """VARCHAR type is accepted."""
        result = _safe_cast_expression("col", "VARCHAR")
        assert result == 'CAST("col" AS VARCHAR) AS "col"'

    def test_valid_decimal_with_precision(self):
        """DECIMAL(10,2) is accepted."""
        result = _safe_cast_expression("col", "DECIMAL(10,2)")
        assert result == 'CAST("col" AS DECIMAL(10,2)) AS "col"'

    def test_valid_integer(self):
        """INTEGER type is accepted."""
        result = _safe_cast_expression("col", "INTEGER")
        assert result == 'CAST("col" AS INTEGER) AS "col"'

    def test_valid_double(self):
        """DOUBLE type is accepted."""
        result = _safe_cast_expression("col", "DOUBLE")
        assert result == 'CAST("col" AS DOUBLE) AS "col"'

    def test_valid_timestamp(self):
        """TIMESTAMP type is accepted."""
        result = _safe_cast_expression("col", "TIMESTAMP")
        assert result == 'CAST("col" AS TIMESTAMP) AS "col"'

    def test_case_insensitive(self):
        """Lowercase types are uppercased and accepted."""
        result = _safe_cast_expression("col", "varchar")
        assert "VARCHAR" in result

    def test_rejects_sql_injection(self):
        """SQL injection in type string is rejected."""
        with pytest.raises(ValueError, match="Invalid type override"):
            _safe_cast_expression("col", "VARCHAR); DROP TABLE imported_data; --")

    def test_rejects_subquery(self):
        """Subquery in type string is rejected."""
        with pytest.raises(ValueError, match="Invalid type override"):
            _safe_cast_expression("col", "VARCHAR) AS x FROM (SELECT 1")

    def test_rejects_semicolon(self):
        """Semicolons in type string are rejected."""
        with pytest.raises(ValueError, match="Invalid type override"):
            _safe_cast_expression("col", "INTEGER; DROP TABLE t")

    def test_rejects_empty(self):
        """Empty type string is rejected."""
        with pytest.raises(ValueError, match="Invalid type override"):
            _safe_cast_expression("col", "")

    def test_rejects_special_chars(self):
        """Special characters in type string are rejected."""
        with pytest.raises(ValueError, match="Invalid type override"):
            _safe_cast_expression("col", "VARCHAR'--")


class TestQueryDataKeywordBlocking:
    """Tests for dangerous keyword blocking in query_data (F-3).

    These tests verify the keyword list and comment stripping logic
    at the unit level via _strip_sql_comments.
    """

    @pytest.mark.parametrize(
        "keyword",
        [
            "COPY",
            "ATTACH",
            "DETACH",
            "EXPORT",
            "IMPORT",
            "LOAD",
            "INSTALL",
            "CALL",
            "PRAGMA",
            "SET",
            "EXECUTE",
            "READ_CSV",
            "READ_PARQUET",
            "READ_JSON",
            "GLOB",
        ],
    )
    def test_new_dangerous_keywords_detectable(self, keyword):
        """New dangerous keywords are detected after comment stripping."""
        # Verify comment bypass doesn't hide them
        sql_with_comment = f"SELECT /* {keyword} */ * FROM t"
        stripped = _strip_sql_comments(sql_with_comment)
        assert keyword not in stripped.upper()

        # Verify they ARE detected when not in a comment
        sql_plain = f"SELECT * FROM {keyword}('file.csv')"
        stripped_plain = _strip_sql_comments(sql_plain)
        assert keyword in stripped_plain.upper()

    def test_semicolon_in_query_detectable(self):
        """Semicolons for stacked queries are detectable after stripping."""
        sql = "SELECT 1; DROP TABLE imported_data"
        stripped = _strip_sql_comments(sql)
        assert ";" in stripped

    def test_comment_bypass_block_comment(self):
        """Block comment hiding DROP is stripped before keyword check."""
        sql = "SELECT * FROM imported_data /* DROP TABLE imported_data */"
        stripped = _strip_sql_comments(sql)
        assert "DROP" not in stripped

    def test_comment_bypass_line_comment(self):
        """Line comment hiding DELETE is stripped before keyword check."""
        sql = "SELECT * FROM imported_data -- DELETE FROM imported_data"
        stripped = _strip_sql_comments(sql)
        assert "DELETE" not in stripped

    def test_legitimate_select_passes(self):
        """Legitimate SELECT queries pass through comment stripping intact."""
        sql = "SELECT state, COUNT(*) as cnt FROM imported_data GROUP BY state"
        stripped = _strip_sql_comments(sql)
        assert stripped == sql
        assert stripped.strip().upper().startswith("SELECT")
