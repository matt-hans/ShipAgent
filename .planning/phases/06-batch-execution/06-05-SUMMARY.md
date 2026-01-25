---
phase: 06-batch-execution
plan: 05
subsystem: batch-execution
tags: [batch, recovery, crash-recovery, user-prompts]

dependency-graph:
  requires: ["06-03", "06-04"]
  provides: ["check_interrupted_jobs", "get_recovery_prompt", "handle_recovery_choice", "RecoveryChoice"]
  affects: ["06-06", "06-07"]

tech-stack:
  added: []
  patterns: ["running-state-crash-detection", "recovery-choice-enum"]

key-files:
  created:
    - src/orchestrator/batch/recovery.py
    - tests/orchestrator/batch/test_recovery.py
  modified:
    - src/orchestrator/batch/__init__.py

decisions:
  - id: "06-05-01"
    title: "Running state as crash indicator"
    choice: "Jobs in 'running' state indicate interrupted execution"
    rationale: "Normal completion transitions to completed/failed; running means interrupted"

metrics:
  duration: "4 minutes"
  completed: "2026-01-25"
  tasks: 3
  tests-added: 14
  total-tests: 81
---

# Phase 6 Plan 5: Crash Recovery Summary

**One-liner:** Recovery module detecting interrupted jobs via 'running' state with user-friendly prompts and resume/restart/cancel handling.

## What Was Built

### Recovery Module (178 lines)

Crash recovery utilities implementing CONTEXT.md Decision 3 requirements:

```python
class RecoveryChoice(str, Enum):
    """User choices for interrupted job recovery."""
    RESUME = "resume"
    RESTART = "restart"
    CANCEL = "cancel"

def check_interrupted_jobs(job_service: JobService) -> Optional[InterruptedJobInfo]:
    """Finds jobs in 'running' state - indicates crash."""

def get_recovery_prompt(info: InterruptedJobInfo) -> str:
    """Generates user-friendly recovery prompt with progress info."""

def handle_recovery_choice(
    choice: RecoveryChoice,
    job_id: str,
    job_service: JobService,
) -> dict:
    """Handles user's recovery choice with appropriate actions."""
```

**Key Features:**
- **Detection:** Finds jobs in 'running' state (crash indicator)
- **Progress info:** Shows completed/total rows, last tracking number
- **Error context:** Includes error code/message if crash was due to error
- **Recovery options:** Resume, Restart, Cancel with appropriate handling
- **Duplicate warning:** Restart warns about duplicate shipments for completed rows

### Recovery Prompt Format

```
Job 'California Orders' was interrupted at row 47/200.

Last completed: Row 47 (tracking: 1Z999AA10123456784)
Remaining: 153 rows

Last error: E-3001: UPS API timeout
Resume will retry from the failed row.

Options:
  [resume]  - Continue from where it stopped
  [restart] - Start over from the beginning (may create duplicates!)
  [cancel]  - Abandon this job
```

### Recovery Choice Handling

| Choice | Action | State Change |
|--------|--------|--------------|
| RESUME | Return action info | None - executor processes pending rows |
| RESTART | Return warning with confirmation | None - requires user confirmation |
| CANCEL | Transition to cancelled | job.status = cancelled |

### Unit Tests (14 tests)

Comprehensive test coverage:
- `test_no_interrupted_jobs` - Returns None when no running jobs
- `test_finds_interrupted_job` - Correct progress and tracking info
- `test_finds_interrupted_job_with_error` - Error info included
- `test_no_completed_rows` - Handles fresh interrupted job
- `test_basic_prompt` - Readable format with all info
- `test_prompt_with_error` - Error context included
- `test_handle_resume` - No state changes, returns message
- `test_handle_restart_warning` - Duplicate warning with count
- `test_handle_cancel` - Transitions to cancelled state

## Key Links

| From | To | Via | Pattern |
|------|-----|-----|---------|
| recovery.py | JobService | list_jobs query | `job_service.list_jobs(status=JobStatus.running)` |
| recovery.py | JobService | get_rows query | `job_service.get_rows(job_id, status=RowStatus.completed)` |
| recovery.py | JobService | Status update | `job_service.update_status(job_id, JobStatus.cancelled)` |
| recovery.py | InterruptedJobInfo | Model usage | Imported from batch.models |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Status |
|-------|--------|
| check_interrupted_jobs finds running state jobs | PASSED |
| InterruptedJobInfo includes progress and error info | PASSED |
| get_recovery_prompt generates readable message | PASSED |
| handle_recovery_choice handles all three choices | PASSED |
| Restart warns about duplicate shipments | PASSED |
| Cancel transitions job to cancelled state | PASSED |
| All unit tests pass | PASSED (14/14) |
| All batch tests pass | PASSED (81/81) |

## Next Phase Readiness

**Blockers:** None

**Ready for:**
- 06-06: Batch Orchestration Tools (uses recovery functions)
- 06-07: Integration Tests (end-to-end recovery flow)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| e7a451d | feat | Create crash recovery module with detection and prompts |
| aec4e3f | chore | Export recovery utilities from batch package |
| 1f567bc | test | Add unit tests for crash recovery |
