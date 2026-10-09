# MCP acceptance: local proof and actual-client gates

Scope: [#75](https://github.com/matt-hans/ShipAgent/issues/75),
[#77](https://github.com/matt-hans/ShipAgent/issues/77),
[#78](https://github.com/matt-hans/ShipAgent/issues/78) and
[#81](https://github.com/matt-hans/ShipAgent/issues/81).
Harness integration includes the repaired durable lifecycle from #85 and
current-request OAuth authority from #86; earlier harness-only evidence on
`9de0ddd67510b5cf8725fb9ecd4cb8826a639256` is historical, not this integrated gate.

This harness qualifies a **local synthetic slice**, not either product client,
OAuth deployment, shipping functionality, or a production launch. The default
catalog stays status-only. Test-local descriptor copies opt in the implemented
source-free submit/read/cancel tools. There is no inferred continue, event
cursor, source upload, approval, label, or live carrier capability.

## Reproduce the local slice

Use Linux, Python 3.12+, Git, and a project virtual environment installed from
the committed lockfile. Prepare dependencies separately, with network access
only for the authorized setup step:

```sh
uv sync --locked --extra dev
./scripts/run_mcp_acceptance.sh
./scripts/run_mcp_acceptance.sh --self-test
```

The script fails if the specified interpreter or required packages are absent;
it never installs packages or falls back to system/global dependencies. For an
isolated worktree sharing an already prepared virtual environment:

```sh
SHIPAGENT_TEST_PYTHON=/absolute/path/to/ShipAgent/.venv/bin/python \
  ./scripts/run_mcp_acceptance.sh
```

`SHIPAGENT_TEST_ACCEPTANCE_OUTPUT` can select a new receipt directory, and
`SHIPAGENT_TEST_HEAVY_LOCK` can select the shared development lock. Defaults
are a unique `.cache/mcp-acceptance-*` directory and the checkout parent's
`development-heavy.lock`. All workers on the same constrained machine must
use the same lock. The script verifies `src` imports resolve to this checkout.
An output directory may not be the checkout, an ancestor of it, or a directory
containing tracked source. The lock file is never excluded from source evidence.

No Redis or PostgreSQL service is needed for this narrow suite. The target
store is real private SQLite with the application's durability checks; Redis
request-counter operations are an explicitly synthetic boundary. Broader
control-plane qualification requires separate real disposable stores. The
existing `scripts/setup_control_plane_test_services.py --root <private-dir>`
extracts packages pinned by `scripts/control_plane_test_packages.json` without
installing global services; it does not turn these synthetic counter tests
into SQL/Redis failure qualification.

### What the local cases prove

- A real FastMCP client initializes, discovers the wire catalog and calls tools
  over a loopback Streamable HTTP socket. It is not an in-process MCP client.
- The default wire catalog remains status-only even if dormant handlers are
  bound. Opt-in submit/read/cancel reaches the real target adapter, `AgentRunService`,
  shared conversation handler/runtime, and durable target-owned store.
- One successful submit response is deliberately discarded at the ASGI wire
  boundary and replaced by HTTP 503. A new MCP session retries the same input
  and recovers the original run, conversation and expiry. Exactly one scripted
  model request is admitted. Conflicting request-key reuse is denied.
- A clean service shutdown/reopen preserves the completed result; retry and
  read do not construct another provider. The separate existing process-crash
  suite tests queued/running/completed process death, without claiming power
  loss or backup-restore proof.
- Missing authorization context, insufficient submit scope, a foreign account
  and a same-account foreign connection fail at the appropriate real gate.
  An owner with only status scope can still read. Production HTTP middleware
  separately returns a 401 discovery challenge for missing bearer credentials.
- A complete fake provider stream succeeds; text followed by clean EOF without
  terminal proof does not count as successful completion.
- Model-generated purchase attempts receive a real policy denial. The provider
  sees no available tools, the fake carrier gateway sees zero acquisitions and
  zero shipment calls, and public results/logs exclude private reply canaries.
  A separate sensor self-test proves the fake carrier counter is actually
  connected to the real gateway acquisition boundary.
- Existing cancellation wire and process-recovery cases cover queued/running
  cancellation, stable identity after reopen, completed history, foreign
  authority and disconnect/restart boundaries. Cancellation preserves prior
  accepted effects; it does not prove in-flight provider billing stopped.
- Every listener is joined on exit. The outer runner checks owned descendants
  and removes its private runtime directory.

Synthetic identity resolution does **not** test JWT verification, OAuth consent,
token refresh, client registration, revocation, or trusted surface assignment.
The loss injection tests a dropped reply with a deterministic HTTP error, not a
real network partition. The carrier fake measures the current source-free
boundary only; no carrier request, sandbox transaction, or paid model request
is made. A source-free answer is not evidence of successful shipping planning
against actual data.

### Receipts and resource limits

Keep the JSON receipt, pytest JUnit XML and log together. The receipt records
the Git commit, tracked/untracked source-file digest, lock/config hashes,
interpreter/package versions, startup-hook and actual loaded-guard hashes,
execution environment allowlist, CPU affinity,
sampled peak descendant RSS, wall duration, exit status, limit failure and
owned-process cleanup. A dirty worktree is identified by a content digest;
the commit alone must not be cited as the tested candidate in that case. A
second source fingerprint is taken after cleanup; source drift fails the run.

The runner admits at most two CPUs and samples aggregate descendant memory
against a 768 MiB limit, with a 90-second wall budget. The Linux child-subreaper
tracks orphaned descendants, including children that start another session.
Timeout, excess memory or leftover children fail the run. The runner is for
cooperative synthetic tests, **not a security sandbox**: RSS is sampled, CPU
affinity limits parallelism rather than providing a cgroup quota, and an
uninterruptible task or a killed supervisor may defeat cleanup. Report such a
failure; do not call it clean.

The environment is constructed from an allowlist, with a fresh private HOME
and temporary directory, no ambient provider keys/proxy settings, and a null
keyring backend. Each run creates a disposable minimal venv, without pip or
installation, reusing the explicitly selected interpreter's dependency
directories. Its own `.pth` startup hook loads the reviewed loopback/DNS guard,
including when a child using that qualified interpreter strips its environment.
No existing project virtual environment is modified. The runner deliberately
routes its selected Python command through the disposable interpreter and
checks imports resolve to the selected checkout.

This is **not a kernel network sandbox**: native clients, Python `-S`, an
absolute alternate interpreter, or a console script with another interpreter
in its shebang can omit the guard. The runner does not rewrite arbitrary
shebangs. The self-tests demonstrate the `-S` limitation without attempting an
external connection and verify env-stripped children in a fresh overlay. Do not
run unknown code or real credentials under this harness. A separate OS-level
egress boundary is required for a hostile-code claim.

Self-tests cover a clean success, child failure, wall timeout, aggregate RSS
breach, an orphan in a new session, loopback allow/non-loopback deny, startup
guard inheritance, env-stripped child protection, deliberate `-S` bypass,
source-drift failure and exclusion of the runner's own output directory. The generic
offline pytest plugin records the existing LAN-listener test as a named skip;
a skipped non-loopback case never counts as network-listener qualification.

## Extend only as real features arrive

Keep the existing HTTP fixture and external fake seams; extend expected
descriptors only after the implementation is integrated and admitted.

1. Continue: clarification followed by expected-revision acceptance, duplicate
   continuation recovery, conflicting/stale replies and two-session isolation.
2. Cancel: extend the implemented queued/running and terminal cases to future
   waiting-for-input invalidation only when continuation is integrated. MCP
   transport disconnection alone is never interpreted as cancellation of a
   durable agent run.
3. Progress: opaque scoped cursors, ordered retained events, rejected tampered
   and foreign cursors, repeated safe polls with no model dispatch.
4. Source/preview: deterministic synthetic source snapshots, import privacy
   canaries at both model boundaries, immutable preview identity and zero
   unauthorized shipping/commerce effects.
5. Execute/artifacts: only after the separate approval gates, use counted fake
   carrier acceptance and response loss, then separately authorized sandbox
   evidence. Never manufacture a successful shipment by returning model text.

These are missing acceptance gates, not passing tests or silently skipped
coverage. This harness alone does not complete any of #77–81.

## Actual ChatGPT and Claude checklist

Run the checklist independently in both named products on the **same exact
candidate**. Each record needs a date, product/plan/version, endpoint and
canonical resource, source/config identities, authorized target/account/connection
profile, synthetic fixture version, redacted evidence and pass/fail/blocked
status. Do not store tokens, task text, customer rows or label bytes in receipts.

Before either test, obtain explicit approval for the temporary HTTPS destination,
its operator, authentication setup, any credentials and bounded infrastructure
and host/backend model costs. Local success supplies no such authorization.

| Gate | ChatGPT | Claude |
| --- | --- | --- |
| HTTPS preview, account setup and cost authority approved | Not run | Not run |
| Actual product/plan supports the selected private connection | Not run | Not run |
| Exact entered `/mcp` URL, protected-resource metadata, resource requests and token audience agree | Not run | Not run |
| Discovery/HTTP 401, per-tool OAuth schemes and insufficient-scope challenges | Not run | Not run |
| Supported registration identity, exact callback allowlist, PKCE S256/state, login and denied consent | Not run | Not run |
| Refresh/expiry, reconnect/revoke and new link epoch without old-reference revival | Not run | Not run |
| Initialize/list and accurate tool annotations/admission | Not run | Not run |
| Synthetic submit, clarification/continue, advertised-interval poll and cancel | Blocked by implemented lifecycle | Blocked by implemented lifecycle |
| Lost reply, restart and same run identity without duplicate dispatch | Not run | Not run |
| Wrong account, same-account other connection, source/session swap and replaced target denied | Not run | Not run |
| No model/direct hidden purchase, void, pickup, document or write-back path | Not run | Not run |
| Safe bounded results, no source/secret canaries at either model boundary | Not run | Not run |
| Read-only upload/full preview requalification after #79 integration | Blocked by source/preview integration | Blocked by source/preview integration |

Optional rich UI and trusted mutation approval have their own #80 evidence.
No natural-language approval, link click, client-name header or copied
registration identifier confers purchase authority. Successful private-client
testing does not imply public listing eligibility or payment policy approval.

### Official references checked 2026-10-08

- [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports):
  actual initialization/session behavior, JSON or SSE responses, loopback and
  Origin protections, and disconnection versus cancellation. Protocol resumption
  is distinct from ShipAgent's durable task identity and future event cursors.
- [OpenAI authentication](https://developers.openai.com/plugins/build/auth):
  canonical resource propagation, protected-resource discovery, PKCE S256,
  supported client-registration choices and current callback behavior. Copy the
  actual callback shown by the product rather than assuming one historic URL;
  trusted registration must still map to ShipAgent's provider surface.
- [Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp):
  current plan/admin setup, remote MCP URL, sign-in and client-identity choices,
  and per-conversation enablement. A generic protocol test does not prove this
  product's connector setup or authority semantics.

Recheck these sources when preparing an actual-client run. This is a technical
acceptance checklist, not a provider policy or marketplace approval finding.
