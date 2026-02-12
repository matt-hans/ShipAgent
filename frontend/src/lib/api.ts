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
 * @param options - Optional refinement metadata for clean job naming.
 * @returns The job ID and initial status.
 */
export async function submitCommand(
  command: string,
  options?: { baseCommand?: string; refinements?: string[] }
): Promise<CommandSubmitResponse> {
  const body: Record<string, unknown> = { command };
  if (options?.baseCommand) body.base_command = options.baseCommand;
  if (options?.refinements?.length) body.refinements = options.refinements;

  const response = await fetch(`${API_BASE}/commands`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
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
  const response = await fetch(`${API_BASE}/jobs/${jobId}/status`, {
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

/**
 * Mark specific rows as skipped before execution.
 *
 * @param jobId - The job UUID.
 * @param rowNumbers - Array of row numbers to skip.
 */
export async function skipRows(
  jobId: string,
  rowNumbers: number[]
): Promise<void> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/rows/skip`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ row_numbers: rowNumbers }),
  });
  if (!response.ok) {
    await parseResponse(response); // Will throw ApiError
  }
}

/**
 * Refine a job by chaining a natural language refinement onto the original command.
 *
 * Submits the refined command, waits for preview, then deletes the old job.
 * Returns the new job ID and preview data.
 *
 * @param originalCommand - The base command before any refinements.
 * @param refinementHistory - Previous refinements already applied.
 * @param newRefinement - The new refinement to append.
 * @param previousJobId - The job ID to clean up after successful refinement.
 * @returns New job ID and preview data.
 */
export async function refineJob(
  originalCommand: string,
  refinementHistory: string[],
  newRefinement: string,
  previousJobId: string,
): Promise<{ jobId: string; preview: BatchPreview }> {
  // Build refined command by chaining refinements
  const allRefinements = [...refinementHistory, newRefinement];
  const refinedCommand = allRefinements.reduce(
    (cmd, refinement, i) => `${cmd}${i === 0 ? ', but ' : ', and '}${refinement}`,
    originalCommand
  );

  // Submit refined command with refinement metadata for clean job naming
  const result = await submitCommand(refinedCommand, {
    baseCommand: originalCommand,
    refinements: allRefinements,
  });

  // Wait for new preview
  const preview = await waitForPreview(result.job_id);

  // Clean up old job (best-effort)
  try {
    await deleteJob(previousJobId);
  } catch {
    // Delete may fail if job already processed; non-critical
  }

  return { jobId: result.job_id, preview };
}

// === Local Data Source API ===

import type {
  DataSourceImportRequest,
  DataSourceImportResponse,
  DataSourceStatusResponse,
} from '@/types/api';

/**
 * Import a local data source (CSV, Excel, or Database).
 *
 * @param config - Import configuration with type, file path, and options.
 * @returns Import result with schema, row count, and status.
 */
export async function importDataSource(
  config: DataSourceImportRequest
): Promise<DataSourceImportResponse> {
  const response = await fetch(`${API_BASE}/data-sources/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return parseResponse<DataSourceImportResponse>(response);
}

/**
 * Upload a CSV or Excel file and import it as the active data source.
 *
 * @param file - The file selected via a file picker.
 * @returns Import result with schema, row count, and status.
 */
export async function uploadDataSource(
  file: File
): Promise<DataSourceImportResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${API_BASE}/data-sources/upload`, {
    method: 'POST',
    body: formData,
  });
  return parseResponse<DataSourceImportResponse>(response);
}

/**
 * Get the status of the currently connected data source.
 *
 * @returns Connection status with source type, row count, and schema.
 */
export async function getDataSourceStatus(): Promise<DataSourceStatusResponse> {
  const response = await fetch(`${API_BASE}/data-sources/status`);
  return parseResponse<DataSourceStatusResponse>(response);
}

/**
 * Disconnect the currently connected data source.
 */
export async function disconnectDataSource(): Promise<void> {
  const response = await fetch(`${API_BASE}/data-sources/disconnect`, {
    method: 'POST',
  });
  if (!response.ok) {
    await parseResponse(response); // Will throw ApiError
  }
}

// === Saved Data Sources API ===

import type {
  SavedDataSource,
  SavedDataSourceListResponse,
} from '@/types/api';

/**
 * List all saved data sources, ordered by most recently used.
 *
 * @param sourceType - Optional filter ('csv', 'excel', 'database').
 * @returns List of saved sources.
 */
export async function getSavedDataSources(
  sourceType?: string
): Promise<SavedDataSourceListResponse> {
  const params = new URLSearchParams();
  if (sourceType) params.set('source_type', sourceType);
  const qs = params.toString();
  const url = qs ? `${API_BASE}/saved-sources?${qs}` : `${API_BASE}/saved-sources`;
  const response = await fetch(url);
  return parseResponse<SavedDataSourceListResponse>(response);
}

/**
 * Reconnect to a previously saved data source.
 *
 * @param sourceId - UUID of the saved source.
 * @param connectionString - Required for database sources (credentials not stored).
 * @returns Reconnection result with status, source_type, row_count.
 */
export async function reconnectSavedSource(
  sourceId: string,
  connectionString?: string
): Promise<{ status: string; source_type: string; row_count: number; column_count: number }> {
  const body: Record<string, unknown> = { source_id: sourceId };
  if (connectionString) body.connection_string = connectionString;
  const response = await fetch(`${API_BASE}/saved-sources/reconnect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parseResponse(response);
}

/**
 * Delete a single saved data source.
 *
 * @param sourceId - UUID of the source to delete.
 */
export async function deleteSavedSource(sourceId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/saved-sources/${sourceId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    await parseResponse(response);
  }
}

/**
 * Delete multiple saved data sources.
 *
 * @param sourceIds - UUIDs of sources to delete.
 * @returns Number of records deleted.
 */
export async function bulkDeleteSavedSources(
  sourceIds: string[]
): Promise<{ status: string; count: number }> {
  const response = await fetch(`${API_BASE}/saved-sources/bulk-delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_ids: sourceIds }),
  });
  return parseResponse(response);
}

// === External Platform API ===

// === Conversation API ===

import type {
  CreateConversationResponse,
  SendMessageResponse,
} from '@/types/api';

/**
 * Create a new conversation session.
 *
 * @returns The new session ID.
 */
export async function createConversation(): Promise<CreateConversationResponse> {
  const response = await fetch(`${API_BASE}/conversations/`, {
    method: 'POST',
  });
  return parseResponse<CreateConversationResponse>(response);
}

/**
 * Send a user message to the conversation agent.
 *
 * @param sessionId - Conversation session ID.
 * @param content - User message text.
 * @returns Accepted response with session ID.
 */
export async function sendConversationMessage(
  sessionId: string,
  content: string
): Promise<SendMessageResponse> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  return parseResponse<SendMessageResponse>(response);
}

/**
 * Get the SSE stream URL for a conversation.
 *
 * @param sessionId - Conversation session ID.
 * @returns Full URL for EventSource connection.
 */
export function getConversationStreamUrl(sessionId: string): string {
  return `${API_BASE}/conversations/${sessionId}/stream`;
}

/**
 * End a conversation session and free resources.
 *
 * @param sessionId - Conversation session ID.
 */
export async function deleteConversation(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    await parseResponse(response);
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
