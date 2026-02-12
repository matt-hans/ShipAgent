/**
 * TypeScript types for ShipAgent API.
 *
 * These types mirror the backend Pydantic schemas and database models
 * for type-safe API communication.
 */

// === Enums ===

/** Valid job status values. */
export type JobStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

/** Job execution mode values. */
export type JobMode = 'confirm' | 'auto';

/** Row status values. */
export type RowStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'skipped';

// === Data Source Types ===

/** Supported data source types. */
export type DataSourceType = 'csv' | 'excel' | 'database';

/** Status of a data source import. */
export type DataSourceStatus = 'connected' | 'disconnected' | 'error';

/** Column data types from schema discovery. */
export type ColumnDataType =
  | 'INTEGER'
  | 'BIGINT'
  | 'VARCHAR'
  | 'TEXT'
  | 'BOOLEAN'
  | 'DATE'
  | 'TIMESTAMP'
  | 'DECIMAL'
  | 'DOUBLE'
  | 'UNKNOWN';

/** Column metadata from schema discovery. */
export interface ColumnMetadata {
  name: string;
  type: ColumnDataType;
  nullable: boolean;
  warnings: string[];
}

/** CSV import configuration. */
export interface CsvImportConfig {
  filePath: string;
  delimiter?: string;
  header?: boolean;
}

/** Excel import configuration. */
export interface ExcelImportConfig {
  filePath: string;
  sheet?: string;
  header?: boolean;
}

/** Database import configuration. */
export interface DatabaseImportConfig {
  connectionString: string;
  query: string;
  schema?: string;
}

/** Data source connection info. */
export interface DataSourceInfo {
  type: DataSourceType;
  status: DataSourceStatus;
  row_count?: number;
  column_count?: number;
  columns?: ColumnMetadata[];
  connected_at?: string;
  error?: string;
  // Type-specific details
  csv_path?: string;
  excel_path?: string;
  excel_sheet?: string;
  database_query?: string;
}

/** Sheet info for Excel files. */
export interface SheetInfo {
  name: string;
  index: number;
  row_count?: number;
}

/** Table info for databases. */
export interface TableInfo {
  name: string;
  row_count: number;
  requires_filter: boolean;
}

// === Job Types ===

/** Full job response with all details. */
export interface Job {
  id: string;
  name: string;
  description: string | null;
  original_command: string;
  status: JobStatus;
  mode: JobMode;

  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  total_cost_cents: number | null;

  error_code: string | null;
  error_message: string | null;

  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

/** Job summary for list views. */
export interface JobSummary {
  id: string;
  name: string;
  original_command?: string;
  status: JobStatus;
  mode: JobMode;
  total_rows: number;
  successful_rows: number;
  failed_rows: number;
  total_cost_cents: number | null;
  created_at: string;
  completed_at: string | null;
}

/** Paginated job list response. */
export interface JobListResponse {
  jobs: JobSummary[];
  total: number;
  limit: number;
  offset: number;
}

// === Job Row Types ===

/** Individual row within a batch job. */
export interface JobRow {
  id: string;
  row_number: number;
  status: RowStatus;
  row_checksum: string;
  order_data: string | null;
  tracking_number: string | null;
  label_path: string | null;
  cost_cents: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  processed_at: string | null;
}

// === Command Types ===

/** Request schema for submitting a command. */
export interface CommandSubmit {
  command: string;
}

/** Response from command submission. */
export interface CommandSubmitResponse {
  job_id: string;
  status: string;
}

/** Command history entry. */
export interface CommandHistoryItem {
  id: string;
  command: string;
  status: JobStatus;
  created_at: string;
}

// === Preview Types ===

/** Full order data for expanded shipment view. */
export interface OrderData {
  order_id: string;
  order_number?: string | null;
  customer_name: string;
  customer_email?: string | null;
  ship_to_name: string;
  ship_to_company?: string | null;
  ship_to_address1: string;
  ship_to_address2?: string | null;
  ship_to_city: string;
  ship_to_state: string;
  ship_to_postal_code: string;
  ship_to_country: string;
  ship_to_phone?: string | null;
  service_code: string;
}

/** Single row in preview display. */
export interface PreviewRow {
  row_number: number;
  recipient_name: string;
  city_state: string;
  service: string;
  estimated_cost_cents: number;
  warnings: string[];
  order_data?: OrderData | null;
}

/** Batch preview before execution. */
export interface BatchPreview {
  job_id: string;
  total_rows: number;
  preview_rows: PreviewRow[];
  additional_rows: number;
  total_estimated_cost_cents: number;
  rows_with_warnings: number;
}

// === Progress Types ===

/** Current job progress (polling endpoint). */
export interface JobProgress {
  job_id: string;
  status: JobStatus;
  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  total_cost_cents: number | null;
}

// === SSE Event Types ===

/** SSE event when batch starts. */
export interface BatchStartedEvent {
  event: 'batch_started';
  data: {
    job_id: string;
    total_rows: number;
  };
}

/** SSE event when a row starts processing. */
export interface RowStartedEvent {
  event: 'row_started';
  data: {
    job_id: string;
    row_number: number;
  };
}

/** SSE event when a row completes successfully. */
export interface RowCompletedEvent {
  event: 'row_completed';
  data: {
    job_id: string;
    row_number: number;
    tracking_number: string;
    cost_cents: number;
  };
}

/** SSE event when a row fails. */
export interface RowFailedEvent {
  event: 'row_failed';
  data: {
    job_id: string;
    row_number: number;
    error_code: string;
    error_message: string;
  };
}

/** SSE event when batch completes successfully. */
export interface BatchCompletedEvent {
  event: 'batch_completed';
  data: {
    job_id: string;
    total_rows: number;
    successful: number;
    total_cost_cents: number;
  };
}

/** SSE event when batch fails. */
export interface BatchFailedEvent {
  event: 'batch_failed';
  data: {
    job_id: string;
    error_code: string;
    error_message: string;
    processed: number;
  };
}

/** SSE keepalive ping event. */
export interface PingEvent {
  event: 'ping';
  data: '';
}

/** Union of all SSE event types. */
export type ProgressEvent =
  | BatchStartedEvent
  | RowStartedEvent
  | RowCompletedEvent
  | RowFailedEvent
  | BatchCompletedEvent
  | BatchFailedEvent
  | PingEvent;

// === Error Types ===

/** Standard error response. */
export interface ErrorResponse {
  error_code: string;
  message: string;
  remediation: string | null;
  details: Record<string, unknown> | null;
}

// === Audit Log Types ===

/** Audit log entry. */
export interface AuditLogEntry {
  id: string;
  job_id: string;
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  event_type: 'state_change' | 'api_call' | 'row_event' | 'error';
  message: string;
  details: Record<string, unknown> | null;
  row_number: number | null;
}

// === External Platform Types ===

/** Supported external platform identifiers. */
export type PlatformType = 'shopify' | 'woocommerce' | 'sap' | 'oracle';

/** Platform connection status values. */
export type ConnectionStatus = 'connected' | 'disconnected' | 'error' | 'authenticating';

/** Platform connection state. */
export interface PlatformConnection {
  platform: PlatformType;
  store_url: string | null;
  status: ConnectionStatus;
  last_connected: string | null;
  error_message: string | null;
}

/** List connections response. */
export interface ListConnectionsResponse {
  connections: PlatformConnection[];
  count: number;
}

/** Connect platform request - Shopify. */
export interface ShopifyCredentials {
  access_token: string;
}

/** Connect platform request - WooCommerce. */
export interface WooCommerceCredentials {
  consumer_key: string;
  consumer_secret: string;
}

/** Connect platform request - SAP. */
export interface SAPCredentials {
  base_url: string;
  username: string;
  password: string;
  client: string;
}

/** Connect platform request - Oracle (individual params). */
export interface OracleCredentialsParams {
  host: string;
  port?: number;
  service_name: string;
  user: string;
  password: string;
}

/** Connect platform request - Oracle (connection string). */
export interface OracleCredentialsString {
  connection_string: string;
}

/** Union type for Oracle credentials. */
export type OracleCredentials = OracleCredentialsParams | OracleCredentialsString;

/** All credential types union. */
export type PlatformCredentials =
  | { platform: 'shopify'; credentials: ShopifyCredentials; store_url: string }
  | { platform: 'woocommerce'; credentials: WooCommerceCredentials; store_url: string }
  | { platform: 'sap'; credentials: SAPCredentials; store_url?: string }
  | { platform: 'oracle'; credentials: OracleCredentials; store_url?: string };

/** Connect platform response. */
export interface ConnectPlatformResponse {
  success: boolean;
  platform: PlatformType;
  status: string;
  message?: string;
  error?: string;
}

/** Order filters for fetching from external platforms. */
export interface OrderFilters {
  status?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

/** Line item in an external order. */
export interface ExternalOrderItem {
  id: string;
  name: string;
  quantity: number;
  total: string;
  sku: string;
}

/** Order from external platform (normalized). */
export interface ExternalOrder {
  platform: PlatformType;
  order_id: string;
  order_number: string | null;
  status: string;
  created_at: string;
  customer_name: string;
  customer_email: string | null;
  ship_to_name: string;
  ship_to_company: string | null;
  ship_to_address1: string;
  ship_to_address2: string | null;
  ship_to_city: string;
  ship_to_state: string;
  ship_to_postal_code: string;
  ship_to_country: string;
  ship_to_phone: string | null;
  items: ExternalOrderItem[];
}

/** List orders response. */
export interface ListOrdersResponse {
  success: boolean;
  platform: PlatformType;
  orders: ExternalOrder[];
  count: number;
  total?: number;
  error?: string;
}

/** Get single order response. */
export interface GetOrderResponse {
  success: boolean;
  platform: PlatformType;
  order?: ExternalOrder;
  error?: string;
}

/** Tracking update request. */
export interface TrackingUpdateRequest {
  platform: PlatformType;
  order_id: string;
  tracking_number: string;
  carrier?: string;
}

/** Tracking update response. */
export interface TrackingUpdateResponse {
  success: boolean;
  platform: PlatformType;
  order_id: string;
  tracking_number?: string;
  carrier?: string;
  error?: string;
}

// === Data Source Import/Status API Types ===

/** Request for importing a local data source. */
export interface DataSourceImportRequest {
  type: 'csv' | 'excel' | 'database';
  file_path?: string;
  delimiter?: string;
  sheet?: string;
  connection_string?: string;
  query?: string;
}

/** Response from a data source import operation. */
export interface DataSourceImportResponse {
  status: 'connected' | 'error';
  source_type: string;
  row_count: number;
  columns: { name: string; type: string; nullable: boolean }[];
  error?: string;
}

/** Status of the currently connected data source. */
export interface DataSourceStatusResponse {
  connected: boolean;
  source_type?: string;
  file_path?: string;
  row_count?: number;
  columns?: { name: string; type: string; nullable: boolean }[];
}

// === Saved Data Source Types ===

/** A previously connected data source persisted for reconnection. */
export interface SavedDataSource {
  id: string;
  name: string;
  source_type: 'csv' | 'excel' | 'database';
  file_path: string | null;
  sheet_name: string | null;
  db_host: string | null;
  db_port: number | null;
  db_name: string | null;
  db_query: string | null;
  row_count: number;
  column_count: number;
  connected_at: string;
  last_used_at: string;
}

/** Response from listing saved data sources. */
export interface SavedDataSourceListResponse {
  sources: SavedDataSource[];
  total: number;
}

/** Request for reconnecting to a saved data source. */
export interface ReconnectRequest {
  source_id: string;
  connection_string?: string;
}

// === Conversation Types ===

/** Agent event types streamed via SSE. */
export type AgentEventType =
  | 'agent_thinking'
  | 'tool_call'
  | 'tool_result'
  | 'agent_message'
  | 'preview_ready'
  | 'confirmation_needed'
  | 'execution_progress'
  | 'completion'
  | 'error'
  | 'done'
  | 'ping';

/** Base agent event from SSE stream. */
export interface AgentEvent {
  event: AgentEventType;
  data: Record<string, unknown>;
}

/** Create conversation response. */
export interface CreateConversationResponse {
  session_id: string;
}

/** Send message response. */
export interface SendMessageResponse {
  status: string;
  session_id: string;
}

/** Shopify environment status response. */
export interface ShopifyEnvStatus {
  /** True if both SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN are set */
  configured: boolean;
  /** True if credentials validated against Shopify API */
  valid: boolean;
  /** Store URL from environment */
  store_url: string | null;
  /** Shop name from Shopify API */
  store_name: string | null;
  /** Error message if validation failed */
  error: string | null;
}
