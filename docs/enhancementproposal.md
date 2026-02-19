# Feature Proposal: Contact Book, Custom Commands & Settings Panel

**Date:** 2026-02-19
**Status:** Proposal (Enhanced)
**Priority:** P1 (Address Book + Settings Panel + Custom Commands)

---

## Overview

Three tightly related enhancements that together make ShipAgent dramatically faster and more personal to use:

1. **Settings Flyout Panel** — A slide-out panel that expands from the chat window housing all user preferences (replaces the current single-purpose warning-rows settings button).
2. **Address Book** — A persistent contact directory with a clean modal editor, accessible from the Settings panel and fully usable via `@handle` mentions in any chat message or custom command.
3. **Custom /Commands** — User-defined slash commands that encode shipping instructions (with embedded `@mentions`) and can be invoked anywhere in the chat, CLI, or batch pipeline.
4. **Syntax Highlighting in Chat Input** — `@address` and `/command` tokens are coloured distinctly in the input field as the user types, giving instant visual confirmation they will be resolved.

---

## 1. Settings Flyout Panel

### Problem

The current settings button surfaces a single option (handling of rows the system cannot rate or recognise). As functionality grows it needs a home that is always accessible, logically organised, and does not cover or obscure the conversation.

### Proposed UX

A **flyout drawer** anchored to the right side of the chat window. When opened it pushes the chat window to the left (compresses its width); when closed the chat window returns to full width. The flyout is divided into labelled sections, each collapsible.

```
┌─────────────────────────────────┬───────────────────────────┐
│                                 │  ⚙ Settings               │
│  [Chat conversation]            │  ─────────────────────    │
│  (compressed when flyout open)  │  ▾ Shipment Behaviour     │
│                                 │    Warning rows: [skip ▾] │
│                                 │                           │
│                                 │  ▾ Address Book           │
│                                 │    [Open Address Book →]  │
│                                 │                           │
│                                 │  ▾ Custom Commands        │
│                                 │    [+ New Command]        │
│                                 │    /daily-restock  [✏ 🗑] │
│                                 │    /send-to-matt   [✏ 🗑] │
└─────────────────────────────────┴───────────────────────────┘
```

### Flyout Sections

| Section | Contents |
|---------|----------|
| **Shipment Behaviour** | Warning rows toggle — skip / process / ask (existing functionality, relocated here) |
| **Address Book** | "Open Address Book" button that launches the Address Book modal |
| **Custom Commands** | Inline list of saved commands with add / edit / delete; preview of command body on hover |

### Frontend Changes

| File | Change |
|------|--------|
| `frontend/src/components/layout/Header.tsx` | Settings button opens flyout instead of inline popover |
| `frontend/src/components/settings/SettingsFlyout.tsx` | New flyout component (drawer with section accordion) |
| `frontend/src/components/settings/ShipmentBehaviourSection.tsx` | Relocated warning-rows setting |
| `frontend/src/components/settings/AddressBookSection.tsx` | Address Book launcher |
| `frontend/src/components/settings/CustomCommandsSection.tsx` | Custom commands list + inline add |
| `frontend/src/hooks/useAppState.tsx` | `settingsFlyoutOpen` boolean state |
| `frontend/src/index.css` | Flyout width, transition, chat-window compression CSS vars |

---

## 2. Address Book

### Problem

Users repeatedly type the same recipient addresses for recurring shipments (internal warehouses, frequent customers, branch offices). This is error-prone, slow, and creates noise in the conversation. There is no persistence layer for contact identities separate from order data.

### Address Book Modal

Opened from the Settings flyout. A clean, minimal dialog — not a full-page route — so the user can quickly add or edit a contact without leaving the conversation context.

#### Form Layout (simplified from carrier-grade address editors)

```
┌──────────────────────────────────────────────────────┐
│  Add Contact                                    [×]  │
│  ────────────────────────────────────────────────── │
│  Handle *          @  [matt               ]          │
│  Display Name *       [Matt Hans          ]          │
│                                                      │
│  ── Address ─────────────────────────────────────── │
│  Street *             [123 Main St        ]          │
│  Suite / Unit         [                   ]          │
│  City *               [San Francisco      ]          │
│  State *    [CA    ]  ZIP *   [94105   ]             │
│  Country              [United States ▾   ]           │
│                                                      │
│  ── Contact ─────────────────────────────────────── │
│  Phone                [+1-415-555-0100    ]          │
│  Email                [                   ]          │
│  Company              [                   ]          │
│                                                      │
│  ── Usage ───────────────────────────────────────── │
│  Use as    ☑ Ship To   ☑ Ship From   ☐ Third Party  │
│  Tags      [warehouse          ] [+ Add tag]         │
│                                                      │
│  Notes     [                   ]                     │
│                                                      │
│                        [Cancel]  [Save Contact]      │
└──────────────────────────────────────────────────────┘
```

**Design notes:**
- Handle field prefixes `@` visually — user types the slug only, no `@` prefix required.
- Handle is auto-suggested from Display Name (lowercased, hyphens for spaces) but fully editable.
- Country defaults to United States; state field becomes a text input for non-US countries.
- "Use as" checkboxes determine which UPS payload object the contact populates (Ship To, Shipper, or Third-Party billing reference).
- Tags are free-form chips (press Enter or comma to add).
- Notes field is optional, persisted but not sent to UPS.

#### Address Book List View

The Settings flyout shows an abbreviated list. A dedicated list view inside the modal shows all saved contacts in a compact table with search and filter:

```
┌──────────────────────────────────────────────────────────────┐
│  Address Book                          [+ Add Contact]  [×]  │
│  ─────────────────────────────────────────────────────────   │
│  🔍 Search contacts…                                         │
│                                                              │
│  Handle           Name              City          Actions    │
│  @matt            Matt Hans         San Francisco  ✏ 🗑      │
│  @nyc-warehouse   NYC Warehouse     New York       ✏ 🗑      │
│  @la-office       LA Office         Los Angeles    ✏ 🗑      │
│                                                              │
│  3 contacts                                                  │
└──────────────────────────────────────────────────────────────┘
```

### Data Model (SQLite)

```sql
CREATE TABLE contacts (
    id              TEXT PRIMARY KEY,          -- UUID
    handle          TEXT UNIQUE NOT NULL,      -- @mention slug (lowercase, hyphens)
    display_name    TEXT NOT NULL,
    company         TEXT,
    attention_name  TEXT,
    phone           TEXT,
    email           TEXT,
    address_line_1  TEXT NOT NULL,
    address_line_2  TEXT,
    city            TEXT NOT NULL,
    state_province  TEXT NOT NULL,
    postal_code     TEXT NOT NULL,
    country_code    TEXT NOT NULL DEFAULT 'US',
    use_as_ship_to  INTEGER NOT NULL DEFAULT 1, -- boolean
    use_as_shipper  INTEGER NOT NULL DEFAULT 0, -- boolean
    use_as_third_party INTEGER NOT NULL DEFAULT 0, -- boolean
    tags            TEXT,                       -- JSON array of strings
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

### @mention Resolution

The agent resolves `@<handle>` tokens in the user's message before building the shipment payload. Resolution produces a structured `ContactRecord` that maps directly into `UPSPayloadBuilder`.

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

**Resolution rules:**
- Handle lookup is case-insensitive (`@Matt` == `@matt`).
- Exact match resolves silently.
- Prefix match (e.g. `@mat`) returns candidates and asks user to pick.
- No match: agent asks whether to save a new contact or enter details manually.

### Backend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `Contact` DB model | `src/db/models.py` | SQLAlchemy ORM table |
| `ContactService` | `src/services/contact_service.py` | CRUD + fuzzy handle lookup |
| `resolve_contact` tool | `src/orchestrator/agent/tools/contacts.py` | Resolves `@handle` → `ContactRecord` |
| `save_contact` tool | `src/orchestrator/agent/tools/contacts.py` | Creates / updates a contact |
| `list_contacts` tool | `src/orchestrator/agent/tools/contacts.py` | Lists contacts (optionally filtered) |
| `delete_contact` tool | `src/orchestrator/agent/tools/contacts.py` | Deletes a contact by handle |
| `GET /contacts` | `src/api/routes/contacts.py` | List all contacts |
| `POST /contacts` | `src/api/routes/contacts.py` | Create contact |
| `PUT /contacts/{id}` | `src/api/routes/contacts.py` | Update contact |
| `DELETE /contacts/{id}` | `src/api/routes/contacts.py` | Delete contact |

### Integration Points

- **`UPSPayloadBuilder`** — accepts `ContactRecord` as a drop-in for `ShipTo`, `Shipper`, or third-party billing fields; no changes to field mapping logic.
- **`system_prompt.py`** — injects a compact contact catalogue (handle + city only) so the agent recognises `@handles` without a round-trip tool call.
- **Interactive mode** — `preview_interactive_shipment` accepts pre-resolved contact fields and skips re-asking for those fields.
- **Batch mode** — `@handle` can appear in a data source column (e.g. `recipient_handle`); the pipeline tool resolves all handles before previewing.
- **CLI** — All contact CRUD operations available via `shipagent contacts` sub-commands (see CLI section below).

### Agent-Facing Commands (Examples)

```
# Create a contact via conversation
Save @matt as Matt Hans, 123 Main St, San Francisco CA 94105, +1-415-555-0100

# Ship using a saved contact
Ship a 2lb package to @matt via UPS Ground

# Ship from a saved contact (use_as_shipper)
Ship from @la-office to @nyc-warehouse, 5lb box, UPS 2nd Day Air

# List contacts
Show me my saved contacts

# Update a contact
Update @matt's phone to +1-415-555-0199

# Delete a contact
Remove @nyc-warehouse from my contacts
```

### CLI Sub-Commands

```bash
# List all contacts
shipagent contacts list

# Add a contact interactively
shipagent contacts add

# Add from flags (for scripting)
shipagent contacts add --handle matt --name "Matt Hans" \
  --address "123 Main St" --city "San Francisco" --state CA --zip 94105 --phone "+14155550100"

# Show a contact
shipagent contacts show @matt

# Edit a contact
shipagent contacts edit @matt

# Delete a contact
shipagent contacts delete @matt

# Export all contacts to JSON
shipagent contacts export --output contacts.json

# Import contacts from JSON
shipagent contacts import contacts.json
```

---

## 3. Custom /Commands

### Overview

Custom /commands are user-defined slash commands that encode a full or partial shipping instruction — including embedded `@mentions`, service preferences, and any natural language directive. When invoked, the text is expanded in-place and submitted to the agent as if the user had typed it out in full.

### Examples

```
/daily-restock    →  "Ship 3 boxes of standard packaging to @nyc-warehouse via UPS Ground"
/send-to-matt     →  "Ship to @matt via UPS 2nd Day Air, signature required"
/intl-sample      →  "Ship 1 sample unit to @london-office via UPS Worldwide Expedited, declared value $50"
```

### Command Editor (in Settings Flyout)

A minimal inline editor — no modal required for simple cases:

```
┌─────────────────────────────────────────────────────┐
│  Custom Commands                    [+ New Command]  │
│  ──────────────────────────────────────────────────  │
│  /daily-restock                             [✏] [🗑] │
│    Ship 3 boxes to @nyc-warehouse via UPS Ground    │
│                                                      │
│  /send-to-matt                              [✏] [🗑] │
│    Ship to @matt via UPS 2nd Day Air                │
│                                                      │
│  ── New Command ──────────────────────────────────   │
│  Name      /[send-to-london       ]                  │
│  Instruction                                         │
│  ┌────────────────────────────────────────────────┐  │
│  │ Ship 1 unit to @london-office via UPS Worldwide│  │
│  └────────────────────────────────────────────────┘  │
│                          [Cancel]  [Save Command]    │
└─────────────────────────────────────────────────────┘
```

**Design notes:**
- Command name is typed without the `/`; it is prefixed visually and stored with it.
- Name must be lowercase, alphanumeric with hyphens, no spaces.
- Instruction body is a single multi-line text area — any natural language. `@handles` inside it are highlighted in real time (same tokeniser used in the main chat input).
- List rows expand on click to show the body; collapse again on click.
- Commands are stored per-user in SQLite and available in CLI immediately.

### Data Model (SQLite)

```sql
CREATE TABLE custom_commands (
    id           TEXT PRIMARY KEY,       -- UUID
    name         TEXT UNIQUE NOT NULL,   -- e.g. "daily-restock" (stored without /)
    description  TEXT,                   -- optional human note
    body         TEXT NOT NULL,          -- the full instruction text
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
```

### Invocation

The user types `/command-name` in the chat input. The frontend detects a confirmed /command token (on spacebar or Enter) and expands the body inline before submission. If the body contains `@handles`, those are resolved by the agent as normal.

**Resolution flow:**

```
User types /send-to-matt [Enter]
       ↓
Frontend expands: "Ship to @matt via UPS 2nd Day Air"
       ↓
Submitted to agent as expanded text
       ↓
Agent resolves @matt → ContactRecord → preview_interactive_shipment
```

**Slash-command autocomplete:** When the user types `/` in the input, a small popover lists all saved commands with their description. Arrow-key navigation + Enter to select.

```
  /d  →  ┌────────────────────────────────────────┐
         │  /daily-restock   Ship boxes to NYC    │
         │  /daily-summary   Get today's job list │
         └────────────────────────────────────────┘
```

### Backend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `CustomCommand` DB model | `src/db/models.py` | SQLAlchemy ORM table |
| `CustomCommandService` | `src/services/custom_command_service.py` | CRUD + name lookup |
| `GET /commands` | `src/api/routes/commands.py` | List all commands |
| `POST /commands` | `src/api/routes/commands.py` | Create command |
| `PUT /commands/{id}` | `src/api/routes/commands.py` | Update command |
| `DELETE /commands/{id}` | `src/api/routes/commands.py` | Delete command |

> Note: Custom /commands are resolved entirely on the frontend before submission. The agent does not need a dedicated tool for resolution — it receives the expanded text. The API routes exist solely for CRUD management from the Settings UI and CLI.

### CLI Sub-Commands

```bash
# List all commands
shipagent commands list

# Add a command
shipagent commands add --name daily-restock \
  --body "Ship 3 boxes to @nyc-warehouse via UPS Ground"

# Show a command's body
shipagent commands show /daily-restock

# Edit a command
shipagent commands edit /daily-restock

# Delete a command
shipagent commands delete /daily-restock

# Invoke a command directly from CLI
shipagent interact --command /daily-restock
```

---

## 4. Syntax Highlighting in Chat Input

### Overview

As the user types in the chat input field, `@address` and `/command` tokens are highlighted in distinct colours to give immediate visual feedback that they will be resolved — not treated as plain text.

### Token Colours

| Token type | Colour | Example |
|-----------|--------|---------|
| `@handle` | Teal / seafoam (OKLCH 185, matches locator domain) | `@matt` |
| `/command` | Amber (OKLCH 85, matches paperless domain) | `/send-to-matt` |

Both colours are drawn from the existing domain palette to maintain visual coherence.

### Implementation

The chat input (`CommandCenter.tsx`) currently uses a plain `<textarea>`. To support inline token colouring it must be replaced with a **contenteditable div** (or a thin wrapper using a technique like the "mirror div" trick) that applies `<span>` colouring to resolved tokens while preserving cursor behaviour and plain-text submission to the backend.

**Token detection regex:**
- `@handle`: `/\B@([a-z0-9-]+)/gi`
- `/command`: `/\B\/([a-z0-9-]+)/gi`

**Validation states:**

| State | Visual |
|-------|--------|
| Token matches a saved handle / command | Coloured, slightly bold |
| Token does not match (unknown) | Coloured but with a dashed underline |
| Token is being typed (incomplete) | Neutral — no colour until whitespace or punctuation follows |

### Frontend Changes

| File | Change |
|------|--------|
| `frontend/src/components/CommandCenter.tsx` | Replace `<textarea>` with tokenising rich-input component |
| `frontend/src/components/chat/RichChatInput.tsx` | New component — contenteditable with token spans |
| `frontend/src/hooks/useTokenHighlighter.ts` | Hook: parse input string, classify tokens, return annotated segments |
| `frontend/src/hooks/useCommandAutocomplete.ts` | Hook: detect `/` prefix, fetch matching commands, render popover |
| `frontend/src/hooks/useContactAutocomplete.ts` | Hook: detect `@` prefix, fetch matching contacts, render popover |
| `frontend/src/index.css` | Token colour CSS vars: `--token-address`, `--token-command` |

---

## Full Architecture Summary

### New Backend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `Contact` model | `src/db/models.py` | Contact book SQLAlchemy table |
| `CustomCommand` model | `src/db/models.py` | Custom commands SQLAlchemy table |
| `ContactService` | `src/services/contact_service.py` | Contact CRUD + fuzzy lookup |
| `CustomCommandService` | `src/services/custom_command_service.py` | Command CRUD + name lookup |
| Contact agent tools (4) | `src/orchestrator/agent/tools/contacts.py` | resolve, save, list, delete |
| `GET/POST/PUT/DELETE /contacts` | `src/api/routes/contacts.py` | Contact REST API |
| `GET/POST/PUT/DELETE /commands` | `src/api/routes/commands.py` | Command REST API |
| CLI `contacts` group | `src/cli/main.py` | Contact CRUD sub-commands |
| CLI `commands` group | `src/cli/main.py` | Command CRUD + invoke sub-commands |

### New Frontend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `SettingsFlyout` | `components/settings/` | Slide-out settings drawer |
| `ShipmentBehaviourSection` | `components/settings/` | Relocated warning-rows setting |
| `AddressBookSection` | `components/settings/` | Address Book launcher button |
| `AddressBookModal` | `components/settings/` | Contact list + add/edit dialog |
| `ContactForm` | `components/settings/` | Contact entry / edit form |
| `CustomCommandsSection` | `components/settings/` | Inline command list + editor |
| `RichChatInput` | `components/chat/` | Tokenising contenteditable input |
| `useTokenHighlighter` | `hooks/` | Token parsing + annotation hook |
| `useCommandAutocomplete` | `hooks/` | `/` autocomplete popover hook |
| `useContactAutocomplete` | `hooks/` | `@` autocomplete popover hook |

---

## Implementation Phases

| Phase | Scope | Notes |
|-------|-------|-------|
| **Phase A** | DB models + migrations + services + REST routes | Backend foundation; no agent integration yet |
| **Phase B** | Agent tools (resolve, save, list, delete contact) | Enables @mention in chat without UI |
| **Phase C** | Settings flyout + Address Book modal | UI for contacts; all existing settings migrated in |
| **Phase D** | Custom commands backend + Settings UI + CLI | Full command CRUD |
| **Phase E** | RichChatInput with token highlighting + autocomplete popovers | Final polish |

---

## Out of Scope (This Proposal)

- Contact groups / distribution lists
- Address validation on save (can leverage existing `validate_address` UPS tool post-MVP)
- Import contacts from CSV or external address books
- Shared contacts across users (single-user system today)
- Command chaining (running multiple /commands in sequence)
- Conditional logic inside command bodies

---

## Open Questions

1. **Handle case sensitivity** — Resolution is case-insensitive; storage is lowercase-normalised on save. (`@Matt` == `@matt` ✓)
2. **Partial match behaviour** — A prefix match (e.g. `@mat`) presents a candidate list; user selects or types further.
3. **System prompt injection** — Inject compact contact catalogue (handle + city + use_as flags) on every message; cheap for small books and avoids extra tool round-trip.
4. **Shipper contacts** — `use_as_shipper` flag on the contact record allows it to populate the Shipper object in the UPS payload. Default off.
5. **Command body as template** — For now, the body is a static string. A future enhancement could support `{variable}` placeholders for parameterised commands.
6. **CLI non-interactive `/command` invocation** — `shipagent interact --command /name` expands the body and submits it as the first message to the interactive REPL.

---

## Roadmap Placement

This supersedes the **P1 — Address Book** item in `CLAUDE.md`:

> **P1 — Address Book**: Persistent profiles, `resolve_address` tool. Not started.

The expanded scope covers: persistent address book, custom /commands, settings flyout consolidation, and rich chat input with token highlighting. All new capabilities integrate through existing agent tool and REST API patterns — no architectural changes required to the agent loop or MCP layer.
