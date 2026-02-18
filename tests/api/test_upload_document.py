"""Tests for POST /conversations/{session_id}/upload-document endpoint.

Validates file format/size checks, attachment staging, and agent message
triggering.
"""

import io
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def _create_session() -> str:
    """Helper to create a conversation session and return its ID."""
    resp = client.post("/api/v1/conversations/")
    assert resp.status_code == 201
    return resp.json()["session_id"]


class TestUploadDocument:
    """Tests for the upload-document endpoint."""

    def test_upload_pdf_success(self):
        """Upload a valid PDF file successfully."""
        session_id = _create_session()
        file_content = b"%PDF-1.4 test content"
        files = {"file": ("invoice.pdf", io.BytesIO(file_content), "application/pdf")}
        data = {"document_type": "002"}

        with patch(
            "src.api.routes.conversations._process_agent_message",
            new_callable=AsyncMock,
        ):
            resp = client.post(
                f"/api/v1/conversations/{session_id}/upload-document",
                files=files,
                data=data,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["file_name"] == "invoice.pdf"
        assert body["file_format"] == "pdf"
        assert body["file_size_bytes"] == len(file_content)

    def test_upload_rejected_for_bad_extension(self):
        """Files with unsupported extensions are rejected."""
        session_id = _create_session()
        files = {"file": ("script.py", io.BytesIO(b"print('hi')"), "text/x-python")}
        data = {"document_type": "002"}

        resp = client.post(
            f"/api/v1/conversations/{session_id}/upload-document",
            files=files,
            data=data,
        )

        assert resp.status_code == 400
        assert "Unsupported file format" in resp.json()["detail"]

    def test_upload_rejected_for_oversized_file(self):
        """Files exceeding 10 MB are rejected."""
        session_id = _create_session()
        big_content = b"x" * (10 * 1024 * 1024 + 1)
        files = {"file": ("big.pdf", io.BytesIO(big_content), "application/pdf")}
        data = {"document_type": "002"}

        resp = client.post(
            f"/api/v1/conversations/{session_id}/upload-document",
            files=files,
            data=data,
        )

        assert resp.status_code == 400
        assert "10 MB" in resp.json()["detail"]

    def test_upload_404_for_missing_session(self):
        """Returns 404 for non-existent session."""
        files = {"file": ("doc.pdf", io.BytesIO(b"test"), "application/pdf")}
        data = {"document_type": "002"}

        resp = client.post(
            "/api/v1/conversations/nonexistent-session/upload-document",
            files=files,
            data=data,
        )

        assert resp.status_code == 404

    def test_upload_stages_attachment(self):
        """Uploaded file is staged in the attachment store."""
        session_id = _create_session()
        file_content = b"test pdf content"
        files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}
        data = {"document_type": "003", "notes": "For Canada shipment"}

        staged_data = {}

        def capture_stage(sid, d):
            staged_data["sid"] = sid
            staged_data["data"] = d

        with (
            patch(
                "src.api.routes.conversations._process_agent_message",
                new_callable=AsyncMock,
            ),
            patch(
                "src.services.attachment_store.stage",
                side_effect=capture_stage,
            ),
        ):
            resp = client.post(
                f"/api/v1/conversations/{session_id}/upload-document",
                files=files,
                data=data,
            )

        assert resp.status_code == 200
        assert staged_data["sid"] == session_id
        assert staged_data["data"]["file_name"] == "test.pdf"
        assert staged_data["data"]["file_format"] == "pdf"
        assert staged_data["data"]["document_type"] == "003"
        assert "file_content_base64" in staged_data["data"]
        assert staged_data["data"]["file_size_bytes"] == len(file_content)

    def test_upload_with_notes(self):
        """Notes are included in the agent message."""
        session_id = _create_session()
        files = {"file": ("doc.pdf", io.BytesIO(b"pdf"), "application/pdf")}
        data = {"document_type": "002", "notes": "Rush order"}

        agent_messages = []

        async def capture_message(sid, msg):
            agent_messages.append(msg)

        with patch(
            "src.api.routes.conversations._process_agent_message",
            side_effect=capture_message,
        ):
            resp = client.post(
                f"/api/v1/conversations/{session_id}/upload-document",
                files=files,
                data=data,
            )

        assert resp.status_code == 200
        assert len(agent_messages) == 1
        assert "Rush order" in agent_messages[0]
        assert "DOCUMENT_ATTACHED" in agent_messages[0]
        assert "Commercial Invoice" in agent_messages[0]

    def test_upload_various_allowed_formats(self):
        """Various allowed formats are accepted."""
        session_id = _create_session()

        for ext in [
            "bmp", "doc", "docx", "gif", "jpg", "pdf",
            "png", "rtf", "tif", "txt", "xls", "xlsx",
        ]:
            files = {"file": (f"file.{ext}", io.BytesIO(b"data"), "application/octet-stream")}
            data = {"document_type": "002"}

            with patch(
                "src.api.routes.conversations._process_agent_message",
                new_callable=AsyncMock,
            ):
                resp = client.post(
                    f"/api/v1/conversations/{session_id}/upload-document",
                    files=files,
                    data=data,
                )
            assert resp.status_code == 200, f"Format {ext} should be allowed"

    def test_upload_alias_extension_is_normalized(self):
        """Compatibility aliases normalize to UPS canonical formats."""
        session_id = _create_session()
        files = {"file": ("invoice.jpeg", io.BytesIO(b"img"), "image/jpeg")}
        data = {"document_type": "002"}

        with patch(
            "src.api.routes.conversations._process_agent_message",
            new_callable=AsyncMock,
        ):
            resp = client.post(
                f"/api/v1/conversations/{session_id}/upload-document",
                files=files,
                data=data,
            )

        assert resp.status_code == 200
        assert resp.json()["file_format"] == "jpg"
