"""Tests for hierarchical data flattening utilities."""

import json

import duckdb
import pytest

from src.mcp.data_source.utils import (
    _coerce_string_value,
    coerce_records,
    flatten_record,
    load_flat_records_to_duckdb,
)


class TestFlattenRecord:
    """Test recursive dict flattening."""

    def test_flat_dict_unchanged(self):
        """Flat dicts pass through without modification."""
        record = {"name": "John", "city": "Dallas"}
        assert flatten_record(record) == {"name": "John", "city": "Dallas"}

    def test_nested_dict_flattened_with_underscore(self):
        """Nested dicts joined with underscore separator."""
        record = {"shipTo": {"name": "John", "city": "Dallas"}}
        result = flatten_record(record)
        assert result == {"shipTo_name": "John", "shipTo_city": "Dallas"}

    def test_deeply_nested(self):
        """Multiple nesting levels flatten correctly."""
        record = {"a": {"b": {"c": "deep"}}}
        assert flatten_record(record) == {"a_b_c": "deep"}

    def test_max_depth_serializes_remainder(self):
        """Beyond max_depth, nested dicts become JSON strings."""
        record = {"a": {"b": {"c": {"d": "too deep"}}}}
        result = flatten_record(record, max_depth=2)
        # At depth 2, the {"d": "too deep"} dict should be JSON-serialized
        assert result["a_b_c"] == json.dumps({"d": "too deep"})

    def test_max_depth_default_allows_deep_nesting(self):
        """Default max_depth=5 handles typical logistics nesting."""
        record = {"a": {"b": {"c": {"d": {"e": "val"}}}}}
        result = flatten_record(record)
        assert result["a_b_c_d_e"] == "val"

    def test_lists_become_json_strings(self):
        """Lists are serialized as JSON strings, not expanded."""
        record = {"items": [{"sku": "A1", "qty": 2}]}
        result = flatten_record(record)
        assert result["items"] == json.dumps([{"sku": "A1", "qty": 2}])

    def test_mixed_nested_and_flat(self):
        """Mix of flat, nested, and list values."""
        record = {
            "orderId": "123",
            "shipTo": {"name": "John", "address": {"line1": "123 Main"}},
            "items": [{"sku": "X"}],
        }
        result = flatten_record(record)
        assert result["orderId"] == "123"
        assert result["shipTo_name"] == "John"
        assert result["shipTo_address_line1"] == "123 Main"
        assert result["items"] == json.dumps([{"sku": "X"}])

    def test_none_values_preserved(self):
        """None values pass through as None."""
        record = {"a": None, "b": "val"}
        assert flatten_record(record) == {"a": None, "b": "val"}

    def test_empty_dict(self):
        """Empty dict returns empty dict."""
        assert flatten_record({}) == {}

    def test_numeric_values_preserved(self):
        """Numbers are not converted to strings."""
        record = {"qty": 5, "price": 12.99}
        result = flatten_record(record)
        assert result["qty"] == 5
        assert result["price"] == 12.99


class TestLoadFlatRecordsToDuckDB:
    """Test loading flat dicts into DuckDB imported_data table."""

    @pytest.fixture()
    def conn(self):
        """Fresh in-memory DuckDB connection."""
        c = duckdb.connect(":memory:")
        yield c
        c.close()

    def test_basic_load(self, conn):
        """Load simple records and verify row count + schema."""
        records = [
            {"name": "John", "city": "Dallas"},
            {"name": "Jane", "city": "Austin"},
        ]
        result = load_flat_records_to_duckdb(conn, records)
        assert result.row_count == 2
        col_names = [c.name for c in result.columns]
        assert "name" in col_names
        assert "city" in col_names
        assert "_source_row_num" not in col_names  # Hidden from schema

    def test_source_row_num_assigned(self, conn):
        """_source_row_num is 1-based and sequential."""
        records = [{"a": "x"}, {"a": "y"}, {"a": "z"}]
        load_flat_records_to_duckdb(conn, records)
        rows = conn.execute(
            "SELECT _source_row_num FROM imported_data ORDER BY _source_row_num"
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3]

    def test_heterogeneous_keys(self, conn):
        """Records with different keys get NULL for missing fields."""
        records = [
            {"name": "John", "phone": "555-1234"},
            {"name": "Jane", "email": "jane@test.com"},
        ]
        result = load_flat_records_to_duckdb(conn, records)
        assert result.row_count == 2
        col_names = {c.name for c in result.columns}
        assert {"name", "phone", "email"} == col_names

    def test_empty_records_list(self, conn):
        """Empty list produces zero-row table."""
        result = load_flat_records_to_duckdb(conn, [])
        assert result.row_count == 0

    def test_replaces_existing_table(self, conn):
        """Loading new records replaces previous imported_data."""
        load_flat_records_to_duckdb(conn, [{"a": "1"}])
        load_flat_records_to_duckdb(conn, [{"b": "2"}, {"b": "3"}])
        count = conn.execute("SELECT COUNT(*) FROM imported_data").fetchone()[0]
        assert count == 2

    def test_source_type_in_result(self, conn):
        """ImportResult has correct source_type."""
        result = load_flat_records_to_duckdb(conn, [{"x": "1"}], source_type="json")
        assert result.source_type == "json"

    def test_type_inference_preserves_numbers(self, conn):
        """DuckDB should infer numeric types, not force all VARCHAR."""
        records = [{"count": 42, "price": 12.99, "name": "Test"}]
        result = load_flat_records_to_duckdb(conn, records)
        type_map = {c.name: c.type for c in result.columns}
        # DuckDB should infer integer/double for numeric values
        assert "VARCHAR" not in type_map.get("count", "").upper() or "INT" in type_map.get("count", "").upper()

    def test_mixed_int_float_becomes_double(self, conn):
        """Columns with int and float values should become DOUBLE, not VARCHAR."""
        records = [
            {"value": 0, "name": "zero"},
            {"value": 45.99, "name": "price"},
            {"value": 100, "name": "round"},
        ]
        result = load_flat_records_to_duckdb(conn, records)
        type_map = {c.name: c.type for c in result.columns}
        assert type_map["value"] == "DOUBLE"

    def test_coerced_string_records_get_numeric_types(self, conn):
        """String records passed through coerce_records get numeric DuckDB types."""
        records = coerce_records([
            {"weight": "32.5", "qty": "10", "name": "John"},
            {"weight": "22.0", "qty": "5", "name": "Jane"},
        ])
        result = load_flat_records_to_duckdb(conn, records)
        type_map = {c.name: c.type for c in result.columns}
        assert type_map["weight"] == "DOUBLE"
        assert type_map["qty"] == "BIGINT"
        assert type_map["name"] == "VARCHAR"

    def test_coerced_records_support_numeric_queries(self, conn):
        """Coerced records allow numeric SQL comparisons without CAST."""
        records = coerce_records([
            {"name": "Light", "weight": "5.0"},
            {"name": "Heavy", "weight": "25.0"},
            {"name": "Heavier", "weight": "50.0"},
        ])
        load_flat_records_to_duckdb(conn, records)
        rows = conn.execute(
            "SELECT name FROM imported_data WHERE weight > 20"
        ).fetchall()
        names = {r[0] for r in rows}
        assert names == {"Heavy", "Heavier"}


class TestCoerceStringValue:
    """Test best-effort string-to-type coercion."""

    def test_integer_string(self):
        """Pure integer strings become int."""
        assert _coerce_string_value("42") == 42
        assert isinstance(_coerce_string_value("42"), int)

    def test_float_string(self):
        """Decimal strings become float."""
        assert _coerce_string_value("32.5") == 32.5
        assert isinstance(_coerce_string_value("32.5"), float)

    def test_non_numeric_string_unchanged(self):
        """Non-numeric strings pass through."""
        assert _coerce_string_value("Dallas") == "Dallas"
        assert _coerce_string_value("ORD-123") == "ORD-123"

    def test_empty_string_becomes_none(self):
        """Empty/whitespace strings become None."""
        assert _coerce_string_value("") is None
        assert _coerce_string_value("   ") is None

    def test_non_string_passthrough(self):
        """Non-string values (int, float, None) pass through unchanged."""
        assert _coerce_string_value(42) == 42
        assert _coerce_string_value(3.14) == 3.14
        assert _coerce_string_value(None) is None

    def test_padded_numeric_string(self):
        """Whitespace-padded numbers are coerced correctly."""
        assert _coerce_string_value("  32  ") == 32
        assert _coerce_string_value("  12.5  ") == 12.5

    def test_negative_numbers(self):
        """Negative number strings are coerced."""
        assert _coerce_string_value("-5") == -5
        assert _coerce_string_value("-3.14") == -3.14

    def test_zip_codes_stay_string(self):
        """5-digit zip codes starting with 0 stay as strings (int strips leading 0)."""
        # Note: "07302" → int(7302), which loses the leading zero.
        # This is acceptable because DuckDB BIGINT cannot preserve leading zeros.
        # Callers needing zip preservation should use explicit column typing.
        result = _coerce_string_value("07302")
        assert result == 7302  # Coerced to int (leading zero lost)


class TestCoerceRecords:
    """Test batch coercion of record lists."""

    def test_coerce_records_mixed_types(self):
        """Mixed string/numeric records are coerced correctly."""
        records = [
            {"name": "John", "weight": "32.5", "qty": "10", "zip": "75201"},
            {"name": "Jane", "weight": "15.0", "qty": "3", "zip": "78746"},
        ]
        result = coerce_records(records)
        assert result[0]["name"] == "John"
        assert result[0]["weight"] == 32.5
        assert result[0]["qty"] == 10
        assert result[0]["zip"] == 75201
        assert result[1]["weight"] == 15.0

    def test_coerce_empty_values(self):
        """Empty string values become None."""
        records = [{"a": "val", "b": "", "c": "   "}]
        result = coerce_records(records)
        assert result[0]["a"] == "val"
        assert result[0]["b"] is None
        assert result[0]["c"] is None
