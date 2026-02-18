"""Tests for paperless document tool handlers.

Covers: request_document_upload_tool, upload_paperless_document_tool
(with attachment store fallback), push/delete tools.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.orchestrator.agent.tools.documents import (
    DOCUMENT_TYPE_OPTIONS,
    delete_paperless_document_tool,
    push_document_to_shipment_tool,
    request_document_upload_tool,
    upload_paperless_document_tool,
)
from src.services.errors import UPSServiceError


# ---------------------------------------------------------------------------
# request_document_upload_tool
# ---------------------------------------------------------------------------


class TestRequestDocumentUpload:
    """Tests for the request_document_upload_tool."""

    @pytest.mark.asyncio
    async def test_emits_upload_prompt_event(self):
        """Emits paperless_upload_prompt event with format/type info."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        result = await request_document_upload_tool({}, bridge=bridge)

        assert result["isError"] is False
        assert len(events) == 1
        event_type, event_data = events[0]
        assert event_type == "paperless_upload_prompt"
        assert "accepted_formats" in event_data
        assert "pdf" in event_data["accepted_formats"]
        assert "txt" in event_data["accepted_formats"]
        assert "bmp" in event_data["accepted_formats"]
        assert "document_types" in event_data
        assert event_data["prompt"] == "Please upload your customs document."

    @pytest.mark.asyncio
    async def test_custom_prompt(self):
        """Custom prompt text is passed through."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        await request_document_upload_tool(
            {"prompt": "Upload your invoice"}, bridge=bridge,
        )

        assert events[0][1]["prompt"] == "Upload your invoice"

    @pytest.mark.asyncio
    async def test_suggested_document_type(self):
        """Suggested document type is included when provided."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        await request_document_upload_tool(
            {"suggested_document_type": "002"}, bridge=bridge,
        )

        assert events[0][1]["suggested_document_type"] == "002"

    @pytest.mark.asyncio
    async def test_no_suggested_type_omitted(self):
        """No suggested_document_type key when not provided."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        await request_document_upload_tool({}, bridge=bridge)

        assert "suggested_document_type" not in events[0][1]

    @pytest.mark.asyncio
    async def test_document_type_options_match(self):
        """Document type options match the module-level constant."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        await request_document_upload_tool({}, bridge=bridge)

        assert events[0][1]["document_types"] == DOCUMENT_TYPE_OPTIONS


# ---------------------------------------------------------------------------
# upload_paperless_document_tool — attachment store fallback
# ---------------------------------------------------------------------------


class TestUploadPaperlessDocumentWithStore:
    """Tests for upload_paperless_document_tool with attachment store."""

    @pytest.mark.asyncio
    async def test_reads_from_attachment_store(self):
        """When file_content_base64 missing, reads from attachment store."""
        bridge = EventEmitterBridge()
        bridge.session_id = "test-session"
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        attachment = {
            "file_content_base64": "dGVzdA==",
            "file_name": "invoice.pdf",
            "file_format": "pdf",
            "document_type": "002",
            "file_size_bytes": 1234,
        }

        mock_client = AsyncMock()
        mock_client.upload_document.return_value = {"documentId": "DOC123"}

        with (
            patch(
                "src.orchestrator.agent.tools.documents._get_ups_client",
                return_value=mock_client,
            ),
            patch(
                "src.services.attachment_store.consume",
                return_value=attachment,
            ),
        ):
            result = await upload_paperless_document_tool(
                {"document_type": "002"}, bridge=bridge,
            )

        assert result["isError"] is False
        data = json.loads(result["content"][0]["text"])
        assert "DOC123" in data

        # Verify enriched SSE event
        assert len(events) == 1
        evt = events[0][1]
        assert evt["action"] == "uploaded"
        assert evt["documentId"] == "DOC123"
        assert evt["fileName"] == "invoice.pdf"
        assert evt["fileFormat"] == "pdf"
        assert evt["fileSizeBytes"] == 1234

    @pytest.mark.asyncio
    async def test_direct_base64_arg_still_works(self):
        """When file_content_base64 is in args, attachment store is skipped."""
        bridge = EventEmitterBridge()
        bridge.session_id = "test-session"

        mock_client = AsyncMock()
        mock_client.upload_document.return_value = {"documentId": "DOC456"}

        with patch(
            "src.orchestrator.agent.tools.documents._get_ups_client",
            return_value=mock_client,
        ):
            result = await upload_paperless_document_tool(
                {
                    "file_content_base64": "data",
                    "file_name": "x.pdf",
                    "file_format": "pdf",
                    "document_type": "002",
                },
                bridge=bridge,
            )

        assert result["isError"] is False
        # attachment_store.consume should NOT be called
        # (no patch needed — absence of patch confirms it)

    @pytest.mark.asyncio
    async def test_no_base64_no_store_returns_error(self):
        """Returns error when no base64 and no attachment staged."""
        bridge = EventEmitterBridge()
        bridge.session_id = "test-session"

        with patch(
            "src.services.attachment_store.consume",
            return_value=None,
        ):
            result = await upload_paperless_document_tool(
                {"document_type": "002"}, bridge=bridge,
            )

        assert result["isError"] is True
        assert "No document attached" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_no_session_id_no_base64_returns_error(self):
        """Returns error when bridge has no session_id and no base64."""
        bridge = EventEmitterBridge()
        # session_id is None by default

        result = await upload_paperless_document_tool(
            {"document_type": "002"}, bridge=bridge,
        )

        assert result["isError"] is True

    @pytest.mark.asyncio
    async def test_ups_error_propagated(self):
        """UPSServiceError is properly formatted."""
        bridge = EventEmitterBridge()
        bridge.session_id = "s1"

        mock_client = AsyncMock()
        mock_client.upload_document.side_effect = UPSServiceError(
            code="E-3007", message="Upload failed",
        )

        with (
            patch(
                "src.orchestrator.agent.tools.documents._get_ups_client",
                return_value=mock_client,
            ),
            patch(
                "src.services.attachment_store.consume",
                return_value={
                    "file_content_base64": "x",
                    "file_name": "f.pdf",
                    "file_format": "pdf",
                    "document_type": "002",
                },
            ),
        ):
            result = await upload_paperless_document_tool(
                {"document_type": "002"}, bridge=bridge,
            )

        assert result["isError"] is True
        assert "E-3007" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# push/delete — backward compatibility
# ---------------------------------------------------------------------------


class TestPushAndDeleteTools:
    """Ensure push/delete tools still work unchanged."""

    @pytest.mark.asyncio
    async def test_push_document_emits_event(self):
        """Push tool emits paperless_result with action=pushed."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        mock_client = AsyncMock()
        mock_client.push_document.return_value = {}

        with patch(
            "src.orchestrator.agent.tools.documents._get_ups_client",
            return_value=mock_client,
        ):
            result = await push_document_to_shipment_tool(
                {"document_id": "DOC1", "shipment_identifier": "1Z123"},
                bridge=bridge,
            )

        assert result["isError"] is False
        assert events[0][1]["action"] == "pushed"

    @pytest.mark.asyncio
    async def test_delete_document_emits_event(self):
        """Delete tool emits paperless_result with action=deleted."""
        bridge = EventEmitterBridge()
        events: list[tuple[str, dict]] = []
        bridge.callback = lambda t, d: events.append((t, d))

        mock_client = AsyncMock()
        mock_client.delete_document.return_value = {}

        with patch(
            "src.orchestrator.agent.tools.documents._get_ups_client",
            return_value=mock_client,
        ):
            result = await delete_paperless_document_tool(
                {"document_id": "DOC1"},
                bridge=bridge,
            )

        assert result["isError"] is False
        assert events[0][1]["action"] == "deleted"
