# Design: Contact Book, Custom Commands & Settings Panel

**Date:** 2026-02-19
**Status:** Approved
**Priority:** P1

---

## Overview

Four tightly related enhancements:

1. **Settings Flyout Panel** — Slide-out drawer housing all user preferences.
2. **Address Book** — Persistent contact directory with `@handle` mentions.
3. **Custom /Commands** — User-defined slash commands encoding shipping instructions.
4. **Syntax Highlighting** — `@address` and `/command` tokens coloured in the chat input.

---

## Decision Log

| # | Question | Decision |
|---|----------|----------|
| 1 | Flyout responsive behaviour | Overlay on small screens (<1024px), push/compress on large |
| 2 | Modal stacking | Flyout closes when Address Book modal opens |
| 3 | Contact name fields | Keep both `display_name` + `attention_name` for UPS fidelity |
| 4 | Batch @handle resolution | Bulk pre-resolve all unique handles before preview |
| 5 | System prompt contact injection | Top-20 MRU contacts in prompt, tool fallback for rest |
| 6 | /command expansion | Expand in input, user reviews/edits, then Enter to send (two-phase) |
| 7 | Rich input technique | Mirror div (hidden textarea + styled overlay) |
| 8 | Autocomplete selection | Insert token + trailing space |
| 9 | Command naming | Hyphens only: `[a-z0-9]+(-[a-z0-9]+)*` |
| 10 | CLI priority | Ship CLI in Phase A alongside backend |
| 11 | DB migrations | Auto-create at startup (match existing `Base.metadata.create_all()` pattern) |
| 12 | Handle auto-slug | Strip common business suffixes (LLC, Inc, Corp, Ltd, Co, GmbH, PLC) |

---

## 1. Data Model

### Contact Table

```python
class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    handle: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    attention_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state_province: Mapped[str] = mapped_column(String(50), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, server_default="US")
    use_as_ship_to: Mapped[bool] = mapped_column(nullable=False, server_default="1")
    use_as_shipper: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    use_as_third_party: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False, default=utc_now_iso)

    __table_args__ = (
        Index("idx_contacts_handle", "handle"),
        Index("idx_contacts_last_used_at", "last_used_at"),
        CheckConstraint(
            "handle GLOB '[a-z0-9]*' AND handle NOT GLOB '*[^a-z0-9-]*'",
            name="ck_contacts_handle_format",
        ),
    )

    @property
    def tag_list(self) -> list[str]:
        """Parse tags JSON string into a Python list."""
        if not self.tags:
            return []
        import json
        return json.loads(self.tags)

    @tag_list.setter
    def tag_list(self, value: list[str]) -> None:
        import json
        self.tags = json.dumps(value) if value else None
```

### CustomCommand Table

```python
class CustomCommand(Base):
    __tablename__ = "custom_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False, default=utc_now_iso)

    __table_args__ = (
        CheckConstraint(
            "name GLOB '[a-z0-9]*' AND name NOT GLOB '*[^a-z0-9-]*'",
            name="ck_commands_name_format",
        ),
    )
```

Both tables auto-created by `Base.metadata.create_all()` at startup.

---

## 2. Services

### ContactService (`src/services/contact_service.py`)

```
BUSINESS_SUFFIXES = {"llc", "inc", "corp", "corporation", "ltd", "co", "company", "plc", "gmbh"}
HANDLE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
```

Methods (no `db.commit()` inside — route commits):

| Method | Purpose |
|--------|---------|
| `create_contact(data)` | Validate handle uniqueness + format. Auto-slug from display_name if handle absent (strips business suffixes). |
| `get_by_handle(handle)` | Case-insensitive exact match (`func.lower()`). |
| `search_by_prefix(prefix)` | `LIKE prefix%` query. Returns candidate list. |
| `list_contacts(search?, tag?, limit, offset)` | Paginated, filterable list. |
| `update_contact(id, data)` | Partial update of non-null fields. |
| `delete_contact(id)` | Hard delete. |
| `touch_last_used(handle)` | Sets `last_used_at` to current ISO timestamp. |
| `get_mru_contacts(limit=20)` | Top-N by `last_used_at DESC`. For system prompt injection. |
| `resolve_handles(handles)` | Bulk resolve list of handles. Returns dict[handle, ContactRecord]. |

### CustomCommandService (`src/services/custom_command_service.py`)

Methods:

| Method | Purpose |
|--------|---------|
| `create_command(data)` | Validate name pattern `[a-z0-9]+(-[a-z0-9]+)*`. |
| `get_by_name(name)` | Exact match (stored without `/`). |
| `list_commands()` | All commands. |
| `update_command(id, data)` | Partial update. |
| `delete_command(id)` | Hard delete. |

---

## 3. REST Routes

### Contacts (`src/api/routes/contacts.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/contacts` | List with `?search=` and `?tag=` filters |
| `GET` | `/api/v1/contacts/by-handle/{handle}` | Resolve by handle (for frontend autocomplete + agent) |
| `POST` | `/api/v1/contacts` | Create |
| `PATCH` | `/api/v1/contacts/{id}` | Partial update |
| `DELETE` | `/api/v1/contacts/{id}` | Delete |

### Commands (`src/api/routes/commands.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/commands` | List all |
| `POST` | `/api/v1/commands` | Create |
| `PATCH` | `/api/v1/commands/{id}` | Partial update |
| `DELETE` | `/api/v1/commands/{id}` | Delete |

### Pydantic Schemas (in `src/api/schemas.py`)

```
ContactCreate, ContactUpdate, ContactResponse, ContactListResponse
CommandCreate, CommandUpdate, CommandResponse, CommandListResponse
```

---

## 4. Agent Tools

Four contact tools in `src/orchestrator/agent/tools/contacts.py`. **Always available** (both batch and interactive modes).

| Tool | Input | Behaviour |
|------|-------|-----------|
| `resolve_contact` | `handle: str` | Case-insensitive lookup. Exact → ContactRecord + use_as flags. Prefix → candidate list. Auto-calls `touch_last_used()` on success. |
| `save_contact` | All fields; `handle` optional (auto-slugs from `display_name`) | Create or update. Returns ContactRecord. |
| `list_contacts` | `search?: str`, `tag?: str` | Filtered list from DB. |
| `delete_contact` | `handle: str` | Hard delete by handle. |

Registered in `tools/__init__.py` via `get_all_tool_definitions()` — no mode gating.

---

## 5. System Prompt Integration

New `_build_contacts_section(contacts: list[dict])` helper in `system_prompt.py`:

```
MAX_PROMPT_CONTACTS = 20

Format:
## Saved Contacts
@handle — City, ST (ship_to|shipper|third_party)

When you see @handle in a user message, check the catalogue above first.
If found, use the contact data directly. If not found, call resolve_contact.
```

Called by `build_system_prompt()` with contacts from `ContactService.get_mru_contacts(limit=20)`.

---

## 6. Batch Mode @handle Resolution

When `ship_command_pipeline` detects `@handle` tokens in column values (e.g. a `recipient_handle` column), it calls `ContactService.resolve_handles(handles)` in bulk before preview. The resolved `ContactRecord` dict is cached and used per-row during payload building, avoiding N+1 queries.

Detection: scan all row values for the `@[a-z0-9-]+` pattern. Collect unique handles. Resolve in one query. Inject into row data before `UPSPayloadBuilder`.

---

## 7. Settings Flyout Panel

### Layout

Right-side drawer, 360px wide. CSS transition (`transform: translateX`) with `transition: transform 300ms ease`.

**Responsive:** At ≥1024px the flyout pushes the chat (chat width compresses). At <1024px the flyout overlays with a semi-transparent backdrop.

### Sections (collapsible accordion)

1. **Shipment Behaviour** — Relocated warning rows toggle (skip/process/ask)
2. **Address Book** — "Open Address Book" button → launches modal (flyout auto-closes)
3. **Custom Commands** — Inline list of saved commands with add/edit/delete. Expandable rows show body preview on click.

### Trigger

Settings gear icon in `Header.tsx` (right side, next to the interactive shipping toggle). Toggles `settingsFlyoutOpen` in AppState.

---

## 8. Address Book Modal

Opened from Settings flyout (flyout closes, modal takes over).

### List View

Compact table: Handle | Name | City | Actions (edit/delete). Search bar filters by handle/name/city. `?tag=` chip filter. "+ Add Contact" button top-right.

### Form (Add/Edit)

- **Handle** — `@` prefix shown visually, user types slug only. Auto-suggested from display_name (lowercase, hyphens, stripped business suffixes). Fully editable.
- **Display Name** — Required.
- **Attention Name** — Optional (UPS AttentionName override).
- **Company** — Optional (UPS CompanyName).
- **Address** — Street (required), Suite/Unit (optional), City (required), State (required), ZIP (required), Country (dropdown, default US; state becomes text input for non-US).
- **Contact** — Phone, Email (both optional).
- **Usage** — Checkboxes: Ship To (default on), Ship From, Third Party.
- **Tags** — Free-form chips (Enter/comma to add).
- **Notes** — Optional text area.

**Error handling:** Duplicate handle shows inline error on the handle field.

---

## 9. Custom Commands UI

### In Flyout

Inline list of saved commands. Each row shows `/command-name` and collapses/expands to show the body. Edit pencil and delete trash icons per row.

### New Command Editor

Inline form in the flyout:
- **Name** — typed without `/`, prefixed visually. Validated: `[a-z0-9]+(-[a-z0-9]+)*`.
- **Description** — Optional human note.
- **Body** — Multi-line textarea. `@handles` highlighted using the same tokeniser as the chat input.

---

## 10. Rich Chat Input (Syntax Highlighting)

### Mirror Div Technique

Hidden `<textarea>` handles all input (cursor, selection, paste, mobile keyboards). A positioned overlay `<div>` renders the same text with `<span>` elements for coloured tokens.

### Token Colours (OKLCH)

| Token | Colour | OKLCH |
|-------|--------|-------|
| `@handle` | Teal / seafoam | 185 (locator domain) |
| `/command` | Amber | 85 (paperless domain) |

### Validation States

| State | Visual |
|-------|--------|
| Matches saved handle/command | Coloured, slightly bold |
| Unknown token | Coloured, dashed underline |
| Incomplete (still typing) | Neutral (no colour until whitespace follows) |

### Autocomplete Popovers

- `useCommandAutocomplete` — triggered by `/` prefix. Reads from `customCommands` in AppState.
- `useContactAutocomplete` — triggered by `@` prefix. Reads from `contacts` in AppState.
- Arrow-key nav + Enter to select. Inserts token + trailing space.

### Command Expansion

Two-phase Enter:
1. User types `/send-to-matt` and presses Enter.
2. Input field replaces with the expanded body: "Ship to @matt via UPS 2nd Day Air".
3. User reviews/edits, then presses Enter again to submit.

---

## 11. CLI Sub-Commands

Following existing `data_source_app` pattern in `src/cli/main.py`.

### Contacts

```
shipagent contacts list
shipagent contacts add [--handle H] [--name N] [--address A] [--city C] [--state S] [--zip Z] [--phone P]
shipagent contacts show @handle
shipagent contacts edit @handle
shipagent contacts delete @handle [--yes]
shipagent contacts export --output contacts.json
shipagent contacts import contacts.json
```

Export/import JSON schema: array of contact objects matching ContactCreate schema (no `id`, `created_at`, `updated_at`).

### Commands

```
shipagent commands list
shipagent commands add --name NAME --body BODY [--description DESC]
shipagent commands show /name
shipagent commands edit /name
shipagent commands delete /name [--yes]
```

### Invoke

```
shipagent interact --command /name
```

Expands command body and submits as first message to REPL.

Delete operations prompt for Rich `Confirm.ask()` unless `--yes` flag is passed.

---

## 12. Frontend State & API Client

### AppState Additions

```typescript
contacts: Contact[]
setContacts: (contacts: Contact[]) => void
customCommands: CustomCommand[]
setCustomCommands: (commands: CustomCommand[]) => void
settingsFlyoutOpen: boolean
setSettingsFlyoutOpen: (open: boolean) => void
```

Hydrated via `useEffect` on mount: `GET /api/v1/contacts` and `GET /api/v1/commands`.

### API Client Functions (in `frontend/src/lib/api.ts`)

```
listContacts(search?, tag?) → ContactListResponse
createContact(data: ContactCreate) → ContactResponse
updateContact(id, data: ContactUpdate) → ContactResponse
deleteContact(id) → void
getContactByHandle(handle) → ContactResponse

listCommands() → CommandListResponse
createCommand(data: CommandCreate) → CommandResponse
updateCommand(id, data: CommandUpdate) → CommandResponse
deleteCommand(id) → void
```

### TypeScript Types (in `frontend/src/types/api.ts`)

```typescript
interface Contact {
    id: string; handle: string; display_name: string;
    attention_name?: string; company?: string;
    phone?: string; email?: string;
    address_line_1: string; address_line_2?: string;
    city: string; state_province: string;
    postal_code: string; country_code: string;
    use_as_ship_to: boolean; use_as_shipper: boolean;
    use_as_third_party: boolean;
    tags?: string[]; notes?: string;
    last_used_at?: string;
    created_at: string; updated_at: string;
}

interface CustomCommand {
    id: string; name: string; description?: string;
    body: string;
    created_at: string; updated_at: string;
}
```

---

## 13. New Frontend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `SettingsFlyout` | `components/settings/SettingsFlyout.tsx` | Slide-out drawer with accordion sections |
| `ShipmentBehaviourSection` | `components/settings/ShipmentBehaviourSection.tsx` | Relocated warning-rows toggle |
| `AddressBookSection` | `components/settings/AddressBookSection.tsx` | "Open Address Book" launcher |
| `CustomCommandsSection` | `components/settings/CustomCommandsSection.tsx` | Inline command list + editor |
| `AddressBookModal` | `components/settings/AddressBookModal.tsx` | Full contact list + search/filter |
| `ContactForm` | `components/settings/ContactForm.tsx` | Add/edit contact form |
| `RichChatInput` | `components/chat/RichChatInput.tsx` | Mirror-div tokenising input |
| `useTokenHighlighter` | `hooks/useTokenHighlighter.ts` | Parse input, classify tokens, return annotated segments |
| `useCommandAutocomplete` | `hooks/useCommandAutocomplete.ts` | `/` autocomplete from AppState |
| `useContactAutocomplete` | `hooks/useContactAutocomplete.ts` | `@` autocomplete from AppState |

---

## 14. Implementation Phases

| Phase | Scope | Test Strategy |
|-------|-------|---------------|
| **A** | DB models (Contact + CustomCommand), services, Pydantic schemas, REST routes, CLI sub-commands | Unit: service CRUD, auto-slug, handle validation. Integration: all REST endpoints. CLI: smoke tests. |
| **B** | Agent tools (4 contact tools), system prompt `_build_contacts_section()`, batch @handle pre-resolve | Tool invocation tests (exact, prefix, not-found, auto-touch). Prompt output + token cap. |
| **C** | Settings flyout, Address Book modal, frontend API client, TypeScript types, AppState hydration | Manual verification. |
| **D** | Custom commands UI in flyout, command expansion logic (two-phase Enter) | Manual verification. |
| **E** | RichChatInput (mirror div), token highlighting, autocomplete popovers | Manual verification. |

---

## 15. Files Changed Summary

### New Backend Files

- `src/services/contact_service.py`
- `src/services/custom_command_service.py`
- `src/api/routes/contacts.py`
- `src/api/routes/commands.py`
- `src/orchestrator/agent/tools/contacts.py`

### Modified Backend Files

- `src/db/models.py` — Add `Contact` + `CustomCommand` models
- `src/api/schemas.py` — Add request/response Pydantic schemas
- `src/api/main.py` — Register new routers
- `src/orchestrator/agent/tools/__init__.py` — Register contact tools
- `src/orchestrator/agent/system_prompt.py` — Add `_build_contacts_section()`
- `src/cli/main.py` — Add `contacts` + `commands` Typer sub-command groups

### New Frontend Files

- `frontend/src/components/settings/SettingsFlyout.tsx`
- `frontend/src/components/settings/ShipmentBehaviourSection.tsx`
- `frontend/src/components/settings/AddressBookSection.tsx`
- `frontend/src/components/settings/AddressBookModal.tsx`
- `frontend/src/components/settings/ContactForm.tsx`
- `frontend/src/components/settings/CustomCommandsSection.tsx`
- `frontend/src/components/chat/RichChatInput.tsx`
- `frontend/src/hooks/useTokenHighlighter.ts`
- `frontend/src/hooks/useCommandAutocomplete.ts`
- `frontend/src/hooks/useContactAutocomplete.ts`

### Modified Frontend Files

- `frontend/src/components/layout/Header.tsx` — Add settings gear button
- `frontend/src/components/CommandCenter.tsx` — Replace input with RichChatInput
- `frontend/src/hooks/useAppState.tsx` — Add contacts/commands/flyout state
- `frontend/src/lib/api.ts` — Add contact/command API functions
- `frontend/src/types/api.ts` — Add Contact/CustomCommand types
- `frontend/src/index.css` — Flyout CSS, token colours, new component styles

### New Test Files

- `tests/services/test_contact_service.py`
- `tests/services/test_custom_command_service.py`
- `tests/api/test_contacts_routes.py`
- `tests/api/test_commands_routes.py`
- `tests/orchestrator/agent/tools/test_contacts_tools.py`
- `tests/cli/test_contacts_cli.py`
- `tests/cli/test_commands_cli.py`

---

## Out of Scope

- Contact groups / distribution lists
- Address validation on save (post-MVP: leverage `validate_address` UPS tool)
- Import contacts from CSV or external address books (CLI JSON import covers power users)
- Shared contacts across users (single-user system)
- Command chaining (multiple /commands in sequence)
- Conditional logic / `{variable}` placeholders inside command bodies
