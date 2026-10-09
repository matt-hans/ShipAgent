# Synthetic CSV ingress and immutable source contract

Status: **proposed seam; design and deliberately RED acceptance tests only**.
No product implementation, provider export or capability admission is authorized
by this document. Parent [#75](https://github.com/matt-hans/ShipAgent/issues/75),
first uploaded-source slice of [#79](https://github.com/matt-hans/ShipAgent/issues/79).
Reviewed source base: `c391e8c31e52598a9473de7b0a92f6308dd37a83`.

## Outcome and boundary

An authenticated operator can stream a small synthetic CSV to one exact
user-controlled Execution Target. Only a complete, validated upload becomes a
new immutable Shipment Source. The originating provider conversation can refer
to it without receiving its bytes, headers or rows. A later reviewed runtime
slice can configure deterministic mapping/filtering against that exact snapshot.

This slice includes neither real user uploads nor runtime integration. It does
not add commerce, shipping questions, previews, purchases, exports, a web upload
UI, a new host attachment adapter, credentials or deployment. Milestone #79
remains open. The source-free tracer, continue/cancel work and enrollment work
remain separate; their unreleased interfaces are not assumed here.

The authority and data-location rules are ADRs [0002](../adr/0002-relay-first-execution-target.md),
[0005](../adr/0005-ephemeral-cloud-state-retention.md),
[0007](../adr/0007-origin-based-provider-redaction.md) and
[0009](../adr/0009-headless-full-agent-authority.md). Source setup belongs to
separately authenticated operator management. `shipagent.preview` permits
selection of an already-authorized source and potentially charged model work;
it does not establish source credentials or authorize arbitrary uploads.

## Why the existing active-source gateway is not the seam

- `services/gateway_provider.py` owns a process-global DataSourceMCPClient. Its
  lock protects singleton lifecycle, not a conversation's source transaction.
- `mcp/data_source/server.py` owns one DuckDB connection, `imported_data` table
  and mutable `current_source`. Another import replaces the prior table.
- `services/source_identity.py` identifies an import/schema instance. That
  digest is neither content verification nor account/conversation authority.
- `mcp/data_source/adapters/csv_adapter.py` uses permissive auto-detection,
  `ignore_errors`, `null_padding` and full-file inference. It interpolates column
  identifiers produced from headers. It is not an untrusted-ingress validator.
- `mcp/data_source/tools/import_tools.py` accepts local paths and logs paths.
  Query/schema helpers can log source-dependent expressions or parser errors.
  Their local-admin contract must not become the public upload contract.
- `services/mapping_cache.py` is global and can persist raw column names. A
  snapshot workflow must not use it as an implicit source-selection mechanism.

Rejected shortcuts: treating a conversation UUID as permission; importing into
or temporarily swapping the global gateway; locking only import and then
allowing later queries to read a changed source; handing a model a local path;
exposing the whole existing DataSourceGateway (including write-back).

### Smallest reuse path

Add only a target-local `services/source_ingress/` boundary after seam approval.
It owns bounded upload admission, immutable source identities and a narrow
snapshot reader. Reuse existing row identity/checksum helpers, pure
`column_mapping` normalization/validation, and typed FilterSpec compilation.
Keep original values and headers target-local; assign safe internal column
identifiers before any SQL or schema projection.

A snapshot reader owns its own bounded DuckDB connection and fixed normalized
relation, or a dedicated gateway child scoped to the same immutable snapshot.
The preferred first implementation is a short-lived explicit reader over the
validated target-local snapshot, reusing pure deterministic helpers. A new
process-global client, pool, source framework or second agent runtime is not
needed. The permissive CSV adapter can only be reused behind strict validation,
canonical column names, and checked row-count/value-preservation parity; if that
cannot preserve exact strings, use the existing `import_records` VARCHAR insertion pattern from
`mcp/data_source/tools/source_info_tools.py` against a reader-owned context
instead. That function also replaces its context's table, so the global MCP
context must never be passed. Do not silently coerce postal codes, IDs or
formula-looking strings through inferred numeric/date types.

The reader is passed explicitly to the future deterministic operation; it is
never looked up from ambient state. Existing shared wrappers need a separately
reviewed injection seam before reuse. This design does not change the current
`gateway_provider` ownership rule or instantiate an extra long-lived
DataSourceMCPClient outside it. Per-reader mapping/type settings are immutable
and versioned; no process-global mapping cache is used.

## Authority, references and original lifetime

A trusted operator admission adapter resolves all bindings from authenticated
records. Provider/model arguments cannot populate or override them. The target
checks them against its pinned account/target and a current authority resolver;
a Python DTO, signed-looking string or copied opaque reference is not proof.

The target-owned upload envelope binds:

1. Cloud Account ID.
2. Originating Provider Connection ID **and its non-reusable link epoch**.
   The epoch is an opaque trusted string of 1–128 characters, aligned with the
   continuation proposal. That proposal permits NULL only for unbound legacy
   state; NULL cannot authorize this new ingress. There is no numeric,
   synthetic-default, missing-value or implicit-current production fallback.
3. An existing conversation reference whose durable ownership is verified for
   that account, connection/epoch and exact target, plus its original expiry.
4. Exact Execution Target ID **and the authenticated target-key fingerprint**
   pinned at admission. The fingerprint comes from verified target registration
   and proof of possession, never a caller declaration. A stable target ID alone
   cannot hide replacement or key rotation: changed fingerprint invalidates an
   old upload/source even if the ID remains the same. Replacement/offline/
   incompatible targets fail closed; there is no reroute or local-source fallback.
5. A random upload reference, a scoped idempotency key and admission timestamp.
6. Expected content byte length and SHA-256, declared `text/csv`, and a pinned
   parser/normalizer profile version.
7. Original upload expiry and original snapshot expiry, both set at admission.

The upload SHA-256 is supplied by the authenticated uploader and recomputed on
all received bytes. A matching hash proves integrity only, never ownership or
safe content. No content hash is used as a bearer token, provider-visible source
reference or cross-account deduplication key.

The completed manifest adds a random opaque source reference, immutable snapshot
version, verified raw-content digest/length, normalized snapshot identity, row
and column counts, stable source-row ordinals, opaque column bindings, parser
version and private storage identity. It preserves every authority/expiry field
from admission. It contains no user-selected storage path. Raw and normalized
content identities are distinct; neither hashes nor raw metadata need to leave
the target. Identical bytes in two conversations create independently authorized
references, never shared authority.

Every upload/describe/schema/read operation revalidates current account,
connection epoch, conversation ownership, exact target/fingerprint and original
expiry. Stream reception also checks authority at bounded chunk intervals and immediately
before commit; readers check at each operation. Revocation racing commit must
have a defined linearization point: after revocation wins, commit/read cannot
publish. If the authoritative state cannot be established, fail closed. A
stale boolean from admission is insufficient for later use. In particular, the
RED fixture's `authority_is_current` callback checks synthetic current state but
**does not prove atomic revocation/commit fencing**. The real resolver must
provide a trusted generation/lease or equivalent transaction fence that
linearizes authorization with publication and rejects stale finalization.
Selecting that concrete fence is a seam-review blocker before implementation;
adding a second callback check alone does not close the race.

Synthetic defaults, deliberately not production SLOs:

- Upload lifetime: at most five minutes, also capped by conversation expiry.
- Source-reference lifetime: at most 24 hours from **upload admission**, capped
  by the original conversation expiry. Finalization does not start a new TTL.
- Read, retry, resume, reconnect, reauthentication, key rotation and process
  restart cannot extend either expiry. `now >= expires_at` is expired.
- Revoked connection epochs cannot be resurrected by reusing the same connection
  ID or signing in again. A new epoch requires a newly authorized upload/binding.
- Target key rotation may preserve the stable target ID under ADR 0002, but it
  does not silently rebind existing upload/source fingerprints. Newly authorized
  references are required; any future operator recovery must preserve bytes and
  original expiry without reviving revoked authority.
- Source expiry/revocation blocks new use; it does not undo accepted external
  effects. Later jobs retain their separately authorized immutable evidence,
  never derive new approval from source retention. No jobs exist in this slice.

An authorized, correctly bound expired reference returns `source_expired` (or
`upload_expired`). Unknown, wrong-owner, wrong-conversation, replaced-target and
revoked references share a closed unavailable result. Do not reveal a reference's
existence or expiry before ownership checks.

## Complete bytes before publication; never replace implicitly

The proposed target service has four initial operations:

- `issue_upload(binding, request_key, content_length, content_sha256, media_type)`
  checks the trusted operator admission and returns an opaque upload ticket with
  the original upload/source expiries. It does not create a usable source.
- `receive_upload(binding, upload_reference, chunks)` consumes a bounded byte
  stream into target-owned quarantine. EOF, exact length/hash, strict CSV
  validation and current authority are all required before atomic publication.
- `describe_source(binding, source_reference)` returns an allowlisted aggregate
  receipt. It never starts a model, chooses a source or extends expiry.
- `describe_model_schema(binding, source_reference)` returns the separately
  allowlisted target-model configuration projection described below. It is not
  an outer-provider export or a row/sample API.

The names above are a proposed target-service contract, not new MCP tools.
`binding` is supplied only by trusted adapters after independent authentication
and operation-specific authorization. A current-authority callback in synthetic
service tests stands in for that external trust boundary; those tests do not
qualify real authentication, relay binding, CSRF or provider scopes.

Reception is single-owner and atomic per ticket. Conflicting/concurrent receivers
cannot interleave chunks. Interrupt, cancel, short EOF, overflow, hash mismatch,
parser rejection, expired/revoked authority or storage uncertainty leaves no
resolvable source. Quarantine is inaccessible through describe/reader APIs.
A receive failure closes that ticket; a fresh operator-authorized attempt uses a
new request key. The exact idempotency namespace is `(account_id,
provider_connection_id, connection_epoch, conversation_reference,
execution_target_id, target_fingerprint, "upload", request_key)`. Ownership and
current authority are checked before lookup. Within that namespace, the input
identity includes content length, SHA-256, media type and pinned parser profile.
An identical admission returns the original ticket/source and lifetime; changed
input returns `request_conflict` only to the authorized original binding.
A valid distinct conversation may independently use the same request-key text
without revealing another conversation's record. Presenting another binding's
opaque ticket/source returns unavailable, never a conflict or existence hint.
There is no API for changing a ticket's binding. Identity cannot be reset by
deleting an expiry record. A replay need not upload
bytes again once durable completion is known. Uncertain commit is reconciled by
reading the original ticket, never by creating a second source automatically.

There is **no global or conversation active-source pointer in this seam**.
Every successful new upload gets a distinct immutable source reference. Existing
source references continue to denote their original bytes until expiry or
revocation. A later run must explicitly pin source reference/version, parser,
mapping/type-settings version and selection meaning during its existing fenced
acceptance transaction. Later uploads cannot change a previously accepted run.
Changing a selected source is a later compare-and-set conversation transition;
it is not a side effect of starting or finishing an upload. Cancellation fences
future work but does not edit or repurpose an immutable snapshot.

Target storage uses an already provisioned, private, account-dedicated root per
ADR 0009; no production directories/permissions/encryption are provisioned here.
Mint basenames server-side, open without following symlinks, reject hardlink and
ownership/permission anomalies, and bind the checked file identity through use.
A successful commit requires persisted bytes and manifest before acknowledgement;
a missing/replaced/corrupt snapshot is unavailable, never re-imported from a
remembered path. Quarantine/manifest cleanup must survive restart without making
an incomplete snapshot resolvable. Use bounded retention and durable expired-key
tombstones; when the bound is reached, reject admission rather than resurrect old
request keys. Process-crash tests are required before durability claims; physical
power loss, rollback/restore and production encrypted-storage proof remain gates.

## Bounded CSV profile and failure behavior

The initial accepted format is UTF-8 CSV (one optional leading UTF-8 BOM), comma
delimiter, double-quote escaping, one header row, at least one data record,
consistent field count and no NUL bytes. Embedded commas/newlines are valid only
inside correctly quoted cells. Reject malformed quoting, duplicate/empty headers,
invalid encoding and unsupported declared type. Limits include headers and
quoted multiline fields; never count physical lines as records.

Initial synthetic caps: 1 MiB total bytes, 64 KiB per transport chunk, 10,000 data
records, 64 columns, 16 KiB encoded bytes per field and two incomplete uploads
per target. The 16 MiB content quota counts **raw + normalized + quarantine +
publication/cleanup temporary bytes**, across every retained and in-flight
source; normalized content is separately capped at 2 MiB per upload. Reserve
peak simultaneous storage, including any copy-before-rename, not just raw input.
Metadata has a separate 4 MiB total cap, 64 KiB per manifest, at most 128 retained
source manifests and 1,024 upload records including tombstones. No quota can be
avoided by failing reception or accumulating expiry/idempotency records. Admission rejects an oversized declared
length before receiving bytes; streaming stops at the actual limit even when
length lies. Reserve quota before reception and release it only after cleanup is positively
complete. If limits prevent retaining a required tombstone, deny new admission;
do not prune an identity and then allow the same request to be accepted again.
The whole upload is bounded by its five-minute expiry; a stalled stream is
closed after ten seconds without progress. Parser work has a five-second wall
budget and a 64 MiB memory budget, with one execution thread and no network or
extension loading. These caps are reviewable policy constants, never model input.
A coroutine timeout or cancellation request is not proof of termination. An
independent owner watchdog or bounded parser process must enforce the deadline,
retain ownership and quota while cleanup is still live, and fence publication
before reporting failure. Unconfirmed cleanup marks ingress unavailable for new
work rather than silently starting another parser. The 64 MiB/five-second parser
profile and other limits are **proposed, not measured**: check them against
legitimate fixtures before claiming readiness. No such enforcement or
termination guarantee is implemented by this design packet.

ZIP/XLSX/XLS, gzip, archives, XML/JSON, databases and arbitrary delimited formats
are unsupported. Known binary/compressed signatures and format mismatch fail
before parser dispatch; archives are never expanded, so member traversal and
zip bombs have no permitted execution path. A future spreadsheet parser needs
its own resource/expansion/external-link/macro review. Do not auto-detect into it.

No path, URL, upload directory, source_ref-as-path, SQL text or remote fetch
option is accepted as ingress. Model-supplied URLs including redirects, loopback,
cloud metadata and `file:` are rejected; no fetch is attempted. A transport's
original filename is discarded before storage naming/logging and cannot change
format or authority. The original header spelling is private data; it is never
used as an SQL identifier. Attribute names such as `approved`, `connection_id`
or `source_reference` inside CSV cells/headers confer no authority.

Formula-looking values (`=`, `+`, `-`, `@`, or leading control/whitespace variants)
remain inert target-local strings; parsing must not evaluate formulas, resolve
external links or invoke commands. Do not mutate raw bytes as a sanitization
shortcut. This slice exposes no spreadsheet/CSV export. A later export must
neutralize formula injection under its own format-specific contract; ingestion
alone cannot establish safe spreadsheet rendering. Never make HTML from cells.

Errors are closed codes plus fixed safe instructions, with no raw exception,
filename, header, cell, local path, hash or parser excerpt. Expected categories:
`upload_unavailable`, `upload_expired`, `upload_incomplete`, `content_mismatch`,
`invalid_csv`, `unsupported_media_type`, `source_limit_exceeded`,
`source_unavailable`, `source_expired`, `source_storage_unavailable` and
`request_conflict`. Log/audit only redacted correlation IDs, counts and those
categories. No raw exception chaining or SDK debug payloads cross either model
boundary. Storage/authority uncertainty fails closed and preserves prior sources.

## Useful configuration without a row-data pipe

The two model boundaries have different allowlists, while both exclude imported
rows, raw headers, filenames, paths, samples, secrets and raw parser messages.

**Outer ChatGPT/Claude projection:** opaque source reference, original expiry,
fixed format/status, total row/column counts and bounded aggregate readiness or
selection counts. No full schema, mapping trace, raw content hash, per-row
identifiers or target-private metadata. A reference never authorizes download.
The selected source is separate from provider-originated task text; provenance
is never relabeled simply because a user subsequently mentions the upload.

**ShipAgent-owned target-model configuration projection:** the exact source
reference/version plus bounded entries containing opaque column reference,
coarse type from a closed enum (`text`, `number`, `boolean`, `date`, `unknown`),
nullability and canonical shipping-field candidates from a fixed reviewed
vocabulary, together with a closed ambiguity/mapping-readiness state. No dynamic
free-text labels or descriptions. Types are derived deterministically and never
change raw string storage. Selection outcomes are aggregate counts only.

The initial semantic vocabulary is frozen to `shipTo.name`,
`shipTo.addressLine1`, `shipTo.addressLine2`, `shipTo.addressLine3`, `shipTo.city`,
`shipTo.stateProvinceCode`, `shipTo.postalCode`, `shipTo.countryCode`,
`packages[0].weight`, `packages[0].length`, `packages[0].width` and
`packages[0].height`. Candidate generation filters through this explicit set;
it must not expose every field accepted by existing mapping helpers. Credentials,
carrier/account numbers, connection/target identity, permissions, scopes,
confirmation/approval/grants, execute arguments, quoted/final purchase prices,
currency commitments and other authority fields are never mapping candidates.
They stay unknown data regardless of header spelling. Adding semantic fields
requires review of the closed vocabulary; imported `approved=true` or a price
cell cannot become approval or execution authority.

For example, target-local `recipient_name` and `weight_lbs` headers can become
`column_0001 -> shipTo.name` and `column_0002 -> packages[0].weight`, using the
existing pure `column_mapping` rules. Both column references and canonical field
names are generated vocabulary; their original header spellings are not copied
into the model request. Normal schemas therefore remain automatically mappable.
The model configures mappings between these references and allowed canonical
fields, and produces the existing typed filter intent. Deterministic code checks
references against the pinned snapshot, resolves the private column table and
uses existing mapping/FilterSpec services on target-local rows. Model-authored
raw SQL or invented column references never reach DuckDB.

Heuristic matches are candidates, not trusted assertions from the file. Detect
colliding candidates and missing required fields explicitly; do not silently
choose whichever hostile header matched first. A header containing a prompt or
customer canary may at most affect a bounded candidate/ambiguity state. Unknown
columns remain `unknown`; no model receives their text to guess meaning.
Clarification is limited to the ambiguous field/opaque column ordinal. A human
may assign meaning through the separately authenticated target management view,
or explicitly provide non-row mapping configuration. That configuration is
versioned; it does not confer permission to disclose imported cell values.
A prior dataset's mapping cannot transfer merely because a schema hash matches.

The optional future `open_snapshot` reader is target-internal, never a model
result. It gives deterministic code pinned rows and checksums; it cannot import,
write back, select another source, fetch URLs or resolve arbitrary file paths.
No schema/reader/runtime admission occurs in this design-only change.

## Acceptance evidence and next gate

The adjacent proposed tests exercise service outcomes and wire projections using
synthetic authority and bytes. They intentionally fail until the service exists;
a missing-feature failure is not a security pass. They do not use fake shipping,
commerce or model effects to claim a working full-agent flow.

| Behavior to establish | Observable outcome |
| --- | --- |
| Complete valid CSV | One immutable source receipt, exact counts and original expiry |
| Short/raised/interrupted stream, bad digest | No new source; prior source still usable and unchanged |
| Oversized declaration/actual bytes/chunk/field/rows/columns | Bounded rejection; no publication or quota bypass |
| Wrong MIME, invalid UTF-8, malformed quotes/width, duplicate header | Fixed safe error; prior source untouched |
| Archive/XLSX/zip bomb/traversal payload | Unsupported; no expansion, remote retrieval or file escape |
| Path/URL pretending to be reference | Uniform unavailable; no file/network access |
| Two same-account conversations or connections | Independent sources; copied ticket/ref denied |
| Wrong account/target/fingerprint/opaque epoch or unowned conversation | Denied before private metadata or bytes are exposed |
| Same target ID with changed authenticated key identity | Original ticket/source denied; no silent rebind or extended expiry |
| Revocation during receive/read, authority outage | Commit/read fenced; no reroute or new lifetime |
| Expiry boundary/retry/reopen | Same original lifetime; expired reference cannot resurrect |
| Duplicate/racing receive, lost completion reply | One immutable identity or closed conflict, never mixed bytes |
| Source replacement while an existing reader/run is pinned | Existing reader/run sees its original snapshot only |
| Storage symlink/hardlink/identity replacement, disk-full/crash | Closed failure; no escaped writes or partial source |
| Header/cell/filename prompt injection and formula-like strings | Inert data; useful bounded schema; no policy/authority changes |
| Canaries in source, malformed input and parser exceptions | Absent from both model projections, logs/audit and shared stores |
| Ordinary versus ambiguous mapping | Automatic safe candidates for ordinary headers; targeted clarification only |
| Forged fields/column references/SQL | Validation failure; no filesystem/network or arbitrary SQL effect |

The initial RED tracer covers only part of this matrix. Quota/races,
process-crash/storage tampering, current-authority linearization, pinned reader
isolation, real loopback HTTP upload, control-plane memory/disk inspection and
actual model requests must be added in subsequent approved vertical slices.
No required but untested row is considered passed. The control plane must use
bounded transit-only buffers with proxy/framework body spooling, request logging,
tracing and caches explicitly disabled; a target-service unit test cannot prove
that deployment property.

Before product implementation: review this seam with the integration owner and
security gatekeeper, agree the authority-resolver/fencing contract (the synthetic
callback is not that fence), select the
strict parser reuse path, and approve the first vertical implementation plan.
Keep failing tests off the passing integration branch until that plan explicitly
accepts their treatment. Later runtime coupling must review exact then-current
continue/cancel/revision interfaces rather than assume this base's tracer can
accept source references. Full #79 acceptance still needs real MCP/shared-runtime
selection, shipping answers and immutable previews under its remaining gates.
