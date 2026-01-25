# Phase 7: Web Interface - Research

**Researched:** 2026-01-25
**Domain:** Web UI with Real-time Updates (FastAPI + React)
**Confidence:** HIGH

## Summary

Phase 7 implements a web interface for natural language shipping commands with real-time progress updates, shipment preview, and label management. The research covers six key areas: real-time updates (SSE vs WebSocket), React + FastAPI integration, PDF preview, ZIP generation, frontend architecture, and state management.

The existing BatchEventEmitter (Phase 6) already implements the Observer pattern with lifecycle events (batch_started, row_completed, batch_failed, etc.), providing a natural bridge to real-time UI updates. The existing FastAPI server (src/api/main.py) with jobs router provides the foundation.

**Primary recommendation:** Use Server-Sent Events (SSE) via sse-starlette for real-time progress updates (simpler than WebSocket for server-to-client only), React with Vite + shadcn/ui for the frontend, react-pdf for in-browser PDF preview, and zipstream-ng for on-the-fly ZIP generation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sse-starlette | 2.x | Server-Sent Events | W3C compliant SSE for FastAPI, production-ready |
| react | 18.x | Frontend framework | React 18 with hooks, wide ecosystem |
| vite | 5.x | Build tool | Fast dev server, optimized production builds |
| @shadcn/ui | latest | UI components | Copy-paste components, Tailwind + Radix based |
| tailwindcss | 4.x | CSS framework | Utility-first, integrates with shadcn/ui |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| react-pdf | 9.x | PDF rendering | In-browser PDF preview (wojtekmaj) |
| react-use-websocket | 4.x | WebSocket hook | If WebSocket fallback needed |
| zipstream-ng | 2.x | Streaming ZIP | On-the-fly ZIP generation without temp files |
| recharts | 3.x | Charts | If dashboard/analytics needed later |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SSE | WebSocket | WebSocket is bidirectional but overkill for server-to-client progress |
| react-pdf | @react-pdf-viewer/core | More features but no updates since 2023 |
| zipstream-ng | stream-zip | Similar API, zipstream-ng has better FastAPI examples |
| shadcn/ui | MUI/Ant Design | MUI/AntD are heavier, shadcn gives full control |

**Installation:**
```bash
# Python (backend)
pip install sse-starlette zipstream-ng

# Node (frontend)
npm create vite@latest frontend -- --template react-ts
cd frontend
npx shadcn@latest init
npm install react-pdf pdfjs-dist
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── api/
│   ├── main.py              # Existing FastAPI app
│   ├── routes/
│   │   ├── jobs.py          # Existing job routes
│   │   ├── commands.py      # NEW: Command submission + history
│   │   ├── progress.py      # NEW: SSE endpoint for progress
│   │   └── labels.py        # NEW: Label download + ZIP
│   └── schemas.py           # Existing + new schemas
├── orchestrator/
│   └── batch/
│       └── events.py        # Existing BatchEventObserver
└── frontend/                 # NEW: React app
    ├── src/
    │   ├── components/
    │   │   ├── CommandInput.tsx
    │   │   ├── ProgressDisplay.tsx
    │   │   ├── PreviewGrid.tsx
    │   │   ├── LabelPreview.tsx
    │   │   └── ui/           # shadcn components
    │   ├── hooks/
    │   │   ├── useSSE.ts
    │   │   └── useJobProgress.ts
    │   ├── pages/
    │   │   └── Dashboard.tsx
    │   └── App.tsx
    └── dist/                 # Built static files
```

### Pattern 1: SSE Observer Bridge
**What:** Create a BatchEventObserver that broadcasts events to SSE connections
**When to use:** Real-time progress updates to web clients
**Example:**
```python
# Source: sse-starlette official docs + BatchEventObserver pattern
import asyncio
from sse_starlette.sse import EventSourceResponse
from src.orchestrator.batch.events import BatchEventObserver

class SSEProgressObserver(BatchEventObserver):
    """Bridges batch events to SSE connections."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue:
        """Create a queue for SSE events for a specific job."""
        queue = asyncio.Queue()
        self._queues[job_id] = queue
        return queue

    def unsubscribe(self, job_id: str):
        """Remove queue when client disconnects."""
        self._queues.pop(job_id, None)

    async def on_row_completed(
        self, job_id: str, row_number: int,
        tracking_number: str, cost_cents: int
    ):
        if queue := self._queues.get(job_id):
            await queue.put({
                "event": "row_completed",
                "data": {
                    "row_number": row_number,
                    "tracking_number": tracking_number,
                    "cost_cents": cost_cents
                }
            })

    async def on_batch_completed(
        self, job_id: str, total_rows: int,
        successful: int, total_cost_cents: int
    ):
        if queue := self._queues.get(job_id):
            await queue.put({
                "event": "batch_completed",
                "data": {
                    "total_rows": total_rows,
                    "successful": successful,
                    "total_cost_cents": total_cost_cents
                }
            })

# FastAPI SSE endpoint
@router.get("/jobs/{job_id}/progress/stream")
async def stream_progress(request: Request, job_id: str):
    queue = sse_observer.subscribe(job_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            sse_observer.unsubscribe(job_id)

    return EventSourceResponse(event_generator())
```

### Pattern 2: Static File Serving with SPA Fallback
**What:** Serve React build from FastAPI with client-side routing support
**When to use:** Production deployment
**Example:**
```python
# Source: FastAPI static files docs + SPA pattern
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI()

# Serve API routes first (existing)
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(commands.router, prefix="/api/v1")
app.include_router(progress.router, prefix="/api/v1")
app.include_router(labels.router, prefix="/api/v1")

# Check if frontend build exists
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    # Serve static assets
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    # SPA fallback - serve index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse(FRONTEND_DIR / "index.html")
```

### Pattern 3: React SSE Hook
**What:** Custom React hook for consuming SSE progress events
**When to use:** Job progress monitoring component
**Example:**
```typescript
// Source: EventSource MDN + React patterns
import { useEffect, useState, useCallback } from 'react';

interface ProgressEvent {
  event: 'row_completed' | 'row_failed' | 'batch_completed' | 'batch_failed' | 'ping';
  data: any;
}

export function useJobProgress(jobId: string | null) {
  const [progress, setProgress] = useState({ processed: 0, total: 0 });
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const eventSource = new EventSource(`/api/v1/jobs/${jobId}/progress/stream`);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.event) {
        case 'row_completed':
          setProgress(prev => ({ ...prev, processed: data.data.row_number }));
          break;
        case 'batch_completed':
          setStatus('completed');
          break;
        case 'batch_failed':
          setStatus('failed');
          setError(data.data.error_message);
          break;
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      // SSE auto-reconnects, but we may want manual handling
    };

    return () => eventSource.close();
  }, [jobId]);

  return { progress, status, error };
}
```

### Anti-Patterns to Avoid
- **Polling for progress:** Don't use setInterval to poll /jobs/{id}/progress; use SSE instead
- **In-memory connection tracking without cleanup:** Always unsubscribe on disconnect
- **Large PDFs in JSON responses:** Return file paths and use separate download endpoints
- **Synchronous ZIP generation:** Use streaming ZIP to avoid memory exhaustion

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE protocol | Manual HTTP streaming | sse-starlette | W3C compliant, handles heartbeats, client disconnect |
| PDF rendering | Canvas drawing | react-pdf with pdfjs | Handles complex PDFs, zoom, rotation |
| ZIP generation | zipfile.ZipFile in memory | zipstream-ng | Streams without memory inflation, predictable size |
| Progress bar | Custom CSS/JS | shadcn/ui Progress | Accessible, styled, animations |
| Form handling | useState sprawl | React Hook Form | Validation, error states, performance |

**Key insight:** Real-time web features have many edge cases (reconnection, heartbeats, backpressure) that libraries handle correctly. Custom implementations invariably miss edge cases.

## Common Pitfalls

### Pitfall 1: SSE Connection Limits (HTTP/1.1)
**What goes wrong:** Browser limits to 6 SSE connections per domain causes connection failures
**Why it happens:** HTTP/1.1 has 6 connection limit per domain
**How to avoid:** Use HTTP/2 (uvicorn supports it) or share single SSE connection across tabs
**Warning signs:** Connections timing out in browser console, multiple tabs breaking

### Pitfall 2: PDF.js Worker Configuration
**What goes wrong:** PDF fails to render with "Cannot read property of undefined" errors
**Why it happens:** pdf.js worker not properly configured in build
**How to avoid:** Set workerSrc in the same file as PDF component:
```typescript
import { pdfjs } from 'react-pdf';
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();
```
**Warning signs:** Console errors about worker, blank PDF viewer

### Pitfall 3: Memory Exhaustion on Large ZIP Downloads
**What goes wrong:** Server OOM when generating ZIP of many labels
**Why it happens:** Loading all PDFs into memory before streaming
**How to avoid:** Use zipstream-ng with generator pattern:
```python
async def generate_zip(label_paths: list[str]):
    zs = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_STORED)
    for path in label_paths:
        zs.write(path, arcname=Path(path).name)
    for chunk in zs:
        yield chunk
```
**Warning signs:** Memory usage spikes during download, process killed

### Pitfall 4: Vite Proxy vs Production Static Serving
**What goes wrong:** API calls work in dev but fail in production
**Why it happens:** Vite dev server proxies /api to FastAPI, but production serves from same origin
**How to avoid:** Use relative URLs (/api/v1/...) and configure vite.config.ts:
```typescript
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```
**Warning signs:** 404 on /api routes in production, CORS errors

### Pitfall 5: SSE Heartbeat/Timeout
**What goes wrong:** SSE connections drop after 30-60 seconds of no events
**Why it happens:** Load balancers/proxies timeout idle connections
**How to avoid:** Send ping events every 15 seconds:
```python
async def event_generator():
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15.0)
            yield event
        except asyncio.TimeoutError:
            yield {"event": "ping", "data": ""}
```
**Warning signs:** "Connection closed" in browser after idle period

## Code Examples

Verified patterns from research:

### ZIP Streaming Endpoint
```python
# Source: zipstream-ng docs + FastAPI streaming
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import zipstream
from pathlib import Path

router = APIRouter()

@router.get("/jobs/{job_id}/labels/zip")
async def download_labels_zip(job_id: str, db: Session = Depends(get_db)):
    """Download all labels for a job as a ZIP file."""
    # Get label paths from job rows
    rows = db.query(JobRow).filter(
        JobRow.job_id == job_id,
        JobRow.label_path.isnot(None)
    ).all()

    label_paths = [row.label_path for row in rows]

    def generate():
        zs = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_STORED)
        for path in label_paths:
            zs.write(path, arcname=Path(path).name)
        for chunk in zs:
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=labels-{job_id}.zip"
        }
    )
```

### PDF Preview Component
```typescript
// Source: react-pdf docs (wojtekmaj/react-pdf)
import { Document, Page, pdfjs } from 'react-pdf';
import { useState } from 'react';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface LabelPreviewProps {
  trackingNumber: string;
}

export function LabelPreview({ trackingNumber }: LabelPreviewProps) {
  const [numPages, setNumPages] = useState<number>(0);

  return (
    <Document
      file={`/api/v1/labels/${trackingNumber}`}
      onLoadSuccess={({ numPages }) => setNumPages(numPages)}
    >
      {Array.from(new Array(numPages), (_, i) => (
        <Page key={i + 1} pageNumber={i + 1} scale={1.0} />
      ))}
    </Document>
  );
}
```

### Command Submission with History
```python
# Source: FastAPI patterns + existing job creation
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()

class CommandSubmit(BaseModel):
    command: str

class CommandHistory(BaseModel):
    id: str
    command: str
    status: str
    created_at: str

@router.post("/commands")
async def submit_command(
    payload: CommandSubmit,
    db: Session = Depends(get_db)
):
    """Submit a natural language command for processing."""
    # Create job
    job = Job(
        name=f"Command: {payload.command[:50]}",
        original_command=payload.command,
        status=JobStatus.pending.value
    )
    db.add(job)
    db.commit()

    # Queue for processing (triggers orchestration agent)
    # In production, this would use a task queue
    return {"job_id": str(job.id), "status": "pending"}

@router.get("/commands/history", response_model=list[CommandHistory])
async def get_command_history(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get recent commands for reuse."""
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
    return [
        CommandHistory(
            id=str(j.id),
            command=j.original_command,
            status=j.status,
            created_at=j.created_at
        )
        for j in jobs
    ]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Polling for updates | SSE/WebSocket | 2020+ | Much better UX, lower server load |
| Create React App | Vite | 2022+ | 10x faster dev builds, better HMR |
| Component libraries | shadcn/ui copy-paste | 2023+ | Full control, no version lock-in |
| Tailwind v3 CSS vars | Tailwind v4 OKLCH | 2024+ | Better color interpolation |
| forwardRef patterns | React 19 data-slot | 2024+ | Simpler component APIs |

**Deprecated/outdated:**
- Create React App: Use Vite instead (CRA is deprecated)
- @react-pdf-viewer/core: No updates since 2023, use react-pdf
- Toast libraries: shadcn/ui recommends sonner over custom toast

## Open Questions

Things that couldn't be fully resolved:

1. **Frontend design system specifics**
   - What we know: CONTEXT.md specifies "leverage frontend-design skill" for high-quality UI
   - What's unclear: Specific design tokens, brand colors, typography
   - Recommendation: Use shadcn/ui defaults initially, customize in design phase

2. **Multi-process SSE coordination**
   - What we know: Single-process SSE works; multi-process needs Redis/broadcaster
   - What's unclear: Will deployment use multiple workers?
   - Recommendation: Start with single-process, add Redis pub/sub if scaling needed

3. **Command processing trigger**
   - What we know: POST /commands creates job, but how does orchestration agent pick it up?
   - What's unclear: Is there a task queue or does agent poll?
   - Recommendation: Research Phase 5 orchestration patterns for integration

## Sources

### Primary (HIGH confidence)
- [FastAPI WebSockets docs](https://fastapi.tiangolo.com/advanced/websockets/) - Official patterns
- [sse-starlette GitHub](https://github.com/sysid/sse-starlette) - SSE implementation
- [react-pdf GitHub](https://github.com/wojtekmaj/react-pdf) - PDF viewer
- [zipstream-ng PyPI](https://pypi.org/project/zipstream-ng/) - Streaming ZIP

### Secondary (MEDIUM confidence)
- [FastAPI + React integration](https://www.joshfinnie.com/blog/fastapi-and-react-in-2025/) - Verified patterns
- [shadcn/ui docs](https://ui.shadcn.com/) - Component library
- [TestDriven.io WebSocket tutorial](https://testdriven.io/blog/fastapi-postgres-websockets/) - Real-time patterns

### Tertiary (LOW confidence)
- WebSearch results for "logistics dashboard" - Need validation for specific patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified from official sources
- Architecture: HIGH - Patterns from FastAPI docs and existing codebase
- Pitfalls: MEDIUM - Based on research + known issues, not project-specific validation
- Frontend specifics: MEDIUM - shadcn/ui documented, but design not finalized

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - stable libraries)
