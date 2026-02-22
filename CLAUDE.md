# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Vision

**ShipAgent** is an AI-native shipping automation platform. The goal is to build the most robust shipping agent ever — a system where a conversational AI agent is the **sole orchestrator** of all operations, with MCP servers as the connectivity layer and deterministic tools as the execution layer.

**The Claude Agent SDK is the backbone of the entire system.** The `OrchestrationAgent` is not a feature — it is the operating model. Every user interaction is an agent-driven conversation. Every capability is an agent tool. Every external system is accessed through MCP. There is no "dumb API" path, no standalone service logic, no orchestration outside the agent loop. If the agent can't do it, it doesn't belong in the system.

### Development Philosophy

**Agent-First Architecture:** The `OrchestrationAgent` (Claude Agent SDK) is the core. Features MUST integrate via tools; never bypass the agent loop. The SDK handles state, dispatch, and streaming—do not reimplement these.

**MCP Connectivity:** External systems are accessed exclusively via MCP (stdio). Integrations MUST be MCP servers or clients, never direct imports.

**Deterministic Execution:** The LLM generates transformation rules; deterministic code executes them. The LLM never touches row data directly. Tools enforce rules and ensure auditability.

**Canonical Data Models:** All integration constants, defaults, and domain enums live in dedicated canonical modules — never scattered as magic numbers across the codebase. When adding a new carrier, platform, or data source, define its constants in a single canonical module and import everywhere. This makes the system maintainable, testable, and auditable. See [Canonical Data Models](#canonical-data-models) for the current inventory.

**No Work Outside the Agentic Process:** Every capability — data import, filtering, preview, execution, tracking, label recovery — is an agent tool. If it can't be expressed as a tool the agent calls, it doesn't belong in the system. This discipline ensures the agent remains the single source of truth for all operations.

### Agent Design Invariants

These rules are non-negotiable. Violating them creates architectural debt that undermines the agent:

1. **No business logic in API routes.** Routes are thin adapters. Decision-making stays in the agent loop or tools.
2. **No direct UPS calls outside MCP.** All UPS operations use MCP (stdio). Never import UPS libraries directly.
3. **No LLM calls outside the agent.** The `OrchestrationAgent` is the sole LLM consumer.
4. **No tool skips approval.** Paths creating shipments or spending money REQUIRE a preview/confirmation step.
5. **No global mutable state for MCP clients.** Use `gateway_provider.py` singletons with async locking.
6. **No mode leakage.** Tool sets are strictly isolated between batch and interactive agents.
7. **No row data in LLM.** The LLM generates rules; tools apply them. LLM never sees individual rows.
8. **No scattered data definitions.** All constants/enums MUST live in canonical modules (e.g., `ups_constants.py`).

## Project Status

**Phases 1-7:** COMPLETE (State DB, Data Source MCP, Error Handling, NL Engine, Agent SDK, Batch Execution, Web Interface)
**Phase 8:** Production Packaging — Tauri v2 desktop wrapper, PyInstaller bundling, secure credential management, settings DB, onboarding wizard, CI/CD with code signing, auto-updater.
**Key Features:** International (CA/MX), Headless CLI, API Key Auth, Decision Auditing, Chat Persistence, Universal Data Ingestion, Address Book, Custom Commands, Settings UI.
**Production Packaging:** Tauri v2 desktop app with PyInstaller sidecar (one-folder build), keyring-based credential storage (macOS Keychain), `AppSettings` DB singleton, first-run onboarding wizard, Ed25519-signed auto-updater via GitHub Releases, CI/CD with Apple code signing.
**Test Count:** ~2660 across 170+ files (as of 2026-02-22)

## Architecture

### Core Principle: Agent → Tools → MCP → Services

The architecture follows a strict hierarchy:

1. **Agent (OrchestrationAgent)** — The brain. Interprets user intent, plans operations, calls tools.
2. **Tools (orchestrator/agent/tools/)** — Deterministic handlers. Execute specific operations, emit events, enforce business rules.
3. **MCP Servers** — Connectivity. Abstract external systems behind a uniform protocol.
4. **Services** — Business logic. State management, payload building, batch processing.

Nothing bypasses this chain. The frontend talks to the agent through SSE conversations. The agent talks to the world through tools and MCP.

```
User → Browser UI (React) → FastAPI REST API → Conversation SSE Route
                                                       ↓
                                              AgentSessionManager
                                                       ↓
                                              OrchestrationAgent (Claude SDK)
                                               ↓              ↓
                                    Orchestrator Tools    UPS MCP (stdio)
                                         ↓
                              ┌──────────┼──────────┐
                              ↓          ↓          ↓
                    DataSourceMCPClient  BatchEngine  ExternalSourcesMCPClient
                    (MCP stdio)         (UPSMCPClient) (MCP stdio)
                              ↓          ↓          ↓
                         Data Source   UPS MCP    External Sources
                         MCP Server   Server     MCP Server
```

### System Components

**Agent Layer:** `OrchestrationAgent` (Claude SDK) → 9 tool modules → Pre/PostToolUse hooks → `AgentSessionManager` (per-conversation lifecycle).

**MCP Layer:** Data Source MCP (FastMCP+DuckDB, stdio), UPS MCP (local fork, stdio, 18 tools), External Sources MCP (FastMCP, stdio — Shopify/WooCommerce/SAP/Oracle). Gateway singletons in `gateway_provider.py`.

**Execution Layer:** `BatchEngine` (concurrent preview+execute), `UPSMCPClient` (programmatic batch), `ConversationPersistenceService` (session/message DB).

**Presentation:** FastAPI backend (REST+SSE), React+Vite+TypeScript frontend, Typer+Rich headless CLI. SQLite+SQLAlchemy for persistence.

**Desktop Packaging:** Tauri v2 (Rust) hosts the React frontend in a native WebView. Python backend bundled via PyInstaller as a one-folder sidecar, spawned by Tauri at launch with OS-assigned port (`--port 0`). `src/bundle_entry.py` dispatches subcommands (`serve`, `mcp-data`, `mcp-ups`, `mcp-external`, `cli`). In bundled mode, MCP servers self-spawn this same binary with subcommand args (see `orchestrator/agent/config.py`).

**Credential & Settings Layer:** `KeyringStore` wraps system keychain (macOS Keychain / Linux Secret Service) with env var fallback for CI. `SettingsService` manages the `AppSettings` DB singleton (agent model, batch concurrency, shipper defaults, UPS account config, onboarding flag). `OnboardingWizard` (React) guides first-run credential + config setup.

### Agent Tool Architecture

The agent's tools are split into 9 modules by concern:

| Module | File | Tools | Purpose |
|--------|------|-------|---------|
| **Core** | `tools/core.py` | `EventEmitterBridge`, helpers | Shared infrastructure — event emission, row caching, bridge binding |
| **Data** | `tools/data.py` | `get_source_info`, `get_schema`, `fetch_rows`, `validate_filter_syntax`, `connect_shopify`, `get_platform_status` | Data source operations — querying, filtering, platform integration |
| **Pipeline** | `tools/pipeline.py` | `ship_command_pipeline`, `create_job`, `add_rows_to_job`, `batch_preview`, `batch_execute`, `get_job_status` | Batch shipping workflow — the core pipeline from command to labels |
| **Interactive** | `tools/interactive.py` | `preview_interactive_shipment` | Ad-hoc single-shipment creation (interactive mode only) |
| **Pickup** | `tools/pickup.py` | `schedule_pickup_tool`, `cancel_pickup_tool`, `rate_pickup_tool`, `get_pickup_status_tool`, `get_political_divisions_tool`, `get_service_center_facilities_tool` | UPS pickup operations — schedule, cancel, rate, status, reference lookups |
| **Locator** | `tools/locator.py` | `find_locations_tool` | UPS location search — Access Points, retail stores, service centers |
| **Paperless** | `tools/paperless.py` | `upload_document_tool`, `push_document_tool`, `delete_document_tool` | Paperless customs — upload, attach, delete trade documents |
| **Landed Cost** | `tools/landed_cost.py` | `get_landed_cost_tool` | International landed cost — duties, taxes, fees estimation |
| **Tracking** | `tools/tracking.py` | `track_package_tool` | UPS tracking — track package with mismatch detection |

Tool registration: `get_all_tool_definitions()` in `tools/__init__.py` assembles all definitions. In interactive mode, only status tools + `preview_interactive_shipment` are exposed; batch/data/v2 tools are hidden. V2 tools (pickup, locator, paperless, landed cost, tracking) are available in both batch and interactive modes via the orchestrator registry and MCP auto-discovery.

### Agent Hook System

Pre/PostToolUse hooks in `hooks.py` enforce business rules: `create_shipping_hook()` blocks direct `create_shipment` in both modes (must use pipeline/preview tools), `schedule_pickup_hook()`/`cancel_pickup_hook()` gate financial commitments, `validate_track_package` forces orchestrator wrapper, `log_post_tool` audits all calls, `detect_error_response` flags failures.

### Agent Intelligence Architecture

System prompt (`system_prompt.py`) assembled per-message by `build_system_prompt()`: identity, service codes (canonical `ServiceCode` enum), live data source schema, mode-aware filter rules, workflow instructions, safety rules. Changes based on `interactive_shipping` flag. Self-correction: up to 3 Jinja2 mapping retries (`CorrectionResult`).

### Data Flow

`POST /conversations/` → `POST /conversations/{id}/messages` → `OrchestrationAgent.process_message_stream()` → SSE events (deltas, tool calls) → `PreviewCard` → **mandatory user confirmation** → `confirmJob()` → `BatchEngine` execution → `CompletionArtifact` with labels → write-back tracking numbers. Fast path: `ship_command_pipeline` handles the entire flow in one tool call.

### Dual Shipping Modes

| Mode | Toggle | Agent Behavior | Tools Available |
|------|--------|---------------|-----------------|
| **Batch** (default) | Off | Data-source-driven — filter rows, preview costs, execute batch | All tools (data, pipeline, status) |
| **Interactive** | On | Conversational — collect recipient details, preview single shipment | `preview_interactive_shipment`, `get_job_status`, `get_platform_status` only |

Mode switching resets the conversation session (deletes old session, creates new one with opposite flag).

### Agent Safety Model

Three layers: **Structural** (tool registry filtering by mode, session isolation, gateway singletons), **Behavioral** (hooks block unsafe operations, audit all calls), **Procedural** (mandatory preview before execution, `confirmJob()` is the only execution path, E-XXXX error codes).

### Canonical Data Models

All constants/enums centralized — no magic numbers. Key modules: `ups_constants.py` (field limits, packaging codes, defaults), `ups_service_codes.py` (ServiceCode enum, 40+ aliases), `international_rules.py` (lane-driven compliance), `orchestrator/models/` (Pydantic models for agent reasoning), `external_sources/models.py` (ExternalOrder), `data_source/models.py` (SchemaColumn, ImportResult). **Pattern:** Create `<carrier>_constants.py` + `<carrier>_service_codes.py` for new integrations.

### MCP Gateway Architecture

Two MCP paths: **Agent MCP** (interactive, SDK-managed per session) and **Programmatic MCP** (batch + data, `gateway_provider.py` singletons). UPS MCP spawned per agent session (interactive) or per batch job (`UPSMCPClient` context manager). Data Source + External Sources MCPs are process-global singletons with `asyncio.Lock`. All clients inherit `MCPClient` with retry + exponential backoff. In bundled mode, MCP servers self-spawn the same binary with subcommand args (`mcp-data`, `mcp-ups`, `mcp-external`).

## Source Structure

```
src/
├── api/                        # FastAPI REST API (HTTP layer only — no business logic)
│   ├── routes/                 # Endpoint modules
│   │   ├── conversations.py    # Agent-driven SSE conversation (PRIMARY — all user interaction flows here)
│   │   ├── data_sources.py     # Local data source import/upload/disconnect/schema
│   │   ├── jobs.py             # Job CRUD + status + rows + summary
│   │   ├── preview.py          # Batch preview + confirm (triggers BatchEngine execution)
│   │   ├── progress.py         # Real-time SSE streaming + progress polling
│   │   ├── labels.py           # Label download (individual, merged PDF, ZIP)
│   │   ├── logs.py             # Audit log endpoints (list, errors, export)
│   │   ├── platforms.py        # Shopify, SAP, Oracle, WooCommerce
│   │   ├── saved_data_sources.py # Saved source CRUD + reconnect
│   │   ├── settings.py         # Settings GET/PATCH, credential status, onboarding
│   │   ├── contacts.py         # Address book CRUD + search
│   │   └── commands.py         # Custom slash commands CRUD
│   ├── main.py                 # App factory with lifespan events + SPA serving
│   ├── schemas.py              # Pydantic request/response models
│   └── schemas_conversations.py # Conversation endpoint schemas
├── cli/                        # Headless automation CLI (shipagent command)
│   ├── main.py                 # Typer entry point — daemon, job, submit, interact
│   ├── config.py, protocol.py, factory.py  # Config, protocol, client factory
│   ├── daemon.py, http_client.py, runner.py  # Daemon mgmt, HTTP client, in-process runner
│   ├── repl.py, output.py      # Conversational REPL, Rich formatters
│   ├── auto_confirm.py         # Auto-confirm engine for headless execution
│   └── watchdog_service.py     # Hot folder filesystem watcher
├── db/                         # Database layer
│   ├── models.py               # SQLAlchemy models (Job, JobRow, AuditLog, SavedDataSource, ConversationSession, ConversationMessage, AppSettings)
│   └── connection.py           # Session management
├── errors/                     # Error handling
│   ├── registry.py             # E-XXXX error code registry
│   ├── ups_translation.py      # UPS error → ShipAgent error mapping
│   └── formatter.py            # Error message formatting
├── services/                   # Business logic (core services — called by agent tools)
│   ├── ups_constants.py        # ⭐ CANONICAL — UPS field limits, packaging codes, defaults, units
│   ├── ups_service_codes.py    # ⭐ CANONICAL — ServiceCode enum, aliases, resolvers
│   ├── international_rules.py  # ⭐ CANONICAL — Lane-driven compliance (customs, commodities)
│   ├── errors.py               # Shared error types (UPSServiceError)
│   ├── mcp_client.py           # Generic async MCP client with retry + exponential backoff
│   ├── ups_mcp_client.py       # UPSMCPClient — async UPS via MCP stdio (batch path)
│   ├── ups_specs.py            # UPS MCP OpenAPI spec path helpers
│   ├── batch_engine.py         # BatchEngine — unified preview + execution with concurrency
│   ├── column_mapping.py       # ColumnMappingService — source → UPS field mapping
│   ├── ups_payload_builder.py  # Builds UPS API payloads from canonical constants + mapped data
│   ├── agent_session_manager.py # Per-conversation agent session lifecycle
│   ├── job_service.py          # Job state machine, row tracking
│   ├── audit_service.py        # Audit logging with redaction
│   ├── data_source_service.py  # Data source import + auto-save hooks (legacy — prefer MCP gateway)
│   ├── data_source_gateway.py  # DataSourceGateway protocol + typed adapter
│   ├── data_source_mcp_client.py # DataSourceMCPClient — async data source via MCP stdio
│   ├── external_sources_mcp_client.py # ExternalSourcesMCPClient — async platform via MCP stdio
│   ├── gateway_provider.py     # Centralized singleton factory for MCP client gateways
│   ├── batch_executor.py       # Shared batch execution service (used by HTTP routes + CLI)
│   ├── conversation_handler.py # Shared conversation handling (agent session + message streaming)
│   ├── conversation_persistence_service.py # DB-backed session/message CRUD + auto title generation
│   ├── saved_data_source_service.py # Saved source CRUD (list, upsert, delete, reconnect)
│   ├── write_back_utils.py     # Atomic CSV/Excel write-back utilities
│   ├── keyring_store.py        # System keychain wrapper (macOS Keychain) with env fallback
│   ├── settings_service.py     # AppSettings DB singleton CRUD + validation
│   ├── contact_service.py      # Contact (address book) CRUD + search
│   └── custom_command_service.py # Custom slash commands CRUD
├── mcp/
│   ├── data_source/            # Data Source MCP server (DuckDB-backed SQL interface)
│   │   ├── server.py           # FastMCP server with stdio transport
│   │   ├── models.py           # Canonical: SchemaColumn, ImportResult, RowData
│   │   ├── adapters/           # Pluggable: base, csv, excel, json, xml, fixed_width, db, edi adapters
│   │   ├── utils.py            # Shared: flatten_record, type inference, DuckDB loading helpers
│   │   ├── tools/              # import, schema, query, checksum, commodity, writeback, edi tools
│   │   └── edi/                # X12 + EDIFACT parsers
│   └── external_sources/       # External platform MCP
│       ├── server.py, tools.py # Platform MCP server + tools
│       ├── models.py           # Canonical: ExternalOrder, PlatformType, ConnectionStatus
│       └── clients/            # Shopify, WooCommerce, SAP, Oracle adapters
├── utils/                      # Cross-cutting utilities
│   ├── paths.py                # Production file path resolver (platformdirs, dev fallback)
│   └── runtime.py              # Runtime detector: is_bundled(), get_resource_dir()
├── bundle_entry.py             # PyInstaller entry point — subcommand dispatch (serve/mcp-*/cli)
└── orchestrator/               # Orchestration layer (AGENT IS PRIMARY)
    ├── filters/                # Jinja2 logistics filter library
    │   └── logistics.py        # truncate_address, format_us_zip, convert_weight, etc.
    ├── models/                 # Data models
    │   ├── intent.py           # ServiceCode enum + SERVICE_ALIASES mapping
    │   ├── filter.py           # NL filter models
    │   ├── mapping.py          # Column mapping models
    │   ├── elicitation.py      # Elicitation models
    │   └── correction.py       # Self-correction loop tracking (max 3 attempts)
    ├── agent/                  # Claude Agent SDK integration (PRIMARY ORCHESTRATION PATH)
    │   ├── client.py           # OrchestrationAgent — SDK agent with streaming + MCP coordination
    │   ├── system_prompt.py    # Dynamic system prompt builder (domain knowledge + data schema)
    │   ├── tools/              # Deterministic SDK tools (split by concern — 9 modules)
    │   │   ├── __init__.py     # Tool registry — get_all_tool_definitions()
    │   │   ├── core.py         # EventEmitterBridge, row cache, bridge binding helpers
    │   │   ├── data.py         # Data source + platform tool handlers
    │   │   ├── pipeline.py     # Batch pipeline tool handlers (ship_command_pipeline fast path)
    │   │   ├── interactive.py  # Interactive shipment tool handler (preview_interactive_shipment)
    │   │   ├── pickup.py       # UPS pickup operations (schedule, cancel, rate, status, divisions, facilities)
    │   │   ├── locator.py      # UPS location search (find_locations_tool)
    │   │   ├── paperless.py    # Paperless customs (upload, push, delete document tools)
    │   │   ├── landed_cost.py  # Landed cost estimation (get_landed_cost_tool)
    │   │   └── tracking.py     # UPS package tracking (track_package_tool)
    │   ├── config.py           # MCP server configuration factory (Data, External, UPS)
    │   └── hooks.py            # Pre/PostToolUse validation hooks (mode enforcement, audit)
    └── batch/                  # Batch orchestration
        ├── events.py           # BatchEventObserver protocol
        ├── models.py           # Batch state models
        ├── modes.py            # Preview/execute modes
        ├── recovery.py         # Crash recovery logic
        └── sse_observer.py     # SSE streaming observer

frontend/src/
├── App.tsx, main.tsx, index.css    # Entry point + design system (OKLCH, DM Sans, Instrument Serif)
├── components/
│   ├── CommandCenter.tsx           # Main chat UI — SSE event orchestration, preview/progress/completion
│   ├── command-center/             # PreviewCard, ProgressDisplay, CompletionArtifact, ToolCallChip, messages, domain cards
│   ├── chat/                       # ChatTimeline (visual minimap), RichChatInput
│   ├── sidebar/                    # DataSourcePanel, JobHistoryPanel, ChatSessionsPanel
│   ├── ui/                         # shadcn/ui primitives + icons.tsx + brand-icons.tsx
│   └── layout/                     # Sidebar, Header (with interactive shipping toggle)
├── hooks/
│   ├── useAppState.tsx             # Global state context (conversation, jobs, data source, mode, chat sessions)
│   ├── useConversation.ts          # Agent SSE lifecycle (session + events + mode switching)
│   └── useJobProgress.ts, useSSE.ts, useExternalSources.ts
├── lib/
│   ├── api.ts                      # REST client (all /api/v1 endpoints)
│   └── tauri-init.ts               # Sidecar bootstrap — discovers dynamic port, sets window.__SHIPAGENT_PORT__
└── types/api.ts                    # TypeScript types mirroring Pydantic schemas

src-tauri/                          # Tauri v2 desktop wrapper (Rust)
├── src/main.rs                     # Sidecar lifecycle — spawn, port discovery, timeout handling
├── tauri.conf.json                 # Bundle config, CSP, auto-updater (Ed25519), resources
├── Cargo.toml                      # Rust deps (tauri v2, shell plugin, updater plugin)
├── entitlements.plist              # macOS code-signing entitlements (Keychain access)
└── capabilities/                   # Tauri permission grants (shell, dialog, updater)

scripts/
├── bundle_backend.sh               # PyInstaller build + smoke test + updater key validation
├── bump-version.sh                  # Syncs version across pyproject.toml, tauri.conf.json, package.json
└── generate-updater-key.sh          # Ed25519 key pair for Tauri auto-updater signing
```

## Key Services

### OrchestrationAgent (`src/orchestrator/agent/client.py`)

**The system backbone.** Claude Agent SDK manages conversation state, tool dispatch, MCP servers, hooks, streaming, and error recovery. `process_message_stream()` yields SSE events, `interrupt()` cancels in-progress responses. MCP servers: `orchestrator` (in-process) + `ups` (stdio). Default model: `AGENT_MODEL` → `ANTHROPIC_MODEL` → Claude Haiku 4.5.

### UPS MCP Server (local fork: `matt-hans/ups-mcp`)

Stdio child process, editable install from pinned commit. 18 tools across 6 domains: Shipping (rate, create, void, recover), Address/Transit (validate, track, time-in-transit), Landed Cost, Paperless (upload, push, delete), Locator, Pickup (rate, schedule, cancel, status, divisions, facilities). V2 tools available in both batch and interactive modes.

### BatchEngine (`src/services/batch_engine.py`)

Unified preview + execution with concurrent `asyncio.gather` + semaphore (`BATCH_CONCURRENCY` env, default 5). Per-row state writes for crash recovery. SSE events for real-time progress. Integrated write-back to CSV/Excel sources and external platforms for tracking number persistence.

### AgentSessionManager (`src/services/agent_session_manager.py`)

Per-conversation agent sessions. Each gets isolated history, persistent `OrchestrationAgent`, `agent_source_hash` for change detection (agent rebuilt on source/mode change), `asyncio.Lock` for serialization, optional prewarm.

### UPSPayloadBuilder (`src/services/ups_payload_builder.py`)

Builds UPS API payloads from column-mapped data + canonical constants (`ups_constants.py`). All field limits, defaults, packaging codes, and label specs are imported — never inline. See [UPS API Lessons](#ups-api-lessons) for hard-won fixes.

### API Key Auth Middleware (`src/api/middleware/auth.py`)

Optional gate controlled by `SHIPAGENT_API_KEY` env var. When set, all `/api/*` paths require `X-API-Key: <key>` header. Public paths (`/health`, `/readyz`, `/docs`, `/assets/`) are exempt. Uses `hmac.compare_digest` for timing-safe comparison. Omit or leave blank to disable.

### DecisionAuditService (`src/services/decision_audit_service.py`)

Agent decision ledger → `agent_decision_runs` + `agent_decision_events` tables + JSONL mirror. Config: `AGENT_AUDIT_ENABLED`, `AGENT_AUDIT_JSONL_PATH`, `AGENT_AUDIT_RETENTION_DAYS`.

### ConversationPersistenceService (`src/services/conversation_persistence_service.py`)

DB-backed CRUD for `ConversationSession` and `ConversationMessage` tables. Session titles set synchronously from first user message (truncated to 50 chars).

### KeyringStore (`src/services/keyring_store.py`)

System keychain wrapper for secure credential storage. Uses `keyring` library (macOS Keychain, Linux Secret Service, Windows Credential Manager). All `set()` calls sync to `os.environ` for immediate runtime access. `get_all_status()` does a single keyring probe for fail-fast, then checks each credential. `load_all_to_env()` hydrates env vars from keychain on startup. Falls back to env-only mode when keychain is unavailable (CI, locked sessions). Managed credentials: `ANTHROPIC_API_KEY`, `UPS_CLIENT_ID`, `UPS_CLIENT_SECRET`, `SHIPAGENT_API_KEY`, `FILTER_TOKEN_SECRET`.

### SettingsService (`src/services/settings_service.py`)

CRUD for the `AppSettings` DB singleton (fixed `id="default"`). Fields: `agent_model`, `batch_concurrency` (1-20), `shipper_name/company/phone/address/city/state/zip/country_code`, `ups_account_number`, `onboarding_completed`. Uses `INSERT OR IGNORE` + `UPDATE` pattern for upsert. Validated at both API layer (Pydantic) and DB layer (CHECK constraints).

### Bundle Entry Point (`src/bundle_entry.py`)

Unified PyInstaller entry point dispatching to `serve` (FastAPI+uvicorn with dynamic port reporting), `mcp-data`, `mcp-ups`, `mcp-external` (MCP stdio servers), or `cli` (Typer). `PortReportingServer` subclass prints `SHIPAGENT_PORT=XXXXX` to stdout for Tauri to parse. Global exception handler catches crashes and prints to stderr.

## Frontend Architecture

Agent-driven chat interface. `useConversation` manages session lifecycle + SSE streaming. `useAppState` context holds all global state (persisted to localStorage where appropriate).

**Chat flow**: User types → SSE events stream → PreviewCard (Confirm/Cancel/Refine) → ProgressDisplay → CompletionArtifact with labels.

**Chat persistence**: DB-backed sessions. `ChatSessionsPanel` groups by date. `chatSessionsVersion` counter triggers re-fetch. Preview cards persisted as `system_artifact` messages, render read-only in history.

**Onboarding**: `OnboardingWizard` renders as full-screen overlay on first launch (when `appSettings.onboarding_completed` is false). 3 steps: Anthropic API key → UPS credentials → shipper address. Saves to keyring + settings DB.

**Settings UI**: `SettingsFlyout` with tabs: Connections (provider status), Address Book (contact CRUD), Commands (custom slash commands), Preferences (agent model, batch concurrency).

## API Endpoints

All endpoints use `/api/v1/` prefix. See route files in `src/api/routes/` for full details.

**Primary agent path** (conversations.py): `POST /conversations/` (create session) → `POST /conversations/{id}/messages` (send to agent) → `GET /conversations/{id}/stream` (SSE events) → `DELETE /conversations/{id}` (cleanup)

**Chat persistence** (conversations.py): `GET /conversations/` (list sessions, paginated) → `GET /conversations/{id}/messages` (load history) → `PATCH /conversations/{id}` (rename) → `GET /conversations/{id}/export` (JSON download)

**Jobs** (jobs.py): CRUD on `/jobs/`, status via `PATCH /jobs/{id}/status`, preview via `GET /jobs/{id}/preview`, confirm via `POST /jobs/{id}/confirm`, SSE progress via `GET /jobs/{id}/progress/stream`

**Labels** (labels.py): Individual `GET /labels/{tracking}`, merged PDF `GET /jobs/{id}/labels/merged`, ZIP `GET /jobs/{id}/labels/zip`

**Data Sources** (data_sources.py): `POST /data-sources/import`, `POST /data-sources/upload`, `GET /data-sources/status`, `POST /data-sources/disconnect`

**Saved Sources** (saved_data_sources.py): `GET /saved-sources`, `POST /saved-sources/reconnect`, `DELETE /saved-sources/{id}`, `POST /saved-sources/bulk-delete`

**Platforms** (platforms.py): `POST /platforms/{platform}/connect`, `GET /platforms/shopify/env-status` (auto-reconnect after restart), `GET /platforms/{platform}/orders`

**Settings & Credentials** (settings.py): `GET /settings` (singleton), `PATCH /settings` (partial update), `GET /settings/credential-status` (keyring probe), `PUT /settings/credentials/{key}` (store in keychain), `POST /settings/onboarding/complete`

**Contacts** (contacts.py): `GET /contacts`, `POST /contacts`, `PUT /contacts/{id}`, `DELETE /contacts/{id}`, `GET /contacts/search`

**Agent Audit** (agent_audit.py): `GET /agent-audit/runs`, `GET /agent-audit/runs/{id}`, `GET /agent-audit/runs/{id}/events`, `GET /agent-audit/runs/{id}/timeline`, `GET /agent-audit/export`, `DELETE /agent-audit/runs` (prune by age)

## Technology Stack

| Component | Technology |
|-----------|------------|
| Desktop App | Tauri v2 (Rust), tauri-plugin-shell, tauri-plugin-updater (Ed25519) |
| Backend | Python 3.12+, FastAPI, SQLAlchemy, SQLite |
| Bundling | PyInstaller (one-folder), `bundle_entry.py` subcommand dispatch |
| Agent Framework | Claude Agent SDK (`claude-agent-sdk>=0.1.22`), Anthropic API |
| MCP Protocol | FastMCP v2 (servers), `mcp` (stdio clients) |
| Credentials | `keyring` (macOS Keychain / Linux Secret Service), `platformdirs` |
| Data Processing | DuckDB (in-memory analytics), openpyxl (Excel), `defusedxml` (XXE prevention) |
| UPS Integration | `ups-mcp` local fork (pinned commit, editable install via pip) |
| NL Processing | sqlglot (SQL generation/validation), Jinja2 (logistics filters) |
| Real-time | SSE via `sse-starlette` |
| PDF | `pypdf` (merging), `react-pdf` + `pdfjs-dist` (browser rendering) |
| Headless CLI | Typer, Rich, httpx, watchdog, PyYAML |
| Frontend | React, Vite, TypeScript, Tailwind CSS v4, shadcn/ui |
| CI/CD | GitHub Actions, Apple code signing, `gh release` |

## Common Commands

### Backend

```bash
# Start backend with all env vars (Shopify, Anthropic, UPS)
./scripts/start-backend.sh

# Or manually:
set -a && source .env && set +a && uvicorn src.api.main:app --reload --port 8000

# After backend restart, reconnect Shopify:
curl http://localhost:8000/api/v1/platforms/shopify/env-status

# Docker (dev)
docker-compose up --build

# Docker (prod)
docker-compose -f docker-compose.prod.yml up -d

# Database: set DATABASE_URL for custom SQLite path
# Docker default: DATABASE_URL=sqlite:////app/data/shipagent.db
# Backup/restore: scripts/backup.sh <dest>, scripts/restore.sh <backup>
```

### Tests

```bash
# Run all tests
pytest

# Skip known hanging tests
pytest -k "not test_stream_endpoint_exists"

# Avoid tests that may hang (SSE/streaming)
pytest -k "not stream and not sse and not progress"

# Run specific test file
pytest tests/services/test_ups_payload_builder.py -v

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Type checking
mypy src/

# Linting
ruff check src/ tests/
ruff format src/ tests/
```

### Headless CLI

```bash
shipagent --standalone submit orders.csv --service "UPS Ground"  # No daemon
shipagent --standalone interact                                   # REPL mode
shipagent daemon start --config shipagent.yaml                    # Daemon mode
shipagent submit orders.csv --auto-confirm                        # With daemon
shipagent job inspect <job-id>                                    # Job details
pytest tests/cli/ -v                                              # CLI tests
```

### Frontend

```bash
cd frontend
npm install
npm run dev          # Development server (port 5173)
npm run build        # Production build
npx tsc --noEmit     # Type check
```

### Build & Packaging

```bash
# Bundle Python backend (PyInstaller one-folder build)
./scripts/bundle_backend.sh

# Build Tauri desktop app (requires bundled backend)
cd src-tauri && cargo tauri build

# Dev mode (Tauri + hot-reload)
cargo tauri dev

# Sync versions across pyproject.toml, tauri.conf.json, package.json
./scripts/bump-version.sh 1.2.3

# Generate Ed25519 updater keypair
./scripts/generate-updater-key.sh
```

### Agent Testing

```bash
pytest tests/orchestrator/agent/ -v        # Agent tools + hooks + system prompt
pytest tests/services/test_batch_engine.py -v  # Batch preview + execution
pytest tests/services/test_ups_mcp_client.py -v  # UPS MCP client
pytest tests/services/test_ups_payload_builder.py -v  # Payload builder + constants
```

## Key Conventions

### Error Codes

Format: `E-XXXX` with category prefixes:
- `E-1xxx`: Data errors
- `E-2xxx`: Validation errors (includes E-2020–E-2025 for MCP elicitation errors)
- `E-3xxx`: UPS API errors (includes E-3006–E-3009 for paperless/pickup/locator errors)
- `E-4xxx`: System errors (includes E-4001–E-4002, E-4011–E-4012 for user cancellation and safety gates)
- `E-5xxx`: Authentication errors

### Currency

All costs stored as **integers in cents** to avoid floating-point precision issues.

### Timestamps

All timestamps stored as **ISO8601 strings** for SQLite compatibility.

### API Versioning

All REST endpoints use `/api/v1/` prefix.

### Enums

All enums inherit from both `str` and `Enum` for JSON serialization.

### Frontend Patterns

- Design system in `index.css`: OKLCH colors, DM Sans / Instrument Serif / JetBrains Mono typography
- CSS classes: `card-premium`, `btn-primary`, `btn-secondary`, `badge-*`, `card-domain-*`
- Domain colors (OKLCH): shipping/green(145), pickup/purple(300), locator/teal(185), paperless/amber(85), landed-cost/indigo(265), tracking/blue(230)
- Icons: `ui/icons.tsx` (general), `ui/brand-icons.tsx` (platform logos)
- shadcn/ui primitives in `components/ui/`
- Labels stored on disk, paths in `JobRow.label_path`; `order_data` as JSON text in `JobRow.order_data`
- Chat sessions: `chatSessionsVersion` counter + `refreshChatSessions()` in AppState (same pattern as `jobListVersion`)
- Timeline dots: grey(user), cyan(assistant), amber(artifact) — `ChatTimeline.tsx` with `IntersectionObserver`
- Copy button: hover-reveal on all message bubbles, visual error/success states

## Known Issues

- SSE/streaming tests may hang — use `pytest -k "not stream and not sse and not progress"`
- After backend restart, Shopify connection lost (in-memory) — call `GET /api/v1/platforms/shopify/env-status`
- EDI adapter test collection errors (10 tests, unrelated to core features)
- **Claude Agent SDK bug [#265](https://github.com/anthropics/claude-agent-sdk-python/issues/265)**: PreToolUse hook denials generate a synthetic "API Error: 400 due to tool use concurrency issues" message. Hooks remain active; the misleading error is suppressed in the chat UI (`CommandCenter.tsx:161`). Remove the filter when the SDK fix ships.

## UPS API Lessons

These are hard-won fixes — do not revert:
- `Packaging` not `PackagingType` for the package type key
- `ShipmentCharge` must be an array `[{...}]`, not a single object
- ReferenceNumber at shipment level is rejected for Ground domestic (omitted entirely)
- Filter evaluator handles compound AND/OR WHERE clauses with parenthesis-depth-aware splitting
- Person name queries generate `customer_name = 'X' OR ship_to_name = 'X'` for disambiguation
- UPS `_translate_error` was swallowing error details — ensure raw_str fallback when ups_message is empty

## Extension Points

All extensions MUST integrate through agent tools/MCP and follow canonical data model patterns:

- **New Carrier**: Create `<carrier>_constants.py` + `<carrier>_service_codes.py` in `src/services/`, build MCP server (stdio), add client wrapper, register tools. Never hardcode constants.
- **New Data Source**: Implement `BaseSourceAdapter` in `src/mcp/data_source/adapters/`. Must produce `ImportResult` with `SchemaColumn`. Use `utils.py` helpers (`flatten_record`, `load_flat_records_to_duckdb`) for nested formats. See JSON/XML adapters as examples.
- **New Platform**: Add client in `src/mcp/external_sources/clients/`. Must normalize to `ExternalOrder`.
- **New Agent Tool**: Add handler in appropriate tool module, register in `tools/__init__.py`. Import constants from canonical modules.
- **New Batch Capability**: Extend `BatchEngine`, expose via pipeline tool.
- **Filters/Observers**: Register Jinja2 filters in Filter Registry; subscribe to BatchEngine SSE events.

## Roadmap (Agent Capabilities)

- **P0 — International Shipping (CA/MX)**: COMPLETE.
- **P0 — Production Packaging**: COMPLETE — Tauri v2, PyInstaller, keyring, settings, onboarding, CI/CD, auto-updater.
- **P0 — Address Book**: COMPLETE — `ContactService` + `contacts.py` tool module with @handle resolution.
- **P1 — Multi-Carrier (FedEx, USPS)**: New MCP servers per carrier, `compare_carriers` tool. Not started.
- **P2 — Google Sheets, Webhooks**: New adapters/tools. Not started.
- **P3 — Smart Routing**: Optimal carrier+service recommendation. Requires multi-carrier. Not started.

## Boundaries

Shipping orchestration only — read-only for orders (except tracking write-back), no inventory management, no payment processing, no customer communication, UPS-only (multi-carrier on roadmap).
