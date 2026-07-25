import { getJobTerminalState } from '@shipagent/shared-types';
import type { JobProgressSnapshot } from './job-progress-sse.service';

/** Build the persisted chat artifact for a terminal job progress state. */
export function buildJobCompletionMetadata(
  jobId: string,
  progress: JobProgressSnapshot,
  jobName = ''
): Record<string, unknown> {
  const terminalState = getJobTerminalState(progress.status);

  return {
    type: 'completion',
    jobId,
    action: 'complete',
    completion: {
      status: progress.status,
      outcome: terminalState?.outcome,
      hasWarnings: terminalState?.hasWarnings ?? false,
      cancelled: terminalState?.cancelled ?? false,
      statusMessage: terminalState?.message,
      jobName: jobName || undefined,
      successful: progress.successful,
      failed: progress.failed,
      totalCostCents: progress.totalCostCents,
      dutiesTaxesCents: progress.dutiesTaxesCents,
      internationalCount: progress.internationalCount,
      error: progress.error ?? undefined,
      rowFailures:
        progress.rowFailures.length > 0 ? progress.rowFailures : undefined,
      currentRow: progress.currentRow ?? undefined,
      lastTrackingNumber: progress.lastTrackingNumber ?? undefined,
    },
  };
}
