# User-controlled headless operator workflow

Status: initial operator guide for [milestone #81](https://github.com/matt-hans/ShipAgent/issues/81),
reviewed against source on 2026-10-09. This is preparation for the chosen
always-on, account-dedicated target. **There is not yet a qualified production
headless target installation or a working ChatGPT/Claude onboarding procedure.**
No Mac application is required. Architecture approval does not authorize a
server, endpoint, account setup, credentials, spending or live shipping.

## Know which version you are operating

This guide describes merged source through
`47c3e21a0b45c7febe7b0e36a49613adf786f7ba` after PRs #85–89. Record the actual
installed commit and configuration; neither a local branch nor this document
qualifies a production deployment.

| Checkpoint | Available evidence and limit |
| --- | --- |
| [Lifecycle/cancellation #85](https://github.com/matt-hans/ShipAgent/pull/85) | Durable target-local source-free submit/read/cancel, genuine terminal-stream proof, process-crash recovery, fencing and bounded cleanup. Contracts remain dormant in production exports. |
| [OAuth/MCP #86](https://github.com/matt-hans/ShipAgent/pull/86) | Exact `/mcp` resource/audience, public scopes and per-request identity checks, with synthetic signed-token/HTTP qualification. Actual-client OAuth and production relink remain open. |
| [Acceptance harness #87](https://github.com/matt-hans/ShipAgent/pull/87) | Reproducible bounded loopback MCP and cleanup evidence. Scripted models and generic MCP clients do not prove ChatGPT/Claude compatibility. |
| [Clarification/continuation #88](https://github.com/matt-hans/ShipAgent/pull/88) | Fixed safe questions, exact waiting-run/revision continuation and quiescent cancellation under an injected trusted epoch authority. No production epoch resolver or shipping approval is supplied. |
| [CSV primitive #89](https://github.com/matt-hans/ShipAgent/pull/89) | Strict bounded in-memory CSV parsing with exact private strings and counts-only projection. It supplies no upload route, storage, ownership, mapping or runtime admission. |
| Other work in progress | Source ingress and headless onboarding are not qualified operator capabilities. No runnable enrollment ceremony, receipt installation or supported secret-provisioning command is established here. |

The historical tracer branch `91f499a` predates terminal-stream and recovery
repairs. Use the merged repaired source, not that branch as a release candidate.

Use [parent #75](https://github.com/matt-hans/ShipAgent/issues/75) and exactly its
six milestones: [architecture #76](https://github.com/matt-hans/ShipAgent/issues/76),
[task lifecycle #77](https://github.com/matt-hans/ShipAgent/issues/77),
[actual-client authentication #78](https://github.com/matt-hans/ShipAgent/issues/78),
[sources/preview #79](https://github.com/matt-hans/ShipAgent/issues/79),
[approval/execution/artifacts #80](https://github.com/matt-hans/ShipAgent/issues/80)
and [operations/release #81](https://github.com/matt-hans/ShipAgent/issues/81).
None is completed by this guide. The [authority packet](architecture-authority.md)
and [ADR 0009](../adr/0009-headless-full-agent-authority.md) define the chosen profile.

## Prerequisites and ownership

- The user operates an always-available, dedicated target process and its storage
  for one account. The user owns uptime, updates, recovery, access and support
  decisions. A shared multi-account local API is not an accepted substitute.
- Source operation needs Python 3.12+ and the project dependencies from
  [pyproject.toml](../../pyproject.toml). Use the project virtual environment for
  the CLI and gateway children. Frontend/desktop packaging is not a headless
  prerequisite. The existing install/runtime instructions are in the
  [SDK-free runtime guide](../runtime/sdk-free-runtime.md).
- ShipAgent uses its own model access. A ChatGPT or Claude subscription does not
  supply the backend's API capacity. The operator must separately approve the
  selected provider, credentials and model budget; carrier/commerce access and
  costs are separate approvals. Missing matching credentials must not trigger
  a fallback to another provider or another account.
- For existing local API/CLI conversations, persisted Agent model Settings take
  precedence over `AGENT_MODEL`, then legacy `ANTHROPIC_MODEL`; the fallback is
  `claude-haiku-4-5-20251001`. `SHIPAGENT_AGENT_RUNTIME=auto` selects the adapter.
  An explicit selector must match the model. `anthropic:*`/full Claude model IDs
  use `ANTHROPIC_API_KEY`, `openai:*` uses `OPENAI_API_KEY`, and `gemini:*` uses
  `GEMINI_API_KEY`. These are variable names, not credential-entry instructions.
  Source-free target tests pass explicit trusted model configuration and use
  scripted providers; they do not inherit local Settings or prove live access.
- The chosen headless profile requires an operator-managed encrypted persistent
  volume, dedicated unprivileged service identity, owner-only data/secrets roots
  and narrowly supplied credentials. These are prerequisites awaiting approved
  setup and qualification, not protections provided by running the local daemon.
  The legacy API loads keyring/environment credentials; it is not the approved
  headless secret-storage boundary. Never put secrets or customer rows in chat,
  public configuration, logs or a release report.

### Inventory local state before any operation

Keep a private inventory of the account/target identity, exact source revision,
configuration, model selection, data paths, backup ownership and retention. Use
placeholder names such as `operator-config.yaml` and `synthetic-job-id` in shared
instructions; do not publish real account identifiers or credentials.

| State | Existing location/configuration | Operator consequence |
| --- | --- | --- |
| Local jobs, Settings, conversation/audit records and connection records | `DATABASE_URL`, then `SHIPAGENT_DB_PATH`, then `<data-dir>/shipagent.db` | This is the legacy local store, not the separate durable Agent Run store. |
| Default data root and uploads | `SHIPAGENT_DATA_DIR`; otherwise source checkout root in development. Uploads use `<data-dir>/uploads`. | A data-root override does not override an explicit database URL or every other path. Inventory all overrides. |
| Labels and audit mirror | Labels normally use `<data-dir>/labels`; integrations can use `UPS_LABELS_OUTPUT_DIR`. Decision audit JSONL uses `AGENT_AUDIT_JSONL_PATH`. | Verify actual destinations. The JSONL mirror is best effort; database audit records are canonical. |
| CLI process bookkeeping | `daemon.pid_file` in the selected YAML; default `~/.shipagent/daemon.pid` | Use the same config and OS identity for start/status/stop. A PID file is not durable task state. |
| Durable Agent Runs | Explicit account/exact-target-bound SQLite file supplied by the target-side service/test | There is no production CLI path/configuration in this baseline. Initialization is explicit; missing/replaced storage must not be silently recreated. |
| Credentials and recovery material | Existing local environment/keyring/encryption-key mechanisms; separately gated headless storage profile | A database backup alone does not preserve all credentials or their decryption material. Protect and recover them through separately approved procedures. |

Source references: [path resolution](../../src/utils/paths.py),
[local DB selection](../../src/db/connection.py),
[CLI configuration](../../src/cli/config.py),
[decision audit](../../src/services/decision_audit_service.py) and
[tracer storage contract](agent-run-tracer.md#local-storage-profile-and-qualification-boundary).

## Existing local service: inspect, start, observe, stop

These commands describe the **existing single-worker local/admin service**.
They do not launch the approved remote full-agent target or qualify an always-on
deployment. Only run lifecycle commands after separately authorized local setup,
in an isolated synthetic environment with known storage and no unintended
watch-folder work. Startup can recover prior jobs and process configured folder
backlogs; it is not a read-only inspection operation.

First inspect the installed command surface without starting services:

```sh
.venv/bin/shipagent version
.venv/bin/shipagent --help
.venv/bin/shipagent daemon start --help
.venv/bin/shipagent config validate --config /path/to/operator-config.yaml
```

For an already prepared local configuration, use an explicit loopback host,
port, PID path, empty `watch_folders` and disabled `auto_confirm`. For example,
the non-secret YAML fields are:

```yaml
daemon:
  host: 127.0.0.1
  port: 8080
  workers: 1
  pid_file: /path/to/private-runtime/daemon.pid
  log_level: info
watch_folders: []
auto_confirm:
  enabled: false
```

The paths are placeholders for existing operator-approved locations. Use the
same explicit config for every command; at this baseline no-config daemon
start/status use port 8000 while normal client defaults are 8080. The CLI does
not load the development launcher's `.env` file for you. Recognized
`SHIPAGENT_<SECTION>_<KEY>` environment variables override YAML values, and
`${VAR}` references resolve from that same environment. Inspect effective
settings and any overrides in the actual service environment, including host,
port and PID path; safe-looking YAML alone is not a safety guarantee.

Before the synthetic lifecycle example below, run `config validate` with the
same configuration **and environment** that will launch the service. Its output
must show `Watch folders: 0` and `Auto-confirm: disabled`. Stop if either differs.
`Config is valid` only reports successful validation; it does not mean the
configuration is safe or that startup is read-only.

```sh
# Foreground service, in its own terminal:
.venv/bin/shipagent --config /path/to/operator-config.yaml daemon start

# From another terminal, using the identical config:
.venv/bin/shipagent --config /path/to/operator-config.yaml daemon status
curl --fail --silent --show-error http://127.0.0.1:8080/health
curl --fail --silent --show-error http://127.0.0.1:8080/readyz

# Request graceful shutdown:
.venv/bin/shipagent --config /path/to/operator-config.yaml daemon stop
```

- `daemon start` runs in the foreground; it does not install a service manager,
  boot-time startup, restart supervision or a headless relay worker. One worker
  is required. `scripts/start-backend.sh` is a hot-reload development launcher.
  Existing Docker definitions likewise do not qualify the remote target profile.
- `daemon status` checks PID/process identity and `/health` HTTP success only.
  `/health` is liveness. Inspect the `/readyz` JSON body: missing credentials or
  unhealthy dependencies can return HTTP 200 with `degraded`/`error`; database
  failure returns 503. Detailed diagnostics require the configured local API
  authentication. Neither endpoint proves OAuth, exact-target availability,
  model spend authorization or connector-capability readiness.
- The API writes application logs to stdout; capture them using the chosen
  operator-approved supervisor when that deployment is qualified. YAML
  `log_file`/`log_format` fields do not establish file logging in this daemon
  launcher. For an existing local job, `shipagent --config
  /path/to/operator-config.yaml job logs synthetic-job-id --follow` follows
  progress with reconnect/backoff. It is not an Agent Run event cursor. Keep
  local job detail/audit output private and redact before sharing.
- Stop sends SIGTERM and waits up to ten seconds. Its success message does not
  independently prove the process and all gateway children exited; verify
  exit/listener closure with the supervisor or process tools before restart or
  restore. Normal API shutdown stops watchers and conversation/batch/gateway
  resources. Forced termination is a separate failure case, not a drain claim.
  PID command matching is best effort and falls back to existence-only when
  `ps` fails. Independently verify the intended process/instance before stop,
  especially with a stale PID file or multiple services.

The original command/help inspection used `c391e8c`; this revision rechecks the
existing help/version surface and example configuration against its source
baseline. No service, account, credential setup, model call or carrier call is
run for documentation.

## Synthetic task proof and restart expectations

The [dormant tracer](agent-run-tracer.md) is the current remote-path proof:
tests explicitly wire a dedicated target, disposable real SQLite and a scripted
model into real loopback MCP. They submit a source-free task, read its stable
reference, retry the same request key, and cancel queued/running work. Epoch-bound
tests additionally expose a fixed clarification question, accept only the exact
current waiting run/revision, and cancel its follow-up without changing terminal
history. The epoch authority is a trusted synthetic injection, not a production
link-generation implementation. Production
exports remain status-only; there is no documented flag here to enable dormant
tools. A source-free run has no shipping/source tools and cannot buy a label.

- Identical accepted retries recover the original run and expiry; conflicting
  key reuse is denied. Polling does not launch another model turn.
- Process-crash tests preserve accepted/completed identities. Queued,
  undispatched work may run on explicit service restart; a previously dispatched
  interrupted turn is not automatically replayed. Completed records remain
  readable. Failed completion publication fences further admission.
- Cancellation bounds future work and preserves accepted history; it does not
  void/refund a shipment. Cleanup failure has an explicit unavailable outcome.
- This is process-crash evidence on the test filesystem. It is not power-loss,
  encrypted-volume, backup rollback or restored-purchase qualification. The
  legacy local conversation queue remains process-local; CLI reconnect does
  not make a pending response crash-durable.
- Actual ChatGPT/Claude reconnect, refresh, revocation, clarification and
  target-restart recovery must still be exercised on one qualified candidate.
  An offline/replaced target cannot silently inherit approval or work ownership.

## Backup, restore and recovery boundary

Existing [backup.sh](../../scripts/backup.sh) uses SQLite's backup operation for
the local database and optionally archives `/app/labels`. It applies configured
backup retention by deleting older matching backup files. Existing
[restore.sh](../../scripts/restore.sh) copies a database backup and optionally
replaces `/app/labels`; the service must be stopped. These are limited legacy
utilities, not a qualified full-target recovery procedure. They do not establish
a consistent snapshot across Agent Runs, sources, uploads, credentials, control
plane state and purchase authority. Do not treat a raw copy of a live SQLite
database file as a complete backup, or assume a custom labels path is included.

Before production operation, #81 must approve and test a protected inventory-wide
backup/retention plan and restoration into an isolated environment with external
dispatch disabled. Record original account/target identities, configuration,
store versions and recovery material; reconcile accepted/uncertain effects before
any admission is restored. A restored audit record cannot recreate a grant, and
an old backup must not make a consumed request purchasable again. Preserve the
original evidence and seek operator reconciliation for ambiguous outcomes; do
not resubmit with new keys. No automatic rollback/no-repurchase guarantee is
claimed by the current scripts. Agent Run retention cleanup is not implemented;
the retained-record limit fails admission rather than forgetting old keys.

## Compact release checklist

Existing tests below are evidence locations, not a fresh full-suite pass or
permission to deploy. Record the exact candidate, configuration, command,
outcome and every skip when qualification is performed.

| Operator-observable behavior | Existing evidence | Remaining gate |
| --- | --- | --- |
| CLI commands and single-worker local lifecycle | Help checked for this guide; [daemon tests](../../tests/cli/test_daemon.py), [SDK-free entry-point tests](../../tests/packaging/test_sdk_free_runtime.py) | Supervised always-on target install/start/drain/stop and owned-child cleanup, #77/#81. |
| Correct model/runtime and missing-credential failure | [runtime selection tests](../../tests/services/test_conversation_agent.py), [credential tests](../../tests/services/test_runtime_credentials.py) | Approved provider access, hard token/spend budgets and real model evidence, #77/#81. |
| Liveness versus dependency readiness | [readiness credential tests](../../tests/api/test_readyz_credentials.py) and [API implementation](../../src/api/main.py) | Full auth/store/exact-target/capability readiness and actionable observability, #81. |
| Stable submit/read, duplicate denial and private output | [real MCP tracer tests](../../tests/services/agent_runs/test_mcp_tracer.py) and [clarification/continue tests](../../tests/services/agent_runs/test_mcp_continuation.py) | Production link epochs, useful source/results and actual-client completion, #77–79. |
| Cancel and fence failed cleanup/publication | [MCP cancel tests](../../tests/services/agent_runs/test_mcp_cancellation.py), [publication-fence test](../../tests/services/agent_runs/test_completion_failure_fence.py) | Combined-client revocation/drain and wider failure coverage, #77/#78/#81. |
| Restart preserves identity without charged replay | [process recovery tests](../../tests/services/agent_runs/test_process_recovery.py), [cancel recovery tests](../../tests/services/agent_runs/test_cancellation_process_recovery.py) | Power-loss/storage model, backup/restore/rollback and no repeated purchase, #77/#80/#81. |
| Account-dedicated ownership and persistent state | [Agent Run store tests](../../tests/services/agent_runs/test_store.py); ADR 0009 | Supported headless onboarding/secret storage and whole-target isolation, #77/#81. |
| ChatGPT and Claude OAuth/reconnect/revocation | [OAuth/MCP wire tests](../../tests/control_plane/test_oauth_mcp_wire.py) and [acceptance guide](../acceptance/mcp-clients.md) | Approved temporary HTTPS endpoint, exact canonical resource, issuer/client IDs/callbacks, consent/refresh/revocation, credential handling and cost; then both actual clients with product/plan/version/date and exact candidate recorded, #78. |
| Uploaded-source preview, trusted approval and labels | Acceptance requirements in #79/#80; unavailable in this tracer | Resolve ChatGPT full-detail approval boundary; qualify immutable preview, trusted gesture, exact-target execution, uncertainty and authenticated artifacts, #79/#80. |
| Safe sustained operation and live release | Requirements in #81; no staging/live claim | Separate staging approval; retention/deletion, load limits, incident/emergency-stop and reconciliation ownership; separately authorized sandbox/live single shipment, then batch; production timing approval. |

Public-directory eligibility, submission and acceptance remain separate policy
and owner decisions. Fake models, synthetic carriers and generic MCP clients
cannot qualify real client behavior, paid shipping or public distribution.
