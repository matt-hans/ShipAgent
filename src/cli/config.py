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
from typing import Any, Literal

import yaml
from pydantic import BaseModel, model_validator

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
    """Rules for automatic job confirmation in headless mode.

    NOTE on address rules: In watchdog mode, address validation state is
    not persisted on JobRow after preview. The watchdog reports addresses
    as unverified (all_addresses_valid=False, has_address_warnings=True)
    so these rules will BLOCK auto-confirm by default. Operators who
    want headless auto-confirm should explicitly set
    require_valid_addresses=false in their config, acknowledging that
    address validation is handled at preview time by the agent, not
    re-checked at auto-confirm time.
    """

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


class DefaultDataSourceConfig(BaseModel):
    """Default data source loaded on daemon/CLI startup.

    At most one of path, saved_source, or platform should be set.
    """

    path: str | None = None
    saved_source: str | None = None
    platform: Literal["shopify"] | None = None

    @model_validator(mode="after")
    def at_most_one_source(self) -> "DefaultDataSourceConfig":
        """Ensure at most one source field is populated."""
        set_fields = sum(
            1 for v in (self.path, self.saved_source, self.platform)
            if v is not None
        )
        if set_fields > 1:
            raise ValueError(
                "Only one of path, saved_source, or platform may be set"
            )
        return self


class ShipAgentConfig(BaseModel):
    """Top-level configuration for the ShipAgent headless automation suite."""

    daemon: DaemonConfig = DaemonConfig()
    auto_confirm: AutoConfirmRules = AutoConfirmRules()
    watch_folders: list[WatchFolderConfig] = []
    shipper: ShipperConfig | None = None
    ups: UPSConfig | None = None
    default_data_source: DefaultDataSourceConfig | None = None


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

    Matches section names by longest prefix so multi-word section names
    like ``auto_confirm`` and ``watch_folders`` are handled correctly.
    For example, ``SHIPAGENT_AUTO_CONFIRM_ENABLED`` maps to section
    ``auto_confirm``, field ``enabled``.

    Args:
        data: Parsed YAML config dict.

    Returns:
        Config dict with env var overrides applied.
    """
    prefix = "SHIPAGENT_"
    # Known sections sorted longest-first so greedy prefix match works.
    known_sections = sorted(
        ShipAgentConfig.model_fields.keys(), key=len, reverse=True
    )
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix):].lower()  # e.g. "auto_confirm_enabled"
        matched_section = None
        matched_field = None
        for section in known_sections:
            section_prefix = section + "_"
            if suffix.startswith(section_prefix):
                matched_section = section
                matched_field = suffix[len(section_prefix):]
                break
        if matched_section is None or not matched_field:
            continue
        if matched_section not in data:
            data[matched_section] = {}
        if isinstance(data[matched_section], dict):
            # Coerce to int, bool, or keep as string
            try:
                data[matched_section][matched_field] = int(value)
            except ValueError:
                if value.lower() in ("true", "false"):
                    data[matched_section][matched_field] = value.lower() == "true"
                else:
                    data[matched_section][matched_field] = value
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
