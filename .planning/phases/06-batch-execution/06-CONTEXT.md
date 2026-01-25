# Phase 6: Batch Execution Engine — Context

## Overview

This document captures implementation decisions for Phase 6. Researchers and planners should treat these as constraints, not suggestions.

**Phase Goal:** System processes batches of shipments with preview mode, fail-fast error handling, and crash recovery.

**Requirements:**
- BATCH-01: System processes batches of 1-500+ shipments in a single job
- BATCH-02: User can preview shipment details and total cost before execution (confirm mode)
- BATCH-03: User can skip preview and execute immediately (auto mode)
- BATCH-04: User can toggle between confirm mode and auto mode
- BATCH-05: System halts entire batch on first error (fail-fast)
- BATCH-06: System tracks per-row state for crash recovery
- DATA-04: System writes tracking numbers back to original data source after successful shipment

---

## Decision 1: Preview Experience

**Question:** What does the preview show and how does it handle large batches?

**Decision:**
- **Detail level:** Summary table per shipment (row number, recipient name, city/state, service, estimated cost)
- **Large batches:** Show first 20 rows in detail, then "... and N more" with aggregate stats
- **Cost display:** Per-row cost shown, plus batch total at bottom
- **Validation:** Flag rows with warnings (e.g., address corrections suggested)

**Rationale:** Users need enough detail to verify the batch is correct without being overwhelmed. Summary table fits terminal output. First 20 rows provides representative sample while aggregate stats confirm full scope.

**Implementation Notes:**
- Preview table columns: `#`, `Recipient`, `City, State`, `Service`, `Est. Cost`, `Warnings`
- Truncate long names to fit terminal width
- Warnings column shows count of issues (e.g., "1 warning") — expandable on demand
- Aggregate footer shows: total rows, total cost, rows with warnings

---

## Decision 2: Mode Switching Behavior

**Question:** How do confirm mode and auto mode interact with sessions and batches?

**Decision:**
- **Default mode:** Confirm mode (preview before execute)
- **Switch scope:** Session-wide (applies to all subsequent batches in session)
- **Mid-preview switch:** Allowed — user can say "looks good, just run it" after seeing preview
- **Mid-execution switch:** Not allowed — mode locked during batch execution

**Rationale:** Confirm mode as default protects against accidental shipments. Session-wide scope is intuitive. Mid-preview switch enables efficient workflow ("preview once, then go"). Locking during execution prevents confusing partial-mode batches.

**Implementation Notes:**
- Store mode in session state (not persisted across sessions)
- Commands: `set mode confirm`, `set mode auto`, or flags on batch command
- When user approves preview, can include "and switch to auto" to reduce friction for subsequent batches
- Reject mode-change commands while batch is executing with clear message

---

## Decision 3: Crash Recovery UX

**Question:** How does the system behave when resuming after a crash?

**Decision:**
- **Resume behavior:** Prompt user with options — "Job X was interrupted at row 47/200. Resume, restart, or cancel?"
- **Restart option:** Allowed with warning about duplicate shipments for already-processed rows
- **Progress display:** Summary + last processed — "47/200 complete. Last: Row 47 (John Doe, tracking ABC123). 153 remaining."
- **Error context:** Show last error if crash was due to error — "Crashed at row 48 due to: UPS API timeout. Resume will retry row 48."

**Rationale:** Users need agency in recovery scenarios. Auto-resume might process rows user now wants to cancel. Restart option needed for "start fresh" scenarios despite duplicate risk. Summary + last processed gives confidence about state. Showing error context helps users decide whether to resume or investigate.

**Implementation Notes:**
- On startup, check for jobs in `executing` state
- Present interactive prompt with three options: Resume, Restart, Cancel
- Restart option shows confirmation: "Warning: Rows 1-47 already have tracking numbers. Restarting will create duplicate shipments. Continue? [y/N]"
- Store last error in job record for display on resume prompt
- Resume starts from first `pending` row (row 48 in example)

---

## Decision 4: Write-Back Semantics

**Question:** When and how are tracking numbers written back to the original data source?

**Decision:**
- **Timing:** After each successful row (immediate write-back)
- **Columns:** `tracking_number` and `shipped_at` timestamp
- **Write failure handling:** Log and continue, retry at batch end
- **Transaction scope:** For database sources, job state and source update in same transaction

**Rationale:** Immediate write-back ensures tracking numbers survive crashes. Two columns (tracking + timestamp) provide minimal audit trail without bloat. Non-blocking write failures prevent shipment success from being masked by source issues. Transactional consistency for DB sources prevents orphaned states.

**Implementation Notes:**
- CSV/Excel: Write to temp file, rename on success (atomic)
- Database: UPDATE within same transaction as job row state
- Failed write-backs queued in memory, retried after batch completes
- If retry fails, job marked `complete_with_warnings` and write failures logged
- `shipped_at` uses ISO8601 format consistent with Phase 1 decision

---

## Out of Scope

These topics were not discussed and should be handled during planning/research:

- Memory management strategy for 500+ row batches (technical implementation)
- Exact format of fail-fast error messages (covered by Phase 1 error framework)
- Rate limiting / throttling UPS API calls (technical implementation)
- Concurrency model (sequential vs parallel row processing) — assume sequential for MVP

---

## Deferred Ideas

No scope creep identified during discussion.

---

*Created: 2025-01-25*
*Status: Ready for research and planning*
