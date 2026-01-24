---
phase: 03
plan: 01
subsystem: ups-mcp
tags: [typescript, mcp, zod, ups-api, schema]

dependency-graph:
  requires: []
  provides:
    - TypeScript MCP package structure
    - Zod schemas for UPS Shipping API
    - Zod schemas for UPS Rating API
    - Config validation with fail-fast behavior
    - MCP server skeleton with stdio transport
  affects:
    - 03-02 (OAuth Authentication)
    - 03-03 (Rating Tools)
    - 03-04 (Shipping Tools)

tech-stack:
  added:
    - "@modelcontextprotocol/sdk": "^1.25.0"
    - "zod": "^3.25.0"
    - "typescript": "^5.9.0"
    - "vitest": "^2.1.0"
  patterns:
    - MCP server with stdio transport
    - Environment variable validation with fail-fast
    - Zod schemas for API type safety

key-files:
  created:
    - packages/ups-mcp/package.json
    - packages/ups-mcp/tsconfig.json
    - packages/ups-mcp/.gitignore
    - packages/ups-mcp/src/config.ts
    - packages/ups-mcp/src/index.ts
    - packages/ups-mcp/src/generated/shipping.ts
    - packages/ups-mcp/src/generated/rating.ts
  modified: []

decisions:
  - id: manual-zod-schemas
    summary: "Created manual Zod schemas instead of auto-generated"
    rationale: "openapi-zod-client generates schemas with @zodios/core dependency and produces types too complex for TypeScript inference. Manual schemas are cleaner and more maintainable."
  - id: passthrough-removed-wrappers
    summary: "Removed .passthrough() from wrapper schemas"
    rationale: "Deep nesting with passthrough() causes TypeScript 'exceeds maximum length' errors. Inner schemas retain passthrough for flexibility."
  - id: sandbox-only
    summary: "Hardcoded sandbox environment URL"
    rationale: "Per CONTEXT.md Decision 1, production support is out of scope for MVP"

metrics:
  duration: 7m
  completed: 2026-01-24
---

# Phase 3 Plan 1: TypeScript Package & Schema Foundation Summary

**One-liner:** TypeScript MCP package with manually-crafted Zod schemas for UPS Shipping/Rating APIs and fail-fast credential validation.

## What Was Built

### Package Structure
Created `@shipagent/ups-mcp` TypeScript package with:
- ESM module configuration (type: "module")
- NodeNext module resolution for modern imports
- Strict TypeScript settings
- MCP SDK and Zod dependencies

### Zod Schemas

**Shipping API (`src/generated/shipping.ts`):**
- Request schemas: ShipmentRequest, ShipRequestWrapper
- Response schemas: ShipmentResponse, ShipResponseWrapper, VoidShipmentResponse
- Common types: Address, Package, Service, PaymentInformation, Shipper, ShipTo, ShipFrom
- Error handling: ErrorResponse schema

**Rating API (`src/generated/rating.ts`):**
- Request schemas: RateRequest, RateRequestWrapper
- Response schemas: RateResponse, RateResponseWrapper with RatedShipment details
- Time-in-transit support: TimeInTransit schema
- Service code constants: UPS_SERVICE_CODES map for all UPS services

### Configuration Management
- `validateConfig()` function checks UPS_CLIENT_ID, UPS_CLIENT_SECRET, UPS_ACCOUNT_NUMBER
- Fails fast with clear error listing missing variables
- Exports singleton `config` object for use across the package
- Sandbox environment hardcoded per CONTEXT.md

### MCP Server Skeleton
- Entry point at `src/index.ts` using McpServer from MCP SDK
- Stdio transport configured for Claude SDK integration
- Startup messages to stderr (stdout reserved for MCP protocol)
- Graceful error handling with process exit on fatal errors

## Key Design Decisions

### Manual Schema Creation
Auto-generated schemas from openapi-zod-client required @zodios/core dependency and produced TypeScript inference errors (TS7056: exceeds maximum length). Created manual schemas that:
- Import only from zod
- Cover actual API structures we'll use
- Include helpful documentation comments
- Export both schemas and TypeScript types

### Passthrough Handling
Removed `.passthrough()` from top-level wrapper schemas to avoid TypeScript complexity issues while keeping it on inner schemas for UPS API flexibility.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] TypeScript inference failure with auto-generated schemas**
- **Found during:** Task 2
- **Issue:** openapi-zod-client generated schemas caused TS7056 errors - types too complex for serialization
- **Fix:** Replaced with manually crafted Zod schemas covering actual API structures
- **Files modified:** src/generated/shipping.ts, src/generated/rating.ts
- **Commit:** a807f7f

**2. [Rule 3 - Blocking] Removed @zodios/core dependency**
- **Found during:** Task 2
- **Issue:** Auto-generated schemas required @zodios/core; manual schemas don't need it
- **Fix:** Removed dependency from package.json
- **Files modified:** package.json
- **Commit:** a807f7f

## Verification Results

All verification checks passed:

```
OK: package.json exists
OK: tsconfig.json exists
OK: MCP SDK installed
OK: Zod installed
OK: shipping schemas exist
OK: rating schemas exist
OK: TypeScript compiles
OK: fails on missing credentials
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 14b2ecf | chore | create TypeScript MCP package structure |
| a807f7f | feat | add Zod schemas for UPS Shipping and Rating APIs |
| 20bae65 | feat | add config validation and MCP server skeleton |

## Next Plan Readiness

Plan 03-02 (OAuth Authentication) can proceed. This plan provides:
- Config object with clientId, clientSecret for OAuth
- MCP server skeleton ready for tool registration
- Zod schemas for validating API responses

**Blockers for next plan:** None

---

*Completed: 2026-01-24 | Duration: 7 minutes*
