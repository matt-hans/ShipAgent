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
        "accepted_formats": [
            "pdf", "doc", "docx", "xls", "xlsx",
            "jpg", "jpeg", "png", "tif", "gif",
        ],
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
    # If base64 missing, read from attachment store (upload card flow)
    if "file_content_base64" not in args and bridge and bridge.session_id:
        from src.services.attachment_store import consume

        attachment = consume(bridge.session_id)
        if attachment:
            args = {**args, **attachment}

    if "file_content_base64" not in args:
        return _err(
            "No document attached. Use request_document_upload first "
            "so the user can attach a file via the upload form."
        )

    # Capture metadata before passing to MCP (extra keys are filtered below)
    file_name = args.get("file_name", "")
    file_format = args.get("file_format", "")
    document_type = args.get("document_type", "")
    file_size_bytes = args.pop("file_size_bytes", None)

    try:
        client = await _get_ups_client()
        result = await client.upload_document(**args)
        doc_id = result.get("documentId", "")

        payload: dict[str, Any] = {
            "action": "uploaded",
            "success": True,
            "documentId": doc_id,
            "fileName": file_name,
            "fileFormat": file_format,
            "documentType": document_type,
        }
        if file_size_bytes is not None:
            payload["fileSizeBytes"] = file_size_bytes

        _emit_event("paperless_result", payload, bridge=bridge)
        return _ok(f"Document uploaded. ID: {doc_id}")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in upload_paperless_document_tool")
        return _err(f"Unexpected error: {e}")


async def push_document_to_shipment_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Attach a document to a shipment and emit paperless_result event.

    Args:
        args: Dict with document_id, shipment_identifier, and optional
              shipment_type, shipper_number.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with success status, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.push_document(**args)
        payload = {"action": "pushed", "success": True, **result}
        _emit_event("paperless_result", payload, bridge=bridge)
        return _ok("Document attached to shipment.")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in push_document_to_shipment_tool")
        return _err(f"Unexpected error: {e}")


async def delete_paperless_document_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Delete a document from UPS Forms History and emit paperless_result event.

    Args:
        args: Dict with document_id and optional shipper_number.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with success status, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.delete_document(**args)
        payload = {"action": "deleted", "success": True, **result}
        _emit_event("paperless_result", payload, bridge=bridge)
        return _ok("Document deleted.")
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in delete_paperless_document_tool")
        return _err(f"Unexpected error: {e}")
