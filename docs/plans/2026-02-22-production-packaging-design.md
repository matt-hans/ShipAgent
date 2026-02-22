# Production Packaging Design — ShipAgent Desktop App

**Date:** 2026-02-22
**Status:** Approved
**Target:** macOS desktop app (v1.0), Windows fast-follow

## Context

ShipAgent is an AI-native shipping automation platform with a FastAPI backend, React frontend, and 3 MCP servers (Data Source, UPS, External Sources). Today it runs as a dev server (`uvicorn --reload`) with a `.env` file for configuration. This design packages it into a signed, auto-updating macOS desktop app for SMB customers.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Desktop wrapper | Tauri v2 | Smaller binary (~10MB vs Electron's 150MB), native WebView, built-in updater, Rust sidecar management |
| Python bundling | PyInstaller (single binary) | Proven, handles native deps (DuckDB, cryptography), single `shipagent-core` binary with subcommand modes |
| MCP server packaging | Self-spawning subcommands | `shipagent-core mcp-data`, `mcp-ups`, `mcp-external` — same binary, different modes via stdio |
| Credential storage | macOS Keychain via `keyring` | Hardware-backed (Secure Enclave), eliminates key-management bootstrapping |
| Non-sensitive config | SQLite `settings` table | Already have `shipagent.db`, extends naturally |
| API key model | BYOK (Bring Your Own Key) | MVP simplicity; architecture supports future proxy option |
| Platform priority | macOS first | Focused scope, Apple signing available |
| Auto-updates | Tauri built-in updater | Checks GitHub Releases, signed updates, differential downloads |
| Code signing | Apple Developer ID | Required for Gatekeeper; Windows deferred |

## Architecture

### Component Diagram

```
ShipAgent.app (macOS)
├── Tauri Shell (~10MB)
│   ├── WKWebView → React frontend (built into app)
│   ├── Rust sidecar manager (start/stop/health-check)
│   └── Updater plugin (checks GitHub Releases)
├── shipagent-core (PyInstaller binary, ~200MB)
│   ├── `serve` mode → FastAPI on localhost:PORT
│   ├── `mcp-data` mode → Data Source MCP server (stdio)
│   ├── `mcp-ups` mode → UPS MCP server (stdio)
│   ├── `mcp-external` mode → External Sources MCP server (stdio)
│   └── `cli` mode → Full Typer CLI (daemon, submit, interact)
└── Resources/
    └── Default config
```

### Communication Flow

```
Tauri Shell
  │
  ├─ spawns ──→ shipagent-core serve --port {PORT}
  │                  │
  │                  ├─ spawns ──→ shipagent-core mcp-data (stdio)
  │                  ├─ spawns ──→ shipagent-core mcp-ups (stdio)
  │                  └─ spawns ──→ shipagent-core mcp-external (stdio)
  │
  └─ WebView loads ──→ http://127.0.0.1:{PORT}
```

### Port Management

Tauri shell picks a random available port, passes it to the sidecar via `--port`, and injects `window.__SHIPAGENT_PORT__` into the WebView. The React app reads this instead of hardcoding `localhost:8000`.

### File Locations (macOS)

| Data | Location |
|------|----------|
| App bundle | `/Applications/ShipAgent.app` |
| Database | `~/Library/Application Support/com.shipagent.app/shipagent.db` |
| Labels | `~/Library/Application Support/com.shipagent.app/labels/` |
| Logs | `~/Library/Logs/com.shipagent.app/` |
| Credentials | macOS Keychain (via `keyring`) |
| Config | `~/Library/Application Support/com.shipagent.app/config.yaml` |

## Configuration & Credential Management

### Three-Tier Configuration

**Tier 1: Secure Credential Store (macOS Keychain)**

Stored via `keyring` library:
- `ANTHROPIC_API_KEY`
- `UPS_CLIENT_ID`, `UPS_CLIENT_SECRET`
- `SHOPIFY_ACCESS_TOKEN`
- `FILTER_TOKEN_SECRET` (auto-generated on first run)
- `SHIPAGENT_API_KEY` (if enabled)

**Tier 2: Settings Database**

New `settings` table in `shipagent.db`:
- `agent_model` — Claude model ID
- `batch_concurrency` — concurrent UPS calls
- `shipper_*` — shipper address defaults (name, address1, city, state, zip, country, phone)
- `ups_account_number`, `ups_environment`
- `allowed_origins` — CORS allowlist
- `labels_output_dir` — label storage path

**Tier 3: Hardcoded Defaults**

Constants computed at startup:
- `DATABASE_URL` → from `platformdirs.user_data_dir()`
- `SHIPAGENT_ALLOW_MULTI_WORKER` → `false`
- Feature flags → static per release

### Resolution Order

```
1. Environment variable (override for dev/debugging)
2. macOS Keychain (secrets only, via keyring)
3. Settings DB (non-sensitive config)
4. Hardcoded default
```

### First-Run Onboarding

Full-screen modal on first launch (detected by absence of API key in Keychain):

1. **Step 1 (required):** Anthropic API Key → stored in Keychain
2. **Step 2 (optional):** UPS credentials → stored in Keychain
3. **Step 3 (optional):** Shipper address → stored in Settings DB

Steps 2-3 are skippable. Accessible later via Settings.

## Python Bundling (PyInstaller)

### Unified Entry Point

New file `src/bundle_entry.py`:

```python
import sys

def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if command == "serve":
        # Parse --port flag, start FastAPI via uvicorn
        ...
    elif command == "mcp-data":
        from src.mcp.data_source.server import main as mcp_main
        mcp_main()
    elif command == "mcp-ups":
        from ups_mcp import main as ups_main
        ups_main()
    elif command == "mcp-external":
        from src.mcp.external_sources.server import main as ext_main
        ext_main()
    elif command == "cli":
        from src.cli.main import app as cli_app
        cli_app()
```

### Dev vs Production Detection

```python
def is_bundled() -> bool:
    return getattr(sys, 'frozen', False)
```

Used in `config.py` to resolve MCP server commands:
- Bundled: `sys.executable, "mcp-data"`
- Dev: `.venv/bin/python3, "-m", "src.mcp.data_source.server"`

### PyInstaller Spec File

`shipagent-core.spec` with:
- Hidden imports for FastMCP, DuckDB, sqlglot, Claude Agent SDK, aiosqlite
- Data files: `frontend/dist` bundled as resources
- Exclusions: tkinter, test, unused stdlib
- Strip debug symbols
- Target size: ~150-200MB

### Build Script

`scripts/bundle_backend.sh` runs PyInstaller with the spec file, producing `dist/shipagent-core`.

## Tauri Integration

### Project Structure

```
src-tauri/
├── Cargo.toml
├── tauri.conf.json
├── capabilities/default.json
├── src/
│   ├── main.rs          # Setup sidecar, configure window
│   ├── sidecar.rs       # Lifecycle: start, health-check, restart, stop
│   └── lib.rs           # Plugin registration
├── icons/
└── Info.plist
```

### Sidecar Lifecycle

1. **Startup:** Find `shipagent-core` in app bundle → spawn `serve --port {PORT}` → poll `/health` every 200ms → load WebView when healthy
2. **Health monitoring:** Background thread pings `/health` every 10s. Three consecutive failures → restart, show "Reconnecting..." overlay
3. **Shutdown:** Window close → `SIGTERM` → wait 5s → `SIGKILL` → cleanup
4. **Port selection:** Bind to port 0, read assigned port, pass to sidecar

### Frontend Changes

1. API base URL reads `window.__SHIPAGENT_PORT__` (injected by Tauri), falls back to `8000` for dev
2. Loading splash while sidecar starts (~2-3s)
3. Vite dev proxy unchanged

### CLI Symlink

On first launch, creates `/usr/local/bin/shipagent` → `shipagent-core cli` (with user permission).

## CI/CD & Distribution

### GitHub Actions Pipeline

`.github/workflows/release.yml` triggered on `v*.*.*` tags:

1. **Test** — pytest + tsc + ruff
2. **Build sidecar** — PyInstaller on `macos-14` (arm64)
3. **Build Tauri** — `npm run tauri build` → `.dmg`
4. **Sign & Notarize** — `codesign` + `xcrun notarytool` + `stapler`
5. **Publish** — Upload to GitHub Releases
6. **Update manifest** — Publish JSON for Tauri updater

### Required Secrets

- `APPLE_CERTIFICATE` — Base64 .p12 Developer ID certificate
- `APPLE_CERTIFICATE_PASSWORD` — .p12 password
- `APPLE_ID` — Apple ID email
- `APPLE_PASSWORD` — App-specific password
- `APPLE_TEAM_ID` — Developer Team ID

### Versioning

Semantic versioning (`v1.0.0`). Version in:
- `pyproject.toml`
- `tauri.conf.json`
- `frontend/package.json`

`scripts/bump-version.sh` updates all three.

### Update Flow

Tauri updater checks GitHub-hosted JSON endpoint on startup + every 4 hours. Updates downloaded and applied on next restart.

## Settings UI Expansion

### New Components

1. **`OnboardingWizard.tsx`** — Full-screen first-run modal (3 steps)
2. **API Key Management** — View masked key, update/rotate, connection status

### Expanded Sections

1. **ConnectionsSection** — Add "Test Connection" button, visual status dots (already functional)
2. **ShipmentBehaviourSection** — Shipper defaults, default service/packaging, batch concurrency slider

### New Backend Routes

```
GET  /api/v1/settings                      # All non-sensitive settings
PUT  /api/v1/settings                      # Bulk update settings
GET  /api/v1/settings/credentials/status   # Which credentials are set (not values)
POST /api/v1/settings/credentials          # Set a credential (Keychain)
POST /api/v1/settings/onboarding/complete  # Mark onboarding done
```

### Expanded: AddressBookSection (Full CRUD + Search)

Replace the stub with a complete address management system:

**Data Model:** New `addresses` table in `shipagent.db`:
- `id` (UUID), `type` (shipper|recipient), `label` (user-given name, e.g. "NYC Warehouse")
- `name`, `attention_name`, `company`, `address1`, `address2`, `city`, `state`, `zip`, `country`, `phone`, `email`
- `is_default` (boolean, one default per type), `created_at`, `updated_at`

**UI Components:**
- Address list with search/filter by name, company, city, type
- Create/edit form (reuses existing `ContactForm.tsx`)
- Set as default shipper button
- Delete with confirmation
- Import from CSV (bulk load existing address book)

**Agent Integration:**
- New `resolve_address` agent tool: given a name/label, looks up the address from the book
- Agent can reference saved addresses by name in natural language: "ship to NYC Warehouse"
- Default shipper address auto-populated from address book (replaces env vars)

**Backend Routes:**
```
GET    /api/v1/addresses                # List with search/filter/pagination
POST   /api/v1/addresses                # Create address
PUT    /api/v1/addresses/{id}           # Update address
DELETE /api/v1/addresses/{id}           # Delete address
POST   /api/v1/addresses/{id}/default   # Set as default
POST   /api/v1/addresses/import         # Bulk CSV import
```

### Expanded: CustomCommandsSection (Slash Commands)

Replace the stub with saved slash commands that expand to agent prompts:

**Data Model:** New `custom_commands` table in `shipagent.db`:
- `id` (UUID), `name` (slash command name, e.g. "rush"), `description` (short help text)
- `prompt` (the full prompt text sent to the agent), `category` (optional grouping)
- `sort_order` (display ordering), `created_at`, `updated_at`

**UI Components (Settings):**
- Command list showing name, description, prompt preview
- Create/edit form: name field, description field, prompt textarea
- Delete with confirmation
- Drag-to-reorder (sort_order)

**UI Components (Chat Input):**
- Typing `/` in `RichChatInput` shows a dropdown of available commands
- Autocomplete filters as user types (e.g., `/ru` shows `/rush`)
- Selecting a command expands the full prompt into the input field
- User can edit the expanded prompt before sending, or send directly

**Example Commands:**
- `/rush` → "Ship all of today's pending orders using Next Day Air with Saturday delivery"
- `/ground-all` → "Ship all unshipped orders via UPS Ground"
- `/ca-orders` → "Filter orders shipping to California and preview them"

**Backend Routes:**
```
GET    /api/v1/commands                 # List all commands
POST   /api/v1/commands                 # Create command
PUT    /api/v1/commands/{id}            # Update command
DELETE /api/v1/commands/{id}            # Delete command
PUT    /api/v1/commands/reorder         # Bulk update sort_order
```

### Unchanged

- `provider_connections` table — unchanged
- `SettingsFlyout` container — unchanged

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| PyInstaller hidden imports | Extensive `.spec` file; CI smoke test that starts bundled binary and hits `/health` |
| MCP self-spawn from bundle | `is_bundled()` check in `config.py`; integration test that verifies MCP tool calls work in bundled mode |
| Binary size (~200MB) | Strip symbols, exclude unused stdlib; UPX optional; monitor in CI |
| Sidecar startup latency (~2-3s) | Loading splash in WebView; investigate lazy import optimization |
| Keychain access denied | Graceful fallback to prompted re-entry; clear error messaging |
| Apple notarization failures | Test with `spctl --assess` in CI; build on Apple Silicon runner |
| `ups-mcp` git dependency | PyInstaller bundles the installed package; no runtime git access needed |

## Out of Scope

- Windows/Linux builds (fast-follow)
- API key proxy service (BYOK now, proxy later)
- Horizontal scaling (multi-worker)
- Mac App Store distribution (Developer ID only)
