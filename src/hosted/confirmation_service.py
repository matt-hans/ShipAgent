import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.db.models import ConfirmationRecord, generate_uuid

_URLSAFE_BASE64_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)
DEFAULT_TOKEN_TTL_SECONDS = 15 * 60


def _parse_utc_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc_datetime(value: datetime | str) -> str:
    if isinstance(value, str):
        parsed = _parse_utc_datetime(value)
        if parsed is None:
            raise ValueError("expires_at must be an ISO8601 timestamp")
        return parsed.isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class ConfirmationService:
    """Issues and validates signed confirmation tokens."""

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("confirmation secret must be at least 32 characters")
        self._secret = secret.encode()

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def issue_token(
        self,
        tenant_id: str,
        confirmation_id: str,
        operation: str,
        expires_at: datetime | str | None = None,
    ) -> str:
        if expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(seconds=DEFAULT_TOKEN_TTL_SECONDS)
        expires_at_text = _format_utc_datetime(expires_at)
        payload = {
            "tenant_id": tenant_id,
            "confirmation_id": confirmation_id,
            "operation": operation,
            "expires_at": expires_at_text,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sig = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        envelope = {"payload": payload, "sig": sig}
        return base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()

    def issue_persisted_token(
        self,
        db: Session,
        *,
        tenant_id: str,
        operation: str,
        preview_id: str,
        idempotency_key: str,
        expires_at: datetime | str | None = None,
        confirmation_id: str | None = None,
    ) -> str:
        confirmation_id = confirmation_id or generate_uuid()
        if expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(seconds=DEFAULT_TOKEN_TTL_SECONDS)
        expires_at_text = _format_utc_datetime(expires_at)
        token = self.issue_token(
            tenant_id=tenant_id,
            confirmation_id=confirmation_id,
            operation=operation,
            expires_at=expires_at_text,
        )
        db.add(
            ConfirmationRecord(
                id=confirmation_id,
                tenant_id=tenant_id,
                operation=operation,
                preview_id=preview_id,
                idempotency_key=idempotency_key,
                token_hash=self.token_hash(token),
                expires_at=expires_at_text,
            )
        )
        db.flush()
        return token

    def validate_token(
        self, token: str, tenant_id: str, operation: str
    ) -> dict[str, Any] | None:
        try:
            token_bytes = token.encode("ascii")
            if any(char not in _URLSAFE_BASE64_CHARS for char in token):
                return None
            envelope = json.loads(
                base64.b64decode(token_bytes, altchars=b"-_", validate=True)
            )
        except Exception:
            return None
        if not isinstance(envelope, dict):
            return None
        payload = envelope.get("payload")
        sig = envelope.get("sig")
        if not isinstance(payload, dict) or not isinstance(sig, str):
            return None
        if len(sig) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sig):
            return None
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload_tenant_id = payload.get("tenant_id")
        payload_confirmation_id = payload.get("confirmation_id")
        payload_operation = payload.get("operation")
        payload_expires_at = payload.get("expires_at")
        if not all(
            isinstance(value, str)
            for value in (
                payload_tenant_id,
                payload_confirmation_id,
                payload_operation,
                payload_expires_at,
            )
        ):
            return None
        if payload_tenant_id != tenant_id or payload_operation != operation:
            return None
        expires_at = _parse_utc_datetime(payload_expires_at)
        if expires_at is None or expires_at <= datetime.now(UTC):
            return None
        return payload

    def validate_and_consume_token(
        self,
        db: Session,
        token: str,
        tenant_id: str,
        operation: str,
    ) -> dict[str, Any] | None:
        payload = self.validate_token(
            token=token,
            tenant_id=tenant_id,
            operation=operation,
        )
        if payload is None:
            return None

        now = datetime.now(UTC).isoformat()
        result = db.execute(
            update(ConfirmationRecord)
            .where(
                ConfirmationRecord.id == payload["confirmation_id"],
                ConfirmationRecord.tenant_id == tenant_id,
                ConfirmationRecord.operation == operation,
                ConfirmationRecord.token_hash == self.token_hash(token),
                ConfirmationRecord.expires_at > now,
                ConfirmationRecord.used_at.is_(None),
            )
            .values(used_at=now)
        )
        if result.rowcount != 1:
            return None
        db.flush()
        return payload
