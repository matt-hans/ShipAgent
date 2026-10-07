"""Migrated filter-policy regressions: nested SQL, structure and reuse."""

import pytest

from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.services.policy_decision import PolicyDecision, PolicyDenialCode


async def _check(data: dict, *, tool_use_id: str) -> PolicyDecision:
    return await RuntimePolicyEngine(interactive_shipping=False).check_pre_tool(
        ProviderToolCall(
            call_id=tool_use_id,
            tool_name=data["tool_name"],
            parsed_input=data["tool_input"],
        )
    )


def _is_denied(result: PolicyDecision) -> bool:
    return not result.allowed


def _denial_reason(result: PolicyDecision) -> str:
    return result.reason


# -------------------------------------------------------------------------
# deny_raw_sql_in_filter_tools
# -------------------------------------------------------------------------


class TestDenyRawSqlInFilterTools:
    """Deny raw SQL keys in filter-related tool payloads."""

    @pytest.mark.anyio
    async def test_denies_where_clause_in_pipeline(self):
        """Denies where_clause key in ship_command_pipeline payload."""
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"where_clause": "state='CA'"},
            },
            tool_use_id="test-1",
        )
        assert _is_denied(result)
        assert "where_clause" in _denial_reason(
            result
        ).lower() or "raw SQL" in _denial_reason(result)

    @pytest.mark.anyio
    async def test_denies_sql_key_in_fetch_rows(self):
        """Denies sql key in fetch_rows payload."""
        result = await _check(
            {"tool_name": "fetch_rows", "tool_input": {"sql": "SELECT * FROM t"}},
            tool_use_id="test-2",
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_top_level_query_key(self):
        """Denies top-level query key."""
        result = await _check(
            {
                "tool_name": "resolve_filter_intent",
                "tool_input": {"query": "DROP TABLE"},
            },
            tool_use_id="test-3",
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_deeply_nested_where_clause(self):
        """Denies where_clause buried inside nested dicts."""
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {
                    "filter_spec": {
                        "root": {"conditions": [{"where_clause": "state='CA'"}]}
                    }
                },
            },
            tool_use_id="test-3a",
        )
        assert _is_denied(result)
        assert "where_clause" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_denies_sql_in_list_of_dicts(self):
        """Denies banned key inside a list of dicts."""
        result = await _check(
            {
                "tool_name": "fetch_rows",
                "tool_input": {"filters": [{"raw_sql": "1=1; DROP TABLE orders"}]},
            },
            tool_use_id="test-3b",
        )
        assert _is_denied(result)
        assert "raw_sql" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_allows_filter_spec(self):
        """Allows filter_spec key without denial."""
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": {"root": {}}},
            },
            tool_use_id="test-4",
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_ignores_unrelated_tools(self):
        """Does NOT trigger for unrelated tools like create_job."""
        result = await _check(
            {"tool_name": "create_job", "tool_input": {"where_clause": "anything"}},
            tool_use_id="test-5",
        )
        assert not _is_denied(result)


# -------------------------------------------------------------------------
# validate_intent_on_resolve
# -------------------------------------------------------------------------


class TestValidateIntentOnResolve:
    """Validate FilterIntent structure before resolution."""

    @pytest.mark.anyio
    async def test_denies_invalid_operator(self):
        """Denies intent with invalid operator."""
        bad_intent = {
            "root": {
                "logic": "AND",
                "conditions": [
                    {"column": "state", "operator": "EXPLODE", "operands": []}
                ],
            }
        }
        result = await _check(
            {
                "tool_name": "resolve_filter_intent",
                "tool_input": {"intent": bad_intent},
            },
            tool_use_id="test-6",
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_allows_valid_intent(self):
        """Allows valid intent structure."""
        good_intent = {
            "root": {
                "logic": "AND",
                "conditions": [
                    {
                        "column": "state",
                        "operator": "eq",
                        "operands": [{"type": "string", "value": "CA"}],
                    }
                ],
            }
        }
        result = await _check(
            {
                "tool_name": "resolve_filter_intent",
                "tool_input": {"intent": good_intent},
            },
            tool_use_id="test-7",
        )
        assert not _is_denied(result)


# -------------------------------------------------------------------------
# validate_filter_spec_on_pipeline
# -------------------------------------------------------------------------


def _filter_spec_with_confirmation() -> dict:
    """Build a filter_spec dict that looks like it needs Tier-B confirmation."""
    return {
        "status": "NEEDS_CONFIRMATION",
        "root": {"logic": "AND", "conditions": []},
        "schema_signature": "sig123",
        "canonical_dict_version": "1.0.0",
    }


def _filter_spec_resolved() -> dict:
    """Build a filter_spec dict that is fully resolved (Tier-A only)."""
    return {
        "status": "RESOLVED",
        "root": {
            "logic": "AND",
            "conditions": [
                {
                    "column": "state",
                    "operator": "eq",
                    "operands": [{"type": "string", "value": "CA"}],
                },
            ],
        },
        "schema_signature": "sig123",
        "canonical_dict_version": "1.0.0",
    }


class TestValidateFilterSpecOnPipeline:
    """Validate simplified filter_spec structural check on pipeline and fetch_rows.

    Structural policy decisions do not mint confirmation authority; trusted
    confirmation remains the workflow service's responsibility.
    """

    @pytest.mark.anyio
    async def test_allows_filter_spec_with_root(self):
        """Allows filter_spec with root field regardless of token."""
        spec = _filter_spec_with_confirmation()
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-8",
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_allows_resolved_spec_without_token(self):
        """Allows RESOLVED spec even without resolution_token (simplified)."""
        spec = _filter_spec_resolved()
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-9",
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_filter_spec_without_root(self):
        """Denies filter_spec missing root field."""
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": {"status": "RESOLVED"}},
            },
            tool_use_id="test-10",
        )
        assert _is_denied(result)
        assert result.code is PolicyDenialCode.INVALID_FILTER_STRUCTURE

    @pytest.mark.anyio
    async def test_allows_repeated_calls_same_spec(self):
        """Allows the same filter_spec to be used multiple times (no replay prevention)."""
        spec = _filter_spec_resolved()
        for i in range(3):
            result = await _check(
                {
                    "tool_name": "ship_command_pipeline",
                    "tool_input": {"filter_spec": spec},
                },
                tool_use_id=f"test-11-{i}",
            )
            assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_ignores_unrelated_tools(self):
        """Does not fire for unrelated tools."""
        result = await _check(
            {
                "tool_name": "create_job",
                "tool_input": {"filter_spec": {"status": "NEEDS_CONFIRMATION"}},
            },
            tool_use_id="test-16",
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_allows_all_rows(self):
        """Allows pipeline with all_rows=true and no filter_spec."""
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"all_rows": True},
            },
            tool_use_id="test-17",
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_allows_no_filter_spec(self):
        """Allows when no filter_spec present (pipeline uses cache)."""
        result = await _check(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"command": "ship all"},
            },
            tool_use_id="test-18",
        )
        assert not _is_denied(result)
