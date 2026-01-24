---
phase: 03
plan: 04
subsystem: ups-mcp
tags: [typescript, shipping, labels, pdf, mcp-tools]

dependency-graph:
  requires:
    - 03-02 (OAuth Authentication)
  provides:
    - shipping_create MCP tool
    - shipping_void MCP tool
    - shipping_get_label MCP tool
    - Label file handling utilities
  affects:
    - 03-06 (Integration Tests)
    - Phase 4 (NL/Mapping)

tech-stack:
  added: []
  patterns:
    - Base64 PDF label decoding
    - Flat label directory structure
    - Tracking number as filename

key-files:
  created:
    - packages/ups-mcp/src/utils/labels.ts
    - packages/ups-mcp/src/tools/shipping.ts
    - packages/ups-mcp/tests/shipping.test.ts
  modified:
    - packages/ups-mcp/src/index.ts

decisions:
  - id: pdf-only-labels
    summary: "PDF format only for labels"
    rationale: "Per CONTEXT.md Decision 3, simplified implementation with single format"
  - id: tracking-number-filename
    summary: "Label filename format: {tracking_number}.pdf"
    rationale: "Easy lookup and identification per CONTEXT.md"
  - id: overwrite-existing-labels
    summary: "shipping_get_label overwrites existing file"
    rationale: "Per CONTEXT.md, reprint retrieves fresh label"

metrics:
  duration: 7m
  completed: 2026-01-24
---

# Phase 3 Plan 4: Shipping Tools Summary

**One-liner:** Three MCP tools for UPS shipment lifecycle (create, void, get_label) with automatic PDF label extraction and filesystem storage.

## What Was Built

### Label Utilities (`src/utils/labels.ts`)

Two functions for label handling:

| Function | Purpose |
|----------|---------|
| `saveLabel()` | Decodes Base64 PDF and saves to filesystem with tracking number filename |
| `extractLabelFromResponse()` | Extracts label data from UPS shipment response (handles single/multi-package) |

Per CONTEXT.md Decision 3:
- PDF format only
- Filename: `{tracking_number}.pdf`
- Flat directory structure
- MCP saves labels directly

### Shipping Tools (`src/tools/shipping.ts`)

Three MCP tools registered with the server:

| Tool | Description | UPS Endpoint |
|------|-------------|--------------|
| `shipping_create` | Create shipment, get tracking number and PDF label | POST /shipments/v2409/ship |
| `shipping_void` | Cancel existing shipment by tracking number | DELETE /shipments/v2409/void/cancel/{tracking} |
| `shipping_get_label` | Retrieve/reprint label for existing shipment | POST /labels/v2409/recovery |

**shipping_create Input Schema:**
```typescript
{
  shipper: { name, phone, addressLine1, city, stateProvinceCode, postalCode, countryCode },
  shipTo: { name, phone, addressLine1, city, stateProvinceCode, postalCode, countryCode },
  packages: [{ weight, length?, width?, height?, packagingType? }],
  serviceCode: string,  // "03" = Ground, "01" = Next Day Air
  description?: string,
  reference?: string
}
```

**shipping_create Output:**
```json
{
  "success": true,
  "trackingNumbers": ["1Z999AA10123456784"],
  "labelPaths": ["/labels/1Z999AA10123456784.pdf"],
  "totalCharges": { "currencyCode": "USD", "monetaryValue": "15.50" },
  "shipmentIdentificationNumber": "1Z999AA10123456784"
}
```

### Server Registration (`src/index.ts`)

Shipping tools registered with MCP server alongside address and rating tools:
```typescript
registerShippingTools(server, apiClient, config.accountNumber, config.labelsOutputDir);
```

### Unit Tests (`tests/shipping.test.ts`)

13 tests covering:

| Category | Tests |
|----------|-------|
| saveLabel | Directory creation, filename format, Base64 decoding |
| extractLabelFromResponse | Single package, multi-package, missing data, filtering |
| Request structure | UPS request body format |
| Response extraction | Tracking number, charges |
| Void endpoint | Path construction, response parsing |
| Get label | Request body, PDF format specification |
| Filename format | {tracking_number}.pdf pattern |

## Key Design Decisions

### PDF Only Labels
Per CONTEXT.md Decision 3, only PDF format is supported. This simplifies:
- Label handling code (no format switching)
- File extension always `.pdf`
- Consistent output for all users

### Tracking Number as Filename
Labels saved as `{tracking_number}.pdf`:
- Easy to locate specific shipment labels
- No need for index/lookup file
- Natural organization

### Overwrite Existing Labels
When `shipping_get_label` is called for a tracking number that already has a saved label:
- Existing file is overwritten
- Fresh label retrieved from UPS
- Per CONTEXT.md requirement for reprints

## Deviations from Plan

### [Rule 3 - Blocking] Fixed MCP SDK Tool Registration API
- **Found during:** Task 2
- **Issue:** rating.ts had incorrect `server.tool()` API usage causing TypeScript errors
- **Fix:** Updated to correct signature: `server.tool(name, schema.shape, callback)`
- **Files modified:** packages/ups-mcp/src/tools/rating.ts (already committed in 03-03)
- **Commit:** e4a6c86

## Verification Results

All verification checks passed:

```
OK: labels.ts exists
OK: shipping.ts exists
OK: shipping_create function present
OK: shipping_void function present
OK: shipping_get_label function present
OK: registerShippingTools in index.ts
OK: TypeScript compiles
OK: 13 shipping tests pass
OK: 54 total tests pass
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 40a9c48 | feat | add label handling utilities |
| 3616737 | feat | implement shipping MCP tools |
| c7e97ef | test | add shipping tools tests and register with server |

## Next Plan Readiness

Plan 03-05 (Address Validation) is already complete. Plan 03-06 (Integration Tests) can proceed. This plan provides:
- Full shipping tool implementation
- Label file generation
- Test patterns for mocking UPS responses

**Blockers for next plan:** None

---

*Completed: 2026-01-24 | Duration: 7 minutes*
