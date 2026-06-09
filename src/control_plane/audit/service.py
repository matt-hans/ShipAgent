import json
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.models import ControlPlaneAuditEvent


class ControlPlaneAuditService:
    """Redacted audit recorder for relay-control operations."""

    _ALLOWED_IDS = {
        "account_id",
        "provider_connection_id",
        "device_id",
        "job_id",
        "correlation_id",
        "preview_id",
        "confirmation_id",
    }
    _ALLOWED_HASHES = {"actor_id_hash", "request_hash", "response_hash", "preview_hash"}
    _ALLOWED_COUNTS = {"count", "row_count", "attempt_count", "error_count"}
    _ALLOWED_SAFE_FIELDS = {
        "status",
        "policy_version",
        "api_version",
        "notes",
    }
    _ALLOWED_VERSIONS = {"schema_version", "contract_version"}
    _ALLOWED_ERROR_CATEGORIES = {
        "validation",
        "authorization",
        "provider",
        "policy",
        "rate_limit",
    }

    @classmethod
    async def record(
        cls,
        *,
        session: AsyncSession,
        event_type: str,
        actor_id_hash: str,
        account_id: str | None = None,
        provider_connection_id: str | None = None,
        device_id: str | None = None,
        ids: dict[str, str] | None = None,
        hashes: dict[str, str] | None = None,
        counts: dict[str, int] | None = None,
        safe_fields: dict[str, Any] | None = None,
        versions: dict[str, str] | None = None,
        error_category: str | None = None,
    ) -> ControlPlaneAuditEvent:
        payload = {
            "ids": cls._validate_map(ids or {}, cls._ALLOWED_IDS),
            "hashes": cls._validate_map(hashes or {}, cls._ALLOWED_HASHES),
            "counts": cls._validate_counts(counts or {}),
            "safe_fields": cls._validate_map(safe_fields or {}, cls._ALLOWED_SAFE_FIELDS),
            "versions": cls._validate_map(versions or {}, cls._ALLOWED_VERSIONS),
        }

        if error_category is not None:
            if error_category not in cls._ALLOWED_ERROR_CATEGORIES:
                raise ValueError("unsupported error category")
            payload["error_category"] = error_category

        # Redact known-sensitive raw payloads at the boundaries above by never
        # accepting them into the payload schema.
        event = ControlPlaneAuditEvent(
            event_type=event_type,
            account_id=account_id,
            provider_connection_id=provider_connection_id,
            device_id=device_id,
            actor_id_hash=actor_id_hash,
            details_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
        session.add(event)
        await session.flush()
        return event

    @classmethod
    async def cleanup_for_account(cls, session: AsyncSession, account_id: str) -> int:
        result = await session.execute(
            delete(ControlPlaneAuditEvent).where(
                ControlPlaneAuditEvent.account_id == account_id
            )
        )
        return result.rowcount or 0

    @classmethod
    def _validate_map(cls, values: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        for key in values:
            if key not in allowed:
                raise ValueError(f"disallowed key: {key}")
        return dict(values)

    @classmethod
    def _validate_counts(cls, values: dict[str, int]) -> dict[str, int]:
        for key, value in values.items():
            if key not in cls._ALLOWED_COUNTS:
                raise ValueError(f"disallowed key: {key}")
            if not isinstance(value, int):
                raise TypeError("counts must be integers")
        return dict(values)

