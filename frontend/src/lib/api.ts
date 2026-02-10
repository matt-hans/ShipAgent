/**
 * API client helpers for ShipAgent backend.
 *
 * All functions use fetch with /api/v1 prefix. In development,
 * Vite proxies these requests to the FastAPI backend.
 */

import type {
  CommandSubmitResponse,
  CommandHistoryItem,
  Job,
  JobRow,
  JobListResponse,
  BatchPreview,
  JobProgress,
  ErrorResponse,
} from '@/types/api';

const API_BASE = '/api/v1';

/**
 * Custom error class for API errors.
 */
export class ApiError extends Error {
  statusCode: number;
  errorResponse: ErrorResponse | null;

  constructor(
    statusCode: number,
    errorResponse: ErrorResponse | null,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.errorResponse = errorResponse;
  }
}

/**
 * Parse API response, throwing ApiError for non-2xx status codes.
 */
async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorResponse: ErrorResponse | null = null;
    try {
      errorResponse = await response.json();
    } catch {
      // Response may not be JSON
    }
    throw new ApiError(
      response.status,
      errorResponse,
      errorResponse?.message || `HTTP ${response.status}: ${response.statusText}`
    );
  }
  return response.json();
}

/**
 * Submit a natural language command for processing.
 *
 * @param command - The natural language shipping command.
 * @returns The job ID and initial status.
 */
export async function submitCommand(
  command: string
): Promise<CommandSubmitResponse> {
  const response = await fetch(`${API_BASE}/commands`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ command }),
  });
  return parseResponse<CommandSubmitResponse>(response);
}

/**
 * Get recent command history.
 *
 * @param limit - Maximum number of items to return (default 10).
 * @returns List of recent commands with their status.
 */
export async function getCommandHistory(
  limit = 10
): Promise<CommandHistoryItem[]> {
  const response = await fetch(
    `${API_BASE}/commands/history?limit=${limit}`
  );
  return parseResponse<CommandHistoryItem[]>(response);
}

/**
 * Get full job details by ID.
 *
 * @param jobId - The job UUID.
 * @returns Full job information.
 */
export async function getJob(jobId: string): Promise<Job> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`);
  return parseResponse<Job>(response);
}

/**
 * Get paginated list of jobs.
 *
 * @param params - Query parameters for filtering and pagination.
 * @returns Paginated job list.
 */
export async function getJobs(params: {
  limit?: number;
  offset?: number;
  status?: string;
  name?: string;
} = {}): Promise<JobListResponse> {
  const searchParams = new URLSearchParams();
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));
  if (params.status) searchParams.set('status', params.status);
  if (params.name) searchParams.set('name', params.name);

  const queryString = searchParams.toString();
  const url = queryString
    ? `${API_BASE}/jobs?${queryString}`
    : `${API_BASE}/jobs`;

  const response = await fetch(url);
  return parseResponse<JobListResponse>(response);
}

/**
 * Get all rows for a job.
 *
 * @param jobId - The job UUID.
 * @returns List of job rows.
 */
export async function getJobRows(jobId: string): Promise<JobRow[]> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/rows`);
  return parseResponse<JobRow[]>(response);
}

/**
 * Get batch preview before execution.
 *
 * @param jobId - The job UUID.
 * @returns Batch preview with sample rows and cost estimate.
 */
export async function getJobPreview(jobId: string): Promise<BatchPreview> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/preview`);
  return parseResponse<BatchPreview>(response);
}

/**
 * Wait for job processing to complete and then return preview.
 *
 * Polls the job endpoint until total_rows > 0 or error_code is set,
 * then fetches and returns the preview.
 *
 * @param jobId - The job UUID.
 * @param maxWaitMs - Maximum time to wait in milliseconds (default: 30000).
 * @param pollIntervalMs - Polling interval in milliseconds (default: 1000).
 * @returns Batch preview with sample rows and cost estimate.
 * @throws ApiError if job processing fails or times out.
 */
export async function waitForPreview(
  jobId: string,
  maxWaitMs = 30000,
  pollIntervalMs = 1000
): Promise<BatchPreview> {
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    const job = await getJob(jobId);

    // Check if processing completed with error
    if (job.error_code) {
      throw new ApiError(
        400,
        {
          error_code: job.error_code,
          message: job.error_message || 'Command processing failed',
          remediation: null,
          details: null,
        },
        job.error_message || 'Command processing failed'
      );
    }

    // Check if rows are ready
    if (job.total_rows > 0) {
      return getJobPreview(jobId);
    }

    // Wait before next poll
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  // Timeout - processing took too long
  throw new ApiError(
    408,
    {
      error_code: 'E-4005',
      message: 'Command processing timed out. Please try again.',
      remediation: null,
      details: null,
    },
    'Command processing timed out. Please try again.'
  );
}

/**
 * Response from confirm endpoint.
 */
export interface ConfirmResponse {
  status: string;
  message: string;
}

/**
 * Confirm a job for execution.
 *
 * @param jobId - The job UUID.
 * @returns Confirmation status and message.
 */
export async function confirmJob(jobId: string): Promise<ConfirmResponse> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/confirm`, {
    method: 'POST',
  });
  return parseResponse<ConfirmResponse>(response);
}

/**
 * Cancel a job.
 *
 * @param jobId - The job UUID.
 */
export async function cancelJob(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ status: 'cancelled' }),
  });
  if (!response.ok) {
    await parseResponse(response); // Will throw ApiError
  }
}

/**
 * Get current job progress (non-SSE fallback).
 *
 * @param jobId - The job UUID.
 * @returns Current progress state.
 */
export async function getJobProgress(jobId: string): Promise<JobProgress> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/progress`);
  return parseResponse<JobProgress>(response);
}

/**
 * Download a single label.
 *
 * @param trackingNumber - The UPS tracking number.
 * @returns Blob containing the PDF label.
 */
export async function downloadLabel(trackingNumber: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/labels/${trackingNumber}`);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      null,
      `Failed to download label: ${response.statusText}`
    );
  }
  return response.blob();
}

/**
 * Download all labels for a job as a ZIP file.
 *
 * @param jobId - The job UUID.
 * @returns Blob containing the ZIP archive.
 */
export async function downloadLabelsZip(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/labels/zip`);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      null,
      `Failed to download labels: ${response.statusText}`
    );
  }
  return response.blob();
}

/**
 * Get the URL for the SSE progress stream.
 *
 * @param jobId - The job UUID.
 * @returns The full URL for EventSource connection.
 */
export function getProgressStreamUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/progress/stream`;
}

/**
 * Get the URL for the merged labels PDF.
 *
 * @param jobId - The job UUID.
 * @returns The full URL for the merged PDF endpoint.
 */
export function getMergedLabelsUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/labels/merged`;
}

/**
 * Delete a job.
 *
 * @param jobId - The job UUID.
 */
export async function deleteJob(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    await parseResponse(response); // Will throw ApiError
  }
}

// === External Platform API ===

import type {
  ListConnectionsResponse,
  PlatformType,
  ConnectPlatformResponse,
  ListOrdersResponse,
  GetOrderResponse,
  TrackingUpdateRequest,
  TrackingUpdateResponse,
  OrderFilters,
  ShopifyEnvStatus,
} from '@/types/api';

/**
 * List all configured platform connections.
 *
 * @returns Connection status for all platforms.
 */
export async function listConnections(): Promise<ListConnectionsResponse> {
  const response = await fetch(`${API_BASE}/platforms/connections`);
  return parseResponse<ListConnectionsResponse>(response);
}

/**
 * Connect to an external platform.
 *
 * @param platform - Platform identifier.
 * @param credentials - Platform-specific credentials.
 * @param storeUrl - Store/instance URL (required for most platforms).
 * @returns Connection result.
 */
export async function connectPlatform(
  platform: PlatformType,
  credentials: Record<string, unknown>,
  storeUrl?: string
): Promise<ConnectPlatformResponse> {
  const response = await fetch(`${API_BASE}/platforms/${platform}/connect`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      credentials,
      store_url: storeUrl,
    }),
  });
  return parseResponse<ConnectPlatformResponse>(response);
}

/**
 * Disconnect from an external platform.
 *
 * @param platform - Platform identifier.
 */
export async function disconnectPlatform(
  platform: PlatformType
): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/platforms/${platform}/disconnect`, {
    method: 'POST',
  });
  return parseResponse<{ success: boolean }>(response);
}

/**
 * Test connection to a platform.
 *
 * @param platform - Platform identifier.
 * @returns Connection health status.
 */
export async function testConnection(
  platform: PlatformType
): Promise<{ success: boolean; status: string }> {
  const response = await fetch(`${API_BASE}/platforms/${platform}/test`);
  return parseResponse<{ success: boolean; status: string }>(response);
}

/**
 * List orders from a connected platform.
 *
 * @param platform - Platform identifier.
 * @param filters - Optional filters.
 * @returns List of orders.
 */
export async function listPlatformOrders(
  platform: PlatformType,
  filters?: OrderFilters
): Promise<ListOrdersResponse> {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.date_from) params.set('date_from', filters.date_from);
  if (filters?.date_to) params.set('date_to', filters.date_to);
  if (filters?.limit) params.set('limit', String(filters.limit));
  if (filters?.offset) params.set('offset', String(filters.offset));

  const queryString = params.toString();
  const url = queryString
    ? `${API_BASE}/platforms/${platform}/orders?${queryString}`
    : `${API_BASE}/platforms/${platform}/orders`;

  const response = await fetch(url);
  return parseResponse<ListOrdersResponse>(response);
}

/**
 * Get a single order from a connected platform.
 *
 * @param platform - Platform identifier.
 * @param orderId - Platform-specific order ID.
 * @returns Order details.
 */
export async function getPlatformOrder(
  platform: PlatformType,
  orderId: string
): Promise<GetOrderResponse> {
  const response = await fetch(
    `${API_BASE}/platforms/${platform}/orders/${encodeURIComponent(orderId)}`
  );
  return parseResponse<GetOrderResponse>(response);
}

/**
 * Update tracking information on a platform order.
 *
 * @param request - Tracking update details.
 * @returns Update result.
 */
export async function updatePlatformTracking(
  request: TrackingUpdateRequest
): Promise<TrackingUpdateResponse> {
  const response = await fetch(
    `${API_BASE}/platforms/${request.platform}/orders/${encodeURIComponent(request.order_id)}/tracking`,
    {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        tracking_number: request.tracking_number,
        carrier: request.carrier || 'UPS',
      }),
    }
  );
  return parseResponse<TrackingUpdateResponse>(response);
}

/**
 * Check Shopify credentials from environment variables.
 *
 * Reads SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN from server environment,
 * validates them against Shopify API, and auto-connects if valid.
 *
 * @returns Status indicating whether credentials are configured and valid.
 */
export async function getShopifyEnvStatus(): Promise<ShopifyEnvStatus> {
  const response = await fetch(`${API_BASE}/platforms/shopify/env-status`);
  return parseResponse<ShopifyEnvStatus>(response);
}
