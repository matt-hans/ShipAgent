# Chat Completion Artifacts Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the broken post-batch-completion UX so users can continuously issue commands in the same chat, with each completed batch collapsing into a compact clickable artifact for label access.

**Architecture:** Frontend-only changes to CommandCenter state management and message rendering. No backend changes required.

**Tech Stack:** React, TypeScript, existing useAppState/useJobProgress hooks

---

## Problem

After a batch completes, `executingJobId` is never cleared. This causes:
1. The old ProgressDisplay card stays visible forever in the chat
2. Input remains disabled (can't type new commands)
3. Subsequent commands show stale batch results from the prior job
4. Users must reload the page to continue working

## Solution

### 1. State Reset on Completion

When the SSE fires `batch_completed`, the `onComplete` callback:

1. Adds a **CompletionMessage** to the conversation (with jobId, cost, row count, original command)
2. Clears `executingJobId` → `null`
3. Clears `currentJobId` → `null`
4. Opens the label preview modal
5. Calls `refreshJobList()` to update sidebar

This re-enables the input immediately, allowing the user to type the next command.

### 2. CompletionArtifact Component

A new compact component rendered inline in the chat thread for messages with `metadata.action === 'complete'`:

```
┌──────────────────────────────────────────────┐
│ ✓ Shipment Complete              COMPLETED   │
│                                              │
│ "Ship orders going to Buffalo, NY..."        │
│                                              │
│ 2 shipments  ·  $36.44  ·  0 failed         │
│                                              │
│           [ View Labels (PDF) ]              │
└──────────────────────────────────────────────┘
```

- **Green left border** for full success, **red** for all failed, **amber** for partial
- Command text truncated with ellipsis if long
- "View Labels" button opens the PDF modal as an overlay (doesn't disrupt current flow)
- For fully failed batches, button changes to "View Details" linking to sidebar job

### 3. Conversation Message Schema

New `completion` metadata shape:

```typescript
metadata: {
  jobId: string;
  action: 'complete';
  completion: {
    command: string;          // Original NL command text
    totalRows: number;
    successful: number;
    failed: number;
    totalCostCents: number;
  }
}
```

When rendering, messages with `action === 'complete'` render `CompletionArtifact` instead of `SystemMessage`.

### 4. Track Original Command

Store the user's command text in a `lastCommandRef` on submit, so it's available when the completion fires later (since `inputValue` is cleared immediately on submit).

### 5. Input Re-enablement

Current disable condition: `disabled={!hasDataSource || isProcessing || !!preview}`

After `onComplete` clears state:
- `executingJobId = null` → StopIcon becomes SendIcon
- `currentJobId = null` → Ready for new job
- `preview = null` → Already cleared on confirm
- `isProcessing = false` → Already false

Input stays enabled while the label modal is open (true overlay).

### 6. refreshJobList on All Terminal States

Call `refreshJobList()` on completion, failure, AND cancellation to ensure the sidebar always reflects current state.

---

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/CommandCenter.tsx` | Add CompletionArtifact component, update onComplete callback, add lastCommandRef, update message rendering |
| `frontend/src/hooks/useAppState.tsx` | Add `completion` to ConversationMessage metadata type |

## Edge Cases

- **Label modal open + new command**: Modal stays as overlay, input works underneath
- **Failed batch**: Artifact shows red styling, "View Details" instead of "View Labels"
- **Partial failure** (some rows succeeded): Amber styling, "View Labels" still available for successful rows
- **Cancelled batch**: No artifact needed (cancellation message already exists)
- **Rapid sequential commands**: Each gets its own lifecycle, state fully resets between

## Implementation Tasks

### Task 1: Update ConversationMessage Type

**Files:**
- Modify: `frontend/src/hooks/useAppState.tsx`

**Step 1:** Add `completion` shape to the metadata interface:

```typescript
completion?: {
  command: string;
  totalRows: number;
  successful: number;
  failed: number;
  totalCostCents: number;
};
```

**Step 2:** Verify TypeScript compiles cleanly.

Run: `cd frontend && npx tsc --noEmit`

**Step 3:** Commit.

```bash
git add frontend/src/hooks/useAppState.tsx
git commit -m "feat: add completion metadata type to ConversationMessage"
```

### Task 2: Add CompletionArtifact Component

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx`

**Step 1:** Add the `CompletionArtifact` component after the existing `ProgressDisplay` component:

```tsx
function CompletionArtifact({ message, onViewLabels }: {
  message: ConversationMessage;
  onViewLabels: (jobId: string) => void;
}) {
  const meta = message.metadata?.completion;
  const jobId = message.metadata?.jobId;
  if (!meta || !jobId) return null;

  const allFailed = meta.successful === 0 && meta.failed > 0;
  const hasFailures = meta.failed > 0;
  const borderColor = allFailed ? 'border-l-error' : hasFailures ? 'border-l-amber-500' : 'border-l-success';
  const badgeClass = allFailed ? 'badge-error' : hasFailures ? 'badge-warning' : 'badge-success';
  const badgeText = allFailed ? 'FAILED' : hasFailures ? 'PARTIAL' : 'COMPLETED';

  // Truncate command to ~60 chars
  const commandPreview = meta.command.length > 60
    ? meta.command.slice(0, 57) + '...'
    : meta.command;

  return (
    <div className={cn(
      'card-premium p-4 space-y-3 border-l-4',
      borderColor
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CheckIcon className="w-4 h-4 text-success" />
          <h3 className="text-sm font-medium text-slate-200">
            {allFailed ? 'Batch Failed' : 'Shipment Complete'}
          </h3>
        </div>
        <span className={cn('badge', badgeClass)}>{badgeText}</span>
      </div>

      <p className="text-xs text-slate-400 italic">"{commandPreview}"</p>

      <div className="flex items-center gap-3 text-xs font-mono text-slate-400">
        <span>{meta.successful} shipment{meta.successful !== 1 ? 's' : ''}</span>
        <span className="text-slate-600">·</span>
        <span className="text-amber-400">{formatCurrency(meta.totalCostCents)}</span>
        {meta.failed > 0 && (
          <>
            <span className="text-slate-600">·</span>
            <span className="text-error">{meta.failed} failed</span>
          </>
        )}
      </div>

      {!allFailed && (
        <button
          onClick={() => onViewLabels(jobId)}
          className="w-full btn-primary py-2 flex items-center justify-center gap-2 text-sm"
        >
          <DownloadIcon className="w-3.5 h-3.5" />
          <span>View Labels (PDF)</span>
        </button>
      )}
    </div>
  );
}
```

**Step 2:** Verify TypeScript compiles cleanly.

Run: `cd frontend && npx tsc --noEmit`

**Step 3:** Commit.

```bash
git add frontend/src/components/CommandCenter.tsx
git commit -m "feat: add CompletionArtifact component for inline batch results"
```

### Task 3: Wire Up State Reset and Artifact Rendering

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx`

**Step 1:** Add `lastCommandRef` inside the `CommandCenter` component (near the other refs):

```typescript
const lastCommandRef = React.useRef<string>('');
```

**Step 2:** In `handleSubmit`, save the command text before clearing input:

```typescript
// Right before setInputValue(''):
lastCommandRef.current = command;
```

**Step 3:** Add state for label preview job ID to support viewing labels from any artifact:

```typescript
const [labelPreviewJobId, setLabelPreviewJobId] = React.useState<string | null>(null);
```

**Step 4:** Update the `onComplete` callback in the ProgressDisplay to add a completion message and clear state:

```tsx
<ProgressDisplay
  jobId={executingJobId}
  onComplete={() => {
    // Get final progress state for the artifact
    // We need to pass progress data - read from the SSE state
    addMessage({
      role: 'system',
      content: '',
      metadata: {
        jobId: executingJobId,
        action: 'complete' as const,
        completion: {
          command: lastCommandRef.current,
          totalRows: 0,    // Will be filled from progress
          successful: 0,
          failed: 0,
          totalCostCents: 0,
        },
      },
    });
    setLabelPreviewJobId(executingJobId);
    setShowLabelPreview(true);
    setExecutingJobId(null);
    setCurrentJobId(null);
    refreshJobList();
  }}
/>
```

Note: The progress values (totalRows, successful, etc.) need to come from the ProgressDisplay's internal state. To accomplish this, update the `onComplete` callback signature to accept progress data:

In `ProgressDisplay`, change to pass progress data on complete:
```tsx
function ProgressDisplay({ jobId, onComplete }: { jobId: string; onComplete?: (data: { total: number; successful: number; failed: number; totalCostCents: number }) => void }) {
  // ... existing code ...

  React.useEffect(() => {
    if (isComplete && !completeFiredRef.current && onComplete) {
      completeFiredRef.current = true;
      onComplete({
        total: progress.total,
        successful: progress.successful,
        failed: progress.failed,
        totalCostCents: progress.totalCostCents,
      });
    }
  }, [isComplete, onComplete, progress]);
```

Then in CommandCenter, update the callback:
```tsx
onComplete={(data) => {
  addMessage({
    role: 'system',
    content: '',
    metadata: {
      jobId: executingJobId!,
      action: 'complete' as const,
      completion: {
        command: lastCommandRef.current,
        totalRows: data.total,
        successful: data.successful,
        failed: data.failed,
        totalCostCents: data.totalCostCents,
      },
    },
  });
  setLabelPreviewJobId(executingJobId);
  setShowLabelPreview(true);
  setExecutingJobId(null);
  setCurrentJobId(null);
  refreshJobList();
}}
```

**Step 5:** Update the message rendering loop to handle completion artifacts:

```tsx
{conversation.map((message) => (
  message.metadata?.action === 'complete' ? (
    <div key={message.id} className="pl-11">
      <CompletionArtifact
        message={message}
        onViewLabels={(jobId) => {
          setLabelPreviewJobId(jobId);
          setShowLabelPreview(true);
        }}
      />
    </div>
  ) : message.role === 'user' ? (
    <UserMessage key={message.id} message={message} />
  ) : (
    <SystemMessage key={message.id} message={message} />
  )
))}
```

**Step 6:** Update the LabelPreview at the bottom to use `labelPreviewJobId` instead of `executingJobId`:

```tsx
{labelPreviewJobId && (
  <LabelPreview
    pdfUrl={getMergedLabelsUrl(labelPreviewJobId)}
    title="Batch Labels"
    isOpen={showLabelPreview}
    onClose={() => {
      setShowLabelPreview(false);
      setLabelPreviewJobId(null);
    }}
  />
)}
```

**Step 7:** Remove the rendering of the live ProgressDisplay from the conversation area. Since `executingJobId` is now cleared on completion, the ProgressDisplay will naturally disappear. But we still need it while the batch is running:

The existing block is fine as-is:
```tsx
{executingJobId && (
  <div className="pl-11">
    <ProgressDisplay jobId={executingJobId} onComplete={...} />
  </div>
)}
```

When `executingJobId` is cleared, this unmounts. The CompletionArtifact in the conversation takes its place.

**Step 8:** Verify TypeScript compiles and the dev server runs cleanly.

Run: `cd frontend && npx tsc --noEmit`

**Step 9:** Commit.

```bash
git add frontend/src/components/CommandCenter.tsx
git commit -m "feat: wire up state reset and completion artifact rendering for continuous chat flow"
```

### Task 4: Handle Failure and Cancellation Refresh

**Files:**
- Modify: `frontend/src/components/CommandCenter.tsx`

**Step 1:** In the ProgressDisplay, also handle failure by adding an `onFailed` callback similar to `onComplete`, or extend `onComplete` to also fire on failure. The simpler approach: add an effect for failure:

Add a new prop to ProgressDisplay:
```tsx
function ProgressDisplay({ jobId, onComplete, onFailed }: {
  jobId: string;
  onComplete?: (data: {...}) => void;
  onFailed?: (data: {...}) => void;
}) {
```

And fire it on failure:
```tsx
const failFiredRef = React.useRef(false);

React.useEffect(() => {
  if (isFailed && !failFiredRef.current && onFailed) {
    failFiredRef.current = true;
    onFailed({
      total: progress.total,
      successful: progress.successful,
      failed: progress.failed,
      totalCostCents: progress.totalCostCents,
    });
  }
}, [isFailed, onFailed, progress]);
```

**Step 2:** In CommandCenter, add the `onFailed` handler:

```tsx
onFailed={(data) => {
  addMessage({
    role: 'system',
    content: '',
    metadata: {
      jobId: executingJobId!,
      action: 'complete' as const,
      completion: {
        command: lastCommandRef.current,
        totalRows: data.total,
        successful: data.successful,
        failed: data.failed,
        totalCostCents: data.totalCostCents,
      },
    },
  });
  // Open labels if any succeeded
  if (data.successful > 0) {
    setLabelPreviewJobId(executingJobId);
    setShowLabelPreview(true);
  }
  setExecutingJobId(null);
  setCurrentJobId(null);
  refreshJobList();
}}
```

**Step 3:** In `handleCancel`, add `refreshJobList()`:

```typescript
const handleCancel = async () => {
  if (!currentJobId) return;
  try {
    await cancelJob(currentJobId);
    setPreview(null);
    setCurrentJobId(null);
    refreshJobList();  // <-- Add this
    addMessage({
      role: 'system',
      content: 'Batch cancelled. You can enter a new command.',
    });
  } catch (err) {
    console.error('Failed to cancel:', err);
  }
};
```

**Step 4:** Verify and commit.

Run: `cd frontend && npx tsc --noEmit`

```bash
git add frontend/src/components/CommandCenter.tsx
git commit -m "feat: handle batch failure artifacts and refresh job list on cancel"
```

### Task 5: Manual E2E Verification

**Step 1:** Start backend and frontend if not running.

**Step 2:** Test continuous flow:
1. Submit "Ship orders going to Buffalo, NY using UPS Ground"
2. Confirm the preview
3. Verify: ProgressDisplay shows during execution
4. Verify: On completion, ProgressDisplay disappears, CompletionArtifact appears
5. Verify: Label modal opens automatically
6. Verify: Input is re-enabled
7. Verify: Job appears in sidebar history

**Step 3:** Test second command in same chat:
1. Submit "Ship orders for customer Novella Gutkowski using UPS Ground"
2. Verify: New preview appears below the first artifact
3. Confirm and verify second artifact appears

**Step 4:** Test artifact label button:
1. Scroll up to first CompletionArtifact
2. Click "View Labels"
3. Verify: PDF modal opens as overlay

**Step 5:** Test failure case:
1. Submit a command that will fail
2. Verify: Failed artifact shows red styling, no "View Labels" button
