/**
 * Job-related test fixtures with realistic sample data.
 */

import type {
  Job,
  JobSummary,
  JobRow,
  JobListResponse,
  BatchPreview,
  PreviewRow,
  JobProgress,
  ConfirmResponse,
} from '@shipagent/shared-types';

export const jobFixtures = {
  /** A pending job waiting for confirmation. */
  pendingJob: (): Job => ({
    id: 'job-001',
    name: 'Ship California Orders',
    description: null,
    original_command: 'Ship all California orders via UPS Ground',
    status: 'pending',
    mode: 'confirm',
    total_rows: 25,
    processed_rows: 0,
    successful_rows: 0,
    failed_rows: 0,
    total_cost_cents: null,
    error_code: null,
    error_message: null,
    created_at: '2026-03-24T10:00:00Z',
    started_at: null,
    completed_at: null,
    updated_at: '2026-03-24T10:00:00Z',
  }),

  /** A running job in the middle of execution. */
  runningJob: (): Job => ({
    id: 'job-002',
    name: 'Ship Texas Orders',
    description: null,
    original_command: 'Ship all Texas orders via UPS Next Day Air',
    status: 'running',
    mode: 'auto',
    total_rows: 10,
    processed_rows: 6,
    successful_rows: 5,
    failed_rows: 1,
    total_cost_cents: 12500,
    error_code: null,
    error_message: null,
    created_at: '2026-03-24T09:00:00Z',
    started_at: '2026-03-24T09:01:00Z',
    completed_at: null,
    updated_at: '2026-03-24T09:30:00Z',
  }),

  /** A completed job with all rows processed. */
  completedJob: (): Job => ({
    id: 'job-003',
    name: 'Ship New York Orders',
    description: null,
    original_command: 'Ship all New York orders',
    status: 'completed',
    mode: 'confirm',
    total_rows: 15,
    processed_rows: 15,
    successful_rows: 14,
    failed_rows: 1,
    total_cost_cents: 45000,
    error_code: null,
    error_message: null,
    created_at: '2026-03-23T14:00:00Z',
    started_at: '2026-03-23T14:02:00Z',
    completed_at: '2026-03-23T14:10:00Z',
    updated_at: '2026-03-23T14:10:00Z',
  }),

  /** A job summary for list views. */
  jobSummary: (): JobSummary => ({
    id: 'job-001',
    name: 'Ship California Orders',
    status: 'pending',
    mode: 'confirm',
    total_rows: 25,
    successful_rows: 0,
    failed_rows: 0,
    total_cost_cents: null,
    created_at: '2026-03-24T10:00:00Z',
    completed_at: null,
  }),

  /** A paginated job list response. */
  jobListResponse: (): JobListResponse => ({
    jobs: [
      {
        id: 'job-001',
        name: 'Ship California Orders',
        status: 'pending',
        mode: 'confirm',
        total_rows: 25,
        successful_rows: 0,
        failed_rows: 0,
        total_cost_cents: null,
        created_at: '2026-03-24T10:00:00Z',
        completed_at: null,
      },
      {
        id: 'job-003',
        name: 'Ship New York Orders',
        status: 'completed',
        mode: 'confirm',
        total_rows: 15,
        successful_rows: 14,
        failed_rows: 1,
        total_cost_cents: 45000,
        created_at: '2026-03-23T14:00:00Z',
        completed_at: '2026-03-23T14:10:00Z',
      },
    ],
    total: 2,
    limit: 50,
    offset: 0,
  }),

  /** A single job row (completed). */
  jobRow: (): JobRow => ({
    id: 'row-001',
    row_number: 1,
    status: 'completed',
    row_checksum: 'abc123',
    order_data: JSON.stringify({
      order_id: 'ORD-001',
      customer_name: 'Alice Johnson',
      ship_to_name: 'Alice Johnson',
      ship_to_address1: '123 Main St',
      ship_to_city: 'Los Angeles',
      ship_to_state: 'CA',
      ship_to_postal_code: '90001',
      ship_to_country: 'US',
      service_code: '03',
    }),
    tracking_number: '1Z999AA10123456784',
    label_path: '/labels/1Z999AA10123456784.pdf',
    cost_cents: 1250,
    error_code: null,
    error_message: null,
    created_at: '2026-03-23T14:02:00Z',
    processed_at: '2026-03-23T14:05:00Z',
  }),

  /** A batch preview with sample rows. */
  batchPreview: (): BatchPreview => ({
    job_id: 'job-001',
    total_rows: 25,
    preview_rows: [
      {
        row_number: 1,
        recipient_name: 'Alice Johnson',
        city_state: 'Los Angeles, CA',
        service: 'UPS Ground',
        estimated_cost_cents: 1250,
        warnings: [],
      },
      {
        row_number: 2,
        recipient_name: 'Bob Smith',
        city_state: 'San Francisco, CA',
        service: 'UPS Ground',
        estimated_cost_cents: 1380,
        warnings: ['Address not validated'],
      },
    ],
    additional_rows: 23,
    total_estimated_cost_cents: 31250,
    rows_with_warnings: 1,
  }),

  /** A job progress snapshot. */
  jobProgress: (): JobProgress => ({
    job_id: 'job-002',
    status: 'running',
    total_rows: 10,
    processed_rows: 6,
    successful_rows: 5,
    failed_rows: 1,
    total_cost_cents: 12500,
  }),

  /** A confirm response. */
  confirmResponse: (): ConfirmResponse => ({
    status: 'accepted',
    message: 'Job queued for execution',
  }),
};
