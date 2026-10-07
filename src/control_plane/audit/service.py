import hashlib
import json
import re

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.control_plane.audit.models import ControlPlaneAuditEvent
from src.registry.identifiers import ShipAgentIdFamily, parse_shipagent_id


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
    _UUID_GRAMMAR = (
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}"
    )
    _UUID_PATTERN = re.compile(rf"^{_UUID_GRAMMAR}$")
    _INTERNAL_ID_PATTERNS = {
        "account_id": re.compile(r"^sa_account_[0-9a-f]{16,25}$"),
        "provider_connection_id": re.compile(r"^sa_connection_[0-9a-f]{16,22}$"),
        "artifact_id": re.compile(r"^sa_(?:artifact|document)_[0-9a-f]{32}$"),
    }
    _PROVIDER_ID_FAMILIES = {
        "job_id": (ShipAgentIdFamily.JOB,),
        "correlation_id": (ShipAgentIdFamily.CORRELATION,),
        "preview_id": (ShipAgentIdFamily.PREVIEW,),
        "confirmation_id": (ShipAgentIdFamily.CONFIRMATION,),
        "artifact_id": (
            ShipAgentIdFamily.LABEL,
            ShipAgentIdFamily.VALIDATION,
        ),
    }
    _SENSITIVE_ID_MARKER = re.compile(
        r"(?:^|[._:-])"
        r"(?:bearer|password|secret|token|sk(?:[._:-](?:live|test|proj))?)"
        r"(?:$|[._:-])",
        re.IGNORECASE,
    )
    _COMPACT_SENSITIVE_ID_MARKERS = frozenset(
        {
            "accesskey",
            "address",
            "apikey",
            "authorization",
            "bearer",
            "clientsecret",
            "credential",
            "customer",
            "email",
            "firstname",
            "fullname",
            "lastname",
            "name",
            "password",
            "phone",
            "recipient",
            "secret",
            "sklive",
            "skproj",
            "sktest",
            "street",
            "token",
        }
    )
    _ID_MAX_LENGTHS = {
        "account_id": 36,
        "provider_connection_id": 36,
        "device_id": 36,
        "job_id": 128,
        "correlation_id": 128,
        "preview_id": 128,
        "confirmation_id": 128,
        "artifact_id": 128,
    }
    _ALLOWED_HASHES = {"actor_id_hash", "request_hash", "response_hash", "preview_hash"}
    _ALLOWED_EXTERNAL_IDS = {
        "external_order_id",
        "provider_reference",
        "provider_subject",
        "tracking_number",
    }
    _EXTERNAL_ID_MAX_LENGTH = 512
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
        external_ids: dict[str, str] | None = None,
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
        persisted_hashes = cls._validate_hashes(hashes or {})
        persisted_hashes.update(cls._hash_external_ids(external_ids or {}))
        payload = {
            "ids": cls._validate_ids(ids or {}),
            "hashes": persisted_hashes,
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
        account_id = cls._validate_id_value(
            account_id,
            key="account_id",
            max_length=cls._ID_MAX_LENGTHS["account_id"],
        )
        # This public cleanup seam must not bypass the explicit hold guard.
        from src.control_plane.retention.legal_hold import (
            LegalHoldService,
            lock_account,
        )

        await lock_account(session, account_id, required=False)
        if await LegalHoldService.has_active_hold(
            session=session, account_id=account_id
        ):
            raise PermissionError("active legal hold")
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
    def _hash_external_ids(cls, values: dict[str, str]) -> dict[str, str]:
        persisted: dict[str, str] = {}
        for key, value in values.items():
            if key not in cls._ALLOWED_EXTERNAL_IDS:
                raise ValueError(f"disallowed external ID key: {key}")
            if (
                not isinstance(value, str)
                or not value
                or len(value) > cls._EXTERNAL_ID_MAX_LENGTH
                or any(
                    ord(character) < 32 or ord(character) == 127 for character in value
                )
            ):
                raise ValueError("external IDs must be bounded scalar values")
            persisted[f"{key}_hash"] = hashlib.sha256(value.encode()).hexdigest()
        return persisted

    @classmethod
    def _validate_ids(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if key not in cls._ID_MAX_LENGTHS:
                raise ValueError(f"disallowed key: {key}")
            cls._validate_id_value(
                value,
                key=key,
                max_length=cls._ID_MAX_LENGTHS[key],
            )
        return dict(values)

    @classmethod
    def _validate_id_value(cls, value: str, *, key: str, max_length: int) -> str:
        if (
            not isinstance(value, str)
            or len(value) > max_length
            or not cls._is_canonical_id(value, key)
            or cls._SENSITIVE_ID_MARKER.search(value)
            or cls._contains_compact_sensitive_id_marker(value)
        ):
            raise ValueError(f"{key} must be a bounded canonical {key}")
        return value

    @classmethod
    def _is_canonical_id(cls, value: str, key: str) -> bool:
        if cls._UUID_PATTERN.fullmatch(value):
            return True

        for family in cls._PROVIDER_ID_FAMILIES.get(key, ()):
            try:
                parse_shipagent_id(value, expected_family=family)
            except ValueError:
                continue
            return True

        internal_pattern = cls._INTERNAL_ID_PATTERNS.get(key)
        return bool(internal_pattern and internal_pattern.fullmatch(value))

    @classmethod
    def _contains_compact_sensitive_id_marker(cls, value: str) -> bool:
        compact = re.sub(r"[^a-z0-9]", "", value.lower())
        return any(marker in compact for marker in cls._COMPACT_SENSITIVE_ID_MARKERS)

    @classmethod
    def _validate_optional_id(cls, value: str | None, key: str) -> str | None:
        if value is None:
            return None
        return cls._validate_id_value(
            value,
            key=key,
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
