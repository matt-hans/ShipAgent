import pytest

from src.services.conversation_runtime.tool_catalog import (
    SideEffectClass,
    ToolMode,
    WorkflowToolCatalog,
)

EXPECTED_BATCH_TOOLS = {
    "get_source_info",
    "get_schema",
    "ship_command_pipeline",
    "fetch_rows",
    "resolve_filter_intent",
    "confirm_filter_interpretation",
    "get_job_status",
    "batch_execute",
    "get_platform_status",
    "connect_shopify",
    "connect_amazon",
    "schedule_pickup",
    "cancel_pickup",
    "rate_pickup",
    "get_pickup_status",
    "find_locations",
    "get_service_center_facilities",
    "request_document_upload",
    "upload_paperless_document",
    "push_document_to_shipment",
    "delete_paperless_document",
    "resolve_contact",
    "save_contact",
    "list_contacts",
    "delete_contact",
    "track_package",
    "get_landed_cost",
}


EXPECTED_INTERACTIVE_TOOLS = {
    "get_job_status",
    "get_platform_status",
    "schedule_pickup",
    "cancel_pickup",
    "rate_pickup",
    "get_pickup_status",
    "find_locations",
    "get_service_center_facilities",
    "request_document_upload",
    "upload_paperless_document",
    "push_document_to_shipment",
    "delete_paperless_document",
    "resolve_contact",
    "save_contact",
    "list_contacts",
    "delete_contact",
    "track_package",
    "get_landed_cost",
    "preview_interactive_shipment",
}


def test_batch_catalog_exposes_current_batch_tool_names() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    assert {tool.name for tool in catalog.tools} == EXPECTED_BATCH_TOOLS


def test_interactive_catalog_exposes_current_interactive_tool_names() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=True)

    assert {tool.name for tool in catalog.tools} == EXPECTED_INTERACTIVE_TOOLS


def test_catalog_never_exposes_raw_ups_mcp_tools() -> None:
    for interactive_shipping in (False, True):
        catalog = WorkflowToolCatalog.for_mode(
            interactive_shipping=interactive_shipping,
        )

        assert all(
            not tool.name.startswith("mcp__ups__")
            for tool in catalog.tools
        )


def test_tool_declarations_have_provider_safe_shape() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    declarations = catalog.provider_declarations()
    fetch_rows = next(
        declaration
        for declaration in declarations
        if declaration.name == "fetch_rows"
    )

    assert fetch_rows.input_schema["type"] == "object"
    assert fetch_rows.projection_hints["model_result_projection"] == "strip_rows"


def test_side_effecting_tools_are_not_parallelizable() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    assert catalog.get("batch_execute").allow_parallel is False
    assert catalog.get("schedule_pickup").allow_parallel is False
    assert catalog.get("get_schema").allow_parallel is True
    assert catalog.get("get_job_status").mode in {ToolMode.BATCH, ToolMode.BOTH}


def test_confirmation_required_metadata_matches_pre_call_safety_gates() -> None:
    batch_catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)
    interactive_catalog = WorkflowToolCatalog.for_mode(interactive_shipping=True)

    assert batch_catalog.get("batch_execute").confirmation_required is True
    assert batch_catalog.get("schedule_pickup").confirmation_required is True
    assert batch_catalog.get("cancel_pickup").confirmation_required is True
    assert (
        interactive_catalog.get("preview_interactive_shipment").confirmation_required
        is False
    )


def test_resolve_contact_metadata_accounts_for_mru_state_update() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    resolve_contact = catalog.get("resolve_contact")

    assert resolve_contact.side_effect_class == SideEffectClass.STATE_CHANGING
    assert resolve_contact.retry_class == "none"


def test_artifact_event_metadata_matches_pickup_and_contact_handlers() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=False)

    assert "pickup_preview" in catalog.get("rate_pickup").artifact_events
    assert "pickup_preview" not in catalog.get("schedule_pickup").artifact_events
    assert "pickup_result" in catalog.get("schedule_pickup").artifact_events
    assert "pickup_result" in catalog.get("get_pickup_status").artifact_events
    assert "contact_resolved" in catalog.get("resolve_contact").artifact_events
    assert "contact_deleted" in catalog.get("delete_contact").artifact_events


def test_interactive_preview_metadata_declares_partial_and_ready_events() -> None:
    catalog = WorkflowToolCatalog.for_mode(interactive_shipping=True)

    artifact_events = catalog.get("preview_interactive_shipment").artifact_events

    assert "preview_partial" in artifact_events
    assert "preview_ready" in artifact_events


def test_catalog_fails_closed_for_unknown_tool_metadata(monkeypatch) -> None:
    async def _handler(args: dict[str, object]) -> dict[str, object]:
        return {}

    def _unknown_tool_definitions(*, event_bridge, interactive_shipping):
        return [
            {
                "name": "new_unclassified_tool",
                "description": "New tool missing explicit catalog metadata.",
                "input_schema": {"type": "object", "properties": {}},
                "handler": _handler,
            }
        ]

    monkeypatch.setattr(
        "src.services.conversation_runtime.tool_catalog.get_all_tool_definitions",
        _unknown_tool_definitions,
    )

    with pytest.raises(
        ValueError,
        match="Missing workflow tool metadata for 'new_unclassified_tool'",
    ):
        WorkflowToolCatalog.for_mode(interactive_shipping=False)
