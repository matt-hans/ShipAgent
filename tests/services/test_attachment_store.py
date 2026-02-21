"""Tests for session-keyed attachment store."""

from src.services.attachment_store import _store, clear, consume, stage


class TestAttachmentStore:
    """Tests for stage/consume/clear lifecycle."""

    def setup_method(self):
        """Clear the store before each test."""
        _store.clear()

    def test_stage_and_consume(self):
        """Stage data, then consume returns it and removes it."""
        data = {"file_content_base64": "abc", "file_name": "doc.pdf"}
        stage("session-1", data)
        result = consume("session-1")
        assert result == data
        # Consumed — second call returns None
        assert consume("session-1") is None

    def test_consume_empty(self):
        """Consume with no staged data returns None."""
        assert consume("nonexistent") is None

    def test_stage_overwrites(self):
        """Re-staging overwrites the previous attachment."""
        stage("s1", {"file_name": "first.pdf"})
        stage("s1", {"file_name": "second.pdf"})
        result = consume("s1")
        assert result is not None
        assert result["file_name"] == "second.pdf"

    def test_clear_removes_without_returning(self):
        """Clear removes staged data without returning it."""
        stage("s1", {"file_name": "x.pdf"})
        clear("s1")
        assert consume("s1") is None

    def test_clear_noop_when_empty(self):
        """Clear on non-existent session does not raise."""
        clear("nonexistent")  # Should not raise

    def test_multiple_sessions(self):
        """Independent sessions do not interfere."""
        stage("a", {"file_name": "a.pdf"})
        stage("b", {"file_name": "b.pdf"})
        assert consume("a")["file_name"] == "a.pdf"  # type: ignore[index]
        assert consume("b")["file_name"] == "b.pdf"  # type: ignore[index]
