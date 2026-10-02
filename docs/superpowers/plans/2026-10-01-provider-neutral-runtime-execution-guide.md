# Provider-neutral runtime ticket execution guide

The approved work breakdown implements [spec #30](https://github.com/matt-hans/ShipAgent/issues/30).
All tickets are labeled `ready-for-agent`; the label means their specification
is ready, not that their blockers are complete. GitHub native blocking links
and each ticket's acceptance criteria govern the execution frontier.

## Ticket inventory

| Step | Ticket | Blocked by |
| --- | --- | --- |
| 1 | [#31 Preserve and reconcile the findings branch](https://github.com/matt-hans/ShipAgent/issues/31) | None |
| 2 | [#32 Validate and integrate the reconciled baseline](https://github.com/matt-hans/ShipAgent/issues/32) | #31 |
| 3 | [#33 Make shared policy decisions provider-neutral](https://github.com/matt-hans/ShipAgent/issues/33) | #32 |
| 4 | [#34 Run streamed Anthropic conversations through the shared runtime](https://github.com/matt-hans/ShipAgent/issues/34) | #33 |
| 5 | [#35 Complete Anthropic tool-call and continuation workflows](https://github.com/matt-hans/ShipAgent/issues/35) | #34 |
| 6 | [#36 Preserve batch previews and confirmed execution](https://github.com/matt-hans/ShipAgent/issues/36) | #35 |
| 7 | [#37 Preserve interactive shipping and auxiliary workflows](https://github.com/matt-hans/ShipAgent/issues/37) | #35 |
| 8 | [#38 Preserve history, interruption and safe provider switching](https://github.com/matt-hans/ShipAgent/issues/38) | #35 |
| 9 | [#39 Enforce privacy across prompts, results and audit](https://github.com/matt-hans/ShipAgent/issues/39) | #35 |
| 10 | [#40 Switch every entry point and remove the Claude Agent SDK](https://github.com/matt-hans/ShipAgent/issues/40) | #36, #37, #38, #39 |
| 11 | [#41 Verify the complete SDK-free release candidate](https://github.com/matt-hans/ShipAgent/issues/41) | #40 |

## Sequential foundation

Run steps 1–5 in order. Finish each acceptance gate and integrate its reviewed
change before starting the next ticket. The first two establish a validated
baseline from the existing findings branch; do not create new competing copies
of that work. Preserve unrelated local edits and the planning documents.

Reconciliation may reveal context-sized follow-up fixes. Declare those as
additional blockers of #32 before progressing. Integration PRs do not override
repository merge policy. This guide does not authorize deployment or purchases.

## Parallel workflow lanes

After #35 is integrated and validated, record its baseline commit and start
#36–#39 from that same commit using separate branches/worktrees. One agent owns
each ticket and its acceptance criteria. Fewer agents may execute the same
frontier sequentially; four concurrent agents are optional.

Coordinate common contracts before editing shared modules. Batch and interactive
lanes own their workflow behavior and scenario tests; the lifecycle lane owns
history/interruption/switching; the privacy lane owns prompt/result/audit
projection. This is coordination of vertical slices, not exclusive ownership of
entire layers. When two lanes need the same shared runtime or dispatcher change,
agree on one owner and integrate that common change first. Record any newly
discovered blocking edge rather than racing contradictory implementations.

Land reviewed lane PRs one at a time. Update each remaining branch from the
latest integrated baseline and rerun affected checks before merging. An agent
reporting completion is not sufficient: the ticket's behavior must be present
and validated in the common baseline.

## Cutover and final verification

Start #40 only after all four lane outcomes are integrated. Switch selectors and
entry points, then delete SDK compatibility and operational coupling, keeping
intermediate changes green. If migration exceeds a fresh context, split bounded
expand/migrate/contract follow-ups and track them as blockers.

Run #41 on the final integrated commit. Verify clean installation, API/CLI
behavior, desktop packaging/startup and the shared acceptance matrix without
the SDK. Update the roadmap with exact evidence and remaining limitations.
Historical test reports do not replace these gates. Leave parent issue #30
unchanged during ticket publication/execution coordination; completion of its
implementation does not complete the cloud connector roadmap.

## Suggested agent assignment

Assign one ticket and its issue URL per agent, with the baseline commit and
repository instructions. Require it to read the parent spec and blockers,
implement only the assigned scope, verify observable behavior at the shared
conversation boundary, and deliver a reviewed PR with evidence. Blocked tickets
must not be started merely because they carry `ready-for-agent`.
