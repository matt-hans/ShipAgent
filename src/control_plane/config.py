from enum import StrEnum

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
