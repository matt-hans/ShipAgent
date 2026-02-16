# Landed Cost Debug Report

**Date**: 2026-02-16
**Status**: BLOCKED - UPS CIE Infrastructure Issue
**Priority**: P1 - Feature Not Working in Test Environment

---

## Executive Summary

The Landed Cost functionality is **blocked by an internal UPS CIE infrastructure issue**. The API returns HTTP 500 with an internal authentication failure against Microsoft Azure AD. This is NOT a client-side bug but rather a UPS backend issue in their Customer Integration Environment (CIE).

---

## Test Results

### Paperless Document Upload ✅ WORKING
- Document uploaded successfully to UPS Forms History
- Document ID: `2013-12-04-00.15.33.207814`
- PaperlessCard displays correctly with all fields

### Landed Cost ❌ FAILING
- Error: HTTP 500 Internal Server Error
- Root Cause: UPS CIE internal OAuth token service failure

---

## Root Cause Analysis

### Direct API Test Output

```bash
$ python3 -c "from ups_mcp.tools import ToolManager; ..."
ERROR: ToolError {
  "status_code": 500,
  "code": "500",
  "message": "UPS API returned HTTP 500",
  "details": {
    "raw": "org.apache.camel.http.common.HttpOperationFailedException:
            HTTP operation failed invoking
            https://login.microsoftonline.com/e7520e4d-d5a0-488d-9e9f-949faae7dce8/oauth2/v2.0/token
            with statusCode: 401"
  }
}
```

### Analysis

| Observation | Interpretation |
|-------------|----------------|
| HTTP 500 from UPS | Server-side error, not client error |
| `login.microsoftonline.com` | UPS CIE uses Azure AD internally |
| `statusCode: 401` in stack trace | Internal auth failure within UPS infrastructure |
| `CIEOauth2RouteBuilder.renewAuth` | UPS CIE's internal OAuth refresh is failing |

**Conclusion**: The UPS CIE environment's internal token service is broken or misconfigured. This is outside our control.

---

## Code Path Analysis

### 1. Request Flow (Correct)

```
User Command
    → Agent (get_landed_cost tool)
    → ShipAgent UPSMCPClient.get_landed_cost()
    → MCP stdio call: get_landed_cost_quote
    → UPS MCP ToolManager.get_landed_cost_quote()
    → UPSHTTPClient.call_operation()
    → POST https://wwwcie.ups.com/api/landedcost/v1/quotes
    → [FAILS HERE] UPS CIE returns 500
```

### 2. Request Body Construction (Correct)

The ups-mcp implementation correctly constructs the request:

```python
# ups_mcp/tools.py:282-340
request_body = {
    "currencyCode": currency_code,
    "transID": str(uuid.uuid4()),
    "allowPartialLandedCostResult": True,
    "alversion": 1,
    "shipment": {
        "id": str(uuid.uuid4()),
        "importCountryCode": import_country_code,
        "exportCountryCode": export_country_code,
        "shipmentItems": shipment_items,  # Properly formatted
        "shipmentType": shipment_type,
    },
}
```

### 3. Headers (Correct)

```python
# ups_mcp/http_client.py:51-60
headers = {
    "Authorization": f"Bearer {token}",
    "transId": request_trans_id,
    "transactionSrc": request_transaction_src,
    "AccountNumber": effective_account,  # Added correctly
}
```

### 4. Test Parameters Used

Following user guidance for "known-good" CIE request:

| Parameter | Value | Source |
|-----------|-------|--------|
| currencyCode | GBP | UPS sample |
| exportCountryCode | US | Simple lane |
| importCountryCode | GB | Simple lane |
| hsCode | 400932 | UPS sample HS code |
| priceEach | 125 | UPS sample |
| quantity | 24 | UPS sample |
| commodityCurrencyCode | GBP | Consistent with top-level |
| originCountryCode | GB | UPS sample pattern |

---

## Potential Issues to Investigate

### 1. CIE Enrollment Required (Most Likely)

The Landed Cost API may require **separate enrollment** even for CIE access. Unlike Rating/Shipping which are universally available, Landed Cost might need:
- [ ] Contact UPS support to verify account has Landed Cost enabled for CIE
- [ ] Check if additional OAuth scopes are required
- [ ] Verify the UPS developer app has Landed Cost permission

### 2. CIE vs Production Environment

The error shows UPS CIE trying to authenticate internally with Azure AD. This could indicate:
- [ ] CIE environment has intermittent Landed Cost availability
- [ ] Production credentials might work where CIE fails
- [ ] Special CIE-LC enrollment may be required

### 3. Test Account Limitations

The test account may have:
- [ ] Landed Cost not enabled (similar to how some pickup locations aren't in CIE)
- [ ] Geographic restrictions for LC calculations
- [ ] Rate limits already exceeded

### 4. API Version/Endpoint Issues

According to user guidance, the correct endpoint is:
```
POST https://wwwcie.ups.com/api/landedcost/v1/quotes
```

The implementation uses this correctly, but:
- [ ] Verify CIE endpoint is actually available (not just documented)
- [ ] Check if there's an alternative CIE endpoint for LC

---

## Recommended Resolution Steps

### Immediate Actions

1. **Contact UPS Developer Support**
   - Ask specifically: "Is Landed Cost Quote API available in CIE?"
   - Request: "Verify my account has Landed Cost access enabled"
   - Reference: The HTTP 500 with `CIEOauth2RouteBuilder` error

2. **Check UPS Developer Portal**
   - Navigate to the developer app settings
   - Verify Landed Cost API is listed under enabled APIs
   - Check for any special enrollment requirements

3. **Try Production Environment** (if possible)
   - The error is internal to CIE, production might work
   - Temporarily switch base URL to test

### Code Changes (If Needed)

If UPS confirms CIE requires special handling, consider:

```python
# ups_mcp/tools.py - Add CIE-specific error handling
def get_landed_cost_quote(...):
    try:
        return self._execute_operation(...)
    except ToolError as e:
        error_data = json.loads(str(e))
        if error_data.get("status_code") == 500:
            if "login.microsoftonline.com" in str(error_data.get("details", {})):
                raise ToolError(json.dumps({
                    "code": "CIE_UNAVAILABLE",
                    "message": "Landed Cost API is not available in UPS CIE. "
                              "Contact UPS support or try production environment.",
                }))
        raise
```

### Frontend Improvements

The current error message in ShipAgent is generic. Update `LandedCostCard` to detect CIE issues:

```typescript
// frontend/src/components/command-center/LandedCostCard.tsx
if (error?.includes("CIE") || error?.includes("500")) {
  return (
    <div className="cie-unavailable">
      <h4>Landed Cost Unavailable in Test Environment</h4>
      <p>The UPS test environment (CIE) does not support Landed Cost quotes.</p>
      <p>Contact UPS support for production access.</p>
    </div>
  );
}
```

---

## Test Evidence

### Successful Paperless Upload

```
✅ Document Uploaded
   File: test_invoice.pdf
   Type: Commercial Invoice · PDF · 43 KB
   Document ID: 2013-12-04-00.15.33.207814
   Status: Uploaded to UPS Forms History
```

### Failed Landed Cost Request

```
❌ Landed Cost Request
   Parameters: US → GB, GBP, 24 units @ $125, HS 400932
   Error: HTTP 500 - Internal UPS OAuth failure
   Stack: CIEOauth2RouteBuilder.renewAuth → Azure AD 401
```

---

## Files Analyzed

| File | Purpose |
|------|---------|
| `ups-mcp/ups_mcp/tools.py:282-340` | Landed cost tool implementation |
| `ups-mcp/ups_mcp/http_client.py:1-100` | HTTP request handling |
| `ups-mcp/ups_mcp/specs/LandedCost.yaml` | OpenAPI spec for Landed Cost |
| `ShipAgent/src/services/ups_mcp_client.py:514-553` | ShipAgent wrapper |
| `ShipAgent/src/orchestrator/agent/tools/__init__.py:600-645` | Tool definition |
| `ShipAgent/src/orchestrator/agent/tools/pipeline.py:388-414` | Tool handler |

---

## Conclusion

**This is NOT a bug in ShipAgent or ups-mcp.** The implementation is correct and follows UPS's documented API patterns. The failure is occurring inside UPS's CIE infrastructure when their backend tries to obtain an internal OAuth token from Azure AD.

**Next Step**: Contact UPS Developer Support to verify Landed Cost API availability in CIE and account enrollment status.

---

## Appendix: User Guidance Applied

Per user's detailed CIE guidance:

| Recommendation | Applied | Result |
|----------------|---------|--------|
| Use CIE endpoint `wwwcie.ups.com/api/landedcost/v1/quotes` | ✅ | Still fails |
| Send `transId` header | ✅ | N/A - fails before reaching API |
| Send `transactionSrc` header | ✅ | N/A - fails before reaching API |
| Send `AccountNumber` header | ✅ | N/A - fails before reaching API |
| Use known-good HS code `400932` | ✅ | N/A - fails before reaching API |
| Use simple lane US→GB | ✅ | N/A - fails before reaching API |
| Consistent currency fields | ✅ | N/A - fails before reaching API |

The error occurs at the UPS infrastructure level (OAuth token refresh), before the actual Landed Cost API is even invoked. This confirms the issue is with UPS CIE, not the request format.
