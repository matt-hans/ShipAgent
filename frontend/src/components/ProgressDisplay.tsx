/**
 * ProgressDisplay component for real-time batch execution progress.
 *
 * Industrial Logistics Terminal aesthetic - data-dense progress display
 * with routing line animations and technical indicators.
 */

import * as React from 'react';
import { useJobProgress } from '@/hooks/useJobProgress';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export interface ProgressDisplayProps {
  /** The job ID to monitor progress for. */
  jobId: string;
  /** Optional additional class name. */
  className?: string;
}

/**
 * Formats cents as currency string.
 */
function formatCurrency(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/**
 * Estimates time remaining based on average processing time.
 */
function formatTimeRemaining(
  processed: number,
  total: number,
  startTime: number | null
): string | null {
  if (!startTime || processed === 0 || processed >= total) {
    return null;
  }

  const elapsed = Date.now() - startTime;
  const avgTimePerRow = elapsed / processed;
  const remainingRows = total - processed;
  const remainingMs = avgTimePerRow * remainingRows;

  if (remainingMs < 60000) {
    return `~${Math.ceil(remainingMs / 1000)}s remaining`;
  }
  return `~${Math.ceil(remainingMs / 60000)}m remaining`;
}

/**
 * ProgressDisplay shows real-time batch execution progress.
 *
 * Features:
 * - Visual progress bar with routing line animation
 * - Text counter showing "X of Y shipments"
 * - Estimated time remaining
 * - Connection status indicator with pulse
 * - Different visual states for running/completed/failed
 * - Industrial aesthetic with technical details
 */
export function ProgressDisplay({ jobId, className }: ProgressDisplayProps) {
  const { progress, isConnected, connectionError } = useJobProgress(jobId);

  // Calculate percentage
  const percentage =
    progress.total > 0
      ? Math.round((progress.processed / progress.total) * 100)
      : 0;

  // Track start time for ETA calculation
  const startTimeRef = React.useRef<number | null>(null);
  if (progress.status === 'running' && !startTimeRef.current) {
    startTimeRef.current = Date.now();
  }

  const timeRemaining = formatTimeRemaining(
    progress.processed,
    progress.total,
    startTimeRef.current
  );

  // Determine visual state
  const isCompleted = progress.status === 'completed';
  const isFailed = progress.status === 'failed';
  const isRunning = progress.status === 'running';
  const isPending = progress.status === 'pending';

  return (
    <Card className={cn(
      'card-industrial overflow-hidden',
      className
    )}>
      <CardHeader className="pb-3 border-b border-steel-700/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Status icon */}
            <div className={cn(
              'p-2 rounded-sm border',
              isCompleted && 'bg-status-go/10 border-status-go/30',
              isFailed && 'bg-status-stop/10 border-status-stop/30',
              isRunning && 'bg-status-go/10 border-status-go/30 animate-pulse',
              isPending && 'bg-steel-800 border-steel-700'
            )}>
              {isCompleted ? (
                <svg className="h-4 w-4 text-status-go" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : isFailed ? (
                <svg className="h-4 w-4 text-status-stop" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <circle cx="12" cy="12" r="10" />
                  <line x1="15" y1="9" x2="9" y2="15" />
                  <line x1="9" y1="9" x2="15" y2="15" strokeLinecap="round" />
                </svg>
              ) : (
                <svg className={cn(
                  'h-4 w-4',
                  isRunning ? 'text-status-go' : 'text-steel-500'
                )} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
              )}
            </div>

            <div>
              <CardTitle className="font-display text-lg">
                BATCH PROGRESS
              </CardTitle>
              <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-widest">
                Job ID: {jobId.slice(0, 8)}
              </p>
            </div>
          </div>

          {/* Connection indicator */}
          <div className="flex items-center gap-2">
            <div className={cn(
              'h-2 w-2 rounded-full',
              isConnected ? 'bg-status-go animate-pulse' : 'bg-status-hold'
            )} />
            <span className="font-mono-display text-xs text-steel-400">
              {isConnected ? 'LIVE' : 'CONNECTING...'}
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-5 space-y-5">
        {/* Pending/Connecting state */}
        {isPending && (
          <div className="text-center py-6">
            <div className="inline-flex">
              <svg className="h-8 w-8 text-steel-500 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            </div>
            <p className="mt-3 font-mono-display text-sm text-steel-400">
              [ INITIALIZING BATCH ]
            </p>
          </div>
        )}

        {/* Running state */}
        {isRunning && (
          <div className="space-y-4">
            {/* Counter display */}
            <div className="flex items-baseline justify-between">
              <div>
                <p className="font-mono-display text-xs text-steel-500 uppercase tracking-widest mb-1">
                  Processing Status
                </p>
                <p className="font-display text-2xl font-bold text-steel-100">
                  <span className="text-signal-500">{progress.processed}</span>
                  <span className="text-steel-500 mx-1">/</span>
                  <span>{progress.total}</span>
                  <span className="text-sm font-normal text-steel-400 ml-2">shipments</span>
                </p>
              </div>
              <div className="text-right">
                <div className={cn(
                  'inline-flex items-center justify-center px-4 py-2 rounded-sm',
                  'bg-signal-500/10 border border-signal-500/30'
                )}>
                  <span className="font-mono-display text-3xl font-bold text-signal-500">
                    {percentage}%
                  </span>
                </div>
              </div>
            </div>

            {/* Progress bar with routing animation */}
            <div className="relative">
              <div className="h-3 progress-routing">
                <div
                  className="h-full bg-gradient-to-r from-signal-600 via-signal-500 to-signal-600"
                  style={{ width: `${percentage}%` }}
                />
              </div>
              {/* Percentage markers */}
              <div className="flex justify-between mt-1 font-mono-display text-[9px] text-steel-600">
                <span>0%</span>
                <span>25%</span>
                <span>50%</span>
                <span>75%</span>
                <span>100%</span>
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 rounded-sm bg-warehouse-800/50 border border-steel-700/50 text-center">
                <p className="font-mono-display text-lg font-bold text-status-go">
                  {progress.successful}
                </p>
                <p className="font-mono-display text-[10px] text-steel-500 uppercase">
                  Success
                </p>
              </div>
              {progress.failed > 0 && (
                <div className="p-3 rounded-sm bg-status-stop/5 border border-status-stop/20 text-center">
                  <p className="font-mono-display text-lg font-bold text-status-stop">
                    {progress.failed}
                  </p>
                  <p className="font-mono-display text-[10px] text-steel-500 uppercase">
                    Failed
                  </p>
                </div>
              )}
              {progress.totalCostCents > 0 && (
                <div className="p-3 rounded-sm bg-warehouse-800/50 border border-steel-700/50 text-center">
                  <p className="font-mono-display text-lg font-bold text-steel-100">
                    {formatCurrency(progress.totalCostCents)}
                  </p>
                  <p className="font-mono-display text-[10px] text-steel-500 uppercase">
                    Cost
                  </p>
                </div>
              )}
            </div>

            {/* Current row & ETA */}
            <div className="flex items-center justify-between font-mono-display text-xs">
              {progress.currentRow !== null ? (
                <div className="flex items-center gap-2 text-signal-500 animate-pulse">
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                  <span>PROCESSING ROW {progress.currentRow}</span>
                </div>
              ) : (
                <span className="text-steel-600">AWAITING NEXT ROW</span>
              )}
              {timeRemaining && (
                <span className="text-steel-400">ETA: {timeRemaining}</span>
              )}
            </div>
          </div>
        )}

        {/* Completed state */}
        {isCompleted && (
          <div className="text-center py-6 space-y-4">
            <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-status-go/10 border border-status-go/30">
              <svg className="h-8 w-8 text-status-go" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={3}>
                <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div>
              <p className="font-display text-xl font-semibold text-status-go">
                BATCH COMPLETE
              </p>
              <p className="font-mono-display text-sm text-steel-400 mt-1">
                {progress.successful} SHIPMENT{progress.successful !== 1 ? 'S' : ''} PROCESSED
              </p>
            </div>
            {progress.totalCostCents > 0 && (
              <div className="inline-flex items-center gap-3 px-6 py-3 rounded-sm bg-warehouse-800/50 border border-steel-700">
                <span className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
                  Total Cost
                </span>
                <span className="font-mono-display text-2xl font-bold text-signal-500">
                  {formatCurrency(progress.totalCostCents)}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Failed state */}
        {isFailed && (
          <div className="text-center py-6 space-y-4">
            <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-status-stop/10 border border-status-stop/30">
              <svg className="h-8 w-8 text-status-stop" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={3}>
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" strokeLinecap="round" />
                <line x1="9" y1="9" x2="15" y2="15" strokeLinecap="round" />
              </svg>
            </div>
            <div>
              <p className="font-display text-xl font-semibold text-status-stop">
                BATCH FAILED
              </p>
              <p className="font-mono-display text-sm text-steel-400 mt-1">
                PROCESSED {progress.processed} OF {progress.total} SHIPMENTS
              </p>
            </div>
            {progress.error && (
              <div className="max-w-md mx-auto p-3 rounded-sm bg-status-stop/5 border border-status-stop/20">
                <p className="font-mono-display text-xs text-status-stop">
                  [{progress.error.code}] {progress.error.message}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Connection error */}
        {connectionError && (
          <div className="p-3 rounded-sm bg-status-hold/5 border border-status-hold/20">
            <p className="font-mono-display text-xs text-status-hold">
              ⚠ CONNECTION ISSUE: {connectionError.message}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ProgressDisplay;
