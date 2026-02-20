"""Tests for conversation persistence Pydantic schemas."""

from src.api.schemas_conversations import (
    ChatSessionSummary,
    SessionDetailResponse,
    PersistedMessageResponse,
    UpdateTitleRequest,
)


def test_chat_session_summary_fields():
    s = ChatSessionSummary(
        id="abc",
        title="Test",
        mode="batch",
        created_at="2026-02-20T00:00:00Z",
        updated_at="2026-02-20T00:00:00Z",
        message_count=5,
    )
    assert s.id == "abc"
    assert s.message_count == 5


def test_persisted_message_response():
    m = PersistedMessageResponse(
        id="msg-1",
        role="user",
        message_type="text",
        content="hello",
        metadata=None,
        sequence=1,
        created_at="2026-02-20T00:00:00Z",
    )
    assert m.sequence == 1


def test_session_detail_response():
    r = SessionDetailResponse(
        session=ChatSessionSummary(
            id="s1", title=None, mode="interactive",
            created_at="2026-02-20T00:00:00Z",
            updated_at="2026-02-20T00:00:00Z", message_count=0,
        ),
        messages=[],
    )
    assert r.session.mode == "interactive"


def test_update_title_request():
    req = UpdateTitleRequest(title="New Title")
    assert req.title == "New Title"


def test_update_title_rejects_empty():
    import pytest as _pytest
    with _pytest.raises(Exception):
        UpdateTitleRequest(title="")
