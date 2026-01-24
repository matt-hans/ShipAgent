---
phase: 03
plan: 05
subsystem: ups-mcp
tags: [typescript, address-validation, mcp-tools, zod-schemas]

dependency-graph:
  requires:
    - 03-02 (OAuth Authentication)
  provides:
    - address_validate MCP tool for UPS address verification
    - Standardized address output for valid addresses
    - Candidate suggestions for ambiguous addresses
    - Clear error reasons for invalid addresses
  affects:
    - 03-06 (Integration Tests)

tech-stack:
  added: []
  patterns:
    - MCP tool registration with Zod input/output schemas
    - UPS XAV Response parsing for valid/ambiguous/invalid status
    - Address classification extraction (commercial/residential)

key-files:
  created:
    - packages/ups-mcp/src/tools/address.ts
    - packages/ups-mcp/tests/address.test.ts
  modified:
    - packages/ups-mcp/src/index.ts

decisions:
  - id: address-tool-separate
    summary: "address_validate is standalone, not integrated with shipping_create"
    rationale: "Per CONTEXT.md: users compose validation into their workflow as needed"
  - id: xav-status-enum
    summary: "Use 'valid', 'ambiguous', 'invalid' status enum"
    rationale: "Maps directly to UPS XAV indicators for clear API semantics"
  - id: zip-plus-4-format
    summary: "Format extended postal codes as ZIP-4 (e.g., 90001-1234)"
    rationale: "Standard US postal format, combines PostcodePrimaryLow and PostcodeExtendedLow"

metrics:
  duration: 7m
  completed: 2026-01-24
---

# Phase 3 Plan 5: Address Validation Summary

**One-liner:** UPS address validation MCP tool returning valid/ambiguous/invalid status with standardized addresses, candidate suggestions, or clear error reasons.

## What Was Built

### Address Validation Tool (`src/tools/address.ts`)

MCP tool `address_validate` for verifying addresses with UPS:

**Input Schema:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| addressLine1 | string | Yes | Street address line 1 |
| addressLine2 | string | No | Street address line 2 |
| city | string | Yes | City name |
| stateProvinceCode | string | Yes | State/province code (e.g., CA, NY) |
| postalCode | string | Yes | Postal/ZIP code |
| countryCode | string | No | Country code (defaults to US) |

**Output Schema:**
| Field | Type | Description |
|-------|------|-------------|
| status | enum | 'valid', 'ambiguous', or 'invalid' |
| classification | enum? | 'commercial', 'residential', or 'unknown' |
| validatedAddress | object? | Standardized address (for valid status) |
| candidates | array? | Candidate addresses (for ambiguous status) |
| invalidReason | string? | Error description (for invalid status) |

**API Integration:**
- POST to `/addressvalidation/v2/1`
- Builds UPS XAVRequest with AddressKeyFormat structure
- Parses XAVResponse for ValidAddressIndicator, AmbiguousAddressIndicator, NoCandidatesIndicator
- Extracts classification from AddressClassification.Code (1=commercial, 2=residential)

### Unit Tests (`tests/address.test.ts`)

15 tests covering:

| Category | Tests |
|----------|-------|
| Valid address | status, standardized address, classification |
| Ambiguous address | candidates array, classification per candidate |
| Invalid address | status, error reason |
| Optional fields | addressLine2, countryCode default, classification handling |
| API format | endpoint path, request body structure |

## Key Design Decisions

### Separate Address Tool
Per CONTEXT.md: `address_validate` is a standalone tool. `shipping_create` does NOT auto-validate. Users compose validation into their workflow as needed, enabling flexibility in batch processing.

### Status Enum Mapping
The three status values map directly to UPS XAV indicators:
- `ValidAddressIndicator` present -> status: 'valid'
- `AmbiguousAddressIndicator` present -> status: 'ambiguous'
- `NoCandidatesIndicator` present -> status: 'invalid'

### ZIP+4 Formatting
When UPS returns extended postal codes (PostcodeExtendedLow), they are formatted as standard ZIP+4 (e.g., "90001-1234") for consistent output.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

All verification checks passed:

```
OK: address.ts exists
OK: address_validate tool implemented
OK: status enum includes valid/ambiguous/invalid
OK: registerAddressTools in index.ts
OK: TypeScript compiles
OK: 15 address tests pass
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 26c5302 | feat | implement address_validate MCP tool |
| ab22e1a | feat | register address tool and add tests |

## Next Plan Readiness

Plan 03-06 (Integration Tests) can proceed. This plan provides:
- Complete address validation tool
- Unit test patterns to follow
- All Phase 3 tools now implemented (rating, shipping, address)

**Blockers for next plan:** None

---

*Completed: 2026-01-24 | Duration: 7 minutes*
