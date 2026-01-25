/**
 * ProgressDisplay component for real-time batch execution progress.
 *
 * Displays a progress bar with row counter, percentage, and status
 * information during batch execution. Connects to SSE stream via
 * the useJobProgress hook.
 */

import * as React from 'react';
import { useJobProgress } from '@/hooks/useJobProgress';
import { Progress } from '@/components/ui/progress';
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
 * - Visual progress bar with percentage
 * - Text counter showing "X of Y shipments"
 * - Estimated time remaining
 * - Connection status indicator
 * - Different visual states for running/completed/failed
 */
export function ProgressDisplay({ jobId, className }: ProgressDisplayProps) {
  const { progress, isConnected, connectionError } = useJobProgress(jobId);

  // Calculate percentage
  const percentage =
    progress.total > 0
      ? Math.round((progress.processed / progress.total) * 100)
      : 0;

  // Track start time for ETA calculation
  // We use a simple approach - assume batch started when component mounts with running status
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
    <Card className={cn('w-full', className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold">
            Batch Progress
          </CardTitle>
          {/* Connection indicator */}
          <div className="flex items-center gap-2 text-sm">
            <span
              className={cn(
                'inline-block h-2 w-2 rounded-full',
                isConnected ? 'bg-green-500' : 'bg-yellow-500'
              )}
            />
            <span className="text-muted-foreground">
              {isConnected ? 'Live' : 'Connecting...'}
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Pending/Connecting state */}
        {isPending && (
          <div className="text-center py-4">
            <p className="text-muted-foreground">
              Waiting for batch to start...
            </p>
          </div>
        )}

        {/* Running state */}
        {isRunning && (
          <>
            {/* Counter text */}
            <div className="flex items-baseline justify-between">
              <p className="text-2xl font-bold tracking-tight">
                Processing{' '}
                <span className="text-primary">{progress.processed}</span>
                {' of '}
                <span className="text-primary">{progress.total}</span>
                {' shipments'}
              </p>
              <span className="text-3xl font-bold text-primary">
                {percentage}%
              </span>
            </div>

            {/* Progress bar */}
            <Progress
              value={percentage}
              className="h-3"
            />

            {/* Additional info row */}
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <div className="flex gap-4">
                <span>
                  <span className="text-green-600 font-medium">
                    {progress.successful}
                  </span>{' '}
                  successful
                </span>
                {progress.failed > 0 && (
                  <span>
                    <span className="text-red-600 font-medium">
                      {progress.failed}
                    </span>{' '}
                    failed
                  </span>
                )}
              </div>
              {timeRemaining && <span>{timeRemaining}</span>}
            </div>

            {/* Current row indicator */}
            {progress.currentRow !== null && (
              <p className="text-sm text-muted-foreground animate-pulse">
                Processing row {progress.currentRow}...
              </p>
            )}

            {/* Running cost */}
            {progress.totalCostCents > 0 && (
              <p className="text-sm text-muted-foreground">
                Cost so far: {formatCurrency(progress.totalCostCents)}
              </p>
            )}
          </>
        )}

        {/* Completed state */}
        {isCompleted && (
          <div className="text-center py-4 space-y-3">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-green-100 dark:bg-green-900/30">
              <CheckCircleIcon className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-xl font-semibold text-green-700 dark:text-green-400">
                Batch Complete!
              </p>
              <p className="text-muted-foreground mt-1">
                {progress.successful} shipment{progress.successful !== 1 ? 's' : ''}{' '}
                processed successfully
              </p>
            </div>
            {progress.totalCostCents > 0 && (
              <p className="text-lg font-medium">
                Total: {formatCurrency(progress.totalCostCents)}
              </p>
            )}
            {/* Full progress bar for completed */}
            <Progress value={100} className="h-2 mt-4" />
          </div>
        )}

        {/* Failed state */}
        {isFailed && (
          <div className="text-center py-4 space-y-3">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-red-100 dark:bg-red-900/30">
              <XCircleIcon className="h-6 w-6 text-red-600 dark:text-red-400" />
            </div>
            <div>
              <p className="text-xl font-semibold text-red-700 dark:text-red-400">
                Batch Failed
              </p>
              <p className="text-muted-foreground mt-1">
                Processed {progress.processed} of {progress.total} shipments
                before failure
              </p>
            </div>
            {/* Progress bar showing where it stopped */}
            <Progress
              value={percentage}
              className="h-2 mt-4 [&>div]:bg-red-500"
            />
          </div>
        )}

        {/* Connection error */}
        {connectionError && (
          <p className="text-sm text-yellow-600 dark:text-yellow-400 mt-2">
            Connection issue: {connectionError.message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Simple SVG icons to avoid external dependency
function CheckCircleIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

function XCircleIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  );
}

export default ProgressDisplay;
