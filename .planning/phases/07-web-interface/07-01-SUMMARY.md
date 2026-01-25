---
phase: "07"
plan: "01"
subsystem: "api"
tags: ["fastapi", "sse", "streaming", "rest-api", "real-time"]

dependency-graph:
  requires: ["06-02", "01-05"]
  provides: ["backend-api-endpoints", "sse-observer", "label-downloads"]
  affects: ["07-02", "07-03", "07-04"]

tech-stack:
  added: ["sse-starlette>=2.0.0", "zipstream-ng>=1.7.0"]
  patterns: ["observer-bridge", "sse-streaming", "zip-streaming"]

key-files:
  created:
    - src/orchestrator/batch/sse_observer.py
    - src/api/routes/commands.py
    - src/api/routes/labels.py
    - src/api/routes/progress.py
  modified:
    - pyproject.toml
    - src/api/schemas.py
    - src/api/routes/__init__.py
    - src/api/main.py
    - src/orchestrator/batch/__init__.py

decisions:
  - id: "module-level-sse-observer"
    choice: "Single module-level SSEProgressObserver instance in progress.py"
    rationale: "Simplifies integration - observers can be registered globally"
  - id: "15-second-ping"
    choice: "15-second timeout with ping events for SSE keepalive"
    rationale: "Prevents connection timeout from load balancers/proxies"

metrics:
  duration: "~4 minutes"
  completed: "2026-01-25"
---

# Phase 7 Plan 01: Backend API Endpoints Summary

JWT auth with SSE streaming for real-time batch progress updates

## Execution Results

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Install dependencies and create SSE observer | Complete | f525b88 |
| 2 | Create commands and labels API routes | Complete | 6d2af8a |
| 3 | Create SSE progress endpoint and wire routes | Complete | e6c9322 |

## What Was Built

### SSE Progress Observer (`src/orchestrator/batch/sse_observer.py`)

Implements BatchEventObserver protocol to bridge batch events to SSE connections:

```python
class SSEProgressObserver:
    def subscribe(self, job_id: str) -> asyncio.Queue
    def unsubscribe(self, job_id: str) -> None
    async def on_batch_started(...)
    async def on_row_completed(...)
    async def on_batch_completed(...)
    async def on_batch_failed(...)
```

### New API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/commands` | Submit NL shipping command |
| GET | `/api/v1/commands/history` | Get recent commands (last 10-50) |
| GET | `/api/v1/labels/{tracking}` | Download individual label PDF |
| GET | `/api/v1/jobs/{id}/labels/zip` | Download all labels as ZIP |
| GET | `/api/v1/jobs/{id}/progress/stream` | SSE stream of batch events |
| GET | `/api/v1/jobs/{id}/progress` | Polling fallback for progress |

### New Pydantic Schemas (`src/api/schemas.py`)

- `CommandSubmit`: Request body for command submission
- `CommandSubmitResponse`: Response with job_id and status
- `CommandHistoryItem`: History entry with id, command, status, created_at

### Dependencies Added (`pyproject.toml`)

```toml
"sse-starlette>=2.0.0",  # Server-Sent Events for FastAPI
"zipstream-ng>=1.7.0",   # Memory-efficient ZIP streaming
```

## Key Implementation Details

1. **SSE Event Format**: Events follow `{event: string, data: dict}` structure
2. **Keepalive**: 15-second ping events prevent connection timeout
3. **Cleanup**: Automatic unsubscribe when client disconnects via try/finally
4. **ZIP Streaming**: Uses zipstream-ng generator to avoid loading all PDFs into memory
5. **Label Lookup**: Queries JobRow by tracking_number, returns FileResponse

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- [x] sse-starlette and zipstream-ng in pyproject.toml
- [x] SSEProgressObserver implements BatchEventObserver and manages job queues
- [x] POST /api/v1/commands creates job and returns job_id
- [x] GET /api/v1/commands/history returns recent commands
- [x] GET /api/v1/labels/{tracking} returns PDF file
- [x] GET /api/v1/jobs/{id}/labels/zip streams ZIP file
- [x] GET /api/v1/jobs/{id}/progress/stream returns SSE stream
- [x] All routes registered in main app
- [x] All 654 existing tests pass

## Next Phase Readiness

**Ready for 07-02 (React Project Setup)**

The backend API is complete and ready for frontend integration:

1. Commands endpoint ready for `CommandInput` component
2. SSE endpoint ready for `useJobProgress` hook
3. Labels endpoints ready for `LabelPreview` and download functionality
4. Progress endpoint ready for `ProgressDisplay` component

No blockers identified.
