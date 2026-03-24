/**
 * ApiService
 *
 * Central Angular HttpClient-based API service for ShipAgent.
 * Mirrors all endpoints from the React frontend/src/lib/api.ts.
 * Organized by domain group matching the backend route structure.
 *
 * All methods return Observable<T>. SSE streams are NOT handled here —
 * use SseService for real-time event consumption.
 */

import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_BASE_URL } from './api-url.token';

// Types
import type {
  // Jobs
  Job,
  JobRow,
  JobListResponse,
  JobProgress,
  ConfirmResponse,
  // Data Sources
  DataSourceImportRequest,
  DataSourceImportResponse,
  DataSourceStatusResponse,
  SavedDataSourceListResponse,
  // Conversations
  CreateConversationResponse,
  SendMessageResponse,
  ChatSessionSummary,
  SessionDetail,
  UploadDocumentResponse,
  // Platforms
  ListConnectionsResponse,
  PlatformType,
  ConnectPlatformResponse,
  ListOrdersResponse,
  OrderFilters,
  ShopifyEnvStatus,
  AmazonEnvStatus,
  // Connections (provider)
  ProviderConnectionInfo,
  SaveProviderRequest,
  ValidateConnectionResult,
  // Settings
  AppSettings,
  CredentialStatus,
  // Contacts
  Contact,
  ContactCreate,
  ContactUpdate,
  ContactListResponse,
  // Commands
  CustomCommand,
  CommandCreate,
  CommandUpdate,
  CommandListResponse,
} from '@shipagent/shared-types';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly apiBaseUrl = inject(API_BASE_URL);

  /** Resolve the current base URL from the signal. */
  private get baseUrl(): string {
    return this.apiBaseUrl();
  }

  // ===========================================================================
  // CONVERSATIONS
  // ===========================================================================

  /**
   * Create a new conversation session.
   */
  createConversation(
    options?: { interactive_shipping?: boolean },
  ): Observable<CreateConversationResponse> {
    return this.http.post<CreateConversationResponse>(
      `${this.baseUrl}/conversations/`,
      options ?? {},
    );
  }

  /**
   * Send a user message to the conversation agent.
   */
  sendMessage(
    sessionId: string,
    content: string,
  ): Observable<SendMessageResponse> {
    return this.http.post<SendMessageResponse>(
      `${this.baseUrl}/conversations/${sessionId}/messages`,
      { content },
    );
  }

  /**
   * List conversation sessions for the sidebar.
   */
  getConversations(activeOnly = true): Observable<ChatSessionSummary[]> {
    const params = new HttpParams().set('active_only', String(activeOnly));
    return this.http.get<ChatSessionSummary[]>(
      `${this.baseUrl}/conversations/`,
      { params },
    );
  }

  /**
   * Load a session's message history for resume/display.
   */
  getConversationMessages(
    sessionId: string,
    limit?: number,
    offset = 0,
  ): Observable<SessionDetail> {
    let params = new HttpParams().set('offset', String(offset));
    if (limit !== undefined) {
      params = params.set('limit', String(limit));
    }
    return this.http.get<SessionDetail>(
      `${this.baseUrl}/conversations/${sessionId}/messages`,
      { params },
    );
  }

  /**
   * Delete (soft-delete) a single conversation session.
   */
  deleteConversation(sessionId: string): Observable<void> {
    return this.http.delete<void>(
      `${this.baseUrl}/conversations/${sessionId}`,
    );
  }

  /**
   * Soft-delete all active conversation sessions.
   */
  deleteAllConversations(): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(
      `${this.baseUrl}/conversations/bulk-delete`,
      {},
    );
  }

  /**
   * Update a conversation session's title.
   */
  renameConversation(
    sessionId: string,
    title: string,
  ): Observable<void> {
    return this.http.patch<void>(
      `${this.baseUrl}/conversations/${sessionId}`,
      { title },
    );
  }

  /**
   * Export a conversation session as JSON.
   * Returns a Blob for download.
   */
  exportConversation(sessionId: string): Observable<Blob> {
    return this.http.get(
      `${this.baseUrl}/conversations/${sessionId}/export`,
      { responseType: 'blob' },
    );
  }

  /**
   * Persist a frontend-generated artifact to a conversation session.
   */
  saveArtifact(
    sessionId: string,
    content: string,
    metadata: Record<string, unknown>,
  ): Observable<void> {
    return this.http.post<void>(
      `${this.baseUrl}/conversations/${sessionId}/artifacts`,
      { content, metadata },
    );
  }

  /**
   * Get the SSE stream URL for a conversation.
   * Returns a URL string — connect with EventSource directly.
   */
  getStreamUrl(sessionId: string): string {
    return `${this.baseUrl}/conversations/${sessionId}/stream`;
  }

  /**
   * Upload a customs/trade document for paperless processing.
   */
  uploadDocument(
    sessionId: string,
    file: File,
    documentType: string,
    notes?: string,
  ): Observable<UploadDocumentResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);
    if (notes) formData.append('notes', notes);
    return this.http.post<UploadDocumentResponse>(
      `${this.baseUrl}/conversations/${sessionId}/upload-document`,
      formData,
    );
  }

  // ===========================================================================
  // JOBS
  // ===========================================================================

  /**
   * Get paginated list of jobs.
   */
  getJobs(params?: {
    limit?: number;
    offset?: number;
    status?: string;
    name?: string;
  }): Observable<JobListResponse> {
    let httpParams = new HttpParams();
    if (params?.limit) httpParams = httpParams.set('limit', String(params.limit));
    if (params?.offset) httpParams = httpParams.set('offset', String(params.offset));
    if (params?.status) httpParams = httpParams.set('status', params.status);
    if (params?.name) httpParams = httpParams.set('name', params.name);
    return this.http.get<JobListResponse>(`${this.baseUrl}/jobs`, {
      params: httpParams,
    });
  }

  /**
   * Get full job details by ID.
   */
  getJob(jobId: string): Observable<Job> {
    return this.http.get<Job>(`${this.baseUrl}/jobs/${jobId}`);
  }

  /**
   * Get all rows for a job.
   */
  getJobRows(jobId: string): Observable<JobRow[]> {
    return this.http.get<JobRow[]>(`${this.baseUrl}/jobs/${jobId}/rows`);
  }

  /**
   * Confirm a job for execution.
   */
  confirmJob(
    jobId: string,
    writeBackEnabled = true,
    selectedServiceCode?: string,
  ): Observable<ConfirmResponse> {
    const payload: Record<string, unknown> = {
      write_back_enabled: writeBackEnabled,
    };
    if (selectedServiceCode) {
      payload['selected_service_code'] = selectedServiceCode;
    }
    return this.http.post<ConfirmResponse>(
      `${this.baseUrl}/jobs/${jobId}/confirm`,
      payload,
    );
  }

  /**
   * Cancel a job.
   */
  cancelJob(jobId: string): Observable<void> {
    return this.http.patch<void>(`${this.baseUrl}/jobs/${jobId}/status`, {
      status: 'cancelled',
    });
  }

  /**
   * Delete a job.
   */
  deleteJob(jobId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/jobs/${jobId}`);
  }

  /**
   * Mark specific rows as skipped before execution.
   */
  skipFailedRows(jobId: string, rowNumbers: number[]): Observable<void> {
    return this.http.patch<void>(`${this.baseUrl}/jobs/${jobId}/rows/skip`, {
      row_numbers: rowNumbers,
    });
  }

  /**
   * Get current job progress (non-SSE polling fallback).
   */
  getJobProgress(jobId: string): Observable<JobProgress> {
    return this.http.get<JobProgress>(
      `${this.baseUrl}/jobs/${jobId}/progress`,
    );
  }

  /**
   * Get the SSE progress stream URL for a job.
   * Returns a URL string — connect with EventSource directly.
   */
  getJobProgressUrl(jobId: string): string {
    return `${this.baseUrl}/jobs/${jobId}/progress/stream`;
  }

  /**
   * Get the merged labels PDF URL for a job.
   */
  getMergedLabelsUrl(jobId: string): string {
    return `${this.baseUrl}/jobs/${jobId}/labels/merged`;
  }

  /**
   * Get the ZIP labels archive URL for a job.
   */
  getZipLabelsUrl(jobId: string): string {
    return `${this.baseUrl}/jobs/${jobId}/labels/zip`;
  }

  // ===========================================================================
  // DATA SOURCES
  // ===========================================================================

  /**
   * Import a local data source (CSV, Excel, or Database).
   */
  importDataSource(
    config: DataSourceImportRequest,
  ): Observable<DataSourceImportResponse> {
    return this.http.post<DataSourceImportResponse>(
      `${this.baseUrl}/data-sources/import`,
      config,
    );
  }

  /**
   * Upload a CSV or Excel file and import it as the active data source.
   */
  uploadDataSource(file: File): Observable<DataSourceImportResponse> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<DataSourceImportResponse>(
      `${this.baseUrl}/data-sources/upload`,
      formData,
    );
  }

  /**
   * Disconnect the currently connected data source.
   */
  disconnectDataSource(): Observable<void> {
    return this.http.post<void>(
      `${this.baseUrl}/data-sources/disconnect`,
      {},
    );
  }

  /**
   * Get the currently connected data source status.
   */
  getDataSourceStatus(): Observable<DataSourceStatusResponse> {
    return this.http.get<DataSourceStatusResponse>(
      `${this.baseUrl}/data-sources/status`,
    );
  }

  // ===========================================================================
  // SAVED SOURCES
  // ===========================================================================

  /**
   * List all saved data sources, ordered by most recently used.
   */
  getSavedSources(sourceType?: string): Observable<SavedDataSourceListResponse> {
    let params = new HttpParams();
    if (sourceType) params = params.set('source_type', sourceType);
    return this.http.get<SavedDataSourceListResponse>(
      `${this.baseUrl}/saved-sources`,
      { params },
    );
  }

  /**
   * Reconnect to a previously saved data source.
   */
  reconnectSavedSource(
    sourceId: string,
    connectionString?: string,
  ): Observable<{ status: string; source_type: string; row_count: number; column_count: number }> {
    const body: Record<string, unknown> = { source_id: sourceId };
    if (connectionString) body['connection_string'] = connectionString;
    return this.http.post<{ status: string; source_type: string; row_count: number; column_count: number }>(
      `${this.baseUrl}/saved-sources/reconnect`,
      body,
    );
  }

  /**
   * Delete a single saved data source.
   */
  deleteSavedSource(sourceId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/saved-sources/${sourceId}`);
  }

  /**
   * Delete multiple saved data sources.
   */
  bulkDeleteSavedSources(
    sourceIds: string[],
  ): Observable<{ status: string; count: number }> {
    return this.http.post<{ status: string; count: number }>(
      `${this.baseUrl}/saved-sources/bulk-delete`,
      { source_ids: sourceIds },
    );
  }

  // ===========================================================================
  // PLATFORMS
  // ===========================================================================

  /**
   * Connect to an external platform.
   */
  connectPlatform(
    platform: PlatformType,
    credentials: Record<string, unknown>,
    storeUrl?: string,
  ): Observable<ConnectPlatformResponse> {
    return this.http.post<ConnectPlatformResponse>(
      `${this.baseUrl}/platforms/${platform}/connect`,
      { credentials, store_url: storeUrl },
    );
  }

  /**
   * Disconnect from an external platform.
   */
  disconnectPlatform(
    platform: PlatformType,
  ): Observable<{ success: boolean }> {
    return this.http.post<{ success: boolean }>(
      `${this.baseUrl}/platforms/${platform}/disconnect`,
      {},
    );
  }

  /**
   * Check Shopify credentials from environment variables.
   */
  getPlatformEnvStatus(
    platform: 'shopify',
  ): Observable<ShopifyEnvStatus>;
  getPlatformEnvStatus(
    platform: 'amazon',
  ): Observable<AmazonEnvStatus>;
  getPlatformEnvStatus(
    platform: string,
  ): Observable<ShopifyEnvStatus | AmazonEnvStatus> {
    return this.http.get<ShopifyEnvStatus | AmazonEnvStatus>(
      `${this.baseUrl}/platforms/${platform}/env-status`,
    );
  }

  /**
   * List orders from a connected platform.
   */
  getPlatformOrders(
    platform: PlatformType,
    filters?: OrderFilters,
  ): Observable<ListOrdersResponse> {
    let params = new HttpParams();
    if (filters?.status) params = params.set('status', filters.status);
    if (filters?.date_from) params = params.set('date_from', filters.date_from);
    if (filters?.date_to) params = params.set('date_to', filters.date_to);
    if (filters?.limit) params = params.set('limit', String(filters.limit));
    if (filters?.offset) params = params.set('offset', String(filters.offset));
    return this.http.get<ListOrdersResponse>(
      `${this.baseUrl}/platforms/${platform}/orders`,
      { params },
    );
  }

  /**
   * List all configured platform connections.
   */
  getPlatformConnections(): Observable<ListConnectionsResponse> {
    return this.http.get<ListConnectionsResponse>(
      `${this.baseUrl}/platforms/connections`,
    );
  }

  /**
   * Activate Shopify as the active data source (connect + fetch + import).
   */
  activateShopify(): Observable<{
    success: boolean;
    row_count: number;
    source_type: string | null;
    columns: Array<Record<string, unknown>>;
    error: string | null;
  }> {
    return this.http.post<{
      success: boolean;
      row_count: number;
      source_type: string | null;
      columns: Array<Record<string, unknown>>;
      error: string | null;
    }>(`${this.baseUrl}/platforms/shopify/activate`, {});
  }

  /**
   * Activate Amazon as the active data source (connect + fetch + import).
   */
  activateAmazon(): Observable<{
    success: boolean;
    row_count: number;
    source_type: string | null;
    columns: Array<Record<string, unknown>>;
    error: string | null;
  }> {
    return this.http.post<{
      success: boolean;
      row_count: number;
      source_type: string | null;
      columns: Array<Record<string, unknown>>;
      error: string | null;
    }>(`${this.baseUrl}/platforms/amazon/activate`, {});
  }

  /**
   * Test connection to a platform.
   */
  testPlatformConnection(
    platform: PlatformType,
  ): Observable<{ success: boolean; status: string }> {
    return this.http.get<{ success: boolean; status: string }>(
      `${this.baseUrl}/platforms/${platform}/test`,
    );
  }

  // ===========================================================================
  // CONNECTIONS (Provider credential management — /connections/ routes)
  // ===========================================================================

  /**
   * List all provider connections (no credentials exposed).
   */
  listProviderConnections(): Observable<ProviderConnectionInfo[]> {
    return this.http.get<ProviderConnectionInfo[]>(
      `${this.baseUrl}/connections/`,
    );
  }

  /**
   * Get a single connection by key.
   */
  getProviderConnection(
    connectionKey: string,
  ): Observable<ProviderConnectionInfo> {
    return this.http.get<ProviderConnectionInfo>(
      `${this.baseUrl}/connections/${encodeURIComponent(connectionKey)}`,
    );
  }

  /**
   * Save or overwrite provider credentials.
   */
  saveProviderCredentials(
    provider: string,
    payload: SaveProviderRequest,
  ): Observable<{ connection_key: string; is_new: boolean }> {
    return this.http.post<{ connection_key: string; is_new: boolean }>(
      `${this.baseUrl}/connections/${encodeURIComponent(provider)}/save`,
      payload,
    );
  }

  /**
   * Delete a connection by key.
   */
  deleteProviderConnection(
    connectionKey: string,
  ): Observable<{ deleted: boolean }> {
    return this.http.delete<{ deleted: boolean }>(
      `${this.baseUrl}/connections/${encodeURIComponent(connectionKey)}`,
    );
  }

  /**
   * Validate saved credentials against the real provider API.
   * Note: returns 422 for invalid creds (not a fatal error).
   */
  validateProviderConnection(
    connectionKey: string,
  ): Observable<ValidateConnectionResult> {
    return this.http.post<ValidateConnectionResult>(
      `${this.baseUrl}/connections/${encodeURIComponent(connectionKey)}/validate`,
      {},
    );
  }

  /**
   * Disconnect a connection (preserves credentials, clears runtime state).
   */
  disconnectProvider(
    connectionKey: string,
  ): Observable<ProviderConnectionInfo> {
    return this.http.post<ProviderConnectionInfo>(
      `${this.baseUrl}/connections/${encodeURIComponent(connectionKey)}/disconnect`,
      {},
    );
  }

  // ===========================================================================
  // SETTINGS
  // ===========================================================================

  /**
   * Get application settings.
   */
  getSettings(): Observable<AppSettings> {
    return this.http.get<AppSettings>(`${this.baseUrl}/settings`);
  }

  /**
   * Update application settings (patch semantics).
   */
  patchSettings(patch: Partial<AppSettings>): Observable<AppSettings> {
    return this.http.patch<AppSettings>(`${this.baseUrl}/settings`, patch);
  }

  /**
   * Store a credential in the secure store (keychain).
   */
  putCredential(key: string, value: string): Observable<void> {
    return this.http.post<void>(`${this.baseUrl}/settings/credentials`, {
      key,
      value,
    });
  }

  /**
   * Get credential status (never returns values, only booleans).
   */
  getCredentialStatus(): Observable<CredentialStatus> {
    return this.http.get<CredentialStatus>(
      `${this.baseUrl}/settings/credentials/status`,
    );
  }

  /**
   * Mark onboarding as completed.
   */
  completeOnboarding(): Observable<void> {
    return this.http.post<void>(
      `${this.baseUrl}/settings/onboarding/complete`,
      {},
    );
  }

  // ===========================================================================
  // CONTACTS
  // ===========================================================================

  /**
   * List contacts with optional search and filters.
   */
  getContacts(params?: {
    search?: string;
    tag?: string;
    limit?: number;
    offset?: number;
  }): Observable<ContactListResponse> {
    let httpParams = new HttpParams();
    if (params?.search) httpParams = httpParams.set('search', params.search);
    if (params?.tag) httpParams = httpParams.set('tag', params.tag);
    if (params?.limit) httpParams = httpParams.set('limit', String(params.limit));
    if (params?.offset) httpParams = httpParams.set('offset', String(params.offset));
    return this.http.get<ContactListResponse>(`${this.baseUrl}/contacts`, {
      params: httpParams,
    });
  }

  /**
   * Get a contact by handle.
   */
  getContactByHandle(handle: string): Observable<Contact> {
    return this.http.get<Contact>(
      `${this.baseUrl}/contacts/by-handle/${handle}`,
    );
  }

  /**
   * Create a new contact.
   */
  createContact(data: ContactCreate): Observable<Contact> {
    return this.http.post<Contact>(`${this.baseUrl}/contacts`, data);
  }

  /**
   * Update an existing contact.
   */
  updateContact(contactId: string, data: ContactUpdate): Observable<Contact> {
    return this.http.patch<Contact>(
      `${this.baseUrl}/contacts/${contactId}`,
      data,
    );
  }

  /**
   * Delete a contact.
   */
  deleteContact(contactId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/contacts/${contactId}`);
  }

  /**
   * Search contacts.
   */
  searchContacts(query: string): Observable<ContactListResponse> {
    return this.getContacts({ search: query });
  }

  // ===========================================================================
  // COMMANDS
  // ===========================================================================

  /**
   * List custom commands.
   */
  getCommands(params?: {
    limit?: number;
    offset?: number;
  }): Observable<CommandListResponse> {
    let httpParams = new HttpParams();
    if (params?.limit) httpParams = httpParams.set('limit', String(params.limit));
    if (params?.offset) httpParams = httpParams.set('offset', String(params.offset));
    return this.http.get<CommandListResponse>(`${this.baseUrl}/commands`, {
      params: httpParams,
    });
  }

  /**
   * Create a new custom command.
   */
  createCommand(data: CommandCreate): Observable<CustomCommand> {
    return this.http.post<CustomCommand>(`${this.baseUrl}/commands`, data);
  }

  /**
   * Update an existing command.
   */
  updateCommand(
    commandId: string,
    data: CommandUpdate,
  ): Observable<CustomCommand> {
    return this.http.patch<CustomCommand>(
      `${this.baseUrl}/commands/${commandId}`,
      data,
    );
  }

  /**
   * Delete a command.
   */
  deleteCommand(commandId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/commands/${commandId}`);
  }
}
