/**
 * JobProgressSseService — Maps job progress SSE events to local signals.
 *
 * Consumes the /jobs/{id}/progress/stream endpoint and maintains
 * real-time progress signals for the ProgressDisplay component.
 *
 * Uses its own EventSource instance (not the shared SseService) to avoid
 * conflicts with ConversationSseService which also uses SseService.
 *
 * Provided at component level (not root) for proper lifecycle management.
 */

import { Injectable, OnDestroy, inject, signal, computed } from '@angular/core';
import { firstValueFrom, fromEvent, takeUntil } from 'rxjs';
import {
  ApiService,
  BrowserSessionTransportService,
} from '@shipagent/shared-api';
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

const RECONNECT_BASE_DELAY_MS = 250;
const MAX_RECONNECT_ATTEMPTS = 3;

@Injectable()
export class JobProgressSseService implements OnDestroy {
  private readonly apiService = inject(ApiService);
  private readonly browserTransport = inject(BrowserSessionTransportService);
  private readonly jobStore = inject(JobStore);

  /** Own EventSource instance — separate from the conversation SSE. */
  private eventSource: EventSource | null = null;
  private currentJobId: string | null = null;
  private lifecycleGeneration = 0;
  private lifecycleAbortController: AbortController | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;

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
    this.currentJobId = jobId;
    this.lifecycleAbortController = new AbortController();
    const generation = this.lifecycleGeneration;
    this.progress.set({ ...INITIAL_PROGRESS });

    // Fetch initial progress for crash recovery.
    const status = await this.refreshSnapshot(
      jobId,
      generation,
      this.lifecycleAbortController.signal
    );
    if (!this.isCurrent(jobId, generation)) return;
    if (status === 'completed' || status === 'failed') return;
    this.openStream(jobId, generation);
  }

  private openStream(jobId: string, generation: number): void {
    if (!this.isCurrent(jobId, generation) || this.eventSource) return;

    const es = new EventSource(this.apiService.getJobProgressUrl(jobId), {
      withCredentials: true,
    });
    let handlingError = false;
    this.eventSource = es;

    es.onopen = () => {
      if (this.eventSource === es && this.isCurrent(jobId, generation)) {
        this.reconnectAttempts = 0;
      }
    };

    es.onmessage = (event: MessageEvent) => {
      if (this.eventSource !== es || !this.isCurrent(jobId, generation)) return;
      try {
        const rawData = event.data as string;
        if (!rawData || rawData.trim() === '') return;

        const parsed = JSON.parse(rawData) as unknown;
        if (!parsed || typeof parsed !== 'object') return;

        // The progress endpoint sends { event, data } envelope.
        // Pass the FULL envelope to handleEvent — it extracts event type and data.
        const envelope = parsed as Record<string, unknown>;
        const eventType = envelope['event'] as string | undefined;

        // Skip pings.
        if (eventType === 'ping') return;

        this.handleEvent(envelope);
      } catch {
        // Ignore parse errors.
      }
    };

    es.onerror = () => {
      if (handlingError) return;
      handlingError = true;
      es.close();
      if (this.eventSource !== es || !this.isCurrent(jobId, generation)) return;
      this.eventSource = null;
      void this.recoverFromError(jobId, generation);
    };
  }

  /** Disconnect the progress stream. */
  disconnect(): void {
    this.lifecycleGeneration++;
    this.currentJobId = null;
    this.reconnectAttempts = 0;
    this.lifecycleAbortController?.abort();
    this.lifecycleAbortController = null;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  private async recoverFromError(
    jobId: string,
    generation: number
  ): Promise<void> {
    const abortSignal = this.lifecycleAbortController?.signal;
    if (!abortSignal || abortSignal.aborted) return;
    const sessionExpired =
      await this.browserTransport.confirmSessionAfterEventSourceError(
        abortSignal
      );
    if (sessionExpired || !this.isCurrent(jobId, generation)) return;

    const status = await this.refreshSnapshot(jobId, generation, abortSignal);
    if (!this.isCurrent(jobId, generation)) return;
    if (status === 'completed' || status === 'failed') {
      this.jobStore.incrementJobListVersion();
      return;
    }
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;

    const delay = RECONNECT_BASE_DELAY_MS * 2 ** this.reconnectAttempts;
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openStream(jobId, generation);
    }, delay);
  }

  private async refreshSnapshot(
    jobId: string,
    generation: number,
    abortSignal: AbortSignal
  ): Promise<JobStatus | null> {
    if (abortSignal.aborted) return null;
    try {
      const data = await firstValueFrom(
        this.apiService
          .getJobProgress(jobId)
          .pipe(takeUntil(fromEvent(abortSignal, 'abort')))
      );
      if (!this.isCurrent(jobId, generation)) return null;
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
      return data.status;
    } catch {
      // Non-critical — live SSE recovery remains bounded by its generation.
      return null;
    }
  }

  private isCurrent(jobId: string, generation: number): boolean {
    return (
      this.currentJobId === jobId && this.lifecycleGeneration === generation
    );
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
          totalCostCents:
            p.totalCostCents + ((eventData['cost_cents'] as number) ?? 0),
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
              errorMessage:
                (eventData['error_message'] as string) ?? 'Unknown error',
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
          totalCostCents:
            (eventData['total_cost_cents'] as number) ?? p.totalCostCents,
          dutiesTaxesCents:
            (eventData['duties_taxes_cents'] as number | undefined) ??
            p.dutiesTaxesCents,
          internationalCount:
            (eventData['international_row_count'] as number | undefined) ??
            p.internationalCount,
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
            (eventData['duties_taxes_cents'] as number | undefined) ??
            p.dutiesTaxesCents,
          internationalCount:
            (eventData['international_row_count'] as number | undefined) ??
            p.internationalCount,
          error: {
            code: (eventData['error_code'] as string) ?? 'E-0000',
            message:
              (eventData['error_message'] as string) ??
              'Batch execution failed',
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
