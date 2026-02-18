"""Tests for confirm_filter_interpretation_tool token-binding semantics.

Covers: matched token → RESOLVED, mismatched token/intent → reject,
expired token → reject, invalid token → reject, dict version mismatch → reject.
"""

import base64
import hashlib
import hmac as hmac_mod
import json
import os
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator.agent.tools.core import EventEmitterBridge
from src.orchestrator.models.filter_spec import (
    FilterGroup,
    FilterIntent,
    FilterOperator,
    ResolutionStatus,
    SemanticReference,
    TypedLiteral,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_TOKEN_SECRET = "test-secret-for-confirmation-tests"
SCHEMA_SIG = "test_schema_sig_confirm"
SCHEMA_COLS = {"state", "company", "name", "weight"}
COL_TYPES = {
    "state": "VARCHAR",
    "company": "VARCHAR",
    "name": "VARCHAR",
    "weight": "DOUBLE",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_token_secret(monkeypatch):
    """Ensure FILTER_TOKEN_SECRET is set for all tests."""
    monkeypatch.setenv("FILTER_TOKEN_SECRET", TEST_TOKEN_SECRET)


@pytest.fixture()
def bridge() -> EventEmitterBridge:
    """Fresh bridge with empty confirmed_resolutions."""
    return EventEmitterBridge()


@pytest.fixture()
def mock_gateway():
    """Patch get_data_gateway to return a mock with source info."""
    gw = AsyncMock()
    gw.get_source_info.return_value = {
        "active": True,
        "source_type": "csv",
        "columns": [
            {"name": n, "type": t} for n, t in COL_TYPES.items()
        ],
        "signature": SCHEMA_SIG,
        "row_count": 100,
    }
    with patch(
        "src.orchestrator.agent.tools.data.get_data_gateway",
        return_value=gw,
    ):
        yield gw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _northeast_intent() -> dict[str, Any]:
    """FilterIntent with NORTHEAST semantic reference."""
    return FilterIntent(
        root=FilterGroup(
            logic="AND",
            conditions=[
                SemanticReference(semantic_key="NORTHEAST", target_column="state"),
            ],
        ),
        schema_signature=SCHEMA_SIG,
    ).model_dump()


def _business_recipient_intent() -> dict[str, Any]:
    """FilterIntent with BUSINESS_RECIPIENT semantic reference."""
    return FilterIntent(
        root=FilterGroup(
            logic="AND",
            conditions=[
                SemanticReference(
                    semantic_key="BUSINESS_RECIPIENT", target_column="company",
                ),
            ],
        ),
        schema_signature=SCHEMA_SIG,
    ).model_dump()


def _resolve_to_token(intent_raw: dict[str, Any]) -> str:
    """Resolve an intent and return the NEEDS_CONFIRMATION token."""
    from src.orchestrator.filter_resolver import resolve_filter_intent

    intent = FilterIntent(**intent_raw)
    result = resolve_filter_intent(
        intent=intent,
        schema_columns=SCHEMA_COLS,
        column_types=COL_TYPES,
        schema_signature=SCHEMA_SIG,
    )
    assert result.status == ResolutionStatus.NEEDS_CONFIRMATION, (
        f"Expected NEEDS_CONFIRMATION, got {result.status}"
    )
    assert result.resolution_token is not None
    return result.resolution_token


def _forge_expired_token(intent_raw: dict[str, Any]) -> str:
    """Generate a structurally valid but expired token for the intent."""
    from src.orchestrator.filter_resolver import resolve_filter_intent
    from src.services.filter_constants import CANONICAL_DICT_VERSION

    intent = FilterIntent(**intent_raw)
    result = resolve_filter_intent(
        intent=intent,
        schema_columns=SCHEMA_COLS,
        column_types=COL_TYPES,
        schema_signature=SCHEMA_SIG,
    )
    # Rebuild with expired timestamp
    spec_hash = hashlib.sha256(
        result.root.model_dump_json().encode()
    ).hexdigest()
    payload = {
        "schema_signature": SCHEMA_SIG,
        "canonical_dict_version": CANONICAL_DICT_VERSION,
        "resolved_spec_hash": spec_hash,
        "resolution_status": "NEEDS_CONFIRMATION",
        "expires_at": time.time() - 100,  # Already expired
    }
    payload_json = json.dumps(payload, sort_keys=True)
    sig = hmac_mod.new(
        TEST_TOKEN_SECRET.encode(), payload_json.encode(), hashlib.sha256,
    ).hexdigest()
    payload["signature"] = sig
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfirmFilterInterpretation:
    """Verify token-binding enforcement in confirm_filter_interpretation_tool."""

    @pytest.mark.asyncio
    async def test_matched_token_resolves_to_resolved(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """Valid token + matching intent → RESOLVED."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        intent_raw = _northeast_intent()
        token = _resolve_to_token(intent_raw)

        result = await confirm_filter_interpretation_tool(
            {"resolution_token": token, "intent": intent_raw},
            bridge=bridge,
        )

        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "RESOLVED"
        assert payload["resolution_token"] is not None
        # Confirmed spec stored in bridge cache
        assert len(bridge.confirmed_resolutions) == 1

    @pytest.mark.asyncio
    async def test_confirmation_turn_preserves_semantic_filter_command(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """Confirmation turns should not overwrite cached command with 'yes'."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        intent_raw = _northeast_intent()
        token = _resolve_to_token(intent_raw)
        bridge.last_user_message = "yes"
        bridge.last_shipping_command = "Process shipments for the northeast companies."
        bridge.last_resolved_filter_command = "ship northeast companies"

        result = await confirm_filter_interpretation_tool(
            {"resolution_token": token, "intent": intent_raw},
            bridge=bridge,
        )

        assert result["isError"] is False
        assert (
            bridge.last_resolved_filter_command
            == "Process shipments for the northeast companies."
        )

    @pytest.mark.asyncio
    async def test_mismatched_token_intent_rejected(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """NORTHEAST token + BUSINESS_RECIPIENT intent → reject."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        # Get token for NORTHEAST
        northeast_intent = _northeast_intent()
        northeast_token = _resolve_to_token(northeast_intent)

        # Try to use it with BUSINESS_RECIPIENT intent
        business_intent = _business_recipient_intent()

        result = await confirm_filter_interpretation_tool(
            {"resolution_token": northeast_token, "intent": business_intent},
            bridge=bridge,
        )

        assert result["isError"] is True
        error_text = result["content"][0]["text"]
        assert "mismatch" in error_text.lower()
        # Nothing stored in cache
        assert len(bridge.confirmed_resolutions) == 0

    @pytest.mark.asyncio
    async def test_expired_token_rejected(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """Expired token → reject with clear error."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        intent_raw = _northeast_intent()
        expired_token = _forge_expired_token(intent_raw)

        result = await confirm_filter_interpretation_tool(
            {"resolution_token": expired_token, "intent": intent_raw},
            bridge=bridge,
        )

        assert result["isError"] is True
        error_text = result["content"][0]["text"]
        assert "invalid" in error_text.lower() or "expired" in error_text.lower()

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """Garbage token → reject."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        result = await confirm_filter_interpretation_tool(
            {
                "resolution_token": "not-a-real-token",
                "intent": _northeast_intent(),
            },
            bridge=bridge,
        )

        assert result["isError"] is True

    @pytest.mark.asyncio
    async def test_resolved_token_rejected(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """A RESOLVED-status token cannot be used for confirmation."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )
        from src.orchestrator.filter_resolver import resolve_filter_intent

        # Create a Tier-A intent (auto-resolves to RESOLVED)
        tier_a_intent = FilterIntent(
            root=FilterGroup(
                logic="AND",
                conditions=[
                    SemanticReference(
                        semantic_key="california", target_column="state",
                    ),
                ],
            ),
            schema_signature=SCHEMA_SIG,
        )
        tier_a_result = resolve_filter_intent(
            intent=tier_a_intent,
            schema_columns=SCHEMA_COLS,
            column_types=COL_TYPES,
            schema_signature=SCHEMA_SIG,
        )
        assert tier_a_result.status == ResolutionStatus.RESOLVED
        assert tier_a_result.resolution_token is not None

        result = await confirm_filter_interpretation_tool(
            {
                "resolution_token": tier_a_result.resolution_token,
                "intent": tier_a_intent.model_dump(),
            },
            bridge=bridge,
        )

        assert result["isError"] is True
        error_text = result["content"][0]["text"]
        assert "NEEDS_CONFIRMATION" in error_text

    @pytest.mark.asyncio
    async def test_missing_bridge_rejected(self, mock_gateway) -> None:
        """No bridge → internal error."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        result = await confirm_filter_interpretation_tool(
            {
                "resolution_token": "any",
                "intent": _northeast_intent(),
            },
            bridge=None,
        )

        assert result["isError"] is True
        assert "bridge" in result["content"][0]["text"].lower()

    @pytest.mark.asyncio
    async def test_missing_args_rejected(
        self, bridge: EventEmitterBridge, mock_gateway,
    ) -> None:
        """Missing required args → error."""
        from src.orchestrator.agent.tools.data import (
            confirm_filter_interpretation_tool,
        )

        # Missing intent
        result = await confirm_filter_interpretation_tool(
            {"resolution_token": "token"},
            bridge=bridge,
        )
        assert result["isError"] is True

        # Missing token
        result = await confirm_filter_interpretation_tool(
            {"intent": _northeast_intent()},
            bridge=bridge,
        )
        assert result["isError"] is True
