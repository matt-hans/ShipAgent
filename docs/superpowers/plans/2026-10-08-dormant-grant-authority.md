# Dormant Grant Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task; lifecycle protocol work is independently scoped and the frozen branch receives independent review.

**Goal:** Complete the dormant real-store authority/recovery prerequisite in issue 67.

**Architecture:** Extend Plan 4 state and hashed ledger APIs; bind one fenced authority reservation to Plan 2 lifecycle callbacks. Keep all production application wiring dormant.

**Tech Stack:** Python, redis.asyncio, PostgreSQL/SQLAlchemy, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-dormant-grant-authority-design.md`

## Global Constraints

- Grant and approval lifetime at most 900 seconds; lifecycle/job reference at most 86400 seconds.
- No raw PII, carrier payloads, labels, URLs, prompts or credentials in SQL.
- No real shipping/paid API, hosted enablement or mandatory local cloud dependencies.
- Target idempotency and durable acceptance are authoritative; ambiguity never releases.

## Review Focus

- Delayed Redis writes after SQL commit/account deletion cannot create live authorization.
- Lease or authorization expiry during acceptance never permits a second effect.
- Old generation callbacks and target sends cannot affect a positively authorized retry.
- Lost Redis grant state cannot be rebuilt from approval metadata or SQL evidence.
- Gate ownership and lifecycle callbacks share a single reservation and accepted result semantics.

## Task 1: Typed state and real authority

Files: `grant_models.py`, `authorization_state.py`, `grant_ledger.py`,
`redis_grant_authority.py`, `tests/control_plane/persistence/test_grant_authority.py`.
Produces strict approved purchase/state, internally minted approval IDs, bounded
`RedisExecutionGrantAuthority.reserve(...)` and fenced reservations.

- [ ] Write and run failing real-store tests for issue/reserve/races, live binding drift, hashed ledger commit-before-enable and original TTL.
- [ ] Implement strict allowlisted grant payload in the existing state record and atomic deadline-aware CAS.
- [ ] Implement dormant real authority, PostgreSQL transaction adapter and inert publication protocol.
- [ ] Verify ordinary consume/release/hold fencing, lost replies, cancellation, deletion and revocation with targeted tests.
- [ ] Commit and push atomic verified checkpoints.

## Task 2: Shared lifecycle attempts and authority callbacks

Files: `relay/protocol.py`, `relay/lifecycle_store.py`, `relay/lifecycle.py`,
existing deterministic target helper and focused retry/authority recovery tests.
Consumes Task 1 ownership; produces explicit safe retry preserving all purchase
identity, job references and deadlines.

- [ ] Write/run failing attempt-generation and stale-dispatch tests.
- [ ] Implement additive explicit retry and target evidence generation fencing in the shared lifecycle.
- [ ] Add authority callbacks sharing one reservation and exact durable evidence recovery.
- [ ] Verify accepted expiry/restart recovery, rejection retry and old callback fencing against real stores.
- [ ] Commit and push coherent checkpoints.

## Task 3: Process proof and final review

Files: new authority process utility/tests and component/control-plane docs.

- [ ] Exercise independent authority processes, target/application restart, post-write lost replies and one effect per purchase.
- [ ] Update contracts and remaining issue 51 acceptance obligations accurately.
- [ ] Run focused tests, lint, migrations and guarded broad suite; report explicit skips.
- [ ] Open a draft PR, obtain clean independent frozen-head review, address findings with regressions, and return exact tested SHA to parent for merge.
