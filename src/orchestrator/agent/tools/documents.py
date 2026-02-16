"""Paperless document tool handlers for the orchestration agent.

Handles: upload_paperless_document, push_document_to_shipment,
delete_paperless_document.
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


async def upload_paperless_document_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Upload a customs/trade document and emit paperless_result event.

    Args:
        args: Dict with file_content_base64, file_name, file_format,
              document_type, and optional shipper_number.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with documentId on success, or error envelope.
    """
    try:
        client = await _get_ups_client()
        result = await client.upload_document(**args)
        doc_id = result.get("documentId", "")
        payload = {"action": "uploaded", "success": True, "documentId": doc_id}
        _emit_event("paperless_result", payload, bridge=bridge)
        return _ok({"success": True, "action": "uploaded", "documentId": doc_id})
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
        return _ok({"success": True, "action": "pushed"})
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
        return _ok({"success": True, "action": "deleted"})
    except UPSServiceError as e:
        return _err(f"[{e.code}] {e.message}")
    except Exception as e:
        logger.exception("Unexpected error in delete_paperless_document_tool")
        return _err(f"Unexpected error: {e}")
