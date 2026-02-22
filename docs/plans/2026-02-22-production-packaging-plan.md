# Production Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package ShipAgent as a signed, auto-updating macOS desktop app using Tauri + PyInstaller, with secure credential management and professional onboarding.

**Architecture:** Tauri v2 wraps the React frontend in a native WebView and manages a PyInstaller-bundled Python sidecar (`shipagent-core`) that runs the FastAPI server, all 3 MCP servers (via subcommands), and the CLI. Credentials use macOS Keychain (via `keyring`), non-sensitive config uses a `settings` table in SQLite, and env vars remain as dev overrides.

**Tech Stack:** Tauri v2 (Rust), PyInstaller, `keyring`, `platformdirs`, GitHub Actions, Apple Developer ID signing.

**Design Doc:** `docs/plans/2026-02-22-production-packaging-design.md`

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
    """In bundled mode, returns sys._MEIPASS."""
    fake_meipass = "/tmp/test_meipass"
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, '_MEIPASS', fake_meipass, create=True):
            result = get_resource_dir()
            from pathlib import Path
            assert result == Path(fake_meipass)
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
    In PyInstaller mode, returns sys._MEIPASS (temporary extraction dir).
    """
    if is_bundled():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
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


def test_serve_command_starts_uvicorn():
    """'serve' command should launch uvicorn with the FastAPI app."""
    with patch.dict(sys.modules, {}):
        with patch('sys.argv', ['shipagent-core', 'serve', '--port', '9000']):
            # We can't actually start uvicorn, so test the arg parsing
            from src.bundle_entry import parse_serve_args
            args = parse_serve_args(['--port', '9000'])
            assert args.port == 9000
            assert args.host == '127.0.0.1'


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
    parser.add_argument('--port', type=int, default=8000, help='Listen port')
    return parser.parse_args(args)


def main() -> None:
    """Dispatch to the correct subsystem based on the subcommand."""
    command = get_command()

    if command == 'serve':
        serve_args = parse_serve_args(sys.argv[2:])
        import uvicorn
        from src.api.main import app
        uvicorn.run(
            app,
            host=serve_args.host,
            port=serve_args.port,
            workers=1,
            log_level='info',
        )

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

**Step 4: Update `src/db/connection.py` — add platformdirs fallback**

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

**Step 5: Run tests**

Run: `pytest tests/utils/test_paths.py -v`
Expected: 7 passed

Run: `pytest tests/db/ -v -k "not stream"`
Expected: Existing DB tests still pass

**Step 6: Commit**

```bash
git add src/utils/paths.py tests/utils/test_paths.py src/db/connection.py
git commit -m "feat: platformdirs-based file paths for production, dev uses project root"
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
 * In Tauri mode: window.__SHIPAGENT_PORT__ is injected by the Rust shell
 * with the dynamically assigned sidecar port.
 *
 * In dev mode (Vite): relative URL is proxied to localhost:8000 by vite.config.ts.
 */
const TAURI_PORT = (window as any).__SHIPAGENT_PORT__;
const API_BASE = TAURI_PORT
  ? `http://127.0.0.1:${TAURI_PORT}/api/v1`
  : '/api/v1';
```

**Step 2: Verify dev mode still works**

Run: `cd frontend && npm run dev`
Navigate to `http://localhost:5173` — API calls should still proxy through Vite.

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='shipagent-core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,  # UPX disabled by default; enable with --upx-dir
    console=True,
    target_arch=None,
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

# 3. Verify the binary
echo "--- Verifying binary ---"
BINARY="$PROJECT_ROOT/dist/shipagent-core"
if [ ! -f "$BINARY" ]; then
    echo "ERROR: Binary not found at $BINARY"
    exit 1
fi

SIZE=$(du -sh "$BINARY" | cut -f1)
echo "Binary size: $SIZE"
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
echo "Output: $BINARY"
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

**Step 1: Install Tauri CLI**

```bash
cd frontend
npm install -D @tauri-apps/cli@latest @tauri-apps/api@latest
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
    "externalBin": ["shipagent-core"]
  }
}
```

**Step 4: Create sidecar management in Rust**

Create `src-tauri/src/sidecar.rs`:

```rust
// Sidecar lifecycle management for the Python backend.
// Starts shipagent-core, health-checks, restarts on failure.

use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::thread;
use std::net::TcpListener;

/// Find a free port by binding to port 0.
pub fn find_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("Failed to bind to a free port")
        .local_addr()
        .expect("Failed to get local address")
        .port()
}

/// Start the sidecar process and return the child handle.
pub fn start_sidecar(binary_path: &str, port: u16) -> std::io::Result<Child> {
    Command::new(binary_path)
        .args(["serve", "--port", &port.to_string()])
        .spawn()
}

/// Wait for the sidecar to respond to /health.
pub fn wait_for_health(port: u16, timeout: Duration) -> bool {
    let start = std::time::Instant::now();
    let url = format!("http://127.0.0.1:{}/health", port);

    while start.elapsed() < timeout {
        if let Ok(resp) = ureq::get(&url).call() {
            if resp.status() == 200 {
                return true;
            }
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}
```

Update `src-tauri/src/main.rs` to use the sidecar module, inject the port into the WebView, and handle shutdown.

**Step 5: Add sidecar binary to Tauri bundle**

Place the `shipagent-core` binary at `src-tauri/binaries/shipagent-core-{target_triple}` (Tauri convention for external binaries).

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
    runs-on: macos-14  # Apple Silicon
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

      - name: Copy sidecar to Tauri binaries
        run: |
          mkdir -p src-tauri/binaries
          cp dist/shipagent-core "src-tauri/binaries/shipagent-core-aarch64-apple-darwin"

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
          security import certificate.p12 -k build.keychain -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
          security set-key-partition-list -S apple-tool:,apple: -s -k "" build.keychain
          rm certificate.p12

      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APPLE_PASSWORD: ${{ secrets.APPLE_PASSWORD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        with:
          tagName: ${{ github.ref_name }}
          releaseName: 'ShipAgent ${{ github.ref_name }}'
          releaseBody: 'See the [changelog](https://github.com/matt-hans/ShipAgent/blob/main/CHANGELOG.md) for details.'
          releaseDraft: true
          prerelease: false
```

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
        logger.info("Auto-generated FILTER_TOKEN_SECRET and stored in keychain")
    else:
        os.environ["FILTER_TOKEN_SECRET"] = existing
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

## Summary

| Task | What it does | Estimated effort |
|------|-------------|-----------------|
| 1 | Runtime detection utility (`is_bundled()`) | 15 min |
| 2 | MCP config bundled mode support | 30 min |
| 3 | Bundle entry point (`bundle_entry.py`) | 30 min |
| 4 | Production file paths with `platformdirs` | 30 min |
| 5 | Settings DB table, service, and API routes | 1 hour |
| 6 | Keyring integration for secure credentials | 45 min |
| 7 | Dynamic port for frontend API client | 15 min |
| 8 | Onboarding wizard component | 1.5 hours |
| 9 | PyInstaller spec file and build script | 1 hour |
| 10 | Tauri project initialization | 1.5 hours |
| 11 | Version bump script | 15 min |
| 12 | GitHub Actions release pipeline | 45 min |
| 13 | Expand ShipmentBehaviourSection | 45 min |
| 14 | Startup directory initialization | 30 min |
| 15 | Integration testing | 30 min |

**Total: ~10 hours of implementation**

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
- Task 15 depends on all previous tasks
