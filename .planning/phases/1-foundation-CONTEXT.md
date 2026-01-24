# Phase 1: Foundation and State Management — Context

## Overview

This document captures implementation decisions for Phase 1. Downstream agents (researcher, planner, executor) should treat these as locked decisions, not open questions.

**Phase Goal:** Persistent state infrastructure, audit logging, and error handling foundation that all subsequent phases build upon.

---

## Job Lifecycle & States

### Job States

| State | Description | Transitions To |
|-------|-------------|----------------|
| **Pending** | Job created, not started | Running |
| **Running** | Actively processing rows | Paused, Completed, Failed, Cancelled |
| **Paused** | Browser disconnected, awaiting resume | Running, Cancelled |
| **Completed** | All rows succeeded | (terminal) |
| **Failed** | Error encountered, partial results preserved | (terminal, but supports retry) |
| **Cancelled** | User stopped job | (terminal) |

### Key Decisions

- **Job creation timing:** Depends on user setting (auto mode = immediate, confirm mode = after preview approval)
- **Concurrency:** One job at a time per user
- **Pause behavior:** Browser disconnect pauses job; waits indefinitely for user return
- **Pause timeout:** None — job waits indefinitely until user reconnects
- **Failed state:** Preserves which rows succeeded vs failed (per-row status tracking)
- **Retry capability:** Failed jobs can retry failed rows only (not full restart) — Phase 1 schema must support this, Phase 6 implements logic
- **Cancel behavior:** User can cancel running job; already-created shipments require manual void at UPS.com
- **Job naming:** User can customize name and description
- **Job details:** Comprehensive — original command, row counts, costs, failure details

### Deferred Ideas

- **Save job as reusable template** — good feature, defer to post-MVP

---

## Audit Log Structure

### Key Decisions

- **Audience:** Developers + end users troubleshooting problems
- **Scope:** Job-specific logs only (each log entry tied to a job)
- **Detail level:** Full UPS API request/response payloads
- **Export format:** Plain text (human-readable)
- **UI access:** Export only — no in-UI search/filter (external tools for search)
- **Sensitive data:** Redact with `[REDACTED]` placeholder (addresses, names, account numbers)
- **Retention:** Same policy as job history

### What Gets Logged

- Job state transitions (created, started, paused, completed, failed, cancelled)
- Each UPS API call (full request/response, with sensitive data redacted)
- Errors encountered (with context)
- Row processing events (started row N, completed row N, failed row N)

---

## Error Message Design

### Key Decisions

- **UPS error translation:** Translate raw UPS errors to friendly, actionable messages
- **Translation approach:** Maintain curated list of common UPS errors with custom messages
- **Location specificity:** Point to specific row/column for user-fixable errors (e.g., "Row 47, column 'zip_code': Invalid format")
- **System errors:** Provide maximum detail about what's happening (user can't fix, but needs to understand)
- **Timing:** Errors appear immediately (blocking) when batch fails
- **Error codes:** Include unique codes for support reference (e.g., E-1042)
- **Grouping:** Same errors across multiple rows grouped together (e.g., "Rows 5, 12, 34: Missing ZIP code")

### Error Code Format

`E-XXXX` where XXXX is a 4-digit code. Maintain registry of codes with meanings.

### Example Error Messages

**User-fixable (data issue):**
```
E-2001: Invalid ZIP code format
Rows 5, 12, 34, 47 have invalid ZIP codes.
US ZIP codes should be 5 digits (12345) or 9 digits (12345-6789).
Please correct these values in your spreadsheet and retry.
```

**System error (UPS API):**
```
E-3005: UPS service temporarily unavailable
The UPS Rating API is not responding. This is a UPS system issue.
Status: HTTP 503 Service Unavailable
Recommendation: Wait a few minutes and retry. If the problem persists, check UPS system status at ups.com.
```

---

## Job History Access

### List View

- **Default sort:** Most recent first
- **Filters available:** Status (completed/failed), date range, job name
- **Date range options:** Presets ("Today", "Last 7 days", "Last 30 days") + custom date picker
- **Columns displayed:** Name, status, date, row count, cost

### Detail View

- **First view:** Business summary (total cost, shipments processed, success/fail counts, key metrics)
- **Row details:** Paginated for large jobs (500+ rows)
- **Available data:** Original command, full row-by-row results, error details, timestamps

### Management

- **Deletion:** Users can delete old jobs from history (not immutable)
- **Retention:** Configurable (define default in implementation)

### Deferred Ideas

- **Side-by-side job comparison** — good feature, implement in Phase 7 (Web Interface)

---

## Implementation Notes for Downstream Agents

### Schema Requirements

The state database schema must support:
1. Job record with all states (pending, running, paused, completed, failed, cancelled)
2. Per-row status tracking (for retry failed rows capability)
3. Job metadata (name, description, original command, timestamps)
4. Aggregate metrics (row count, cost, success/fail counts)
5. Relationship to audit logs

### API Requirements

Phase 1 should expose:
1. Create job
2. Update job state
3. Get job by ID
4. List jobs with filters (status, date range, name)
5. Delete job
6. Export job logs (plain text)

### Error Handling Requirements

1. Error code registry (E-XXXX format)
2. UPS error translation map (raw code → friendly message)
3. Row/column location tracking for data errors
4. Error grouping logic (same error across rows)

---

*Created: 2025-01-23*
*Phase: 1 - Foundation and State Management*
