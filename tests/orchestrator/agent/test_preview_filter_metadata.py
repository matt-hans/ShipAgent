"""Tests for _emit_preview_ready filter metadata passthrough."""

import json
from unittest.mock import MagicMock

from src.orchestrator.agent.tools.core import _emit_preview_ready


def _parse_tool_result(result: dict) -> tuple[bool, dict | str]:
    """Parse MCP tool response."""
    is_error = result.get("isError", False)
    content_list = result.get("content", [])
    if content_list and content_list[0].get("type") == "text":
        text = content_list[0]["text"]
        try:
            return is_error, json.loads(text)
        except json.JSONDecodeError:
            return is_error, text
    return is_error, {}


class TestPreviewFilterMetadata:
    """Verify _emit_preview_ready includes filter metadata when present."""

    def test_includes_filter_explanation(self):
        """filter_explanation passes through to slim LLM response."""
        result = {
            "job_id": "test-job",
            "total_rows": 5,
            "total_estimated_cost_cents": 5000,
            "filter_explanation": "state equals CA",
        }

        tool_result = _emit_preview_ready(result=result, rows_with_warnings=0)
        _, content = _parse_tool_result(tool_result)
        assert content["filter_explanation"] == "state equals CA"

    def test_includes_filter_audit(self):
        """filter_audit passes through to slim LLM response."""
        audit = {
            "spec_hash": "abc123",
            "compiled_hash": "def456",
            "schema_signature": "sig789",
            "dict_version": "1.0",
        }
        result = {
            "job_id": "test-job",
            "total_rows": 5,
            "total_estimated_cost_cents": 5000,
            "filter_audit": audit,
        }

        tool_result = _emit_preview_ready(result=result, rows_with_warnings=0)
        _, content = _parse_tool_result(tool_result)
        assert content["filter_audit"] == audit

    def test_includes_compiled_filter(self):
        """compiled_filter passes through to slim LLM response."""
        compiled = {
            "where_sql": '"state" = $1',
            "params": ["CA"],
        }
        result = {
            "job_id": "test-job",
            "total_rows": 5,
            "total_estimated_cost_cents": 5000,
            "compiled_filter": compiled,
        }

        tool_result = _emit_preview_ready(result=result, rows_with_warnings=0)
        _, content = _parse_tool_result(tool_result)
        assert content["compiled_filter"] == compiled

    def test_omits_filter_keys_when_absent(self):
        """Filter metadata keys are absent when not in result."""
        result = {
            "job_id": "test-job",
            "total_rows": 5,
            "total_estimated_cost_cents": 5000,
        }

        tool_result = _emit_preview_ready(result=result, rows_with_warnings=0)
        _, content = _parse_tool_result(tool_result)
        assert "filter_explanation" not in content
        assert "filter_audit" not in content
        assert "compiled_filter" not in content

    def test_sse_event_receives_filter_metadata(self):
        """SSE preview_ready event includes filter metadata."""
        captured = {}

        def capture_emit(event_type, data):
            captured.update(data)

        bridge = MagicMock()
        bridge.emit = capture_emit

        result = {
            "job_id": "test-job",
            "total_rows": 5,
            "total_estimated_cost_cents": 5000,
            "filter_explanation": "weight > 10",
            "filter_audit": {"spec_hash": "abc"},
        }

        _emit_preview_ready(result=result, rows_with_warnings=0, bridge=bridge)
        assert captured["filter_explanation"] == "weight > 10"
        assert captured["filter_audit"] == {"spec_hash": "abc"}
