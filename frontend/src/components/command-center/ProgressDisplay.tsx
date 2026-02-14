/**
 * Real-time batch execution progress display.
 *
 * Shows progress bar, success/failure stats, per-row failure details,
 * and download button on completion.
 */

import * as React from 'react';
import { useJobProgress } from '@/hooks/useJobProgress';
import { cn, formatCurrency } from '@/lib/utils';
import { getMergedLabelsUrl } from '@/lib/api';
import { DownloadIcon } from '@/components/ui/icons';

/** Per-row failure detail for callbacks. */
export interface RowFailureInfo {
  rowNumber: number;
  errorCode: string;
  errorMessage: string;
}

/** Progress data passed to completion callbacks. */
export interface ProgressData {
  total: number;
  successful: number;
  failed: number;
  totalCostCents: number;
  rowFailures: RowFailureInfo[];
}

/** Live batch execution progress with per-row failures. */
export function ProgressDisplay({ jobId, onComplete, onFailed }: {
  jobId: string;
  onComplete?: (data: ProgressData) => void;
  onFailed?: (data: ProgressData) => void;
}) {
  const { progress } = useJobProgress(jobId);
  const completeFiredRef = React.useRef(false);
  const failFiredRef = React.useRef(false);

  const percentage = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
  const isRunning = progress.status === 'running';
  const isComplete = progress.status === 'completed';
  const isFailed = progress.status === 'failed';

  React.useEffect(() => {
    if (isComplete && !completeFiredRef.current && onComplete) {
      completeFiredRef.current = true;
      onComplete({
        total: progress.total,
        successful: progress.successful,
        failed: progress.failed,
        totalCostCents: progress.totalCostCents,
        rowFailures: progress.rowFailures,
      });
    }
  }, [isComplete, onComplete, progress]);

  React.useEffect(() => {
    if (isFailed && !failFiredRef.current && onFailed) {
      failFiredRef.current = true;
      onFailed({
        total: progress.total,
        successful: progress.successful,
        failed: progress.failed,
        totalCostCents: progress.totalCostCents,
        rowFailures: progress.rowFailures,
      });
    }
  }, [isFailed, onFailed, progress]);

  return (
    <div className={cn(
      'card-premium p-4 space-y-4',
      isRunning && 'scan-line',
      isComplete && 'border-success/30',
      isFailed && 'border-error/30'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">
          {isComplete ? 'Batch Complete' : isFailed ? 'Batch Failed' : 'Processing Shipments'}
        </h3>
        <span className={cn(
          'badge',
          isComplete && 'badge-success',
          isFailed && 'badge-error',
          isRunning && 'badge-info'
        )}>
          {progress.status}
        </span>
      </div>

      {/* Progress bar */}
      <div className="space-y-2">
        <div className="progress-bar">
          <div
            className={cn('progress-bar-fill', isRunning && 'animated')}
            style={{ width: `${percentage}%` }}
          />
        </div>
        <div className="flex justify-between text-xs font-mono">
          <span className="text-slate-400">
            {progress.processed} / {progress.total} rows
          </span>
          <span className="text-slate-400">{percentage}%</span>
        </div>
      </div>

      {/* Stats */}
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

      {/* Per-row failure details */}
      {(progress.rowFailures?.length ?? 0) > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-error/90">
            {progress.rowFailures.length} row{progress.rowFailures.length !== 1 ? 's' : ''} failed:
          </p>
          <div className="max-h-[120px] overflow-y-auto scrollable space-y-1">
            {progress.rowFailures.map((f) => (
              <div key={f.rowNumber} className="p-2 rounded bg-error/10 border border-error/20 flex items-start gap-2">
                <span className="text-[10px] font-mono text-error/70 flex-shrink-0 mt-px">
                  Row {f.rowNumber}
                </span>
                <span className="text-[10px] font-mono text-error/90 break-all">
                  {f.errorMessage}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Batch-level error (when no per-row details available) */}
      {isFailed && progress.error && (progress.rowFailures?.length ?? 0) === 0 && (
        <div className="p-3 rounded-lg bg-error/10 border border-error/30">
          <p className="text-xs font-mono text-error">
            {progress.error.code}: {progress.error.message}
          </p>
        </div>
      )}

      {/* Download button if complete */}
      {isComplete && (
        <button
          onClick={() => window.open(getMergedLabelsUrl(jobId), '_blank')}
          className="w-full btn-primary py-2.5 flex items-center justify-center gap-2"
        >
          <DownloadIcon className="w-4 h-4" />
          <span>Download All Labels (PDF)</span>
        </button>
      )}
    </div>
  );
}
