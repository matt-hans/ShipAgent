/**
 * Local API response models used only within the shared-api library.
 * These complement the types in @shipagent/shared-types.
 */

/**
 * Custom error class for typed API errors.
 * Thrown by ApiService when a request returns a non-2xx status.
 */
export class ApiError extends Error {
  /** HTTP status code. */
  readonly statusCode: number;
  /** Parsed error body from the backend, or null if parsing failed. */
  readonly errorResponse: ApiErrorBody | null;

  constructor(
    statusCode: number,
    errorResponse: ApiErrorBody | null,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.errorResponse = errorResponse;
  }
}

/** Shape of the backend error body. */
export interface ApiErrorBody {
  error_code?: string;
  message?: string;
  remediation?: string | null;
  details?: Record<string, unknown> | null;
}
