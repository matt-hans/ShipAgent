/**
 * API client helpers for ShipAgent backend.
 *
 * All functions use fetch with /api/v1 prefix. In development,
 * Vite proxies these requests to the FastAPI backend.
 */

import type {
  Job,
  JobRow,
  JobListResponse,
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
 * @param writeBackEnabled - Whether to write tracking numbers back to the source.
 * @returns Confirmation status and message.
 */
export async function confirmJob(
  jobId: string,
  writeBackEnabled: boolean = true,
  selectedServiceCode?: string,
): Promise<ConfirmResponse> {
  const payload: Record<string, unknown> = {
    write_back_enabled: writeBackEnabled,
  };
  if (selectedServiceCode) {
    payload.selected_service_code = selectedServiceCode;
  }
  const response = await fetch(`${API_BASE}/jobs/${jobId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
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

/**
 * Get the currently connected data source status.
 */
export async function getDataSourceStatus(): Promise<DataSourceStatusResponse> {
  const response = await fetch(`${API_BASE}/data-sources/status`);
  return parseResponse<DataSourceStatusResponse>(response);
}

// === Saved Data Sources API ===

import type {
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
  UploadDocumentResponse,
} from '@/types/api';

/**
 * Create a new conversation session.
 *
 * @param options - Optional configuration for the session.
 * @returns The new session ID and configuration.
 */
export async function createConversation(
  options?: { interactive_shipping?: boolean },
): Promise<CreateConversationResponse> {
  const response = await fetch(`${API_BASE}/conversations/`, {
    method: 'POST',
    headers: options ? { 'Content-Type': 'application/json' } : undefined,
    body: options ? JSON.stringify(options) : undefined,
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
 * Upload a customs/trade document for paperless processing.
 *
 * Server-side base64 encoding — binary file never enters LLM context.
 *
 * @param sessionId - Conversation session ID.
 * @param file - The file selected via file picker.
 * @param documentType - UPS document type code (e.g. '002').
 * @param notes - Optional notes for the agent.
 * @returns Upload result with file metadata.
 */
export async function uploadDocument(
  sessionId: string,
  file: File,
  documentType: string,
  notes?: string,
): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('document_type', documentType);
  if (notes) formData.append('notes', notes);

  const response = await fetch(
    `${API_BASE}/conversations/${sessionId}/upload-document`,
    { method: 'POST', body: formData },
  );
  return parseResponse<UploadDocumentResponse>(response);
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

// === Chat Session Persistence API ===

import type { ChatSessionSummary, SessionDetail } from '@/types/api';

/**
 * List conversation sessions for the sidebar.
 *
 * @param activeOnly - If true, exclude soft-deleted sessions.
 * @returns List of session summaries ordered by recency.
 */
export async function listConversations(
  activeOnly = true,
): Promise<ChatSessionSummary[]> {
  const response = await fetch(
    `${API_BASE}/conversations/?active_only=${activeOnly}`,
  );
  return parseResponse<ChatSessionSummary[]>(response);
}

/**
 * Load a session's message history for resume/display.
 *
 * @param sessionId - Conversation session ID.
 * @param limit - Max messages to return.
 * @param offset - Skip first N messages.
 * @returns Session metadata and ordered messages.
 */
export async function getConversationMessages(
  sessionId: string,
  limit?: number,
  offset = 0,
): Promise<SessionDetail> {
  const params = new URLSearchParams({ offset: String(offset) });
  if (limit !== undefined) params.set('limit', String(limit));
  const response = await fetch(
    `${API_BASE}/conversations/${sessionId}/messages?${params}`,
  );
  return parseResponse<SessionDetail>(response);
}

/**
 * Update a conversation session's title.
 *
 * @param sessionId - Conversation session ID.
 * @param title - New title string.
 */
export async function updateConversationTitle(
  sessionId: string,
  title: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) await parseResponse(response);
}

/**
 * Export a conversation session as JSON file download.
 *
 * @param sessionId - Conversation session ID.
 */
export async function exportConversation(sessionId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/conversations/${sessionId}/export`,
  );
  if (!response.ok) {
    throw new ApiError(response.status, null, `Export failed: HTTP ${response.status}`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="(.+?)"/);
  const filename = match?.[1] || 'conversation-export.json';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Persist a frontend-generated artifact to a conversation session.
 *
 * @param sessionId - Conversation session ID.
 * @param content - Optional text content.
 * @param metadata - Artifact metadata (action, payload, etc.).
 */
export async function saveArtifactMessage(
  sessionId: string,
  content: string,
  metadata: Record<string, unknown>,
): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${sessionId}/artifacts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, metadata }),
  });
  if (!response.ok) {
    await parseResponse(response);
  }
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

// === Contact Book API ===

import type {
  Contact,
  ContactCreate,
  ContactUpdate,
  ContactListResponse,
} from '@/types/api';

/**
 * List contacts with optional search and filters.
 *
 * @param params - Query parameters for filtering and pagination.
 * @returns Paginated contact list.
 */
export async function listContacts(params: {
  search?: string;
  tag?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ContactListResponse> {
  const searchParams = new URLSearchParams();
  if (params.search) searchParams.set('search', params.search);
  if (params.tag) searchParams.set('tag', params.tag);
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));

  const queryString = searchParams.toString();
  const url = queryString
    ? `${API_BASE}/contacts?${queryString}`
    : `${API_BASE}/contacts`;

  const response = await fetch(url);
  return parseResponse<ContactListResponse>(response);
}

/**
 * Get a contact by handle.
 *
 * @param handle - The contact handle (without @ prefix).
 * @returns Contact details.
 */
export async function getContactByHandle(handle: string): Promise<Contact> {
  const response = await fetch(`${API_BASE}/contacts/by-handle/${handle}`);
  return parseResponse<Contact>(response);
}

/**
 * Create a new contact.
 *
 * @param data - Contact creation payload.
 * @returns Created contact.
 */
export async function createContact(data: ContactCreate): Promise<Contact> {
  const response = await fetch(`${API_BASE}/contacts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return parseResponse<Contact>(response);
}

/**
 * Update an existing contact.
 *
 * @param contactId - The contact UUID.
 * @param data - Contact update payload.
 * @returns Updated contact.
 */
export async function updateContact(
  contactId: string,
  data: ContactUpdate
): Promise<Contact> {
  const response = await fetch(`${API_BASE}/contacts/${contactId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return parseResponse<Contact>(response);
}

/**
 * Delete a contact.
 *
 * @param contactId - The contact UUID.
 */
export async function deleteContact(contactId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/contacts/${contactId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    await parseResponse(response);
  }
}

// === Custom Commands API ===

import type {
  CustomCommand,
  CommandCreate,
  CommandUpdate,
  CommandListResponse,
} from '@/types/api';

/**
 * List custom commands.
 *
 * @param params - Query parameters for pagination.
 * @returns Paginated command list.
 */
export async function listCommands(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<CommandListResponse> {
  const searchParams = new URLSearchParams();
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));

  const queryString = searchParams.toString();
  const url = queryString
    ? `${API_BASE}/commands?${queryString}`
    : `${API_BASE}/commands`;

  const response = await fetch(url);
  return parseResponse<CommandListResponse>(response);
}

/**
 * Create a new custom command.
 *
 * @param data - Command creation payload.
 * @returns Created command.
 */
export async function createCommand(data: CommandCreate): Promise<CustomCommand> {
  const response = await fetch(`${API_BASE}/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return parseResponse<CustomCommand>(response);
}

/**
 * Update an existing command.
 *
 * @param commandId - The command UUID.
 * @param data - Command update payload.
 * @returns Updated command.
 */
export async function updateCommand(
  commandId: string,
  data: CommandUpdate
): Promise<CustomCommand> {
  const response = await fetch(`${API_BASE}/commands/${commandId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return parseResponse<CustomCommand>(response);
}

/**
 * Delete a command.
 *
 * @param commandId - The command UUID.
 */
export async function deleteCommand(commandId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/commands/${commandId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    await parseResponse(response);
  }
}
