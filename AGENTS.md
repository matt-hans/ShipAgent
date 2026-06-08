# ShipAgent Agent Guide

## Scope

This file applies to the whole repository. More specific instructions live in:

- `src/AGENTS.md` for Python backend, orchestration, MCP, registry, and CLI work.
- `shipagent-frontend/AGENTS.md` for Angular/Nx/Native Federation work.

Follow the most specific applicable `AGENTS.md` first, then this file.

## Product Direction

ShipAgent is an AI-native shipping automation platform. Users describe shipping
work in natural language; deterministic services import data, map columns,
preview shipments, execute after confirmation, track progress, and preserve an
audit trail.

The core architectural rule is: provider/runtime adapters expose a shared
workflow and tool backbone. They do not own shipping business logic.

## Repo Map

- `src/` - Python backend: FastAPI, orchestration agent, workflow services, MCP
  servers/clients, registry projections, CLI.
- `src/services/conversation_runtime/` - Provider-neutral conversation runtime:
  normalized message/tool contracts, OpenAI/Gemini adapters, fake-provider tests,
  local tool dispatch, policy gates, and provider-safe result projection.
- `src/hosted/ups_boundary/` - Hosted UPS MCP boundary contract, fixtures,
  readiness reporting, and validator helpers.
- `tests/` - Pytest suite mirroring backend package boundaries.
- `shipagent-frontend/` - Angular 21 + Nx + Native Federation frontend. This is
  the active frontend path; do not use stale `frontend/` paths from older docs.
- `src-tauri/` - Tauri v2 desktop wrapper that launches the Python sidecar and
  hosts the Angular shell.
- `generated/provider_artifacts/` - Generated provider exports from the
  canonical registry. Regenerate rather than hand-edit.
- `scripts/` - Local dev, packaging, versioning, provider artifact, and Docker
  helper scripts.

## Architecture Invariants

- Keep API routes thin. HTTP parsing, status codes, and response shaping belong
  in routes; decisions and shipping behavior belong in services/workflow tools.
- The LLM is a configuration engine, not a data pipe. It can produce filters,
  mappings, and plans; deterministic code applies them to row data.
- Do not send row-level shipping data through model prompts.
- All shipment creation, pickup scheduling, voiding, or other money/state
  changing operations require preview and explicit confirmation first.
- Do not call UPS or external commerce platforms directly from unrelated layers.
  Use the MCP/client gateway and service abstractions already in `src/`.
- Do not put provider-specific shipping behavior in OpenAI/Anthropic/Gemini
  adapter code. Add or change canonical workflow tools/services instead.
- Keep carrier/platform constants, service codes, field limits, defaults, and
  enums centralized in canonical modules. Avoid magic strings scattered through
  routes or components.
- Preserve auditability. New decisions, confirmations, tool calls, or execution
  paths should have tests and redaction-aware logging where appropriate.
- Conversation providers are selected with `AGENT_MODEL`: Claude-style model names
  use the Claude Agent SDK compatibility path; `openai:*` and `gemini:*` use the
  provider-neutral runtime. Keep all providers on shared workflow tools and
  provider-safe result projections.
- Raw UPS MCP calls are not provider-neutral behavior. Expose UPS capabilities
  through workflow wrappers such as `rate_shipment`, `validate_address`,
  `get_time_in_transit`, tracking, pickup, landed-cost, and preview/execute tools.

## Common Commands

Backend setup and dev:

```bash
.venv/bin/python -m pip install -e '.[dev]'
./scripts/start-backend.sh
```

Backend validation:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest -k "not stream and not sse and not progress"
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m ruff format src/ tests/
```

Model runtime examples:

```bash
AGENT_MODEL=claude-haiku-4-5-20251001 ./scripts/start-backend.sh
AGENT_MODEL=openai:gpt-5-mini ./scripts/start-backend.sh
AGENT_MODEL=gemini:gemini-2.5-flash ./scripts/start-backend.sh
```

Frontend setup and validation:

```bash
cd shipagent-frontend
npm ci
npx nx serve shell
npx nx run-many -t typecheck --all
npx nx run-many -t lint --all
npx nx run-many -t test --all
npx nx run-many -t build --all --configuration=production
./scripts/link-remotes.sh
```

Provider registry artifacts:

```bash
.venv/bin/python scripts/generate_provider_artifacts.py
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -v
```

Packaging:

```bash
./scripts/bundle_backend.sh
cd src-tauri && cargo tauri build
```

## Working Rules

- Prefer targeted tests while iterating, then broaden validation based on the
  risk and blast radius.
- When changing backend contracts consumed by the frontend, update shared
  frontend types in `shipagent-frontend/libs/shared/types/src/` and verify the
  affected Nx projects.
- When changing registry/tool definitions, regenerate provider artifacts and run
  the artifact drift test.
- Keep generated files out of manual edits unless the generating source changed.
- Do not commit secrets, real labels, customer data, API keys, `.env`, local DBs,
  cache directories, or dependency folders.
- Use `package-lock.json` and npm for frontend dependencies.
- Use the project virtualenv for backend commands so MCP subprocesses share the
  same dependencies as the API.
