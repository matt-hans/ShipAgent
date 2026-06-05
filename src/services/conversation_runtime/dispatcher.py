from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from typing import Any

from src.services.conversation_runtime.models import (
    ProviderToolCall,
    ProviderToolResult,
)
from src.services.conversation_runtime.policy import RuntimePolicyEngine
from src.utils.redaction import sanitize_error_message

logger = logging.getLogger(__name__)


def _normalize_model_key(key: Any) -> str:
    return "".join(char.lower() for char in str(key) if char.isalnum())


_DROP_MODEL_KEYS = {
    "rows",
    "sample_rows",
    "preview_rows",
    "raw_rows",
    "labels",
    "label",
    "label_url",
    "label_download_url",
    "label_data",
    "credentials",
    "request_body",
    "response_body",
    "raw_response",
    "file_content_base64",
    "document_bytes",
    "document_url",
    "document_download_url",
}

_DROP_MODEL_KEY_VARIANTS = {
    *_DROP_MODEL_KEYS,
    "credential",
    "sample",
    "samples",
    "label_urls",
    "label_download_urls",
    "label_datas",
    "document_urls",
    "document_download_urls",
    "raw_responses",
}

_DROP_MODEL_NORMALIZED_KEYS = {
    _normalize_model_key(key) for key in _DROP_MODEL_KEY_VARIANTS
}

_UNSAFE_NORMALIZED_KEY_FRAGMENTS = {
    "address",
    "contact",
    "credential",
    "customer",
    "document",
    "email",
    "filecontent",
    "label",
    "name",
    "order",
    "payload",
    "phone",
    "previewrow",
    "raw",
    "rawpayload",
    "rawresponse",
    "rawrow",
    "request",
    "requestbody",
    "requestpayload",
    "response",
    "responsebody",
    "responsepayload",
    "sample",
    "samplerow",
    "secret",
}

_SAFE_SCALAR_KEYS = {
    "action",
    "artifact_id",
    "column_count",
    "confirmation_token",
    "count",
    "fetch_id",
    "job_id",
    "ok",
    "returned_count",
    "row_count",
    "safe_id",
    "source_type",
    "status",
    "success",
    "total_count",
}

_SAFE_NORMALIZED_SCALAR_KEYS = {
    _normalize_model_key(key) for key in _SAFE_SCALAR_KEYS
}

_SAFE_NORMALIZED_LIST_CONTAINER_KEYS = {
    _normalize_model_key("items"),
}

_SAFE_NORMALIZED_SCHEMA_LIST_KEYS = {
    _normalize_model_key("columns"),
}

_COUNT_NORMALIZED_KEYS = {
    _normalize_model_key(key)
    for key in {
        "column_count",
        "count",
        "returned_count",
        "row_count",
        "total_count",
    }
}

_SAFE_SCHEMA_COLUMN_STRING_KEYS = {
    _normalize_model_key(key)
    for key in {
        "column",
        "data_type",
        "field",
        "name",
        "type",
    }
}

_SAFE_SCHEMA_COLUMN_IDENTIFIER_KEYS = {
    _normalize_model_key(key)
    for key in {
        "column",
        "field",
        "name",
    }
}

_SAFE_SCHEMA_COLUMN_TYPE_KEYS = {
    _normalize_model_key(key)
    for key in {
        "data_type",
        "type",
    }
}

_SAFE_SCHEMA_TYPE_VALUES = {
    value.lower()
    for value in {
        "array",
        "bool",
        "boolean",
        "currency",
        "date",
        "datetime",
        "decimal",
        "double",
        "float",
        "int",
        "integer",
        "number",
        "object",
        "string",
        "text",
        "time",
        "timestamp",
        "unknown",
    }
}

_SAFE_SCHEMA_COLUMN_BOOL_KEYS = {
    _normalize_model_key(key)
    for key in {
        "nullable",
        "required",
    }
}

_SAFE_SCHEMA_COLUMN_COUNT_KEYS = {
    _normalize_model_key(key)
    for key in {
        "count",
        "distinct_count",
        "non_null_count",
        "null_count",
    }
}
_ERROR_STATUS_NORMALIZED_KEYS = {"status", "statuscode"}
_ERROR_STATUS_MARKERS = {"error", "errored"}

_BOOL_NORMALIZED_KEYS = {
    _normalize_model_key(key)
    for key in {
        "ok",
        "success",
    }
}

_OPAQUE_STRING_NORMALIZED_KEYS = {
    _normalize_model_key(key)
    for key in {
        "artifact_id",
        "confirmation_token",
        "fetch_id",
        "job_id",
        "safe_id",
    }
}

_ENUM_STRING_NORMALIZED_KEYS = {
    _normalize_model_key(key)
    for key in {
        "action",
        "status",
    }
}

_SOURCE_STRING_NORMALIZED_KEYS = {
    _normalize_model_key("source_type"),
}

_SAFE_SOURCE_TYPE_VALUES = {
    value.lower()
    for value in {
        "csv",
        "excel",
        "json",
        "manual",
        "unknown",
        "upload",
        "xls",
        "xlsx",
    }
}

_SAFE_STATUS_VALUES = {
    "complete",
    "completed",
    "failed",
    "ok",
    "pending",
    "queued",
    "ready",
    "running",
    "success",
}

_SAFE_ACTION_VALUES = {
    "cancelled",
    "created",
    "deleted",
    "scheduled",
    "status",
    "updated",
}
_FILTER_RESOLUTION_TOOLS = {
    "confirm_filter_interpretation",
    "resolve_filter_intent",
}
_FILTER_STATUS_VALUES = {
    "NEEDS_CONFIRMATION",
    "RESOLVED",
    "UNRESOLVED",
}
_FILTER_LOGIC_VALUES = {"AND", "OR"}
_FILTER_OPERATOR_VALUES = {
    "between",
    "contains_ci",
    "ends_with_ci",
    "eq",
    "gt",
    "gte",
    "in",
    "is_blank",
    "is_not_blank",
    "is_not_null",
    "is_null",
    "lt",
    "lte",
    "neq",
    "not_in",
    "starts_with_ci",
}
_FILTER_LITERAL_TYPES = {"boolean", "date", "number", "string"}
_FILTER_METADATA_KEYS = {
    _normalize_model_key(key)
    for key in {
        "canonical_dict_version",
        "compiler_version",
        "mapping_version",
        "normalizer_version",
        "schema_signature",
        "source_fingerprint",
    }
}
_FILTER_TOKEN_NORMALIZED_KEYS = {
    _normalize_model_key("resolution_token"),
}
_FILTER_SAFE_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9 _./#():,=-]+$")
_FILTER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.=-]+$")

_SAFE_OPAQUE_PREFIXES_BY_KEY = {
    _normalize_model_key("artifact_id"): ("artifact-",),
    _normalize_model_key("confirmation_token"): ("confirm-",),
    _normalize_model_key("fetch_id"): ("fetch-",),
    _normalize_model_key("job_id"): ("job-",),
    _normalize_model_key("safe_id"): ("safe-",),
}

_UNSAFE_SCALAR_SUBSTRINGS = {
    "address",
    "ave",
    "credential",
    "customer",
    "document",
    "doe",
    "email",
    "jane",
    "john",
    "label",
    "main",
    "name",
    "order",
    "phone",
    "raw",
    "road",
    "request",
    "response",
    "smith",
    "street",
    "token",
}

_UUID_PATTERN = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$",
)

_SAFE_SCHEMA_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9 _./#()-]+$")
_STREET_ADDRESS_PATTERN = re.compile(
    r"(?i)\b\d+\s+[A-Za-z0-9 .'-]+\s+"
    r"(?:ave|avenue|blvd|boulevard|dr|drive|ln|lane|rd|road|st|street|terrace|ter)\b",
)
_LEADING_ADDRESS_PATTERN = re.compile(r"(?i)^\d+\s+[A-Za-z][A-Za-z0-9 .'-]*$")
_DOMAIN_LIKE_PATTERN = re.compile(
    r"(?i)\b(?:www\.)?[a-z0-9][a-z0-9-]*\.[a-z][a-z0-9-]{1,}"
    r"(?:[/:?#]|$|\b)",
)
_COMPACT_ADDRESS_IDENTIFIER_PATTERN = re.compile(
    r"(?i)^\d+[a-z0-9]*"
    r"(?:main|ave|avenue|blvd|boulevard|dr|drive|ln|lane|rd|road|st|street|ter|terrace)"
    r"[a-z0-9]*$",
)
_NUMERIC_PREFIX_IDENTIFIER_PATTERN = re.compile(r"^\d+[A-Za-z]")
_CAMEL_PERSON_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Z]?[a-z]+(?:[A-Z][a-z]+){1,2}$",
)
_LONG_DIGIT_RUN_PATTERN = re.compile(r"\d{7,}")
_SCHEMA_IDENTIFIER_TOKEN_PATTERN = re.compile(
    r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+",
)
_SCHEMA_PERSON_TOKENS = {
    "bob",
    "doe",
    "jane",
    "john",
    "jones",
    "robert",
    "smith",
    "wilson",
}
_SCHEMA_ROW_VALUE_TECHNICAL_SUFFIX_TOKENS = {
    "address",
    "customer",
    "email",
    "id",
    "name",
    "order",
    "phone",
}
_SAFE_SCHEMA_TECHNICAL_IDENTIFIERS = {
    "carrier",
    "quantity",
    "servicelevel",
    "sku",
}
_SCHEMA_TECHNICAL_CAMEL_TOKENS = {
    "address",
    "amount",
    "billing",
    "carrier",
    "city",
    "code",
    "country",
    "count",
    "customer",
    "date",
    "email",
    "field",
    "from",
    "g",
    "gram",
    "grams",
    "id",
    "in",
    "inch",
    "inches",
    "item",
    "kg",
    "level",
    "line",
    "lb",
    "lbs",
    "name",
    "number",
    "order",
    "ounce",
    "ounces",
    "oz",
    "package",
    "phone",
    "pound",
    "pounds",
    "postal",
    "product",
    "quantity",
    "reference",
    "service",
    "ship",
    "shipping",
    "sku",
    "state",
    "status",
    "time",
    "to",
    "tracking",
    "type",
    "weight",
    "zip",
}
_ADDRESS_STREET_TOKENS = {
    "ave",
    "avenue",
    "blvd",
    "boulevard",
    "dr",
    "drive",
    "ln",
    "lane",
    "main",
    "rd",
    "road",
    "st",
    "street",
    "ter",
    "terrace",
}

_SAFE_STRING_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._-",
)

_GENERIC_POLICY_DENIAL_CONTENT = "Tool call denied by policy."


class LocalToolDispatcher:
    def __init__(
        self,
        catalog: Any,
        policy: RuntimePolicyEngine,
        emit_frontend: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.catalog = catalog
        self.policy = policy
        # Dispatcher records provider-neutral tool calls; handlers own domain events.
        self.emit_frontend = emit_frontend

    async def dispatch(self, call: ProviderToolCall) -> ProviderToolResult:
        self._emit_tool_call(call)

        if not self.catalog.has(call.tool_name):
            content = (
                f"Tool {call.tool_name!r} is not available in this conversation mode."
            )
            sanitized_error = sanitize_error_message(content)
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=sanitized_error or content,
                is_error=True,
                sanitized_error=sanitized_error,
            )

        decision = await self.policy.check_pre_tool(call)
        if not decision.allowed:
            content = _policy_denial_content(decision.reason)
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=content,
                is_error=True,
                sanitized_error=content,
            )

        tool = self.catalog.get(call.tool_name)
        try:
            raw_result = await tool.handler(call.parsed_input)
        except Exception as exc:
            logger.warning(
                "Conversation runtime tool handler failed for tool=%s "
                "call_id=%s exception_type=%s",
                call.tool_name,
                call.call_id,
                type(exc).__name__,
            )
            content = f"Tool {call.tool_name!r} failed."
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=content,
                is_error=True,
                sanitized_error=content,
            )

        payload = _extract_payload(raw_result)
        is_error = _detect_dispatch_error(self.policy, raw_result, payload)
        if is_error:
            content = _generic_error_content(call.tool_name)
            return ProviderToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                content=content,
                structured_payload={"error": content},
                is_error=True,
                sanitized_error=content,
            )

        safe_payload = _project_payload(payload, tool_name=call.tool_name)
        structured_payload = _structured_payload(payload, safe_payload)
        summary_payload = safe_payload if isinstance(payload, dict) else None
        content = _summarize_payload(call.tool_name, summary_payload, is_error=is_error)
        return ProviderToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            content=content,
            structured_payload=structured_payload,
            is_error=is_error,
            sanitized_error=sanitize_error_message(content) if is_error else None,
        )

    def _emit_tool_call(self, call: ProviderToolCall) -> None:
        payload = {
            "tool_name": call.tool_name,
            "tool_input": dict(call.parsed_input),
        }
        if call.call_id is not None:
            payload["tool_use_id"] = call.call_id

        self.emit_frontend("tool_call", payload)


def _generic_error_content(tool_name: str) -> str:
    return f"{tool_name} failed."


def _policy_denial_content(reason: str) -> str:
    if reason.startswith("Raw SQL keys "):
        return sanitize_error_message(reason) or _GENERIC_POLICY_DENIAL_CONTENT
    return _GENERIC_POLICY_DENIAL_CONTENT


def _detect_dispatch_error(
    policy: RuntimePolicyEngine,
    raw_result: Any,
    payload: Any,
) -> bool:
    if _has_explicit_error_envelope(raw_result):
        return True
    if _has_error_content(policy, raw_result):
        return True
    return policy.detect_error_response(_project_error_detection_payload(payload))


def _has_explicit_error_envelope(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("error"):
        return True
    if value.get("isError") is True:
        return True
    if value.get("is_error") is True:
        return True
    for key, item in value.items():
        if not _is_error_status_key(key):
            continue
        if isinstance(item, int) and item >= 400:
            return True
        if isinstance(item, str) and _is_error_status_marker(item):
            return True
    return False


def _is_error_status_key(key: Any) -> bool:
    return _normalize_model_key(key) in _ERROR_STATUS_NORMALIZED_KEYS


def _is_error_status_marker(value: str) -> bool:
    return value.strip().lower() in _ERROR_STATUS_MARKERS


def _has_error_content(policy: RuntimePolicyEngine, value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    content = value.get("content")
    if not isinstance(content, list):
        return False

    for item in content:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue

        text = item["text"]
        json_payload = _parse_json_payload(text)
        if json_payload is None:
            if policy.detect_error_response(text):
                return True
            continue

        if policy.detect_error_response(
            _project_error_detection_payload(json_payload)
        ):
            return True

    return False


def _parse_json_payload(value: str) -> Any:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _project_error_detection_payload(value: Any) -> Any:
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            if _is_unsafe_model_key(_normalize_model_key(key)):
                continue
            projected[key] = _project_error_detection_payload(item)
        return projected

    if isinstance(value, list):
        return [_project_error_detection_payload(item) for item in value]

    return value


def _structured_payload(payload: Any, safe_payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return safe_payload
    if isinstance(payload, list):
        return {"count": len(payload)}
    if isinstance(payload, str):
        return {"result_type": "text"}
    if isinstance(payload, bytes | bytearray):
        return {"result_type": "bytes"}
    return {"result_type": "scalar"}


def _extract_payload(raw_result: Any) -> Any:
    if not isinstance(raw_result, dict):
        return raw_result

    content = raw_result.get("content")
    if isinstance(content, list):
        first_text: str | None = None
        for item in content:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                continue

            text = item["text"]
            if first_text is None:
                first_text = text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue

        if first_text is not None:
            return first_text

    return raw_result


def _project_payload(value: Any, *, tool_name: str | None = None) -> Any:
    if tool_name in _FILTER_RESOLUTION_TOOLS and isinstance(value, dict):
        return _project_filter_resolution_payload(value)

    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _normalize_model_key(key)
            if _is_unsafe_model_key(normalized_key):
                continue

            if isinstance(item, dict):
                continue

            if isinstance(item, list):
                if normalized_key in _SAFE_NORMALIZED_SCHEMA_LIST_KEYS:
                    projected_columns = _project_schema_columns(item)
                    if projected_columns is not None:
                        projected[key] = projected_columns
                    continue

                if normalized_key in _SAFE_NORMALIZED_LIST_CONTAINER_KEYS:
                    projected[key] = _project_payload(item)
                continue

            if (
                normalized_key in _SAFE_NORMALIZED_SCALAR_KEYS
                and not isinstance(item, bytes | bytearray)
                and _is_safe_scalar_value(normalized_key, item)
            ):
                projected[key] = item

        return projected

    if isinstance(value, list):
        return {"count": len(value)}

    return value


def _project_filter_resolution_payload(value: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = _normalize_model_key(key)
        if _is_unsafe_model_key(normalized_key):
            continue

        if normalized_key == "status":
            if isinstance(item, str) and item in _FILTER_STATUS_VALUES:
                projected[key] = item
            continue

        if normalized_key == "root":
            root = _project_filter_node(item)
            if root is not None:
                projected[key] = root
            continue

        if normalized_key == "filterspec":
            if isinstance(item, dict):
                filter_spec = _project_filter_resolution_payload(item)
                if filter_spec:
                    projected[key] = filter_spec
            continue

        if normalized_key in _FILTER_TOKEN_NORMALIZED_KEYS:
            if _is_safe_filter_token(item):
                projected[key] = item
            continue

        if normalized_key in _FILTER_METADATA_KEYS:
            if _is_safe_filter_text(item, max_length=256):
                projected[key] = item
            continue

        if normalized_key == "pendingconfirmations":
            confirmations = _project_pending_confirmations(item)
            if confirmations:
                projected[key] = confirmations
            continue

        if normalized_key == "unresolvedterms":
            unresolved_terms = _project_unresolved_terms(item)
            if unresolved_terms:
                projected[key] = unresolved_terms

    return projected


def _project_filter_node(value: Any, *, depth: int = 0) -> dict[str, Any] | None:
    if not isinstance(value, dict) or depth > 8:
        return None

    projected: dict[str, Any] = {}
    logic = value.get("logic")
    if isinstance(logic, str) and logic in _FILTER_LOGIC_VALUES:
        projected["logic"] = logic
        conditions = value.get("conditions")
        if isinstance(conditions, list):
            projected["conditions"] = [
                child
                for item in conditions[:100]
                if (child := _project_filter_node(item, depth=depth + 1)) is not None
            ]
        return projected if "conditions" in projected else None

    column = value.get("column")
    operator = value.get("operator")
    operands = value.get("operands")
    if (
        _is_safe_filter_text(column, max_length=128)
        and isinstance(operator, str)
        and operator in _FILTER_OPERATOR_VALUES
        and isinstance(operands, list)
    ):
        projected["column"] = column
        projected["operator"] = operator
        projected["operands"] = [
            operand
            for item in operands[:100]
            if (operand := _project_filter_operand(item)) is not None
        ]
        return projected

    semantic_key = value.get("semantic_key")
    target_column = value.get("target_column")
    if _is_safe_filter_text(semantic_key) and _is_safe_filter_text(
        target_column,
        max_length=128,
    ):
        return {
            "semantic_key": semantic_key,
            "target_column": target_column,
        }

    return None


def _project_filter_operand(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    literal_type = value.get("type")
    literal_value = value.get("value")
    if not isinstance(literal_type, str) or literal_type not in _FILTER_LITERAL_TYPES:
        return None

    if not _is_safe_filter_literal_value(literal_value):
        return None

    return {"type": literal_type, "value": literal_value}


def _project_pending_confirmations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    projected: list[dict[str, str]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue

        confirmation: dict[str, str] = {}
        for key in ("term", "expansion", "tier"):
            item_value = item.get(key)
            if _is_safe_filter_text(item_value, max_length=256):
                confirmation[key] = item_value

        if "term" in confirmation:
            projected.append(confirmation)

    return projected


def _project_unresolved_terms(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    projected: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue

        unresolved: dict[str, Any] = {}
        phrase = item.get("phrase")
        if _is_safe_filter_text(phrase, max_length=256):
            unresolved["phrase"] = phrase

        suggestions = item.get("suggestions")
        if isinstance(suggestions, list):
            projected_suggestions = _project_filter_suggestions(suggestions)
            if projected_suggestions:
                unresolved["suggestions"] = projected_suggestions

        if unresolved:
            projected.append(unresolved)

    return projected


def _project_filter_suggestions(value: list[Any]) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue

        suggestion: dict[str, str] = {}
        for key in ("key", "expansion"):
            item_value = item.get(key)
            if _is_safe_filter_text(item_value, max_length=256):
                suggestion[key] = item_value

        if "key" in suggestion:
            projected.append(suggestion)

    return projected


def _is_safe_filter_token(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 8192
        and _FILTER_TOKEN_PATTERN.fullmatch(value) is not None
    )


def _is_safe_filter_text(value: Any, *, max_length: int = 512) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and value.strip() == value
        and "://" not in value.lower()
        and "@" not in value
        and _FILTER_SAFE_TEXT_PATTERN.fullmatch(value) is not None
    )


def _is_safe_filter_literal_value(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float):
        return True
    return _is_safe_filter_text(value)


def _project_schema_columns(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None

    projected_columns: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        projected_column: dict[str, Any] = {}
        has_safe_identifier = False
        for key, column_value in item.items():
            normalized_key = _normalize_model_key(key)
            if normalized_key in _SAFE_SCHEMA_COLUMN_STRING_KEYS:
                if _is_safe_schema_text(normalized_key, column_value):
                    projected_column[key] = column_value
                    if normalized_key in _SAFE_SCHEMA_COLUMN_IDENTIFIER_KEYS:
                        has_safe_identifier = True
                continue

            if normalized_key in _SAFE_SCHEMA_COLUMN_BOOL_KEYS:
                if isinstance(column_value, bool):
                    projected_column[key] = column_value
                continue

            if normalized_key in _SAFE_SCHEMA_COLUMN_COUNT_KEYS:
                if _is_safe_count_value(column_value):
                    projected_column[key] = column_value

        if projected_column and has_safe_identifier:
            projected_columns.append(projected_column)

    return projected_columns


def _is_unsafe_model_key(normalized_key: str) -> bool:
    if normalized_key in _DROP_MODEL_NORMALIZED_KEYS:
        return True
    return any(
        fragment in normalized_key
        for fragment in _UNSAFE_NORMALIZED_KEY_FRAGMENTS
    )


def _is_safe_schema_text(normalized_key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if not value or len(value) > 128:
        return False
    if value.strip() != value:
        return False
    if normalized_key in _SAFE_SCHEMA_COLUMN_TYPE_KEYS:
        return _is_safe_schema_type(value)

    value_lower = value.lower()
    if "://" in value_lower or value_lower.startswith(("http:", "https:")):
        return False
    if "@" in value:
        return False
    if _DOMAIN_LIKE_PATTERN.search(value) is not None:
        return False
    if _STREET_ADDRESS_PATTERN.search(value) is not None:
        return False
    if _LEADING_ADDRESS_PATTERN.fullmatch(value) is not None:
        return False
    normalized_value = _normalize_model_key(value)
    if normalized_value.isdigit() and len(normalized_value) > 6:
        return False
    if (
        normalized_key in _SAFE_SCHEMA_COLUMN_IDENTIFIER_KEYS
        and not _is_safe_schema_identifier(value)
    ):
        return False

    return _SAFE_SCHEMA_TEXT_PATTERN.fullmatch(value) is not None


def _is_safe_schema_type(value: str) -> bool:
    return value == value.strip().lower() and value in _SAFE_SCHEMA_TYPE_VALUES


def _is_safe_schema_identifier(value: str) -> bool:
    normalized_value = _normalize_model_key(value)
    tokens = _schema_identifier_tokens(value)
    if _LONG_DIGIT_RUN_PATTERN.search(value) is not None:
        return False
    if _NUMERIC_PREFIX_IDENTIFIER_PATTERN.match(value) is not None:
        return False
    if _COMPACT_ADDRESS_IDENTIFIER_PATTERN.fullmatch(value) is not None:
        return False
    if _has_person_token_sequence(value):
        return False
    if _has_row_value_technical_prefix(value):
        return False
    if _has_row_value_technical_suffix(value):
        return False
    if normalized_value in _SAFE_SCHEMA_TECHNICAL_IDENTIFIERS:
        return True
    if tokens and not _has_only_schema_technical_tokens(tokens):
        return False
    if _looks_like_person_name(value):
        return False
    if _CAMEL_PERSON_IDENTIFIER_PATTERN.fullmatch(value) is not None:
        return _is_technical_camel_identifier(value)
    return _has_schema_technical_fragment(normalized_value)


def _has_only_schema_technical_tokens(tokens: list[str]) -> bool:
    return all(
        token.isdigit() or token.lower() in _SCHEMA_TECHNICAL_CAMEL_TOKENS
        for token in tokens
    )


def _is_technical_camel_identifier(value: str) -> bool:
    tokens = _schema_identifier_tokens(value)
    return bool(tokens) and _has_only_schema_technical_tokens(tokens)


def _has_person_token_sequence(value: str) -> bool:
    tokens = [
        token.lower()
        for token in _schema_identifier_tokens(value)
        if not token.isdigit()
    ]
    return any(
        first in _SCHEMA_PERSON_TOKENS and second in _SCHEMA_PERSON_TOKENS
        for first, second in zip(tokens, tokens[1:], strict=False)
    )


def _has_row_value_technical_suffix(value: str) -> bool:
    tokens = [token.lower() for token in _schema_identifier_tokens(value)]
    if len(tokens) < 2:
        return False

    first_token = tokens[0]
    if not (
        first_token.isdigit()
        or first_token in _SCHEMA_PERSON_TOKENS
        or _is_unknown_row_value_prefix(first_token)
    ):
        return False

    return any(
        token in _SCHEMA_ROW_VALUE_TECHNICAL_SUFFIX_TOKENS
        for token in tokens[1:]
    )


def _is_unknown_row_value_prefix(token: str) -> bool:
    return token.isalpha() and token not in _SCHEMA_TECHNICAL_CAMEL_TOKENS


def _has_row_value_technical_prefix(value: str) -> bool:
    tokens = [token.lower() for token in _schema_identifier_tokens(value)]
    if len(tokens) < 2:
        return False

    if _has_address_like_token_window(tokens):
        return True

    for index, token in enumerate(tokens[:-1]):
        suffix_tokens = tokens[index + 1 :]
        if token == "phone" and _has_phone_like_suffix(suffix_tokens):
            return True
        if token == "address" and _has_address_like_suffix(suffix_tokens):
            return True
        if token == "email" and _has_email_like_suffix(suffix_tokens):
            return True

    return False


def _has_phone_like_suffix(suffix_tokens: list[str]) -> bool:
    digit_count = sum(len(token) for token in suffix_tokens if token.isdigit())
    return digit_count >= 7


def _has_email_like_suffix(suffix_tokens: list[str]) -> bool:
    if len(suffix_tokens) < 2:
        return False

    domain_tokens = {
        "app",
        "biz",
        "ca",
        "co",
        "com",
        "dev",
        "edu",
        "fr",
        "gov",
        "info",
        "io",
        "me",
        "net",
        "org",
        "uk",
        "us",
    }
    return any(token in domain_tokens for token in suffix_tokens[1:])


def _has_address_like_token_window(tokens: list[str]) -> bool:
    return any(
        token.isdigit() and _has_address_like_suffix(tokens[index:])
        for index, token in enumerate(tokens[:-1])
    )


def _has_address_like_suffix(suffix_tokens: list[str]) -> bool:
    if not suffix_tokens or not suffix_tokens[0].isdigit():
        return False

    compact_suffix = "".join(suffix_tokens)
    if _COMPACT_ADDRESS_IDENTIFIER_PATTERN.fullmatch(compact_suffix) is not None:
        return True

    return any(token in _ADDRESS_STREET_TOKENS for token in suffix_tokens[1:])


def _schema_identifier_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for part in re.split(r"[\s_-]+", value):
        if not part:
            continue
        tokens.extend(_SCHEMA_IDENTIFIER_TOKEN_PATTERN.findall(part))
    return tokens


def _looks_like_person_name(value: str) -> bool:
    normalized_value = _normalize_model_key(value)
    if _has_schema_technical_fragment(normalized_value):
        return False

    tokens = [token for token in re.split(r"[\s_-]+", value) if token]
    if len(tokens) not in {2, 3}:
        return False
    return all(token.isalpha() for token in tokens)


def _has_schema_technical_fragment(normalized_value: str) -> bool:
    technical_fragments = {
        "address",
        "amount",
        "city",
        "code",
        "country",
        "count",
        "date",
        "email",
        "field",
        "from",
        "id",
        "name",
        "number",
        "order",
        "phone",
        "postal",
        "ship",
        "shipping",
        "state",
        "status",
        "time",
        "to",
        "type",
        "weight",
        "zip",
    }
    return any(fragment in normalized_value for fragment in technical_fragments)


def _is_safe_source_type(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value == value.strip().lower() and value in _SAFE_SOURCE_TYPE_VALUES


def _is_safe_scalar_value(normalized_key: str, value: Any) -> bool:
    if normalized_key in _COUNT_NORMALIZED_KEYS:
        return _is_safe_count_value(value)

    if normalized_key in _BOOL_NORMALIZED_KEYS:
        return isinstance(value, bool)

    if normalized_key in _OPAQUE_STRING_NORMALIZED_KEYS:
        return _is_safe_opaque_id(normalized_key, value)

    if normalized_key in _ENUM_STRING_NORMALIZED_KEYS:
        return _is_safe_enum_value(normalized_key, value)

    if normalized_key in _SOURCE_STRING_NORMALIZED_KEYS:
        return _is_safe_source_type(value)

    return False


def _is_safe_count_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 999_999
    if isinstance(value, float):
        return math.isfinite(value) and 0 <= value <= 999_999
    return False


def _is_safe_enum_value(normalized_key: str, value: Any) -> bool:
    if not _is_safe_short_token(value):
        return False

    normalized_value = value.lower()
    if normalized_key == _normalize_model_key("status"):
        return normalized_value in _SAFE_STATUS_VALUES
    if normalized_key == _normalize_model_key("action"):
        return normalized_value in _SAFE_ACTION_VALUES
    return False


def _is_safe_opaque_id(normalized_key: str, value: Any) -> bool:
    if not _is_safe_short_token(value):
        return False
    if _UUID_PATTERN.fullmatch(value) is not None:
        return True

    safe_prefixes = _SAFE_OPAQUE_PREFIXES_BY_KEY.get(normalized_key, ())
    for prefix in safe_prefixes:
        if not value.startswith(prefix):
            continue
        suffix = value.removeprefix(prefix)
        return _is_safe_opaque_suffix(suffix)

    return False


def _is_safe_opaque_suffix(suffix: str) -> bool:
    return suffix.isdigit() and 1 <= len(suffix) <= 6


def _is_safe_short_token(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if not value or len(value) > 128:
        return False
    if value.strip() != value:
        return False
    if not all(char in _SAFE_STRING_CHARS for char in value):
        return False

    normalized_value = _normalize_model_key(value)
    return not any(
        unsafe in normalized_value for unsafe in _UNSAFE_SCALAR_SUBSTRINGS
    )


def _summarize_payload(tool_name: str, payload: Any, *, is_error: bool) -> str:
    if is_error:
        return sanitize_error_message(json.dumps(payload, default=str)) or ""

    if isinstance(payload, dict):
        keys = ", ".join(sorted(payload))
        return f"{tool_name} completed. Provider-safe fields: {keys}."

    return f"{tool_name} completed."
