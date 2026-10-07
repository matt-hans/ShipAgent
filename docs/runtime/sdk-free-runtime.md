# SDK-free conversation runtime

ShipAgent owns the conversation loop, tool dispatch, policy, history, interruption
and confirmation boundaries for Anthropic, OpenAI and Gemini. API, headless CLI
and the desktop Python sidecar use the same factory and conversation service.
The Claude Agent SDK and its CLI/subprocess framework are no longer installed
or used. Thin provider HTTP clients remain inside the protocol adapters.

## Configuration and migration

Persisted Settings → Agent model takes precedence for API and CLI conversations.
When that setting is unset, `AGENT_MODEL` takes precedence over the legacy
`ANTHROPIC_MODEL` environment variable. With neither set, the model is
`claude-haiku-4-5-20251001`.

| Model example | Provider key | Runtime |
| --- | --- | --- |
| `claude-haiku-4-5-20251001` | `ANTHROPIC_API_KEY` | shared Anthropic Messages |
| `anthropic:claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | shared Anthropic Messages |
| `anthropic:default` | `ANTHROPIC_API_KEY` | shared Anthropic default |
| `openai:gpt-5-mini` | `OPENAI_API_KEY` | shared OpenAI Responses |
| `gemini:gemini-2.5-flash` | `GEMINI_API_KEY` | shared Gemini |

`SHIPAGENT_AGENT_RUNTIME=auto` (or unset/empty) selects the adapter from the model.
Explicit `anthropic_messages`, `anthropic-messages`, `openai` and
`gemini` selectors require a matching provider model. `claude`, `claude_sdk` and `anthropic`
are deprecated Anthropic aliases and log a deprecation warning; neither starts
an SDK. `fake` remains the deterministic development/test runtime.
Unknown runtime selectors, unknown unprefixed models and cross-provider
mismatches fail closed, with no provider fallback. Missing matching API keys
produce an actionable error. Short Claude aliases such as `haiku` and `sonnet`
are unsupported; use a full model ID. `ANTHROPIC_MODEL` is a supported legacy
configuration key, not an invitation to use those short model IDs.

Provider defaults `OPENAI_MODEL` and `GEMINI_MODEL` are used for their
`provider:default` selections. Model/runtime configuration is snapshotted at a
safe turn boundary; changing it recreates the next session runtime with neutral
history. Existing confirmations are never reinterpreted as fresh authority.

## Start locally

```bash
uv sync --locked --extra dev
cp .env.example .env
# Set only the provider/integration credentials you need in .env or Settings.
./scripts/start-backend.sh
.venv/bin/shipagent version
.venv/bin/shipagent --standalone interact
```

The existing pip editable setup also works: `.venv/bin/python -m pip install -e
'.[dev]'`. Use the project interpreter for backend and MCP subprocesses.
The launcher checks `uvicorn`, `httpx`, `openai` and `google.genai`; no Claude
agent framework is probed. `shipagent version` reports the shared runtime.
Desktop model settings use the same backend setting and selectors. PyInstaller
collects the supported protocol clients without the removed framework.

The frontend uses local Nx task execution and local caching by default. After
`npm ci`, `npm exec nx ...` does not require Nx Cloud credentials or a downloaded
cloud runner. Explicit operator-provided cloud configuration remains an Nx
choice, rather than a project prerequisite.

Local orchestration does not imply offline model inference: the configured
Anthropic/OpenAI/Gemini endpoints require connectivity and their provider key.
No local-model endpoint or offline inference capability is claimed here.
Carrier and commerce integrations likewise require their configured services.
Cloud relay/connector deployment is a separate product path, not needed for the
local conversation runtime.

## Verification and preserved contracts

`tests/test_claude_sdk_optional.py` (historical filename) enforces no SDK
production import, wrapper or dependency exemption. The SDK-free entry-point
suite in `tests/packaging/test_sdk_free_runtime.py` creates a fresh interpreter
view with the SDK module and distribution absent and no `.pth` path injection.
It exercises real API startup/SSE/persistence, persisted model settings, CLI
workflow dispatch the actual development launcher and desktop source-sidecar server startup,
and the desktop CLI entry point over synthetic transport
and gateway seams. This fast test reuses installed dependencies; it does not
substitute for #41's clean installation and frozen desktop release gate.

The [retirement map](sdk-removal-coverage.md) inventories removed SDK-specific
tests and their neutral replacements. Shared acceptance covers previews,
trusted one-shot confirmations, raw-carrier/SQL denials, privacy projections,
resume, cancellation and uncertain effect accounting. HTTP/SSE and persisted
artifact contracts remain unchanged; no database migration is required.
