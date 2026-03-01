"""Tests for session context persistence with Amazon source type.

Verifies that _persist_session_context correctly classifies Amazon sources
and persists the context with type='amazon'.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.api.routes.conversations import _persist_session_context

# ConversationPersistenceService is module-level import in conversations.py
_CPS_TARGET = "src.api.routes.conversations.ConversationPersistenceService"
# get_db_context is lazily imported inside the function body
_DB_CTX_TARGET = "src.db.connection.get_db_context"
# SavedDataSourceService is lazily imported inside the function body
_SDS_TARGET = "src.services.saved_data_source_service.SavedDataSourceService"


def _make_db_context_mock(mock_db: MagicMock):
    """Create a context manager mock for get_db_context."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestSessionContextAmazonType:
    """Verify Amazon source type is classified as 'amazon' in session context."""

    def test_amazon_source_type_persisted(self):
        """source_type='amazon' produces context with type='amazon'."""
        source_info = SimpleNamespace(
            source_type="amazon",
            file_path="",
            row_count=42,
        )

        mock_db = MagicMock()
        mock_svc = MagicMock()

        with patch(_DB_CTX_TARGET, return_value=_make_db_context_mock(mock_db)), \
             patch(_CPS_TARGET, return_value=mock_svc):
            _persist_session_context("sess-amazon-1", source_info)

        mock_svc.update_session_context.assert_called_once()
        call_args = mock_svc.update_session_context.call_args[0]
        assert call_args[0] == "sess-amazon-1"
        context = call_args[1]
        assert context["data_source"]["type"] == "amazon"
        assert context["data_source"]["source_type"] == "amazon"
        assert context["data_source"]["row_count"] == 42

    def test_shopify_source_type_unchanged(self):
        """source_type='shopify' still produces context with type='shopify'."""
        source_info = SimpleNamespace(
            source_type="shopify",
            file_path="",
            row_count=10,
        )

        mock_db = MagicMock()
        mock_svc = MagicMock()

        with patch(_DB_CTX_TARGET, return_value=_make_db_context_mock(mock_db)), \
             patch(_CPS_TARGET, return_value=mock_svc):
            _persist_session_context("sess-shopify-1", source_info)

        call_args = mock_svc.update_session_context.call_args[0]
        assert call_args[1]["data_source"]["type"] == "shopify"

    def test_csv_source_type_is_local(self):
        """source_type='csv' produces context with type='local'."""
        source_info = SimpleNamespace(
            source_type="csv",
            file_path="/tmp/orders.csv",
            row_count=100,
        )

        mock_db = MagicMock()
        mock_svc = MagicMock()
        mock_saved_svc = MagicMock()
        mock_saved_svc.list_sources.return_value = []

        with patch(_DB_CTX_TARGET, return_value=_make_db_context_mock(mock_db)), \
             patch(_CPS_TARGET, return_value=mock_svc), \
             patch(_SDS_TARGET, mock_saved_svc):
            _persist_session_context("sess-local-1", source_info)

        call_args = mock_svc.update_session_context.call_args[0]
        assert call_args[1]["data_source"]["type"] == "local"
