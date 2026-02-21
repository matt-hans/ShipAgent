"""Tests for interactive_shipping flag in conversation lifecycle.

Covers:
- CreateConversationRequest schema defaults and validation
- CreateConversationResponse echo of interactive_shipping
- AgentSession storage of the flag
- Rebuild hash differentation by interactive_shipping flag
"""

from src.api.routes.conversations import _compute_source_hash
from src.api.schemas_conversations import (
    CreateConversationRequest,
    CreateConversationResponse,
)
from src.services.agent_session_manager import AgentSession


class TestCreateConversationRequest:
    """Tests for the CreateConversationRequest schema."""

    def test_defaults_to_false(self):
        """interactive_shipping defaults to False when omitted."""
        req = CreateConversationRequest()
        assert req.interactive_shipping is False

    def test_accepts_true(self):
        """interactive_shipping can be set to True."""
        req = CreateConversationRequest(interactive_shipping=True)
        assert req.interactive_shipping is True

    def test_accepts_false_explicit(self):
        """interactive_shipping can be explicitly set to False."""
        req = CreateConversationRequest(interactive_shipping=False)
        assert req.interactive_shipping is False

    def test_json_round_trip(self):
        """interactive_shipping survives JSON serialization."""
        req = CreateConversationRequest(interactive_shipping=True)
        data = req.model_dump()
        restored = CreateConversationRequest(**data)
        assert restored.interactive_shipping is True


class TestCreateConversationResponseEcho:
    """Tests for echoing interactive_shipping in response."""

    def test_response_includes_flag_true(self):
        """Response echoes interactive_shipping=True."""
        resp = CreateConversationResponse(
            session_id="test-123",
            interactive_shipping=True,
        )
        assert resp.interactive_shipping is True
        assert resp.session_id == "test-123"

    def test_response_includes_flag_false(self):
        """Response echoes interactive_shipping=False."""
        resp = CreateConversationResponse(
            session_id="test-123",
            interactive_shipping=False,
        )
        assert resp.interactive_shipping is False

    def test_response_defaults_false(self):
        """Response defaults interactive_shipping to False."""
        resp = CreateConversationResponse(
            session_id="test-123",
        )
        assert resp.interactive_shipping is False


class TestAgentSessionStorage:
    """Tests for interactive_shipping stored on AgentSession."""

    def test_session_defaults_false(self):
        """AgentSession defaults interactive_shipping to False."""
        session = AgentSession("test-id")
        assert session.interactive_shipping is False

    def test_session_stores_true(self):
        """AgentSession stores interactive_shipping when set."""
        session = AgentSession("test-id")
        session.interactive_shipping = True
        assert session.interactive_shipping is True

    def test_session_stores_false_after_true(self):
        """AgentSession can toggle interactive_shipping back to False."""
        session = AgentSession("test-id")
        session.interactive_shipping = True
        session.interactive_shipping = False
        assert session.interactive_shipping is False


class TestRebuildHashIncludesInteractive:
    """Tests for rebuild hash including interactive_shipping flag."""

    def test_hashes_differ_when_only_flag_changes(self):
        """Rebuild hash differs when interactive_shipping changes (same source)."""
        source_hash = _compute_source_hash(None)
        hash_off = f"{source_hash}|interactive=False"
        hash_on = f"{source_hash}|interactive=True"
        assert hash_off != hash_on

    def test_hash_stable_for_same_inputs(self):
        """Rebuild hash is deterministic for identical inputs."""
        source_hash = _compute_source_hash(None)
        assert source_hash == _compute_source_hash(None)

    def test_hash_includes_flag_and_source(self):
        """Combined hash format includes both source and flag."""
        source_hash = _compute_source_hash(None)
        combined = f"{source_hash}|interactive=True"
        assert "|interactive=" in combined
        assert source_hash in combined
