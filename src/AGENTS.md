# Backend Agent Guide

## Scope

This file applies to `src/` and backend-facing tests in `tests/`. It covers the
FastAPI API, orchestration agent, MCP clients/servers, workflow services,
registry exports, and CLI.

## Layering

- `src/api/` is the HTTP adapter. Routes validate input, call services, translate
  errors, stream SSE events, and return response schemas. Do not put shipping
  workflow decisions in routes.
- `src/services/` owns business logic: job lifecycle, batch execution, payload
  building, credentials, settings, contacts, audit, labels, write-back, MCP
  client gateways, and provider-neutral conversation ownership.
- `src/services/conversation_runtime/` owns provider-neutral model/runtime
  contracts, OpenAI/Gemini adapters, fake-provider tests, tool catalog projection,
  policy gates, local tool dispatch, safe tool-result projection, and runtime
  session loops.
- `src/orchestrator/agent/` owns the Claude Agent SDK compatibility adapter,
  dynamic system prompt, mode-aware tool registration, hooks, and deterministic
  tool handlers used by Claude and by neutral workflow wrappers.
- `src/mcp/` owns internal MCP connectivity modules for data sources and
  external commerce platforms.
- `src/carriers/` and carrier services are integration boundaries. UPS access
  goes through MCP/client abstractions, not direct ad hoc SDK calls.
- `src/hosted/ups_boundary/` defines the hosted UPS MCP boundary contract,
  readiness checks, fixtures, and validators. Keep it independent from model
  provider SDKs.
- `src/registry/`, `src/provider_adapters/`, and `generated/provider_artifacts/`
  define the canonical provider-neutral workflow/tool backbone and projections.
- `src/cli/` should share services and conversation handling with the API rather
  than forking behavior.

## Non-Negotiable Backend Invariants

- No business logic in API routes.
- No direct UPS calls outside the established MCP/client gateway.
- No provider-specific shipping logic in model SDK or provider projection code.
- No shipment execution or pickup scheduling without preview/confirmation.
- No row data in LLM prompts. Generate filters/mappings; apply them in code.
- No raw UPS MCP tool exposure in provider-neutral runtimes. Use orchestrator
  workflow wrappers and `UPSMCPClient` gateway methods instead.
- No global mutable MCP client state outside the gateway provider patterns with
  async locking.
- No mode leakage between batch and interactive agent sessions.
- No scattered carrier/platform constants. Add canonical modules and import them.
- All user-visible or API-visible errors must be sanitized and fit the existing
  error registry/error translation patterns.

## Implementation Guidance

- Reuse the canonical conversation path in `src/services/conversation_handler.py`
  for agent message processing. Keep history write ownership explicit.
- Use `AgentSessionManager` for per-session agent lifecycle. Stop and remove
  sessions when temporary flows finish.
- For OpenAI/Gemini/fake-provider behavior, extend
  `src/services/conversation_runtime/` rather than the Claude adapter. Preserve
  provider output items needed for continuation, especially OpenAI reasoning and
  function-call items.
- Keep FastAPI request/response models in `src/api/schemas*.py` unless a domain
  model already exists elsewhere.
- Prefer Pydantic/SQLAlchemy models and typed service methods over loose dicts
  at service boundaries.
- Use `gateway_provider.py` for data/external-source gateways. Avoid creating
  duplicate long-lived MCP clients in routes or tools.
- When adding a workflow tool, add tests for tool registration, mode exposure,
  hooks/approval behavior, and the underlying service.
- When adding a provider-neutral workflow tool, update the runtime tool catalog,
  policy gates for unsafe direct calls, dispatcher projection/sanitization, and
  provider contract tests under `tests/services/conversation_runtime/`.
- When adding UPS capabilities, route through `UPSMCPClient` or the established
  gateway. Keep model-visible tool results actionable but sanitized: no raw
  request bodies, labels, documents, credentials, row samples, or customer data
  unless the workflow explicitly allows that data to be shown.
- When adding or changing provider exports, edit the canonical registry source,
  run `python scripts/generate_provider_artifacts.py`, and verify
  `tests/registry/test_artifact_drift.py`.
- Keep logging redaction-aware. Do not log credentials, tokens, customer payloads,
  raw labels, or full row data.

## Tests

Use the narrowest relevant test first:

```bash
.venv/bin/python -m pytest tests/api/test_<area>.py -v
.venv/bin/python -m pytest tests/services/test_<service>.py -v
.venv/bin/python -m pytest tests/services/conversation_runtime/ -v -k "<provider_or_tool>"
.venv/bin/python -m pytest tests/orchestrator/agent/ -v -k "<tool_or_behavior>"
.venv/bin/python -m pytest tests/mcp/data_source/ -v -k "<adapter_or_tool>"
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Before broad completion checks:

```bash
.venv/bin/python -m pytest -k "not stream and not sse and not progress"
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m ruff format src/ tests/
```

Use full `pytest` when the change touches shared workflow behavior,
serialization contracts, persistence, registry exports, provider adapters, or
cross-layer flows.

## Local Runtime

- Install backend deps into the project virtualenv:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

- Start the backend through the script so `.env`, `AGENT_MODEL`, model SDK
  dependency probes, MCP subprocesses, and the single-worker setting are handled
  consistently:

```bash
./scripts/start-backend.sh
```

- The script defaults to `SHIPAGENT_PORT=8080`. The frontend expects API routes
  under `/api/v1`; Tauri resolves a sidecar port dynamically.
- `AGENT_MODEL` examples: `claude-haiku-4-5-20251001`, `openai:gpt-5-mini`,
  `gemini:gemini-2.5-flash`. Optional defaults for `openai:default` and
  `gemini:default` come from `OPENAI_MODEL` and `GEMINI_MODEL`.
