/**
 * JobDetailPanel - Displays full details for a selected job from sidebar.
 *
 * Shows job header, summary stats, per-row details with order data,
 * and action buttons (reprint labels, start new batch).
 */

import * as React from 'react';
import { getJob, getJobRows, getMergedLabelsUrl } from '@/lib/api';
import { cn } from '@/lib/utils';
import { LabelPreview } from '@/components/LabelPreview';
import type { Job, JobRow, OrderData } from '@/types/api';

interface JobDetailPanelProps {
  /** The job to display details for. */
  job: Job;
  /** Callback to dismiss the detail panel and return to command input. */
  onBack: () => void;
}

// Icons

function ArrowLeftIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <line x1="19" y1="12" x2="5" y2="12" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="12 19 5 12 12 5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PrinterIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <polyline points="6 9 6 2 18 2 18 9" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="6" y="14" width="12" height="8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PlusIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <line x1="12" y1="5" x2="12" y2="19" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="5" y1="12" x2="19" y2="12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function XCircleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="9" y1="9" x2="15" y2="15" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MapPinIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="6 9 12 15 18 9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Format currency from cents. */
function formatCurrency(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

/** Format ISO date string to readable format. */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** Status badge matching sidebar pattern. */
function StatusBadge({ status }: { status: string }) {
  const style = {
    completed: 'badge-success',
    running: 'badge-info',
    failed: 'badge-error',
    pending: 'badge-neutral',
    cancelled: 'badge-warning',
  }[status] || 'badge-neutral';

  return <span className={cn('badge', style)}>{status}</span>;
}

/** Parse order_data JSON string safely. */
function parseOrderData(raw: string | null): OrderData | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Row detail item with expand/collapse. */
function RowDetailItem({ row }: { row: JobRow }) {
  const [expanded, setExpanded] = React.useState(false);
  const orderData = parseOrderData(row.order_data);
  const isSuccess = row.status === 'completed';
  const isFailed = row.status === 'failed';

  return (
    <div className="border-b border-slate-800 last:border-0">
      <button
        onClick={orderData ? () => setExpanded(!expanded) : undefined}
        className={cn(
          'w-full flex items-center justify-between px-3 py-2.5 text-xs transition-colors',
          orderData && 'hover:bg-slate-800/30 cursor-pointer',
          !orderData && 'cursor-default',
          expanded && 'bg-slate-800/20'
        )}
      >
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {/* Status icon */}
          {isSuccess ? (
            <CheckIcon className="w-3.5 h-3.5 text-success flex-shrink-0" />
          ) : isFailed ? (
            <XCircleIcon className="w-3.5 h-3.5 text-error flex-shrink-0" />
          ) : (
            <span className="w-3.5 h-3.5 rounded-full border border-slate-600 flex-shrink-0" />
          )}

          {orderData && (
            <ChevronDownIcon
              className={cn(
                'w-3 h-3 text-slate-500 transition-transform flex-shrink-0',
                expanded && 'rotate-180'
              )}
            />
          )}

          <div className="flex-1 min-w-0 text-left">
            <span className="text-slate-300 font-mono text-[10px]">Row {row.row_number}</span>
            {orderData && (
              <span className="text-slate-200 ml-2 font-medium truncate">
                {orderData.ship_to_name}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {row.tracking_number && (
            <span className="font-mono text-cyan-400 text-[10px]">{row.tracking_number}</span>
          )}
          {row.cost_cents != null && row.cost_cents > 0 && (
            <span className="font-mono text-amber-400 text-[10px]">{formatCurrency(row.cost_cents)}</span>
          )}
          {isFailed && row.error_message && (
            <span className="text-error text-[10px] truncate max-w-[120px]" title={row.error_message}>
              {row.error_code || 'Error'}
            </span>
          )}
        </div>
      </button>

      {/* Expanded order details */}
      {expanded && orderData && (
        <div className="px-4 py-3 bg-slate-800/30 border-t border-slate-800 animate-fade-in">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Recipient</span>
              <p className="text-sm text-slate-200">{orderData.ship_to_name}</p>
              {orderData.ship_to_company && (
                <p className="text-xs text-slate-400">{orderData.ship_to_company}</p>
              )}
            </div>
            <div className="space-y-1">
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Customer</span>
              <p className="text-sm text-slate-200">{orderData.customer_name}</p>
              {orderData.customer_email && (
                <p className="text-[10px] font-mono text-slate-500">{orderData.customer_email}</p>
              )}
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-800/50">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider mb-1">
              <MapPinIcon className="w-3 h-3" />
              <span>Address</span>
            </div>
            <p className="text-sm text-slate-200">{orderData.ship_to_address1}</p>
            {orderData.ship_to_address2 && (
              <p className="text-sm text-slate-300">{orderData.ship_to_address2}</p>
            )}
            <p className="text-sm text-slate-300">
              {orderData.ship_to_city}, {orderData.ship_to_state} {orderData.ship_to_postal_code}
            </p>
          </div>

          {orderData.order_number && (
            <div className="mt-2 text-[10px] font-mono text-slate-500">
              Order #{orderData.order_number}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * JobDetailPanel displays full job information when a job is selected
 * from the sidebar history.
 */
export function JobDetailPanel({ job, onBack }: JobDetailPanelProps) {
  const [fullJob, setFullJob] = React.useState<Job>(job);
  const [rows, setRows] = React.useState<JobRow[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [showLabelPreview, setShowLabelPreview] = React.useState(false);

  // Fetch full job data and rows
  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);

    Promise.all([getJob(job.id), getJobRows(job.id)])
      .then(([jobData, rowData]) => {
        if (cancelled) return;
        setFullJob(jobData);
        setRows(rowData);
      })
      .catch((err) => {
        console.error('Failed to load job details:', err);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [job.id]);

  const isCompleted = fullJob.status === 'completed';

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-slate-800 px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors mb-3"
          >
            <ArrowLeftIcon className="w-3.5 h-3.5" />
            <span>Back to commands</span>
          </button>

          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-medium text-slate-100 truncate">
                {fullJob.original_command || fullJob.name}
              </h2>
              <p className="text-[10px] font-mono text-slate-500 mt-1">
                {formatDate(fullJob.created_at)} · Job {fullJob.id.slice(0, 8)}
              </p>
            </div>
            <StatusBadge status={fullJob.status} />
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto scrollable p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {/* Summary stats */}
          <div className="grid grid-cols-4 gap-3">
            <div className="card-premium p-3 text-center">
              <p className="text-2xl font-semibold text-slate-100">{fullJob.total_rows}</p>
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Total</p>
            </div>
            <div className="card-premium p-3 text-center">
              <p className="text-2xl font-semibold text-success">{fullJob.successful_rows}</p>
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Success</p>
            </div>
            <div className="card-premium p-3 text-center">
              <p className="text-2xl font-semibold text-error">{fullJob.failed_rows}</p>
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Failed</p>
            </div>
            <div className="card-premium p-3 text-center">
              <p className="text-2xl font-semibold text-amber-400">
                {fullJob.total_cost_cents ? formatCurrency(fullJob.total_cost_cents) : '$0.00'}
              </p>
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Cost</p>
            </div>
          </div>

          {/* Error info if failed */}
          {fullJob.error_code && (
            <div className="p-3 rounded-lg bg-error/10 border border-error/30">
              <p className="text-xs font-mono text-error">
                {fullJob.error_code}: {fullJob.error_message}
              </p>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-3">
            {isCompleted && (
              <button
                onClick={() => setShowLabelPreview(true)}
                className="btn-primary py-2.5 px-4 flex items-center gap-2"
              >
                <PrinterIcon className="w-4 h-4" />
                <span>View Labels</span>
              </button>
            )}
            <button
              onClick={onBack}
              className="btn-secondary py-2.5 px-4 flex items-center gap-2"
            >
              <PlusIcon className="w-4 h-4" />
              <span>New Batch</span>
            </button>
          </div>

          {/* Row details */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                Shipment Rows
              </p>
              <p className="text-[10px] font-mono text-slate-500">{rows.length} rows</p>
            </div>

            {isLoading ? (
              <div className="space-y-2">
                <div className="h-10 bg-slate-800 rounded shimmer" />
                <div className="h-10 bg-slate-800 rounded shimmer" />
                <div className="h-10 bg-slate-800 rounded shimmer" />
              </div>
            ) : rows.length === 0 ? (
              <p className="text-xs text-slate-500 text-center py-8">No rows found</p>
            ) : (
              <div className="rounded-md border border-slate-800 overflow-hidden">
                {rows.map((row) => (
                  <RowDetailItem key={row.id} row={row} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Label preview modal */}
      {isCompleted && (
        <LabelPreview
          pdfUrl={getMergedLabelsUrl(fullJob.id)}
          title="Batch Labels"
          isOpen={showLabelPreview}
          onClose={() => setShowLabelPreview(false)}
        />
      )}
    </div>
  );
}

export default JobDetailPanel;
