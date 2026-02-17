# ShipAgent Headless Automation Suite — Design Document

**Date:** 2026-02-16
**Status:** Approved
**Codename:** Industrial Core (v3.0)

---

## 1. Problem Statement

ShipAgent currently requires a web browser and manual interaction. This limits adoption in:

- **Automated workflows** — ERP systems generating files need zero-touch shipping
- **Constrained hardware** — Raspberry Pi warehouse appliances run headless
- **Scripted integrations** — IT teams need CLI tools for shell scripts and pipelines

## 2. Solution: Layered CLI Architecture

A unified `shipagent` CLI tool with two runtime modes sharing a common protocol:

- **HTTP Client mode** (default) — thin client talking to the daemon over HTTP
- **Standalone mode** (`--standalone`) — runs the full agent stack in-process

### Why This Approach

- **Concurrency safety**: daemon mode ensures one process owns the DB and MCP clients
- **Dev velocity**: standalone mode allows rapid iteration without spinning up a server
- **Unified surface**: same commands work in both modes; scripts are portable

## 3. Source Structure

```
src/cli/
├── __init__.py
├── main.py              # Typer app, command groups, global --standalone flag
├── protocol.py          # ShipAgentClient protocol (abstract interface)
├── factory.py           # get_client(standalone) → HttpClient | InProcessRunner
├── http_client.py       # HttpClient — httpx calls to daemon API
├── runner.py            # InProcessRunner — direct service/agent calls
├── daemon.py            # shipagent daemon start/stop — embedded uvicorn
├── repl.py              # shipagent interact — conversational agent REPL
├── watchdog.py          # HotFolderService — filesystem watcher (daemon-embedded)
├── config.py            # YAML config loader + env var merge + Pydantic validation
├── output.py            # Rich tables, JSON formatter, progress bars
├── progress.py          # CLI adapter for BatchEngine progress callbacks
└── auto_confirm.py      # Rule-based approval engine
```

## 4. Protocol: ShipAgentClient

Both `HttpClient` and `InProcessRunner` implement this protocol. `main.py` never knows which it's talking to.

```python
from typing import Protocol, AsyncIterator

class ShipAgentClient(Protocol):
    # Lifecycle (Context Manager)
    async def __aenter__(self) -> "ShipAgentClient": ...
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...

    # Session Management (REPL)
    async def create_session(self, interactive: bool = False) -> str: ...
    async def delete_session(self, session_id: str) -> None: ...

    # File Operations
    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult: ...

    # Job Operations
    async def list_jobs(self, status: str | None) -> list[JobSummary]: ...
    async def get_job(self, job_id: str) -> JobDetail: ...
    async def get_job_rows(self, job_id: str) -> list[RowDetail]: ...
    async def cancel_job(self, job_id: str) -> None: ...
    async def approve_job(self, job_id: str) -> None: ...
    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]: ...

    # Agent Conversation
    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]: ...

    # System
    async def health(self) -> HealthStatus: ...
    async def cleanup(self) -> None: ...
```

## 5. CLI Command Surface

```
shipagent                                    # Help + version
shipagent daemon start [--config PATH]       # Start server + watchdog
shipagent daemon stop                        # Graceful SIGTERM via PID file
shipagent daemon status                      # Health check

shipagent submit <file> [--command "..."]    # Import + agent command
    [--auto-confirm]                         # Apply auto-confirm rules
    [--service "UPS Ground"]                 # Service shorthand
    [--standalone]                           # In-process mode
    [--json]                                 # JSON output

shipagent job list [--status ...] [--json]
shipagent job inspect <job_id> [--json]      # Detail + rows + violations
shipagent job approve <job_id>               # Override auto-confirm rejection
shipagent job cancel <job_id>
shipagent job logs <job_id> [-f]             # Stream progress (-f = follow)

shipagent interact [--standalone]            # Conversational REPL
    [--session <id>]                         # Resume existing session

shipagent config show                        # Resolved config (secrets masked)
shipagent config validate [--config PATH]    # Validate YAML

shipagent version                            # Version + deps
```

### Submit Defaults

If `--command` is omitted, defaults to `"Ship all orders"`. If the file has ambiguous data, the agent will ask clarifying questions through the normal tool flow.

## 6. Daemon & Watchdog

### Daemon (`src/cli/daemon.py`)

- Wraps `uvicorn.run()` programmatically (no subprocess)
- Writes PID to `~/.shipagent/daemon.pid`
- `stop` reads PID file, sends SIGTERM; checks for stale PIDs via `os.kill(pid, 0)`
- `status` checks PID alive + calls `/api/v1/health` endpoint

### Watchdog (`src/cli/watchdog.py`)

`HotFolderService` runs inside the daemon process, started in the FastAPI lifespan. Uses the `watchdog` library with a thread bridge to the async event loop.

**Processing pipeline:**

1. **Debounce** — wait 2s after last write event
2. **Lock** — per-directory lock prevents duplicate processing
3. **Claim** — move file to `.processing/` subfolder
4. **Import** — `get_data_gateway().import_csv()` or `import_excel()`
5. **Agent session** — create headless session with folder's configured command
6. **Auto-confirm** — evaluate rules; if rejected, job stays pending
7. **Move** — success: `processed/`; failure: `failed/` with `.error` sidecar

**File lifecycle:**

```
inbox/priority/
├── orders.csv              ← dropped by ERP
├── .processing/            ← claimed during processing
│   └── orders.csv
├── processed/              ← moved on success
│   └── orders.csv
└── failed/                 ← moved on failure
    ├── orders.csv
    └── orders.csv.error    ← JSON error details
```

**Startup scan:** On daemon start, scans inbox directories for existing files dropped while the daemon was down. Processes backlog before entering watch mode.

**Thread model:** `watchdog` library thread → `loop.call_soon_threadsafe()` → async event loop. All agent/MCP/DB work stays on the main async loop.

**Watch directories:** Configured entirely through `shipagent.yaml` under `watch_folders[].path`. Operators define which directories to monitor, what command to run, and what auto-confirm rules apply per directory.

## 7. Configuration (`shipagent.yaml`)

YAML config loaded from (priority order):
1. `--config <path>` CLI flag
2. `./shipagent.yaml` (working directory)
3. `~/.shipagent/config.yaml` (user home)

Environment variables override YAML: `SHIPAGENT_<SECTION>_<KEY>`.
`${VAR}` references in YAML values resolve from environment at load time.

### Full Schema

```yaml
daemon:
  host: "127.0.0.1"
  port: 8000
  workers: 1                        # Always 1 (SQLite constraint)
  pid_file: "~/.shipagent/daemon.pid"
  log_level: "info"                 # debug | info | warning | error
  log_format: "text"                # text | json
  log_file: null                    # null = stdout; path = rotating file

auto_confirm:
  enabled: false                    # Global kill switch
  max_cost_cents: 50000             # $500 total cap
  max_rows: 500                     # Row count cap
  max_cost_per_row_cents: 5000      # $50 per-row outlier detection
  allowed_services:                 # Whitelist service codes
    - "03"                          # UPS Ground
    - "02"                          # UPS 2nd Day Air
  require_valid_addresses: true     # Block on address validation failure
  allow_warnings: false             # Block on address warnings (corrections)

watch_folders:
  - path: "./inbox/priority"
    command: "Ship all orders using UPS Next Day Air"
    auto_confirm: true              # Per-folder override
    max_cost_cents: 100000
    max_rows: 200
    file_types: [".csv", ".xlsx"]

  - path: "./inbox/ground"
    command: "Ship all orders using UPS Ground"
    auto_confirm: true
    file_types: [".csv"]
    # inherits global auto_confirm thresholds

shipper:                            # Optional — overrides env vars
  name: "Acme Corp"
  attention_name: "Shipping Dept"
  address_line: "123 Main St"
  city: "Los Angeles"
  state: "CA"
  postal_code: "90001"
  country_code: "US"
  phone: "5551234567"

ups:                                # Optional — overrides env vars
  account_number: "${UPS_ACCOUNT_NUMBER}"
  client_id: "${UPS_CLIENT_ID}"
  client_secret: "${UPS_CLIENT_SECRET}"
```

### Config Models (Pydantic)

```python
class DaemonConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    pid_file: str = "~/.shipagent/daemon.pid"
    log_level: str = "info"
    log_format: str = "text"
    log_file: str | None = None

class AutoConfirmRules(BaseModel):
    enabled: bool = False
    max_cost_cents: int = 50000
    max_rows: int = 500
    max_cost_per_row_cents: int = 5000
    allowed_services: list[str] = []
    require_valid_addresses: bool = True
    allow_warnings: bool = False

class WatchFolderConfig(BaseModel):
    path: str
    command: str
    auto_confirm: bool = False
    max_cost_cents: int | None = None      # None = inherit global
    max_rows: int | None = None
    file_types: list[str] = [".csv", ".xlsx"]

class ShipAgentConfig(BaseModel):
    daemon: DaemonConfig = DaemonConfig()
    auto_confirm: AutoConfirmRules = AutoConfirmRules()
    watch_folders: list[WatchFolderConfig] = []
    shipper: ShipperConfig | None = None
    ups: UPSConfig | None = None
```

## 8. Auto-Confirm Engine

### Data Models

```python
@dataclass
class AutoConfirmResult:
    approved: bool
    reason: str                          # Human-readable
    violations: list[RuleViolation]

@dataclass
class RuleViolation:
    rule: str           # "max_cost_cents" | "max_rows" | ...
    threshold: Any
    actual: Any
    message: str        # "Total cost $623.50 exceeds limit $500.00"
```

### Evaluation Order

1. `max_rows` — reject early before cost calculation
2. `max_cost_cents` — total estimated cost
3. `max_cost_per_row_cents` — per-row outlier detection
4. `allowed_services` — every row's service code must be whitelisted
5. `require_valid_addresses` — all addresses must validate
6. `allow_warnings` — if false, address corrections also block

### Rejection Behavior

- Job stays in `pending` status with violation metadata
- Daemon logs rejection with full details
- Operator can `shipagent job inspect <id>` to see violations
- Operator can `shipagent job approve <id>` to manually override

## 9. REPL (`shipagent interact`)

Full conversational agent session in the terminal using Rich for rendering.

### Behaviors

- **Ephemeral session** by default; `--session <id>` to resume
- Agent streaming renders token-by-token
- Preview events render as Rich tables with confirm/cancel/refine prompt
- Progress events render as Rich progress bars
- Completion events show tracking numbers + label paths
- `Ctrl+C` interrupts current agent response
- `Ctrl+D` exits REPL and cleans up session

### Logs Streaming

`shipagent job logs <id> -f` streams progress events. Handles daemon restarts gracefully with reconnect + backoff.

## 10. Dependencies (New)

| Package | Purpose |
|---------|---------|
| `typer[all]` | CLI framework with auto-completion |
| `httpx` | Async HTTP client for daemon communication |
| `rich` | Terminal UI (tables, progress, panels) |
| `watchdog` | Filesystem event monitoring |
| `pyyaml` | YAML config parsing |

## 11. Reusable Components (No Changes Needed)

These existing services work as-is in both HTTP and standalone modes:

- `src/db/connection.py:init_db()` — Database initialization
- `src/services/agent_session_manager.py:AgentSessionManager` — Session lifecycle
- `src/services/gateway_provider.py` — MCP client singletons
- `src/services/job_service.py:JobService` — Job CRUD + state machine
- `src/services/batch_engine.py:BatchEngine` — Preview + execution
- `src/orchestrator/agent/client.py:OrchestrationAgent` — Claude agent
- `src/orchestrator/agent/system_prompt.py:build_system_prompt()` — Dynamic prompts

## 12. Entry Point Registration

```toml
# pyproject.toml
[project.scripts]
shipagent = "src.cli.main:app"
```

## 13. Implementation Phases

1. **CLI Skeleton & Config** — `src/cli/` scaffold, YAML loader, Pydantic models
2. **Daemon Entrypoint** — `shipagent daemon start/stop/status`, PID management
3. **HTTP Client** — `HttpClient` implementing `ShipAgentClient` protocol
4. **Job Commands** — `list`, `inspect`, `approve`, `cancel`, `logs`
5. **Submit Command** — file import + agent processing + auto-confirm
6. **Standalone Runner** — `InProcessRunner` implementing same protocol
7. **REPL** — conversational agent in terminal
8. **Watchdog** — `HotFolderService` in daemon lifespan
9. **System Packaging** — systemd service file, structured logging
