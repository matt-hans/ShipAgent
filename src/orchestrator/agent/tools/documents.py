"""Paperless document tool handlers for the orchestration agent.

Handles: request_document_upload, upload_paperless_document,
push_document_to_shipment, delete_paperless_document.
"""

from __future__ import annotations

import logging
from typing import Any

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _emit_event,
    _err,
    _get_ups_client,
    _ok,
)
from src.services.errors import UPSServiceError
from src.services.paperless_constants import UPS_PAPERLESS_UI_ACCEPTED_FORMATS

logger = logging.getLogger(__name__)

# Document type options exposed to the upload card UI.
DOCUMENT_TYPE_OPTIONS = [
    {"code": "002", "label": "Commercial Invoice"},
    {"code": "003", "label": "Certificate of Origin"},
    {"code": "004", "label": "NAFTA Certificate"},
    {"code": "005", "label": "Partial Invoice"},
    {"code": "006", "label": "Packing List"},
    {"code": "007", "label": "Customer Generated Forms"},
    {"code": "008", "label": "Air Freight Invoice"},
    {"code": "009", "label": "Proforma Invoice"},
    {"code": "010", "label": "SED"},
    {"code": "011", "label": "Weight Certificate"},
]


async def request_document_upload_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Emit an upload prompt for the user to attach a customs document.

    The frontend renders a PaperlessUploadCard with file picker, document
    type dropdown, and submit/cancel buttons.  The agent should call this
    instead of asking for file paths in chat.

    Args:
        args: Optional prompt text and suggested_document_type.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response confirming the upload form was displayed.
    """
    payload: dict[str, Any] = {
        "accepted_formats": list(UPS_PAPERLESS_UI_ACCEPTED_FORMATS),
        "document_types": DOCUMENT_TYPE_OPTIONS,
        "prompt": args.get("prompt", "Please upload your customs document."),
    }
    suggested = args.get("suggested_document_type")
    if suggested:
        payload["suggested_document_type"] = suggested

    _emit_event("paperless_upload_prompt", payload, bridge=bridge)
    return _ok("Upload form displayed to user. Waiting for file attachment.")


async def upload_paperless_document_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Upload a customs/trade document and emit paperless_result event.

    If ``file_content_base64`` is not in args (typical when the user
    attached a file via the upload card), the tool reads it from the
    session-scoped attachment store.

    Args:
        args: Dict with document_type (required).  file_content_base64,
              file_name, file_format are auto-loaded from attachment store
              when the user attached a file via the upload card.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with documentId on success, or error envelope.
    """
    # Only the user's form creates an upload grant. Model-provided bytes or
    # selected types can never authorize or overwrite that immutable attachment.
    from src.services.attachment_store import consume, has_pending

    attachment_id = args.get("attachment_id")
    attachment = None
    if (
        bridge
        and bridge.session_id
        and isinstance(attachment_id, str)
        and has_pending(bridge.session_id, attachment_id)
    ):
        try:
            client = await _get_ups_client()
        except Exception as exc:
            logger.warning(
                "Document upload connection failed exception_type=%s",
                type(exc).__name__,
            )
            return _err(
                "Document upload connection is unavailable. Try the upload form again."
            )
        attachment = consume(bridge.session_id, attachment_id, gateway=client)
    if attachment is None:
        return _err(
            "No document attached for this upload. Use request_document_upload "
            "so the user can approve the exact file and document type."
        )
    args = attachment

    # Capture metadata before passing to MCP (extra keys are filtered below)
    file_name = args.get("file_name", "")
    file_format = args.get("file_format", "")
    document_type = args.get("document_type", "")
    file_size_bytes = args.pop("file_size_bytes", None)

    try:
        result = await client.upload_document(**args)
        document_ids = result.get("documentIds", [])
        doc_id = str(result.get("documentId", "") or "")
        if not doc_id and isinstance(document_ids, list) and document_ids:
            doc_id = str(document_ids[0])

        if result.get("success") is not True or not doc_id:
            return _err(
                "Document upload outcome is unconfirmed. Check UPS Forms History before uploading again."
            )
        payload: dict[str, Any] = {
            "action": "uploaded",
            **result,
            "fileName": file_name,
            "fileFormat": file_format,
            "documentType": document_type,
        }
        payload.setdefault("success", True)
        if doc_id:
            payload["documentId"] = doc_id
        if file_size_bytes is not None:
            payload["fileSizeBytes"] = file_size_bytes

        _emit_event("paperless_result", payload, bridge=bridge)
        handle = bridge.workflow_actions.register_document(doc_id, client)
        return _ok({"success": True, "document_handle": handle})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.warning(
            "Unexpected error in upload_paperless_document_tool exception_type=%s",
            type(e).__name__,
        )
        return _err(
            "Document upload outcome is unconfirmed. Check UPS Forms History before uploading again."
        )


async def push_document_to_shipment_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Prepare a document attachment for explicit confirmation in the UI."""
    return await _prepare_document_action("push_document", args, bridge)


async def delete_paperless_document_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Prepare document deletion for explicit confirmation in the UI."""
    return await _prepare_document_action("delete_document", args, bridge)


async def _prepare_document_action(
    operation: str,
    args: dict[str, Any],
    bridge: EventEmitterBridge | None,
) -> dict[str, Any]:
    if bridge is None or not bridge.session_id:
        return _err("A conversation is required to confirm a document action.")
    bridge.workflow_actions.invalidate(operation)
    handle = args.get("document_handle")
    document_id = args.get("document_id")
    shipment = args.get("shipment_identifier")
    if handle and document_id:
        return _err("Choose either a document handle or an explicit document ID.")
    if (
        not isinstance(handle or document_id, str)
        or not (handle or document_id).strip()
    ):
        return _err("A document handle or document ID is required.")
    if operation == "push_document" and (
        not isinstance(shipment, str) or not shipment.strip()
    ):
        return _err("A shipment identifier is required.")
    try:
        client = await _get_ups_client()
        if handle:
            document_id = bridge.workflow_actions.resolve_document(handle, client)
    except Exception as exc:
        logger.warning(
            "Document preparation failed exception_type=%s", type(exc).__name__
        )
        return _err(
            "Document handle or carrier connection is unavailable. Request a new preview."
        )
    details = {"document_id": document_id.strip()}
    if operation == "push_document":
        details["shipment_identifier"] = shipment.strip()
    token = bridge.workflow_actions.prepare(operation, details, client)
    _emit_event(
        "paperless_result",
        {
            "action": "push_preview"
            if operation == "push_document"
            else "delete_preview",
            "status": "pending_confirmation",
            "success": True,
            "documentId": details["document_id"],
            "shipmentIdentifier": details.get("shipment_identifier"),
            "confirmation_token": token,
            "session_id": bridge.session_id,
        },
        bridge=bridge,
    )
    return _ok(
        "Document action preview displayed. Waiting for the user to confirm or cancel."
    )
