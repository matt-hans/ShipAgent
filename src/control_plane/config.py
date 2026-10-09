import re
from enum import StrEnum

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.control_plane.auth.oauth_contract import canonical_mcp_resource


class AuthMode(StrEnum):
    auth0 = "auth0"
    fake_local = "fake_local"


class Environment(StrEnum):
    local = "local"
    prototype = "prototype"
    beta = "beta"
    production = "production"


class ControlPlaneSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHIPAGENT_",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    auth_mode: AuthMode = AuthMode.auth0
    environment: Environment = Environment.local
    bind_host: str = "127.0.0.1"
    public_base_url: AnyHttpUrl | None = None
    database_url: str | None = None
    redis_url: str | None = None
    auth0_issuer: str = ""
    auth0_audience: str = ""
    relay_signing_secret: str = Field(default="", min_length=0)
    control_plane_schema: str = "shipagent_private"
    auth0_provider_clients: dict[str, str] = Field(
        default_factory=lambda: {
            "chatgpt-client": "chatgpt",
            "claude-client": "claude_ai",
            "desktop-client": "desktop",
            "operator-client": "operator",
        }
    )

    # Dormant unless the control-plane operator explicitly enables retention.
    audit_retention_days: int = Field(default=90, ge=30, le=365, strict=True)
    retention_background_tasks_enabled: bool = False

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _validate_public_url_before_normalization(cls, value):
        if value is not None:
            canonical_mcp_resource(str(value))
        return value

    @field_validator("audit_retention_days", mode="before")
    @classmethod
    def _parse_retention_days(cls, value):
        # BaseSettings receives environment values as strings even in strict mode.
        if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
            return int(value)
        return value
