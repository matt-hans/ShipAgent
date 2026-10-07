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


@pytest.fixture(autouse=True)
def isolated_upload_gateway(test_db, monkeypatch):
    """The route binds an upload to a synthetic, fixture-owned connection."""
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setenv("AGENT_AUDIT_ENABLED", "false")
    monkeypatch.setattr(
        "src.db.connection.SessionLocal", sessionmaker(bind=test_db.bind)
    )
    monkeypatch.setattr(
        "src.services.gateway_provider.get_ups_gateway",
        AsyncMock(return_value=object()),
    )


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

        def capture_stage(sid, d, **kwargs):
            staged_data["sid"] = sid
            staged_data["data"] = d
            return "synthetic-attachment"

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

        async def capture_message(sid, msg, run_id=None, turn_id=None):
            assert isinstance(turn_id, str) and turn_id
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
        assert "document_type=002" in agent_messages[0]
        assert "doc.pdf" not in agent_messages[0]

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


def test_unknown_document_type_does_not_create_upload_grant():
    session_id = _create_session()
    response = client.post(
        f"/api/v1/conversations/{session_id}/upload-document",
        files={"file": ("test.pdf", b"synthetic")},
        data={"document_type": "UNKNOWN"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_session_ended_during_upload_cannot_recreate_grant(monkeypatch):
    import asyncio

    import httpx

    from src.api.routes import conversations
    from src.services import attachment_store

    session = conversations._session_manager.get_or_create_session("ending-upload")
    entered, release = asyncio.Event(), asyncio.Event()

    async def connect():
        entered.set()
        await release.wait()
        return object()

    monkeypatch.setattr("src.services.gateway_provider.get_ups_gateway", connect)
    scheduled = []
    monkeypatch.setattr(
        conversations, "_schedule_agent_message", lambda *a, **k: scheduled.append(a)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        task = asyncio.create_task(
            api.post(
                "/api/v1/conversations/ending-upload/upload-document",
                files={"file": ("test.pdf", b"synthetic")},
                data={"document_type": "002"},
            )
        )
        await entered.wait()
        session.terminating = True
        conversations._session_manager.remove_session(session.session_id)
        release.set()
        response = await task
    assert response.status_code == 409
    assert conversations._session_manager.get_session(session.session_id) is None
    assert attachment_store.consume(session.session_id) is None
    assert scheduled == []


@pytest.mark.asyncio
async def test_slower_older_upload_cannot_replace_newer_file(monkeypatch):
    import asyncio

    import httpx

    from src.api.routes import conversations
    from src.services import attachment_store

    sid = "reordered-uploads"
    conversations._session_manager.get_or_create_session(sid)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    gateway = object()

    async def connect():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return gateway

    monkeypatch.setattr("src.services.gateway_provider.get_ups_gateway", connect)
    monkeypatch.setattr(conversations, "_schedule_agent_message", lambda *a, **k: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        old = asyncio.create_task(
            api.post(
                f"/api/v1/conversations/{sid}/upload-document",
                files={"file": ("old.pdf", b"old")},
                data={"document_type": "002"},
            )
        )
        await entered.wait()
        new = await api.post(
            f"/api/v1/conversations/{sid}/upload-document",
            files={"file": ("new.pdf", b"new")},
            data={"document_type": "003"},
        )
        release.set()
        older = await old
    assert new.status_code == 200 and older.status_code == 409
    data = attachment_store.consume(sid, new.json()["attachment_id"], gateway=gateway)
    assert data["file_name"] == "new.pdf" and data["document_type"] == "003"
