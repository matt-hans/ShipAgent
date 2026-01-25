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

/** Single row in preview display. */
export interface PreviewRow {
  row_number: number;
  recipient_name: string;
  city_state: string;
  service: string;
  estimated_cost_cents: number;
  warnings: string[];
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
