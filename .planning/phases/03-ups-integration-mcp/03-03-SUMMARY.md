---
phase: 03
plan: 03
subsystem: ups-mcp
tags: [typescript, rating, mcp-tools, ups-api, cost-breakdown]

dependency-graph:
  requires:
    - 03-01 (TypeScript Package & Schema Foundation)
    - 03-02 (OAuth Authentication)
  provides:
    - rating_quote MCP tool for specific service rates
    - rating_shop MCP tool for comparing all services
    - Cost breakdown extraction with fuel/accessorial charges
    - Transit time and delivery date information
  affects:
    - 03-06 (Integration Tests)

tech-stack:
  added: []
  patterns:
    - Zod schemas for MCP tool input validation
    - UPS Rating API v2403 endpoints
    - Response transformation with service name mapping
    - Unavailable services marked with reason (not omitted)

key-files:
  created:
    - packages/ups-mcp/src/tools/rating.ts
    - packages/ups-mcp/tests/rating.test.ts
  modified:
    - packages/ups-mcp/src/index.ts

decisions:
  - id: zod-schema-for-mcp-tools
    summary: "Use Zod object shape for MCP tool registration"
    rationale: "MCP SDK expects Zod schemas for parameter validation, not JSON Schema objects"
  - id: service-name-mapping
    summary: "Map UPS service codes to human-readable names"
    rationale: "Users understand 'UPS Ground' better than code '03'"
  - id: itemized-charge-extraction
    summary: "Extract fuel, delivery area, and residential surcharges from RatedPackage"
    rationale: "UPS returns itemized charges at package level with codes 376, 375, 400"

metrics:
  duration: 6m
  completed: 2026-01-24
---

# Phase 3 Plan 3: Rating Tools Summary

**One-liner:** Two MCP tools (rating_quote, rating_shop) for UPS rate quotes with itemized cost breakdowns and transit time information.

## What Was Built

### Rating Tools Module (`src/tools/rating.ts`)

Two MCP tools for querying UPS Rating API:

| Tool | Purpose | Endpoint |
|------|---------|----------|
| `rating_quote` | Get rate for specific UPS service | `/rating/v2403/Rate` |
| `rating_shop` | Compare rates across all services | `/rating/v2403/Shop` |

### Input Schema

Both tools accept:

```typescript
{
  shipFrom: {
    name: string,
    addressLine1: string,
    addressLine2?: string,
    city: string,
    stateProvinceCode: string,
    postalCode: string,
    countryCode: string  // default "US"
  },
  shipTo: { /* same structure */ },
  packages: [{
    weight: number,      // pounds
    length?: number,     // inches
    width?: number,
    height?: number,
    packagingType?: string  // default "02" (Package)
  }],
  serviceCode?: string   // required for rating_quote
}
```

### Output Schema

Rate responses include:

```typescript
{
  service: { code: string, name: string },
  available: boolean,
  unavailableReason?: string,
  totalCharges?: { currency: string, amount: string },
  breakdown?: [{
    type: string,      // "Transportation", "Fuel Surcharge", etc.
    currency: string,
    amount: string
  }],
  deliveryDate?: string,   // YYYYMMDD
  deliveryTime?: string,   // HHMMSS
  businessDays?: number
}
```

### Service Name Mapping

Maps UPS service codes to human-readable names:

| Code | Name |
|------|------|
| 01 | UPS Next Day Air |
| 02 | UPS 2nd Day Air |
| 03 | UPS Ground |
| 12 | UPS 3 Day Select |
| 13 | UPS Next Day Air Saver |
| 14 | UPS Next Day Air Early |
| 59 | UPS 2nd Day Air A.M. |
| 65 | UPS Saver |

### Cost Breakdown Extraction

Extracts itemized charges from UPS response:

- **Transportation**: Base shipping cost
- **Base Service**: Service-specific charges
- **Service Options**: Optional service charges
- **Fuel Surcharge** (code 376): Fuel cost component
- **Delivery Area Surcharge** (code 375): Remote area charges
- **Residential Surcharge** (code 400): Home delivery charges

### Unavailable Service Handling

Per CONTEXT.md requirement, unavailable services are returned with `available: false` and reason, not omitted:

```typescript
{
  service: { code: "01", name: "UPS Next Day Air" },
  available: false,
  unavailableReason: "Next Day Air service is not available for this route"
}
```

### Unit Tests (`tests/rating.test.ts`)

15 tests covering:

| Category | Tests |
|----------|-------|
| Tool Registration | rating_quote and rating_shop registered |
| Request Building | Correct UPS API structure, service code, account number |
| Response Transformation | Cost breakdown, delivery date, business days |
| Itemized Charges | Fuel surcharge extraction (code 376) |
| Unavailable Services | Marked with available=false and reason |
| Service Names | Known codes mapped, unknown codes handled |
| Package Handling | Dimensions, multiple packages |
| Error Handling | API errors returned with isError flag |

## Key Design Decisions

### Zod Schema for MCP Tools
The MCP SDK's `server.tool()` method requires Zod schemas for parameter validation. We pass `RatingQuoteInputSchema.shape` to register the tool schema correctly.

### Service Name Mapping
UPS returns service codes like "03" but users understand "UPS Ground" better. A static mapping table provides human-readable names.

### Package-Level Itemized Charges
UPS returns fuel surcharges and accessorial charges at the package level in `RatedPackage.ItemizedCharges`. We extract these with code-to-name mapping (376 = Fuel Surcharge).

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

All verification checks passed:

```
OK: rating.ts exists
OK: rating_quote found
OK: rating_shop found
OK: breakdown found
OK: deliveryDate found
OK: registerRatingTools in index.ts
OK: TypeScript compiles
OK: 15 tests pass
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 56be4bd | feat | add rating_quote and rating_shop MCP tools |
| b5025bd | feat | add package-level itemized charge extraction |
| e4a6c86 | test | add rating tools tests and server registration |

## Next Plan Readiness

Plan 03-04 (Shipping Tools) can proceed. This plan provides:
- Reference implementation for MCP tool patterns
- UPS request building patterns
- Response transformation patterns

**Blockers for next plan:** None

---

*Completed: 2026-01-24 | Duration: 6 minutes*
