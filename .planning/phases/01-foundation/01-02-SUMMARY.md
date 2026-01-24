# Phase 01 Plan 02: Job Service Summary

## One-Liner

JobService with state machine validation, per-row tracking, and auto-updating counts for crash recovery.

---

## Overview

| Attribute | Value |
|-----------|-------|
| **Phase** | 01-foundation |
| **Plan** | 02 |
| **Type** | execute |
| **Status** | Complete |
| **Duration** | ~3 minutes |
| **Completed** | 2026-01-24 |

---

## What Was Built

### JobService Class (`src/services/job_service.py`)

A comprehensive service layer for job lifecycle management providing:

1. **Job CRUD Operations**
   - `create_job()` - Create new jobs with name, command, description, mode
   - `get_job()` - Retrieve job by ID
   - `list_jobs()` - List jobs with optional status filter and pagination
   - `delete_job()` - Delete job with cascade to rows and logs

2. **State Machine Validation**
   - `VALID_TRANSITIONS` map defining allowed state changes
   - `can_transition()` - Check if transition is valid
   - `update_status()` - Transition with validation, raises `InvalidStateTransition`
   - Automatically sets `started_at` on first run, `completed_at` on terminal states

3. **Job Metrics**
   - `update_counts()` - Update row counts (total, processed, successful, failed)
   - `set_error()` - Set error code and message on job

4. **Per-Row Tracking** (for crash recovery)
   - `create_rows()` - Bulk create rows with checksums
   - `get_row()`, `get_rows()` - Query rows
   - `get_pending_rows()`, `get_failed_rows()` - Convenience queries
   - `start_row()` - Mark row as processing
   - `complete_row()` - Mark complete with tracking number, label path, cost
   - `fail_row()` - Mark failed with error details
   - `skip_row()` - Mark skipped for retry scenarios

5. **Aggregation**
   - `get_job_summary()` - Returns comprehensive metrics including calculated pending count and total cost

### InvalidStateTransition Exception

Custom exception with full context:
- `current_state` - Where the job is
- `attempted_state` - Where it tried to go
- `allowed_transitions` - Valid targets from current state

---

## Key Files

| File | Purpose |
|------|---------|
| `src/services/__init__.py` | Service layer exports |
| `src/services/job_service.py` | Job CRUD, state machine, row tracking |

---

## State Machine

```
pending -> running -> completed (terminal)
                   -> failed (terminal)
                   -> cancelled (terminal)
                   -> paused -> running
                            -> cancelled (terminal)
```

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src.db.models` | Job, JobRow, JobStatus, RowStatus |
| `src.db.connection` | Session for database operations |

---

## Verification Results

All 7 success criteria verified:

1. Jobs created with all required fields
2. State transitions validate correctly
3. Invalid transitions raise exception with details
4. Rows created, tracked, and updated per-row
5. Job counts auto-update on row completion
6. `get_job_summary()` returns accurate metrics
7. Failed rows can be queried for retry

---

## Commits

| Hash | Message |
|------|---------|
| 40ac423 | feat(01-02): create JobService with CRUD and state machine |

---

## Deviations from Plan

None - plan executed exactly as written.

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Combined Task 1 and Task 2 implementation | Row tracking methods are logically part of JobService, no benefit to splitting |
| Use SQLAlchemy `func.sum()` for cost aggregation | Database-level aggregation more efficient than Python loop |
| Helper `_utc_now_iso()` function | Consistent timestamp generation matching models.py pattern |

---

## Next Phase Readiness

- **Provides:** JobService class for job lifecycle management
- **Required by:** Plan 01-03 (Audit Service), Plan 01-04 (Error Handling)
- **Blockers:** None
- **Concerns:** None

---

*Generated: 2026-01-24*
