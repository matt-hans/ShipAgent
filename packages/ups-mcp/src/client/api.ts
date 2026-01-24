/**
 * UPS API Client
 *
 * HTTP client for UPS API with retry logic and authentication.
 * - Integrates with UpsAuthManager for OAuth tokens
 * - Retries on 5xx errors with exponential backoff
 * - Fails immediately on 4xx errors
 * - Includes required UPS transaction headers
 */

import { UpsAuthManager } from "../auth/manager.js";
import { UpsApiError, UpsNetworkError, type UpsErrorResponse } from "./errors.js";

/**
 * Default UPS API base URL for sandbox environment
 */
const UPS_SANDBOX_API_URL = "https://wwwcie.ups.com/api";

/**
 * Exponential backoff delays in milliseconds
 * [1s, 2s, 4s] for up to 3 retries
 */
const RETRY_DELAYS_MS = [1000, 2000, 4000];

/**
 * Maximum number of retry attempts
 */
const MAX_RETRIES = 3;

/**
 * HTTP client for UPS API requests
 *
 * Handles authentication, retry logic, and error handling.
 *
 * Usage:
 * ```typescript
 * const authManager = new UpsAuthManager(clientId, clientSecret);
 * const client = new UpsApiClient(authManager);
 *
 * const response = await client.request<ShipmentResponse>(
 *   'POST',
 *   '/shipments/v2409/ship',
 *   { ShipmentRequest: { ... } }
 * );
 * ```
 */
export class UpsApiClient {
  /**
   * Creates a new UpsApiClient
   *
   * @param authManager - OAuth token manager for authentication
   * @param baseUrl - UPS API base URL (defaults to sandbox)
   */
  constructor(
    private readonly authManager: UpsAuthManager,
    private readonly baseUrl: string = UPS_SANDBOX_API_URL
  ) {}

  /**
   * Makes an authenticated request to UPS API
   *
   * @param method - HTTP method (GET, POST, DELETE, etc.)
   * @param path - API path (e.g., '/shipments/v2409/ship')
   * @param body - Optional request body (will be JSON stringified)
   * @returns Promise resolving to parsed JSON response
   * @throws UpsApiError if API returns an error
   * @throws UpsNetworkError if network fails after retries
   */
  async request<T>(
    method: string,
    path: string,
    body?: unknown
  ): Promise<T> {
    // Get valid OAuth token
    const token = await this.authManager.getToken();

    // Build request with required headers
    const url = `${this.baseUrl}${path}`;
    const options: RequestInit = {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        transId: crypto.randomUUID(),
        transactionSrc: "shipagent",
      },
      body: body ? JSON.stringify(body) : undefined,
    };

    // Execute with retry logic
    const response = await this.fetchWithRetry(url, options);

    // Handle error responses
    if (!response.ok) {
      const errorBody: UpsErrorResponse = await response.json();
      throw new UpsApiError(response.status, errorBody);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Makes a GET request to UPS API
   *
   * @param path - API path
   * @returns Promise resolving to parsed JSON response
   */
  async get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  /**
   * Makes a POST request to UPS API
   *
   * @param path - API path
   * @param body - Request body
   * @returns Promise resolving to parsed JSON response
   */
  async post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  /**
   * Makes a DELETE request to UPS API
   *
   * @param path - API path
   * @returns Promise resolving to parsed JSON response
   */
  async delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }

  /**
   * Fetches with retry logic for transient failures
   *
   * Retry behavior:
   * - 5xx errors: Retry with exponential backoff
   * - Network errors: Retry with exponential backoff
   * - 4xx errors: Fail immediately (client error, won't help to retry)
   * - 2xx/3xx: Return immediately
   *
   * @param url - Full URL to fetch
   * @param options - Fetch options
   * @returns Promise resolving to Response
   * @throws UpsNetworkError if all retries exhausted
   */
  private async fetchWithRetry(
    url: string,
    options: RequestInit
  ): Promise<Response> {
    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const response = await fetch(url, options);

        // 4xx client errors - fail immediately, no retry
        if (response.status >= 400 && response.status < 500) {
          return response;
        }

        // 5xx server errors - retry with backoff
        if (response.status >= 500) {
          if (attempt < MAX_RETRIES) {
            await this.sleep(RETRY_DELAYS_MS[attempt]);
            continue;
          }
          // Max retries reached for 5xx
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

    // All retries exhausted
    throw new UpsNetworkError(
      `Network request failed after ${MAX_RETRIES} retries`,
      lastError
    );
  }

  /**
   * Sleeps for the specified duration
   *
   * @param ms - Milliseconds to sleep
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
