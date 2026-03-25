/**
 * JobProgressSseService — Maps job progress SSE events to local signals.
 *
 * Consumes the /jobs/{id}/progress/stream endpoint and maintains
 * real-time progress signals for the ProgressDisplay component.
 *
 * Provided at component level (not root) for proper lifecycle management.
 */

import { Injectable, OnDestroy, inject, signal, computed } from '@angular/core';
import { Subscription, firstValueFrom } from 'rxjs';
import { SseService } from '@shipagent/shared-sse';
import { ApiService } from '@shipagent/shared-api';
import { JobStore } from '@shipagent/shared-state';
import type { JobStatus } from '@shipagent/shared-types';

/** Per-row failure detail. */
export interface RowFailure {
  rowNumber: number;
  errorCode: string;
  errorMessage: string;
}

/** Snapshot of batch execution progress. */
export interface JobProgressSnapshot {
  total: number;
  processed: number;
  successful: number;
  failed: number;
  totalCostCents: number;
  dutiesTaxesCents: number | undefined;
  internationalCount: number | undefined;
  status: JobStatus;
  error: { code: string; message: string } | null;
  rowFailures: RowFailure[];
  currentRow: number | null;
  lastTrackingNumber: string | null;
}

const INITIAL_PROGRESS: JobProgressSnapshot = {
  total: 0,
  processed: 0,
  successful: 0,
  failed: 0,
  totalCostCents: 0,
  dutiesTaxesCents: undefined,
  internationalCount: undefined,
  status: 'pending',
  error: null,
  rowFailures: [],
  currentRow: null,
  lastTrackingNumber: null,
};

@Injectable()
export class JobProgressSseService implements OnDestroy {
  private readonly sseService = inject(SseService);
  private readonly apiService = inject(ApiService);
  private readonly jobStore = inject(JobStore);

  private sseSubscription: Subscription | null = null;

  /** Current progress snapshot. */
  readonly progress = signal<JobProgressSnapshot>({ ...INITIAL_PROGRESS });

  /** Percentage complete (0-100). */
  readonly percentage = computed(() => {
    const p = this.progress();
    return p.total > 0 ? Math.round((p.processed / p.total) * 100) : 0;
  });

  /** True while batch is actively running. */
  readonly isRunning = computed(() => this.progress().status === 'running');

  /** True when batch completed successfully. */
  readonly isComplete = computed(() => this.progress().status === 'completed');

  /** True when batch failed. */
  readonly isFailed = computed(() => this.progress().status === 'failed');

  ngOnDestroy(): void {
    this.disconnect();
  }

  /**
   * Connect to the job progress SSE stream.
   * Also fetches the initial progress snapshot for page-refresh recovery.
   */
  async connectToJobProgress(jobId: string): Promise<void> {
    this.disconnect();
    this.progress.set({ ...INITIAL_PROGRESS });

    // Fetch initial progress for crash recovery.
    try {
      const data = await firstValueFrom(this.apiService.getJobProgress(jobId));
      this.progress.set({
        total: data.total_rows,
        processed: data.processed_rows,
        successful: data.successful_rows,
        failed: data.failed_rows,
        totalCostCents: data.total_cost_cents ?? 0,
        dutiesTaxesCents: data.total_duties_taxes_cents ?? undefined,
        internationalCount: data.international_row_count ?? undefined,
        status: data.status,
        error: null,
        rowFailures: [],
        currentRow: null,
        lastTrackingNumber: null,
      });
    } catch {
      // Non-critical — live SSE will update.
    }

    const url = this.apiService.getJobProgressUrl(jobId);
    this.sseSubscription = this.sseService.connect(url).subscribe({
      next: (event) => this.handleEvent(event.data),
      error: (err: unknown) => {
        console.error('[JobProgressSseService] SSE error:', err);
      },
    });
  }

  /** Disconnect the progress stream. */
  disconnect(): void {
    this.sseSubscription?.unsubscribe();
    this.sseSubscription = null;
    this.sseService.disconnect();
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  private handleEvent(data: unknown): void {
    if (!data || typeof data !== 'object') return;
    const d = data as Record<string, unknown>;

    // Backend sends { event, data } envelope.
    const eventType = d['event'] as string | undefined;
    const eventData = (d['data'] as Record<string, unknown>) ?? {};

    switch (eventType) {
      case 'batch_started':
        this.progress.update((p) => ({
          ...p,
          total: (eventData['total_rows'] as number) ?? p.total,
          status: 'running',
          processed: 0,
          successful: 0,
          failed: 0,
          totalCostCents: 0,
          error: null,
          rowFailures: [],
        }));
        break;

      case 'row_started':
        this.progress.update((p) => ({
          ...p,
          currentRow: (eventData['row_number'] as number) ?? null,
        }));
        break;

      case 'row_completed':
        this.progress.update((p) => ({
          ...p,
          processed: p.successful + p.failed + 1,
          successful: p.successful + 1,
          totalCostCents: p.totalCostCents + ((eventData['cost_cents'] as number) ?? 0),
          lastTrackingNumber: (eventData['tracking_number'] as string) ?? null,
          currentRow: null,
        }));
        break;

      case 'row_failed':
        this.progress.update((p) => ({
          ...p,
          processed: p.successful + p.failed + 1,
          failed: p.failed + 1,
          currentRow: null,
          error: {
            code: (eventData['error_code'] as string) ?? 'E-0000',
            message: (eventData['error_message'] as string) ?? 'Unknown error',
          },
          rowFailures: [
            ...p.rowFailures,
            {
              rowNumber: (eventData['row_number'] as number) ?? 0,
              errorCode: (eventData['error_code'] as string) ?? 'E-0000',
              errorMessage: (eventData['error_message'] as string) ?? 'Unknown error',
            },
          ],
        }));
        break;

      case 'batch_completed':
        this.progress.update((p) => ({
          ...p,
          status: 'completed',
          processed: (eventData['total_rows'] as number) ?? p.total,
          successful: (eventData['successful'] as number) ?? p.successful,
          totalCostCents: (eventData['total_cost_cents'] as number) ?? p.totalCostCents,
          dutiesTaxesCents:
            (eventData['duties_taxes_cents'] as number | undefined) ?? p.dutiesTaxesCents,
          internationalCount:
            (eventData['international_row_count'] as number | undefined) ?? p.internationalCount,
          currentRow: null,
        }));
        this.jobStore.incrementJobListVersion();
        break;

      case 'batch_failed':
        this.progress.update((p) => ({
          ...p,
          status: 'failed',
          processed: (eventData['processed'] as number) ?? p.processed,
          dutiesTaxesCents:
            (eventData['duties_taxes_cents'] as number | undefined) ?? p.dutiesTaxesCents,
          internationalCount:
            (eventData['international_row_count'] as number | undefined) ?? p.internationalCount,
          error: {
            code: (eventData['error_code'] as string) ?? 'E-0000',
            message: (eventData['error_message'] as string) ?? 'Batch execution failed',
          },
          currentRow: null,
        }));
        this.jobStore.incrementJobListVersion();
        break;

      default:
        break;
    }
  }
}
