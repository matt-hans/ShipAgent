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
  building, credentials, settings, contacts, audit, labels, write-back, and MCP
  client gateways.
- `src/orchestrator/agent/` owns the Claude SDK runtime adapter, dynamic system
  prompt, mode-aware tool registration, hooks, and deterministic tool handlers.
- `src/mcp/` owns internal MCP connectivity modules for data sources and
  external commerce platforms.
- `src/carriers/` and carrier services are integration boundaries. UPS access
  goes through MCP/client abstractions, not direct ad hoc SDK calls.
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
- Keep FastAPI request/response models in `src/api/schemas*.py` unless a domain
  model already exists elsewhere.
- Prefer Pydantic/SQLAlchemy models and typed service methods over loose dicts
  at service boundaries.
- Use `gateway_provider.py` for data/external-source gateways. Avoid creating
  duplicate long-lived MCP clients in routes or tools.
- When adding a workflow tool, add tests for tool registration, mode exposure,
  hooks/approval behavior, and the underlying service.
- When adding or changing provider exports, edit the canonical registry source,
  run `python scripts/generate_provider_artifacts.py`, and verify
  `tests/registry/test_artifact_drift.py`.
- Keep logging redaction-aware. Do not log credentials, tokens, customer payloads,
  raw labels, or full row data.

## Tests

Use the narrowest relevant test first:

```bash
pytest tests/api/test_<area>.py -v
pytest tests/services/test_<service>.py -v
pytest tests/orchestrator/agent/ -v -k "<tool_or_behavior>"
pytest tests/mcp/data_source/ -v -k "<adapter_or_tool>"
pytest tests/registry/test_artifact_drift.py -v
```

Before broad completion checks:

```bash
pytest -k "not stream and not sse and not progress"
ruff check src/ tests/
ruff format src/ tests/
```

Use full `pytest` when the change touches shared workflow behavior,
serialization contracts, persistence, registry exports, or cross-layer flows.

## Local Runtime

- Install backend deps into the project virtualenv:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

- Start the backend through the script so `.env`, `AGENT_MODEL`, MCP subprocesses,
  and the single-worker setting are handled consistently:

```bash
./scripts/start-backend.sh
```

- The script defaults to `SHIPAGENT_PORT=8080`. The frontend expects API routes
  under `/api/v1`; Tauri resolves a sidecar port dynamically.
