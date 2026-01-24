# Phase 3: UPS Integration MCP - Research

## 1. MCP TypeScript SDK Patterns

### Server Setup with stdio Transport

```typescript
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import * as z from 'zod';

const server = new McpServer({
    name: 'ups-mcp',
    version: '1.0.0'
});

// Connect via stdio (for spawned processes)
const transport = new StdioServerTransport();
await server.connect(transport);
```

### Tool Registration Pattern

```typescript
server.registerTool(
    'tool-name',
    {
        title: 'Tool Title',
        description: 'What the tool does',
        inputSchema: {
            param1: z.string().describe('Description'),
            param2: z.number().optional()
        },
        outputSchema: {
            result: z.string(),
            data: z.object({...})
        }
    },
    async ({ param1, param2 }) => {
        const output = { result: 'value', data: {...} };
        return {
            content: [{ type: 'text', text: JSON.stringify(output) }],
            structuredContent: output
        };
    }
);
```

### Key Patterns
- Input/output schemas defined with Zod
- Handler receives destructured params
- Return both `content` (text for LLM) and `structuredContent` (typed data)
- Use `StdioServerTransport` for Claude SDK integration

---

## 2. OpenAPI to Zod Generation

### Tool: openapi-zod-client

```bash
# Install
pnpm add -D openapi-zod-client

# Generate from YAML
pnpx openapi-zod-client ./docs/shipping.yaml -o ./src/generated/shipping.ts --export-schemas
pnpx openapi-zod-client ./docs/rating.yaml -o ./src/generated/rating.ts --export-schemas
```

### Key Options
- `--export-schemas` - Export all `#/components/schemas` as Zod schemas
- `-o` - Output path
- `--implicit-required` - Make properties required by default

### Generated Output
- Zod schemas for all request/response types
- Can import schemas directly: `import { ShipmentRequestSchema } from './generated/shipping'`

### Alternative: Manual Schemas
For complex cases or selective generation, define Zod schemas manually based on OpenAPI spec. This gives more control over validation messages and optional fields.

---

## 3. UPS OAuth 2.0 Implementation

### Token Endpoint
```
POST https://wwwcie.ups.com/security/v1/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
```

### Headers Required
```
Authorization: Basic base64(client_id:client_secret)
```

### Response
```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 14399,
  "issued_at": "1234567890"
}
```

### Token Management Pattern
```typescript
class UpsAuthManager {
  private token: string | null = null;
  private expiresAt: number = 0;

  async getToken(): Promise<string> {
    if (this.token && Date.now() < this.expiresAt - 60000) {
      return this.token; // Return cached, with 1min buffer
    }
    return this.refreshToken();
  }

  private async refreshToken(): Promise<string> {
    const response = await fetch('https://wwwcie.ups.com/security/v1/oauth/token', {
      method: 'POST',
      headers: {
        'Authorization': `Basic ${btoa(`${clientId}:${clientSecret}`)}`,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: 'grant_type=client_credentials'
    });

    if (!response.ok) {
      this.token = null;
      throw new UpsAuthError('Token refresh failed');
    }

    const data = await response.json();
    this.token = data.access_token;
    this.expiresAt = Date.now() + (data.expires_in * 1000);
    return this.token;
  }

  clearToken(): void {
    this.token = null;
    this.expiresAt = 0;
  }
}
```

---

## 4. HTTP Client and Retry Pattern

### Fetch with Retry
```typescript
async function fetchWithRetry(
  url: string,
  options: RequestInit,
  maxRetries = 3
): Promise<Response> {
  const delays = [1000, 2000, 4000]; // Exponential backoff

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch(url, options);

      // Don't retry 4xx client errors
      if (response.status >= 400 && response.status < 500) {
        return response;
      }

      // Retry 5xx server errors
      if (response.status >= 500 && attempt < maxRetries) {
        await sleep(delays[attempt]);
        continue;
      }

      return response;
    } catch (error) {
      // Network error - retry
      if (attempt < maxRetries) {
        await sleep(delays[attempt]);
        continue;
      }
      throw error;
    }
  }

  throw new Error('Max retries exceeded');
}
```

### UPS API Client Pattern
```typescript
class UpsApiClient {
  constructor(
    private authManager: UpsAuthManager,
    private baseUrl = 'https://wwwcie.ups.com/api'
  ) {}

  async request<T>(
    method: string,
    path: string,
    body?: unknown
  ): Promise<T> {
    const token = await this.authManager.getToken();

    const response = await fetchWithRetry(`${this.baseUrl}${path}`, {
      method,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        'transId': crypto.randomUUID(),
        'transactionSrc': 'shipagent'
      },
      body: body ? JSON.stringify(body) : undefined
    });

    if (!response.ok) {
      const error = await response.json();
      throw new UpsApiError(error);
    }

    return response.json();
  }
}
```

---

## 5. Label Handling

### UPS Returns Base64 PDF
The Shipping API returns labels as Base64-encoded PDF in the response:
```json
{
  "ShipmentResponse": {
    "ShipmentResults": {
      "PackageResults": [{
        "ShippingLabel": {
          "GraphicImage": "JVBERi0xLjQK...", // Base64 PDF
          "ImageFormat": { "Code": "PDF" }
        }
      }]
    }
  }
}
```

### Decode and Save Pattern
```typescript
import { writeFile, mkdir } from 'fs/promises';
import { join } from 'path';

async function saveLabel(
  trackingNumber: string,
  base64Data: string,
  outputDir: string
): Promise<string> {
  await mkdir(outputDir, { recursive: true });

  const buffer = Buffer.from(base64Data, 'base64');
  const filePath = join(outputDir, `${trackingNumber}.pdf`);

  await writeFile(filePath, buffer);
  return filePath;
}
```

---

## 6. UPS API Endpoints Summary

### Rating API
```
POST /rating/v2409/{requestoption}
- requestoption: Rate | Shop | Ratetimeintransit | Shoptimeintransit
```

### Shipping API
```
POST /shipments/v2409/ship           - Create shipment
DELETE /shipments/v2409/void/cancel/{trackingNumber} - Void shipment
POST /labels/v2409/recovery          - Recover/reprint label
```

### Address Validation API
```
POST /addressvalidation/v2/1         - Validate address
```

---

## 7. Recommended Plan Breakdown

### Plan 03-01: Package Foundation
- TypeScript project setup (tsconfig, package.json)
- Dependency installation (@modelcontextprotocol/sdk, zod)
- Generate Zod schemas from OpenAPI specs
- Basic MCP server skeleton with stdio transport
- Environment validation (fail fast on missing credentials)

### Plan 03-02: OAuth & HTTP Client
- UpsAuthManager class (token acquisition, refresh, caching)
- UpsApiClient class (request wrapper with retry logic)
- Error types (UpsAuthError, UpsApiError)
- Unit tests for auth flow

### Plan 03-03: Rating Tools
- `rating_quote` tool (specific service)
- `rating_shop` tool (all services)
- Response transformation (extract costs, transit times)
- Handle unavailable services

### Plan 03-04: Shipping Tools
- `shipping_create` tool (create shipment, save label)
- `shipping_void` tool (cancel shipment)
- `shipping_get_label` tool (reprint existing label)
- Label file management

### Plan 03-05: Address Validation
- `address_validate` tool
- Response classification (valid, ambiguous, invalid)

### Plan 03-06: Integration Testing
- End-to-end tests against UPS sandbox
- Tool response verification
- Error handling verification

---

## 8. Key Files to Create

```
packages/ups-mcp/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts              # Entry point, MCP server setup
│   ├── config.ts             # Environment variable loading
│   ├── generated/
│   │   ├── shipping.ts       # Generated Zod schemas
│   │   └── rating.ts         # Generated Zod schemas
│   ├── auth/
│   │   └── manager.ts        # OAuth token management
│   ├── client/
│   │   ├── api.ts            # HTTP client with retry
│   │   └── errors.ts         # Error types
│   ├── tools/
│   │   ├── rating.ts         # rating_quote, rating_shop
│   │   ├── shipping.ts       # shipping_create, shipping_void, shipping_get_label
│   │   └── address.ts        # address_validate
│   └── utils/
│       └── labels.ts         # Label file handling
└── tests/
    ├── auth.test.ts
    ├── rating.test.ts
    ├── shipping.test.ts
    └── integration.test.ts
```

---

## RESEARCH COMPLETE

Research covers all technical areas needed for planning. Key findings:
1. MCP SDK uses `registerTool` with Zod schemas for input/output validation
2. `openapi-zod-client` can generate schemas from UPS OpenAPI specs
3. UPS OAuth uses client_credentials grant with Basic auth header
4. Token should be cached with 1-minute buffer before expiry
5. Retry only on 5xx/network errors, not 4xx
6. Labels are Base64 PDF, decode with Buffer and write to file
7. 6 plans recommended for logical separation of concerns
