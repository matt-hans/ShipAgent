---
phase: 09-angular-module-federation-frontend-rebuild
plan: 08
subsystem: domain-remote
tags: [angular, native-federation, domain-cards, tracking, pickup, location, landed-cost, paperless, contact, job-detail, pdf-viewer, ng2-pdf-viewer]
dependency_graph:
  requires: [09-04-PLAN]
  provides: [DomainCardRegistryService, PickupPreviewComponent, PickupCompletionComponent, LocationCardComponent, LandedCostCardComponent, PaperlessCardComponent, PaperlessUploadComponent, TrackingCardComponent, ContactCardComponent, JobDetailPanelComponent, LabelPreviewComponent]
  affects: [chat-remote, domain-remote, shell]
tech_stack:
  added:
    - "ng2-pdf-viewer v10.4.0 — PdfViewerModule for in-browser PDF label rendering"
    - "DomainCardRegistryService — registry mapping SSE card type strings to Angular component Types"
  patterns:
    - "Registry pattern: DomainCardRegistryService.resolve(cardType) returns Type<unknown> for ngComponentOutlet"
    - "All domain cards standalone, OnPush, Angular 21 @if/@for control flow"
    - "Card state via signals (isConfirming, uploadState, cardState, isExpanded)"
    - "LandedCostCardComponent uses component-level fmtAmount helper (no pipe needed)"
    - "TrackingCardComponent uses computed() for visibleActivities with expand/collapse"
    - "ContactCardComponent implements 3-state machine: active -> confirmed/deleted"
    - "JobDetailPanelComponent reads from JobStore.activeJob() signal"
    - "LabelPreviewComponent derives URL from labelUrl > jobId/rowNumber > trackingNumber"
    - "Boolean() filtered in templates via protected method (Angular template restriction)"
key_files:
  created:
    - shipagent-frontend/apps/domain-remote/src/app/domain-card-registry.service.ts
    - shipagent-frontend/apps/domain-remote/src/app/pickup-preview/pickup-preview.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/pickup-completion/pickup-completion.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/location-card/location-card.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/landed-cost-card/landed-cost-card.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/paperless-card/paperless-card.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/paperless-upload/paperless-upload.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/tracking-card/tracking-card.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/contact-card/contact-card.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/job-detail-panel/job-detail-panel.component.ts
    - shipagent-frontend/apps/domain-remote/src/app/label-preview/label-preview.component.ts
  modified:
    - shipagent-frontend/apps/domain-remote/src/app/remote-entry.ts
decisions:
  - "DomainCardRegistryService is @Injectable() (not root-scoped) — provided by consuming remote's Injector so each remote gets its own instance; avoids cross-remote DI pollution"
  - "TrackingCardComponent uses computed() signal for visibleActivities — avoids recalculating on every CD cycle; collapses to 3 activities by default"
  - "LabelPreviewComponent uses ng2-pdf-viewer PdfViewerModule — supports Angular 21, no pdfjs worker config needed unlike react-pdf"
  - "ContactCardComponent handles delete by fetching contacts and finding by handle — mirrors React implementation; @handle is user-visible key but server uses UUID"
  - "Boolean() global not accessible in Angular templates — replaced .filter(Boolean) with protected formatAlert() method in PaperlessCardComponent"
  - "JobDetailPanelComponent uses displayCostCents() as plain function (not computed signal) — activeJob is already a signal from NgRx SignalStore"
metrics:
  duration_minutes: 11
  completed: 2026-03-25T00:19:47Z
  tasks_completed: 2
  files_created: 11
  files_modified: 1
---

# Phase 9 Plan 08: Domain Remote — Registry, Cards, Job Detail, Label Preview

Complete domain-remote with DomainCardRegistryService, all 8 domain card components ported from React, job detail panel reading from JobStore, and PDF label viewer using ng2-pdf-viewer.

## What Was Built

### DomainCardRegistryService
Registry service mapping SSE card type strings to Angular component Types for ngComponentOutlet dynamic rendering. Resolves 8 card types: `pickup_preview`, `pickup_completion`, `location_result`, `landed_cost_result`, `tracking_result`, `paperless_result`, `paperless_upload`, `contact_saved`.

### Domain Card Components (8 total)

All standalone, OnPush, Angular 21 `@if`/`@for` control flow, domain-specific CSS classes:

| Component | Source | Domain Color | Key Feature |
|-----------|--------|-------------|-------------|
| PickupPreviewComponent | PickupPreviewCard.tsx | `card-domain-pickup` | Confirm/cancel with charge breakdown |
| PickupCompletionComponent | PickupCompletionCard.tsx | `card-domain-pickup` | scheduled/cancelled/rated/status variants |
| LocationCardComponent | LocationCard.tsx | `card-domain-locator` | Expand/collapse panels with UPS detail dump |
| LandedCostCardComponent | LandedCostCard.tsx | `card-domain-landed-cost` | Commodity table, brokerage, copy shipment ID |
| PaperlessCardComponent | PaperlessCard.tsx | `card-domain-paperless` | File metadata, document IDs, UPS alerts |
| PaperlessUploadComponent | PaperlessUploadCard.tsx | `card-domain-paperless` | Drag-drop picker, ApiService upload |
| TrackingCardComponent | TrackingCard.tsx | `card-domain-tracking` | Collapsible activity timeline (3 default) |
| ContactCardComponent | ContactCard.tsx | `card-domain-contacts` | 3-state machine, confirm/delete actions |

### JobDetailPanelComponent
Full job information panel reading from `JobStore.activeJob()` signal. Shows summary stats (total/success/failed/cost), expand/collapse per-row details with order data + address + charge breakdown, confirm/cancel for pending jobs, merged PDF + ZIP download links for completed jobs.

### LabelPreviewComponent
PDF label viewer using `PdfViewerModule` from ng2-pdf-viewer. Resolves PDF URL from priority inputs (labelUrl → jobId/rowNumber → trackingNumber). Loading and error states. Download (browser anchor) and print (window.open + print()) actions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Angular template cannot access global `Boolean` function**
- **Found during:** Task 1 build compilation
- **Issue:** PaperlessCardComponent template used `.filter(Boolean)` in an interpolation expression; Angular templates don't expose browser globals
- **Fix:** Added `protected formatAlert(alert)` method to PaperlessCardComponent returning `[alert.code, alert.message].filter((v) => v != null && v !== '').join(': ')`
- **Files modified:** `paperless-card/paperless-card.component.ts`
- **Commit:** 24a6010

**2. [Rule 1 - Bug] Unused imports caused TypeScript compilation errors**
- **Found during:** Task 1 and Task 2 build compilation
- **Issue:** `OnDestroy`, `Job`, `computed`, `apiService` (unused inject) left in components from initial port; TS6133/TS6196 errors block build
- **Fix:** Removed all unused imports and inject calls across job-detail-panel, label-preview, location-card
- **Files modified:** Multiple component files
- **Commit:** 24a6010, 2402948

## Verification

```
nx build domain-remote  → Successfully ran target build for project domain-remote
nx test domain-remote   → 1 passed (1)
```

- DomainCardRegistryService resolves all 8 card type strings
- All domain cards render with correct data bindings and domain CSS classes
- PickupPreviewComponent has confirm/cancel action buttons with isConfirming signal
- PaperlessUploadComponent uses ApiService.uploadDocument() via firstValueFrom
- TrackingCardComponent shows collapsible activity timeline (3 default, computed signal)
- LabelPreviewComponent uses PdfViewerModule with loading/error states
- JobDetailPanelComponent reads from JobStore.activeJob() signal, label download URLs from ApiService

## Self-Check: PASSED

Files verified:
- `shipagent-frontend/apps/domain-remote/src/app/domain-card-registry.service.ts` FOUND
- `shipagent-frontend/apps/domain-remote/src/app/tracking-card/tracking-card.component.ts` FOUND
- `shipagent-frontend/apps/domain-remote/src/app/contact-card/contact-card.component.ts` FOUND
- `shipagent-frontend/apps/domain-remote/src/app/job-detail-panel/job-detail-panel.component.ts` FOUND
- `shipagent-frontend/apps/domain-remote/src/app/label-preview/label-preview.component.ts` FOUND

Commits verified:
- 24a6010: feat(09-08): build DomainCardRegistryService and all 8 domain card components
- 2402948: feat(09-08): build job detail panel and label preview with PDF rendering
