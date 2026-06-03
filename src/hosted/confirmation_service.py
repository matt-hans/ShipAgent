import base64
import hashlib
import hmac
import json
from typing import Any

_URLSAFE_BASE64_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)


class ConfirmationService:
    """Issues and validates signed confirmation tokens."""

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("confirmation secret must be at least 32 characters")
        self._secret = secret.encode()

    def issue_token(self, tenant_id: str, confirmation_id: str, operation: str) -> str:
        payload = {
            "tenant_id": tenant_id,
            "confirmation_id": confirmation_id,
            "operation": operation,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sig = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        envelope = {"payload": payload, "sig": sig}
        return base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()

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
        if not all(
            isinstance(value, str)
            for value in (
                payload_tenant_id,
                payload_confirmation_id,
                payload_operation,
            )
        ):
            return None
        if payload_tenant_id != tenant_id or payload_operation != operation:
            return None
        return payload
