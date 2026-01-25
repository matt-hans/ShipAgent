---
phase: 07-web-interface
plan: 03
title: "Command Input and Preview Components"
subsystem: web-interface
tags: [react, components, preview, confirmation, dashboard]

dependency-graph:
  requires: ["07-01", "07-02"]
  provides:
    - command-input-component
    - command-history-component
    - preview-grid-component
    - confirmation-footer-component
    - dashboard-page
    - preview-api-endpoints
  affects:
    - 07-04 (Progress Display)
    - 07-05 (Label Management)

tech-stack:
  added: []
  patterns:
    - "Sticky confirmation footer"
    - "Click-to-reuse command history"
    - "Preview card grid layout"
    - "Phase-based workflow state machine"

key-files:
  created:
    - frontend/src/components/CommandInput.tsx
    - frontend/src/components/CommandHistory.tsx
    - frontend/src/components/PreviewGrid.tsx
    - frontend/src/components/ConfirmationFooter.tsx
    - src/api/routes/preview.py
  modified:
    - frontend/src/pages/Dashboard.tsx
    - frontend/src/lib/api.ts
    - src/api/schemas.py
    - src/api/routes/__init__.py
    - src/api/main.py

decisions:
  - id: "max-preview-rows"
    decision: "Show maximum 10 preview rows"
    rationale: "Balance between useful preview and performance"
    alternatives: ["5 rows", "20 rows", "configurable"]
  - id: "sticky-footer"
    decision: "Fixed position footer for confirmation"
    rationale: "Per CONTEXT.md Decision 3 - always accessible during scroll"
    alternatives: ["Inline buttons", "Modal dialog"]
  - id: "phase-state-machine"
    decision: "Four phases: input, preview, executing, complete"
    rationale: "Clear separation of workflow states"
    alternatives: ["Three phases", "Nested state"]

metrics:
  duration: "6 minutes"
  completed: "2026-01-25"
---

# Phase 7 Plan 03: Command Input and Preview Components Summary

Command input with history, shipment preview grid, sticky confirmation footer, and integrated Dashboard workflow

## Execution Results

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Create preview API endpoint | Complete | 2854bbd |
| 2 | Create command input and history components | Complete | 15a580b |
| 3 | Create preview grid, confirmation footer, dashboard | Complete | b1cc049 |

## What Was Built

### Task 1: Backend Preview Endpoints

**New API Endpoints:**
- `GET /api/v1/jobs/{id}/preview` - Returns BatchPreviewResponse with sample rows, costs, warnings
- `POST /api/v1/jobs/{id}/confirm` - Confirms batch for execution, updates status to running

**New Schemas (`src/api/schemas.py`):**
- `PreviewRowResponse`: row_number, recipient_name, city_state, service, estimated_cost_cents, warnings
- `BatchPreviewResponse`: job_id, total_rows, preview_rows, additional_rows, total_estimated_cost_cents, rows_with_warnings
- `ConfirmRequest`: job_id
- `ConfirmResponse`: status, message

### Task 2: Command Input Components

**CommandInput.tsx (190 lines):**
- Large text input with descriptive placeholder
- Submit on Enter key or button click
- Loading state with spinner during submission
- Example command chips for quick population
- Keyboard accessible with focus management

**CommandHistory.tsx (203 lines):**
- Displays up to 5 most recent commands
- Status badge for each command (pending, running, completed, failed, cancelled)
- Relative timestamp display ("2h ago", "Just now")
- Click-to-reuse with hover indicator
- Loading skeleton state

### Task 3: Preview and Dashboard Components

**PreviewGrid.tsx (279 lines):**
- Grid layout of shipment preview cards (1/2/3 columns responsive)
- Each card shows: row number, recipient name, city/state, service type, cost
- Warning badges for problematic shipments
- Summary header with total count and estimated cost
- Loading skeleton state
- "Additional rows not shown" indicator

**ConfirmationFooter.tsx (188 lines):**
- Sticky footer at bottom of viewport
- Summary section: shipment count and estimated total
- Green "Confirm X Shipments ($Y.YY)" button
- Cancel button with outline style
- Loading state during confirmation
- Smooth transitions

**Dashboard.tsx (413 lines) - Updated:**
- Four-phase workflow: input -> preview -> executing -> complete
- Integrated CommandInput with example chips
- Integrated CommandHistory with click-to-reuse
- Integrated PreviewGrid for shipment cards
- Integrated ConfirmationFooter sticky bar
- Command history loading on mount
- Error handling for submit and confirm failures

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `CommandInput.tsx` | 190 | NL command text input with submit |
| `CommandHistory.tsx` | 203 | Recent commands with click-to-reuse |
| `PreviewGrid.tsx` | 279 | Shipment preview card grid |
| `ConfirmationFooter.tsx` | 188 | Sticky confirm/cancel footer |
| `Dashboard.tsx` | 413 | Main page composing all components |
| `preview.py` | 145 | Backend preview and confirm endpoints |

## Commits

| Hash | Description |
|------|-------------|
| `2854bbd` | Add preview and confirm API endpoints |
| `15a580b` | Add CommandInput and CommandHistory components |
| `b1cc049` | Integrate new components into Dashboard |

## Verification Results

- [x] `npm run build` - Builds successfully (66 modules)
- [x] `pytest tests/` - 654 passed, 36 skipped
- [x] CommandInput accepts text and calls onSubmit on Enter
- [x] CommandHistory displays recent commands with click-to-reuse
- [x] PreviewGrid renders shipment cards from BatchPreview data
- [x] ConfirmationFooter shows sticky bar with confirm/cancel buttons
- [x] Dashboard manages workflow state (input -> preview -> confirm)
- [x] GET /api/v1/jobs/{id}/preview returns preview data
- [x] POST /api/v1/jobs/{id}/confirm updates job status
- [x] Costs display correctly formatted as currency ($X.XX)
- [x] Line counts meet requirements (all components exceed minimums)

## Deviations from Plan

None - plan executed exactly as written.

## Dependencies for Next Plans

- **07-04 (Progress Display)**: Already has ProgressDisplay, ErrorAlert, RowStatusTable integrated
- **07-05 (Label Management)**: Will add label preview modal and download functionality
- **07-06 (Integration)**: Full end-to-end testing with backend

## Notes

Some commits (6163635, 4ea8aeb, 6f26b8e) were created by prior work on 07-04 components but the Dashboard integration for 07-03's new components was completed in this plan execution. The workflow now supports the complete command -> preview -> confirm flow.
