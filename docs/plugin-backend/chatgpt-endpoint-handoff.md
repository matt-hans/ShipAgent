# Private connector endpoint handoff

Prepared 2026-10-15 for bounded [#77](https://github.com/matt-hans/ShipAgent/issues/77)
work under [ADR 0009](../adr/0009-headless-full-agent-authority.md).
**This candidate is an admission integration precursor, not an endpoint-ready
full-agent deployment.** No endpoint, tunnel, OAuth registration, secret entry,
model call or carrier call was provisioned. #76–81 remain open.

## What this change proves

The dormant lifecycle relay path now resolves current Cloud Account and
Provider Connection records using fresh SQL sessions, checks trusted client
registration/surface, persisted link generation, and the pinned exact live target
with its qualified version/capability profile. It rechecks authority after the
broker's authenticated device guard is acquired. Unknown, revoked, suspended,
offline, replaced and incompatible identities do not receive task input.
Authority travels outside model-controlled arguments and is included in the
canonical input hash. The legacy authority-free lifecycle broker path is denied;
legacy status frames retain their existing wire shape.

A real loopback HTTP MCP test drives submit → clarification → continuation →
read → quiescent cancellation and restart/read through this admission path,
real SQLite stores and the existing shared conversation runtime. It uses scripted
inner models, an in-process synthetic relay consumer and synthetic identity.
This does **not** prove an authenticated production WSS target, actual ChatGPT or
Claude, target enrollment, or revocation during an already-running model turn.
The existing target worker epoch callback is still synthetic in this test.

`link_generation` is durable metadata (existing connections migrate to generation
1). This change does not create a provider-callable relink/reactivation operation.
A future trusted management ceremony must increment generation atomically and
must never reactivate a revoked link using its old generation. Distinct
independently revocable links sharing one OAuth client still need issuer-backed
link identity; current account/client/surface lookup does not supply that.

The resolver's binding is an admission snapshot, **not a lease or an execution
grant**. SQL and Redis checks are not a distributed transaction. Target-side
current-authority fencing remains required before acceptance, model/tool dispatch
and result publication; do not replace it with a cached successful lookup.
Production lifecycle exports remain disabled. Mutations, uploads, source-backed
mapping/preview, approvals and labels remain outside this slice.

## Remaining software before a full-agent endpoint can be entered

1. Implement the approved browser operator enrollment and local administrative
   receipt confirmation, with proof of possession and replay/expiry protection.
   Existing desktop registration routes do not satisfy that headless ceremony.
2. Add the authority-aware dedicated headless WSS consumer and authenticated
   current-authority/revocation channel. Verify account/connection/generation,
   exact target, session, sequence, deadline and authority-inclusive input hash;
   fence acceptance, worker dispatch and publication after revoke/relink/rekey/
   replacement. The existing desktop client is not that consumer and must not
   silently accept this envelope as ambient desktop work.
3. Add supported owner-only encrypted-volume secret/storage startup and explicit
   installation/reopen/shutdown commands for an account-dedicated target. No
   desktop keychain, shared environment or local administrative API fallback.
4. Qualify the combined real-store/WSS lifecycle, restart and in-flight revocation
   path; reconcile canonical tool descriptors, scopes and availability before
   explicitly admitting only the source-free lifecycle tier. Do not flip the
   catalog export flags or inject a constant epoch to skip these prerequisites.
   ADR 0006 additionally requires canonical `ToolContract.minimum_capabilities`
   compatibility and the public `target_update_required` response; this dormant
   exact-version admission profile does not qualify that public error contract.

These are implementation dependencies within the already approved architecture,
not a request to choose a different hosting architecture. A status-only endpoint
can be configured earlier to test discovery/login, but it cannot qualify #78's
full-agent lifecycle.

## Local verification without external setup

Run from the selected checkout with its prepared project interpreter. In an
isolated worktree without its own `.venv`, replace `.venv/bin/python` below with
the absolute path to the already prepared project interpreter. No public
listener is needed:

```sh
.venv/bin/python -m pytest tests/control_plane/test_agent_run_authority.py -q
.venv/bin/python -m pytest tests/control_plane/test_models.py -q
.venv/bin/python -m pytest tests/control_plane/relay tests/services/agent_runs -q
.venv/bin/python -m pytest tests/registry/test_artifact_drift.py -q
```

The SQLite migration tests upgrade real disposable stores, including existing
connections, and check the positive generation constraint. PostgreSQL and Redis
qualification must be recorded separately; SQLite/FakeRedis results do not prove
production PostgreSQL/Redis behavior or power-loss/restore guarantees.

## Operator inputs for the later temporary endpoint

Before #78's actual-client setup, record the approved endpoint owner/destination,
issuer, provider and operator client IDs/callbacks, synthetic-model choice and
bounded operating/model budget. Credentials go through the approved operator
secret mechanism, never this guide, chat or model tool inputs. The sample
[configuration](temporary-endpoint.env.example) contains placeholders only and
is not a deployment or a secret-provisioning command.

For a separately authorized **status-only control-plane** check, the existing
supported application factory is:

```sh
.venv/bin/python -m alembic -c alembic.ini upgrade head
.venv/bin/python -m uvicorn src.control_plane.app:create_control_plane_app \
  --factory --host 127.0.0.1 --port 8091 --workers 1
```

Run only after the actual database/Redis/auth configuration is supplied in the
operator's service environment. These commands do not launch a headless target,
configure a TLS proxy or expose a tunnel. The migration changes the configured
control-plane database; use a disposable approved database for development.
`SHIPAGENT_BIND_HOST` and the actual listener must agree. Existing production
exports remain status-only even when this factory is running.

Once the authenticated HTTPS endpoint is separately provisioned and verified,
ChatGPT's custom MCP form receives:

| Field | Value |
| --- | --- |
| Name | `ShipAgent Dev` |
| Description | `Private ShipAgent integration testing` |
| Connection | `Server URL` |
| Server URL | The actual approved `https://<host>/mcp` |
| Authentication | OAuth |
| Advanced OAuth | Actual issuer/client settings only as required by the chosen supported registration mode; no guessed IDs/secrets |

The exact entered `/mcp` URL is the canonical OAuth resource and must equal
`SHIPAGENT_AUTH0_AUDIENCE`; metadata uses that same resource. The provider client
registry must map the real ChatGPT client ID to `chatgpt` and Claude's to
`claude_ai`. The separate operator-purpose client is not a provider identity.
`Tunnel` needs a separately created supported tunnel ID, not a localhost URL or
an invented string. No usable URL/tunnel ID exists as an output of this change.

Record each actual client's product/plan/version/date, candidate commit,
configuration, passed/failed/blocked cases, and redacted discovery/login/consent/
refresh/reconnect/revocation evidence. Keep the fuller
[operator workflow](operator-workflow.md) and [#78](https://github.com/matt-hans/ShipAgent/issues/78)
acceptance boundary; local synthetic success is not deployment or release approval.
