# ShipAgent Headless Automation Suite — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a unified `shipagent` CLI tool with daemon management, conversational REPL, hot-folder watchdog, and auto-confirm engine — enabling fully headless, scriptable shipping automation.

**Architecture:** Layered CLI with a `ShipAgentClient` protocol satisfied by two implementations: `HttpClient` (talks to the daemon over HTTP) and `InProcessRunner` (runs the full agent stack in-process). A factory selects the implementation based on the `--standalone` flag. The watchdog runs inside the daemon's FastAPI lifespan.

**Tech Stack:** Python 3.12+, Typer (CLI), httpx (HTTP client), Rich (terminal UI), watchdog (filesystem), PyYAML (config), Pydantic (config models)

**Design Doc:** `docs/plans/2026-02-16-headless-automation-design.md`

---

## Task 1: Install Dependencies & Register Entry Point

**Files:**
- Modify: `pyproject.toml:11-36`

**Step 1: Add CLI dependencies to pyproject.toml**

Add to the `dependencies` list in `pyproject.toml`:

```python
    # CLI dependencies
    "typer[all]>=0.9.0",
    "httpx>=0.27.0",
    "rich>=13.0.0",
    "watchdog>=4.0.0",
    "pyyaml>=6.0",
```

Add the entry point after `[project.optional-dependencies]`:

```toml
[project.scripts]
shipagent = "src.cli.main:app"
```

**Step 2: Install dependencies**

Run: `pip install -e '.[dev]'`
Expected: All dependencies install successfully, `shipagent` command becomes available.

**Step 3: Verify entry point**

Run: `shipagent --help`
Expected: Will fail with `ModuleNotFoundError` (module doesn't exist yet). That's expected — confirms the entry point is registered.

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(cli): add CLI dependencies and entry point registration"
```

---

## Task 2: Config Models & YAML Loader

**Files:**
- Create: `src/cli/__init__.py`
- Create: `src/cli/config.py`
- Create: `tests/cli/__init__.py`
- Create: `tests/cli/test_config.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_config.py
"""Tests for CLI configuration loading and validation."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from src.cli.config import (
    AutoConfirmRules,
    DaemonConfig,
    ShipAgentConfig,
    ShipperConfig,
    UPSConfig,
    WatchFolderConfig,
    load_config,
    resolve_env_vars,
)


class TestDaemonConfig:
    """Tests for DaemonConfig defaults and validation."""

    def test_defaults(self):
        """All defaults are sensible for single-worker SQLite."""
        cfg = DaemonConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.workers == 1
        assert cfg.log_level == "info"
        assert cfg.log_format == "text"
        assert cfg.log_file is None

    def test_custom_values(self):
        """Custom values override defaults."""
        cfg = DaemonConfig(host="0.0.0.0", port=9000, log_level="debug")
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000
        assert cfg.log_level == "debug"


class TestAutoConfirmRules:
    """Tests for auto-confirm rule defaults and validation."""

    def test_defaults_are_conservative(self):
        """Default auto-confirm is disabled with safe thresholds."""
        rules = AutoConfirmRules()
        assert rules.enabled is False
        assert rules.max_cost_cents == 50000
        assert rules.max_rows == 500
        assert rules.max_cost_per_row_cents == 5000
        assert rules.allowed_services == []
        assert rules.require_valid_addresses is True
        assert rules.allow_warnings is False

    def test_custom_rules(self):
        """Custom rules override defaults."""
        rules = AutoConfirmRules(
            enabled=True,
            max_cost_cents=100000,
            allowed_services=["03", "02"],
        )
        assert rules.enabled is True
        assert rules.max_cost_cents == 100000
        assert rules.allowed_services == ["03", "02"]


class TestWatchFolderConfig:
    """Tests for watch folder configuration."""

    def test_required_fields(self):
        """Path and command are required."""
        cfg = WatchFolderConfig(path="./inbox", command="Ship all orders")
        assert cfg.path == "./inbox"
        assert cfg.command == "Ship all orders"
        assert cfg.auto_confirm is False
        assert cfg.file_types == [".csv", ".xlsx"]

    def test_per_folder_overrides(self):
        """Per-folder overrides inherit None for global fallback."""
        cfg = WatchFolderConfig(
            path="./inbox/priority",
            command="Ship via Next Day Air",
            auto_confirm=True,
            max_cost_cents=100000,
        )
        assert cfg.auto_confirm is True
        assert cfg.max_cost_cents == 100000
        assert cfg.max_rows is None  # inherits global


class TestResolveEnvVars:
    """Tests for ${VAR} resolution in config values."""

    def test_resolves_env_var(self, monkeypatch):
        """${VAR} syntax resolves from environment."""
        monkeypatch.setenv("TEST_SECRET", "my-secret-key")
        assert resolve_env_vars("${TEST_SECRET}") == "my-secret-key"

    def test_passthrough_no_vars(self):
        """Strings without ${} pass through unchanged."""
        assert resolve_env_vars("plain-value") == "plain-value"

    def test_missing_env_var_returns_empty(self):
        """Missing env vars resolve to empty string."""
        result = resolve_env_vars("${DEFINITELY_NOT_SET_XYZ}")
        assert result == ""

    def test_mixed_content(self, monkeypatch):
        """${VAR} embedded in other text resolves correctly."""
        monkeypatch.setenv("MY_HOST", "localhost")
        assert resolve_env_vars("http://${MY_HOST}:8000") == "http://localhost:8000"


class TestLoadConfig:
    """Tests for YAML config file loading."""

    def test_load_from_explicit_path(self, tmp_path):
        """Load config from explicit --config path."""
        config_data = {
            "daemon": {"port": 9000},
            "auto_confirm": {"enabled": True, "max_rows": 100},
        }
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.daemon.port == 9000
        assert cfg.auto_confirm.enabled is True
        assert cfg.auto_confirm.max_rows == 100

    def test_returns_none_when_no_config(self, tmp_path, monkeypatch):
        """Returns None when no config file is found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = load_config()
        assert cfg is None

    def test_env_var_override(self, tmp_path, monkeypatch):
        """SHIPAGENT_ env vars override YAML values."""
        config_data = {"daemon": {"port": 8000}}
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))
        monkeypatch.setenv("SHIPAGENT_DAEMON_PORT", "9999")

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.daemon.port == 9999

    def test_dollar_var_resolution(self, tmp_path, monkeypatch):
        """${VAR} in YAML values resolve from environment."""
        monkeypatch.setenv("MY_UPS_KEY", "secret-123")
        config_data = {"ups": {"client_id": "${MY_UPS_KEY}"}}
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.ups is not None
        assert cfg.ups.client_id == "secret-123"

    def test_watch_folders(self, tmp_path):
        """Watch folders parse correctly from YAML."""
        config_data = {
            "watch_folders": [
                {
                    "path": "./inbox/priority",
                    "command": "Ship via Next Day Air",
                    "auto_confirm": True,
                    "file_types": [".csv"],
                }
            ]
        }
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert len(cfg.watch_folders) == 1
        assert cfg.watch_folders[0].command == "Ship via Next Day Air"
        assert cfg.watch_folders[0].auto_confirm is True

    def test_full_config(self, tmp_path, monkeypatch):
        """Full config with all sections parses correctly."""
        monkeypatch.setenv("UPS_ACCT", "ABC123")
        config_data = {
            "daemon": {"host": "0.0.0.0", "port": 9000, "log_format": "json"},
            "auto_confirm": {
                "enabled": True,
                "max_cost_cents": 100000,
                "allowed_services": ["03", "02"],
            },
            "watch_folders": [
                {"path": "./inbox", "command": "Ship all orders"}
            ],
            "shipper": {
                "name": "Acme Corp",
                "address_line": "123 Main St",
                "city": "Los Angeles",
                "state": "CA",
                "postal_code": "90001",
                "country_code": "US",
                "phone": "5551234567",
            },
            "ups": {"account_number": "${UPS_ACCT}"},
        }
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(config_path=str(config_file))
        assert cfg is not None
        assert cfg.daemon.host == "0.0.0.0"
        assert cfg.auto_confirm.allowed_services == ["03", "02"]
        assert cfg.shipper is not None
        assert cfg.shipper.name == "Acme Corp"
        assert cfg.ups is not None
        assert cfg.ups.account_number == "ABC123"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.cli'`

**Step 3: Write the implementation**

```python
# src/cli/__init__.py
"""ShipAgent CLI — headless automation suite."""
```

```python
# tests/cli/__init__.py
```

```python
# src/cli/config.py
"""YAML configuration loader with env var resolution and Pydantic validation.

Loads config from (priority order):
1. --config <path> CLI flag
2. ./shipagent.yaml (working directory)
3. ~/.shipagent/config.yaml (user home)

Environment variables override YAML: SHIPAGENT_<SECTION>_<KEY>.
${VAR} references in YAML values resolve from environment at load time.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def resolve_env_vars(value: str) -> str:
    """Resolve ${VAR} references in a string from environment variables.

    Args:
        value: String potentially containing ${VAR} references.

    Returns:
        String with all ${VAR} references replaced by their env values.
        Missing env vars resolve to empty string.
    """
    def _replace(match: re.Match) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _resolve_env_vars_recursive(data: Any) -> Any:
    """Recursively resolve ${VAR} references in a nested data structure.

    Args:
        data: Dict, list, or scalar value to process.

    Returns:
        Same structure with all string values resolved.
    """
    if isinstance(data, str):
        return resolve_env_vars(data)
    elif isinstance(data, dict):
        return {k: _resolve_env_vars_recursive(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_resolve_env_vars_recursive(item) for item in data]
    return data


class DaemonConfig(BaseModel):
    """Configuration for the ShipAgent daemon process."""

    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    pid_file: str = "~/.shipagent/daemon.pid"
    log_level: str = "info"
    log_format: str = "text"
    log_file: str | None = None


class AutoConfirmRules(BaseModel):
    """Rules for automatic job confirmation in headless mode."""

    enabled: bool = False
    max_cost_cents: int = 50000
    max_rows: int = 500
    max_cost_per_row_cents: int = 5000
    allowed_services: list[str] = []
    require_valid_addresses: bool = True
    allow_warnings: bool = False


class WatchFolderConfig(BaseModel):
    """Configuration for a single hot-folder watch directory."""

    path: str
    command: str
    auto_confirm: bool = False
    max_cost_cents: int | None = None
    max_rows: int | None = None
    file_types: list[str] = [".csv", ".xlsx"]


class ShipperConfig(BaseModel):
    """Shipper address configuration."""

    name: str = ""
    attention_name: str = ""
    address_line: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country_code: str = "US"
    phone: str = ""


class UPSConfig(BaseModel):
    """UPS API credentials configuration."""

    account_number: str = ""
    client_id: str = ""
    client_secret: str = ""


class ShipAgentConfig(BaseModel):
    """Top-level configuration for the ShipAgent headless automation suite."""

    daemon: DaemonConfig = DaemonConfig()
    auto_confirm: AutoConfirmRules = AutoConfirmRules()
    watch_folders: list[WatchFolderConfig] = []
    shipper: ShipperConfig | None = None
    ups: UPSConfig | None = None


def _find_config_file() -> Path | None:
    """Search for config file in standard locations.

    Returns:
        Path to config file if found, None otherwise.
    """
    candidates = [
        Path.cwd() / "shipagent.yaml",
        Path.cwd() / "shipagent.yml",
        Path.home() / ".shipagent" / "config.yaml",
        Path.home() / ".shipagent" / "config.yml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply SHIPAGENT_<SECTION>_<KEY> env var overrides to config data.

    Args:
        data: Parsed YAML config dict.

    Returns:
        Config dict with env var overrides applied.
    """
    prefix = "SHIPAGENT_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, field = parts
        if section not in data:
            data[section] = {}
        if isinstance(data[section], dict):
            # Try to coerce to int if the value looks numeric
            try:
                data[section][field] = int(value)
            except ValueError:
                if value.lower() in ("true", "false"):
                    data[section][field] = value.lower() == "true"
                else:
                    data[section][field] = value
    return data


def load_config(config_path: str | None = None) -> ShipAgentConfig | None:
    """Load ShipAgent configuration from YAML file with env var resolution.

    Args:
        config_path: Explicit path to config file. If None, searches
            standard locations (cwd, then ~/.shipagent/).

    Returns:
        Parsed and validated ShipAgentConfig, or None if no config found.
    """
    # Find config file
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
    else:
        path = _find_config_file()
        if path is None:
            return None

    logger.info("Loading config from %s", path)

    # Parse YAML
    with open(path) as f:
        raw_data = yaml.safe_load(f) or {}

    # Resolve ${VAR} references
    data = _resolve_env_vars_recursive(raw_data)

    # Apply SHIPAGENT_ env var overrides
    data = _apply_env_overrides(data)

    # Validate with Pydantic
    return ShipAgentConfig(**data)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_config.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/cli/__init__.py src/cli/config.py tests/cli/__init__.py tests/cli/test_config.py
git commit -m "feat(cli): add YAML config loader with Pydantic models and env var resolution"
```

---

## Task 3: Protocol & Data Models

**Files:**
- Create: `src/cli/protocol.py`
- Create: `tests/cli/test_protocol.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_protocol.py
"""Tests for the ShipAgentClient protocol and data models."""

from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    ShipAgentClient,
    SubmitResult,
)


class TestDataModels:
    """Tests for CLI data models."""

    def test_submit_result(self):
        """SubmitResult holds job submission outcome."""
        result = SubmitResult(
            job_id="job-123",
            status="pending",
            row_count=10,
            message="File imported, 10 rows queued",
        )
        assert result.job_id == "job-123"
        assert result.row_count == 10

    def test_job_summary(self):
        """JobSummary holds lightweight job listing data."""
        summary = JobSummary(
            id="job-123",
            name="CA Orders",
            status="running",
            total_rows=50,
            successful_rows=30,
            failed_rows=2,
            created_at="2026-02-16T10:00:00Z",
        )
        assert summary.id == "job-123"
        assert summary.status == "running"

    def test_job_detail(self):
        """JobDetail holds full job information."""
        detail = JobDetail(
            id="job-123",
            name="CA Orders",
            status="completed",
            original_command="Ship all CA orders",
            total_rows=50,
            processed_rows=50,
            successful_rows=48,
            failed_rows=2,
            total_cost_cents=62350,
            created_at="2026-02-16T10:00:00Z",
            started_at="2026-02-16T10:01:00Z",
            completed_at="2026-02-16T10:05:00Z",
            error_code=None,
            error_message=None,
            auto_confirm_violations=None,
        )
        assert detail.total_cost_cents == 62350
        assert detail.auto_confirm_violations is None

    def test_row_detail(self):
        """RowDetail holds per-row outcome data."""
        row = RowDetail(
            id="row-1",
            row_number=1,
            status="completed",
            tracking_number="1Z999AA10123456784",
            cost_cents=1250,
            error_code=None,
            error_message=None,
        )
        assert row.tracking_number == "1Z999AA10123456784"

    def test_health_status(self):
        """HealthStatus reports daemon health."""
        health = HealthStatus(
            healthy=True,
            version="3.0.0",
            uptime_seconds=3600,
            active_jobs=2,
            watchdog_active=True,
            watch_folders=["./inbox/priority"],
        )
        assert health.healthy is True
        assert health.watchdog_active is True

    def test_progress_event(self):
        """ProgressEvent holds streaming progress data."""
        event = ProgressEvent(
            job_id="job-123",
            event_type="row_completed",
            row_number=5,
            total_rows=50,
            tracking_number="1Z999AA10123456784",
            message="Row 5 completed",
        )
        assert event.event_type == "row_completed"

    def test_agent_event(self):
        """AgentEvent holds streaming agent output."""
        event = AgentEvent(
            event_type="agent_message_delta",
            content="I found 12 orders",
            tool_name=None,
            tool_input=None,
        )
        assert event.event_type == "agent_message_delta"


class TestProtocolExists:
    """Tests that ShipAgentClient protocol is properly defined."""

    def test_protocol_has_required_methods(self):
        """Protocol defines all required methods."""
        import inspect
        members = dict(inspect.getmembers(ShipAgentClient))
        required = [
            "submit_file", "list_jobs", "get_job", "get_job_rows",
            "cancel_job", "approve_job", "stream_progress",
            "send_message", "health", "cleanup",
            "create_session", "delete_session",
            "__aenter__", "__aexit__",
        ]
        for method in required:
            assert method in members, f"Missing protocol method: {method}"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/cli/protocol.py
"""ShipAgentClient protocol and CLI data models.

Defines the abstract interface that both HttpClient and InProcessRunner
implement. The CLI commands call protocol methods without knowing which
backend is active.
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


@dataclass
class SubmitResult:
    """Result of submitting a file for processing."""

    job_id: str
    status: str
    row_count: int
    message: str


@dataclass
class JobSummary:
    """Lightweight job data for list views."""

    id: str
    name: str
    status: str
    total_rows: int
    successful_rows: int
    failed_rows: int
    created_at: str


@dataclass
class JobDetail:
    """Full job detail with all fields."""

    id: str
    name: str
    status: str
    original_command: str
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    total_cost_cents: int
    created_at: str
    started_at: str | None
    completed_at: str | None
    error_code: str | None
    error_message: str | None
    auto_confirm_violations: list[dict] | None = None


@dataclass
class RowDetail:
    """Per-row outcome data."""

    id: str
    row_number: int
    status: str
    tracking_number: str | None
    cost_cents: int | None
    error_code: str | None
    error_message: str | None


@dataclass
class HealthStatus:
    """Daemon health report."""

    healthy: bool
    version: str
    uptime_seconds: int
    active_jobs: int
    watchdog_active: bool
    watch_folders: list[str] = field(default_factory=list)


@dataclass
class ProgressEvent:
    """Streaming progress event from batch execution."""

    job_id: str
    event_type: str
    row_number: int | None
    total_rows: int | None
    tracking_number: str | None = None
    message: str = ""


@dataclass
class AgentEvent:
    """Streaming event from agent conversation."""

    event_type: str
    content: str | None = None
    tool_name: str | None = None
    tool_input: str | None = None


class ShipAgentClient(Protocol):
    """Protocol defining the interface for CLI backends.

    Both HttpClient (daemon mode) and InProcessRunner (standalone mode)
    implement this protocol. CLI commands are written against this
    abstraction and never know which backend is active.
    """

    async def __aenter__(self) -> "ShipAgentClient":
        """Initialize resources (HTTP session or service stack)."""
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release resources on exit."""
        ...

    async def create_session(self, interactive: bool = False) -> str:
        """Create a new agent conversation session.

        Args:
            interactive: If True, creates an interactive shipping session.

        Returns:
            Session ID string.
        """
        ...

    async def delete_session(self, session_id: str) -> None:
        """Delete an agent conversation session.

        Args:
            session_id: The session to delete.
        """
        ...

    async def submit_file(
        self, file_path: str, command: str | None, auto_confirm: bool
    ) -> SubmitResult:
        """Import a file and submit it for agent processing.

        Args:
            file_path: Path to CSV or Excel file.
            command: Agent command (e.g. "Ship all orders via UPS Ground").
                     Defaults to "Ship all orders" if None.
            auto_confirm: Whether to apply auto-confirm rules.

        Returns:
            SubmitResult with job ID and status.
        """
        ...

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs with optional status filter.

        Args:
            status: Filter by status (pending, running, completed, etc.)

        Returns:
            List of JobSummary objects.
        """
        ...

    async def get_job(self, job_id: str) -> JobDetail:
        """Get full detail for a specific job.

        Args:
            job_id: The job ID.

        Returns:
            JobDetail with all fields.
        """
        ...

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get all rows for a job.

        Args:
            job_id: The job ID.

        Returns:
            List of RowDetail objects.
        """
        ...

    async def cancel_job(self, job_id: str) -> None:
        """Cancel a pending or running job.

        Args:
            job_id: The job to cancel.
        """
        ...

    async def approve_job(self, job_id: str) -> None:
        """Manually approve a job blocked by auto-confirm rules.

        Args:
            job_id: The job to approve.
        """
        ...

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream real-time progress events for a job.

        Args:
            job_id: The job to stream progress for.

        Yields:
            ProgressEvent objects as execution proceeds.
        """
        ...

    async def send_message(
        self, session_id: str, content: str
    ) -> AsyncIterator[AgentEvent]:
        """Send a message to an agent session and stream the response.

        Args:
            session_id: The conversation session ID.
            content: The user message content.

        Yields:
            AgentEvent objects (deltas, tool calls, previews, done).
        """
        ...

    async def health(self) -> HealthStatus:
        """Check daemon health status.

        Returns:
            HealthStatus with version, uptime, and component status.
        """
        ...

    async def cleanup(self) -> None:
        """Clean up resources (close connections, stop MCP clients)."""
        ...
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_protocol.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/cli/protocol.py tests/cli/test_protocol.py
git commit -m "feat(cli): add ShipAgentClient protocol and CLI data models"
```

---

## Task 4: Output Formatter

**Files:**
- Create: `src/cli/output.py`
- Create: `tests/cli/test_output.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_output.py
"""Tests for CLI output formatting."""

import json

from src.cli.output import format_job_table, format_job_detail, format_cost
from src.cli.protocol import JobSummary, JobDetail


class TestFormatCost:
    """Tests for cost formatting helper."""

    def test_formats_cents_to_dollars(self):
        """Converts cents integer to $X.XX string."""
        assert format_cost(1250) == "$12.50"
        assert format_cost(0) == "$0.00"
        assert format_cost(99) == "$0.99"
        assert format_cost(100000) == "$1,000.00"

    def test_none_returns_dash(self):
        """None cost displays as dash."""
        assert format_cost(None) == "—"


class TestFormatJobTable:
    """Tests for job list table rendering."""

    def test_renders_jobs_as_text(self):
        """Job list renders as a readable table."""
        jobs = [
            JobSummary(
                id="job-123", name="CA Orders", status="completed",
                total_rows=50, successful_rows=48, failed_rows=2,
                created_at="2026-02-16T10:00:00Z",
            ),
        ]
        output = format_job_table(jobs, as_json=False)
        assert "job-123" in output
        assert "CA Orders" in output
        assert "completed" in output

    def test_renders_jobs_as_json(self):
        """Job list renders as valid JSON array."""
        jobs = [
            JobSummary(
                id="job-123", name="CA Orders", status="completed",
                total_rows=50, successful_rows=48, failed_rows=2,
                created_at="2026-02-16T10:00:00Z",
            ),
        ]
        output = format_job_table(jobs, as_json=True)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert parsed[0]["id"] == "job-123"

    def test_empty_list(self):
        """Empty job list shows informative message."""
        output = format_job_table([], as_json=False)
        assert "No jobs found" in output


class TestFormatJobDetail:
    """Tests for detailed job view rendering."""

    def test_renders_detail_as_text(self):
        """Job detail renders with all fields."""
        detail = JobDetail(
            id="job-123", name="CA Orders", status="completed",
            original_command="Ship all CA orders",
            total_rows=50, processed_rows=50,
            successful_rows=48, failed_rows=2,
            total_cost_cents=62350,
            created_at="2026-02-16T10:00:00Z",
            started_at="2026-02-16T10:01:00Z",
            completed_at="2026-02-16T10:05:00Z",
            error_code=None, error_message=None,
        )
        output = format_job_detail(detail, as_json=False)
        assert "job-123" in output
        assert "$623.50" in output
        assert "Ship all CA orders" in output

    def test_renders_detail_as_json(self):
        """Job detail renders as valid JSON object."""
        detail = JobDetail(
            id="job-123", name="CA Orders", status="completed",
            original_command="Ship all CA orders",
            total_rows=50, processed_rows=50,
            successful_rows=48, failed_rows=2,
            total_cost_cents=62350,
            created_at="2026-02-16T10:00:00Z",
            started_at=None, completed_at=None,
            error_code=None, error_message=None,
        )
        output = format_job_detail(detail, as_json=True)
        parsed = json.loads(output)
        assert parsed["id"] == "job-123"
        assert parsed["total_cost_cents"] == 62350
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_output.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/cli/output.py
"""CLI output formatters for Rich tables and JSON.

Provides human-readable Rich table output (default) and machine-parseable
JSON output (--json flag). All formatting goes through these functions
so the CLI commands stay clean.
"""

import dataclasses
import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.cli.protocol import JobDetail, JobSummary, RowDetail

console = Console()

# Status color map (matches web UI domain colors)
STATUS_COLORS = {
    "pending": "yellow",
    "running": "blue",
    "completed": "green",
    "failed": "red",
    "cancelled": "dim",
    "paused": "yellow",
}


def format_cost(cents: int | None) -> str:
    """Format cost in cents as a dollar string.

    Args:
        cents: Cost in cents, or None.

    Returns:
        Formatted string like "$12.50" or "—" for None.
    """
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


def format_job_table(jobs: list[JobSummary], as_json: bool = False) -> str:
    """Format a list of jobs as a Rich table or JSON.

    Args:
        jobs: List of job summaries to display.
        as_json: If True, return JSON string instead of Rich table.

    Returns:
        Formatted string output.
    """
    if as_json:
        return json.dumps(
            [dataclasses.asdict(j) for j in jobs], indent=2
        )

    if not jobs:
        return "No jobs found."

    table = Table(title="Jobs", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("Status")
    table.add_column("Rows", justify="right")
    table.add_column("OK", justify="right", style="green")
    table.add_column("Fail", justify="right", style="red")
    table.add_column("Created")

    for job in jobs:
        status_color = STATUS_COLORS.get(job.status, "white")
        table.add_row(
            job.id[:12],
            job.name or "—",
            f"[{status_color}]{job.status}[/{status_color}]",
            str(job.total_rows),
            str(job.successful_rows),
            str(job.failed_rows),
            job.created_at[:19] if job.created_at else "—",
        )

    # Render to string
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def format_job_detail(detail: JobDetail, as_json: bool = False) -> str:
    """Format a single job's full detail as a Rich panel or JSON.

    Args:
        detail: Full job detail to display.
        as_json: If True, return JSON string instead of Rich panel.

    Returns:
        Formatted string output.
    """
    if as_json:
        return json.dumps(dataclasses.asdict(detail), indent=2)

    status_color = STATUS_COLORS.get(detail.status, "white")

    lines = [
        f"[bold]Job ID:[/bold]    {detail.id}",
        f"[bold]Name:[/bold]      {detail.name}",
        f"[bold]Status:[/bold]    [{status_color}]{detail.status}[/{status_color}]",
        f"[bold]Command:[/bold]   {detail.original_command}",
        "",
        f"[bold]Rows:[/bold]      {detail.processed_rows}/{detail.total_rows} processed",
        f"[bold]Success:[/bold]   [green]{detail.successful_rows}[/green]",
        f"[bold]Failed:[/bold]    [red]{detail.failed_rows}[/red]",
        f"[bold]Cost:[/bold]      {format_cost(detail.total_cost_cents)}",
        "",
        f"[bold]Created:[/bold]   {detail.created_at[:19] if detail.created_at else '—'}",
        f"[bold]Started:[/bold]   {detail.started_at[:19] if detail.started_at else '—'}",
        f"[bold]Completed:[/bold] {detail.completed_at[:19] if detail.completed_at else '—'}",
    ]

    if detail.error_code:
        lines.append("")
        lines.append(f"[bold red]Error:[/bold red] {detail.error_code}: {detail.error_message}")

    if detail.auto_confirm_violations:
        lines.append("")
        lines.append("[bold yellow]Auto-Confirm Violations:[/bold yellow]")
        for v in detail.auto_confirm_violations:
            lines.append(f"  - {v.get('message', v.get('rule', 'Unknown'))}")

    content = "\n".join(lines)

    with console.capture() as capture:
        console.print(Panel(content, title="Job Detail", border_style="cyan"))
    return capture.get()


def format_rows_table(rows: list[RowDetail], as_json: bool = False) -> str:
    """Format job rows as a Rich table or JSON.

    Args:
        rows: List of row details to display.
        as_json: If True, return JSON string instead of Rich table.

    Returns:
        Formatted string output.
    """
    if as_json:
        return json.dumps(
            [dataclasses.asdict(r) for r in rows], indent=2
        )

    if not rows:
        return "No rows found."

    table = Table(title="Job Rows", show_lines=True)
    table.add_column("#", justify="right")
    table.add_column("Status")
    table.add_column("Tracking", style="cyan")
    table.add_column("Cost", justify="right")
    table.add_column("Error")

    for row in rows:
        status_color = STATUS_COLORS.get(row.status, "white")
        table.add_row(
            str(row.row_number),
            f"[{status_color}]{row.status}[/{status_color}]",
            row.tracking_number or "—",
            format_cost(row.cost_cents),
            row.error_message[:40] if row.error_message else "—",
        )

    with console.capture() as capture:
        console.print(table)
    return capture.get()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_output.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/cli/output.py tests/cli/test_output.py
git commit -m "feat(cli): add Rich table and JSON output formatters"
```

---

## Task 5: Auto-Confirm Engine

**Files:**
- Create: `src/cli/auto_confirm.py`
- Create: `tests/cli/test_auto_confirm.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_auto_confirm.py
"""Tests for the auto-confirm rule evaluation engine."""

from src.cli.auto_confirm import AutoConfirmResult, RuleViolation, evaluate_auto_confirm
from src.cli.config import AutoConfirmRules


def _make_preview(
    total_rows: int = 10,
    total_cost_cents: int = 5000,
    max_row_cost_cents: int = 1000,
    service_codes: list[str] | None = None,
    address_valid: bool = True,
    has_warnings: bool = False,
) -> dict:
    """Build a mock preview result for testing."""
    return {
        "total_rows": total_rows,
        "total_cost_cents": total_cost_cents,
        "max_row_cost_cents": max_row_cost_cents,
        "service_codes": service_codes or ["03"],
        "all_addresses_valid": address_valid,
        "has_address_warnings": has_warnings,
    }


class TestEvaluateAutoConfirm:
    """Tests for the rule evaluation engine."""

    def test_all_rules_pass(self):
        """Approves when all rules are satisfied."""
        rules = AutoConfirmRules(
            enabled=True, max_cost_cents=10000, max_rows=50,
            allowed_services=["03"], max_cost_per_row_cents=2000,
        )
        preview = _make_preview()
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True
        assert len(result.violations) == 0

    def test_disabled_rejects(self):
        """Rejects when auto-confirm is globally disabled."""
        rules = AutoConfirmRules(enabled=False)
        result = evaluate_auto_confirm(rules, _make_preview())
        assert result.approved is False
        assert any(v.rule == "enabled" for v in result.violations)

    def test_max_rows_violation(self):
        """Rejects when row count exceeds threshold."""
        rules = AutoConfirmRules(enabled=True, max_rows=5)
        preview = _make_preview(total_rows=10)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "max_rows" for v in result.violations)
        violation = next(v for v in result.violations if v.rule == "max_rows")
        assert violation.threshold == 5
        assert violation.actual == 10

    def test_max_cost_violation(self):
        """Rejects when total cost exceeds threshold."""
        rules = AutoConfirmRules(enabled=True, max_cost_cents=1000)
        preview = _make_preview(total_cost_cents=5000)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "max_cost_cents" for v in result.violations)

    def test_max_cost_per_row_violation(self):
        """Rejects when any single row exceeds per-row threshold."""
        rules = AutoConfirmRules(enabled=True, max_cost_per_row_cents=500)
        preview = _make_preview(max_row_cost_cents=1000)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "max_cost_per_row_cents" for v in result.violations)

    def test_disallowed_service_violation(self):
        """Rejects when rows use services not in the whitelist."""
        rules = AutoConfirmRules(
            enabled=True, allowed_services=["03"],
        )
        preview = _make_preview(service_codes=["03", "01"])
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "allowed_services" for v in result.violations)

    def test_empty_allowed_services_allows_all(self):
        """Empty allowed_services list means no service restriction."""
        rules = AutoConfirmRules(enabled=True, allowed_services=[])
        preview = _make_preview(service_codes=["01", "02", "03"])
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True

    def test_invalid_address_violation(self):
        """Rejects when address validation fails."""
        rules = AutoConfirmRules(enabled=True, require_valid_addresses=True)
        preview = _make_preview(address_valid=False)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "require_valid_addresses" for v in result.violations)

    def test_address_warnings_violation(self):
        """Rejects on address warnings when allow_warnings is False."""
        rules = AutoConfirmRules(
            enabled=True, require_valid_addresses=True, allow_warnings=False,
        )
        preview = _make_preview(has_warnings=True)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert any(v.rule == "allow_warnings" for v in result.violations)

    def test_address_warnings_allowed(self):
        """Approves address warnings when allow_warnings is True."""
        rules = AutoConfirmRules(
            enabled=True, require_valid_addresses=True, allow_warnings=True,
        )
        preview = _make_preview(has_warnings=True)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is True

    def test_multiple_violations(self):
        """Collects all violations, not just the first."""
        rules = AutoConfirmRules(
            enabled=True, max_rows=5, max_cost_cents=1000,
        )
        preview = _make_preview(total_rows=10, total_cost_cents=5000)
        result = evaluate_auto_confirm(rules, preview)
        assert result.approved is False
        assert len(result.violations) >= 2
        rule_names = {v.rule for v in result.violations}
        assert "max_rows" in rule_names
        assert "max_cost_cents" in rule_names
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_auto_confirm.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/cli/auto_confirm.py
"""Auto-confirm rule evaluation engine.

Evaluates preview results against configured rules and returns
an approval decision with detailed violation information.
Rules are evaluated in order; all violations are collected.
"""

from dataclasses import dataclass, field

from src.cli.config import AutoConfirmRules
from src.cli.output import format_cost


@dataclass
class RuleViolation:
    """A single auto-confirm rule that was violated."""

    rule: str
    threshold: object
    actual: object
    message: str


@dataclass
class AutoConfirmResult:
    """Result of auto-confirm rule evaluation."""

    approved: bool
    reason: str
    violations: list[RuleViolation] = field(default_factory=list)


def evaluate_auto_confirm(
    rules: AutoConfirmRules, preview: dict
) -> AutoConfirmResult:
    """Evaluate a preview result against auto-confirm rules.

    Rules are checked in order (cheapest checks first). All violations
    are collected so operators see every issue at once.

    Args:
        rules: The auto-confirm rules to evaluate against.
        preview: Preview data dict with keys: total_rows, total_cost_cents,
                 max_row_cost_cents, service_codes, all_addresses_valid,
                 has_address_warnings.

    Returns:
        AutoConfirmResult with approval decision and any violations.
    """
    violations: list[RuleViolation] = []

    # Rule 0: Global kill switch
    if not rules.enabled:
        violations.append(RuleViolation(
            rule="enabled",
            threshold=True,
            actual=False,
            message="Auto-confirm is globally disabled",
        ))
        return AutoConfirmResult(
            approved=False,
            reason="Auto-confirm is disabled",
            violations=violations,
        )

    # Rule 1: Max rows (reject early before cost calculation)
    total_rows = preview.get("total_rows", 0)
    if total_rows > rules.max_rows:
        violations.append(RuleViolation(
            rule="max_rows",
            threshold=rules.max_rows,
            actual=total_rows,
            message=f"Row count {total_rows} exceeds limit {rules.max_rows}",
        ))

    # Rule 2: Max total cost
    total_cost = preview.get("total_cost_cents", 0)
    if total_cost > rules.max_cost_cents:
        violations.append(RuleViolation(
            rule="max_cost_cents",
            threshold=rules.max_cost_cents,
            actual=total_cost,
            message=(
                f"Total cost {format_cost(total_cost)} exceeds "
                f"limit {format_cost(rules.max_cost_cents)}"
            ),
        ))

    # Rule 3: Max cost per row (outlier detection)
    max_row_cost = preview.get("max_row_cost_cents", 0)
    if max_row_cost > rules.max_cost_per_row_cents:
        violations.append(RuleViolation(
            rule="max_cost_per_row_cents",
            threshold=rules.max_cost_per_row_cents,
            actual=max_row_cost,
            message=(
                f"Row cost {format_cost(max_row_cost)} exceeds "
                f"per-row limit {format_cost(rules.max_cost_per_row_cents)}"
            ),
        ))

    # Rule 4: Allowed services whitelist
    if rules.allowed_services:
        service_codes = set(preview.get("service_codes", []))
        allowed = set(rules.allowed_services)
        disallowed = service_codes - allowed
        if disallowed:
            violations.append(RuleViolation(
                rule="allowed_services",
                threshold=sorted(rules.allowed_services),
                actual=sorted(disallowed),
                message=f"Disallowed service codes: {', '.join(sorted(disallowed))}",
            ))

    # Rule 5: Address validation
    if rules.require_valid_addresses:
        if not preview.get("all_addresses_valid", True):
            violations.append(RuleViolation(
                rule="require_valid_addresses",
                threshold=True,
                actual=False,
                message="One or more addresses failed validation",
            ))

    # Rule 6: Address warnings
    if rules.require_valid_addresses and not rules.allow_warnings:
        if preview.get("has_address_warnings", False):
            violations.append(RuleViolation(
                rule="allow_warnings",
                threshold=False,
                actual=True,
                message="Address corrections detected (warnings not allowed)",
            ))

    if violations:
        return AutoConfirmResult(
            approved=False,
            reason=f"{len(violations)} rule(s) violated",
            violations=violations,
        )

    return AutoConfirmResult(
        approved=True,
        reason="All rules satisfied",
        violations=[],
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_auto_confirm.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/cli/auto_confirm.py tests/cli/test_auto_confirm.py
git commit -m "feat(cli): add auto-confirm rule evaluation engine"
```

---

## Task 6: Factory & CLI Skeleton

**Files:**
- Create: `src/cli/factory.py`
- Create: `src/cli/main.py`
- Create: `tests/cli/test_factory.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_factory.py
"""Tests for the client factory."""

import pytest

from src.cli.factory import get_client


class TestGetClient:
    """Tests for client factory dispatch."""

    def test_standalone_returns_runner(self):
        """Standalone mode returns InProcessRunner."""
        client = get_client(standalone=True)
        from src.cli.runner import InProcessRunner
        assert isinstance(client, InProcessRunner)

    def test_http_returns_http_client(self):
        """Default mode returns HttpClient."""
        client = get_client(standalone=False)
        from src.cli.http_client import HttpClient
        assert isinstance(client, HttpClient)

    def test_http_with_custom_url(self):
        """HttpClient accepts custom base URL."""
        client = get_client(standalone=False, base_url="http://pi.local:9000")
        assert client._base_url == "http://pi.local:9000"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_factory.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/cli/factory.py
"""Client factory for selecting HTTP or in-process backend.

The factory pattern ensures CLI commands never import concrete
implementations directly. The --standalone flag selects the backend.
"""

from src.cli.config import ShipAgentConfig


def get_client(
    standalone: bool = False,
    base_url: str | None = None,
    config: ShipAgentConfig | None = None,
):
    """Create the appropriate ShipAgentClient implementation.

    Args:
        standalone: If True, returns InProcessRunner (runs agent stack in-process).
                    If False, returns HttpClient (talks to daemon over HTTP).
        base_url: Custom daemon URL for HTTP mode. Defaults to http://127.0.0.1:8000.
        config: Loaded config for resolving daemon URL and other settings.

    Returns:
        A ShipAgentClient implementation (HttpClient or InProcessRunner).
    """
    if standalone:
        from src.cli.runner import InProcessRunner
        return InProcessRunner(config=config)
    else:
        if base_url is None:
            if config and config.daemon:
                base_url = f"http://{config.daemon.host}:{config.daemon.port}"
            else:
                base_url = "http://127.0.0.1:8000"
        from src.cli.http_client import HttpClient
        return HttpClient(base_url=base_url)
```

Now create stub implementations so the factory can import them:

```python
# src/cli/http_client.py
"""HTTP client implementation of ShipAgentClient.

Thin wrapper around httpx that talks to the ShipAgent daemon API.
All methods map to existing REST endpoints.
"""

from typing import AsyncIterator

from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    SubmitResult,
)


class HttpClient:
    """ShipAgentClient implementation that talks to the daemon over HTTP."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        """Initialize with daemon base URL.

        Args:
            base_url: The daemon's HTTP base URL.
        """
        self._base_url = base_url
        self._client = None

    async def __aenter__(self):
        """Open httpx async client."""
        import httpx
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close httpx async client."""
        if self._client:
            await self._client.aclose()

    async def create_session(self, interactive: bool = False) -> str:
        """Create conversation session via POST /api/v1/conversations/."""
        raise NotImplementedError("HttpClient.create_session — Task 8")

    async def delete_session(self, session_id: str) -> None:
        """Delete conversation session via DELETE /api/v1/conversations/{id}."""
        raise NotImplementedError("HttpClient.delete_session — Task 8")

    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult:
        """Submit file via POST /api/v1/data-sources/import + agent message."""
        raise NotImplementedError("HttpClient.submit_file — Task 9")

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs via GET /api/v1/jobs."""
        raise NotImplementedError("HttpClient.list_jobs — Task 8")

    async def get_job(self, job_id: str) -> JobDetail:
        """Get job detail via GET /api/v1/jobs/{id}."""
        raise NotImplementedError("HttpClient.get_job — Task 8")

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get job rows via GET /api/v1/jobs/{id}/rows."""
        raise NotImplementedError("HttpClient.get_job_rows — Task 8")

    async def cancel_job(self, job_id: str) -> None:
        """Cancel job via PATCH /api/v1/jobs/{id}/status."""
        raise NotImplementedError("HttpClient.cancel_job — Task 8")

    async def approve_job(self, job_id: str) -> None:
        """Approve job via POST /api/v1/jobs/{id}/confirm."""
        raise NotImplementedError("HttpClient.approve_job — Task 8")

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream progress via GET /api/v1/jobs/{id}/progress/stream."""
        raise NotImplementedError("HttpClient.stream_progress — Task 8")
        yield  # pragma: no cover

    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]:
        """Send message via POST /api/v1/conversations/{id}/messages."""
        raise NotImplementedError("HttpClient.send_message — Task 10")
        yield  # pragma: no cover

    async def health(self) -> HealthStatus:
        """Check health via GET /health."""
        raise NotImplementedError("HttpClient.health — Task 8")

    async def cleanup(self) -> None:
        """No-op for HTTP client (stateless)."""
        pass
```

```python
# src/cli/runner.py
"""In-process runner implementation of ShipAgentClient.

Runs the full agent stack directly without requiring a daemon.
Used for development, testing, and standalone deployments.
"""

from typing import AsyncIterator

from src.cli.config import ShipAgentConfig
from src.cli.protocol import (
    AgentEvent,
    HealthStatus,
    JobDetail,
    JobSummary,
    ProgressEvent,
    RowDetail,
    SubmitResult,
)


class InProcessRunner:
    """ShipAgentClient implementation that runs the agent stack in-process."""

    def __init__(self, config: ShipAgentConfig | None = None):
        """Initialize with optional config.

        Args:
            config: Loaded ShipAgent config. Uses defaults if None.
        """
        self._config = config
        self._initialized = False

    async def __aenter__(self):
        """Initialize DB, MCP gateways, and agent session manager."""
        from src.db.connection import init_db
        init_db()
        self._initialized = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Shut down MCP gateways."""
        if self._initialized:
            from src.services.gateway_provider import shutdown_gateways
            await shutdown_gateways()

    async def create_session(self, interactive: bool = False) -> str:
        """Create agent session in-process."""
        raise NotImplementedError("InProcessRunner.create_session — Task 10")

    async def delete_session(self, session_id: str) -> None:
        """Delete agent session in-process."""
        raise NotImplementedError("InProcessRunner.delete_session — Task 10")

    async def submit_file(self, file_path: str, command: str | None,
                          auto_confirm: bool) -> SubmitResult:
        """Import file and run agent command in-process."""
        raise NotImplementedError("InProcessRunner.submit_file — Task 10")

    async def list_jobs(self, status: str | None = None) -> list[JobSummary]:
        """List jobs directly from database."""
        raise NotImplementedError("InProcessRunner.list_jobs — Task 10")

    async def get_job(self, job_id: str) -> JobDetail:
        """Get job detail directly from database."""
        raise NotImplementedError("InProcessRunner.get_job — Task 10")

    async def get_job_rows(self, job_id: str) -> list[RowDetail]:
        """Get job rows directly from database."""
        raise NotImplementedError("InProcessRunner.get_job_rows — Task 10")

    async def cancel_job(self, job_id: str) -> None:
        """Cancel job directly via JobService."""
        raise NotImplementedError("InProcessRunner.cancel_job — Task 10")

    async def approve_job(self, job_id: str) -> None:
        """Approve job directly via batch execution."""
        raise NotImplementedError("InProcessRunner.approve_job — Task 10")

    async def stream_progress(self, job_id: str) -> AsyncIterator[ProgressEvent]:
        """Stream progress in-process."""
        raise NotImplementedError("InProcessRunner.stream_progress — Task 10")
        yield  # pragma: no cover

    async def send_message(self, session_id: str,
                           content: str) -> AsyncIterator[AgentEvent]:
        """Send message to agent in-process."""
        raise NotImplementedError("InProcessRunner.send_message — Task 10")
        yield  # pragma: no cover

    async def health(self) -> HealthStatus:
        """Report in-process health (always healthy if running)."""
        return HealthStatus(
            healthy=True,
            version="3.0.0",
            uptime_seconds=0,
            active_jobs=0,
            watchdog_active=False,
        )

    async def cleanup(self) -> None:
        """Shut down gateways."""
        from src.services.gateway_provider import shutdown_gateways
        await shutdown_gateways()
```

Now create the Typer CLI skeleton:

```python
# src/cli/main.py
"""ShipAgent CLI — headless automation suite.

Unified entry point for daemon management, job control,
file submission, and conversational shipping.

Usage:
    shipagent daemon start     Start the ShipAgent daemon
    shipagent job list         List all jobs
    shipagent submit file.csv  Submit a file for processing
    shipagent interact         Start conversational REPL
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from src.cli.config import load_config
from src.cli.factory import get_client
from src.cli.output import format_job_detail, format_job_table, format_rows_table

app = typer.Typer(
    name="shipagent",
    help="AI-native shipping automation — headless CLI",
    no_args_is_help=True,
)
daemon_app = typer.Typer(help="Manage the ShipAgent daemon")
job_app = typer.Typer(help="Manage shipping jobs")
config_app = typer.Typer(help="Configuration management")

app.add_typer(daemon_app, name="daemon")
app.add_typer(job_app, name="job")
app.add_typer(config_app, name="config")

console = Console()

# --- Global state ---
_standalone: bool = False
_config_path: str | None = None


@app.callback()
def main(
    standalone: bool = typer.Option(
        False, "--standalone", help="Run in-process without daemon"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", help="Path to shipagent.yaml config file"
    ),
):
    """ShipAgent CLI — AI-native shipping automation."""
    global _standalone, _config_path
    _standalone = standalone
    _config_path = config


# --- Version ---


@app.command()
def version():
    """Show ShipAgent version and dependency info."""
    console.print("[bold]ShipAgent[/bold] v3.0.0")
    console.print("  CLI: headless automation suite")
    try:
        import claude_agent_sdk
        console.print(f"  Agent SDK: {getattr(claude_agent_sdk, '__version__', 'unknown')}")
    except ImportError:
        console.print("  Agent SDK: [red]not installed[/red]")


# --- Config commands ---


@config_app.command("show")
def config_show():
    """Display resolved configuration (secrets masked)."""
    cfg = load_config(config_path=_config_path)
    if cfg is None:
        console.print("[yellow]No config file found.[/yellow]")
        console.print("Searched: ./shipagent.yaml, ~/.shipagent/config.yaml")
        raise typer.Exit(1)

    console.print("[bold]Daemon:[/bold]")
    console.print(f"  host: {cfg.daemon.host}")
    console.print(f"  port: {cfg.daemon.port}")
    console.print(f"  log_level: {cfg.daemon.log_level}")

    console.print("\n[bold]Auto-Confirm:[/bold]")
    console.print(f"  enabled: {cfg.auto_confirm.enabled}")
    console.print(f"  max_cost: ${cfg.auto_confirm.max_cost_cents / 100:.2f}")
    console.print(f"  max_rows: {cfg.auto_confirm.max_rows}")

    if cfg.watch_folders:
        console.print(f"\n[bold]Watch Folders ({len(cfg.watch_folders)}):[/bold]")
        for wf in cfg.watch_folders:
            console.print(f"  {wf.path} → \"{wf.command}\"")

    if cfg.ups:
        console.print("\n[bold]UPS:[/bold]")
        acct = cfg.ups.account_number
        console.print(f"  account: {'***' + acct[-4:] if len(acct) > 4 else '***'}")


@config_app.command("validate")
def config_validate(
    config: Optional[str] = typer.Option(None, "--config", help="Config file path"),
):
    """Validate a config file without starting the daemon."""
    path = config or _config_path
    try:
        cfg = load_config(config_path=path)
        if cfg is None:
            console.print("[red]No config file found.[/red]")
            raise typer.Exit(1)
        console.print("[green]Config is valid.[/green]")
        console.print(f"  Watch folders: {len(cfg.watch_folders)}")
        console.print(f"  Auto-confirm: {'enabled' if cfg.auto_confirm.enabled else 'disabled'}")
    except Exception as e:
        console.print(f"[red]Config validation failed:[/red] {e}")
        raise typer.Exit(1)


# --- Job commands ---


@job_app.command("list")
def job_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all shipping jobs."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            jobs = await client.list_jobs(status=status)
            output = format_job_table(jobs, as_json=json_output)
            console.print(output)

    asyncio.run(_run())


@job_app.command("inspect")
def job_inspect(
    job_id: str = typer.Argument(help="Job ID to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show detailed information about a specific job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            detail = await client.get_job(job_id)
            output = format_job_detail(detail, as_json=json_output)
            console.print(output)

    asyncio.run(_run())


@job_app.command("rows")
def job_rows(
    job_id: str = typer.Argument(help="Job ID"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show rows for a specific job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            rows = await client.get_job_rows(job_id)
            output = format_rows_table(rows, as_json=json_output)
            console.print(output)

    asyncio.run(_run())


@job_app.command("approve")
def job_approve(
    job_id: str = typer.Argument(help="Job ID to approve"),
):
    """Manually approve a job blocked by auto-confirm rules."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            await client.approve_job(job_id)
            console.print(f"[green]Job {job_id} approved and queued for execution.[/green]")

    asyncio.run(_run())


@job_app.command("cancel")
def job_cancel(
    job_id: str = typer.Argument(help="Job ID to cancel"),
):
    """Cancel a pending or running job."""
    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            await client.cancel_job(job_id)
            console.print(f"[yellow]Job {job_id} cancelled.[/yellow]")

    asyncio.run(_run())


# --- Submit command ---


@app.command()
def submit(
    file: Path = typer.Argument(help="Path to CSV or Excel file"),
    command: Optional[str] = typer.Option(
        None, "--command", "-c", help='Agent command (default: "Ship all orders")'
    ),
    service: Optional[str] = typer.Option(
        None, "--service", "-s", help="Service shorthand (e.g., 'UPS Ground')"
    ),
    auto_confirm: bool = typer.Option(
        False, "--auto-confirm", help="Apply auto-confirm rules"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Submit a file for shipping processing."""
    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    # Build command from --service shorthand if provided
    if command is None and service:
        command = f"Ship all orders using {service}"
    elif command is None:
        command = "Ship all orders"

    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)

    async def _run():
        async with client:
            result = await client.submit_file(
                file_path=str(file.resolve()),
                command=command,
                auto_confirm=auto_confirm,
            )
            if json_output:
                import dataclasses, json
                console.print(json.dumps(dataclasses.asdict(result), indent=2))
            else:
                console.print(f"[green]Job submitted:[/green] {result.job_id}")
                console.print(f"  Status: {result.status}")
                console.print(f"  Rows: {result.row_count}")
                console.print(f"  {result.message}")

    asyncio.run(_run())


# --- Daemon commands (placeholder for Task 7) ---


@daemon_app.command("start")
def daemon_start(
    host: Optional[str] = typer.Option(None, "--host", help="Bind address"),
    port: Optional[int] = typer.Option(None, "--port", help="Bind port"),
):
    """Start the ShipAgent daemon (FastAPI + Watchdog)."""
    console.print("[yellow]Daemon start — implemented in Task 7[/yellow]")


@daemon_app.command("stop")
def daemon_stop():
    """Stop the ShipAgent daemon."""
    console.print("[yellow]Daemon stop — implemented in Task 7[/yellow]")


@daemon_app.command("status")
def daemon_status():
    """Check daemon status."""
    console.print("[yellow]Daemon status — implemented in Task 7[/yellow]")


# --- Interact command (placeholder for Task 11) ---


@app.command()
def interact(
    session: Optional[str] = typer.Option(
        None, "--session", help="Resume existing session ID"
    ),
):
    """Start a conversational shipping REPL."""
    console.print("[yellow]Interactive REPL — implemented in Task 11[/yellow]")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_factory.py -v`
Expected: All tests PASS.

**Step 5: Verify CLI works**

Run: `pip install -e '.[dev]' && shipagent --help`
Expected: Shows help with daemon, job, config subcommands.

Run: `shipagent version`
Expected: Shows `ShipAgent v3.0.0` and SDK version.

Run: `shipagent config validate`
Expected: "No config file found" (no shipagent.yaml yet).

**Step 6: Commit**

```bash
git add src/cli/factory.py src/cli/main.py src/cli/http_client.py src/cli/runner.py tests/cli/test_factory.py
git commit -m "feat(cli): add Typer CLI skeleton with factory pattern and command stubs"
```

---

## Task 7: Daemon Management

**Files:**
- Create: `src/cli/daemon.py`
- Create: `tests/cli/test_daemon.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_daemon.py
"""Tests for daemon PID management."""

import os
import signal

from src.cli.daemon import (
    read_pid_file,
    write_pid_file,
    is_pid_alive,
    remove_pid_file,
)


class TestPidFile:
    """Tests for PID file read/write/cleanup."""

    def test_write_and_read(self, tmp_path):
        """Write PID file and read it back."""
        pid_file = str(tmp_path / "test.pid")
        write_pid_file(pid_file, 12345)
        assert read_pid_file(pid_file) == 12345

    def test_read_missing_file(self, tmp_path):
        """Reading missing PID file returns None."""
        pid_file = str(tmp_path / "missing.pid")
        assert read_pid_file(pid_file) is None

    def test_remove_pid_file(self, tmp_path):
        """Remove PID file cleans up."""
        pid_file = str(tmp_path / "test.pid")
        write_pid_file(pid_file, 12345)
        remove_pid_file(pid_file)
        assert read_pid_file(pid_file) is None

    def test_is_pid_alive_current_process(self):
        """Current process PID is alive."""
        assert is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_nonexistent(self):
        """Non-existent PID is not alive."""
        # PID 999999 is unlikely to exist
        assert is_pid_alive(999999) is False

    def test_write_creates_parent_dirs(self, tmp_path):
        """Writing PID file creates parent directories."""
        pid_file = str(tmp_path / "nested" / "dir" / "test.pid")
        write_pid_file(pid_file, 12345)
        assert read_pid_file(pid_file) == 12345
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/cli/daemon.py
"""Daemon management — start, stop, status.

Wraps uvicorn.run() programmatically with PID file management
for clean start/stop/status lifecycle.
"""

import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def write_pid_file(pid_file: str, pid: int) -> None:
    """Write the current process PID to a file.

    Args:
        pid_file: Path to PID file. Parent dirs created if needed.
        pid: Process ID to write.
    """
    path = Path(pid_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def read_pid_file(pid_file: str) -> int | None:
    """Read PID from a file.

    Args:
        pid_file: Path to PID file.

    Returns:
        The PID as int, or None if file doesn't exist or is invalid.
    """
    path = Path(pid_file).expanduser()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_pid_file(pid_file: str) -> None:
    """Remove the PID file.

    Args:
        pid_file: Path to PID file. No-op if file doesn't exist.
    """
    path = Path(pid_file).expanduser()
    if path.exists():
        path.unlink()


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Args:
        pid: Process ID to check.

    Returns:
        True if process exists and is accessible.
    """
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def start_daemon(
    host: str = "127.0.0.1",
    port: int = 8000,
    pid_file: str = "~/.shipagent/daemon.pid",
    log_level: str = "info",
) -> None:
    """Start the ShipAgent daemon using uvicorn.

    Args:
        host: Bind address.
        port: Bind port.
        pid_file: Path to write PID file.
        log_level: Logging level for uvicorn.
    """
    import uvicorn

    # Check for stale PID
    existing_pid = read_pid_file(pid_file)
    if existing_pid is not None:
        if is_pid_alive(existing_pid):
            logger.error(
                "Daemon already running (PID %d). Use 'shipagent daemon stop' first.",
                existing_pid,
            )
            sys.exit(1)
        else:
            logger.warning("Removing stale PID file (PID %d no longer running)", existing_pid)
            remove_pid_file(pid_file)

    # Write current PID
    write_pid_file(pid_file, os.getpid())
    logger.info("Daemon starting on %s:%d (PID %d)", host, port, os.getpid())

    try:
        uvicorn.run(
            "src.api.main:app",
            host=host,
            port=port,
            workers=1,
            log_level=log_level,
            lifespan="on",
        )
    finally:
        remove_pid_file(pid_file)


def stop_daemon(pid_file: str = "~/.shipagent/daemon.pid") -> bool:
    """Stop the ShipAgent daemon by sending SIGTERM.

    Args:
        pid_file: Path to PID file.

    Returns:
        True if signal was sent successfully, False if daemon not running.
    """
    pid = read_pid_file(pid_file)
    if pid is None:
        logger.info("No PID file found — daemon may not be running")
        return False

    if not is_pid_alive(pid):
        logger.warning("PID %d not running — cleaning up stale PID file", pid)
        remove_pid_file(pid_file)
        return False

    logger.info("Sending SIGTERM to daemon (PID %d)", pid)
    os.kill(pid, signal.SIGTERM)
    remove_pid_file(pid_file)
    return True


def daemon_status(
    pid_file: str = "~/.shipagent/daemon.pid",
    base_url: str = "http://127.0.0.1:8000",
) -> dict:
    """Check daemon status.

    Args:
        pid_file: Path to PID file.
        base_url: Daemon HTTP base URL for health check.

    Returns:
        Dict with pid, alive, healthy keys.
    """
    pid = read_pid_file(pid_file)
    alive = pid is not None and is_pid_alive(pid)

    result = {"pid": pid, "alive": alive, "healthy": False}

    if alive:
        try:
            import httpx
            resp = httpx.get(f"{base_url}/health", timeout=5.0)
            result["healthy"] = resp.status_code == 200
        except Exception:
            result["healthy"] = False

    return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_daemon.py -v`
Expected: All tests PASS.

**Step 5: Wire daemon commands into main.py**

Update the daemon command stubs in `src/cli/main.py`:

Replace the `daemon_start`, `daemon_stop`, and `daemon_status` functions with:

```python
@daemon_app.command("start")
def daemon_start_cmd(
    host: Optional[str] = typer.Option(None, "--host", help="Bind address"),
    port: Optional[int] = typer.Option(None, "--port", help="Bind port"),
):
    """Start the ShipAgent daemon (FastAPI + Watchdog)."""
    from src.cli.daemon import start_daemon

    cfg = load_config(config_path=_config_path)
    final_host = host or (cfg.daemon.host if cfg else "127.0.0.1")
    final_port = port or (cfg.daemon.port if cfg else 8000)
    pid_file = cfg.daemon.pid_file if cfg else "~/.shipagent/daemon.pid"
    log_level = cfg.daemon.log_level if cfg else "info"

    console.print(f"[bold]Starting ShipAgent daemon on {final_host}:{final_port}[/bold]")
    start_daemon(host=final_host, port=final_port, pid_file=pid_file, log_level=log_level)


@daemon_app.command("stop")
def daemon_stop_cmd():
    """Stop the ShipAgent daemon."""
    from src.cli.daemon import stop_daemon

    cfg = load_config(config_path=_config_path)
    pid_file = cfg.daemon.pid_file if cfg else "~/.shipagent/daemon.pid"

    if stop_daemon(pid_file=pid_file):
        console.print("[green]Daemon stopped.[/green]")
    else:
        console.print("[yellow]Daemon is not running.[/yellow]")


@daemon_app.command("status")
def daemon_status_cmd():
    """Check daemon status."""
    from src.cli.daemon import daemon_status as check_status

    cfg = load_config(config_path=_config_path)
    pid_file = cfg.daemon.pid_file if cfg else "~/.shipagent/daemon.pid"
    base_url = f"http://{cfg.daemon.host}:{cfg.daemon.port}" if cfg else "http://127.0.0.1:8000"

    status = check_status(pid_file=pid_file, base_url=base_url)
    if status["alive"] and status["healthy"]:
        console.print(f"[green]Daemon running[/green] (PID {status['pid']}) — healthy")
    elif status["alive"]:
        console.print(f"[yellow]Daemon running[/yellow] (PID {status['pid']}) — unhealthy")
    else:
        console.print("[red]Daemon not running[/red]")
```

**Step 6: Commit**

```bash
git add src/cli/daemon.py tests/cli/test_daemon.py src/cli/main.py
git commit -m "feat(cli): add daemon start/stop/status with PID file management"
```

---

## Task 8: HTTP Client Implementation

**Files:**
- Modify: `src/cli/http_client.py`
- Create: `tests/cli/test_http_client.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_http_client.py
"""Tests for HttpClient — mocked HTTP responses."""

import json

import pytest
import httpx

from src.cli.http_client import HttpClient
from src.cli.protocol import JobSummary, JobDetail


class FakeTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns canned responses."""

    def __init__(self, responses: dict[str, tuple[int, dict]]):
        self._responses = responses

    async def handle_async_request(self, request):
        path = request.url.path
        for pattern, (status, body) in self._responses.items():
            if pattern in path:
                return httpx.Response(
                    status, json=body,
                    request=request,
                )
        return httpx.Response(404, json={"error": "not found"}, request=request)


def _make_client(responses: dict) -> HttpClient:
    """Create HttpClient with mocked transport."""
    client = HttpClient(base_url="http://test:8000")
    transport = FakeTransport(responses)
    client._client = httpx.AsyncClient(transport=transport, base_url="http://test:8000")
    return client


class TestListJobs:
    """Tests for HttpClient.list_jobs."""

    @pytest.mark.asyncio
    async def test_returns_job_summaries(self):
        """Parses job list response into JobSummary objects."""
        client = _make_client({
            "/api/v1/jobs": (200, {
                "jobs": [{
                    "id": "job-1", "name": "Test", "status": "completed",
                    "total_rows": 10, "successful_rows": 9, "failed_rows": 1,
                    "created_at": "2026-02-16T10:00:00Z",
                }],
                "total": 1, "limit": 50, "offset": 0,
            })
        })
        jobs = await client.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "job-1"
        assert jobs[0].status == "completed"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty job list returns empty array."""
        client = _make_client({
            "/api/v1/jobs": (200, {"jobs": [], "total": 0, "limit": 50, "offset": 0})
        })
        jobs = await client.list_jobs()
        assert jobs == []


class TestGetJob:
    """Tests for HttpClient.get_job."""

    @pytest.mark.asyncio
    async def test_returns_job_detail(self):
        """Parses job response into JobDetail."""
        client = _make_client({
            "/api/v1/jobs/job-1": (200, {
                "id": "job-1", "name": "Test", "status": "completed",
                "original_command": "Ship all", "total_rows": 10,
                "processed_rows": 10, "successful_rows": 9, "failed_rows": 1,
                "total_cost_cents": 5000, "created_at": "2026-02-16T10:00:00Z",
                "started_at": None, "completed_at": None,
                "error_code": None, "error_message": None,
            })
        })
        detail = await client.get_job("job-1")
        assert detail.id == "job-1"
        assert detail.total_cost_cents == 5000


class TestHealth:
    """Tests for HttpClient.health."""

    @pytest.mark.asyncio
    async def test_healthy(self):
        """Health check parses response."""
        client = _make_client({
            "/health": (200, {"status": "healthy"})
        })
        status = await client.health()
        assert status.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy(self):
        """Connection failure reports unhealthy."""
        client = HttpClient(base_url="http://localhost:99999")
        # Don't set mock transport — will fail to connect
        client._client = httpx.AsyncClient(base_url="http://localhost:99999", timeout=0.1)
        status = await client.health()
        assert status.healthy is False


class TestCancelJob:
    """Tests for HttpClient.cancel_job."""

    @pytest.mark.asyncio
    async def test_sends_patch(self):
        """Cancel sends PATCH with cancelled status."""
        client = _make_client({
            "/api/v1/jobs/job-1/status": (200, {
                "id": "job-1", "name": "Test", "status": "cancelled",
                "total_rows": 0, "processed_rows": 0,
                "successful_rows": 0, "failed_rows": 0,
                "total_cost_cents": 0,
                "created_at": "2026-02-16T10:00:00Z",
                "original_command": "test",
                "started_at": None, "completed_at": None,
                "error_code": None, "error_message": None,
            })
        })
        await client.cancel_job("job-1")  # Should not raise


class TestCreateSession:
    """Tests for HttpClient.create_session."""

    @pytest.mark.asyncio
    async def test_creates_session(self):
        """Creates conversation session via API."""
        client = _make_client({
            "/api/v1/conversations": (200, {"session_id": "sess-abc"})
        })
        session_id = await client.create_session()
        assert session_id == "sess-abc"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_http_client.py -v`
Expected: FAIL (NotImplementedError from stubs)

**Step 3: Replace stubs in http_client.py with real implementations**

Update `src/cli/http_client.py` — replace all `raise NotImplementedError` stubs with actual httpx calls. The key implementations:

- `list_jobs` → `GET /api/v1/jobs`
- `get_job` → `GET /api/v1/jobs/{id}`
- `get_job_rows` → `GET /api/v1/jobs/{id}/rows`
- `cancel_job` → `PATCH /api/v1/jobs/{id}/status` with `{"status": "cancelled"}`
- `approve_job` → `POST /api/v1/jobs/{id}/confirm`
- `create_session` → `POST /api/v1/conversations/`
- `delete_session` → `DELETE /api/v1/conversations/{id}`
- `health` → `GET /health`
- `submit_file` → `POST /api/v1/data-sources/import` + `POST /api/v1/conversations/{id}/messages`
- `stream_progress` → `GET /api/v1/jobs/{id}/progress/stream` (SSE parsing)
- `send_message` → `POST /api/v1/conversations/{id}/messages` + `GET /api/v1/conversations/{id}/stream` (SSE parsing)

Each method parses the JSON response into the appropriate protocol dataclass. Error responses raise `typer.Exit(1)` with a Rich error message.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_http_client.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/cli/http_client.py tests/cli/test_http_client.py
git commit -m "feat(cli): implement HttpClient with httpx for all daemon API calls"
```

---

## Task 9: Health Endpoint Enhancement

**Files:**
- Modify: `src/api/main.py:141-148`

**Step 1: Enhance the /health endpoint**

The existing `/health` endpoint returns `{"status": "healthy"}`. Enhance it to include version, uptime, and active job count so `shipagent daemon status` and `HttpClient.health()` get richer data.

```python
# Replace the existing health_check function in src/api/main.py

import time as _time

_startup_time: float = 0.0

# In startup_event(), add:
#   global _startup_time
#   _startup_time = _time.time()

@app.get("/health")
def health_check() -> dict:
    """Health check endpoint with system status.

    Returns:
        Dictionary with health status, version, and metrics.
    """
    uptime = int(_time.time() - _startup_time) if _startup_time else 0
    return {
        "status": "healthy",
        "version": "3.0.0",
        "uptime_seconds": uptime,
    }
```

**Step 2: Run existing tests**

Run: `pytest tests/api/ -v -k "health"`
Expected: PASS (existing health tests should still pass with the added fields).

**Step 3: Commit**

```bash
git add src/api/main.py
git commit -m "feat(api): enhance /health endpoint with version and uptime"
```

---

## Task 10: InProcessRunner Implementation

**Files:**
- Modify: `src/cli/runner.py`
- Create: `tests/cli/test_runner.py`

**Step 1: Write the failing tests**

```python
# tests/cli/test_runner.py
"""Tests for InProcessRunner — in-process agent stack."""

import pytest

from src.cli.runner import InProcessRunner


class TestInProcessRunnerLifecycle:
    """Tests for runner initialization and cleanup."""

    @pytest.mark.asyncio
    async def test_context_manager_initializes_db(self):
        """Entering context initializes the database."""
        runner = InProcessRunner()
        async with runner:
            assert runner._initialized is True

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self):
        """In-process runner always reports healthy."""
        runner = InProcessRunner()
        async with runner:
            status = await runner.health()
            assert status.healthy is True


class TestInProcessRunnerJobs:
    """Tests for job operations via direct DB access."""

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self):
        """Empty database returns empty job list."""
        runner = InProcessRunner()
        async with runner:
            jobs = await runner.list_jobs()
            assert isinstance(jobs, list)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_runner.py -v`
Expected: FAIL (NotImplementedError)

**Step 3: Implement InProcessRunner**

Replace the stubs in `src/cli/runner.py` with implementations that directly use `JobService`, `AgentSessionManager`, `get_data_gateway()`, etc.

Key implementations:
- `list_jobs` → `JobService(db).list_jobs()` → map `Job` → `JobSummary`
- `get_job` → `JobService(db).get_job()` → map `Job` → `JobDetail`
- `get_job_rows` → `JobService(db).get_rows()` → map `JobRow` → `RowDetail`
- `cancel_job` → `JobService(db).update_status(job_id, JobStatus.cancelled)`
- `approve_job` → Execute batch inline (mirror `preview.py:_execute_batch`)
- `create_session` → `AgentSessionManager().get_or_create_session(uuid4())`
- `send_message` → `session.agent.process_message_stream(content)` → yield `AgentEvent`
- `submit_file` → `get_data_gateway().import_csv()` → create session → send command

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_runner.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/cli/runner.py tests/cli/test_runner.py
git commit -m "feat(cli): implement InProcessRunner with direct service access"
```

---

## Task 11: Conversational REPL

**Files:**
- Create: `src/cli/repl.py`
- Modify: `src/cli/main.py` (wire interact command)

**Step 1: Write the REPL implementation**

```python
# src/cli/repl.py
"""Interactive conversational REPL for the ShipAgent agent.

Provides a terminal-based chat interface with Rich rendering
for previews, progress, and completions.
"""

import asyncio
import signal

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from src.cli.output import format_cost
from src.cli.protocol import AgentEvent, ShipAgentClient

console = Console()


async def run_repl(client: ShipAgentClient, session_id: str | None = None) -> None:
    """Run the interactive conversational REPL.

    Args:
        client: The ShipAgentClient implementation (HTTP or in-process).
        session_id: Optional session ID to resume. Creates new if None.
    """
    async with client:
        # Create or resume session
        if session_id is None:
            session_id = await client.create_session(interactive=False)
            console.print(f"[dim]Session: {session_id}[/dim]")

        console.print()
        console.print("[bold]ShipAgent[/bold] v3.0 — Interactive Mode")
        console.print("Type your shipping commands. Ctrl+D to exit.")
        console.print()

        try:
            while True:
                try:
                    user_input = console.input("[bold green]> [/bold green]")
                except EOFError:
                    # Ctrl+D
                    break

                if not user_input.strip():
                    continue

                # Stream agent response
                message_buffer = []
                try:
                    async for event in client.send_message(session_id, user_input):
                        if event.event_type == "agent_message_delta":
                            if event.content:
                                console.print(event.content, end="")
                                message_buffer.append(event.content)
                        elif event.event_type == "tool_call":
                            console.print(
                                f"\n[dim]Tool: {event.tool_name}[/dim]", end=""
                            )
                        elif event.event_type == "done":
                            break
                        elif event.event_type == "error":
                            console.print(
                                f"\n[red]Error: {event.content}[/red]"
                            )
                except KeyboardInterrupt:
                    console.print("\n[yellow]Interrupted[/yellow]")
                    continue

                console.print()  # Newline after streamed response

        finally:
            # Cleanup session
            try:
                await client.delete_session(session_id)
            except Exception:
                pass

        console.print("\n[dim]Session ended.[/dim]")
```

**Step 2: Wire into main.py**

Replace the `interact` placeholder in `src/cli/main.py`:

```python
@app.command()
def interact(
    session: Optional[str] = typer.Option(
        None, "--session", help="Resume existing session ID"
    ),
):
    """Start a conversational shipping REPL."""
    from src.cli.repl import run_repl

    cfg = load_config(config_path=_config_path)
    client = get_client(standalone=_standalone, config=cfg)
    asyncio.run(run_repl(client, session_id=session))
```

**Step 3: Manual test**

Run: `shipagent interact --standalone`
Expected: Shows "ShipAgent v3.0 — Interactive Mode" prompt. Type a message and see agent response (requires ANTHROPIC_API_KEY).

**Step 4: Commit**

```bash
git add src/cli/repl.py src/cli/main.py
git commit -m "feat(cli): add conversational REPL with Rich rendering"
```

---

## Task 12: Watchdog Hot-Folder Service

**Files:**
- Create: `src/cli/watchdog_service.py`
- Create: `tests/cli/test_watchdog_service.py`
- Modify: `src/api/main.py` (lifespan integration)

**Step 1: Write the failing tests**

```python
# tests/cli/test_watchdog_service.py
"""Tests for the HotFolderService watchdog."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from src.cli.config import WatchFolderConfig
from src.cli.watchdog_service import (
    HotFolderService,
    _ensure_subdirs,
    _get_file_extension,
    _should_process_file,
)


class TestHelpers:
    """Tests for watchdog helper functions."""

    def test_ensure_subdirs_creates_dirs(self, tmp_path):
        """Creates .processing, processed, and failed subdirectories."""
        _ensure_subdirs(str(tmp_path))
        assert (tmp_path / ".processing").is_dir()
        assert (tmp_path / "processed").is_dir()
        assert (tmp_path / "failed").is_dir()

    def test_get_file_extension(self):
        """Returns lowercase file extension."""
        assert _get_file_extension("orders.CSV") == ".csv"
        assert _get_file_extension("data.xlsx") == ".xlsx"
        assert _get_file_extension("readme.txt") == ".txt"

    def test_should_process_file_csv(self):
        """CSV files in allowed types are processable."""
        config = WatchFolderConfig(
            path="./inbox", command="Ship all", file_types=[".csv"]
        )
        assert _should_process_file("orders.csv", config) is True
        assert _should_process_file("orders.xlsx", config) is False

    def test_should_process_file_ignores_hidden(self):
        """Hidden files (dotfiles) are never processed."""
        config = WatchFolderConfig(
            path="./inbox", command="Ship all", file_types=[".csv"]
        )
        assert _should_process_file(".orders.csv", config) is False

    def test_should_process_file_ignores_temp(self):
        """Temp files (ending in ~) are never processed."""
        config = WatchFolderConfig(
            path="./inbox", command="Ship all", file_types=[".csv"]
        )
        assert _should_process_file("orders.csv~", config) is False


class TestHotFolderService:
    """Tests for the HotFolderService lifecycle."""

    def test_init_creates_subdirs(self, tmp_path):
        """Service initialization creates subdirectories."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        service = HotFolderService(configs=[config])
        assert (inbox / ".processing").is_dir()
        assert (inbox / "processed").is_dir()
        assert (inbox / "failed").is_dir()

    def test_startup_scan_finds_existing_files(self, tmp_path):
        """Startup scan detects files dropped while daemon was down."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "backlog.csv").write_text("col1,col2\na,b")
        config = WatchFolderConfig(path=str(inbox), command="Ship all")
        service = HotFolderService(configs=[config])
        backlog = service.scan_existing_files()
        assert len(backlog) == 1
        assert backlog[0].name == "backlog.csv"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_watchdog_service.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/cli/watchdog_service.py
"""HotFolderService — filesystem watcher for zero-touch automation.

Monitors configured directories for new CSV/Excel files.
When a file lands, it is debounced, claimed, imported, and
processed through the agent with auto-confirm rules.

Runs inside the daemon process using the watchdog library.
Thread events are bridged to the async loop via call_soon_threadsafe.
"""

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.cli.config import WatchFolderConfig

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 2.0


def _ensure_subdirs(folder_path: str) -> None:
    """Create .processing, processed, and failed subdirectories.

    Args:
        folder_path: The watch folder root path.
    """
    root = Path(folder_path)
    for subdir in [".processing", "processed", "failed"]:
        (root / subdir).mkdir(parents=True, exist_ok=True)


def _get_file_extension(filename: str) -> str:
    """Get lowercase file extension from filename.

    Args:
        filename: The filename to extract extension from.

    Returns:
        Lowercase extension including dot (e.g., ".csv").
    """
    return Path(filename).suffix.lower()


def _should_process_file(filename: str, config: WatchFolderConfig) -> bool:
    """Check if a file should be processed based on config rules.

    Args:
        filename: The filename to check.
        config: The watch folder configuration.

    Returns:
        True if the file matches the configured file types and isn't hidden/temp.
    """
    # Ignore hidden files
    if filename.startswith("."):
        return False
    # Ignore temp files
    if filename.endswith("~"):
        return False
    # Check extension
    ext = _get_file_extension(filename)
    return ext in config.file_types


class _DebouncingHandler(FileSystemEventHandler):
    """Filesystem event handler with debouncing.

    Waits DEBOUNCE_SECONDS after the last event for a file before
    triggering processing. This handles partial uploads and large files.
    """

    def __init__(
        self,
        config: WatchFolderConfig,
        loop: asyncio.AbstractEventLoop,
        callback: Any,
    ):
        """Initialize handler with config, event loop, and async callback.

        Args:
            config: Watch folder configuration.
            loop: The asyncio event loop to bridge events to.
            callback: Async function(file_path, config) called after debounce.
        """
        self._config = config
        self._loop = loop
        self._callback = callback
        self._pending: dict[str, float] = {}  # path → last_event_time
        self._timers: dict[str, asyncio.TimerHandle] = {}

    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            self._debounce(event.src_path)

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            self._debounce(event.src_path)

    def _debounce(self, file_path: str) -> None:
        """Debounce file events — wait for writes to settle.

        Args:
            file_path: Path of the file that triggered the event.
        """
        filename = Path(file_path).name
        if not _should_process_file(filename, self._config):
            return

        self._pending[file_path] = time.time()

        # Cancel existing timer
        if file_path in self._timers:
            self._timers[file_path].cancel()

        # Schedule new timer on the async loop
        self._timers[file_path] = self._loop.call_later(
            DEBOUNCE_SECONDS,
            lambda fp=file_path: self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._fire(fp))
            ),
        )

    async def _fire(self, file_path: str) -> None:
        """Fire the callback after debounce period.

        Args:
            file_path: Path of the file to process.
        """
        self._pending.pop(file_path, None)
        self._timers.pop(file_path, None)
        try:
            await self._callback(file_path, self._config)
        except Exception:
            logger.exception("Error processing file %s", file_path)


class HotFolderService:
    """Watches configured directories and processes incoming files.

    Runs inside the daemon process. Uses the watchdog library for
    filesystem monitoring with thread→async bridging.
    """

    def __init__(self, configs: list[WatchFolderConfig]):
        """Initialize the hot folder service.

        Args:
            configs: List of watch folder configurations.
        """
        self._configs = configs
        self._observer: Observer | None = None
        self._locks: dict[str, asyncio.Lock] = {}

        # Create subdirectories for each watch folder
        for config in configs:
            _ensure_subdirs(config.path)
            self._locks[config.path] = asyncio.Lock()

    def scan_existing_files(self) -> list[Path]:
        """Scan watch folders for files dropped while daemon was down.

        Returns:
            List of file paths that need processing.
        """
        backlog = []
        for config in self._configs:
            root = Path(config.path)
            if not root.exists():
                continue
            for entry in root.iterdir():
                if entry.is_file() and _should_process_file(entry.name, config):
                    backlog.append(entry)
        return backlog

    async def start(self, process_callback) -> None:
        """Start watching all configured directories.

        Args:
            process_callback: Async function(file_path, config) to handle files.
        """
        loop = asyncio.get_running_loop()
        self._observer = Observer()

        for config in self._configs:
            folder_path = Path(config.path)
            if not folder_path.exists():
                logger.warning("Watch folder does not exist: %s", config.path)
                continue

            handler = _DebouncingHandler(config, loop, process_callback)
            self._observer.schedule(handler, str(folder_path), recursive=False)
            logger.info("Watching: %s → \"%s\"", config.path, config.command)

        self._observer.start()
        logger.info("HotFolderService started (%d folders)", len(self._configs))

    async def stop(self) -> None:
        """Stop the filesystem observer."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("HotFolderService stopped")

    def claim_file(self, file_path: str) -> Path | None:
        """Move a file to .processing/ to claim it.

        Args:
            file_path: Path to the file to claim.

        Returns:
            New path in .processing/, or None if file doesn't exist.
        """
        src = Path(file_path)
        if not src.exists():
            return None
        parent = src.parent
        dest = parent / ".processing" / src.name
        shutil.move(str(src), str(dest))
        return dest

    def complete_file(self, processing_path: Path) -> None:
        """Move a processed file to processed/ directory.

        Args:
            processing_path: Path in .processing/ to move.
        """
        dest = processing_path.parent.parent / "processed" / processing_path.name
        shutil.move(str(processing_path), str(dest))

    def fail_file(self, processing_path: Path, error: dict) -> None:
        """Move a failed file to failed/ with error sidecar.

        Args:
            processing_path: Path in .processing/ to move.
            error: Error details to write to .error sidecar file.
        """
        failed_dir = processing_path.parent.parent / "failed"
        dest = failed_dir / processing_path.name
        shutil.move(str(processing_path), str(dest))

        # Write error sidecar
        error_file = failed_dir / f"{processing_path.name}.error"
        error_file.write_text(json.dumps(error, indent=2))
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_watchdog_service.py -v`
Expected: All tests PASS.

**Step 5: Integrate into daemon lifespan**

Modify `src/api/main.py` startup/shutdown to optionally start the watchdog:

```python
# In startup_event(), after init_db():
    # Start watchdog if configured
    from src.cli.config import load_config
    config = load_config()
    if config and config.watch_folders:
        from src.cli.watchdog_service import HotFolderService
        global _watchdog_service
        _watchdog_service = HotFolderService(configs=config.watch_folders)
        # Process backlog from while daemon was down
        backlog = _watchdog_service.scan_existing_files()
        if backlog:
            logger.info("Found %d backlog files to process", len(backlog))
        # Start watching (requires running event loop — schedule as task)
        import asyncio
        asyncio.get_event_loop().create_task(_start_watchdog())

# In shutdown_event(), before shutdown_gateways():
    if _watchdog_service:
        await _watchdog_service.stop()
```

**Step 6: Commit**

```bash
git add src/cli/watchdog_service.py tests/cli/test_watchdog_service.py src/api/main.py
git commit -m "feat(cli): add HotFolderService watchdog with debouncing and file lifecycle"
```

---

## Task 13: Integration Testing & Polish

**Files:**
- Create: `tests/cli/test_integration.py`

**Step 1: Write integration tests**

```python
# tests/cli/test_integration.py
"""Integration tests for the CLI — end-to-end command execution."""

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


class TestCLICommands:
    """Tests for CLI command invocation."""

    def test_version(self):
        """Version command prints version string."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "ShipAgent" in result.stdout
        assert "v3.0" in result.stdout

    def test_help(self):
        """Help shows available commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "daemon" in result.stdout
        assert "job" in result.stdout
        assert "submit" in result.stdout
        assert "interact" in result.stdout

    def test_config_validate_no_file(self):
        """Config validate fails when no config file exists."""
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 1

    def test_config_validate_with_file(self, tmp_path):
        """Config validate succeeds with valid YAML."""
        config_file = tmp_path / "shipagent.yaml"
        config_file.write_text("daemon:\n  port: 9000\n")
        result = runner.invoke(app, ["config", "validate", "--config", str(config_file)])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_daemon_status_not_running(self):
        """Daemon status reports not running when no PID file."""
        result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0
        assert "not running" in result.stdout.lower()

    def test_submit_missing_file(self):
        """Submit fails with clear error for missing file."""
        result = runner.invoke(app, ["submit", "/nonexistent/file.csv"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_job_list_standalone(self):
        """Job list in standalone mode returns empty list."""
        result = runner.invoke(app, ["--standalone", "job", "list"])
        assert result.exit_code == 0
```

**Step 2: Run tests**

Run: `pytest tests/cli/test_integration.py -v`
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add tests/cli/test_integration.py
git commit -m "test(cli): add integration tests for CLI command invocation"
```

---

## Task 14: Update CLAUDE.md & Final Commit

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add CLI section to CLAUDE.md**

Add the CLI to the architecture section, command surface, and component table. Key additions:

- New component in the System Components table
- New `src/cli/` section in Source Structure
- `shipagent` commands in Common Commands
- CLI dependencies in Technology Stack
- Update version to 3.0.0

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with headless automation CLI architecture"
```

---

## Summary

| Task | Component | New Files | Tests |
|------|-----------|-----------|-------|
| 1 | Dependencies & entry point | — | — |
| 2 | Config models & YAML loader | `config.py` | `test_config.py` |
| 3 | Protocol & data models | `protocol.py` | `test_protocol.py` |
| 4 | Output formatter | `output.py` | `test_output.py` |
| 5 | Auto-confirm engine | `auto_confirm.py` | `test_auto_confirm.py` |
| 6 | Factory & CLI skeleton | `factory.py`, `main.py`, `http_client.py`, `runner.py` | `test_factory.py` |
| 7 | Daemon management | `daemon.py` | `test_daemon.py` |
| 8 | HTTP client implementation | `http_client.py` (full) | `test_http_client.py` |
| 9 | Health endpoint enhancement | `main.py` (modify) | existing |
| 10 | InProcessRunner implementation | `runner.py` (full) | `test_runner.py` |
| 11 | Conversational REPL | `repl.py` | manual |
| 12 | Watchdog hot-folders | `watchdog_service.py` | `test_watchdog_service.py` |
| 13 | Integration tests | — | `test_integration.py` |
| 14 | CLAUDE.md update | — | — |

**Total new files:** 12 source + 8 test = 20 files
**Estimated commits:** 14
