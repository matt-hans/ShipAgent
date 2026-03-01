"""Regression tests for conversation agent context rebuild/bootstrap behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ensure_agent_rebuilds_when_platform_context_changes():
    """Session agent should rebuild when platform prompt context hash changes."""
    from src.api.routes import conversations

    session = MagicMock()
    session.agent = None
    session.agent_source_hash = None
    session.session_id = "platform-context-session"
    session.interactive_shipping = False
    session.confirmed_resolutions = {}

    agent1 = AsyncMock()
    agent2 = AsyncMock()
    platforms_first = [
        {"platform_id": "shopify", "connection_status": "sync_ready", "is_active": True},
    ]
    platforms_second = [
        {
            "platform_id": "shopify",
            "connection_status": "synced",
            "is_active": True,
            "last_sync_row_count": 12,
        },
    ]

    with (
        patch(
            "src.services.conversation_handler._get_active_platform_summaries",
            side_effect=[platforms_first, platforms_second],
        ),
        patch(
            "src.services.conversation_handler._load_prior_conversation",
            return_value=None,
        ),
        patch(
            "src.orchestrator.agent.system_prompt.build_system_prompt",
            return_value="prompt",
        ),
        patch(
            "src.orchestrator.agent.client.OrchestrationAgent",
            side_effect=[agent1, agent2],
        ),
        patch("src.api.routes.conversations._resolve_agent_model", return_value=None),
    ):
        rebuilt_first = await conversations._ensure_agent(session, source_info=None)
        rebuilt_second = await conversations._ensure_agent(session, source_info=None)

    assert rebuilt_first is True
    assert rebuilt_second is True
    agent1.stop.assert_awaited_once()
    assert session.agent is agent2


@pytest.mark.asyncio
async def test_prewarm_resolves_source_with_platform_bootstrap():
    """Prewarm should use the bootstrap resolver instead of direct source lookup."""
    from src.api.routes import conversations

    session_id = "prewarm-bootstrap-session"
    conversations._session_manager.get_or_create_session(session_id)

    mock_source = MagicMock()
    mock_source.source_type = "shopify"
    mock_gw = AsyncMock()

    try:
        with (
            patch(
                "src.services.gateway_provider.get_data_gateway",
                new=AsyncMock(return_value=mock_gw),
            ),
            patch(
                "src.services.conversation_handler.resolve_source_info_with_platform_bootstrap",
                new=AsyncMock(return_value=mock_source),
            ) as mock_resolve,
            patch(
                "src.api.routes.conversations._ensure_agent",
                new=AsyncMock(return_value=True),
            ) as mock_ensure,
        ):
            await conversations._prewarm_session_agent(session_id)

        mock_resolve.assert_awaited_once_with(mock_gw)
        mock_ensure.assert_awaited_once()
    finally:
        conversations._session_manager.remove_session(session_id)
