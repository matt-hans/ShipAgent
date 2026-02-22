"""Secret redaction utility for safe logging and error responses.

Provides centralized redaction to prevent credential leakage in logs,
error messages, and API error responses. Uses case-insensitive substring
matching for sensitive key detection. Handles nested dicts, lists of dicts,
and known container keys.
"""

import re

# Substring patterns matched case-insensitively against dict keys
_DEFAULT_SENSITIVE_PATTERNS = frozenset({
    "secret", "token", "authorization", "api_key", "password",
    "credential", "client_id", "client_secret", "access_token",
    "refresh_token",
})

# Keys whose entire value is redacted (regardless of content type)
_CONTAINER_KEYS = frozenset({"credentials", "headers"})

_REDACTED = "***REDACTED***"


def _is_sensitive_key(key: str, sensitive_patterns: frozenset[str]) -> bool:
    """Check if a key matches any sensitive pattern (case-insensitive substring).

    Args:
        key: Dict key to check.
        sensitive_patterns: Patterns to match against.

    Returns:
        True if the key matches any sensitive pattern.
    """
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in sensitive_patterns)


def redact_for_logging(
    obj: dict,
    sensitive_patterns: frozenset[str] = _DEFAULT_SENSITIVE_PATTERNS,
) -> dict:
    """Redact sensitive values from a dict for safe logging/error responses.

    Args:
        obj: Dict to redact (not mutated — returns a copy).
        sensitive_patterns: Substring patterns whose matching keys' values
            should be replaced. Matching is case-insensitive.

    Returns:
        New dict with sensitive values replaced by '***REDACTED***'.
        Handles nested dicts, lists of dicts, and container keys recursively.
    """
    result = {}
    for key, value in obj.items():
        key_lower = key.lower()
        if key_lower in _CONTAINER_KEYS:
            result[key] = _REDACTED
        elif _is_sensitive_key(key, sensitive_patterns):
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = redact_for_logging(value, sensitive_patterns)
        elif isinstance(value, list):
            result[key] = [
                redact_for_logging(item, sensitive_patterns) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


# Patterns for detecting sensitive values in free-text error messages.
# Handles: key=value, Authorization: Bearer <token>, "key": "value",
# key = "quoted value", and multi-token lines.
_SENSITIVE_KEYWORDS = (
    r"secret|token|password|api_key|client_id|client_secret|"
    r"access_token|refresh_token|authorization|credential"
)
_SENSITIVE_VALUE_PATTERNS = re.compile(
    r"(?i)"
    r"(?:"
    # Pattern 1: Authorization: Bearer <token>
    r"Authorization\s*:\s*Bearer\s+\S+"
    r"|"
    # Pattern 2: JSON-style "key": "value" or "key":"value"
    r'"(?:' + _SENSITIVE_KEYWORDS + r')"\s*:\s*"[^"]*"'
    r"|"
    # Pattern 3: key = "quoted value" or key="quoted value"
    r"(?:" + _SENSITIVE_KEYWORDS + r")\s*[=:]\s*\"[^\"]*\""
    r"|"
    # Pattern 4: key=value (unquoted, consumes until whitespace/end)
    r"(?:" + _SENSITIVE_KEYWORDS + r")\s*[=:]\s*\S+"
    r")",
)


def sanitize_error_message(msg: str | None, max_length: int = 2000) -> str | None:
    """Sanitize an error message for safe DB persistence.

    Redacts sensitive-looking key=value pairs and truncates to max_length.

    Args:
        msg: Error message to sanitize (None passes through).
        max_length: Maximum length of the sanitized message.

    Returns:
        Sanitized and truncated message, or None.
    """
    if msg is None:
        return None
    sanitized = _SENSITIVE_VALUE_PATTERNS.sub("***REDACTED***", msg)
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + "..."
    return sanitized
