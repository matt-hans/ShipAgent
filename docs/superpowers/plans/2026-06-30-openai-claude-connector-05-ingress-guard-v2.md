# Ingress Guard v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider ingress guard v2 for OpenAI/Claude connector calls: canonical input hashing, duplicate-call collapse, in-flight coalescing, semantic loop breaking, terminal `repeated_tool_call` envelopes, and `max_result_bytes` enforcement.

**Architecture:** Keep the ingress guard in `src/control_plane/request_controls.py`, where the existing Redis token buckets already live. The guard exposes a new `guarded_call(...)` wrapper that Plan 1 endpoint placement and Plan 7 provider execution can call around tool handlers, while retaining the existing `require_allowed(...)` API for the current hosted MCP wrapper. It stores only canonical hashes, short in-flight markers, and provider-safe JSON results in Redis; it never stores raw provider prompts, row data, labels, credentials, or full request bodies.

**Tech Stack:** Python 3.12, asyncio, redis.asyncio-compatible client, pytest, dataclasses, JSON canonicalization, SHA-256, existing `src.registry.models.ToolContract` `rate_limit_class` and `max_result_bytes` fields.

---

## Source Context

- Required spec: `docs/superpowers/specs/2026-06-10-openai-claude-connector-design.md`, especially sections 3.5, 3.6, 4 Plan 5, and 5.
- Repo rules checked: `AGENTS.md` and `src/AGENTS.md`.
- Current implementation checked:
  - `src/control_plane/request_controls.py` has token bucket rate limits, `hash_arguments(...)`, and a basic identical-call loop guard.
  - `src/hosted_mcp/server.py` currently computes `hash_arguments(arguments)`, calls `request_controls.require_allowed(...)`, invokes the handler, then calls `project_result(...)`.
  - `src/control_plane/result_projection.py` already validates schemas and has a size check, but it raises `ValueError`; this slice adds guard-layer provider-safe terminal envelopes without changing Plan 6 output-profile work.
  - `src/services/conversation_runtime/policy.py` already owns local provider-neutral policy gates; this plan does not move ingress guard behavior into provider adapters or runtime policy.

## File Structure

Future implementation changes are intentionally narrow because other workers own adjacent connector slices.

- Modify: `src/control_plane/request_controls.py`
  - Keep existing token bucket behavior.
  - Add `canonical_input_hash(...)` and keep `hash_arguments(...)` as a compatibility alias.
  - Add provider-safe envelope helpers for terminal ingress failures.
  - Add `GuardedCallResult` and `RequestControls.guarded_call(...)`.
  - Add short-lived Redis duplicate-result cache keyed by provider connection, tool name, and canonical input hash.
  - Add short-lived Redis in-flight markers with polling-based coalescing.
  - Add semantic loop breaker returning a terminal `repeated_tool_call` envelope from `guarded_call(...)`; keep `require_allowed(...)` raising `RequestControlError` for current callers.
  - Add `max_result_bytes` enforcement before a result is returned or cached.
- Modify: `tests/control_plane/test_request_controls.py`
  - Expand `_FakeRedis` to support `eval`, `set`, `get`, and `delete` with TTL semantics.
  - Add focused unit tests for canonical hashing, safe envelopes, duplicate collapse, coalescing, loop breaking, result caps, and backward-compatible `require_allowed(...)`.

Do not modify these files in Plan 5:

- `src/hosted_mcp/server.py`: Plan 1 endpoint placement or Plan 7 provider execution should call `guarded_call(...)` when wiring the final public endpoint.
- `src/control_plane/result_projection.py`: Plan 6 owns output profiles and origin redaction. Plan 5 only enforces byte caps and returns provider-safe guard envelopes.
- `src/control_plane/redis_keys.py`: Plan 4 owns broad Redis retention/key policy. Plan 5 uses private guard-key helpers inside `request_controls.py` to avoid cross-slice churn.
- `src/services/conversation_runtime/*`: this slice is hosted provider ingress, not local model-runtime policy.

## Guard Contract

`RequestControls.guarded_call(...)` returns `GuardedCallResult`:

```python
GuardedCallResult(
    result={"status": "..."},
    arguments_hash="sha256-hex",
    source="handler" | "duplicate" | "coalesced" | "terminal_envelope" | "coalesced_timeout",
)
```

The terminal repeated-call envelope is:

```python
{
    "status": "blocked",
    "reason": "repeated_tool_call",
    "terminal": True,
    "message": (
        "This tool call repeated with the same canonical input. "
        "Do not retry the same call. Ask the user to change the request "
        "or wait before trying again."
    ),
}
```

The oversized-result envelope is:

```python
{
    "status": "blocked",
    "reason": "result_too_large",
    "terminal": True,
    "message": (
        "The tool result exceeded ShipAgent's provider result size limit. "
        "Do not retry the same call. Ask the user to narrow the request "
        "or open ShipAgent for details."
    ),
    "max_result_bytes": 1024,
}
```

These envelopes match the spec's provider-facing failure rule: schema-valid result shape, sanitized message, and no MCP protocol error for guard outcomes. Plan 6/7 must ensure public tool output schemas admit these common failure envelopes.

### Task 1: Canonical Input Hash API

**Files:**
- Modify: `tests/control_plane/test_request_controls.py`
- Modify: `src/control_plane/request_controls.py`

- [ ] **Step 1: Write the failing canonical-hash tests**

Replace the import block in `tests/control_plane/test_request_controls.py` with:

```python
import asyncio
import time

import pytest

from src.control_plane.request_controls import (
    RequestControlError,
    RequestControls,
    canonical_input_hash,
    hash_arguments,
)
```

Add these tests after the `fake_controls` fixture:

```python
def test_canonical_input_hash_is_stable_for_json_key_order():
    first = canonical_input_hash(
        {
            "shipment_id": "ship-1",
            "options": {"service": "ground", "signature": False},
        }
    )
    second = canonical_input_hash(
        {
            "options": {"signature": False, "service": "ground"},
            "shipment_id": "ship-1",
        }
    )

    assert first == second
    assert hash_arguments(
        {
            "options": {"signature": False, "service": "ground"},
            "shipment_id": "ship-1",
        }
    ) == first


def test_canonical_input_hash_redacts_sensitive_values_recursively():
    first = canonical_input_hash(
        {
            "shipment_id": "ship-1",
            "token": "provider-visible-secret-1",
            "nested": {"api_key": "provider-visible-secret-2"},
            "packages": [{"password": "provider-visible-secret-3", "weight": 2}],
        }
    )
    second = canonical_input_hash(
        {
            "packages": [{"password": "different-secret", "weight": 2}],
            "nested": {"api_key": "different-secret"},
            "token": "different-secret",
            "shipment_id": "ship-1",
        }
    )
    changed_business_input = canonical_input_hash(
        {
            "shipment_id": "ship-2",
            "token": "provider-visible-secret-1",
            "nested": {"api_key": "provider-visible-secret-2"},
            "packages": [{"password": "provider-visible-secret-3", "weight": 2}],
        }
    )

    assert first == second
    assert first != changed_business_input
```

- [ ] **Step 2: Run the canonical-hash tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_canonical_input_hash_is_stable_for_json_key_order tests/control_plane/test_request_controls.py::test_canonical_input_hash_redacts_sensitive_values_recursively -v
```

Expected: FAIL with `ImportError: cannot import name 'canonical_input_hash'`.

- [ ] **Step 3: Add the canonical hash function**

In `src/control_plane/request_controls.py`, replace the current imports and `hash_arguments(...)` function area with this code, preserving the existing `RATE_LIMIT_BY_CLASS` and `_SENSITIVE_ARGUMENT_KEYS` definitions:

```python
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.control_plane.redis_keys import RedisKey

DEFAULT_WINDOW_SECONDS = 60
LOOP_DETECTION_LIMIT = 3

RATE_LIMIT_BY_CLASS: dict[str, int] = {
    "default": 10,
    "read": 30,
    "estimate": 10,
    "write": 20,
    "purchase": 5,
}


def _normalize_rate_limit_class(rate_limit_class: str | None) -> str:
    return rate_limit_class if rate_limit_class in RATE_LIMIT_BY_CLASS else "default"


_SENSITIVE_ARGUMENT_KEYS = frozenset(
    {
        "secret",
        "api_secret",
        "api_key",
        "access_token",
        "token",
        "password",
        "provider_file_url",
        "file_url",
    }
)


def _canonicalize_argument_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[redacted]"
                if str(key).lower() in _SENSITIVE_ARGUMENT_KEYS
                else _canonicalize_argument_value(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_argument_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize_argument_value(item) for item in value]
    return value


def canonical_input_hash(arguments: Mapping[str, object]) -> str:
    normalized = _canonicalize_argument_value(dict(arguments))
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def hash_arguments(arguments: Mapping[str, object]) -> str:
    return canonical_input_hash(arguments)
```

- [ ] **Step 4: Run the canonical-hash tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_canonical_input_hash_is_stable_for_json_key_order tests/control_plane/test_request_controls.py::test_canonical_input_hash_redacts_sensitive_values_recursively -v
```

Expected: PASS.

- [ ] **Step 5: Commit the canonical hash API**

Run:

```bash
git add src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
git commit -m "feat: add canonical provider input hashing"
```

### Task 2: Provider-Safe Guard Envelopes and Result Byte Caps

**Files:**
- Modify: `tests/control_plane/test_request_controls.py`
- Modify: `src/control_plane/request_controls.py`

- [ ] **Step 1: Write failing envelope and result-cap tests**

Extend the import from `src.control_plane.request_controls` in `tests/control_plane/test_request_controls.py` to include:

```python
    enforce_max_result_bytes,
    repeated_tool_call_envelope,
```

Add these tests after the canonical-hash tests:

```python
def test_repeated_tool_call_envelope_is_terminal_and_provider_safe():
    assert repeated_tool_call_envelope() == {
        "status": "blocked",
        "reason": "repeated_tool_call",
        "terminal": True,
        "message": (
            "This tool call repeated with the same canonical input. "
            "Do not retry the same call. Ask the user to change the request "
            "or wait before trying again."
        ),
    }


def test_enforce_max_result_bytes_returns_terminal_envelope_without_raw_payload():
    result = enforce_max_result_bytes(
        {"job_id": "job-1", "payload": "x" * 2048},
        max_result_bytes=256,
    )

    assert result == {
        "status": "blocked",
        "reason": "result_too_large",
        "terminal": True,
        "message": (
            "The tool result exceeded ShipAgent's provider result size limit. "
            "Do not retry the same call. Ask the user to narrow the request "
            "or open ShipAgent for details."
        ),
        "max_result_bytes": 256,
    }
    assert "x" * 32 not in result["message"]


def test_enforce_max_result_bytes_allows_small_results():
    result = {"job_id": "job-1", "status": "processing"}

    assert enforce_max_result_bytes(result, max_result_bytes=1024) == result
```

- [ ] **Step 2: Run the envelope tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_repeated_tool_call_envelope_is_terminal_and_provider_safe tests/control_plane/test_request_controls.py::test_enforce_max_result_bytes_returns_terminal_envelope_without_raw_payload tests/control_plane/test_request_controls.py::test_enforce_max_result_bytes_allows_small_results -v
```

Expected: FAIL with import errors for `enforce_max_result_bytes` and `repeated_tool_call_envelope`.

- [ ] **Step 3: Add provider-safe envelope helpers**

In `src/control_plane/request_controls.py`, add this code after `hash_arguments(...)`:

```python
ProviderEnvelopeStatus = Literal["blocked", "unavailable", "processing_unknown"]

REPEATED_TOOL_CALL_MESSAGE = (
    "This tool call repeated with the same canonical input. "
    "Do not retry the same call. Ask the user to change the request "
    "or wait before trying again."
)

RESULT_TOO_LARGE_MESSAGE = (
    "The tool result exceeded ShipAgent's provider result size limit. "
    "Do not retry the same call. Ask the user to narrow the request "
    "or open ShipAgent for details."
)


def provider_safe_error_envelope(
    *,
    status: ProviderEnvelopeStatus,
    reason: str,
    terminal: bool,
    message: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    envelope: dict[str, object] = {
        "status": status,
        "reason": reason,
        "terminal": terminal,
        "message": message,
    }
    if extra:
        for key, value in extra.items():
            if isinstance(value, str | int | float | bool) or value is None:
                envelope[str(key)] = value
    return envelope


def repeated_tool_call_envelope() -> dict[str, object]:
    return provider_safe_error_envelope(
        status="blocked",
        reason="repeated_tool_call",
        terminal=True,
        message=REPEATED_TOOL_CALL_MESSAGE,
    )


def result_too_large_envelope(max_result_bytes: int) -> dict[str, object]:
    return provider_safe_error_envelope(
        status="blocked",
        reason="result_too_large",
        terminal=True,
        message=RESULT_TOO_LARGE_MESSAGE,
        extra={"max_result_bytes": max_result_bytes},
    )


def _provider_result_bytes(result: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def enforce_max_result_bytes(
    result: dict[str, object],
    *,
    max_result_bytes: int,
) -> dict[str, object]:
    if _provider_result_bytes(result) <= max_result_bytes:
        return result
    return result_too_large_envelope(max_result_bytes)
```

Also update the `typing` import added in Task 1:

```python
from typing import Any, Literal
```

- [ ] **Step 4: Run the envelope tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_repeated_tool_call_envelope_is_terminal_and_provider_safe tests/control_plane/test_request_controls.py::test_enforce_max_result_bytes_returns_terminal_envelope_without_raw_payload tests/control_plane/test_request_controls.py::test_enforce_max_result_bytes_allows_small_results -v
```

Expected: PASS.

- [ ] **Step 5: Commit the envelope helpers**

Run:

```bash
git add src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
git commit -m "feat: add provider-safe ingress guard envelopes"
```

### Task 3: Duplicate Collapse and Semantic Loop Breaker

**Files:**
- Modify: `tests/control_plane/test_request_controls.py`
- Modify: `src/control_plane/request_controls.py`

- [ ] **Step 1: Expand fake Redis and write failing guarded-call tests**

Replace `_FakeRedis` in `tests/control_plane/test_request_controls.py` with:

```python
class _FakeRedis:
    def __init__(self):
        self._values: dict[str, tuple[object, float | None]] = {}

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (_, expiry) in self._values.items()
            if expiry is not None and now > expiry
        ]
        for key in expired:
            self._values.pop(key, None)

    async def eval(self, script: str, keys: int, *args: str) -> int:
        if keys != 1:
            raise RuntimeError("unexpected keys arg")
        self._purge_expired()
        key = args[0]
        ttl = float(args[2] if "SA_RATE_LIMIT" in script else args[1])
        value, _ = self._values.get(key, (0, None))
        next_value = int(value) + 1
        expiry = time.monotonic() + ttl
        self._values[key] = (next_value, expiry)
        return next_value

    async def set(
        self,
        name: str,
        value: object,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        self._purge_expired()
        if nx and name in self._values:
            return False
        expiry = time.monotonic() + ex if ex is not None else None
        self._values[name] = (value, expiry)
        return True

    async def get(self, name: str) -> object | None:
        self._purge_expired()
        entry = self._values.get(name)
        if entry is None:
            return None
        return entry[0]

    async def delete(self, *names: str) -> int:
        self._purge_expired()
        deleted = 0
        for name in names:
            if name in self._values:
                deleted += 1
                self._values.pop(name, None)
        return deleted
```

Extend the import from `src.control_plane.request_controls` to include:

```python
    GuardedCallResult,
```

Add these tests after the existing loop-breaker test:

```python
@pytest.mark.asyncio
async def test_guarded_call_collapses_duplicate_completed_calls(fake_controls):
    calls = 0

    async def handler():
        nonlocal calls
        calls += 1
        return {"status": "rated", "rate_id": "rate-1"}

    first = await fake_controls.guarded_call(
        connection_id="connection-1",
        tool_name="get_shipment_rates",
        rate_limit_class="estimate",
        arguments={"shipment_id": "ship-1", "options": {"service": "ground"}},
        max_result_bytes=1024,
        call=handler,
    )
    second = await fake_controls.guarded_call(
        connection_id="connection-1",
        tool_name="get_shipment_rates",
        rate_limit_class="estimate",
        arguments={"options": {"service": "ground"}, "shipment_id": "ship-1"},
        max_result_bytes=1024,
        call=handler,
    )

    assert isinstance(first, GuardedCallResult)
    assert calls == 1
    assert first.source == "handler"
    assert second.source == "duplicate"
    assert second.arguments_hash == first.arguments_hash
    assert second.result == {"status": "rated", "rate_id": "rate-1"}


@pytest.mark.asyncio
async def test_guarded_call_returns_repeated_tool_call_after_duplicate_threshold(
    fake_controls,
):
    calls = 0

    async def handler():
        nonlocal calls
        calls += 1
        return {"job_id": "job-1", "status": "processing"}

    results = []
    for _ in range(4):
        results.append(
            await fake_controls.guarded_call(
                connection_id="connection-1",
                tool_name="get_job_status",
                rate_limit_class="read",
                arguments={"job_id": "job-1"},
                max_result_bytes=1024,
                call=handler,
            )
        )

    assert calls == 1
    assert [result.source for result in results] == [
        "handler",
        "duplicate",
        "duplicate",
        "terminal_envelope",
    ]
    assert results[-1].result == repeated_tool_call_envelope()
```

- [ ] **Step 2: Run the guarded-call tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_guarded_call_collapses_duplicate_completed_calls tests/control_plane/test_request_controls.py::test_guarded_call_returns_repeated_tool_call_after_duplicate_threshold -v
```

Expected: FAIL with `AttributeError: 'RequestControls' object has no attribute 'guarded_call'`.

- [ ] **Step 3: Add duplicate-result cache and guarded-call wrapper**

Update the imports in `src/control_plane/request_controls.py`:

```python
import inspect
```

Update the collection import:

```python
from collections.abc import Awaitable, Callable, Mapping
```

Add these constants after `LOOP_DETECTION_LIMIT`:

```python
DUPLICATE_RESULT_TTL_SECONDS = 60
```

Add these helper functions after `enforce_max_result_bytes(...)`:

```python
def _duplicate_result_key(
    connection_id: str,
    tool_name: str,
    arguments_hash: str,
) -> str:
    return f"sa:guard:result:{connection_id}:{tool_name}:{arguments_hash}"


def _decode_redis_value(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _serialize_provider_result(result: Mapping[str, object]) -> str:
    return json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _deserialize_provider_result(value: object) -> dict[str, object]:
    parsed = json.loads(_decode_redis_value(value))
    if not isinstance(parsed, dict):
        return provider_safe_error_envelope(
            status="unavailable",
            reason="cached_result_invalid",
            terminal=True,
            message=(
                "ShipAgent could not read a cached tool result. "
                "Do not retry the same call. Ask the user to wait before trying again."
            ),
        )
    return parsed
```

Replace `RequestControlError` with:

```python
@dataclass
class RequestControlError(PermissionError):
    code: str
    message: str
    retry_after_seconds: int | None = None
    envelope: dict[str, object] | None = None

    def __str__(self) -> str:
        if self.retry_after_seconds is None:
            return self.message
        return f"{self.message} (retry_after={self.retry_after_seconds})"
```

Add `GuardedCallResult` after `RequestControlError`:

```python
GuardedCallSource = Literal[
    "handler",
    "duplicate",
    "coalesced",
    "terminal_envelope",
    "coalesced_timeout",
]


@dataclass(frozen=True)
class GuardedCallResult:
    result: dict[str, object]
    arguments_hash: str
    source: GuardedCallSource
```

Inside `RequestControls`, replace `_require_loop_guard(...)` with these methods, keeping `_require_rate_limit(...)` unchanged:

```python
    async def guarded_call(
        self,
        *,
        connection_id: str,
        tool_name: str,
        rate_limit_class: str,
        arguments: Mapping[str, object],
        max_result_bytes: int,
        call: Callable[[], Awaitable[dict[str, object]] | dict[str, object]],
    ) -> GuardedCallResult:
        arguments_hash = canonical_input_hash(arguments)
        await self._require_rate_limit(
            connection_id=connection_id,
            rate_limit_class=rate_limit_class,
        )

        attempt_count = await self._increment_semantic_attempt(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )
        if attempt_count > LOOP_DETECTION_LIMIT:
            return GuardedCallResult(
                result=repeated_tool_call_envelope(),
                arguments_hash=arguments_hash,
                source="terminal_envelope",
            )

        cached = await self._load_cached_result(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )
        if cached is not None:
            return GuardedCallResult(
                result=cached,
                arguments_hash=arguments_hash,
                source="duplicate",
            )

        result = call()
        if inspect.isawaitable(result):
            result = await result
        capped_result = enforce_max_result_bytes(
            result,
            max_result_bytes=max_result_bytes,
        )
        await self._store_cached_result(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            result=capped_result,
        )
        return GuardedCallResult(
            result=capped_result,
            arguments_hash=arguments_hash,
            source=(
                "terminal_envelope"
                if capped_result.get("terminal") is True
                else "handler"
            ),
        )

    async def _increment_semantic_attempt(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
    ) -> int:
        key = RedisKey.loop_guard(connection_id, tool_name, arguments_hash)
        return int(
            await self.redis.eval(
                self._LOOP_GUARD_LUA,
                1,
                key,
                str(DEFAULT_WINDOW_SECONDS),
            )
        )

    async def _require_loop_guard(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
    ) -> None:
        count = await self._increment_semantic_attempt(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )
        if count > LOOP_DETECTION_LIMIT:
            raise RequestControlError(
                code="provider_loop_detected",
                message="identical call loop detected",
                envelope=repeated_tool_call_envelope(),
            )

    async def _load_cached_result(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
    ) -> dict[str, object] | None:
        value = await self.redis.get(
            _duplicate_result_key(connection_id, tool_name, arguments_hash)
        )
        if value is None:
            return None
        return _deserialize_provider_result(value)

    async def _store_cached_result(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
        result: dict[str, object],
    ) -> None:
        await self.redis.set(
            _duplicate_result_key(connection_id, tool_name, arguments_hash),
            _serialize_provider_result(result),
            ex=DUPLICATE_RESULT_TTL_SECONDS,
        )
```

- [ ] **Step 4: Run the guarded-call tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_guarded_call_collapses_duplicate_completed_calls tests/control_plane/test_request_controls.py::test_guarded_call_returns_repeated_tool_call_after_duplicate_threshold -v
```

Expected: PASS.

- [ ] **Step 5: Run existing request-control tests for compatibility**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_rate_limit_is_namespaced_by_connection_and_class tests/control_plane/test_request_controls.py::test_repeated_identical_calls_trip_loop_breaker tests/control_plane/test_request_controls.py::test_fake_redis_isolation_of_namespaces -v
```

Expected: PASS.

- [ ] **Step 6: Commit duplicate collapse and semantic loop breaking**

Run:

```bash
git add src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
git commit -m "feat: collapse duplicate provider tool calls"
```

### Task 4: In-Flight Coalescing

**Files:**
- Modify: `tests/control_plane/test_request_controls.py`
- Modify: `src/control_plane/request_controls.py`

- [ ] **Step 1: Write the failing coalescing test**

Add this test after `test_guarded_call_collapses_duplicate_completed_calls`:

```python
@pytest.mark.asyncio
async def test_guarded_call_coalesces_in_flight_duplicate_calls(fake_controls):
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"job_id": "job-1", "status": "processing"}

    first_task = asyncio.create_task(
        fake_controls.guarded_call(
            connection_id="connection-1",
            tool_name="execute_shipments",
            rate_limit_class="purchase",
            arguments={"approval_request_ref": "apr-1"},
            max_result_bytes=1024,
            call=handler,
        )
    )
    await started.wait()

    second_task = asyncio.create_task(
        fake_controls.guarded_call(
            connection_id="connection-1",
            tool_name="execute_shipments",
            rate_limit_class="purchase",
            arguments={"approval_request_ref": "apr-1"},
            max_result_bytes=1024,
            call=handler,
        )
    )
    await asyncio.sleep(0)
    release.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert calls == 1
    assert {first.source, second.source} == {"handler", "coalesced"}
    assert first.result == second.result == {"job_id": "job-1", "status": "processing"}
    assert first.arguments_hash == second.arguments_hash
```

- [ ] **Step 2: Run the coalescing test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_guarded_call_coalesces_in_flight_duplicate_calls -v
```

Expected: FAIL because both calls enter the handler and `calls == 2`.

- [ ] **Step 3: Add Redis in-flight markers and coalescing**

Update the imports in `src/control_plane/request_controls.py`:

```python
import asyncio
import secrets
```

Add these constants after `DUPLICATE_RESULT_TTL_SECONDS`:

```python
IN_FLIGHT_TTL_SECONDS = 30
IN_FLIGHT_WAIT_TIMEOUT_SECONDS = 25
IN_FLIGHT_POLL_INTERVAL_SECONDS = 0.05

PROCESSING_UNKNOWN_MESSAGE = (
    "A matching tool call is already in progress and did not finish within "
    "ShipAgent's provider sync window. Wait before trying again."
)
```

Add these helper functions after `_duplicate_result_key(...)`:

```python
def _in_flight_key(
    connection_id: str,
    tool_name: str,
    arguments_hash: str,
) -> str:
    return f"sa:guard:inflight:{connection_id}:{tool_name}:{arguments_hash}"


def processing_unknown_envelope() -> dict[str, object]:
    return provider_safe_error_envelope(
        status="processing_unknown",
        reason="processing_unknown",
        terminal=False,
        message=PROCESSING_UNKNOWN_MESSAGE,
    )
```

Replace `guarded_call(...)` inside `RequestControls` with:

```python
    async def guarded_call(
        self,
        *,
        connection_id: str,
        tool_name: str,
        rate_limit_class: str,
        arguments: Mapping[str, object],
        max_result_bytes: int,
        call: Callable[[], Awaitable[dict[str, object]] | dict[str, object]],
    ) -> GuardedCallResult:
        arguments_hash = canonical_input_hash(arguments)
        await self._require_rate_limit(
            connection_id=connection_id,
            rate_limit_class=rate_limit_class,
        )

        token = secrets.token_urlsafe(16)
        claimed = await self._claim_in_flight(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            token=token,
        )
        if not claimed:
            coalesced = await self._wait_for_cached_result(
                connection_id=connection_id,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
            )
            if coalesced is not None:
                return GuardedCallResult(
                    result=coalesced,
                    arguments_hash=arguments_hash,
                    source="coalesced",
                )
            return GuardedCallResult(
                result=processing_unknown_envelope(),
                arguments_hash=arguments_hash,
                source="coalesced_timeout",
            )

        try:
            return await self._run_claimed_guarded_call(
                connection_id=connection_id,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
                max_result_bytes=max_result_bytes,
                call=call,
            )
        finally:
            await self._release_in_flight(
                connection_id=connection_id,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
                token=token,
            )
```

Add these methods inside `RequestControls` after `guarded_call(...)`:

```python
    async def _run_claimed_guarded_call(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
        max_result_bytes: int,
        call: Callable[[], Awaitable[dict[str, object]] | dict[str, object]],
    ) -> GuardedCallResult:
        attempt_count = await self._increment_semantic_attempt(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )
        if attempt_count > LOOP_DETECTION_LIMIT:
            return GuardedCallResult(
                result=repeated_tool_call_envelope(),
                arguments_hash=arguments_hash,
                source="terminal_envelope",
            )

        cached = await self._load_cached_result(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )
        if cached is not None:
            return GuardedCallResult(
                result=cached,
                arguments_hash=arguments_hash,
                source="duplicate",
            )

        result = call()
        if inspect.isawaitable(result):
            result = await result
        capped_result = enforce_max_result_bytes(
            result,
            max_result_bytes=max_result_bytes,
        )
        await self._store_cached_result(
            connection_id=connection_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            result=capped_result,
        )
        return GuardedCallResult(
            result=capped_result,
            arguments_hash=arguments_hash,
            source=(
                "terminal_envelope"
                if capped_result.get("terminal") is True
                else "handler"
            ),
        )

    async def _claim_in_flight(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
        token: str,
    ) -> bool:
        return bool(
            await self.redis.set(
                _in_flight_key(connection_id, tool_name, arguments_hash),
                token,
                ex=IN_FLIGHT_TTL_SECONDS,
                nx=True,
            )
        )

    async def _release_in_flight(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
        token: str,
    ) -> None:
        key = _in_flight_key(connection_id, tool_name, arguments_hash)
        current = await self.redis.get(key)
        if current is not None and _decode_redis_value(current) == token:
            await self.redis.delete(key)

    async def _wait_for_cached_result(
        self,
        *,
        connection_id: str,
        tool_name: str,
        arguments_hash: str,
    ) -> dict[str, object] | None:
        deadline = time.monotonic() + IN_FLIGHT_WAIT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            cached = await self._load_cached_result(
                connection_id=connection_id,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
            )
            if cached is not None:
                return cached
            await asyncio.sleep(IN_FLIGHT_POLL_INTERVAL_SECONDS)
        return None
```

- [ ] **Step 4: Run the coalescing test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_guarded_call_coalesces_in_flight_duplicate_calls -v
```

Expected: PASS.

- [ ] **Step 5: Run duplicate and loop tests again**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_guarded_call_collapses_duplicate_completed_calls tests/control_plane/test_request_controls.py::test_guarded_call_returns_repeated_tool_call_after_duplicate_threshold -v
```

Expected: PASS.

- [ ] **Step 6: Commit in-flight coalescing**

Run:

```bash
git add src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
git commit -m "feat: coalesce in-flight provider tool calls"
```

### Task 5: Guarded Result Cap and Backward-Compatible Loop Errors

**Files:**
- Modify: `tests/control_plane/test_request_controls.py`
- Modify: `src/control_plane/request_controls.py`

- [ ] **Step 1: Write result-cap and compatibility tests**

Add these tests after `test_guarded_call_returns_repeated_tool_call_after_duplicate_threshold`:

```python
@pytest.mark.asyncio
async def test_guarded_call_applies_result_cap_before_caching(fake_controls):
    calls = 0

    async def handler():
        nonlocal calls
        calls += 1
        return {"job_id": "job-1", "payload": "x" * 2048}

    first = await fake_controls.guarded_call(
        connection_id="connection-1",
        tool_name="get_job_status",
        rate_limit_class="read",
        arguments={"job_id": "job-1"},
        max_result_bytes=256,
        call=handler,
    )
    second = await fake_controls.guarded_call(
        connection_id="connection-1",
        tool_name="get_job_status",
        rate_limit_class="read",
        arguments={"job_id": "job-1"},
        max_result_bytes=256,
        call=handler,
    )

    assert calls == 1
    assert first.source == "terminal_envelope"
    assert second.source == "duplicate"
    assert first.result == {
        "status": "blocked",
        "reason": "result_too_large",
        "terminal": True,
        "message": (
            "The tool result exceeded ShipAgent's provider result size limit. "
            "Do not retry the same call. Ask the user to narrow the request "
            "or open ShipAgent for details."
        ),
        "max_result_bytes": 256,
    }
    assert second.result == first.result


@pytest.mark.asyncio
async def test_require_allowed_loop_error_carries_terminal_envelope(fake_controls):
    for _ in range(3):
        await fake_controls.require_allowed(
            connection_id="connection-1",
            tool_name="get_job_status",
            rate_limit_class="read",
            arguments_hash="same-hash",
        )

    with pytest.raises(RequestControlError) as exc:
        await fake_controls.require_allowed(
            connection_id="connection-1",
            tool_name="get_job_status",
            rate_limit_class="read",
            arguments_hash="same-hash",
        )

    assert exc.value.code == "provider_loop_detected"
    assert exc.value.envelope == repeated_tool_call_envelope()
```

- [ ] **Step 2: Run the new tests**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py::test_guarded_call_applies_result_cap_before_caching tests/control_plane/test_request_controls.py::test_require_allowed_loop_error_carries_terminal_envelope -v
```

Expected: PASS if Tasks 2 through 4 were implemented exactly. If `test_require_allowed_loop_error_carries_terminal_envelope` fails with `AttributeError: 'RequestControlError' object has no attribute 'envelope'`, re-apply the `RequestControlError` replacement from Task 3 Step 3.

- [ ] **Step 3: Run the full request-controls test module**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_request_controls.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit result-cap integration**

Run:

```bash
git add src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
git commit -m "feat: cap provider guard results"
```

### Task 6: Cross-Boundary Verification

**Files:**
- Verify only: `src/control_plane/request_controls.py`
- Verify only: `tests/control_plane/test_request_controls.py`
- Verify only: `tests/hosted/test_hosted_mcp_registry.py`
- Verify only: `tests/control_plane/test_result_projection.py`
- Verify only: `tests/services/conversation_runtime/test_policy.py`

- [ ] **Step 1: Verify current hosted MCP compatibility**

Run:

```bash
.venv/bin/python -m pytest tests/hosted/test_hosted_mcp_registry.py::test_hosted_mcp_handler_applies_request_controls_before_invocation tests/hosted/test_hosted_mcp_registry.py::test_hosted_mcp_handler_translates_request_control_deny -v
```

Expected: PASS. This confirms the existing `require_allowed(...)` adapter path still works until Plan 1/7 wires `guarded_call(...)` into the final provider endpoint.

- [ ] **Step 2: Verify projection and runtime policy boundaries**

Run:

```bash
.venv/bin/python -m pytest tests/control_plane/test_result_projection.py tests/services/conversation_runtime/test_policy.py -v
```

Expected: PASS. This confirms Plan 5 did not regress Plan 6's projection file or the provider-neutral runtime policy gates.

- [ ] **Step 3: Run lint for touched files**

Run:

```bash
.venv/bin/python -m ruff check src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
```

Expected: PASS.

- [ ] **Step 4: Run format check for touched files**

Run:

```bash
.venv/bin/python -m ruff format --check src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
```

Expected: PASS. If formatting fails, run:

```bash
.venv/bin/python -m ruff format src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
```

Then rerun:

```bash
.venv/bin/python -m ruff format --check src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
```

Expected: PASS.

- [ ] **Step 5: Commit verification formatting if needed**

Run only if Step 4 changed formatting:

```bash
git add src/control_plane/request_controls.py tests/control_plane/test_request_controls.py
git commit -m "style: format ingress guard tests"
```

## Dependencies Consumed

- Plan 1 provides endpoint placement and the final public provider ingress path that can call `RequestControls.guarded_call(...)`.
- Existing registry contracts provide `rate_limit_class` and `max_result_bytes`; this plan does not change registry schemas.
- Existing `redis.asyncio` configuration in `src/control_plane/app.py` provides the Redis client.
- Existing hosted MCP compatibility path continues to use `hash_arguments(...)` and `require_allowed(...)`.

## Dependencies Provided

- `canonical_input_hash(...)` and `hash_arguments(...)` compatibility alias for Plan 2 invocation envelopes and Plan 7 idempotency-adjacent guard keys.
- `GuardedCallResult` and `RequestControls.guarded_call(...)` for Plan 1/7 endpoint wiring.
- Provider-safe terminal `repeated_tool_call` envelope for Plan 10 adversarial loop-retry prompts.
- Guard-layer `result_too_large` envelope and byte-cap helper for Plan 6/7 output schemas and projection integration.
- Short-lived Redis duplicate and in-flight keys that collapse provider retries before relay dispatch.

## Overlap Risks

- Plan 2 owns relay invocation lifecycle, accepted/retry semantics, and recovery after dispatch. Plan 5 must stop at provider ingress before relay dispatch; do not use guard duplicate collapse as a substitute for relay accepted-state recovery.
- Plan 6 owns output profiles, origin-based redaction, descriptor visibility, and schema changes. Plan 5 may return safe guard envelopes and enforce byte size, but must not format Claude markdown, OpenAI widget metadata, or origin-redacted shipment payloads.
- Plan 7 owns approval requests, execution grants, exact-preview validation, shipment idempotency, and label-download authorization. Plan 5 may coalesce identical `execute_shipments` ingress calls, but must not mint, validate, consume, or cache approval grants.
- Plan 4 may later centralize Redis TTL constants and key patterns. This plan keeps guard-only keys private in `request_controls.py` to avoid editing `redis_keys.py` during parallel work.

## Self-Review Notes

- Spec coverage: canonical input hashing is Task 1; provider-safe terminal envelopes and result-size caps are Task 2 and Task 5; duplicate collapse and semantic loop breaker are Task 3; in-flight coalescing is Task 4; testing strategy and cross-boundary checks are Task 6.
- Type consistency: `GuardedCallResult.source` values are defined once and used consistently in tests.
- Scope control: no production source outside `src/control_plane/request_controls.py` is assigned to Plan 5.
