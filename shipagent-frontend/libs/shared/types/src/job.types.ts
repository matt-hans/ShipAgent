/**
 * Job and batch execution types.
 */

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

/** Monetary entry in a charge breakdown (e.g., transportation, duties). */
export interface ChargeBreakdownEntry {
  monetaryValue: string;
  currencyCode: string;
}

/** Itemized charge breakdown for international shipments. */
export interface ChargeBreakdown {
  version: string;
  transportationCharges?: ChargeBreakdownEntry;
  serviceOptionsCharges?: ChargeBreakdownEntry;
  dutiesAndTaxes?: ChargeBreakdownEntry;
  brokerageCharges?: ChargeBreakdownEntry;
}

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

  // International shipping aggregates
  total_duties_taxes_cents?: number | null;
  international_row_count?: number;

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

  // International shipping data
  destination_country?: string | null;
  duties_taxes_cents?: number | null;
  charge_breakdown?: ChargeBreakdown | null;

  error_code: string | null;
  error_message: string | null;
  created_at: string;
  processed_at: string | null;
}

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

  // International shipping data
  destination_country?: string;
  charge_breakdown?: ChargeBreakdown;
}

/** Shipper address info for interactive preview display. */
export interface ShipperInfo {
  name: string;
  phone?: string;
  addressLine1: string;
  addressLine2?: string;
  city: string;
  stateProvinceCode: string;
  postalCode: string;
  countryCode: string;
}

/** Service option discovered from UPS Shop for a route. */
export interface AvailableServiceOption {
  code: string;
  name: string;
  description?: string;
  estimated_cost_cents: number;
  total_charges: {
    monetary_value: string;
    currency_code: string;
  };
  delivery_days?: string | null;
  selected?: boolean;
}

/** Batch preview before execution. */
export interface BatchPreview {
  job_id: string;
  total_rows: number;
  preview_rows: PreviewRow[];
  additional_rows: number;
  total_estimated_cost_cents: number;
  rows_with_warnings: number;
  // International shipping aggregates
  total_duties_taxes_cents?: number;
  international_row_count?: number;
  // Interactive shipment metadata (present when interactive=true)
  interactive?: boolean;
  shipper?: ShipperInfo;
  ship_to?: {
    name: string;
    attention_name?: string;
    address1: string;
    address2?: string;
    city: string;
    state: string;
    postal_code: string;
    country: string;
    phone?: string;
  };
  account_number?: string;
  service_name?: string;
  service_code?: string;
  available_services?: AvailableServiceOption[];
  service_selection_notice?: string;
  weight_lbs?: number;
  packaging_type?: string;
  resolved_payload?: Record<string, unknown>;
  // Filter transparency metadata (batch mode)
  filter_explanation?: string;
  compiled_filter?: string;
  filter_audit?: {
    spec_hash: string;
    compiled_hash: string;
    schema_signature: string;
    dict_version: string;
    source_fingerprint?: string;
    compiler_version?: string;
    mapping_version?: string;
    normalizer_version?: string;
    mapping_hash?: string;
  };
}

/** Incremental preview update streamed before preview_ready. */
export interface PreviewPartialPayload {
  job_id: string;
  preview_rows: PreviewRow[];
  rows_rated: number;
  total_rows: number;
  is_final: boolean;
}

/** Current job progress (polling endpoint). */
export interface JobProgress {
  job_id: string;
  status: JobStatus;
  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  total_cost_cents: number | null;
  total_duties_taxes_cents?: number | null;
  international_row_count?: number;
}

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
    duties_taxes_cents?: number;
    international_row_count?: number;
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
    duties_taxes_cents?: number;
    international_row_count?: number;
  };
}

/** SSE keepalive ping event. */
export interface PingEvent {
  event: 'ping';
  data: '';
}

/** Union of all SSE progress event types. */
export type ProgressEvent =
  | BatchStartedEvent
  | RowStartedEvent
  | RowCompletedEvent
  | RowFailedEvent
  | BatchCompletedEvent
  | BatchFailedEvent
  | PingEvent;

/** Response from confirm endpoint. */
export interface ConfirmResponse {
  status: string;
  message: string;
}
