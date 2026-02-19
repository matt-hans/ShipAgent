# Feature Proposal: Contact Book with @mention Addressing

**Date:** 2026-02-19
**Status:** Proposal
**Priority:** P1 (Address Book)

---

## Overview

Enable users to save shipping contacts (recipients, shippers, third-party billing accounts) and reference them by @mention in the agent conversation. A command like:

```
Ship 5 boxes to @matt via UPS Ground
```

...would resolve `@matt` to the saved contact's full address and contact details — no re-entry required.

---

## Problem

Users repeatedly enter the same recipient addresses for recurring shipments (internal warehouses, frequent customers, branch offices). This is error-prone, slow, and creates noise in the agent conversation. There is currently no persistence layer for contact identities separate from order data.

---

## Proposed Solution

### Contact Book

A persistent contact directory stored in the ShipAgent SQLite database. Each contact holds the full set of fields the UPS payload builder expects for a ship-to or shipper address:

| Field | Notes |
|-------|-------|
| `handle` | Unique @mention slug (e.g. `matt`, `nyc-warehouse`) |
| `display_name` | Human-readable label |
| `company` | Optional company name |
| `attention_name` | Person's name |
| `phone` | Contact phone |
| `email` | Optional email |
| `address_line_1` | Street address |
| `address_line_2` | Suite/unit (optional) |
| `city` | City |
| `state_province` | State/province code |
| `postal_code` | ZIP/postal |
| `country_code` | ISO 2-letter (default `US`) |
| `tags` | Optional user-defined labels (e.g. `residential`, `warehouse`) |
| `created_at` | ISO8601 timestamp |
| `updated_at` | ISO8601 timestamp |

### @mention Resolution

The agent resolves `@<handle>` tokens in the user's message before building the shipment payload. Resolution produces a structured `ContactRecord` that maps directly to the `ShipTo` / `Shipper` objects in `UPSPayloadBuilder`.

**Resolution flow:**

```
User message → agent intent parsing
                     ↓
            @mention token detected
                     ↓
            resolve_contact tool called
                     ↓
            ContactRecord injected into shipment context
                     ↓
            preview_interactive_shipment / ship_command_pipeline proceeds
```

If a handle is not found, the agent asks the user whether to save a new contact or enter details manually.

---

## Architecture Fit

### New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `ContactBook` DB model | `src/db/models.py` | SQLAlchemy table for contacts |
| `ContactService` | `src/services/contact_service.py` | CRUD + fuzzy handle lookup |
| `resolve_contact` tool | `src/orchestrator/agent/tools/contacts.py` | Agent tool — resolves @handle to ContactRecord |
| `save_contact` tool | `src/orchestrator/agent/tools/contacts.py` | Agent tool — creates/updates a contact |
| `list_contacts` tool | `src/orchestrator/agent/tools/contacts.py` | Agent tool — lists saved contacts |
| Contact REST endpoints | `src/api/routes/contacts.py` | CRUD API for UI management |
| `ContactsPanel` | `frontend/src/components/sidebar/` | Sidebar panel for browsing/editing contacts |

### Integration Points

- **`UPSPayloadBuilder`** — accepts `ContactRecord` as a drop-in for `ShipTo` / `Shipper` fields; no changes to field mapping logic.
- **`system_prompt.py`** — injects a brief contact catalogue summary so the agent knows available handles without a tool call for common cases.
- **Interactive mode** — `preview_interactive_shipment` accepts pre-resolved contact fields; skips re-asking for known fields.
- **Batch mode** — `@handle` can appear in a data source column (e.g. a `recipient_handle` column); the pipeline tool resolves all handles before previewing.

---

## User-Facing Commands (Examples)

```
# Create a contact
Save @matt as Matt Hans, 123 Main St, San Francisco CA 94105, +1-415-555-0100

# Ship using a saved contact
Ship a 2lb package to @matt via UPS Ground

# List contacts
Show me my saved contacts

# Update a contact
Update @matt's phone to +1-415-555-0199

# Delete a contact
Remove @nyc-warehouse from my contacts
```

---

## Data Model (SQLite)

```sql
CREATE TABLE contacts (
    id          TEXT PRIMARY KEY,          -- UUID
    handle      TEXT UNIQUE NOT NULL,      -- @mention slug
    display_name TEXT NOT NULL,
    company     TEXT,
    attention_name TEXT,
    phone       TEXT,
    email       TEXT,
    address_line_1 TEXT NOT NULL,
    address_line_2 TEXT,
    city        TEXT NOT NULL,
    state_province TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country_code TEXT NOT NULL DEFAULT 'US',
    tags        TEXT,                      -- JSON array
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

---

## Out of Scope (This Proposal)

- Contact groups / distribution lists
- Address validation on save (deferred — can leverage existing `validate_address` UPS tool)
- Import contacts from CSV or external address books
- Shared contacts across users (single-user system today)

---

## Open Questions

1. Should handle resolution be case-insensitive? (`@Matt` == `@matt`) — likely yes.
2. Should a partial match (e.g. `@mat`) prompt the agent to clarify? — yes, list candidates.
3. Should the system prompt summarise all contacts on every message (cheap for small books) or only inject on @mention detection?
4. Do we allow a contact to be used as the **shipper** (return address) as well as the recipient?

---

## Roadmap Placement

This maps to the existing **P1 — Address Book** item in `CLAUDE.md`:

> **P1 — Address Book**: Persistent profiles, `resolve_address` tool. Not started.

This proposal refines that item with a concrete data model, tool surface, and @mention UX pattern.
