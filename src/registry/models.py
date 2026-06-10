from enum import StrEnum
from typing import Any, Literal

from jsonschema import SchemaError, validators
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ToolVisibility(StrEnum):
    public = "public"
    private = "private"
    desktop_only = "desktop_only"
    dev_only = "dev_only"


class Availability(StrEnum):
    hosted = "hosted"
    local = "local"


class SideEffectClass(StrEnum):
    read = "read"
    estimate = "estimate"
    write = "write"
    purchase = "purchase"
    external_mutation = "external_mutation"
    destructive = "destructive"


class ProviderExport(StrEnum):
    openai = "openai"
    anthropic = "anthropic"
    microsoft = "microsoft"
    gemini = "gemini"
    generic_mcp = "generic_mcp"
    openai_apps_public = "openai_apps_public"
    claude_remote_mcp_public = "claude_remote_mcp_public"


class AuditLevel(StrEnum):
    none = "none"
    basic = "basic"
    full = "full"
    regulated = "regulated"


class ResultSensitivity(StrEnum):
    public = "public"
    business = "business"
    confidential = "confidential"
    credential_redacted = "credential_redacted"


class ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=3)
    description: str = Field(min_length=20)
    contract_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    visibility: ToolVisibility
    availability: list[Availability]
    implementation_status: Literal["planned", "implemented"]
    hosted_readiness: Literal["not_ready", "ready"]
    tenant_safe: bool
    provider_export_enabled: bool
    side_effect: SideEffectClass
    requires_confirmation: bool
    auth_scopes: list[str]
    provider_exports: list[ProviderExport]
    audit_level: AuditLevel
    result_sensitivity: ResultSensitivity
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    confirmation_policy: str | None = None
    ui_resource: str | None = None
    notes: str = ""
    prepare_tool: str | None = None
    execution_target_required: bool = False
    result_profile: Literal[
        "aggregate", "provider_ingress_echo", "artifact_action"
    ] = "aggregate"
    max_sync_seconds: int = Field(default=30, ge=1, le=300)
    max_result_bytes: int = Field(default=65536, ge=1024)
    minimum_capabilities: dict[str, str] = Field(default_factory=dict)
    rate_limit_class: str = "default"

    @field_validator("availability", "provider_exports")
    @classmethod
    def _non_empty_unique_list(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("must not be empty")
        seen = set()
        duplicates = []
        for item in value:
            if item in seen:
                duplicates.append(item.value)
            else:
                seen.add(item)
        if duplicates:
            raise ValueError(f"must not contain duplicates: {duplicates}")
        return value

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _schema_must_be_valid_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("canonical schemas must be JSON objects")
        validator = validators.validator_for(value)
        try:
            validator.check_schema(value)
        except SchemaError as exc:
            raise ValueError("canonical schemas must be valid JSON Schema") from exc
        return value

    @model_validator(mode="after")
    def _validate_public_export(self) -> "ToolContract":
        if self.visibility == ToolVisibility.public and self.provider_export_enabled:
            if self.implementation_status != "implemented":
                raise ValueError("public exported tools must be implemented")
            if not self.tenant_safe:
                raise ValueError("public exported tools must be tenant_safe")
            if self.hosted_readiness != "ready":
                raise ValueError("public exported tools must be hosted-ready")
        if (
            self.side_effect
            in {
                SideEffectClass.write,
                SideEffectClass.purchase,
                SideEffectClass.external_mutation,
                SideEffectClass.destructive,
            }
            and not self.requires_confirmation
        ):
            raise ValueError("side-effecting tools require confirmation")
        if self.requires_confirmation and not self.prepare_tool:
            raise ValueError("confirmed tools must declare prepare_tool")
        if (
            self.requires_confirmation
            and self.visibility == ToolVisibility.public
            and self.prepare_tool is not None
            and not self.prepare_tool.startswith("prepare_")
        ):
            raise ValueError(
                "public confirmed tools must declare prepare_tool with prepare_* name"
            )
        if self.prepare_tool == self.name:
            raise ValueError("prepare_tool must be distinct from tool name")
        return self


class RegistrySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    tools: list[ToolContract]

    @model_validator(mode="after")
    def _unique_tool_names(self) -> "RegistrySchema":
        seen = set()
        duplicates = []
        for tool in self.tools:
            if tool.name in seen:
                duplicates.append(tool.name)
            else:
                seen.add(tool.name)
        if duplicates:
            raise ValueError(f"duplicate tool names: {duplicates}")
        return self
