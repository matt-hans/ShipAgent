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
 * Confirm a job for execution.
 *
 * @param jobId - The job UUID.
 */
export async function confirmJob(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/confirm`, {
    method: 'POST',
  });
  if (!response.ok) {
    await parseResponse(response); // Will throw ApiError
  }
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
