/**
 * Core API types — errors, pagination, and generic response shapes.
 */

/** Standard error response from the backend. */
export interface ErrorResponse {
  error_code: string;
  message: string;
  remediation: string | null;
  details: Record<string, unknown> | null;
}

/** Generic paginated response wrapper. */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

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
