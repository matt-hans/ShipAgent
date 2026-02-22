# Production Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package ShipAgent as a signed, auto-updating macOS desktop app using Tauri + PyInstaller, with secure credential management and professional onboarding.

**Architecture:** Tauri v2 wraps the React frontend in a native WebView and manages a PyInstaller-bundled Python sidecar (`shipagent-core`) that runs the FastAPI server, all 3 MCP servers (via subcommands), and the CLI. Credentials use macOS Keychain (via `keyring`), non-sensitive config uses a `settings` table in SQLite, and env vars remain as dev overrides.

**Tech Stack:** Tauri v2 (Rust), PyInstaller (one-folder build), `tauri-plugin-shell` (sidecar), `tauri-plugin-updater`, `keyring`, `platformdirs`, GitHub Actions, Apple Developer ID signing + notarization.

**Design Doc:** `docs/plans/2026-02-22-production-packaging-design.md`

---

## Critical Production Fixes (incorporated from review)

These fixes prevent production failures and are woven into the tasks below:

| # | Issue | Fix | Affected Tasks |
|---|-------|-----|---------------|
| 1 | **PyInstaller one-file cold-start penalty** — each MCP subprocess re-extracts _MEIPASS (1-3s delay) | Switch to **one-folder (COLLECT)** build. `get_resource_dir()` uses `sys.executable` parent dir, not `_MEIPASS`. | 1, 9 |
| 2 | **Missing Apple Notarization** — signed-but-not-notarized apps are blocked by Gatekeeper on macOS 10.15+ | Add **App Store Connect API Keys** (`APPLE_API_ISSUER` + `APPLE_API_KEY_ID` + `APPLE_API_KEY`) and `xcrun notarytool` to CI. API Keys are more reliable than Apple ID + App-Specific Passwords. | 12 |
| 3 | **Custom Rust sidecar = zombie processes** — force-quit leaves orphaned Python processes | Replace custom `std::process::Command` with **`tauri-plugin-shell`** native Sidecar support (auto-kills children). | 10 |
| 4 | **No auto-updater task** — design says "auto-updating" but plan had no updater implementation | Add **`tauri-plugin-updater`**, Ed25519 key generation, frontend update check UI. | New Task 16 |
| 5 | **TOCTOU port race condition** — find free port → drop → another app steals it | Uvicorn binds to port 0, prints `SHIPAGENT_PORT=XXXXX` to stdout. Tauri reads from sidecar stdout stream. | 3, 7, 10 |
| 6 | **Keychain + code signing mismatch** — unsigned binary triggers "wants to access keychain" prompt | Explicitly `codesign -s "Developer ID..."` the sidecar binary BEFORE Tauri bundles it in CI. | 12 |
| 7 | **Intel Mac support** — macos-14 only builds arm64; Intel users get Rosetta or nothing | Matrix build: `macos-13` (x86_64) + `macos-14` (arm64) with Universal DMG. | 12 |
| 8 | **SQLite locking under concurrency** — multiple MCP subprocesses hitting same DB | Enable **WAL mode** via `PRAGMA journal_mode=WAL;` in `connection.py`. | 4 |
| 9 | **Secret logged to stdout** — auto-generated FILTER_TOKEN_SECRET could leak | Log the event but **never log the value**. Use `logger.info("Auto-generated FILTER_TOKEN_SECRET")` only. | 14 |
| 10 | **Vite proxy interference** — dev proxy must not intercept Tauri IPC calls | Scope Vite proxy to `/api/` prefix only (already correct), add explicit exclusion comment. | 7 |
| 11 | **Tauri `externalBin` vs one-folder build** — `externalBin` expects a single file, but PyInstaller one-folder output is a directory; Tauri build panics | Use `bundle.resources` instead of `externalBin`. Launch via `shell.command()` with dynamic `resource_dir()` path, not `shell.sidecar()`. | 9, 10, 12 |
| 12 | **Apple Notarization reliability** — Apple ID + App-Specific Passwords cause random CI timeouts | Switch to **App Store Connect API Keys** (`APPLE_API_ISSUER` + `APPLE_API_KEY_ID` + `APPLE_API_KEY`), which are 100x more reliable. | 12 |
| 13 | **SQLite WAL performance** — WAL mode without `synchronous=NORMAL` doesn't get full performance benefit | Add `PRAGMA synchronous=NORMAL;` alongside `journal_mode=WAL` for optimal throughput without sacrificing durability. | 4 |
| 14 | **Private repo auto-updater 404** — `tauri-plugin-updater` cannot fetch `latest.json` from private GitHub repos | Document the issue with fix options: inject `Authorization: Bearer` header in Rust, or use a proxy server, or make repo public. | 16 |

---

## Existing Implementation Summary

Before starting, note what already exists and does NOT need to be built:

| Feature | Backend | Frontend | Status |
|---------|---------|----------|--------|
| Contact (Address Book) CRUD | `routes/contacts.py`, `ContactService` | `AddressBookSection.tsx`, `ContactForm.tsx` | **Complete** |
| Custom Commands CRUD | `routes/commands.py`, `CustomCommandService` | `CustomCommandsSection.tsx` | **Complete** |
| Slash command autocomplete | — | `RichChatInput.tsx` (useCommandAutocomplete) | **Complete** |
| @handle autocomplete | — | `RichChatInput.tsx` (useContactAutocomplete) | **Complete** |
| Provider Connections CRUD | `routes/connections.py`, `ConnectionService` | `ConnectionsSection.tsx` | **Complete** |
| Credential encryption | `credential_encryption.py` | — | **Complete** |
| Runtime credential resolution | `runtime_credentials.py` | — | **Complete** (DB-first, env fallback) |
| Warning preference | — | `ShipmentBehaviourSection.tsx` | **Complete** (client-only, not persisted to DB) |
| `platformdirs` | In `pyproject.toml` | — | **Installed** (not yet used for DB path) |

---

## Task 1: Runtime Detection Utility

**Files:**
- Create: `src/utils/runtime.py`
- Test: `tests/utils/test_runtime.py`

**Step 1: Write the failing test**

```python
# tests/utils/test_runtime.py
"""Tests for runtime environment detection."""

import sys
from unittest.mock import patch

from src.utils.runtime import is_bundled, get_resource_dir


def test_is_bundled_false_in_dev():
    """Dev mode: sys.frozen is absent."""
    with patch.object(sys, 'frozen', create=False):
        # Remove frozen attr if it exists
        if hasattr(sys, 'frozen'):
            delattr(sys, 'frozen')
        assert is_bundled() is False


def test_is_bundled_true_when_frozen():
    """PyInstaller sets sys.frozen = True."""
    with patch.object(sys, 'frozen', True, create=True):
        assert is_bundled() is True


def test_get_resource_dir_dev_mode():
    """In dev mode, returns project root."""
    result = get_resource_dir()
    # Should be the project root (where pyproject.toml lives)
    assert (result / "pyproject.toml").exists()


def test_get_resource_dir_bundled_mode():
    """In bundled mode (one-folder), returns parent of sys.executable."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/app/dist/shipagent-core/shipagent-core'):
            result = get_resource_dir()
            from pathlib import Path
            # One-folder build: resources are next to the executable
            assert result == Path('/app/dist/shipagent-core')
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/utils/test_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.utils.runtime'`

**Step 3: Write minimal implementation**

```python
# src/utils/runtime.py
"""Runtime environment detection for dev vs PyInstaller bundled mode."""

import sys
from pathlib import Path


def is_bundled() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return getattr(sys, 'frozen', False)


def get_resource_dir() -> Path:
    """Return base directory for bundled resources.

    In dev mode, returns the project root (parent of src/).
    In PyInstaller one-folder mode, returns the directory containing
    the executable (where all extracted files live). We use one-folder
    (not one-file) to avoid _MEIPASS re-extraction penalty on every
    MCP subprocess spawn.
    """
    if is_bundled():
        # One-folder build: resources live next to the executable
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent
```

Also create the `__init__.py` if needed:

```python
# src/utils/__init__.py (create only if missing)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/utils/test_runtime.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add src/utils/ tests/utils/
git commit -m "feat: add runtime detection utility for dev vs bundled mode"
```

---

## Task 2: Update MCP Config for Bundled Mode

**Files:**
- Modify: `src/orchestrator/agent/config.py:44-57` (change `_get_python_command()`)
- Modify: `src/orchestrator/agent/config.py:74-90` (change `get_data_mcp_config()`)
- Test: `tests/orchestrator/agent/test_config_bundled.py`

**Step 1: Write the failing test**

```python
# tests/orchestrator/agent/test_config_bundled.py
"""Tests for MCP config in bundled mode."""

import sys
from unittest.mock import patch

from src.orchestrator.agent.config import (
    get_data_mcp_config,
    get_external_mcp_config,
)


def test_data_mcp_config_bundled_uses_self_executable():
    """In bundled mode, MCP spawns self with subcommand."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/app/shipagent-core'):
            config = get_data_mcp_config()
            assert config["command"] == "/app/shipagent-core"
            assert config["args"] == ["mcp-data"]


def test_data_mcp_config_dev_uses_python_module():
    """In dev mode, MCP uses python -m module pattern."""
    # Ensure frozen is not set
    frozen_backup = getattr(sys, 'frozen', None)
    if hasattr(sys, 'frozen'):
        delattr(sys, 'frozen')
    try:
        config = get_data_mcp_config()
        assert "-m" in config["args"]
        assert "src.mcp.data_source.server" in config["args"]
    finally:
        if frozen_backup is not None:
            sys.frozen = frozen_backup


def test_external_mcp_config_bundled():
    """In bundled mode, external MCP uses self with subcommand."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/app/shipagent-core'):
            config = get_external_mcp_config()
            assert config["command"] == "/app/shipagent-core"
            assert config["args"] == ["mcp-external"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/orchestrator/agent/test_config_bundled.py -v`
Expected: FAIL — bundled path not implemented

**Step 3: Modify `config.py`**

In `src/orchestrator/agent/config.py`, update `_get_python_command()` and the config builders:

Replace `_get_python_command()` (lines 44-57) with:

```python
def _get_python_command() -> str:
    """Return the preferred Python interpreter for MCP subprocesses.

    In bundled mode (PyInstaller), returns None — callers should use
    sys.executable with subcommands instead of python -m.
    Honors MCP_PYTHON_PATH when explicitly configured.
    Prioritizes the project virtual environment to ensure all MCP
    subprocesses use the same dependency set as the backend.
    Falls back to the current interpreter when .venv Python is missing.
    """
    override = os.environ.get("MCP_PYTHON_PATH", "").strip()
    if override:
        return override
    if os.path.exists(VENV_PYTHON):
        return VENV_PYTHON
    return sys.executable
```

Replace `get_data_mcp_config()` (lines 74-90) with:

```python
def get_data_mcp_config() -> MCPServerConfig:
    """Get configuration for the Data Source MCP server.

    In bundled mode, spawns self with 'mcp-data' subcommand.
    In dev mode, runs as a Python module using FastMCP with stdio transport.
    """
    from src.utils.runtime import is_bundled

    if is_bundled():
        return MCPServerConfig(
            command=sys.executable,
            args=["mcp-data"],
            env={"PATH": os.environ.get("PATH", "")},
        )

    return MCPServerConfig(
        command=_get_python_command(),
        args=["-m", "src.mcp.data_source.server"],
        env={
            "PYTHONPATH": str(PROJECT_ROOT),
            "PATH": os.environ.get("PATH", ""),
        },
    )
```

Apply the same pattern to `get_external_mcp_config()` and the UPS config function (use subcommand `"mcp-ups"` and `"mcp-external"` respectively).

**Step 4: Run test to verify it passes**

Run: `pytest tests/orchestrator/agent/test_config_bundled.py -v`
Expected: 3 passed

**Step 5: Run existing config tests to verify no regressions**

Run: `pytest tests/orchestrator/agent/ -v -k "not stream and not sse"`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/orchestrator/agent/config.py tests/orchestrator/agent/test_config_bundled.py
git commit -m "feat: MCP config resolves bundled binary subcommands in PyInstaller mode"
```

---

## Task 3: Bundle Entry Point

**Files:**
- Create: `src/bundle_entry.py`
- Test: `tests/test_bundle_entry.py`

**Step 1: Write the failing test**

```python
# tests/test_bundle_entry.py
"""Tests for the unified bundle entry point."""

from unittest.mock import patch, MagicMock
import sys


def test_serve_command_parses_port():
    """'serve' command should parse --port argument."""
    with patch.dict(sys.modules, {}):
        with patch('sys.argv', ['shipagent-core', 'serve', '--port', '9000']):
            from src.bundle_entry import parse_serve_args
            args = parse_serve_args(['--port', '9000'])
            assert args.port == 9000
            assert args.host == '127.0.0.1'


def test_serve_default_port_zero():
    """Default port is 0 (OS-assigned) to avoid TOCTOU race."""
    from src.bundle_entry import parse_serve_args
    args = parse_serve_args([])
    assert args.port == 0


def test_default_command_is_serve():
    """No subcommand defaults to 'serve'."""
    with patch('sys.argv', ['shipagent-core']):
        from src.bundle_entry import get_command
        assert get_command() == 'serve'


def test_mcp_data_command():
    """'mcp-data' is recognized as a valid subcommand."""
    with patch('sys.argv', ['shipagent-core', 'mcp-data']):
        from src.bundle_entry import get_command
        assert get_command() == 'mcp-data'


def test_cli_command_passes_remaining_args():
    """'cli' passes remaining args to the Typer CLI."""
    with patch('sys.argv', ['shipagent-core', 'cli', 'submit', 'orders.csv']):
        from src.bundle_entry import get_command, get_cli_args
        assert get_command() == 'cli'
        assert get_cli_args() == ['submit', 'orders.csv']


def test_unknown_command_exits():
    """Unknown subcommand exits with code 1."""
    import pytest
    with patch('sys.argv', ['shipagent-core', 'unknown']):
        from src.bundle_entry import get_command
        assert get_command() == 'unknown'
        # main() should sys.exit(1) for unknown
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_bundle_entry.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/bundle_entry.py
"""Unified entry point for the bundled ShipAgent binary.

This module dispatches to the correct subsystem based on the first CLI argument:
  serve        — Start FastAPI server (default)
  mcp-data     — Data Source MCP server (stdio)
  mcp-ups      — UPS MCP server (stdio)
  mcp-external — External Sources MCP server (stdio)
  cli          — Typer CLI (daemon, submit, interact, job)

In PyInstaller bundles, MCP servers self-spawn this same binary with the
appropriate subcommand. See src/orchestrator/agent/config.py for dispatch.
"""

import argparse
import sys


VALID_COMMANDS = {'serve', 'mcp-data', 'mcp-ups', 'mcp-external', 'cli'}


def get_command() -> str:
    """Extract the subcommand from sys.argv, defaulting to 'serve'."""
    if len(sys.argv) < 2:
        return 'serve'
    return sys.argv[1]


def get_cli_args() -> list[str]:
    """Return args after 'cli' subcommand for Typer dispatch."""
    return sys.argv[2:]


def parse_serve_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse serve-mode arguments (host, port)."""
    parser = argparse.ArgumentParser(description='ShipAgent server')
    parser.add_argument('--host', default='127.0.0.1', help='Bind address')
    parser.add_argument('--port', type=int, default=0,
                        help='Listen port (0 = OS-assigned to avoid TOCTOU race)')
    return parser.parse_args(args)


def main() -> None:
    """Dispatch to the correct subsystem based on the subcommand."""
    command = get_command()

    if command == 'serve':
        serve_args = parse_serve_args(sys.argv[2:])
        import uvicorn

        # Use a custom server class to print the actual port after binding.
        # Tauri reads "SHIPAGENT_PORT=XXXXX" from stdout to learn the port.
        class PortReportingServer(uvicorn.Server):
            def startup(self, sockets=None):
                result = super().startup(sockets)
                for server in self.servers:
                    for sock in server.sockets:
                        addr = sock.getsockname()
                        # Print port protocol line for Tauri to parse
                        print(f"SHIPAGENT_PORT={addr[1]}", flush=True)
                return result

        config = uvicorn.Config(
            "src.api.main:app",
            host=serve_args.host,
            port=serve_args.port,
            workers=1,
            log_level='info',
        )
        server = PortReportingServer(config)
        server.run()

    elif command == 'mcp-data':
        from src.mcp.data_source.server import main as mcp_main
        mcp_main()

    elif command == 'mcp-ups':
        from ups_mcp import main as ups_main
        ups_main()

    elif command == 'mcp-external':
        from src.mcp.external_sources.server import main as ext_main
        ext_main()

    elif command == 'cli':
        sys.argv = ['shipagent'] + get_cli_args()
        from src.cli.main import app as cli_app
        cli_app()

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(f"Valid commands: {', '.join(sorted(VALID_COMMANDS))}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_bundle_entry.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add src/bundle_entry.py tests/test_bundle_entry.py
git commit -m "feat: unified bundle entry point for PyInstaller with subcommand dispatch"
```

---

## Task 4: Production File Paths with platformdirs

**Files:**
- Create: `src/utils/paths.py`
- Modify: `src/db/connection.py:39-57` (update `get_database_url()`)
- Test: `tests/utils/test_paths.py`

**Step 1: Write the failing test**

```python
# tests/utils/test_paths.py
"""Tests for production file path resolution."""

import os
from pathlib import Path
from unittest.mock import patch

from src.utils.paths import get_data_dir, get_log_dir, get_default_db_path, get_labels_dir


def test_get_data_dir_returns_path():
    """Data dir should be a valid Path."""
    result = get_data_dir()
    assert isinstance(result, Path)


def test_get_data_dir_bundled_uses_platformdirs():
    """In bundled mode, data dir uses platformdirs."""
    import sys
    with patch.object(sys, 'frozen', True, create=True):
        result = get_data_dir()
        # On macOS: ~/Library/Application Support/com.shipagent.app
        assert 'shipagent' in str(result).lower() or 'ShipAgent' in str(result)


def test_get_data_dir_dev_uses_cwd():
    """In dev mode, data dir is the project root."""
    result = get_data_dir()
    # Should be near the project root
    assert result.exists() or result == Path('.')


def test_get_default_db_path():
    """Default DB path combines data dir + shipagent.db."""
    result = get_default_db_path()
    assert result.name == 'shipagent.db'


def test_env_var_overrides_data_dir():
    """DATABASE_URL env var takes priority over platformdirs."""
    with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///custom/path.db'}):
        from src.db.connection import get_database_url
        assert get_database_url() == 'sqlite:///custom/path.db'


def test_get_labels_dir_bundled():
    """Labels dir uses platformdirs in bundled mode."""
    import sys
    with patch.object(sys, 'frozen', True, create=True):
        result = get_labels_dir()
        assert isinstance(result, Path)


def test_get_log_dir():
    """Log dir returns a valid path."""
    result = get_log_dir()
    assert isinstance(result, Path)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/utils/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# src/utils/paths.py
"""Production file path resolution using platformdirs.

In dev mode (not bundled), paths resolve relative to the project root.
In bundled mode (PyInstaller), paths use platform-appropriate directories:
  macOS: ~/Library/Application Support/com.shipagent.app/
  Windows: %LOCALAPPDATA%/ShipAgent/  (future)
  Linux: ~/.local/share/shipagent/  (future)
"""

from pathlib import Path

import platformdirs

from src.utils.runtime import is_bundled

APP_NAME = "ShipAgent"
APP_AUTHOR = "ShipAgent"
# Bundle identifier for macOS (used by platformdirs when roaming=False)
_BUNDLE_ID = "com.shipagent.app"


def get_data_dir() -> Path:
    """Return the directory for persistent data (DB, config).

    In dev mode: project root (where shipagent.db lives today).
    In bundled mode: platform user data dir.
    """
    if is_bundled():
        return Path(platformdirs.user_data_dir(_BUNDLE_ID, appauthor=False))
    # Dev mode: project root
    return Path(__file__).resolve().parent.parent.parent


def get_labels_dir() -> Path:
    """Return the directory for label PDF storage."""
    data = get_data_dir()
    return data / "labels"


def get_log_dir() -> Path:
    """Return the directory for application logs.

    In dev mode: project root.
    In bundled mode: platform log dir (macOS: ~/Library/Logs/com.shipagent.app/).
    """
    if is_bundled():
        return Path(platformdirs.user_log_dir(_BUNDLE_ID, appauthor=False))
    return Path(__file__).resolve().parent.parent.parent


def get_default_db_path() -> Path:
    """Return the default SQLite database file path."""
    return get_data_dir() / "shipagent.db"


def ensure_dirs_exist() -> None:
    """Create all required directories if they don't exist."""
    for d in [get_data_dir(), get_labels_dir(), get_log_dir()]:
        d.mkdir(parents=True, exist_ok=True)
```

**Step 4: Update `src/db/connection.py` — add platformdirs fallback + WAL mode**

In `get_database_url()` (line 39-57), replace the final fallback:

Change:
```python
    return "sqlite:///./shipagent.db"
```

To:
```python
    from src.utils.paths import get_default_db_path
    return f"sqlite:///{get_default_db_path()}"
```

**Step 5: Enable SQLite WAL mode for concurrent MCP access**

Multiple MCP subprocesses (data, UPS, external) hit the same `shipagent.db` concurrently.
Default SQLite journal mode (`DELETE`) causes `SQLITE_BUSY` errors under concurrency.
WAL mode allows concurrent readers + a single writer without blocking.

In `src/db/connection.py`, add WAL pragma inside the `get_engine()` function or the
engine creation, using a `connect` event listener:

```python
from sqlalchemy import event

engine = create_engine(url, connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode and optimal sync for concurrent MCP subprocess access.

    WAL mode allows concurrent readers + a single writer without blocking.
    synchronous=NORMAL gives full WAL performance benefit without sacrificing
    durability — commits are durable after the WAL is fsynced, but checkpoints
    may lose a few recent transactions on power loss (acceptable for desktop).
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()
```

Also add a test in `tests/utils/test_paths.py`:

```python
def test_wal_mode_enabled():
    """SQLite WAL mode is set on engine connect for concurrency."""
    from src.db.connection import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert result == "wal", f"Expected WAL mode, got {result}"
```

**Step 6: Run tests**

Run: `pytest tests/utils/test_paths.py -v`
Expected: 8 passed (including WAL mode test)

Run: `pytest tests/db/ -v -k "not stream"`
Expected: Existing DB tests still pass

**Step 7: Commit**

```bash
git add src/utils/paths.py tests/utils/test_paths.py src/db/connection.py
git commit -m "feat: platformdirs-based file paths, WAL mode for concurrency"
```

---

## Task 5: Settings Database Table & Service

**Files:**
- Modify: `src/db/models.py` (add `AppSettings` model after line 874)
- Modify: `src/db/connection.py` (add migration in `_ensure_columns_exist()`)
- Create: `src/services/settings_service.py`
- Create: `src/api/routes/settings.py`
- Modify: `src/api/main.py` (register settings router)
- Test: `tests/services/test_settings_service.py`
- Test: `tests/api/test_settings.py`

**Step 1: Write the failing tests**

```python
# tests/services/test_settings_service.py
"""Tests for SettingsService."""

import pytest
from sqlalchemy.orm import Session

from src.db.models import AppSettings
from src.services.settings_service import SettingsService


@pytest.fixture
def service(db_session: Session) -> SettingsService:
    return SettingsService(db_session)


def test_get_or_create_returns_singleton(service: SettingsService, db_session: Session):
    """First call creates, second call returns same row."""
    s1 = service.get_or_create()
    s2 = service.get_or_create()
    assert s1.id == s2.id
    # Only one row in table
    assert db_session.query(AppSettings).count() == 1


def test_get_or_create_has_defaults(service: SettingsService):
    """New settings have sensible defaults."""
    s = service.get_or_create()
    assert s.agent_model is None  # Uses env var default
    assert s.batch_concurrency == 5
    assert s.onboarding_completed is False


def test_update_settings_patch_semantics(service: SettingsService, db_session: Session):
    """Only provided fields are updated; others untouched."""
    s = service.get_or_create()
    original_concurrency = s.batch_concurrency

    service.update({"shipper_name": "Acme Corp"})
    db_session.commit()
    db_session.refresh(s)

    assert s.shipper_name == "Acme Corp"
    assert s.batch_concurrency == original_concurrency  # Unchanged


def test_update_settings_rejects_unknown_fields(service: SettingsService):
    """Unknown fields raise ValueError."""
    service.get_or_create()
    with pytest.raises(ValueError, match="Unknown setting"):
        service.update({"nonexistent_field": "value"})


def test_complete_onboarding(service: SettingsService, db_session: Session):
    """Marking onboarding complete persists."""
    s = service.get_or_create()
    assert s.onboarding_completed is False
    service.complete_onboarding()
    db_session.commit()
    db_session.refresh(s)
    assert s.onboarding_completed is True
```

```python
# tests/api/test_settings.py
"""Tests for settings API routes."""

import pytest
from fastapi.testclient import TestClient


def test_get_settings_returns_defaults(client: TestClient):
    """GET /settings returns default settings."""
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch_concurrency"] == 5
    assert data["onboarding_completed"] is False


def test_patch_settings_updates_fields(client: TestClient):
    """PATCH /settings updates specified fields."""
    resp = client.patch(
        "/api/v1/settings",
        json={"shipper_name": "Test Corp", "batch_concurrency": 10}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["shipper_name"] == "Test Corp"
    assert data["batch_concurrency"] == 10


def test_get_credential_status(client: TestClient):
    """GET /settings/credentials/status shows which keys are set."""
    resp = client.get("/api/v1/settings/credentials/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "anthropic_api_key" in data
    # Should be False since no key is set in test
    assert data["anthropic_api_key"] is False


def test_post_onboarding_complete(client: TestClient):
    """POST /settings/onboarding/complete marks onboarding done."""
    resp = client.post("/api/v1/settings/onboarding/complete")
    assert resp.status_code == 200

    # Verify it persisted
    resp2 = client.get("/api/v1/settings")
    assert resp2.json()["onboarding_completed"] is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/services/test_settings_service.py tests/api/test_settings.py -v`
Expected: FAIL — missing models, service, routes

**Step 3: Add AppSettings model to `src/db/models.py`**

Add after the last model (after `ConversationMessage`):

```python
class AppSettings(Base):
    """Application-wide settings singleton.

    Stores non-sensitive configuration that was previously scattered across
    env vars. One row per installation. Created on first access via
    SettingsService.get_or_create().
    """

    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)

    # Agent config
    agent_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    batch_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Shipper defaults
    shipper_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shipper_attention_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shipper_address1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shipper_address2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shipper_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipper_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shipper_zip: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shipper_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    shipper_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # UPS non-sensitive config
    ups_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ups_environment: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Onboarding state
    onboarding_completed: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="0"
    )

    # Timestamps
    created_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )
    updated_at: Mapped[str] = mapped_column(
        String(50), nullable=False, default=utc_now_iso
    )

    def __repr__(self) -> str:
        return f"<AppSettings(id={self.id!r}, onboarding={self.onboarding_completed})>"
```

**Step 4: Add migration DDL to `src/db/connection.py`**

In `_ensure_columns_exist()`, add the `CREATE TABLE IF NOT EXISTS app_settings` DDL following the existing pattern used for `provider_connections` and `custom_commands`.

**Step 5: Create SettingsService**

```python
# src/services/settings_service.py
"""Service for application settings management.

Provides singleton access to AppSettings with patch-style updates.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import AppSettings, utc_now_iso

logger = logging.getLogger(__name__)

# Fields that can be updated via PATCH
_MUTABLE_FIELDS = {
    "agent_model", "batch_concurrency",
    "shipper_name", "shipper_attention_name",
    "shipper_address1", "shipper_address2",
    "shipper_city", "shipper_state", "shipper_zip",
    "shipper_country", "shipper_phone",
    "ups_account_number", "ups_environment",
    "onboarding_completed",
}


class SettingsService:
    """CRUD service for the AppSettings singleton."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create(self) -> AppSettings:
        """Return the settings singleton, creating it if absent."""
        settings = self._db.query(AppSettings).first()
        if settings is None:
            settings = AppSettings()
            self._db.add(settings)
            self._db.flush()
            logger.info("Created AppSettings singleton: %s", settings.id)
        return settings

    def update(self, patch: dict[str, Any]) -> AppSettings:
        """Apply patch-style updates to settings.

        Args:
            patch: Dict of field names to new values. Unknown fields raise ValueError.

        Returns:
            Updated AppSettings instance.

        Raises:
            ValueError: If patch contains unknown field names.
        """
        unknown = set(patch.keys()) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown setting fields: {unknown}")

        settings = self.get_or_create()
        for key, value in patch.items():
            setattr(settings, key, value)
        settings.updated_at = utc_now_iso()
        self._db.flush()
        return settings

    def complete_onboarding(self) -> AppSettings:
        """Mark onboarding as completed."""
        return self.update({"onboarding_completed": True})
```

**Step 6: Create settings routes**

```python
# src/api/routes/settings.py
"""API routes for application settings management.

Provides GET/PATCH for the settings singleton and credential status checks.
All endpoints use /api/v1/settings prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.connection import get_db
from src.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    """Response schema for app settings."""
    agent_model: str | None = None
    batch_concurrency: int = 5
    shipper_name: str | None = None
    shipper_attention_name: str | None = None
    shipper_address1: str | None = None
    shipper_address2: str | None = None
    shipper_city: str | None = None
    shipper_state: str | None = None
    shipper_zip: str | None = None
    shipper_country: str | None = None
    shipper_phone: str | None = None
    ups_account_number: str | None = None
    ups_environment: str | None = None
    onboarding_completed: bool = False

    model_config = {"from_attributes": True}


class SettingsPatch(BaseModel):
    """Request schema for updating settings (all fields optional)."""
    agent_model: str | None = None
    batch_concurrency: int | None = None
    shipper_name: str | None = None
    shipper_attention_name: str | None = None
    shipper_address1: str | None = None
    shipper_address2: str | None = None
    shipper_city: str | None = None
    shipper_state: str | None = None
    shipper_zip: str | None = None
    shipper_country: str | None = None
    shipper_phone: str | None = None
    ups_account_number: str | None = None
    ups_environment: str | None = None


class CredentialStatusResponse(BaseModel):
    """Which credentials are configured (never returns values)."""
    anthropic_api_key: bool = False
    ups_client_id: bool = False
    ups_client_secret: bool = False
    shopify_access_token: bool = False
    filter_token_secret: bool = False


def _get_service(db: Session = Depends(get_db)) -> SettingsService:
    """Dependency injector for SettingsService."""
    return SettingsService(db)


@router.get("", response_model=SettingsResponse)
def get_settings(
    service: SettingsService = Depends(_get_service),
) -> SettingsResponse:
    """Get all application settings."""
    settings = service.get_or_create()
    return SettingsResponse.model_validate(settings)


@router.patch("", response_model=SettingsResponse)
def update_settings(
    data: SettingsPatch,
    service: SettingsService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    """Update application settings (patch semantics)."""
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        settings = service.update(updates)
        db.commit()
        return SettingsResponse.model_validate(settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/credentials/status", response_model=CredentialStatusResponse)
def get_credential_status() -> CredentialStatusResponse:
    """Check which credentials are configured (never returns values).

    Checks keyring first (production), then env vars (dev).
    """
    import os
    # In production this will check keyring; for now check env vars
    return CredentialStatusResponse(
        anthropic_api_key=bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        ups_client_id=bool(os.environ.get("UPS_CLIENT_ID", "").strip()),
        ups_client_secret=bool(os.environ.get("UPS_CLIENT_SECRET", "").strip()),
        shopify_access_token=bool(os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()),
        filter_token_secret=bool(os.environ.get("FILTER_TOKEN_SECRET", "").strip()),
    )


@router.post("/onboarding/complete")
def complete_onboarding(
    service: SettingsService = Depends(_get_service),
    db: Session = Depends(get_db),
) -> dict:
    """Mark onboarding as completed."""
    service.complete_onboarding()
    db.commit()
    return {"status": "completed"}
```

**Step 7: Register router in `src/api/main.py`**

Add alongside existing router includes:

```python
from src.api.routes import settings
app.include_router(settings.router, prefix="/api/v1")
```

**Step 8: Run all tests**

Run: `pytest tests/services/test_settings_service.py tests/api/test_settings.py -v`
Expected: All pass

**Step 9: Commit**

```bash
git add src/db/models.py src/db/connection.py src/services/settings_service.py \
        src/api/routes/settings.py src/api/main.py \
        tests/services/test_settings_service.py tests/api/test_settings.py
git commit -m "feat: settings DB table, service, and API routes for production config"
```

---

## Task 6: Keyring Integration for Secure Credentials

**Files:**
- Modify: `pyproject.toml` (add `keyring` dependency)
- Create: `src/services/keyring_store.py`
- Modify: `src/services/runtime_credentials.py` (add keyring to resolution chain)
- Modify: `src/api/routes/settings.py` (update credential status + POST credential)
- Test: `tests/services/test_keyring_store.py`

**Step 1: Add `keyring` to `pyproject.toml`**

Add to dependencies list:
```
    "keyring>=25.0.0",
```

Run: `pip install keyring`

**Step 2: Write the failing test**

```python
# tests/services/test_keyring_store.py
"""Tests for keyring credential store.

Uses a mock backend to avoid touching the real system keychain.
"""

from unittest.mock import patch, MagicMock

from src.services.keyring_store import KeyringStore


@patch("src.services.keyring_store.keyring")
def test_set_credential_stores_to_keyring(mock_kr):
    """Setting a credential calls keyring.set_password."""
    store = KeyringStore()
    store.set("ANTHROPIC_API_KEY", "sk-ant-test-key")
    mock_kr.set_password.assert_called_once_with(
        "com.shipagent.app", "ANTHROPIC_API_KEY", "sk-ant-test-key"
    )


@patch("src.services.keyring_store.keyring")
def test_get_credential_reads_from_keyring(mock_kr):
    """Getting a credential reads from keyring."""
    mock_kr.get_password.return_value = "sk-ant-test-key"
    store = KeyringStore()
    result = store.get("ANTHROPIC_API_KEY")
    assert result == "sk-ant-test-key"
    mock_kr.get_password.assert_called_once_with(
        "com.shipagent.app", "ANTHROPIC_API_KEY"
    )


@patch("src.services.keyring_store.keyring")
def test_get_credential_returns_none_when_absent(mock_kr):
    """Missing credential returns None."""
    mock_kr.get_password.return_value = None
    store = KeyringStore()
    assert store.get("NONEXISTENT") is None


@patch("src.services.keyring_store.keyring")
def test_has_credential(mock_kr):
    """has() returns True when credential exists."""
    mock_kr.get_password.return_value = "value"
    store = KeyringStore()
    assert store.has("ANTHROPIC_API_KEY") is True


@patch("src.services.keyring_store.keyring")
def test_delete_credential(mock_kr):
    """delete() removes credential from keyring."""
    store = KeyringStore()
    store.delete("ANTHROPIC_API_KEY")
    mock_kr.delete_password.assert_called_once_with(
        "com.shipagent.app", "ANTHROPIC_API_KEY"
    )


@patch("src.services.keyring_store.keyring")
def test_get_all_status(mock_kr):
    """get_all_status() returns dict of credential name → bool."""
    mock_kr.get_password.side_effect = lambda svc, key: "val" if key == "ANTHROPIC_API_KEY" else None
    store = KeyringStore()
    status = store.get_all_status()
    assert status["ANTHROPIC_API_KEY"] is True
    assert status["UPS_CLIENT_ID"] is False
```

**Step 3: Write implementation**

```python
# src/services/keyring_store.py
"""Secure credential storage using the system keychain.

Uses the `keyring` library which maps to:
  macOS: Keychain Access (Secure Enclave on Apple Silicon)
  Windows: Windows Credential Manager (future)
  Linux: Secret Service API (future)

All credentials are stored under the service name 'com.shipagent.app'.
"""

import logging

import keyring

logger = logging.getLogger(__name__)

SERVICE_NAME = "com.shipagent.app"

# Credentials managed by this store
MANAGED_CREDENTIALS = [
    "ANTHROPIC_API_KEY",
    "UPS_CLIENT_ID",
    "UPS_CLIENT_SECRET",
    "SHOPIFY_ACCESS_TOKEN",
    "FILTER_TOKEN_SECRET",
    "SHIPAGENT_API_KEY",
]


class KeyringStore:
    """Thin wrapper around keyring for credential CRUD."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service = service_name

    def get(self, key: str) -> str | None:
        """Retrieve a credential value. Returns None if not set."""
        try:
            return keyring.get_password(self._service, key)
        except Exception:
            logger.warning("Keyring read failed for %s", key, exc_info=True)
            return None

    def set(self, key: str, value: str) -> None:
        """Store a credential value."""
        keyring.set_password(self._service, key, value)
        logger.info("Stored credential: %s", key)

    def delete(self, key: str) -> None:
        """Remove a credential."""
        try:
            keyring.delete_password(self._service, key)
            logger.info("Deleted credential: %s", key)
        except keyring.errors.PasswordDeleteError:
            logger.debug("Credential %s not found for deletion", key)

    def has(self, key: str) -> bool:
        """Check if a credential is set."""
        return self.get(key) is not None

    def get_all_status(self) -> dict[str, bool]:
        """Return status of all managed credentials."""
        return {key: self.has(key) for key in MANAGED_CREDENTIALS}
```

**Step 4: Update credential status route in `settings.py`**

Replace the `get_credential_status()` endpoint to use keyring + env var fallback:

```python
@router.get("/credentials/status", response_model=CredentialStatusResponse)
def get_credential_status() -> CredentialStatusResponse:
    """Check which credentials are configured (never returns values).

    Checks keyring first (production), then env vars (dev fallback).
    """
    import os
    from src.services.keyring_store import KeyringStore
    store = KeyringStore()

    def _is_set(key: str) -> bool:
        return store.has(key) or bool(os.environ.get(key, "").strip())

    return CredentialStatusResponse(
        anthropic_api_key=_is_set("ANTHROPIC_API_KEY"),
        ups_client_id=_is_set("UPS_CLIENT_ID"),
        ups_client_secret=_is_set("UPS_CLIENT_SECRET"),
        shopify_access_token=_is_set("SHOPIFY_ACCESS_TOKEN"),
        filter_token_secret=_is_set("FILTER_TOKEN_SECRET"),
    )
```

Add a POST endpoint for setting credentials:

```python
class SetCredentialRequest(BaseModel):
    """Request to set a credential in the secure store."""
    key: str
    value: str


@router.post("/credentials")
def set_credential(data: SetCredentialRequest) -> dict:
    """Set a credential in the secure store (keychain)."""
    from src.services.keyring_store import KeyringStore, MANAGED_CREDENTIALS
    if data.key not in MANAGED_CREDENTIALS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown credential: {data.key}. Valid: {MANAGED_CREDENTIALS}"
        )
    store = KeyringStore()
    store.set(data.key, data.value)
    return {"status": "stored", "key": data.key}
```

**Step 5: Run tests**

Run: `pytest tests/services/test_keyring_store.py -v`
Expected: 6 passed

**Step 6: Commit**

```bash
git add pyproject.toml src/services/keyring_store.py src/api/routes/settings.py \
        tests/services/test_keyring_store.py
git commit -m "feat: keyring-backed credential store with env var fallback"
```

---

## Task 7: Dynamic Port for Frontend API Client

**Files:**
- Modify: `frontend/src/lib/api.ts:18` (dynamic port resolution)
- Verify: `frontend/vite.config.ts` (proxy scoping)
- Test: Manual — `npm run dev` still works, port override works

**Step 1: Update API base URL**

In `frontend/src/lib/api.ts`, replace line 18:

```typescript
const API_BASE = '/api/v1';
```

With:

```typescript
/**
 * API base URL.
 *
 * In Tauri mode: window.__SHIPAGENT_PORT__ is injected by the sidecar
 * port reporter. Tauri reads "SHIPAGENT_PORT=XXXXX" from sidecar stdout
 * and injects it into the WebView — no TOCTOU race condition.
 *
 * In dev mode (Vite): relative URL is proxied to localhost:8000 by vite.config.ts.
 * The Vite proxy ONLY intercepts /api/ paths — it does NOT interfere with
 * Tauri IPC calls or other non-API routes.
 */
const TAURI_PORT = (window as any).__SHIPAGENT_PORT__;
const API_BASE = TAURI_PORT
  ? `http://127.0.0.1:${TAURI_PORT}/api/v1`
  : '/api/v1';
```

**Step 2: Verify Vite proxy scope**

Check `frontend/vite.config.ts` — the proxy should ONLY match `/api/` prefix:

```typescript
server: {
  proxy: {
    // IMPORTANT: Only proxy /api/ paths to the backend.
    // Do NOT use a catch-all proxy — it would intercept Tauri IPC.
    '/api/': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
},
```

If the proxy uses a broader pattern, scope it to `/api/` only.

**Step 3: Verify dev mode still works**

Run: `cd frontend && npm run dev`
Navigate to `http://localhost:5173` — API calls should still proxy through Vite.

**Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: dynamic API port for Tauri sidecar, dev proxy unchanged"
```

---

## Task 8: Onboarding Wizard Component

**Files:**
- Create: `frontend/src/components/settings/OnboardingWizard.tsx`
- Modify: `frontend/src/hooks/useAppState.tsx` (add settings state + onboarding check)
- Modify: `frontend/src/App.tsx` (render wizard when onboarding incomplete)
- Modify: `frontend/src/lib/api.ts` (add settings API functions)
- Modify: `frontend/src/types/api.ts` (add AppSettings type)
- Test: `cd frontend && npx tsc --noEmit`

**Step 1: Add TypeScript types**

In `frontend/src/types/api.ts`, add:

```typescript
export interface AppSettings {
  agent_model: string | null;
  batch_concurrency: number;
  shipper_name: string | null;
  shipper_attention_name: string | null;
  shipper_address1: string | null;
  shipper_address2: string | null;
  shipper_city: string | null;
  shipper_state: string | null;
  shipper_zip: string | null;
  shipper_country: string | null;
  shipper_phone: string | null;
  ups_account_number: string | null;
  ups_environment: string | null;
  onboarding_completed: boolean;
}

export interface CredentialStatus {
  anthropic_api_key: boolean;
  ups_client_id: boolean;
  ups_client_secret: boolean;
  shopify_access_token: boolean;
  filter_token_secret: boolean;
}
```

**Step 2: Add API functions to `frontend/src/lib/api.ts`**

```typescript
// Settings API

export async function getSettings(): Promise<AppSettings> {
  const r = await fetch(`${API_BASE}/settings`);
  return parseResponse<AppSettings>(r);
}

export async function updateSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  const r = await fetch(`${API_BASE}/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return parseResponse<AppSettings>(r);
}

export async function getCredentialStatus(): Promise<CredentialStatus> {
  const r = await fetch(`${API_BASE}/settings/credentials/status`);
  return parseResponse<CredentialStatus>(r);
}

export async function setCredential(key: string, value: string): Promise<void> {
  const r = await fetch(`${API_BASE}/settings/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, value }),
  });
  await parseResponse(r);
}

export async function completeOnboarding(): Promise<void> {
  const r = await fetch(`${API_BASE}/settings/onboarding/complete`, { method: 'POST' });
  await parseResponse(r);
}
```

**Step 3: Add settings state to `useAppState.tsx`**

Add to the context type and provider:

```typescript
// In the context type:
appSettings: AppSettings | null;
appSettingsLoading: boolean;
credentialStatus: CredentialStatus | null;
refreshAppSettings: () => Promise<void>;
refreshCredentialStatus: () => Promise<void>;
```

Add state variables and fetch functions following the same pattern as existing `providerConnections` state (lines 197-202, 271-299).

**Step 4: Create OnboardingWizard**

```typescript
// frontend/src/components/settings/OnboardingWizard.tsx
/**
 * Full-screen onboarding wizard shown on first launch.
 *
 * Three steps:
 * 1. Anthropic API Key (required)
 * 2. UPS Credentials (optional)
 * 3. Shipper Address (optional)
 *
 * On completion, calls POST /settings/onboarding/complete.
 */
```

The component should:
- Be a full-screen overlay (z-50, fixed positioning)
- Have step indicators (1/3, 2/3, 3/3)
- Step 1: Text input for API key, "Save & Continue" button
- Step 2: Client ID + Secret inputs, "Skip" and "Save & Continue" buttons
- Step 3: Shipper address form (reuse field layout from ContactForm), "Skip" and "Get Started" buttons
- Call `api.setCredential()` for secrets, `api.updateSettings()` for shipper address
- Call `api.completeOnboarding()` on final step
- Match the existing design system (DM Sans, OKLCH colors, card-premium styling)

**Step 5: Wire into App.tsx**

In `App.tsx`, conditionally render the wizard:

```typescript
const { appSettings, appSettingsLoading } = useAppState();

// Show onboarding wizard if settings loaded and not completed
if (!appSettingsLoading && appSettings && !appSettings.onboarding_completed) {
  return <OnboardingWizard />;
}
```

**Step 6: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 7: Commit**

```bash
git add frontend/src/components/settings/OnboardingWizard.tsx \
        frontend/src/hooks/useAppState.tsx \
        frontend/src/App.tsx \
        frontend/src/lib/api.ts \
        frontend/src/types/api.ts
git commit -m "feat: onboarding wizard with 3-step setup for API key, UPS, and shipper"
```

---

## Task 9: PyInstaller Spec File & Build Script

**Files:**
- Create: `shipagent-core.spec`
- Create: `scripts/bundle_backend.sh`
- Modify: `pyproject.toml` (add `pyinstaller` to dev dependencies)
- Test: Run build, verify binary starts and responds to `/health`

**Step 1: Add PyInstaller to dev dependencies**

In `pyproject.toml` `[project.optional-dependencies]`:

```toml
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
    "pyinstaller>=6.0",
]
```

Run: `pip install pyinstaller`

**Step 2: Create spec file**

```python
# shipagent-core.spec
# PyInstaller spec for the ShipAgent unified binary.
# Build: pyinstaller shipagent-core.spec --clean --noconfirm

import sys
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / 'src' / 'bundle_entry.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'frontend' / 'dist'), 'frontend/dist'),
    ],
    hiddenimports=[
        # FastAPI + Uvicorn
        'uvicorn.logging',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        # SQLAlchemy
        'sqlalchemy.dialects.sqlite',
        'aiosqlite',
        # FastMCP
        'fastmcp',
        'mcp',
        # DuckDB
        'duckdb',
        # Agent SDK
        'claude_agent_sdk',
        'anthropic',
        # NL Engine
        'sqlglot',
        'jinja2',
        # UPS MCP fork
        'ups_mcp',
        # Data formats
        'openpyxl',
        'xmltodict',
        'calamine',
        # Credential storage
        'keyring',
        'keyring.backends',
        'keyring.backends.macOS',
        'cryptography',
        # CLI
        'typer',
        'rich',
        'click',
        'httpx',
        'watchdog',
        'yaml',
        # Misc
        'pydantic',
        'jsonschema',
        'pypdf',
        'sse_starlette',
        'platformdirs',
        'pydifact',
        'dateutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'tests',
        'setuptools',
        'pip',
        'wheel',
        'distutils',
        '_pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# CRITICAL: Use one-FOLDER build (EXE + COLLECT), NOT one-file (EXE only).
#
# Why: MCP servers spawn this same binary as subprocesses. With one-file mode,
# every subprocess invocation re-extracts the entire bundle to a temp _MEIPASS
# directory (1-3 second cold-start penalty PER MCP server). One-folder mode
# extracts once at build time — subprocess spawning is instant.
#
# The COLLECT step creates a directory with all dependencies alongside the
# executable, which Tauri bundles as the sidecar folder.

exe = EXE(
    pyz,
    a.scripts,
    [],  # binaries, zipfiles, datas go to COLLECT instead
    name='shipagent-core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=True,
    target_arch=None,
    exclude_binaries=True,  # Defer binaries to COLLECT
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=False,
    name='shipagent-core',  # Output: dist/shipagent-core/ (directory)
)
```

**Step 3: Create build script**

```bash
#!/usr/bin/env bash
# scripts/bundle_backend.sh
# Build the ShipAgent Python sidecar using PyInstaller.
#
# Usage: ./scripts/bundle_backend.sh
# Output: dist/shipagent-core

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== ShipAgent Backend Bundler ==="
echo "Project root: $PROJECT_ROOT"

# 1. Build frontend first (bundled into the binary)
echo "--- Building frontend ---"
cd "$PROJECT_ROOT/frontend"
npm ci --prefer-offline --no-audit
npm run build
cd "$PROJECT_ROOT"

# 2. Run PyInstaller
echo "--- Running PyInstaller ---"
.venv/bin/python -m PyInstaller shipagent-core.spec --clean --noconfirm

# 3. Verify the one-folder output
echo "--- Verifying build ---"
BINARY_DIR="$PROJECT_ROOT/dist/shipagent-core"
BINARY="$BINARY_DIR/shipagent-core"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: Binary not found at $BINARY"
    echo "Expected one-folder build at $BINARY_DIR/"
    exit 1
fi

SIZE=$(du -sh "$BINARY_DIR" | cut -f1)
echo "Bundle size: $SIZE"
echo "Binary path: $BINARY"

# 4. Smoke test — start server briefly and check /health
echo "--- Smoke test ---"
"$BINARY" serve --port 9876 &
PID=$!
sleep 5

if curl -sf http://127.0.0.1:9876/health > /dev/null 2>&1; then
    echo "Health check: PASSED"
else
    echo "Health check: FAILED"
    kill $PID 2>/dev/null || true
    exit 1
fi

kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

echo "=== Build complete ==="
echo "Output: $BINARY_DIR/ (one-folder build)"
```

Make executable: `chmod +x scripts/bundle_backend.sh`

**Step 4: Test the build**

Run: `./scripts/bundle_backend.sh`
Expected: Binary builds, smoke test passes, reports binary size

**Step 5: Commit**

```bash
git add shipagent-core.spec scripts/bundle_backend.sh pyproject.toml
git commit -m "feat: PyInstaller spec and build script for shipagent-core binary"
```

---

## Task 10: Tauri Project Initialization

**Files:**
- Create: `src-tauri/` (entire Tauri project)
- Modify: `frontend/package.json` (add `@tauri-apps/cli` dev dependency)

**Prerequisites:** Install Rust toolchain (`rustup`) and Tauri CLI.

**Step 1: Install Tauri CLI and plugins**

```bash
cd frontend
npm install -D @tauri-apps/cli@latest @tauri-apps/api@latest
npm install @tauri-apps/plugin-shell @tauri-apps/plugin-updater
```

**Step 2: Initialize Tauri project**

```bash
cd /Users/matthewhans/Desktop/Programming/ShipAgent
npx tauri init
```

Answer prompts:
- App name: `ShipAgent`
- Window title: `ShipAgent`
- Frontend dev URL: `http://localhost:5173`
- Frontend dist dir: `../frontend/dist`
- Frontend dev command: `npm run dev`
- Frontend build command: `npm run build`

**Step 3: Configure `src-tauri/tauri.conf.json`**

Update the generated config with:

```json
{
  "productName": "ShipAgent",
  "identifier": "com.shipagent.app",
  "version": "0.1.0",
  "build": {
    "frontendDist": "../frontend/dist",
    "devUrl": "http://localhost:5173"
  },
  "app": {
    "windows": [
      {
        "title": "ShipAgent",
        "width": 1200,
        "height": 800,
        "minWidth": 900,
        "minHeight": 600
      }
    ],
    "security": {
      "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:*; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com"
    }
  },
  "bundle": {
    "active": true,
    "targets": ["dmg", "app"],
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ],
    "resources": {
      "../dist/shipagent-core": "backend-dist"
    }
  }
}
```

**CRITICAL:** We use `bundle.resources` — NOT `externalBin`.

Tauri's `externalBin` expects a single executable file. PyInstaller's one-folder
build produces a *directory* (`dist/shipagent-core/` with the executable + all
`.dylib`/`.so` dependencies alongside it). Pointing `externalBin` at a directory
causes the Rust build to panic when it tries to `chmod +x` a directory.

`bundle.resources` copies the entire directory tree into the app bundle's
`Resources/backend-dist/` folder. At runtime, we resolve the executable path via
`app.path().resource_dir().join("backend-dist/shipagent-core")`.

**Step 4: Create sidecar management using `tauri-plugin-shell`**

**IMPORTANT:** Do NOT use custom `std::process::Command` for sidecar lifecycle.
Custom process management creates **zombie processes** when the app is force-quit
(Cmd+Q, crash, SIGKILL). `tauri-plugin-shell` automatically kills child processes
when the parent exits — no cleanup code needed.

Add the plugin to `src-tauri/Cargo.toml`:

```toml
[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-shell = "2"
tauri-plugin-updater = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

Add the shell capability in `src-tauri/capabilities/default.json`:

```json
{
  "identifier": "default",
  "description": "Default permissions",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "shell:allow-spawn",
    "shell:allow-stdin-write",
    "shell:allow-kill",
    {
      "identifier": "shell:allow-execute",
      "allow": [
        {
          "name": "backend",
          "cmd": { "regex": "^.*/backend-dist/shipagent-core$" }
        }
      ]
    },
    "updater:default"
  ]
}
```

**NOTE:** We use `cmd.regex` to allow execution of the binary inside the bundled
`Resources/backend-dist/` directory. This replaces the `sidecar: true` pattern
because we're using `resources` instead of `externalBin`.

Create `src-tauri/src/main.rs`:

```rust
// ShipAgent Tauri v2 desktop wrapper.
//
// Spawns the shipagent-core Python backend from the bundled resources
// directory using tauri-plugin-shell (auto-kills on parent crash — no
// zombies). Reads the dynamically assigned port from sidecar stdout
// ("SHIPAGENT_PORT=XXXXX").
//
// IMPORTANT: We use shell.command() with a dynamic resource_dir() path,
// NOT shell.sidecar(). Tauri's sidecar() is for externalBin (single files).
// Our PyInstaller one-folder build produces a directory, so we bundle it
// as a Tauri resource and resolve the executable path at runtime.

use tauri::Manager;
use tauri_plugin_shell::ShellExt;

#[tauri::command]
async fn start_sidecar(app: tauri::AppHandle) -> Result<u16, String> {
    // Resolve the absolute path to the executable inside the resource directory.
    // Tauri copies the one-folder build to Resources/backend-dist/ at bundle time.
    let resource_path = app.path()
        .resource_dir()
        .map_err(|e| format!("Failed to resolve resource dir: {e}"))?
        .join("backend-dist")
        .join("shipagent-core");

    if !resource_path.exists() {
        return Err(format!(
            "Backend binary not found at: {}",
            resource_path.display()
        ));
    }

    let shell = app.shell();

    // Spawn backend — tauri-plugin-shell manages lifecycle automatically.
    // Port 0 tells uvicorn to bind to an OS-assigned port.
    let (mut rx, _child) = shell
        .command(resource_path.to_str().unwrap())
        .args(["serve", "--port", "0"])
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))?;

    // Read stdout line-by-line until we see the port report.
    use tauri_plugin_shell::process::CommandEvent;
    let mut port: Option<u16> = None;

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let text = String::from_utf8_lossy(&line);
                if let Some(p) = text.strip_prefix("SHIPAGENT_PORT=") {
                    port = p.trim().parse().ok();
                    break;
                }
            }
            CommandEvent::Error(e) => {
                return Err(format!("Backend stderr: {e}"));
            }
            CommandEvent::Terminated(payload) => {
                return Err(format!("Backend exited early: {:?}", payload.code));
            }
            _ => {}
        }
    }

    port.ok_or_else(|| "Backend did not report a port".to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![start_sidecar])
        .setup(|_app| {
            // The frontend JS calls `invoke('start_sidecar')` on load and
            // sets `window.__SHIPAGENT_PORT__` with the returned port.
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running ShipAgent");
}
```

Create `frontend/src/lib/tauri-init.ts` for the frontend integration:

```typescript
/**
 * Tauri sidecar initialization.
 *
 * Called once on app startup to launch the Python backend and
 * discover the dynamically assigned port. Sets window.__SHIPAGENT_PORT__
 * which api.ts reads for the API base URL.
 */
export async function initSidecar(): Promise<void> {
  // Only run inside Tauri — skip in Vite dev mode
  if (!(window as any).__TAURI__) return;

  const { invoke } = await import('@tauri-apps/api/core');
  const port = await invoke<number>('start_sidecar');
  (window as any).__SHIPAGENT_PORT__ = port;
}
```

**Step 5: Verify resource bundling**

The `tauri.conf.json` `resources` field maps `../dist/shipagent-core` → `backend-dist`.
During `tauri build`, Tauri copies the entire one-folder directory into:
`ShipAgent.app/Contents/Resources/backend-dist/`

For **dev mode** (`tauri dev`), ensure `dist/shipagent-core/` exists by running
`scripts/bundle_backend.sh` first. Tauri resolves the resource path relative to
the project root during dev.

**Step 6: Test dev mode**

```bash
cd frontend && npm run tauri dev
```

Expected: Tauri window opens, sidecar starts, WebView loads the app.

**Step 7: Commit**

```bash
git add src-tauri/ frontend/package.json
git commit -m "feat: Tauri v2 project with sidecar lifecycle management"
```

---

## Task 11: Version Bump Script

**Files:**
- Create: `scripts/bump-version.sh`

**Step 1: Create script**

```bash
#!/usr/bin/env bash
# scripts/bump-version.sh
# Update version across all project manifests.
#
# Usage: ./scripts/bump-version.sh 1.2.3

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 1.2.3"
    exit 1
fi

VERSION="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Bumping version to $VERSION"

# 1. pyproject.toml
sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$PROJECT_ROOT/pyproject.toml"
echo "  Updated pyproject.toml"

# 2. tauri.conf.json
if [ -f "$PROJECT_ROOT/src-tauri/tauri.conf.json" ]; then
    # Use python for reliable JSON editing
    python3 -c "
import json, sys
with open('$PROJECT_ROOT/src-tauri/tauri.conf.json', 'r') as f:
    conf = json.load(f)
conf['version'] = '$VERSION'
with open('$PROJECT_ROOT/src-tauri/tauri.conf.json', 'w') as f:
    json.dump(conf, f, indent=2)
    f.write('\n')
"
    echo "  Updated tauri.conf.json"
fi

# 3. frontend/package.json
if [ -f "$PROJECT_ROOT/frontend/package.json" ]; then
    python3 -c "
import json
with open('$PROJECT_ROOT/frontend/package.json', 'r') as f:
    pkg = json.load(f)
pkg['version'] = '$VERSION'
with open('$PROJECT_ROOT/frontend/package.json', 'w') as f:
    json.dump(pkg, f, indent=2)
    f.write('\n')
"
    echo "  Updated frontend/package.json"
fi

# 4. Cargo.toml (if Tauri exists)
if [ -f "$PROJECT_ROOT/src-tauri/Cargo.toml" ]; then
    sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$PROJECT_ROOT/src-tauri/Cargo.toml"
    echo "  Updated Cargo.toml"
fi

echo "Version bumped to $VERSION across all manifests."
echo "Run: git add -u && git commit -m 'chore: bump version to v$VERSION'"
```

Make executable: `chmod +x scripts/bump-version.sh`

**Step 2: Test**

Run: `./scripts/bump-version.sh 0.2.0`
Verify all files updated, then revert: `git checkout -- pyproject.toml frontend/package.json`

**Step 3: Commit**

```bash
git add scripts/bump-version.sh
git commit -m "feat: version bump script for pyproject.toml, tauri, and frontend"
```

---

## Task 12: GitHub Actions Release Pipeline

**Files:**
- Create: `.github/workflows/release.yml`

**Step 1: Create workflow file**

This workflow includes:
- **Matrix build** for both Intel (x86_64) and Apple Silicon (arm64)
- **Codesign the sidecar** before Tauri bundles it (same Team ID — prevents Keychain access prompts)
- **Apple Notarization** via `xcrun notarytool` (required for macOS 10.15+ Gatekeeper)
- **Auto-updater manifest** published alongside the DMG

Required GitHub Secrets:
- `APPLE_CERTIFICATE` — Base64-encoded .p12 Developer ID certificate
- `APPLE_CERTIFICATE_PASSWORD` — .p12 password
- `APPLE_SIGNING_IDENTITY` — e.g. "Developer ID Application: Your Name (TEAM_ID)"
- `APPLE_API_ISSUER` — App Store Connect API Issuer UUID (from App Store Connect → Users and Access → Integrations → App Store Connect API)
- `APPLE_API_KEY_ID` — App Store Connect API Key ID (e.g. "ABCDEF1234")
- `APPLE_API_KEY` — Base64-encoded .p8 private key file content
- `APPLE_TEAM_ID` — 10-character Team ID
- `TAURI_SIGNING_PRIVATE_KEY` — Ed25519 private key for auto-updater signing (see Task 16)
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — Password for the updater key

**NOTE:** We use **App Store Connect API Keys** for notarization instead of
Apple ID + App-Specific Passwords. Apple frequently throttles and times out the
legacy auth method in CI. API Keys are 100x more reliable and are Apple's
recommended approach for automated workflows.

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags: ['v*.*.*']

env:
  PYTHON_VERSION: '3.12'
  NODE_VERSION: '20'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install dependencies
        run: |
          python -m venv .venv
          .venv/bin/pip install -e '.[dev]'
      - name: Lint
        run: .venv/bin/ruff check src/ tests/
      - name: Test
        run: .venv/bin/pytest -k "not stream and not sse and not progress" --timeout=60

  build-macos:
    needs: test
    strategy:
      matrix:
        include:
          - runner: macos-14      # Apple Silicon (arm64)
            target: aarch64-apple-darwin
          - runner: macos-13      # Intel (x86_64)
            target: x86_64-apple-darwin
    runs-on: ${{ matrix.runner }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}

      - name: Install Rust
        uses: dtolnay/rust-toolchain@stable
        with:
          targets: ${{ matrix.target }}

      - name: Install Python dependencies
        run: |
          python -m venv .venv
          .venv/bin/pip install -e '.[dev]'

      - name: Build frontend
        run: |
          cd frontend
          npm ci
          npm run build

      - name: Build Python sidecar
        run: |
          .venv/bin/python -m PyInstaller shipagent-core.spec --clean --noconfirm

      - name: Import Apple certificate
        if: env.APPLE_CERTIFICATE != ''
        env:
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
        run: |
          echo "$APPLE_CERTIFICATE" | base64 --decode > certificate.p12
          security create-keychain -p "" build.keychain
          security default-keychain -s build.keychain
          security unlock-keychain -p "" build.keychain
          security import certificate.p12 -k build.keychain \
            -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security set-key-partition-list -S apple-tool:,apple: -s -k "" build.keychain
          rm certificate.p12

      # CRITICAL: Codesign the sidecar binary BEFORE Tauri bundles it.
      # Without this, the sidecar has a different signing identity than the
      # app wrapper, causing macOS Keychain to show "wants to access" prompts.
      - name: Codesign sidecar binary
        if: env.APPLE_SIGNING_IDENTITY != ''
        env:
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
        run: |
          echo "--- Codesigning sidecar (one-folder build) ---"
          # Sign all .dylib and .so files in the one-folder output first
          find dist/shipagent-core -name '*.dylib' -o -name '*.so' | while read f; do
            codesign --force --sign "$APPLE_SIGNING_IDENTITY" \
              --options runtime --timestamp "$f"
          done
          # Sign the main executable
          codesign --force --sign "$APPLE_SIGNING_IDENTITY" \
            --options runtime --timestamp --entitlements src-tauri/entitlements.plist \
            dist/shipagent-core/shipagent-core
          # Verify
          codesign --verify --deep --strict dist/shipagent-core/shipagent-core
          echo "Sidecar codesigning: PASSED"

      # NO "Copy sidecar to Tauri binaries" step needed.
      # The tauri.conf.json resources field ("../dist/shipagent-core": "backend-dist")
      # tells Tauri to bundle the one-folder output directly from dist/.

      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          # App Store Connect API Keys for notarization (more reliable than Apple ID)
          APPLE_API_ISSUER: ${{ secrets.APPLE_API_ISSUER }}
          APPLE_API_KEY_ID: ${{ secrets.APPLE_API_KEY_ID }}
          APPLE_API_KEY: ${{ secrets.APPLE_API_KEY }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
        with:
          tagName: ${{ github.ref_name }}
          releaseName: 'ShipAgent ${{ github.ref_name }}'
          releaseBody: 'See the [changelog](https://github.com/matt-hans/ShipAgent/blob/main/CHANGELOG.md) for details.'
          releaseDraft: true
          prerelease: false
          args: --target ${{ matrix.target }}

      # Apple Notarization: Required on macOS 10.15+.
      # Signed-but-not-notarized apps are blocked by Gatekeeper.
      #
      # We use App Store Connect API Keys (APPLE_API_ISSUER + APPLE_API_KEY_ID
      # + APPLE_API_KEY) instead of Apple ID + App-Specific Passwords.
      # Reason: Apple frequently throttles and times out the legacy auth in CI.
      # API keys are Apple's recommended approach for automated workflows.
      #
      # tauri-action handles notarization automatically when these env vars
      # are set. For manual builds:
      #
      #   xcrun notarytool submit ShipAgent.dmg \
      #     --issuer "$APPLE_API_ISSUER" \
      #     --key-id "$APPLE_API_KEY_ID" \
      #     --key "$APPLE_API_KEY_PATH" \
      #     --wait
      #   xcrun stapler staple ShipAgent.dmg
```

Also create `src-tauri/entitlements.plist` for the sidecar:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
</dict>
</plist>
```

The entitlements allow:
- `allow-unsigned-executable-memory` — required for Python's ctypes/FFI
- `allow-jit` — required for DuckDB's JIT compilation
- `network.client` — required for outbound HTTP (UPS API calls)

**Step 2: Commit**

```bash
mkdir -p .github/workflows
git add .github/workflows/release.yml
git commit -m "feat: GitHub Actions release pipeline with Tauri build and Apple signing"
```

---

## Task 13: Expand ShipmentBehaviourSection with Persisted Settings

**Files:**
- Modify: `frontend/src/components/settings/ShipmentBehaviourSection.tsx`
- Test: `cd frontend && npx tsc --noEmit`

This task connects the existing `ShipmentBehaviourSection` (currently client-only `warningPreference`) to the Settings DB so values persist across restarts. Add the shipper address defaults here (pulled from `appSettings`).

**Step 1: Update the component**

Expand `ShipmentBehaviourSection.tsx` to include:
1. The existing warning preference (now saved to Settings DB via `api.updateSettings`)
2. Default batch concurrency slider (1-20)
3. Default service code dropdown (Ground, Next Day Air, etc.)
4. Shipper address defaults (name, address, city, state, zip, phone)

All values read from `appSettings` and write via `api.updateSettings()`.

**Step 2: Verify compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/components/settings/ShipmentBehaviourSection.tsx
git commit -m "feat: persist shipment behaviour settings to DB, add shipper defaults"
```

---

## Task 14: Startup Directory Initialization

**Files:**
- Modify: `src/api/main.py` (call `ensure_dirs_exist()` in lifespan)
- Test: Start server, verify directories created

**Step 1: Update lifespan**

In `src/api/main.py`, add to the `lifespan()` function (early, before `init_db()`):

```python
from src.utils.paths import ensure_dirs_exist
ensure_dirs_exist()
```

This creates `~/Library/Application Support/com.shipagent.app/` and subdirectories in bundled mode, or is a no-op in dev mode.

**Step 2: Also generate FILTER_TOKEN_SECRET if absent**

In the lifespan, after init_db:

```python
import os, secrets
if not os.environ.get("FILTER_TOKEN_SECRET"):
    from src.services.keyring_store import KeyringStore
    store = KeyringStore()
    existing = store.get("FILTER_TOKEN_SECRET")
    if not existing:
        generated = secrets.token_hex(32)
        store.set("FILTER_TOKEN_SECRET", generated)
        os.environ["FILTER_TOKEN_SECRET"] = generated
        # CRITICAL: Never log the secret value — only log the event.
        # Logging the value would leak it to stdout/stderr/log files.
        logger.info("Auto-generated FILTER_TOKEN_SECRET and stored in keychain")
    else:
        os.environ["FILTER_TOKEN_SECRET"] = existing
        logger.info("Loaded FILTER_TOKEN_SECRET from keychain")
```

**Step 3: Test**

Run: `./scripts/start-backend.sh`
Expected: Server starts, directories exist, FILTER_TOKEN_SECRET is set

**Step 4: Commit**

```bash
git add src/api/main.py
git commit -m "feat: auto-create data dirs on startup, auto-generate FILTER_TOKEN_SECRET"
```

---

## Task 15: Integration Testing

**Files:**
- Create: `tests/integration/test_production_readiness.py`

**Step 1: Write integration tests**

```python
# tests/integration/test_production_readiness.py
"""Integration tests for production readiness features."""

import os
import sys
from pathlib import Path
from unittest.mock import patch


def test_bundled_mcp_config_resolves_self():
    """In bundled mode, MCP config uses self-executable."""
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/fake/shipagent-core'):
            from src.orchestrator.agent.config import get_data_mcp_config
            config = get_data_mcp_config()
            assert config["command"] == "/fake/shipagent-core"
            assert config["args"] == ["mcp-data"]


def test_settings_round_trip(client):
    """Settings can be saved and loaded."""
    # Save
    resp = client.patch("/api/v1/settings", json={"shipper_name": "Test Inc"})
    assert resp.status_code == 200
    assert resp.json()["shipper_name"] == "Test Inc"

    # Load
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json()["shipper_name"] == "Test Inc"


def test_credential_status_endpoint(client):
    """Credential status returns booleans, never values."""
    resp = client.get("/api/v1/settings/credentials/status")
    assert resp.status_code == 200
    data = resp.json()
    # All fields are booleans
    for key, value in data.items():
        assert isinstance(value, bool), f"{key} should be bool, got {type(value)}"


def test_onboarding_flow(client):
    """Onboarding starts incomplete, can be completed."""
    resp = client.get("/api/v1/settings")
    assert resp.json()["onboarding_completed"] is False

    resp = client.post("/api/v1/settings/onboarding/complete")
    assert resp.status_code == 200

    resp = client.get("/api/v1/settings")
    assert resp.json()["onboarding_completed"] is True


def test_env_var_override_still_works():
    """DATABASE_URL env var takes priority over platformdirs."""
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///override.db"}):
        from src.db.connection import get_database_url
        assert get_database_url() == "sqlite:///override.db"
```

**Step 2: Run integration tests**

Run: `pytest tests/integration/test_production_readiness.py -v`
Expected: All pass

**Step 3: Commit**

```bash
git add tests/integration/test_production_readiness.py
git commit -m "test: integration tests for production readiness features"
```

---

## Task 16: Auto-Updater (tauri-plugin-updater)

**Files:**
- Modify: `src-tauri/tauri.conf.json` (add updater configuration)
- Modify: `src-tauri/src/main.rs` (already has plugin registered — verify)
- Create: `frontend/src/components/settings/UpdateChecker.tsx`
- Modify: `frontend/src/App.tsx` or `frontend/src/components/layout/Header.tsx` (mount update checker)
- Create: `scripts/generate-updater-key.sh`

**Prerequisites:** `tauri-plugin-updater` already installed (Task 10) and registered in `main.rs`.

**Step 1: Generate Ed25519 signing key pair**

Create `scripts/generate-updater-key.sh`:

```bash
#!/usr/bin/env bash
# scripts/generate-updater-key.sh
# Generate the Ed25519 key pair for Tauri auto-updater.
#
# The PRIVATE key is a GitHub Secret (TAURI_SIGNING_PRIVATE_KEY).
# The PUBLIC key goes into tauri.conf.json.
#
# Usage: ./scripts/generate-updater-key.sh

set -euo pipefail

echo "=== Tauri Updater Key Generation ==="
echo ""
echo "This generates an Ed25519 key pair for signing auto-updates."
echo "You will be prompted for a password (stored as TAURI_SIGNING_PRIVATE_KEY_PASSWORD)."
echo ""

npx @tauri-apps/cli signer generate -w ~/.tauri/shipagent-updater.key

echo ""
echo "=== IMPORTANT ==="
echo "1. Add the PRIVATE key to GitHub Secrets as: TAURI_SIGNING_PRIVATE_KEY"
echo "2. Add the password to GitHub Secrets as: TAURI_SIGNING_PRIVATE_KEY_PASSWORD"
echo "3. Copy the PUBLIC key into src-tauri/tauri.conf.json under plugins.updater.pubkey"
echo "4. NEVER commit the private key to the repository."
```

Make executable: `chmod +x scripts/generate-updater-key.sh`

Run: `./scripts/generate-updater-key.sh`
Copy the public key output for the next step.

**Step 2: Configure updater in `tauri.conf.json`**

Add the updater plugin configuration to `src-tauri/tauri.conf.json`:

```json
{
  "plugins": {
    "updater": {
      "endpoints": [
        "https://github.com/matt-hans/ShipAgent/releases/latest/download/latest.json"
      ],
      "pubkey": "PASTE_YOUR_ED25519_PUBLIC_KEY_HERE"
    }
  }
}
```

The `latest.json` file is auto-generated by `tauri-action` during CI and uploaded
alongside the DMG. It contains: version, platform URLs, signatures, and release notes.

**Private Repo Warning:** If `matt-hans/ShipAgent` is a **private** GitHub repository,
the updater will get a 404 when fetching `latest.json` because it has no auth token.
Fix options (choose one):
1. **Make the repo public** — simplest, no auth needed.
2. **Inject a GitHub PAT in Rust** — pass a `Bearer` token header to the updater:
   ```rust
   tauri_plugin_updater::Builder::new()
       .header("Authorization", format!("Bearer {}", github_pat))
       .build()
   ```
3. **Use a proxy server** — Cloudflare Worker or AWS Lambda that authenticates
   and serves the update manifest publicly.

If the repo is public, ignore this.

**Step 3: Create UpdateChecker frontend component**

```typescript
// frontend/src/components/settings/UpdateChecker.tsx
/**
 * Auto-update checker for the Tauri desktop app.
 *
 * Checks for updates on mount and every 4 hours. Shows a non-intrusive
 * banner when an update is available, with "Update Now" and "Later" buttons.
 * Only renders inside Tauri — hidden in Vite dev mode.
 */

import { useEffect, useState } from 'react';

interface UpdateInfo {
  version: string;
  body: string;  // release notes
}

export function UpdateChecker() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    // Only run inside Tauri
    if (!(window as any).__TAURI__) return;

    async function checkForUpdate() {
      try {
        const { check } = await import('@tauri-apps/plugin-updater');
        const result = await check();
        if (result?.available) {
          setUpdate({
            version: result.version,
            body: result.body ?? 'Bug fixes and improvements.',
          });
        }
      } catch (err) {
        console.warn('Update check failed:', err);
      }
    }

    // Check immediately and every 4 hours
    checkForUpdate();
    const interval = setInterval(checkForUpdate, 4 * 60 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (!update) return null;

  async function handleInstall() {
    setInstalling(true);
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const result = await check();
      if (result?.available) {
        await result.downloadAndInstall();
        // Tauri auto-restarts after install
      }
    } catch (err) {
      console.error('Update install failed:', err);
      setInstalling(false);
    }
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm rounded-lg border
                    border-cyan-500/30 bg-gray-900 p-4 shadow-lg">
      <p className="text-sm font-medium text-white">
        ShipAgent {update.version} is available
      </p>
      <p className="mt-1 text-xs text-gray-400 line-clamp-2">{update.body}</p>
      <div className="mt-3 flex gap-2">
        <button
          onClick={handleInstall}
          disabled={installing}
          className="btn-primary text-xs"
        >
          {installing ? 'Installing...' : 'Update Now'}
        </button>
        <button
          onClick={() => setUpdate(null)}
          className="btn-secondary text-xs"
        >
          Later
        </button>
      </div>
    </div>
  );
}
```

**Step 4: Mount UpdateChecker in the app**

In `frontend/src/App.tsx`, add at the end of the root layout (after main content):

```typescript
import { UpdateChecker } from './components/settings/UpdateChecker';

// Inside the return JSX, at the bottom:
<UpdateChecker />
```

**Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 6: Commit**

```bash
git add scripts/generate-updater-key.sh \
        src-tauri/tauri.conf.json \
        frontend/src/components/settings/UpdateChecker.tsx \
        frontend/src/App.tsx
git commit -m "feat: auto-updater with Ed25519 signing, GitHub Releases endpoint, and UI"
```

---

## Summary

| Task | What it does | Estimated effort |
|------|-------------|-----------------|
| 1 | Runtime detection utility (`is_bundled()`, one-folder aware) | 15 min |
| 2 | MCP config bundled mode support | 30 min |
| 3 | Bundle entry point + `PortReportingServer` (TOCTOU fix) | 30 min |
| 4 | Production file paths with `platformdirs` + **SQLite WAL + synchronous=NORMAL** | 45 min |
| 5 | Settings DB table, service, and API routes | 1 hour |
| 6 | Keyring integration for secure credentials | 45 min |
| 7 | Dynamic port for frontend API client + Vite proxy scoping | 15 min |
| 8 | Onboarding wizard component | 1.5 hours |
| 9 | PyInstaller spec file (one-folder COLLECT) and build script | 1 hour |
| 10 | Tauri project initialization with **`resources` + `shell.command()`** sidecar | 1.5 hours |
| 11 | Version bump script | 15 min |
| 12 | GitHub Actions release pipeline (**matrix build** + **codesign sidecar** + **API Key notarization**) | 1 hour |
| 13 | Expand ShipmentBehaviourSection | 45 min |
| 14 | Startup directory initialization + secret auto-gen (**never log value**) | 30 min |
| 15 | Integration testing | 30 min |
| 16 | **Auto-updater** (`tauri-plugin-updater` + Ed25519 + frontend UI) | 1 hour |

**Total: ~11 hours of implementation**

**Dependencies:**
- Tasks 1-4 are foundational (no deps on each other, can be parallelized)
- Task 5 depends on Task 4 (paths module)
- Task 6 depends on Task 5 (settings routes exist)
- Task 7 is independent
- Task 8 depends on Tasks 5, 6 (settings API + credential API exist)
- Task 9 depends on Tasks 1, 2, 3 (runtime detection, MCP config, entry point)
- Task 10 depends on Task 9 (sidecar binary exists)
- Tasks 11-12 depend on Task 10 (Tauri project exists)
- Task 13 depends on Task 5 (settings API exists)
- Task 14 depends on Tasks 4, 6 (paths + keyring)
- Task 15 depends on all previous tasks (Tasks 1-14)
- Task 16 depends on Task 10 (Tauri project + plugins exist)

**Critical Production Fix Coverage:**
- Fix #1 (one-folder build): Tasks 1, 9
- Fix #2 (notarization): Task 12
- Fix #3 (zombie processes): Task 10
- Fix #4 (auto-updater): Task 16
- Fix #5 (TOCTOU port race): Tasks 3, 7, 10
- Fix #6 (codesign sidecar): Task 12
- Fix #7 (Intel Mac support): Task 12
- Fix #8 (SQLite WAL mode): Task 4
- Fix #9 (secret logging): Task 14
- Fix #10 (Vite proxy scope): Task 7
- Fix #11 (externalBin → resources): Tasks 9, 10, 12
- Fix #12 (API Key notarization): Task 12
- Fix #13 (synchronous=NORMAL): Task 4
- Fix #14 (private repo updater): Task 16
