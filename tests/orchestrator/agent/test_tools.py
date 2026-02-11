"""Unit tests for src/orchestrator/agent/tools.py.

Tests verify:
- process_command_tool wraps NLMappingEngine correctly
- get_job_status_tool handles job queries
- list_tools_tool returns proper tool listing
- All tools return MCP-compliant response format
"""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from src.orchestrator.agent.tools import (
    process_command_tool,
    get_job_status_tool,
    list_tools_tool,
    get_orchestrator_tools,
    PROCESS_COMMAND_SCHEMA,
    GET_JOB_STATUS_SCHEMA,
    LIST_TOOLS_SCHEMA,
)


class TestProcessCommandTool:
    """Tests for process_command orchestrator tool."""

    @pytest.mark.asyncio
    async def test_returns_mcp_format(self):
        """Should return MCP-compliant response format."""
        result = await process_command_tool({
            "command": "Ship California orders",
            "source_schema": [{"name": "state", "type": "string"}]
        })

        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_response_is_json(self):
        """Response text should be valid JSON."""
        result = await process_command_tool({
            "command": "Ship California orders",
            "source_schema": [{"name": "state", "type": "string"}]
        })

        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert "command" in parsed

    @pytest.mark.asyncio
    async def test_includes_command_in_result(self):
        """Response should include the original command."""
        result = await process_command_tool({
            "command": "Ship California orders via Ground",
            "source_schema": [{"name": "state", "type": "string"}]
        })

        text = result["content"][0]["text"]
        parsed = json.loads(text)
        # Command should be in the result
        assert "command" in parsed

    @pytest.mark.asyncio
    async def test_handles_empty_schema(self):
        """Should handle empty source schema."""
        result = await process_command_tool({
            "command": "Ship all orders",
            "source_schema": []
        })

        assert "content" in result
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_handles_complex_schema(self):
        """Should handle complex source schema."""
        result = await process_command_tool({
            "command": "Ship California orders",
            "source_schema": [
                {"name": "recipient_name", "type": "string"},
                {"name": "address", "type": "string"},
                {"name": "city", "type": "string"},
                {"name": "state", "type": "string"},
                {"name": "zip", "type": "string"},
                {"name": "weight", "type": "float"},
            ]
        })

        assert "content" in result
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert isinstance(parsed, dict)

    def test_schema_has_required_fields(self):
        """Schema should define command and source_schema."""
        assert "command" in PROCESS_COMMAND_SCHEMA
        assert "source_schema" in PROCESS_COMMAND_SCHEMA

    def test_schema_has_only_required_fields(self):
        """Schema should only define command and source_schema."""
        assert len(PROCESS_COMMAND_SCHEMA) == 2
        assert "command" in PROCESS_COMMAND_SCHEMA
        assert "source_schema" in PROCESS_COMMAND_SCHEMA


class TestGetJobStatusTool:
    """Tests for get_job_status orchestrator tool."""

    @pytest.mark.asyncio
    async def test_requires_job_id(self):
        """Should return error if job_id missing."""
        result = await get_job_status_tool({})

        # Should return error
        assert "content" in result
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert "error" in parsed
        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_handles_nonexistent_job(self):
        """Should handle missing job gracefully."""
        result = await get_job_status_tool({
            "job_id": "00000000-0000-0000-0000-000000000000"
        })

        # Should return error, not crash
        assert "content" in result
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        # Either error or job not found message
        assert "error" in parsed or "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_handles_invalid_uuid(self):
        """Should handle invalid UUID format."""
        result = await get_job_status_tool({
            "job_id": "not-a-valid-uuid"
        })

        # Should return error
        assert "content" in result

    def test_schema_has_job_id(self):
        """Schema should require job_id."""
        assert "job_id" in GET_JOB_STATUS_SCHEMA


class TestListToolsTool:
    """Tests for list_tools orchestrator tool."""

    @pytest.mark.asyncio
    async def test_returns_all_namespaces(self):
        """Should return tools for all namespaces."""
        result = await list_tools_tool({})

        text = result["content"][0]["text"]
        tools = json.loads(text)

        assert "orchestrator" in tools
        assert "data" in tools
        assert "ups" in tools

    @pytest.mark.asyncio
    async def test_orchestrator_has_expected_tools(self):
        """Orchestrator namespace should have expected tools."""
        result = await list_tools_tool({})

        text = result["content"][0]["text"]
        tools = json.loads(text)
        tool_names = [t["name"] for t in tools["orchestrator"]]

        assert "process_command" in tool_names
        assert "get_job_status" in tool_names
        assert "list_tools" in tool_names

    @pytest.mark.asyncio
    async def test_filters_by_namespace(self):
        """Should filter tools by namespace."""
        result = await list_tools_tool({"namespace": "data"})

        text = result["content"][0]["text"]
        tools = json.loads(text)

        assert "data" in tools
        assert "ups" not in tools
        assert "orchestrator" not in tools

    @pytest.mark.asyncio
    async def test_errors_on_unknown_namespace(self):
        """Should return error for unknown namespace."""
        result = await list_tools_tool({"namespace": "unknown"})

        assert result.get("isError") is True
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_data_namespace_has_expected_tools(self):
        """Data namespace should have import/query tools."""
        result = await list_tools_tool({"namespace": "data"})

        text = result["content"][0]["text"]
        tools = json.loads(text)
        tool_names = [t["name"] for t in tools["data"]]

        assert "import_csv" in tool_names
        assert "get_schema" in tool_names
        assert "query_data" in tool_names
        assert "compute_checksums" in tool_names
        assert "verify_checksum" in tool_names

    @pytest.mark.asyncio
    async def test_ups_namespace_has_expected_tools(self):
        """UPS namespace should have shipping tools."""
        result = await list_tools_tool({"namespace": "ups"})

        text = result["content"][0]["text"]
        tools = json.loads(text)
        tool_names = [t["name"] for t in tools["ups"]]

        assert "rating_quote" in tool_names
        assert "rating_shop" in tool_names
        assert "shipping_create" in tool_names
        assert "shipping_void" in tool_names
        assert "address_validate" in tool_names

    @pytest.mark.asyncio
    async def test_each_tool_has_description(self):
        """Each tool in listing should have description."""
        result = await list_tools_tool({})

        text = result["content"][0]["text"]
        tools = json.loads(text)

        for namespace, tool_list in tools.items():
            for tool_info in tool_list:
                assert "name" in tool_info
                assert "description" in tool_info
                assert tool_info["description"]  # Not empty

    def test_schema_has_namespace(self):
        """Schema should have optional namespace filter."""
        assert "namespace" in LIST_TOOLS_SCHEMA


class TestGetOrchestratorTools:
    """Tests for get_orchestrator_tools factory."""

    def test_returns_list_of_dicts(self):
        """Should return list of tool definition dicts."""
        tools = get_orchestrator_tools()
        assert isinstance(tools, list)
        assert all(isinstance(t, dict) for t in tools)

    def test_includes_required_fields(self):
        """Each tool should have name, description, schema, function."""
        tools = get_orchestrator_tools()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "schema" in tool
            assert "function" in tool

    def test_includes_all_orchestrator_tools(self):
        """Should include process_command, get_job_status, list_tools."""
        tools = get_orchestrator_tools()
        names = [t["name"] for t in tools]

        assert "process_command" in names
        assert "get_job_status" in names
        assert "list_tools" in names

    def test_functions_are_callable(self):
        """Each tool function should be callable."""
        tools = get_orchestrator_tools()
        for tool in tools:
            assert callable(tool["function"])

    def test_descriptions_are_not_empty(self):
        """Each tool description should be non-empty."""
        tools = get_orchestrator_tools()
        for tool in tools:
            assert tool["description"]
            assert len(tool["description"]) > 10  # At least a short sentence

    def test_schemas_are_dicts(self):
        """Each tool schema should be a dict."""
        tools = get_orchestrator_tools()
        for tool in tools:
            assert isinstance(tool["schema"], dict)

    def test_returns_seven_tools(self):
        """Should return exactly 7 orchestrator tools (3 core + 4 batch)."""
        tools = get_orchestrator_tools()
        # 3 original: process_command, get_job_status, list_tools
        # 4 batch: batch_preview, batch_execute, batch_set_mode, batch_resume
        assert len(tools) == 7


class TestMCPResponseFormat:
    """Tests verifying all tools follow MCP response format."""

    @pytest.mark.asyncio
    async def test_process_command_has_content_array(self):
        """process_command should return content array."""
        result = await process_command_tool({
            "command": "Ship orders",
            "source_schema": []
        })

        assert "content" in result
        assert isinstance(result["content"], list)

    @pytest.mark.asyncio
    async def test_process_command_text_block(self):
        """process_command content should have text type block."""
        result = await process_command_tool({
            "command": "Ship orders",
            "source_schema": []
        })

        block = result["content"][0]
        assert block["type"] == "text"
        assert "text" in block

    @pytest.mark.asyncio
    async def test_get_job_status_error_has_is_error(self):
        """Error responses should have isError=True."""
        result = await get_job_status_tool({})

        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_list_tools_error_has_is_error(self):
        """Error responses should have isError=True."""
        result = await list_tools_tool({"namespace": "invalid"})

        assert result.get("isError") is True
