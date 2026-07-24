import json
import re

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.models import ControlPlaneAuditEvent


class ControlPlaneAuditService:
    """Redacted audit recorder for relay-control operations."""

    _VERSION_MAX_LENGTH = 64
    _SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
    _EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:[.:][a-z][a-z0-9_]*)*$")
    _VERSION_PATTERN = re.compile(
        r"^v?\d+(?:\.\d+){0,2}"
        r"(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?"
        r"(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$"
    )
    _OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    _SENSITIVE_ID_MARKER = re.compile(
        r"(?:^|[._:-])"
        r"(?:bearer|password|secret|token|sk(?:[._:-](?:live|test|proj))?)"
        r"(?:$|[._:-])",
        re.IGNORECASE,
    )
    _ID_MAX_LENGTHS = {
        "account_id": 36,
        "provider_connection_id": 36,
        "device_id": 36,
        "job_id": 36,
        "correlation_id": 128,
        "preview_id": 128,
        "confirmation_id": 128,
    }
    _ALLOWED_HASHES = {"actor_id_hash", "request_hash", "response_hash", "preview_hash"}
    _ALLOWED_COUNTS = {"count", "row_count", "attempt_count", "error_count"}
    _REASON_CODES = {
        "authorization_denied",
        "confirmation_expired",
        "confirmation_missing",
        "confirmation_rejected",
        "policy_blocked",
        "provider_error",
        "provider_unavailable",
        "rate_limited",
        "retry_exhausted",
        "user_cancelled",
        "user_confirmed",
        "validation_failed",
    }
    _STATUS_CODES = {
        "accepted",
        "active",
        "blocked",
        "cancelled",
        "completed",
        "confirmed",
        "expired",
        "failed",
        "inactive",
        "invalid",
        "ok",
        "pending",
        "prepared",
        "queued",
        "ready",
        "rejected",
        "retrying",
        "revoked",
        "running",
        "succeeded",
        "suspended",
        "unavailable",
        "valid",
    }
    _ALLOWED_VERSIONS = {
        "api_version",
        "contract_version",
        "policy_version",
        "schema_version",
    }
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
        safe_fields: dict[str, str] | None = None,
        versions: dict[str, str] | None = None,
        error_category: str | None = None,
    ) -> ControlPlaneAuditEvent:
        event_type = cls._validate_event_type(event_type)
        actor_id_hash = cls._validate_hash_value(actor_id_hash)
        account_id = cls._validate_optional_id(account_id, "account_id")
        provider_connection_id = cls._validate_optional_id(
            provider_connection_id,
            "provider_connection_id",
        )
        device_id = cls._validate_optional_id(device_id, "device_id")
        payload = {
            "ids": cls._validate_ids(ids or {}),
            "hashes": cls._validate_hashes(hashes or {}),
            "counts": cls._validate_counts(counts or {}),
            "safe_fields": cls._validate_safe_fields(safe_fields or {}),
            "versions": cls._validate_versions(versions or {}),
        }

        if error_category is not None:
            if (
                not isinstance(error_category, str)
                or error_category not in cls._ALLOWED_ERROR_CATEGORIES
            ):
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
    def _validate_counts(cls, values: dict[str, int]) -> dict[str, int]:
        for key, value in values.items():
            if key not in cls._ALLOWED_COUNTS:
                raise ValueError(f"disallowed key: {key}")
            if type(value) is not int:
                raise TypeError("counts must be integers")
            if not 0 <= value < 2**63:
                raise ValueError("counts must be non-negative signed 64-bit integers")
        return dict(values)

    @classmethod
    def _validate_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if key not in cls._ALLOWED_HASHES:
                raise ValueError(f"disallowed key: {key}")
            cls._validate_hash_value(value)
        return dict(values)

    @classmethod
    def _validate_hash_value(cls, value: str) -> str:
        if not isinstance(value, str) or not cls._SHA256_PATTERN.fullmatch(value):
            raise ValueError("hash values must be lowercase SHA-256 digests")
        return value

    @classmethod
    def _validate_ids(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if key not in cls._ID_MAX_LENGTHS:
                raise ValueError(f"disallowed key: {key}")
            cls._validate_id_value(
                value,
                max_length=cls._ID_MAX_LENGTHS[key],
            )
        return dict(values)

    @classmethod
    def _validate_id_value(cls, value: str, *, max_length: int) -> str:
        if (
            not isinstance(value, str)
            or len(value) > max_length
            or not cls._OPAQUE_ID_PATTERN.fullmatch(value)
            or cls._SENSITIVE_ID_MARKER.search(value)
        ):
            raise ValueError("ID values must be bounded opaque IDs")
        return value

    @classmethod
    def _validate_optional_id(cls, value: str | None, key: str) -> str | None:
        if value is None:
            return None
        return cls._validate_id_value(
            value,
            max_length=cls._ID_MAX_LENGTHS[key],
        )

    @classmethod
    def _validate_safe_fields(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if not isinstance(value, str):
                raise TypeError("sensitive payload values must be scalar string codes")
            if key == "status":
                if value not in cls._STATUS_CODES:
                    raise ValueError("unsupported audit status code")
            elif key == "reason_code":
                if value not in cls._REASON_CODES:
                    raise ValueError("unsupported audit reason code")
            else:
                raise ValueError(f"disallowed key: {key}")
        return dict(values)

    @classmethod
    def _validate_versions(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if key not in cls._ALLOWED_VERSIONS:
                raise ValueError(f"disallowed version key: {key}")
            if isinstance(value, str) and len(value) > cls._VERSION_MAX_LENGTH:
                raise ValueError(
                    f"version values must be at most {cls._VERSION_MAX_LENGTH} characters"
                )
            if not isinstance(value, str) or not cls._VERSION_PATTERN.fullmatch(value):
                raise ValueError("version values must use a bounded version code")
        return dict(values)

    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) > 96
            or not cls._EVENT_TYPE_PATTERN.fullmatch(value)
            or cls._SENSITIVE_ID_MARKER.search(value)
        ):
            raise ValueError("event type must be a bounded event type code")
        return value
