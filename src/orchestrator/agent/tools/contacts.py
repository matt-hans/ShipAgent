"""Contact book tool handlers for the orchestration agent.

Provides tools for @handle resolution, contact CRUD, and MRU tracking.
Contact tools are available in both batch and interactive modes.

C2 integration: resolve_contact returns order_data dict with ship_to_*
keys ready for UPSPayloadBuilder.

C3 integration: Batch @handle resolution happens in pipeline.py via
_resolve_row_handles helper that scans rows for @handle patterns and
bulk-resolves via ContactService.resolve_handles().
"""

from __future__ import annotations

import logging
from typing import Any

from src.orchestrator.agent.tools.core import (
    EventEmitterBridge,
    _emit_event,
    _err,
    _ok,
)

logger = logging.getLogger(__name__)


def _get_contact_service():
    """Get ContactService with DB session.

    Uses get_db_context for clean session management.
    """
    from src.db.connection import get_db_context
    from src.services.contact_service import ContactService

    # Create a context manager and enter it
    ctx = get_db_context()
    db = ctx.__enter__()
    return ContactService(db), ctx


async def resolve_contact_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Resolve an @handle to a contact record with order_data mapping.

    This is the primary contact resolution tool. It:
    1. Looks up exact handle matches
    2. Falls back to prefix search for autocomplete
    3. Returns order_data with ship_to_* keys for UPSPayloadBuilder
    4. Updates last_used_at for MRU ranking

    Args:
        args: Dict with handle (required), optional role (ship_to/shipper).
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with contact data and order_data on success.
    """
    handle = args.get("handle", "").strip().lstrip("@")
    role = args.get("role", "ship_to")

    if not handle:
        return _err("Missing required parameter: handle")

    if role not in ("ship_to", "shipper"):
        return _err(f"Invalid role: {role!r}. Must be 'ship_to' or 'shipper'.")

    svc, ctx = _get_contact_service()
    try:
        from src.services.contact_service import contact_to_order_data

        # Try exact match first
        contact = svc.get_by_handle(handle)
        if contact:
            # Touch last_used_at for MRU ranking (SOLID: ISP - separate from read)
            svc.touch_last_used(handle)

            order_data = contact_to_order_data(contact, role=role)

            result = {
                "found": True,
                "match_type": "exact",
                "contact": {
                    "id": contact.id,
                    "handle": contact.handle,
                    "display_name": contact.display_name,
                    "attention_name": contact.attention_name,
                    "company": contact.company,
                    "phone": contact.phone,
                    "email": contact.email,
                    "address_line_1": contact.address_line_1,
                    "address_line_2": contact.address_line_2,
                    "city": contact.city,
                    "state_province": contact.state_province,
                    "postal_code": contact.postal_code,
                    "country_code": contact.country_code,
                    "use_as_ship_to": contact.use_as_ship_to,
                    "use_as_shipper": contact.use_as_shipper,
                    "tags": contact.tag_list,
                },
                "order_data": order_data,
            }

            _emit_event("contact_resolved", result, bridge=bridge)
            return _ok(result)

        # No exact match - try prefix search for autocomplete
        candidates = svc.search_by_prefix(handle)
        if candidates:
            result = {
                "found": False,
                "match_type": "prefix",
                "candidates": [
                    {
                        "handle": c.handle,
                        "display_name": c.display_name,
                        "city": c.city,
                        "state_province": c.state_province,
                    }
                    for c in candidates[:10]  # Cap at 10
                ],
                "message": f"No exact match for '@{handle}'. Did you mean one of these?",
            }
            return _ok(result)

        # No matches at all
        return _ok({
            "found": False,
            "match_type": "none",
            "message": f"No contact found with handle '@{handle}'. "
                       f"Use save_contact to create a new contact.",
        })

    except Exception as e:
        logger.exception("Error in resolve_contact_tool")
        return _err(f"Error resolving contact: {e}")
    finally:
        ctx.__exit__(None, None, None)


async def save_contact_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Create or update a contact in the address book.

    If handle exists, updates fields. If not, creates new contact.
    Handle is auto-generated from display_name if omitted.

    Args:
        args: Contact fields (display_name, address_line_1, city, etc.).
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with created/updated contact data.
    """
    handle = args.get("handle")
    display_name = args.get("display_name", "").strip()

    if not display_name:
        return _err("Missing required parameter: display_name")

    svc, ctx = _get_contact_service()
    try:
        # Check if handle exists for update
        if handle:
            existing = svc.get_by_handle(handle)
            if existing:
                # Update existing contact
                update_fields = {
                    k: v for k, v in args.items()
                    if k not in ("handle",) and v is not None
                }
                if update_fields:
                    svc.update_contact(existing.id, **update_fields)

                _emit_event("contact_saved", {
                    "action": "updated",
                    "handle": existing.handle,
                    "display_name": existing.display_name,
                }, bridge=bridge)

                return _ok({
                    "action": "updated",
                    "handle": existing.handle,
                    "display_name": existing.display_name,
                    "message": f"Updated contact @{existing.handle}",
                })

        # Create new contact
        contact = svc.create_contact(
            handle=handle,
            display_name=args.get("display_name"),
            address_line_1=args.get("address_line_1", ""),
            city=args.get("city", ""),
            state_province=args.get("state_province", ""),
            postal_code=args.get("postal_code", ""),
            country_code=args.get("country_code", "US"),
            attention_name=args.get("attention_name"),
            company=args.get("company"),
            phone=args.get("phone"),
            email=args.get("email"),
            address_line_2=args.get("address_line_2"),
            use_as_ship_to=args.get("use_as_ship_to", True),
            use_as_shipper=args.get("use_as_shipper", False),
            use_as_third_party=args.get("use_as_third_party", False),
            tags=args.get("tags"),
            notes=args.get("notes"),
        )

        _emit_event("contact_saved", {
            "action": "created",
            "handle": contact.handle,
            "display_name": contact.display_name,
        }, bridge=bridge)

        return _ok({
            "action": "created",
            "handle": contact.handle,
            "display_name": contact.display_name,
            "message": f"Created contact @{contact.handle}",
        })

    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.exception("Error in save_contact_tool")
        return _err(f"Error saving contact: {e}")
    finally:
        ctx.__exit__(None, None, None)


async def list_contacts_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """List contacts with optional search filter.

    Args:
        args: Optional search string and limit.
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response with list of matching contacts.
    """
    search = args.get("search", "").strip() or None
    tag = args.get("tag", "").strip() or None
    limit = min(args.get("limit", 50), 100)  # Cap at 100

    svc, ctx = _get_contact_service()
    try:
        contacts = svc.list_contacts(search=search, tag=tag, limit=limit)

        result = {
            "contacts": [
                {
                    "handle": c.handle,
                    "display_name": c.display_name,
                    "city": c.city,
                    "state_province": c.state_province,
                    "country_code": c.country_code,
                    "use_as_ship_to": c.use_as_ship_to,
                    "use_as_shipper": c.use_as_shipper,
                    "tags": c.tag_list,
                }
                for c in contacts
            ],
            "total": len(contacts),
        }

        return _ok(result)

    except Exception as e:
        logger.exception("Error in list_contacts_tool")
        return _err(f"Error listing contacts: {e}")
    finally:
        ctx.__exit__(None, None, None)


async def delete_contact_tool(
    args: dict[str, Any],
    bridge: EventEmitterBridge | None = None,
) -> dict[str, Any]:
    """Delete a contact by handle.

    Args:
        args: Dict with handle (required).
        bridge: Event bridge for SSE emission.

    Returns:
        Tool response confirming deletion.
    """
    handle = args.get("handle", "").strip().lstrip("@")

    if not handle:
        return _err("Missing required parameter: handle")

    svc, ctx = _get_contact_service()
    try:
        contact = svc.get_by_handle(handle)
        if not contact:
            return _ok({
                "deleted": False,
                "message": f"No contact found with handle '@{handle}'",
            })

        svc.delete_contact(contact.id)

        _emit_event("contact_deleted", {
            "handle": handle,
            "display_name": contact.display_name,
        }, bridge=bridge)

        return _ok({
            "deleted": True,
            "handle": handle,
            "message": f"Deleted contact @{handle}",
        })

    except Exception as e:
        logger.exception("Error in delete_contact_tool")
        return _err(f"Error deleting contact: {e}")
    finally:
        ctx.__exit__(None, None, None)
