"""The local runtime catalog and the canonical public registry stay aligned.

Their scopes differ on purpose: the local catalog is the desktop conversation
toolset (names like ``rate_shipment``), the registry is the public provider
surface (``get_shipment_rates``). This pins the intentional correspondences so a
change on either side is a conscious decision, and the generated provider
artifacts are checked by ``tests/registry/test_artifact_drift.py``.
"""

from __future__ import annotations

import pytest

from src.registry.catalog import public_tools
from src.registry.models import SideEffectClass as CanonicalEffect
from src.services.conversation_runtime.tool_catalog import (
    SideEffectClass as LocalEffect,
)
from src.services.conversation_runtime.tool_catalog import WorkflowToolCatalog

# local runtime tool -> canonical public tool it deliberately mirrors
LOCAL_TO_CANONICAL = {
    "rate_shipment": "get_shipment_rates",
    "validate_address": "validate_shipment_address",
    "get_job_status": "get_job_status",
    "get_platform_status": "get_shipagent_status",
}
# Canonical public tools with no local read-only counterpart, and why.
PUBLIC_ONLY = {
    "submit_shipagent_task": "outer task admission must never be an inner model tool",
    "read_shipagent_run": "outer accepted-run status is owned by the durable facade",
    "cancel_shipagent_run": "outer cancellation authority is not an inner model tool",
    "prepare_shipments": "local equivalent is the preview pipeline, not a tool name",
    "execute_shipments": "local execution is confirmJob(), never a model tool",
    "create_label_download": "labels are served by the local API, not the model",
}


def _local() -> WorkflowToolCatalog:
    return WorkflowToolCatalog.for_mode(interactive_shipping=False)


@pytest.mark.parametrize(("local_name", "canonical_name"), LOCAL_TO_CANONICAL.items())
def test_mirrored_tools_exist_and_agree_on_safety(
    local_name: str, canonical_name: str
) -> None:
    local = _local().get(local_name)
    canonical = {tool.name: tool for tool in public_tools()}[canonical_name]

    assert local.side_effect_class == LocalEffect.READ_ONLY
    assert canonical.side_effect in {CanonicalEffect.read, CanonicalEffect.estimate}
    assert local.confirmation_required is False
    assert canonical.requires_confirmation is False


def test_every_public_tool_is_mirrored_or_explicitly_public_only() -> None:
    mirrored = set(LOCAL_TO_CANONICAL.values())

    unaccounted = {t.name for t in public_tools()} - mirrored - set(PUBLIC_ONLY)

    assert unaccounted == set()


def test_confirmation_gated_public_tools_have_no_same_named_local_tool() -> None:
    for tool in public_tools():
        if tool.requires_confirmation:
            assert not _local().has(tool.name)


def test_local_confirmation_gated_tools_are_never_read_only() -> None:
    for tool in _local().tools:
        if tool.confirmation_required:
            assert tool.side_effect_class != LocalEffect.READ_ONLY
