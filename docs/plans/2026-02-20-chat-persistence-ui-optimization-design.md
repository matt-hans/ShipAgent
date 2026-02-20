# Chat Persistence & UI Optimization Design

**Date:** 2026-02-20
**Status:** Approved
**Scope:** Persistent conversation history, visual timeline minimap, copy/export, sidebar integration

---

## 1. Overview

Transition ShipAgent's chat from ephemeral in-memory sessions to database-backed persistent conversations. Users can switch between sessions, resume prior conversations with full agent context, export transcripts, and navigate long threads via a visual timeline.

### Key Decisions (from brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Resume depth | Full resume | Users need to continue complex multi-step workflows |
| Context restore | Best-effort | Try reconnect; degrade gracefully if source missing |
| Timeline scope | Same delivery | Ship all features together |
| History UI location | Existing sidebar | Unify navigation; no new flyout pattern |
| Title generation | Agent-generated (background Haiku) | Polished titles without polluting main conversation |
| Export format | JSON only | Structured, machine-readable, simple |
| Storage depth | Rendered messages only | Tool internals already in decision audit tables |
| New chat flow | Explicit button + auto-save | Clear signal for context switching |
| Architecture | DB + system prompt re-injection | Clean, leverages existing patterns, handles restarts |
| Persistence responsibility | Backend only | Frontend displays; backend persists before `done` event |

---

## 2. Database Schema

New tables in `src/db/models.py`, following existing `Mapped[type]` + `mapped_column` + ISO8601 conventions.

### Enums

```python
class MessageType(str, Enum):
    """Type classification for visual timeline rendering."""
    text = "text"                        # Plain user/assistant text
    system_artifact = "system_artifact"  # Preview, completion, domain cards
    error = "error"                      # Error messages
    tool_call = "tool_call"              # Tool call chips
```

### ConversationSession

```python
class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="batch")
    context_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default=utc_now_iso)
    updated_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    messages = relationship("ConversationMessage", back_populates="session",
                           cascade="all, delete-orphan", order_by="ConversationMessage.sequence")
```

### ConversationMessage

```python
class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MessageType.text.value
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default=utc_now_iso)

    session = relationship("ConversationSession", back_populates="messages")
```

### Indexes

- `(session_id, sequence)` — Ordered message retrieval
- `(session_id, message_type)` — Timeline queries
- `(is_active, updated_at)` — Sidebar session listing

### context_data JSON Structure

```json
{
  "data_source_id": "saved-source-uuid-or-null",
  "source_name": "Q3_Orders.csv",
  "source_type": "csv",
  "agent_source_hash": "abc123...",
  "filter_state": null
}
```

The `agent_source_hash` enables staleness detection on resume — if the hash changed, the data source was modified since the session was active.

---

## 3. Backend Services

### ConversationPersistenceService (`src/services/conversation_persistence_service.py`)

New service with these operations:

| Method | Purpose |
|--------|---------|
| `create_session(mode, context_data?)` | Insert new `ConversationSession` row |
| `save_message(session_id, role, content, message_type, metadata?)` | Append message with auto-incrementing sequence |
| `list_sessions(active_only=True)` | Lightweight list: id, title, mode, timestamps, message_count |
| `get_session_with_messages(session_id, limit?, offset?)` | Full hydration with pagination |
| `update_session_title(session_id, title)` | Set agent-generated title |
| `update_session_context(session_id, context_data)` | Snapshot context (on data source change) |
| `soft_delete_session(session_id)` | Set `is_active = False` |
| `export_session_json(session_id)` | Full session + messages as JSON dict |

### Title Generation Service

After the first assistant response is saved to DB, a background `asyncio.Task` fires:

1. Takes first user prompt + first assistant response text
2. Calls Claude Haiku with a minimal prompt: `"Generate a concise 3-6 word title for this shipping conversation: [user]: {prompt} [assistant]: {response}"`
3. Saves result via `update_session_title()`
4. Frontend polls or receives title update via next SSE keepalive cycle

This is a fire-and-forget background task — title appears asynchronously in the sidebar.

### Message Persistence Points (Backend-Owned)

**User messages:** Persisted in the `send_message` route handler (`POST /conversations/{id}/messages`) before dispatching to the agent. The frontend does NOT write messages.

**Assistant messages:** Persisted in `_process_agent_message()` after the agent finishes generating (after the response loop completes, before emitting the `done` SSE event). The accumulated text + detected message_type + metadata are saved as a single `ConversationMessage` row.

**Artifact messages:** When tool events emit artifacts (preview_ready, completion, pickup_preview, etc.), the artifact metadata is captured and saved as a separate `ConversationMessage` with `message_type = "system_artifact"` and the artifact payload in `metadata_json`.

**Error messages:** Exceptions in `_process_agent_message()` are saved with `message_type = "error"` before the error SSE event is emitted.

### Agent Resume Architecture

When a user loads a prior session and sends a new message:

1. `AgentSessionManager.get_or_create_session(session_id)` detects no in-memory session
2. Loads `ConversationSession` + messages from DB
3. Reads `mode` from session → creates agent with correct `interactive_shipping` flag
4. `build_system_prompt()` receives a new `prior_conversation` parameter — a formatted string of the message history:
   ```
   ## Prior Conversation (Resumed Session)
   You are resuming a prior conversation. Here is the history:

   [user]: Ship all orders from Q3_Orders.csv via UPS Ground
   [assistant]: I'll help with that. Let me check the data source...
   [user]: Only ship orders to California
   [assistant]: I'll filter for California addresses...
   ```
5. Best-effort context restore: parse `context_data` → check data source exists → reconnect or emit warning banner via SSE
6. Agent processes the new message with full conversational context

---

## 4. API Endpoints

### New Endpoints

| Method | Path | Request | Response |
|--------|------|---------|----------|
| `GET /conversations` | List active sessions | `?active_only=true` | `[{id, title, mode, created_at, updated_at, message_count}]` |
| `GET /conversations/{id}/messages` | Load history | `?limit=50&offset=0` | `{session: {...}, messages: [{id, role, message_type, content, metadata, sequence, created_at}]}` |
| `PATCH /conversations/{id}` | Update title | `{title: "..."}` | `{id, title}` |
| `DELETE /conversations/{id}` | Soft delete | — | `204 No Content` |
| `GET /conversations/{id}/export` | Export JSON | — | `application/json` download |

### Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| `POST /conversations/` | Create session | Also creates `ConversationSession` DB row |
| `POST /conversations/{id}/messages` | Send message | Persists user message to DB before dispatching |
| `DELETE /conversations/{id}` | Delete session | Soft-deletes DB row (was: in-memory only) |

---

## 5. Frontend Architecture

### State Changes (`useAppState.tsx`)

```typescript
// New state
chatSessions: ChatSessionSummary[];
setChatSessions: (sessions: ChatSessionSummary[]) => void;
chatSessionsVersion: number;        // Refresh trigger (like jobListVersion)
refreshChatSessions: () => void;    // Increment version counter
activeSessionTitle: string | null;
setActiveSessionTitle: (title: string | null) => void;

interface ChatSessionSummary {
  id: string;
  title: string | null;
  mode: "batch" | "interactive";
  created_at: string;
  updated_at: string | null;
  message_count: number;
}
```

### Hook Changes (`useConversation.ts`)

| Function | Change |
|----------|--------|
| `sendMessage()` | No change to persistence (backend handles it). Still creates session lazily. |
| `loadSession(sessionId)` | NEW. Fetches messages from `GET /conversations/{id}/messages`. Sets mode FIRST (prevents flicker), then populates `AppState.conversation`, connects SSE. |
| `reset()` | Modified: auto-saves implicitly (session already in DB). Disconnects SSE, clears events, increments epoch. Does NOT delete the session. |
| `startNewChat()` | NEW. Calls `reset()`, clears `AppState.conversation`, resets `conversationSessionId` to null. Shows WelcomeMessage. |

**Critical:** `loadSession()` must set `interactiveShipping` from the session's `mode` field BEFORE rendering messages to prevent UI mode flickering.

### API Client (`lib/api.ts`)

New functions:

```typescript
export async function listConversations(): Promise<ChatSessionSummary[]>
export async function getConversationMessages(id: string, limit?: number, offset?: number): Promise<SessionDetail>
export async function updateConversationTitle(id: string, title: string): Promise<void>
export async function deleteConversation(id: string): Promise<void>  // existing, now soft-delete
export async function exportConversation(id: string): Promise<Blob>
```

### TypeScript Types (`types/api.ts`)

```typescript
interface ChatSessionSummary {
  id: string;
  title: string | null;
  mode: "batch" | "interactive";
  created_at: string;
  updated_at: string | null;
  message_count: number;
}

interface SessionDetail {
  session: ChatSessionSummary;
  messages: PersistedMessage[];
}

interface PersistedMessage {
  id: string;
  role: "user" | "assistant" | "system";
  message_type: "text" | "system_artifact" | "error" | "tool_call";
  content: string;
  metadata: Record<string, unknown> | null;
  sequence: number;
  created_at: string;
}
```

---

## 6. Visual Components

### ChatSessionsPanel (`frontend/src/components/sidebar/ChatSessionsPanel.tsx`)

**Location:** Middle section of existing sidebar (between Data Source and Job History).

**Layout:**
- Header: "Chat Sessions" label + "New Chat" button (`btn-primary`, small)
- Collapsible with max-height and internal scrolling
- Session list grouped by: Today, Yesterday, Previous 7 Days, Older

**Session item:**
- Title text (or "New conversation..." muted if untitled)
- Mode badge: `badge-shipping` (batch) or small "Interactive" pill
- Relative timestamp ("2m ago", "Yesterday")
- Trash icon on hover (right side)
- Active session: left border accent in primary color

**Empty state:** "No conversations yet. Start typing to begin."

### ChatTimeline (`frontend/src/components/command-center/ChatTimeline.tsx`)

**Layout:** 16px gutter on right edge of chat scroll container. Thin 2px vertical line with color-coded dots.

**Dot colors (OKLCH):**
- Grey `oklch(0.7 0 0)`: User text (`message_type = "text"`, `role = "user"`)
- Cyan `oklch(0.75 0.15 195)`: Assistant text (`message_type = "text"`, `role = "assistant"`)
- Amber `oklch(0.8 0.15 85)`: Artifacts (`message_type = "system_artifact"`)
- Red `oklch(0.7 0.18 25)`: Errors (`message_type = "error"`)

**Behavior:**
- Dots positioned proportionally: `top = (message.sequence / totalMessages) * 100%`
- Single `IntersectionObserver` with `threshold: 0.5` tracks visible messages
- Visible message range highlighted with subtle glow/size increase on corresponding dots
- Click dot → `document.querySelector([data-message-id=...]).scrollIntoView({ behavior: 'smooth' })`
- Each rendered message element gets `data-message-id={message.id}` attribute

### CopyButton Enhancement (`messages.tsx`)

**Component:** `CopyButton` — appears on hover at top-right of message bubbles.

```tsx
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button onClick={handleCopy} className="opacity-0 group-hover:opacity-100 transition-opacity">
      {copied ? <CheckIcon /> : <CopyIcon />}
    </button>
  );
}
```

**Scope:** User messages and assistant text messages only. Artifact cards (PreviewCard, CompletionArtifact, etc.) do not get copy buttons.

### Export Button

**Location:** Inside the ChatSessionsPanel, per-session action (alongside trash). Small download icon.

**Behavior:** Calls `GET /conversations/{id}/export` → triggers browser file download as `{title}-{date}.json`.

---

## 7. Data Flow Diagrams

### New Message Flow (with persistence)

```
User types → CommandCenter.sendMessage()
  → useConversation.ensureSession() [lazy create]
  → POST /conversations/{id}/messages
     ├─ Backend persists user message to DB (role=user, type=text)
     ├─ Dispatches _process_agent_message() background task
     │   ├─ Agent processes message
     │   ├─ Accumulates response text + artifact events
     │   ├─ On completion:
     │   │   ├─ Persist assistant message to DB (role=assistant, type=text)
     │   │   ├─ Persist artifact messages to DB (role=system, type=system_artifact)
     │   │   └─ Emit "done" SSE event
     │   └─ On error:
     │       ├─ Persist error message to DB (role=system, type=error)
     │       └─ Emit "error" SSE event
     └─ Returns 202 ACCEPTED
  → SSE events stream to frontend for real-time display
```

### Session Resume Flow

```
User clicks session in sidebar
  → useConversation.loadSession(sessionId)
     ├─ GET /conversations/{id}/messages
     ├─ Read session.mode → setInteractiveShipping() [BEFORE rendering]
     ├─ Populate AppState.conversation from messages
     ├─ Parse context_data → best-effort data source reconnect
     │   ├─ Source exists + hash matches → reconnect silently
     │   ├─ Source exists + hash changed → reconnect + warn "Source modified"
     │   └─ Source missing → warn "Original data source unavailable"
     ├─ Connect SSE for new events
     └─ Set conversationSessionId
  → User can now send new messages (agent gets history via system prompt)
```

### New Chat Flow

```
User clicks "New Chat" button
  → startNewChat()
     ├─ Disconnect current SSE
     ├─ Clear AppState.conversation
     ├─ Set conversationSessionId = null
     ├─ Refresh sidebar (chatSessionsVersion++)
     └─ Show WelcomeMessage
  → User types first message
     → Lazy session creation (existing pattern)
     → New ConversationSession row created in DB
```

---

## 8. File Impact Summary

### New Files

| File | Purpose |
|------|---------|
| `src/services/conversation_persistence_service.py` | DB persistence service for sessions + messages |
| `frontend/src/components/sidebar/ChatSessionsPanel.tsx` | Chat sessions sidebar panel |
| `frontend/src/components/command-center/ChatTimeline.tsx` | Visual timeline minimap |

### Modified Files

| File | Changes |
|------|---------|
| `src/db/models.py` | Add `MessageType` enum, `ConversationSession`, `ConversationMessage` models |
| `src/db/connection.py` | Ensure new tables created on startup |
| `src/api/routes/conversations.py` | Add list/delete/export endpoints; modify create/send to persist |
| `src/api/schemas_conversations.py` | Add response schemas for session list, messages, export |
| `src/services/agent_session_manager.py` | Add `resume_session()` path; integrate with persistence service |
| `src/orchestrator/agent/system_prompt.py` | Add `prior_conversation` section to `build_system_prompt()` |
| `frontend/src/lib/api.ts` | Add `listConversations`, `getConversationMessages`, `exportConversation`, `updateConversationTitle` |
| `frontend/src/types/api.ts` | Add `ChatSessionSummary`, `SessionDetail`, `PersistedMessage` types |
| `frontend/src/hooks/useAppState.tsx` | Add `chatSessions`, `chatSessionsVersion`, `activeSessionTitle` state |
| `frontend/src/hooks/useConversation.ts` | Add `loadSession()`, `startNewChat()`; modify `reset()` to not delete |
| `frontend/src/components/CommandCenter.tsx` | Integrate timeline gutter; add `data-message-id` to messages |
| `frontend/src/components/command-center/messages.tsx` | Add `CopyButton` on hover for message bubbles |
| `frontend/src/components/layout/Sidebar.tsx` | Add `ChatSessionsPanel` section between data source and job history |

### Test Files (New)

| File | Coverage |
|------|----------|
| `tests/services/test_conversation_persistence_service.py` | CRUD, pagination, soft delete, export |
| `tests/api/test_conversations_persistence.py` | API endpoint integration tests |
| `tests/orchestrator/agent/test_system_prompt_resume.py` | Prior conversation injection |

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Context mismatch (deleted data source) | Medium | Best-effort restore with degraded-mode warning banner |
| System prompt token bloat on long conversations | Medium | Truncate prior conversation to last ~30 messages; summarize earlier messages |
| Performance on 1000+ message sessions | Low | Pagination (`limit`/`offset`) on message fetch; timeline maps to loaded messages |
| Sidebar vertical space with 3 panels | Low | Chat sessions panel collapsible with max-height internal scroll |
| Title generation race condition | Low | Fire-and-forget background task; frontend polls on sidebar refresh |
| SDK agent context loss on resume | Medium | System prompt injection gives context; agent cannot recall exact tool results but has conversational summary |

---

## 10. Non-Goals (Explicit Exclusions)

- Real-time collaboration (multiple users in same session)
- Full event replay (tool_call/tool_result storage — handled by decision audit)
- PDF/Markdown export (JSON only for V1)
- Session sharing or linking
- Auto-save drafts (user input not persisted until sent)
- Search across all sessions (V1: search within sidebar list by title only)
