/**
 * UPS MCP Error Types
 *
 * Provides typed error classes for authentication, API, and network failures.
 * Per CONTEXT.md Decision 4: Return UPS error codes as-is (no translation at MCP layer).
 */

/**
 * UPS error response structure from API
 */
export interface UpsErrorResponse {
  response?: {
    errors?: Array<{
      code?: string;
      message?: string;
      context?: string;
    }>;
  };
}

/**
 * Error thrown when OAuth authentication fails
 *
 * Use cases:
 * - Token request returns 401/403
 * - Token refresh fails
 * - Invalid credentials
 */
export class UpsAuthError extends Error {
  override readonly name = "UpsAuthError";
  readonly cause?: Error;

  constructor(message: string, cause?: Error) {
    super(message);
    this.cause = cause;
    Object.setPrototypeOf(this, UpsAuthError.prototype);
  }
}

/**
 * Error thrown when UPS API returns an error response
 *
 * Preserves the original UPS error code and message for upstream handling.
 * Per CONTEXT.md Decision 4: Error codes passed through as-is.
 */
export class UpsApiError extends Error {
  override readonly name = "UpsApiError";
  readonly statusCode: number;
  readonly errorCode: string;
  readonly errorMessage: string;
  readonly field?: string;

  constructor(statusCode: number, response: UpsErrorResponse) {
    const firstError = response.response?.errors?.[0];
    const code = firstError?.code ?? "UNKNOWN";
    const msg = firstError?.message ?? "Unknown UPS API error";
    const field = firstError?.context;

    super(`UPS API Error [${code}]: ${msg}`);
    this.statusCode = statusCode;
    this.errorCode = code;
    this.errorMessage = msg;
    this.field = field;
    Object.setPrototypeOf(this, UpsApiError.prototype);
  }
}

/**
 * Error thrown when network request fails
 *
 * Use cases:
 * - DNS resolution failure
 * - Connection timeout
 * - Socket errors
 * - Max retries exceeded
 */
export class UpsNetworkError extends Error {
  override readonly name = "UpsNetworkError";
  readonly cause?: Error;

  constructor(message: string, cause?: Error) {
    super(message);
    this.cause = cause;
    Object.setPrototypeOf(this, UpsNetworkError.prototype);
  }
}
