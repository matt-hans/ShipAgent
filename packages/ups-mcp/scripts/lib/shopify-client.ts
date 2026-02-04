/**
 * Rate-Limited Shopify HTTP Client
 *
 * HTTP client for Shopify Admin API with:
 * - Token bucket rate limiting (2 req/s standard, configurable for Plus)
 * - Retry with exponential backoff on 429/5xx errors
 * - Concurrency control via p-limit
 *
 * Pattern from: packages/ups-mcp/src/client/api.ts
 */

import pLimit from "p-limit";
import type {
  ShopifyClientConfig,
  ShopifyOrderPayload,
  ShopifyOrderResponse,
  ShopifyOrdersListResponse,
  ShopifyOrderCountResponse,
  ShopifyErrorResponse,
} from "./types.js";

/**
 * Exponential backoff delays in milliseconds
 * [1s, 2s, 4s, 8s] for up to 4 retries
 */
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000];

/**
 * Maximum number of retry attempts
 */
const MAX_RETRIES = 4;

/**
 * Default rate limit (requests per second) for standard Shopify stores
 */
const DEFAULT_RATE_LIMIT = 2;

/**
 * Error thrown when Shopify API returns an error
 */
export class ShopifyApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly errors: ShopifyErrorResponse["errors"],
    message?: string
  ) {
    super(
      message ||
        `Shopify API error (${status}): ${typeof errors === "string" ? errors : JSON.stringify(errors)}`
    );
    this.name = "ShopifyApiError";
  }
}

/**
 * Error thrown when network request fails after retries
 */
export class ShopifyNetworkError extends Error {
  constructor(
    message: string,
    public readonly cause?: Error
  ) {
    super(message);
    this.name = "ShopifyNetworkError";
  }
}

/**
 * Token bucket rate limiter
 */
class TokenBucket {
  private tokens: number;
  private lastRefill: number;
  private readonly maxTokens: number;
  private readonly refillRate: number;

  constructor(tokensPerSecond: number) {
    this.maxTokens = tokensPerSecond;
    this.refillRate = tokensPerSecond;
    this.tokens = tokensPerSecond;
    this.lastRefill = Date.now();
  }

  /**
   * Acquire a token, waiting if necessary
   */
  async acquire(): Promise<void> {
    this.refill();

    if (this.tokens >= 1) {
      this.tokens -= 1;
      return;
    }

    // Wait for token to become available
    const waitMs = ((1 - this.tokens) / this.refillRate) * 1000;
    await this.sleep(waitMs);
    this.refill();
    this.tokens -= 1;
  }

  private refill(): void {
    const now = Date.now();
    const elapsed = (now - this.lastRefill) / 1000;
    this.tokens = Math.min(this.maxTokens, this.tokens + elapsed * this.refillRate);
    this.lastRefill = now;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/**
 * Rate-limited HTTP client for Shopify Admin API
 *
 * Usage:
 * ```typescript
 * const client = new ShopifyClient({
 *   storeDomain: 'my-store.myshopify.com',
 *   accessToken: 'shpat_xxx',
 *   apiVersion: '2024-01',
 *   rateLimit: 2
 * });
 *
 * const response = await client.createOrder(orderPayload);
 * ```
 */
export class ShopifyClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly rateLimiter: TokenBucket;
  private readonly concurrencyLimiter: ReturnType<typeof pLimit>;

  constructor(private readonly config: ShopifyClientConfig) {
    this.baseUrl = `https://${config.storeDomain}/admin/api/${config.apiVersion}`;
    this.headers = {
      "Content-Type": "application/json",
      "X-Shopify-Access-Token": config.accessToken,
    };
    this.rateLimiter = new TokenBucket(config.rateLimit || DEFAULT_RATE_LIMIT);
    // Allow up to 2 concurrent requests (within rate limit)
    this.concurrencyLimiter = pLimit(2);
  }

  /**
   * Creates a new order
   *
   * @param payload - Order creation payload
   * @returns Created order response
   */
  async createOrder(payload: ShopifyOrderPayload): Promise<ShopifyOrderResponse> {
    return this.concurrencyLimiter(() =>
      this.request<ShopifyOrderResponse>("POST", "/orders.json", payload)
    );
  }

  /**
   * Deletes an order by ID
   *
   * @param orderId - Order ID to delete
   */
  async deleteOrder(orderId: number): Promise<void> {
    return this.concurrencyLimiter(() =>
      this.request<void>("DELETE", `/orders/${orderId}.json`)
    );
  }

  /**
   * Lists orders with optional filters
   *
   * @param params - Query parameters
   * @returns List of orders
   */
  async listOrders(params?: {
    status?: string;
    tags?: string;
    limit?: number;
    since_id?: number;
    fields?: string;
  }): Promise<ShopifyOrdersListResponse> {
    const query = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) {
          query.set(key, String(value));
        }
      });
    }
    const queryString = query.toString();
    const path = `/orders.json${queryString ? `?${queryString}` : ""}`;

    return this.concurrencyLimiter(() =>
      this.request<ShopifyOrdersListResponse>("GET", path)
    );
  }

  /**
   * Gets count of orders with optional filters
   *
   * @param params - Query parameters
   * @returns Order count
   */
  async countOrders(params?: {
    status?: string;
    tags?: string;
  }): Promise<number> {
    const query = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) {
          query.set(key, String(value));
        }
      });
    }
    const queryString = query.toString();
    const path = `/orders/count.json${queryString ? `?${queryString}` : ""}`;

    const response = await this.concurrencyLimiter(() =>
      this.request<ShopifyOrderCountResponse>("GET", path)
    );
    return response.count;
  }

  /**
   * Makes an authenticated request to Shopify API
   *
   * @param method - HTTP method
   * @param path - API path
   * @param body - Optional request body
   * @returns Promise resolving to parsed JSON response
   */
  private async request<T>(
    method: string,
    path: string,
    body?: unknown
  ): Promise<T> {
    // Acquire rate limit token before making request
    await this.rateLimiter.acquire();

    const url = `${this.baseUrl}${path}`;
    const options: RequestInit = {
      method,
      headers: this.headers,
      body: body ? JSON.stringify(body) : undefined,
    };

    // Execute with retry logic
    const response = await this.fetchWithRetry(url, options);

    // Handle DELETE with no content
    if (method === "DELETE" && response.status === 200) {
      return undefined as T;
    }

    // Handle error responses
    if (!response.ok) {
      const errorBody: ShopifyErrorResponse = await response.json();
      throw new ShopifyApiError(response.status, errorBody.errors);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Fetches with retry logic for transient failures
   *
   * Retry behavior:
   * - 429 rate limit: Retry with backoff (honors Retry-After header)
   * - 5xx errors: Retry with exponential backoff
   * - Network errors: Retry with exponential backoff
   * - 4xx errors (except 429): Fail immediately
   * - 2xx/3xx: Return immediately
   *
   * @param url - Full URL to fetch
   * @param options - Fetch options
   * @returns Promise resolving to Response
   */
  private async fetchWithRetry(url: string, options: RequestInit): Promise<Response> {
    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const response = await fetch(url, options);

        // 429 rate limit - honor Retry-After header
        if (response.status === 429) {
          if (attempt < MAX_RETRIES) {
            const retryAfter = response.headers.get("Retry-After");
            const waitMs = retryAfter
              ? parseInt(retryAfter, 10) * 1000
              : RETRY_DELAYS_MS[attempt];
            await this.sleep(waitMs);
            continue;
          }
          return response;
        }

        // 4xx client errors (except 429) - fail immediately
        if (response.status >= 400 && response.status < 500) {
          return response;
        }

        // 5xx server errors - retry with backoff
        if (response.status >= 500) {
          if (attempt < MAX_RETRIES) {
            await this.sleep(RETRY_DELAYS_MS[attempt]);
            continue;
          }
          return response;
        }

        // 2xx/3xx success - return immediately
        return response;
      } catch (error) {
        // Network error - retry with backoff
        lastError = error instanceof Error ? error : new Error(String(error));

        if (attempt < MAX_RETRIES) {
          await this.sleep(RETRY_DELAYS_MS[attempt]);
          continue;
        }
      }
    }

    throw new ShopifyNetworkError(
      `Network request failed after ${MAX_RETRIES} retries`,
      lastError
    );
  }

  /**
   * Sleeps for the specified duration
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/**
 * Creates a ShopifyClient from environment variables
 *
 * Required env vars:
 * - SHOPIFY_STORE_DOMAIN: Store domain (e.g., my-store.myshopify.com)
 * - SHOPIFY_ACCESS_TOKEN: Admin API access token
 *
 * Optional env vars:
 * - SHOPIFY_API_VERSION: API version (default: 2024-01)
 * - SHOPIFY_RATE_LIMIT: Requests per second (default: 2)
 */
export function createShopifyClientFromEnv(): ShopifyClient {
  const storeDomain = process.env.SHOPIFY_STORE_DOMAIN;
  const accessToken = process.env.SHOPIFY_ACCESS_TOKEN;

  if (!storeDomain) {
    throw new Error("SHOPIFY_STORE_DOMAIN environment variable is required");
  }
  if (!accessToken) {
    throw new Error("SHOPIFY_ACCESS_TOKEN environment variable is required");
  }

  return new ShopifyClient({
    storeDomain,
    accessToken,
    apiVersion: process.env.SHOPIFY_API_VERSION || "2024-01",
    rateLimit: parseInt(process.env.SHOPIFY_RATE_LIMIT || "2", 10),
  });
}
