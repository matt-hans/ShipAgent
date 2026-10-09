# Historical design and predecessor recovery

This archive preserves allowed local-only material that predates the reviewed
implementation on main. It is historical WIP, not merge approval, current product
behavior, or a request to run old or incomplete tests.

## Uncommitted source-ingress design

The three `original`/`_red.py` files are exact copies of the earlier contract,
probe README and opt-in RED probe. Their original paths and hashes are in
[source-map.json](source-map.json). They were written against local `c391e8c`;
public commit `8199d0f195edf1a5f6ad8d4d6d51b84e5cbc12da` has that exact base tree.
The last historical run produced 47 expected missing-feature failures, zero
passes. It was design evidence, not a qualified source-ingress feature.

These files are archived under `docs/recovery` to keep their historical claims
and deliberate failures outside current default test collection. The current
internal reservation and snapshot implementation subsequently shipped in PR91
and PR92. Those later source trees and their current design/plan documents remain
the implementation baseline. This original proposal does not supersede them or
establish public upload authority, actual-client readiness, or a production quota.

To reconstruct the original design worktree in a separate disposable checkout,
start from the public equal-tree base above, then copy each archived file to its
`original_path` in the source map. Do not treat its old harness instructions as
current commands without reviewing the recorded prerequisites.

## Superseded continuation predecessor

Seven of the eight dirty predecessor files exactly match the reviewed public
successor `f5740a572f8dfd901eaf8eeb4746ff2cf95c261b` from PR88. The remaining
working-file difference and the distinct staged service version are preserved
as two separate patches, each based on that public successor:

- `continuation-predecessor-working.patch` reconstructs the old working service
- `continuation-predecessor-index.patch` reconstructs its old staged service

Apply each patch only in its own disposable checkout of the public successor.
The source map records the exact working, staged and successor SHA-256 values.
Both patches were checked for applicability and exact reconstructed hashes.
They preserve drafting history; the reviewed successor remains authoritative.
No original local worktree, index or reference was modified for this archive.
