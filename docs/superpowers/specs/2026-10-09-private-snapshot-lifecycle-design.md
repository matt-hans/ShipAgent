# Private CSV reception and immutable snapshot lifecycle

Status: architectural proposal for independent review, not implementation approval.
Base: merged main `cedc8a5fa951965c14b5f6bbfa78e492cb5289be` (PR91).
Milestone #79 remains incomplete. This proposal covers a synthetic target-local
vertical slice; public admission, production authority and deployment stay absent.

## Outcome and existing pieces

An already-authorized operator can supply bounded CSV chunks for an existing
private reservation. Complete, verified bytes become one durable immutable
private snapshot. A lost completion reply recovers the same identity and original
expiry. Incomplete, invalid, revoked or interrupted work never becomes readable.
Existing completed snapshots remain unchanged by later uploads and failures.

Main already provides the exact-string `synthetic_csv_v1` parser and bounded
metadata reservations. The latter pin the actual Agent Run lease, acquire the
Agent Run writer, source writer and real injected authority exclusion in that
order, and retain ownership on uncertain commit or cleanup. They do not own
content, parser processes, physical capacity or a canonical Source Reference.
The earlier whole-ingress design and its missing-feature probes remain historical;
this plan neither relabels them passing nor implements its mapping/model surfaces.

Reuse those components. Add lifecycle rows and private raw/normalized files;
do not put content BLOBs into the metadata WAL. A receive-only validator was
considered but would leave durability, replay and immutable reading unproven.
Keeping content outside SQLite makes content peak accounting and parser file
ownership explicit while retaining one database publication decision.

## Scope and operation interface

The receiver is an internal chunk-driven service, not an arbitrary iterator
consumer. Proposed operations are `begin_receive`, `append_chunk`, `finish`,
`abort`, `describe_snapshot` and `read_private_snapshot`. Every externally
invocable operation takes the trusted operator selector, Provider Connection and
conversation reference, then resolves current authority through the existing
injected fence. Request/model arguments cannot supply epochs, key fingerprints,
generations, paths, URLs, filenames or authority implementations.

`begin_receive` resolves the original request key and private reservation ID
together. Neither ID is a bearer capability. It atomically claims one still-live
reservation and reserves peak content capacity before creating files. It returns
a process-bound internal receiver handle, never a transport token. Handle methods
also verify the original binding and owner, rather than trusting possession of
that handle. Concurrent claims on the same reservation fail without mixing data.
A completed claim returns its original completion receipt; a failed claim stays
failed, and a new attempt requires a separately authorized new request key.

`append_chunk` accepts an exact expected byte offset and an already materialized
nonempty `bytes` value of at most 64 KiB. The offset must equal the owner's current
length; duplicate, overlapping or out-of-order chunks close the attempt with a
fixed conflict rather than being appended twice. Partial retransmission/resume
is deliberately absent. The future transport must bound its own reads before allocation; this
service does not qualify HTTP/proxy spooling or an upstream caller's allocation.
The receiver counts and hashes actual bytes, enforces the declared length and
1 MiB total, and never creates an implicit new reservation. `finish` explicitly
marks EOF. Short/overflowed/mismatched data fails before parser publication.
No resume of partial streams is supported in this slice.

Completed IDs remain independently random, target-private 32-hex identities,
distinct from reservation IDs. No public `source_reference` or registered Source
family is allocated. The private completion receipt contains only its private
snapshot ID/version, CSV format, counts and original expiry. No provider/runtime
code consumes it. The only value-bearing read returns a fully materialized
private snapshot to trusted deterministic target code; no lazy reader, path,
open descriptor, SQL connection or reusable authority escapes. Mapping, model
schema and source selection are deferred.

## Immutable binding and lifetime

The complete record retains the reservation's exact account, connection/epoch,
conversation, target/key, request identity, admission time and prospective source
expiry. Completion never starts a new lifetime. It records a separate version 1
snapshot manifest (at most 8 KiB encoded), with verified raw identity, canonical normalized identity,
byte lengths, counts, fixed parser profile and server-minted storage names.
Headers/rows remain only in private content files.

During reception, use the earlier of the original upload expiry and the operator
authorization expiry captured at claim. Later calls cannot renew that captured
grant by presenting a fresher authorization. They still resolve current authority
and exact binding. Final publication requires the original upload lifetime to be
live. Later completed-snapshot operations require fresh current operator authority
and the original source/conversation lifetime, not the expired upload window.
Legacy NULL epoch, wrong purpose, changed target key, revoked/foreign bindings,
or ineligible conversations deny before private reference-dependent outcomes.

Retain the current narrow `waiting_for_input` conversation policy. Reception does
not consume clarification or mutate revision/history. Cancellation or continuation
can proceed between receiver calls and makes subsequent reception/publication
unavailable. The owner can retire its own incomplete files after such a denial;
cleanup itself does not need a newly valid user grant. Aborting an already
completed snapshot never changes or deletes its immutable bytes.

## One owner, short transactions and independent deadlines

An admitted receiver pins a distinct session-lifetime lease borrow until its
files, child and captured scopes have actually retired. Short per-call fence
operations own separate ordinary borrows; they never transfer or retire the
lifetime token. The durable claim binds the current
coordinator generation and an independent random attempt identity. A new Python
manager cannot adopt the claim or evade the shared source quarantine.

The shared internal SourceFenceExecutor retains the same operation before scope
acquisition. Only trusted synchronous module-defined actions use its private
entrypoint; request/model data cannot select actions, hooks or deadlines. An
optional internal deadline can only shorten the common budget. The action-scoped
held view denies copied/late use and records an exact immutable candidate before
COMMIT when needed. The successful return must be that captured candidate;
connections, scopes and reusable commit functions cannot be returned. Candidate
presence remains separate from commit-attempt evidence, known COMMIT and the
final authorized response. The initial exact result whitelist is ReservationReceipt;
future snapshot result types require their own reviewed extension.

A captured response expiry is explicit and cannot be renewed by the action.
Reservation actions select the original upload expiry; a future completed lookup
will select the original source expiry under the same current authority/conversation
gates. Typed internal set_result, set_response_expiry, require_response_time and
commit methods preserve the old guard order. Private pre-commit hooks return None;
a rejected hook before SQL remains an ordinary precommit error after proven cleanup.
No callback may acquire another lock or retain an actionable scope after return.

Do not hold database/authority transactions while waiting for chunks or parser
completion. Claim, bounded chunk authorization, terminal publication and reads
reuse the established Agent Run writer → source writer → authority order. Each
transaction uses the existing shared two-second deadline and checks current
ownership, generation and original expiry after waits. No authority callback may
re-enter either store. A bounded file write/hash can happen outside that exclusion
because quarantine is invisible; only final fenced publication creates visibility.

A receiver manager independently watches ten seconds without byte progress and
the original whole-upload deadline. Its state mutex is short and never held over
file I/O or child waiting. Each receiver has one owned in-flight action. Concurrent
append/seal/finish/file-durability calls reject before starting another action.
Expiry/abort/shutdown marks publication unavailable, but cannot close or reuse a
descriptor while that action still owns I/O on another thread. Cleanup and release
of the borrow/slot/quota require the action to have actually returned as well as
child and descriptor retirement. A blocked filesystem call retains those resources
and denies further source admission; timeout signaling is not completion. Empty calls, polling, retry and parser activity do
not renew byte-progress time. Normal owner close stops new reception before
waiting for admitted cleanup. If cleanup cannot be confirmed, retain the exact
handles, quota and borrow; quarantine the shared lease for source work and allow
only explicit later retirement. No claim of forcibly terminating a blocked
in-process filesystem call is made. Once owner shutdown denies a new per-call
borrow, already-owned cleanup still proceeds. It cannot delete candidate bytes
whose publication COMMIT is unknown. If a safe terminal/tombstone write cannot
be authorized or acquired, leave conservative durable capacity for explicit
fresh-owner startup reconciliation; do not invent a cleanup bypass that grants
new publication or read authority.

## Shared work bounds and cancellation winner

Use fixed source-work tags on actual lease borrow tokens: at most two receiver
lifetime tokens, one parser token and one private-read token across every manager
object on that lease. Ordinary inner transaction borrows are untagged and do not
consume those work slots. Counts derive from exact active-token membership, so
retirement remains a single removal rather than a separate decrement. Tags are
trusted service constants, never caller/model inputs. All tokens retain PID,
physical ownership, early-closing and sticky-quarantine rules. Durable claims
and quota additionally constrain restart; a fresh Python manager cannot bypass
either layer. The parser token is held in addition to its receiver lifetime token. If the
sole parser slot is busy, finish leaves a retryable sealed-raw state and returns
a fixed busy/unavailable outcome. It neither closes an otherwise valid attempt
merely for scheduling nor renews idle/whole deadlines. A later finish retry can
claim the slot only while those original deadlines remain live.

The parser borrow allocates and retains exactly one process-pin owner before
any descriptor duplication. The helper duplicates the actual lease lock
description through a fixed FileIO opener; it never opens a replacement lock or
calls LOCK_UN. Parent copies are CLOEXEC. Exact pin/token identity and PID checks
precede the state mutex. An active pin prevents its borrow's retirement.
A pin admits one acquisition/retirement action under that short mutex, then
performs FileIO adoption/close outside it while retaining the parser borrow.
Concurrent pin actions and child_fd access reject until that action returns;
lease shutdown can mark admission closing promptly without releasing ownership.
Unknown-I/O denial updates hold the mutex only to record quarantine.
The opener records a duplicate before returning it. Before handoff, cleanup owns
that raw descriptor; after successful adoption it owns the exact real FileIO.
If adoption or raw close leaves ownership uncertain, retain the pin and quarantine
source work instead of blindly retrying a possibly reused integer. A positively
closed FileIO is never raw-closed again after an interrupted wrapper return.
Closing a parent duplicate does not prove child exit. The future OwnedParser must
keep this helper private and enforce exact child wait, then pin retirement, then
parser-borrow retirement. Spawn ownership and parent-death exclusion are Task 6
proof obligations; the helper alone does not qualify that sequencing.

A short state-mutex transition at the trusted pre-commit hook determines the
abort/timeout winner. After acquiring that mutex, recheck the cancellation state
and freshly sample deadline/original expiries following all held-guard checks.
If abort/timeout wins, no publication COMMIT is attempted. If publication claims
the transition first, release the mutex for SQL, but abort/timeout may return only
pending/unavailable until commit is reconciled; it cannot acknowledge a successful
abort, delete candidate bytes or free quota. The cancellation-admission transition
is distinct from the later durable manifest visibility point.

If time crosses during COMMIT, preserve known durable outcome and capacity, and
suppress that call's fresh-live acknowledgment. Unknown commit stays quarantined.
No promise is made to undo an already admitted commit. A subsequent observation
must acquire current authority and apply the original applicable lifetime again.

## Parser child and bounded result protocol

Parsing runs in a dedicated child process using the existing pure parser. The
parent opens the sealed raw input and normalized output descriptors and gives
only those descriptors plus bounded declared metadata to the worker. No caller
path, pickle, arbitrary Python object protocol, plugin/extension loading, model
client or network operation is involved. The child environment excludes ambient
credentials and application settings.

The fixed bootstrap derives three child-local namespace package paths only from
its installed worker location after applying limits. This avoids the existing
src.services initializer's application/database/SDK imports while loading the
unchanged pure CSV parser and codec. No argument or environment value chooses an
import root, and no parent-process module is altered. Bytecode writing is disabled
so those imports cannot create cache files beside installed source. The default
action child timer samples the remaining original monotonic deadline immediately
before installation, after resource and affinity setup; setup never renews it.

The receiver may first admit a captured parser owner without spawning. This
reserves the same tagged slot and fixes its absolute deadline once. Only a known
sealed-to-parsing metadata COMMIT permits run on that owner; failed or unknown
phase commit never spawns. Ordinary run callers use this same admission path.
A busy slot leaves sealed retryable only after the failed admission's resources
positively retire, under the receiver's original clocks.

The parent captures its exact process owner before constructor pipe/spawn effects.
A constructor attempt with an unknown outcome retains and quarantines its pin and
borrow rather than inferring no child from a missing successful return. It cannot
ordinarily release that uncertainty; process exit and the actual inherited lock
remain the recovery exclusion. A fully captured child requires actual wait,
positive result-pipe closure, pin closure and token retirement in that order.
The parent bounds reads before allocating a result payload and applies the same
original deadline to result acceptance and retirement. Deadline expiry may retain
an already-signaled child until a later explicit close observes actual exit.
Neither a signal nor elapsed time proves retirement. An after-effect pipe-close
exception uses the real closed state on retry, without repeating a raw close.

The proposed Linux worker profile is one CPU, five seconds wall time and a
64 MiB RLIMIT_AS address-space ceiling. Sampled resident memory is diagnostic,
not that enforced metric. Legitimate worst-shape fixtures must pass under the
actual ceiling before accepting it. Launch a minimal isolated `python -I -S -B`
bootstrap that sets limits before importing the parser, with bounded output-file
size and an independent parent watchdog. Do not use Python preexec_fn in the
multithreaded service. Boot/spawn time consumes the same deadline and retains the
owned in-flight action if the platform call itself cannot retire. The result channel is a fixed bounded frame containing only a
closed status, counts, byte lengths and private digests. Check the frame length
before allocation. Decode strict UTF-8 without a byte-order mark before JSON
parsing; alternate UTF-16/32 encodings are outside this closed protocol.
Raw exceptions/stdout/stderr never become user errors.

Cleanup addresses only the parser PID/process group created by this owner.
Do not use process-wide `waitpid(-1)`, a shared-service child subreaper or unrelated
descendant killing: Agent Run/provider children may coexist. Terminate, then
bounded kill/wait of that exact owned child; signaling alone is not retirement.
Retain quota/borrow and quarantine if actual child retirement remains uncertain.
The parser cannot directly publish a database manifest or final storage identity.

Parent death must not make a still-running parser invisible to the next owner.
Only an exact admitted parser-tagged borrow may allocate an owned duplicate of
its actual coordinator descriptor. Allocate/capture the pin owner before dup or
spawn; parent copies remain CLOEXEC and pass_fds transfers the pin only to the
fixed child. It refers to the same Linux flock open-file description and stays
open in the child until exit. It grants no Python lease/authority rights. Neither
pin retirement nor the child calls LOCK_UN. The normal parent may unlock only
after actual parser wait, all pin descriptors and the parser borrow retire.

After parent death, the inherited pin keeps replacement lease acquisition blocked
until actual child exit; fresh generation alone never proves old parser retirement.
The fixed bootstrap installs a default-action timer for the remaining original
absolute monotonic deadline, not a fresh five seconds. A stuck child may block
replacement indefinitely rather than permit unsafe file cleanup. Startup does not
guess PIDs or reap unrelated work. This follows Linux's
[flock descriptor lifetime](https://man7.org/linux/man-pages/man2/flock.2.html)
and must be verified with a killed parent and demonstrably surviving child.


Normalized storage uses precisely the existing snapshot-identity preimage: the
16 ASCII bytes `synthetic_csv_v1`, followed by the header record and each data
record; each record begins with its unsigned four-byte big-endian field count,
and each field with its unsigned four-byte big-endian UTF-8 byte length followed
by those exact bytes. The profile prefix is unpadded. EOF terminates the last
complete record; trailing
or incomplete bytes reject. Manifest counts and the canonical SHA-256 pin the
complete content, including order. The decoder bounds record count, field count,
field length and total bytes before allocation and checks strict UTF-8. It has no
dynamic type deserialization. A pure bounded encoder/decoder must prove
roundtrip identity, reject malformed/truncated/oversized framing before allocation,
and preserve leading zeros, Unicode, multiline cells and inert formula strings.
The normalized artifact remains at most 2 MiB. Parent verification checks the
worker's output identity/length and bounded manifest fields before publication.

## Private files and sole publication authority

Use an explicitly supplied already-private, account-dedicated target root.
Provisioning, credentials and encrypted production storage are outside this slice.
Open relative to a pinned directory descriptor with server-minted basenames;
reject symlinks, hardlinks, wrong owner/mode, wrong file type and replaced identity.
Read-only acquisition uses O_NONBLOCK before its regular-file check, so a FIFO
replacement cannot wait for a writer before rejection. Keep the descriptor's
identity bound through writes, sealing and later reads.
Never import a remembered path or fall back to another file on a mismatch.

The file owner exposes a short in-memory `protect_publication()` transition before
any terminal COMMIT attempt. This irreversible marker only denies deletion; it
confers no visibility and is serialized with retirement admission. It refuses once
retirement or another owned action has started. Completed-manifest owners start
protected. A later pre-SQL denial does not clear protection: bytes remain for
fresh-owner reconciliation. The private pre-COMMIT hook may perform this short
state transition but may not acquire another store/authority scope or wait on I/O.

Each owner keeps one in-flight file action outside its short mutex. Root close
marks admission closing and refuses while registered owners remain; it never
closes another action's descriptors. Cleanup captures every descriptor before
its first effect and deletes only a positively pinned original incomplete file.
File deletion is followed by a proven directory fsync before retirement completes.
Failure preserves the dirty-directory stage for explicit retry. Positive completion
of all descriptors and required sync is recorded separately before exact registry
release, so the original owner can reconcile a before/after-effect release failure.
Missing registration alone, copied objects and inherited process state confer no
retirement proof. Synchronized deletion has its own positive completion record;
closing retained descriptors never acknowledges a later deletion request. A later
remove request refuses unless the original incomplete files were actually removed
and the directory sync completed. Protection continues denying deletion after
descriptor retirement. Repeating the same proven disposition remains idempotent. Unknown raw-FD handoff/close effects remain unavailable rather
than retrying an integer that could now identify an unrelated file. These helpers
supply no proof that a child using an exported descriptor has exited; that remains
the parser/receiver owner's later obligation. Their private directory admits only
coordinated trusted writers, not arbitrary same-UID participants.

The lifecycle row is the sole visibility authority. Staging/final filenames,
complete bytes or a parser result never imply a published snapshot. The order is:

1. Durable fenced claim and peak-capacity reservation.
2. Create both server-minted raw/normalized basenames with O_EXCL and pin their
   descriptors. Persist their exact identities in the claim before accepting bytes.
   They remain logically quarantined, despite already having their fixed names.
   Bounded append and seal the raw file after exact EOF/hash.
3. Parse into the separately owned normalized file; retire child.
4. Verify content identities, fsync both files and the containing directory.
5. Reacquire the established fences and current binding/lifetimes; commit the
   immutable complete manifest and terminal lifecycle state in one source DB
   transaction. This commit is the snapshot visibility point.
6. Retire scopes, perform the final local response-time check and acknowledge.

No rename, hardlink or copy is needed for publication; each file retains the
basename and descriptor identity from initial exclusive creation. The DB manifest
alone changes its logical visibility. An implementation needing a copy would need
a separately reviewed peak reservation before writing it; cross-filesystem moves
are absent. A crash after file creation but before durable identity recording is
conservatively quarantined: a reserved basename alone never justifies deleting a
possibly replaced or otherwise unproven file. Recovery removes incomplete files
only with positive previously recorded ownership and matching current identity.
A failed or ambiguous database commit never proves rollback. Keep the exact
candidate identity and bytes; reconcile the original claim under a fresh valid
owner instead of reminting automatically. A known commit stays known even when
the response or later cleanup fails. Existing completed data is never overwritten.

`read_private_snapshot` first authorizes and captures the immutable manifest,
opens/verifies only its pinned content, and materializes bounded data outside
long database locks. It then reacquires the standard fences and revalidates the
same immutable manifest, file identity, current authority and lifetime before
returning any values. One read-tagged lifetime borrow pins the exact generation
through both fence acquisitions and materialization; it is never released and
reacquired between them. All phases share one original deadline. After actual
retirement, recheck that deadline and the captured original operator, source and
conversation expiries before returning values; a refreshed grant cannot extend
the in-progress read. Apply this response-time gate to reference-dependent errors
as well as success, even when no snapshot receipt was materialized. The second
fence is the read's authorization linearization point: revocation/cancellation
winning it denies release, while later changes cannot retract already-linearized
observations. Every read starts fresh; no reusable reader
capability is returned.

## Metadata migration and retention

Add a version 2 database schema with separate lifecycle/manifest rows keyed to
existing reservation IDs. Preserve every version 1 reservation payload byte,
digest, ID and original expiry. Separate the immutable metadata payload codec
version from the database schema version. A migration must not rewrite old input
identity merely to change the database version.

Migration is explicit, atomic and owned by the actual coordinator before normal
admission. It uses the same borrowed Agent Run writer and source writer discipline,
retains setup handles on failure, and makes no caller reference lookup/result.
Every disk-backed source open/transaction, including V1 setup, receives the actual
borrowed conversation writer before sqlite3.connect. That fence pins its exact
object identity and original process; copied or fork-inherited fences cannot
acquire, prove ownership or retire the original connection. Cleanup on the actual
owner remains possible after its admission deadline or source quarantine. Each
held fence admits exactly one original source transaction before creation, file
inspection or SQLite connect, even across distinct store objects. It retains
that exact owner strongly until rollback/checkpoint, real SQLite close, final
descriptor inspection and profile cleanup have finished. A rejected second
owner cannot inspect the source files or release another binding. Fence
retirement refuses while a source binding remains. Source transactions also
pin their own process/object identity; copied/inherited contexts cannot use or
retire the original handles. Release is cleanup-only and clears only the exact
owner, so an interrupted old retirement retry cannot release a later owner. A cached V1 instance cannot
bypass that requirement after migration; version discovery may itself recover WAL
or SHM. This tightens an internal call signature while preserving V1 payloads.
Ordinary open/read never migrates. Interrupted migration rolls back or reopens as
one complete recognized version. Unsupported/corrupt stores remain unavailable.

Both owned SQL executors capture a returned cursor before their post-SQL deadline
check. If that check interrupts, cleanup explicitly closes the retained cursor
before rollback or connection close; a close failure preserves the cursor and its
scope for retry. Fixed cleanup PRAGMAs likewise retain their cursor until the next
cleanup query or final close. Python's closed-connection state alone is not proof
of SQLite retirement while a statement remains unfinalized: close_v2 can defer
actual closure. Only after owned cursors and the exact connection retire may the
source profile inspect descriptors or release the conversation binding. An error
traceback holding the original cursor must not extend that physical lifetime.

Reserved/unclaimed is implicit in a validated reservation without a lifecycle or
manifest. Persisted lifecycle states are receiving, sealed, parsing, staged, complete
and failed. Bounded inventory validation rejects every orphan/mismatched lifecycle
or manifest before reference lookup or claim recovery. Both server-minted raw/normalized basenames are fixed in the durable claim before
file creation. Their names identify expected locations, not proof of file ownership;
exact identities are recorded in a subsequent fenced step before accepting bytes.
The transition rules are:

- Reserved/unclaimed → receiving only by a current fenced durable claim with the
  full peak quota and one receiver slot.
- Receiving → sealed only after exact EOF, length and digest. Invalid input moves
  toward failed cleanup; another receiver cannot resume it.
- Sealed → parsing only with the shared parser slot; a busy slot leaves sealed
  retryable under the unchanged deadlines.
- Parsing → staged only after the child actually retires and bounded normalized
  output is verified. Parser failure moves toward failed cleanup.
- Staged → complete only through the commit-admission transition, durable file
  sequence and final fenced manifest COMMIT. In-memory progress cannot substitute
  for that row. Completion never transitions backward.
- Any pre-publication state → failed only with publication excluded and owned work
  actually retired; until then retain a cleanup-pending marker and conservative
  capacity. An unknown COMMIT is reconciled before choosing complete versus failed.
- Restart treats all unfinished prior-generation states as non-resumable. It keeps
  any valid committed completion; otherwise it records failure after exact owned
  file cleanup. It never restarts a parser or accepts more chunks.

These durable phases support diagnosis/recovery; they do not grant read authority. Failed/expired upload identity remains a tombstone; no key recycling or
implicit retry. Completed manifests are immutable. Retain at most 1,024 upload
records and 128 completed manifests, with 4 MiB total logical metadata and bounded
per-record encoding (4 KiB lifecycle rows and 8 KiB manifests, with every scalar,
identifier and encoded byte charged). Terminal completion/failure stops consuming the two-incomplete-
upload admission slots only after the corresponding owner/cleanup is settled;
retained content still consumes its own capacity. Existing `reserve()` admission
must use this same rule: an unclaimed V1/V2 reservation counts while its upload
window is live; a claimed receiving/sealed/parsing/staged or cleanup-pending failure
counts until actual retirement is durably reconciled, even after expiry; complete
or fully retired failed rows consume retention/content quota but no incomplete
slot. A complete manifest with cleanup_pending remains a valid conservative
state. After positive receiver-token retirement, a separate fresh ordinary fenced
cleanup action may clear that marker using the exact original attempt/generation
and positive retirement proof tied to the exact originally captured receiver token
and owner. The metadata-only checkpoint cannot create this proof and refuses
acknowledgment or fully-cleaned failure; receiver ownership and independent
fresh-owner reconciliation implement those later gates. Failure to acquire it because of shutdown, authority, expiry
or quarantine keeps the complete manifest and its incomplete-slot charge until
authorized recovery or fresh-owner startup. Database update and token retirement
are never presented as one atomic action. The shared receiver-work limit remains
independent. No completed-content garbage
collector or deletion API is added now. At capacity, deny new work.

The same-process receiver qualification settles the exact original claim only.
A cleanup proof rejects a retained primary or abort fence and an active abort or
retirement action. Final token retirement has positive completion evidence, so
an after-effect interruption cannot invent an active token or erase a known
manifest. Unknown acknowledgment COMMIT remains separate from that known
completion. A current call captures its own grant; idle abort never inherits an
expired prior-call response window, and cleanup never renews original clocks.

The manager retains a directory-scan owner when closing an audit fails. Its
explicit scan-only retirement retries that exact iterator without closing the
root or any content descriptor. A known active sibling audit defers receiver
cleanup with its token retained; it does not by itself quarantine the lease.
Uncertain retirement still retains ownership and denies further admission.
Completed-file audit requires exact stored lengths; incomplete files remain
bounded by their reserved caps. A new claim is denied before file creation once
128 completed manifests are retained. The full three-MiB peak is reserved before
creation and only settled after actual receiver retirement is acknowledged.

### Exact lease-owned startup readiness

Startup readiness belongs to one registration on the actual current coordinator
lease. It is absent on a new lease. First registration is denied permanently on
that lease if any tagged source work was previously admitted, even if those
helper tokens later retired; ordinary metadata/maintenance borrows do not set
that history bit. A pending or failed registration denies every tagged admission,
including the direct parser/helper path. No replacement manager, store or
maintenance object may overwrite a registration or rerun its cleanup. Successful
readiness may be reused only with the same verified binding.

The bounded immutable binding contains exact account and target identifiers,
absolute store path plus database device/inode, current durable generation,
absolute content-root path plus directory device/inode. The maintenance owner
validates these facts while holding the existing Agent Run writer and source
transaction and its captured directory descriptor. The lease transition only
compares these captured trusted values and actual lease admission state; it never
runs SQL, directory scans, child waits or injected callbacks under the state mutex.
Later normal fences still check the durable generation after storage waits.

The ordinary maintenance borrow allocates an inert startup registration tied to
the exact original maintenance owner and token. The owner captures it before its
single acquire transition registers the pending attempt. Acquisition occurs before
root or reconciliation effects. The owner then captures its dedicated unopened
SnapshotFiles root owner before opening it, captures each file owner before its
acquisition, and retains all of them through failures. The startup-only retirement
order is recovery file owners, dedicated root/scan owner, source transaction and
checkpoint, conversation writer, then the original ordinary token. Unknown
retirement keeps those scopes and pending/failed registration; it cannot grant
readiness. Known manifest/COMMIT facts survive any later cleanup failure.

Only the original maintenance operation may request the final publication after
all its retained scopes positively retired. It retains the exact original token
for positive retirement proof. The short lease transition checks exact original
owner/registration/token identity, completed token retirement, the captured binding
and a physically held, non-closing, non-quarantined lease. Closing or quarantine
winning the retirement-to-publication gap leaves readiness absent. A before- or
after-effect publication exception latches admission denial without undoing known
database results; a new Python object cannot clear that denial. Copied and
fork-inherited objects fail before acquiring any copied mutex.

Managers require the immutable ready binding while opening their own captured
root, matching its actual directory identity and their verified store identity.
Tagged receiver/read admission passes that exact binding atomically to the lease;
missing/mismatched readiness rejects before a work token is admitted. A parser
created by a receiver passes the same binding. Direct isolated helper use without
a binding remains compatible only when no startup registration exists; it records
tagged-work history and therefore precludes later startup on that same lease.
Once any startup attempt exists, helper admission also requires matching readiness.
Readiness is only storage-lifecycle proof: every operator/conversation/source
reference check still uses the established authority fences.

Fresh-process startup owns a fresh legitimate lease/generation and reconciles all
unfinished claims before accepting new reception. It never replays reception or
parsing. Incomplete claims become failed; only positively removed owned staging
files release their capacity. Complete manifests require exact present content;
missing/corrupt/replaced content is unavailable. Unknown files or cleanup uncertainty
quarantine admission rather than deleting unrecognized data.

The actual issuer is the single-attempt
`SourceStoreOwner.reconcile_snapshots(SnapshotFiles(root))` operation after explicit
store open/V2 migration. One original maintenance owner permanently claims each
ReservationStore object without I/O; a second owner is rejected before taking
ownership, and copied/forked stores reject before their local mutex. A replacement
store object is the explicit recovery route. An uninstalled registration loser
with no root/SQL/file effects may retire only its original borrow without poisoning
the winner; an installed or uncertain attempt remains denying.

The entire bounded lifecycle inventory is checked for current/newer generations,
and the entire directory is audited, before any deletion is selected. Missing
paths are distinct from existing paths lacking durable identity. Protected complete
owners verify raw hashes and canonical normalized values; incomplete recovery
owners require exact original identity or positively observed absence and directory
synchronization. The exact captured row, transaction, original maintenance token
and original file owner's verified disposition form a private settlement proof.
It rejects copied/cross-row/receiver proofs. Settlement never changes a complete
manifest or its original lifetime. Partial deletion followed by a process death
can be retried under a fresh generation; names alone never authorize deletion.

The original two-second reconciliation budget covers acquisition, inventory,
materialization, COMMIT and retirement. It is checked after all resources retire
before readiness publication and again afterward; a late transition latches denial
while preserving known database results. Crash qualification opens source SQLite
first through the real maintenance owner, including pending WAL recovery. Test
observations that open SQLite earlier are limited fixture evidence, not proof of
this first-opener boundary.

Private reads keep one exact PRIVATE_READ token, binding and generation across
both ordinary authority/conversation fences, materialization and retirement.
Each fence audits bounded inventory; completed same-key receipt recovery uses this
same verified read path with its already captured manifest, deadline and minimum
expiry. It cannot repin to new readiness or renew an earlier grant. Known active
retirement defers cleanup; uncertain scan acquisition or resource retirement retains
the lifetime and latches shared quarantine, including explicit manager.close.
Positive final-token retirement remains recorded through ordinary or control-flow
exceptions. Closed clock checks after cleanup apply to both values and
metadata-dependent errors. No private value, lazy reader or live scope escapes
before that final response gate.

## Managed storage capacity prerequisite

The preserved 16 MiB content budget counts raw, normalized, quarantine, publication
and cleanup temporary bytes across every retained and in-flight snapshot. Reserve
worst-case simultaneous raw plus normalized space before creating files; incomplete
cleanup keeps that reservation. Recompute inventory/accounting under ownership,
including every retained/staged/cleanup file length. Also measure allocated blocks
and fail closed on observed overage; this is detection, not a proven peak allocation
quota. Logical counters alone cannot release space. Raw and normalized bytes have distinct
identities; neither grants ownership or cross-account deduplication.

SQLite database/WAL/SHM/temp overhead has a separate explicit managed-file-length
budget in addition to the 4 MiB logical metadata policy. The candidate mechanism uses verified 4096-byte pages and at most 4096 database
pages (16 MiB), disabled dirty-page spilling on the
source-only connection, no attached/temp disk databases, and worst-case WAL space
reserved before any metadata write. All legitimate writers hold the same Agent
Run fence. Before every mutating transaction, require a completed TRUNCATE checkpoint
(including a non-busy result) and verified empty WAL while the Agent Run writer
excludes other legitimate metadata writers. A busy checkpoint fails closed.
Reserve the maximum dirty-page frame set, sync-sector padding and SHM rounding
in advance; do not assume that `journal_size_limit` limits peak WAL growth.
Startup/crash handling must include any existing WAL, never pretend it vanished.
A post-write size check by itself is not enforcement. The bound must cover
creation/migration, existing reserve(), lifecycle/failure/recovery writes,
checkpoint and sidecars created by crash-open recovery. Verify page/max-page,
spill, temp, auto-vacuum and automatic-index settings on every connection. Reject oversized/incompatible
existing geometry without automatic VACUUM or rewriting it. Qualification must
record the actual SQLite version (currently 3.53.1), selected VFS and filesystem;
it is not automatic evidence for other packaged deployment runtimes.

### Candidate supported runtime and numerical envelope

The first profile is deliberately narrow: Linux, explicit built-in `unix` VFS,
SQLite 3.53.1 with source ID
`c88b22011a54b4f6fbd149e9f8e4de77658ce58143a1af0e3785e4e6475127e9`,
and the recorded compile profile. Runtime admission checks the exact source ID
and relevant compile options before opening a source store, using a private
in-memory connection. It does not infer compatibility from the version string
alone. No replacement/custom VFS, page-cache extension, runtime extension loading
or SQLite global reconfiguration is supported. Different packaged runtimes remain
unqualified until separately reviewed. No production C/ctypes probe is introduced.

Every source connection verifies page size 4096, max pages 4096, WAL/FULL,
cache spilling off, memory temp storage, automatic checkpointing off, mmap off,
trusted schema off and automatic indexes off. New stores set auto-vacuum NONE
before creating schema; migration requires existing auto-vacuum NONE and rejects
other geometry without changing it. Automatic or explicit VACUUM, attached DBs,
backup/serialize APIs, arbitrary SQL, triggers and extension-defined storage are
absent. Memory pressure fails the operation rather than enabling spill.

With an empty WAL and one non-spilling dirty-page set per transaction, the maximum
is 4,096 page frames. At 4,120 bytes per frame plus the 32-byte header, and reserving
16 additional complete frames for a conservative 65,536-byte sync-sector crossing,
the WAL file-length envelope is 16,941,472 bytes. The first WAL-index block covers
4,062 frames and the next covers 4,096, so 4,112 total frames require at most two
32 KiB SHM blocks. Combined with a 16,777,216-byte DB, this is 33,784,224 managed
file bytes. Reserve a fixed **34 MiB metadata data-file envelope**
(35,651,584 bytes) before store creation/open, separately from the 16 MiB content
budget. This includes all admitted DB/WAL/SHM files concurrently, not just the
logical row payload. The surplus is not permission for an extra writer or WAL.

The frame calculation is a source-based inference under that restricted write
profile, not a bound inferred from a sampled peak. SQLite's pinned
[pager implementation](https://raw.githubusercontent.com/sqlite/sqlite/version-3.53.1/src/pager.c)
clamps the effective sector to 64 KiB and suppresses the spill path when spilling
is off. Its commit path consumes the dirty page list; no admitted API flushes it
earlier. The pinned
[WAL implementation](https://raw.githubusercontent.com/sqlite/sqlite/version-3.53.1/src/wal.c)
defines frame/header sizes, complete-frame padding and SHM indexing. The
[page-cache implementation](https://raw.githubusercontent.com/sqlite/sqlite/version-3.53.1/src/pcache.c)
maintains the unique cached dirty-page list. The source ID matches the published
[release manifest](https://raw.githubusercontent.com/sqlite/sqlite/version-3.53.1/manifest.uuid).

Pre-open inventory checks bounded file/header geometry before SQLite can perform
recovery: DB size/alignment, bounded main-header page count and known format;
WAL length, exact supported header/page size and at most 4,112 complete frames,
with each big-endian page number 1–4,096 and commit-size field 0–4,096; SHM length;
private identities and absence of a nonempty rollback journal. This bounded
geometry scan interprets no schema/version/rows and performs no repair. Unsupported
torn geometry may remain quarantined. Hold/check descriptor identities through it. Reject
oversized, unknown or incompatible artifacts without opening them for repair.

Descriptor inspection is strictly a pre-connect or positively post-retirement
phase. The profile retains its inspection owner before opening any file; uncertain
cleanup blocks a second inspection and has an explicit close/retry path for only
the exact captured handles. Configure binds the caller's exact real SQLite
connection and the inspected path. While that connection is live, inventory uses
stat-only checks and captures newly created sidecar identities on first observation;
replacement, disappearance or overage denies. It must never open and close another
DB/WAL/SHM descriptor: POSIX record locks can be lost when another descriptor for
that same file closes. The pinned [unix VFS](https://raw.githubusercontent.com/sqlite/sqlite/version-3.53.1/src/os_unix.c)
explicitly defers its own closes for that reason. An independent-process DMS lock
witness qualifies this distinction. The profile never closes the caller's disk
connection. On the same process/thread, the supported real initialized connection's
`in_transaction` property raising `ProgrammingError` is closed-handle evidence;
`False` remains a live handle, and proxy/uninitialized/thread errors are not proof.

Every admitted source connection is a first owner after all previous connections
have positively retired under the Agent Run writer. In the pinned unix VFS, that
first opener obtains the SHM deadman-switch lock and truncates the old mapping to
three bytes before rebuilding it; a competing exclusive lock returns busy. A
fresh-process crash fixture with bounded corrupt cached SHM qualifies this path.
Arbitrary external SQLite participants or retained cached mappings are outside the
admitted profile. The generic pinned-reader refusal test is separate evidence and
does not relax exclusive ownership. An uncertain old connection prevents replacement.

Fresh empty-file initialization is separately qualified; all later schema and
migration writes already use WAL. Rebuilding SHM and checkpointing existing WAL
must fit the same reserved envelope. Verify a successful empty-WAL checkpoint
before another mutation; on busy/error, retain existing bytes and deny that write.
Every successful and failed mutation retires its captured connection and checks
its actual file inventory before releasing the writer fence. An accounting or
checkpoint failure quarantines further ingress; no automatic retry appends a
second dirty set. Known COMMIT remains recorded even when this later check fails.

This slice caps all application-managed file lengths, including SQLite overhead
and every retained/in-flight content file. It also measures `st_blocks` and rejects
further source work on observed allocated-block overage. A post-write observation
cannot establish or enforce a peak allocated-block guarantee. In particular, a
reported 4 KiB statvfs unit is not a valid destination-admission proof. No hard
filesystem, CoW, underlying journal, speculative-allocation or whole-volume quota
is claimed. Such enforcement belongs to the later deployment/storage profile.

Content claims reserve the maximum simultaneous raw plus normalized file lengths
before creation; actual lengths are checked through the pinned descriptors and
bounded writes. Every staged/cleanup file remains charged, and sparse holes or
deduplication never reduce that charge. An observed allocation anomaly retains
conservative accounting and quarantines further work. The 34 MiB metadata bound
and separate 16 MiB content bound are managed-byte limits for this synthetic
internal slice; public admission remains disabled.

### Disposable feasibility evidence and remaining proof

A bounded generic-pager experiment used synthetic BLOB rows only, not the future
V2 metadata schema. With the explicit profile and powersafe-overwrite disabled,
a 4,032-page database update produced 16,570,672 WAL bytes, including a repeated
padding frame; allocated WAL blocks totaled 16,572,416 bytes. A pinned reader
returned a busy checkpoint, no next mutation occurred, and releasing it allowed
a successful truncation to zero. Separate page-ceiling/rollback and before/after-
COMMIT process-death fixtures behaved as expected. The experiment retired cleanly
in 0.405 seconds / 18.391 MiB under the shared 90-second / 512-MiB supervisor.
Sampled peaks are observations, not a proof for all writes or storage systems.

An isolated attempt to measure `xSectorSize` through the installed SQLite C ABI
failed because this Python embeds SQLite without exported symbols. That failed
receipt is retained. The conservative source-derived 64 KiB bound above does not
claim a measured device sector and does not substitute another system library.

This mechanism and its numerical worst-case geometry are a **design proof gate**,
not product-qualified yet. The implementation plan must prove this managed-byte bound with the real V2 schema
and all mutation/recovery paths before admitting content. Allocated-block diagnostics
must retain their separate limitation; they cannot silently become a physical quota
claim. Prefer conservative fixed metadata overhead to an unproved tight bound. The source DB is
metadata-only; no content BLOBs, VACUUM, arbitrary SQL, SQL extension or automatic
index/schema maintenance is admitted. Whole-filesystem quotas, snapshots/CoW and
hostile storage are not claimed to be controlled by this application ledger.

SQLite primary references: [page limit](https://www.sqlite.org/pragma.html#pragma_max_page_count),
[dirty-page spilling](https://www.sqlite.org/pragma.html#pragma_cache_spill),
[checkpoint semantics](https://www.sqlite.org/pragma.html#pragma_wal_checkpoint),
[WAL growth](https://www.sqlite.org/wal.html#avoiding_excessively_large_wal_files).
These document individual mechanisms; the proposed composition still needs proof.

## Required qualification and deferred surfaces

The serial plan must first prove schema/managed-byte accounting and the bounded codec,
then receiver ownership, parser retirement, terminal publication/recovery and reads.
At each checkpoint preserve actual RED evidence and use an independent exact-head
gate before the next shared lifecycle change.

Required cases include complete valid content; every strict CSV cap; duplicate
claims/chunks/finish and conflicting retry; no progress/whole-expiry/abort; authority
changes at each boundary; same ID with changed target key; concurrent shutdown;
parser crash/hang/resource/output faults without touching unrelated children;
file identity/symlink/hardlink/exclusive-create failures; disk-full and failed fsync;
observed allocated-block overage without claiming pre-write physical enforcement;
process death before/after claim, file creation, identity recording, file/directory
fsync and DB commit; unknown COMMIT;
retained quota after failed cleanup; pinned WAL readers; old-store migration;
immutable old snapshot reads through later successful/failed uploads; and canary-
safe errors/logs/count-only receipts. No test may imply a failed upload is readable.

Deferred: public source identifiers and tools, upload capabilities, HTTP/relay/
proxy buffering and CSRF, browser ceremony, production account/epoch/key authority,
semantic mapping/model schema, source selection/run pinning, shipping answers,
previews/execution, exports, encryption provisioning, real clients and deployment.
The held headless publication scenario is not part of this work.
