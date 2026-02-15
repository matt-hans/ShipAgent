/**
 * JobDetailPanel - Displays full details for a selected job from sidebar.
 *
 * Shows job header, summary stats, per-row details with order data,
 * and action buttons (reprint labels, start new batch).
 */

import * as React from 'react';
import { getJob, getJobRows, getMergedLabelsUrl, confirmJob, cancelJob } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useJobProgress } from '@/hooks/useJobProgress';
import { useAppState } from '@/hooks/useAppState';
import { LabelPreview } from '@/components/LabelPreview';
import type { Job, JobRow, OrderData, ChargeBreakdown } from '@/types/api';
import {
  ArrowLeftIcon,
  PrinterIcon,
  PlusIcon,
  CheckIcon,
  XCircleIcon,
  MapPinIcon,
  ChevronDownIcon,
  PlayIcon,
  XIcon,
  DownloadIcon,
  EditIcon,
} from '@/components/ui/icons';

interface JobDetailPanelProps {
  /** The job to display details for. */
  job: Job;
  /** Callback to dismiss the detail panel and return to command input. */
  onBack: () => void;
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

/** Parse charge_breakdown which may be a JSON string or already an object. */
function parseChargeBreakdown(raw: ChargeBreakdown | string | null | undefined): ChargeBreakdown | null {
  if (!raw) return null;
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
  return raw;
}

/** Row detail item with expand/collapse. */
function RowDetailItem({ row }: { row: JobRow }) {
  const [expanded, setExpanded] = React.useState(false);
  const orderData = parseOrderData(row.order_data);
  const chargeBreakdown = parseChargeBreakdown(row.charge_breakdown);
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
          {row.destination_country && row.destination_country !== 'US' && (
            <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-mono font-medium uppercase">
              {row.destination_country}
            </span>
          )}
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
              <p className="text-sm text-slate-200">{orderData.customer_name || orderData.ship_to_name}</p>
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

          {/* Charge breakdown for international rows */}
          {chargeBreakdown && (
            <div className="mt-3 pt-3 border-t border-slate-800/50">
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Charge Breakdown</span>
              <div className="mt-1 space-y-0.5">
                {chargeBreakdown.transportationCharges && (
                  <div className="flex justify-between text-[10px] font-mono text-slate-400">
                    <span>Transportation</span>
                    <span>${chargeBreakdown.transportationCharges.monetaryValue}</span>
                  </div>
                )}
                {chargeBreakdown.dutiesAndTaxes && (
                  <div className="flex justify-between text-[10px] font-mono text-amber-400/80">
                    <span>Duties & Taxes</span>
                    <span>${chargeBreakdown.dutiesAndTaxes.monetaryValue}</span>
                  </div>
                )}
                {chargeBreakdown.brokerageCharges && (
                  <div className="flex justify-between text-[10px] font-mono text-slate-400">
                    <span>Brokerage</span>
                    <span>${chargeBreakdown.brokerageCharges.monetaryValue}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {(orderData.order_number || orderData.order_id) && (
            <div className="mt-2 text-[10px] font-mono text-slate-500">
              Order #{orderData.order_number || orderData.order_id}
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
  const { refreshJobList } = useAppState();
  const [fullJob, setFullJob] = React.useState<Job>(job);
  const [rows, setRows] = React.useState<JobRow[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [showLabelPreview, setShowLabelPreview] = React.useState(false);
  const [isConfirming, setIsConfirming] = React.useState(false);
  const [isCancelling, setIsCancelling] = React.useState(false);
  const [executingJobId, setExecutingJobId] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [showRefinement, setShowRefinement] = React.useState(false);
  const [refinementInput, setRefinementInput] = React.useState('');
  const isRefining = false;

  // Track progress via SSE when executing
  const { progress } = useJobProgress(executingJobId);
  const completeFiredRef = React.useRef(false);

  // Fetch full job data and rows
  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);

    Promise.all([getJob(job.id), getJobRows(job.id)])
      .then(([jobData, rowData]) => {
        if (cancelled) return;
        setFullJob(jobData);
        setRows(rowData);

        // If the job is already running, start tracking progress
        if (jobData.status === 'running') {
          setExecutingJobId(jobData.id);
        }
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

  // Handle execution completion — re-fetch job data and rows
  React.useEffect(() => {
    if (
      executingJobId &&
      (progress.status === 'completed' || progress.status === 'failed') &&
      !completeFiredRef.current
    ) {
      completeFiredRef.current = true;

      // Re-fetch updated job and rows
      Promise.all([getJob(executingJobId), getJobRows(executingJobId)])
        .then(([jobData, rowData]) => {
          setFullJob(jobData);
          setRows(rowData);
          setExecutingJobId(null);
          refreshJobList();
        })
        .catch((err) => {
          console.error('Failed to refresh job after completion:', err);
          setExecutingJobId(null);
          refreshJobList();
        });
    }
  }, [executingJobId, progress.status, refreshJobList]);

  /** Confirm and begin executing the pending batch. */
  const handleConfirm = async () => {
    setIsConfirming(true);
    setActionError(null);
    completeFiredRef.current = false;

    try {
      await confirmJob(fullJob.id);
      setExecutingJobId(fullJob.id);
      setFullJob((prev) => ({ ...prev, status: 'running' }));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to confirm batch');
    } finally {
      setIsConfirming(false);
    }
  };

  /** Cancel the pending batch. */
  const handleCancel = async () => {
    setIsCancelling(true);
    setActionError(null);

    try {
      await cancelJob(fullJob.id);
      setFullJob((prev) => ({ ...prev, status: 'cancelled' }));
      refreshJobList();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to cancel batch');
    } finally {
      setIsCancelling(false);
    }
  };

  /** Refine the pending batch — refinement is now handled via the conversation flow. */
  const handleRefine = async () => {
    if (!refinementInput.trim() || isRefining) return;

    setActionError('Refinement is handled via the chat conversation. Type your refinement in the command center.');
  };

  const isPending = fullJob.status === 'pending';
  const isCompleted = fullJob.status === 'completed';
  const isCancelled = fullJob.status === 'cancelled';

  // For pending jobs, total_cost_cents is 0 — compute estimated cost from row-level rates
  const displayCostCents = fullJob.total_cost_cents
    || rows.reduce((sum, r) => sum + (r.cost_cents ?? 0), 0);

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
              {(() => {
                if (!fullJob.name?.includes(' → ')) {
                  return (
                    <h2 className="text-lg font-medium text-slate-100 truncate">
                      {fullJob.name?.startsWith('Command: ') ? fullJob.name.slice(9) : fullJob.original_command || fullJob.name}
                    </h2>
                  );
                }
                const parts = fullJob.name.split(' → ');
                const base = parts[0];
                const refs = parts.slice(1);
                const maxVisible = 3;
                const visible = refs.slice(0, maxVisible);
                const overflow = refs.length - maxVisible;
                return (
                  <>
                    <h2 className="text-lg font-medium text-slate-100 truncate">{base}</h2>
                    {visible.map((r, i) => (
                      <p key={i} className="text-sm text-primary/80 truncate mt-0.5">
                        &rarr; {r}
                      </p>
                    ))}
                    {overflow > 0 && (
                      <p className="text-xs text-slate-500 italic mt-0.5">
                        +{overflow} more refinement{overflow !== 1 ? 's' : ''}
                      </p>
                    )}
                  </>
                );
              })()}
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
                {formatCurrency(displayCostCents)}
              </p>
              <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                {isPending ? 'Est. Cost' : 'Cost'}
              </p>
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

          {/* Action error */}
          {actionError && (
            <div className="p-3 rounded-lg bg-error/10 border border-error/30">
              <p className="text-xs text-error">{actionError}</p>
            </div>
          )}

          {/* Execution progress (shown while running) */}
          {executingJobId && (
            <div className={cn(
              'card-premium p-4 space-y-4 scan-line',
              progress.status === 'completed' && 'border-success/30',
              progress.status === 'failed' && 'border-error/30'
            )}>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-200">Processing Shipments</h3>
                <span className="badge badge-info">{progress.status}</span>
              </div>

              <div className="space-y-2">
                <div className="progress-bar">
                  <div
                    className={cn('progress-bar-fill', progress.status === 'running' && 'animated')}
                    style={{ width: `${progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-slate-400">
                    {progress.processed} / {progress.total} rows
                  </span>
                  <span className="text-slate-400">
                    {progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0}%
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-2">
                <div className="p-2 rounded bg-slate-800/50 text-center">
                  <p className="text-lg font-semibold text-slate-100">{progress.total}</p>
                  <p className="text-[10px] font-mono text-slate-500">Total</p>
                </div>
                <div className="p-2 rounded bg-slate-800/50 text-center">
                  <p className="text-lg font-semibold text-success">{progress.successful}</p>
                  <p className="text-[10px] font-mono text-slate-500">Success</p>
                </div>
                <div className="p-2 rounded bg-slate-800/50 text-center">
                  <p className="text-lg font-semibold text-error">{progress.failed}</p>
                  <p className="text-[10px] font-mono text-slate-500">Failed</p>
                </div>
                <div className="p-2 rounded bg-slate-800/50 text-center">
                  <p className="text-lg font-semibold text-primary">
                    {formatCurrency(progress.totalCostCents)}
                  </p>
                  <p className="text-[10px] font-mono text-slate-500">Cost</p>
                </div>
              </div>

              {progress.error && (
                <div className="p-3 rounded-lg bg-error/10 border border-error/30">
                  <p className="text-xs font-mono text-error">
                    {progress.error.code}: {progress.error.message}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-3">
            {/* Pending: Confirm & Cancel */}
            {isPending && !executingJobId && (
              <>
                <button
                  onClick={handleConfirm}
                  disabled={isConfirming}
                  className="btn-primary py-2.5 px-4 flex items-center gap-2"
                >
                  {isConfirming ? (
                    <>
                      <span className="w-4 h-4 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
                      <span>Confirming...</span>
                    </>
                  ) : (
                    <>
                      <PlayIcon className="w-4 h-4" />
                      <span>Confirm & Execute</span>
                    </>
                  )}
                </button>
                <button
                  onClick={handleCancel}
                  disabled={isConfirming || isCancelling || isRefining}
                  className="btn-secondary py-2.5 px-4 flex items-center gap-2"
                >
                  {isCancelling ? (
                    <>
                      <span className="w-4 h-4 border-2 border-slate-500/30 border-t-slate-500 rounded-full animate-spin" />
                      <span>Cancelling...</span>
                    </>
                  ) : (
                    <>
                      <XIcon className="w-4 h-4" />
                      <span>Cancel</span>
                    </>
                  )}
                </button>
                <button
                  onClick={() => setShowRefinement(!showRefinement)}
                  disabled={isRefining || isConfirming}
                  className="btn-secondary py-2.5 px-4 flex items-center gap-2"
                >
                  <EditIcon className="w-4 h-4" />
                  <span>Refine</span>
                </button>
              </>
            )}

            {/* Completed: View Labels + Download */}
            {isCompleted && (
              <>
                <button
                  onClick={() => setShowLabelPreview(true)}
                  className="btn-primary py-2.5 px-4 flex items-center gap-2"
                >
                  <PrinterIcon className="w-4 h-4" />
                  <span>View Labels</span>
                </button>
                <button
                  onClick={() => window.open(getMergedLabelsUrl(fullJob.id), '_blank')}
                  className="btn-secondary py-2.5 px-4 flex items-center gap-2"
                >
                  <DownloadIcon className="w-4 h-4" />
                  <span>Download PDF</span>
                </button>
              </>
            )}

            {/* Cancelled info */}
            {isCancelled && (
              <p className="text-xs text-slate-500 py-2.5">This batch was cancelled.</p>
            )}

            {/* Always show New Batch unless executing */}
            {!executingJobId && (
              <button
                onClick={onBack}
                className="btn-secondary py-2.5 px-4 flex items-center gap-2"
              >
                <PlusIcon className="w-4 h-4" />
                <span>New Shipments</span>
              </button>
            )}
          </div>

          {/* Refinement input */}
          {isPending && showRefinement && (
            <div className="card-premium p-4 space-y-3">
              <p className="text-xs text-slate-400">
                Describe how to change this batch (e.g. "change to 2nd Day Air", "only ship orders over $50")
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={refinementInput}
                  onChange={(e) => setRefinementInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleRefine()}
                  placeholder="e.g. change to Next Day Air"
                  disabled={isRefining}
                  className="flex-1 px-3 py-2 rounded-md bg-slate-800 border border-slate-700 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-primary"
                />
                <button
                  onClick={handleRefine}
                  disabled={!refinementInput.trim() || isRefining}
                  className="btn-primary py-2 px-4 flex items-center gap-2"
                >
                  {isRefining ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
                      <span>Refining...</span>
                    </>
                  ) : (
                    <span>Apply</span>
                  )}
                </button>
              </div>
            </div>
          )}

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
