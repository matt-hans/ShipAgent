"""Tests for JSON data source adapter."""

import json

import duckdb
import pytest

from src.mcp.data_source.adapters.json_adapter import JSONAdapter


@pytest.fixture()
def conn():
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def json_file(tmp_path):
    def _create(data, name="data.json"):
        p = tmp_path / name
        p.write_text(json.dumps(data))
        return str(p)
    return _create


class TestJSONAdapterFlat:
    """Test flat JSON array imports (Tier 1 — DuckDB native)."""

    def test_flat_array(self, conn, json_file):
        path = json_file([
            {"name": "John", "city": "Dallas"},
            {"name": "Jane", "city": "Austin"},
        ])
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        assert result.source_type == "json"

    def test_source_type(self):
        assert JSONAdapter().source_type == "json"


class TestJSONAdapterNested:
    """Test nested JSON imports (Tier 2 — Python flattening)."""

    def test_nested_objects_flattened(self, conn, json_file):
        path = json_file([
            {"orderId": "1", "shipTo": {"name": "John", "city": "Dallas"}},
            {"orderId": "2", "shipTo": {"name": "Jane", "city": "Austin"}},
        ])
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2
        col_names = [c.name for c in result.columns]
        assert "shipTo_name" in col_names
        assert "shipTo_city" in col_names

    def test_top_level_dict_with_array(self, conn, json_file):
        """Auto-discovers records inside a wrapper object."""
        path = json_file({
            "metadata": {"count": 2},
            "orders": [
                {"id": "1", "city": "Dallas"},
                {"id": "2", "city": "Austin"},
            ]
        })
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 2

    def test_explicit_record_path(self, conn, json_file):
        """record_path overrides auto-discovery."""
        path = json_file({
            "response": {"data": {"orders": [
                {"id": "1"}, {"id": "2"}, {"id": "3"}
            ]}}
        })
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path, record_path="response/data/orders")
        assert result.row_count == 3

    def test_single_dict_as_one_row(self, conn, json_file):
        """A single dict (no list) imports as 1 row."""
        path = json_file({"name": "John", "city": "Dallas"})
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1

    def test_items_array_preserved_as_json(self, conn, json_file):
        """Nested arrays become JSON string columns, not expanded rows."""
        path = json_file([
            {"orderId": "1", "items": [{"sku": "A"}, {"sku": "B"}]},
        ])
        adapter = JSONAdapter()
        result = adapter.import_data(conn, file_path=path)
        assert result.row_count == 1  # NOT 2 — items are serialized

    def test_file_not_found(self, conn):
        adapter = JSONAdapter()
        with pytest.raises(FileNotFoundError):
            adapter.import_data(conn, file_path="/nonexistent.json")

    def test_file_too_large(self, conn, tmp_path):
        """Files exceeding MAX_FILE_SIZE_BYTES are rejected."""
        path = tmp_path / "huge.json"
        path.write_text("[" + ",".join(['{"x":"y"}'] * 100) + "]")
        adapter = JSONAdapter()
        # Patch the constant for testing (avoid creating a real 50MB file)
        import src.mcp.data_source.adapters.json_adapter as mod
        original = mod.MAX_FILE_SIZE_BYTES
        mod.MAX_FILE_SIZE_BYTES = 10  # 10 bytes
        try:
            with pytest.raises(ValueError, match="exceeds"):
                adapter.import_data(conn, file_path=str(path))
        finally:
            mod.MAX_FILE_SIZE_BYTES = original


class TestJSONAdapterMetadata:
    """Test get_metadata returns correct info."""

    def test_metadata_after_import(self, conn, json_file):
        path = json_file([{"a": 1}, {"a": 2}])
        adapter = JSONAdapter()
        adapter.import_data(conn, file_path=path)
        meta = adapter.get_metadata(conn)
        assert meta["row_count"] == 2
        assert meta["column_count"] == 1
        assert meta["source_type"] == "json"

    def test_metadata_before_import(self, conn):
        adapter = JSONAdapter()
        meta = adapter.get_metadata(conn)
        assert "error" in meta
