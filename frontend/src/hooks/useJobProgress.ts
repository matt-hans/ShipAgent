/**
 * React hook for tracking job progress via SSE.
 *
 * Provides real-time progress updates by consuming the SSE progress
 * stream and maintaining local state.
 */

import { useEffect, useState, useCallback } from 'react';
import { useSSE } from './useSSE';
import { getProgressStreamUrl, getJobProgress } from '@/lib/api';
import type { JobStatus, ProgressEvent } from '@/types/api';

/** Progress state for a job. */
export interface JobProgressState {
  /** Total number of rows in the batch. */
  total: number;
  /** Number of rows processed so far. */
  processed: number;
  /** Number of successful rows. */
  successful: number;
  /** Number of failed rows. */
  failed: number;
  /** Total cost in cents. */
  totalCostCents: number;
  /** Current job status. */
  status: JobStatus;
  /** Error information if the batch failed. */
  error: {
    code: string;
    message: string;
  } | null;
  /** Row that is currently being processed. */
  currentRow: number | null;
  /** Most recent tracking number from a completed row. */
  lastTrackingNumber: string | null;
}

/** Return type for the useJobProgress hook. */
export interface UseJobProgressReturn {
  /** Current progress state. */
  progress: JobProgressState;
  /** Whether connected to SSE stream. */
  isConnected: boolean;
  /** Connection error if any. */
  connectionError: Error | null;
  /** Manually disconnect from the stream. */
  disconnect: () => void;
}

const initialState: JobProgressState = {
  total: 0,
  processed: 0,
  successful: 0,
  failed: 0,
  totalCostCents: 0,
  status: 'pending',
  error: null,
  currentRow: null,
  lastTrackingNumber: null,
};

/**
 * Hook for tracking job progress via SSE.
 *
 * Connects to the SSE progress stream for the given job and
 * maintains progress state. Also fetches initial progress
 * state on mount to handle page refreshes.
 *
 * @param jobId - The job UUID to monitor, or null to disable.
 * @returns Progress state, connection status, and controls.
 *
 * @example
 * ```tsx
 * function BatchProgress({ jobId }: { jobId: string }) {
 *   const { progress, isConnected } = useJobProgress(jobId);
 *
 *   return (
 *     <div>
 *       <p>Status: {progress.status}</p>
 *       <p>Progress: {progress.processed} / {progress.total}</p>
 *       {isConnected ? <span>Live</span> : <span>Disconnected</span>}
 *     </div>
 *   );
 * }
 * ```
 */
export function useJobProgress(
  jobId: string | null
): UseJobProgressReturn {
  const [progress, setProgress] = useState<JobProgressState>(initialState);

  // Get the SSE URL only when jobId is provided
  const sseUrl = jobId ? getProgressStreamUrl(jobId) : null;

  // Connect to SSE stream
  const { lastEvent, isConnected, error: connectionError, disconnect } =
    useSSE<ProgressEvent>(sseUrl);

  // Fetch initial progress state
  useEffect(() => {
    if (!jobId) {
      setProgress(initialState);
      return;
    }

    // Load initial progress (useful for page refresh during execution)
    getJobProgress(jobId)
      .then((data) => {
        setProgress({
          total: data.total_rows,
          processed: data.processed_rows,
          successful: data.successful_rows,
          failed: data.failed_rows,
          totalCostCents: data.total_cost_cents ?? 0,
          status: data.status,
          error: null,
          currentRow: null,
          lastTrackingNumber: null,
        });
      })
      .catch((err) => {
        console.error('Failed to fetch initial progress:', err);
      });
  }, [jobId]);

  // Process SSE events
  useEffect(() => {
    if (!lastEvent) return;

    const eventData = lastEvent.data;

    // Skip ping events
    if (lastEvent.event === 'ping') return;

    // Handle different event types
    // The backend sends events with 'event' field in the data
    if (typeof eventData === 'object' && eventData !== null && 'event' in eventData) {
      const typedEvent = eventData as ProgressEvent;

      switch (typedEvent.event) {
        case 'batch_started':
          setProgress((prev) => ({
            ...prev,
            total: typedEvent.data.total_rows,
            status: 'running',
            processed: 0,
            successful: 0,
            failed: 0,
            totalCostCents: 0,
            error: null,
          }));
          break;

        case 'row_started':
          setProgress((prev) => ({
            ...prev,
            currentRow: typedEvent.data.row_number,
          }));
          break;

        case 'row_completed':
          setProgress((prev) => ({
            ...prev,
            processed: typedEvent.data.row_number,
            successful: prev.successful + 1,
            totalCostCents: prev.totalCostCents + typedEvent.data.cost_cents,
            lastTrackingNumber: typedEvent.data.tracking_number,
            currentRow: null,
          }));
          break;

        case 'row_failed':
          setProgress((prev) => ({
            ...prev,
            processed: typedEvent.data.row_number,
            failed: prev.failed + 1,
            currentRow: null,
            error: {
              code: typedEvent.data.error_code,
              message: typedEvent.data.error_message,
            },
          }));
          break;

        case 'batch_completed':
          setProgress((prev) => ({
            ...prev,
            status: 'completed',
            processed: typedEvent.data.total_rows,
            successful: typedEvent.data.successful,
            totalCostCents: typedEvent.data.total_cost_cents,
            currentRow: null,
          }));
          break;

        case 'batch_failed':
          setProgress((prev) => ({
            ...prev,
            status: 'failed',
            processed: typedEvent.data.processed,
            error: {
              code: typedEvent.data.error_code,
              message: typedEvent.data.error_message,
            },
            currentRow: null,
          }));
          break;

        case 'ping':
          // Ignore ping events
          break;
      }
    }
  }, [lastEvent]);

  const wrappedDisconnect = useCallback(() => {
    disconnect();
  }, [disconnect]);

  return {
    progress,
    isConnected,
    connectionError,
    disconnect: wrappedDisconnect,
  };
}

export default useJobProgress;
