"""Tests for filter enforcement hooks (deny raw SQL, validate filter_spec)."""

import base64
import hashlib
import hmac
import json
import os
import time
from unittest.mock import patch

import pytest

from src.orchestrator.agent.hooks import (
    deny_raw_sql_in_filter_tools,
    validate_filter_spec_on_pipeline,
    validate_intent_on_resolve,
)
from src.orchestrator.models.filter_spec import FilterGroup


def _is_denied(result: dict) -> bool:
    """Check if a hook result is a denial."""
    hook_output = result.get("hookSpecificOutput", {})
    return hook_output.get("permissionDecision") == "deny"


def _denial_reason(result: dict) -> str:
    """Extract the denial reason from a hook result."""
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


# -------------------------------------------------------------------------
# deny_raw_sql_in_filter_tools
# -------------------------------------------------------------------------

class TestDenyRawSqlInFilterTools:
    """Deny raw SQL keys in filter-related tool payloads."""

    @pytest.mark.anyio
    async def test_denies_where_clause_in_pipeline(self):
        """Denies where_clause key in ship_command_pipeline payload."""
        result = await deny_raw_sql_in_filter_tools(
            {"tool_name": "ship_command_pipeline", "tool_input": {"where_clause": "state='CA'"}},
            tool_use_id="test-1",
            context=None,
        )
        assert _is_denied(result)
        assert "where_clause" in _denial_reason(result).lower() or "raw SQL" in _denial_reason(result)

    @pytest.mark.anyio
    async def test_denies_sql_key_in_fetch_rows(self):
        """Denies sql key in fetch_rows payload."""
        result = await deny_raw_sql_in_filter_tools(
            {"tool_name": "fetch_rows", "tool_input": {"sql": "SELECT * FROM t"}},
            tool_use_id="test-2",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_top_level_query_key(self):
        """Denies top-level query key."""
        result = await deny_raw_sql_in_filter_tools(
            {"tool_name": "resolve_filter_intent", "tool_input": {"query": "DROP TABLE"}},
            tool_use_id="test-3",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_deeply_nested_where_clause(self):
        """Denies where_clause buried inside nested dicts."""
        result = await deny_raw_sql_in_filter_tools(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {
                    "filter_spec": {
                        "root": {
                            "conditions": [{"where_clause": "state='CA'"}]
                        }
                    }
                },
            },
            tool_use_id="test-3a",
            context=None,
        )
        assert _is_denied(result)
        assert "where_clause" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_denies_sql_in_list_of_dicts(self):
        """Denies banned key inside a list of dicts."""
        result = await deny_raw_sql_in_filter_tools(
            {
                "tool_name": "fetch_rows",
                "tool_input": {
                    "filters": [{"raw_sql": "1=1; DROP TABLE orders"}]
                },
            },
            tool_use_id="test-3b",
            context=None,
        )
        assert _is_denied(result)
        assert "raw_sql" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_allows_filter_spec(self):
        """Allows filter_spec key without denial."""
        result = await deny_raw_sql_in_filter_tools(
            {"tool_name": "ship_command_pipeline", "tool_input": {"filter_spec": {"root": {}}}},
            tool_use_id="test-4",
            context=None,
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_ignores_unrelated_tools(self):
        """Does NOT trigger for unrelated tools like create_job."""
        result = await deny_raw_sql_in_filter_tools(
            {"tool_name": "create_job", "tool_input": {"where_clause": "anything"}},
            tool_use_id="test-5",
            context=None,
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
        result = await validate_intent_on_resolve(
            {"tool_name": "resolve_filter_intent", "tool_input": {"intent": bad_intent}},
            tool_use_id="test-6",
            context=None,
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
        result = await validate_intent_on_resolve(
            {"tool_name": "resolve_filter_intent", "tool_input": {"intent": good_intent}},
            tool_use_id="test-7",
            context=None,
        )
        assert not _is_denied(result)


# -------------------------------------------------------------------------
# validate_filter_spec_on_pipeline
# -------------------------------------------------------------------------

_TEST_SECRET = "a" * 32


def _make_valid_token(
    schema_signature: str = "sig123",
    dict_version: str = "1.0.0",
    spec_hash: str = "abc",
    ttl: int = 600,
    resolution_status: str = "RESOLVED",
) -> str:
    """Create a valid HMAC-signed token for testing."""
    payload = {
        "schema_signature": schema_signature,
        "canonical_dict_version": dict_version,
        "resolved_spec_hash": spec_hash,
        "resolution_status": resolution_status,
        "expires_at": time.time() + ttl,
    }
    payload_json = json.dumps(payload, sort_keys=True)
    sig = hmac.new(_TEST_SECRET.encode(), payload_json.encode(), hashlib.sha256).hexdigest()
    payload["signature"] = sig
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


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
                {"column": "state", "operator": "eq", "operands": [{"type": "string", "value": "CA"}]},
            ],
        },
        "schema_signature": "sig123",
        "canonical_dict_version": "1.0.0",
    }


class TestValidateFilterSpecOnPipeline:
    """Validate filter_spec and Tier-B token on pipeline and fetch_rows."""

    @pytest.fixture(autouse=True)
    def _set_token_secret(self, monkeypatch):
        """Set FILTER_TOKEN_SECRET for token operations."""
        monkeypatch.setenv("FILTER_TOKEN_SECRET", _TEST_SECRET)

    @pytest.mark.anyio
    async def test_denies_tier_b_missing_token(self):
        """Denies pipeline with NEEDS_CONFIRMATION but no resolution_token."""
        spec = _filter_spec_with_confirmation()
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-8",
            context=None,
        )
        assert _is_denied(result)
        assert "token" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_denies_expired_token(self):
        """Denies pipeline with expired token."""
        spec = _filter_spec_with_confirmation()
        # Create a token that expired 100 seconds ago
        spec["resolution_token"] = _make_valid_token(ttl=-100)
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-9",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_tampered_signature(self):
        """Denies pipeline with tampered HMAC signature."""
        spec = _filter_spec_with_confirmation()
        token = _make_valid_token()
        # Tamper: decode, change signature, re-encode
        decoded = json.loads(base64.urlsafe_b64decode(token))
        decoded["signature"] = "tampered" + decoded["signature"][8:]
        spec["resolution_token"] = base64.urlsafe_b64encode(
            json.dumps(decoded).encode()
        ).decode()
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-10",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_spec_hash_mismatch(self):
        """Denies pipeline with token whose resolved_spec_hash doesn't match."""
        spec = _filter_spec_with_confirmation()
        spec["resolution_token"] = _make_valid_token(spec_hash="wrong_hash")
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-11",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_schema_signature_mismatch(self):
        """Denies pipeline with token whose schema_signature doesn't match."""
        spec = _filter_spec_with_confirmation()
        spec["resolution_token"] = _make_valid_token(schema_signature="different_sig")
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-12",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_dict_version_mismatch(self):
        """Denies pipeline with token whose dict_version doesn't match."""
        spec = _filter_spec_with_confirmation()
        spec["resolution_token"] = _make_valid_token(dict_version="0.0.0")
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-13",
            context=None,
        )
        assert _is_denied(result)

    @pytest.mark.anyio
    async def test_allows_valid_tier_b_token(self):
        """Allows pipeline with valid Tier-B token (all bindings match)."""
        spec = _filter_spec_with_confirmation()
        # Compute spec hash the same way the hook will — using FilterGroup.model_dump_json()
        # to match the serialization used by filter_resolver.py when generating the token.
        root_json = FilterGroup(**spec["root"]).model_dump_json()
        spec_hash = hashlib.sha256(root_json.encode()).hexdigest()
        spec["resolution_token"] = _make_valid_token(
            schema_signature="sig123",
            dict_version="1.0.0",
            spec_hash=spec_hash,
        )
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-14",
            context=None,
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_tier_a_without_token(self):
        """Denies pipeline with RESOLVED spec but no resolution_token."""
        spec = _filter_spec_resolved()
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-15",
            context=None,
        )
        assert _is_denied(result)
        assert "resolution_token" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_allows_tier_a_with_valid_token(self):
        """Allows pipeline with RESOLVED spec and valid token."""
        spec = _filter_spec_resolved()
        # Compute spec hash the same way the hook will — using FilterGroup.model_dump_json()
        root_json = FilterGroup(**spec["root"]).model_dump_json()
        spec_hash = hashlib.sha256(root_json.encode()).hexdigest()
        spec["resolution_token"] = _make_valid_token(
            schema_signature="sig123",
            dict_version="1.0.0",
            spec_hash=spec_hash,
        )
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-15b",
            context=None,
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_denies_needs_confirmation_token(self):
        """Denies pipeline with valid token that carries NEEDS_CONFIRMATION status."""
        spec = _filter_spec_with_confirmation()
        # Compute spec hash the same way the hook will — using FilterGroup.model_dump_json()
        root_json = FilterGroup(**spec["root"]).model_dump_json()
        spec_hash = hashlib.sha256(root_json.encode()).hexdigest()
        spec["resolution_token"] = _make_valid_token(
            schema_signature="sig123",
            dict_version="1.0.0",
            spec_hash=spec_hash,
            resolution_status="NEEDS_CONFIRMATION",
        )
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"filter_spec": spec},
            },
            tool_use_id="test-15c",
            context=None,
        )
        assert _is_denied(result)
        assert "needs_confirmation" in _denial_reason(result).lower()

    @pytest.mark.anyio
    async def test_ignores_unrelated_tools(self):
        """Does not fire for unrelated tools."""
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "create_job",
                "tool_input": {"filter_spec": {"status": "NEEDS_CONFIRMATION"}},
            },
            tool_use_id="test-16",
            context=None,
        )
        assert not _is_denied(result)

    @pytest.mark.anyio
    async def test_allows_all_rows(self):
        """Allows pipeline with all_rows=true and no filter_spec."""
        result = await validate_filter_spec_on_pipeline(
            {
                "tool_name": "ship_command_pipeline",
                "tool_input": {"all_rows": True},
            },
            tool_use_id="test-17",
            context=None,
        )
        assert not _is_denied(result)
