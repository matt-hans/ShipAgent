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
import {
  getJobTerminalState,
  resolveJobTerminalStatus,
  type JobStatus,
  type SafeTerminalDiagnostic,
  type SafeTerminalRowDiagnostic,
} from '@shipagent/shared-types';

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
  error: SafeTerminalDiagnostic | null;
  rowFailures: SafeTerminalRowDiagnostic[];
  omittedFailureCount: number;
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
  omittedFailureCount: 0,
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
  private progressRevision = 0;

  /** Current progress snapshot. */
  readonly progress = signal<JobProgressSnapshot>({ ...INITIAL_PROGRESS });

  /** Percentage complete (0-100). */
  readonly percentage = computed(() => {
    const p = this.progress();
    return p.total > 0 ? Math.round((p.processed / p.total) * 100) : 0;
  });

  /** True while batch is actively running. */
  readonly isRunning = computed(() => this.progress().status === 'running');

  /** Centralized terminal interpretation of the current backend status. */
  readonly terminalState = computed(() =>
    getJobTerminalState(this.progress().status)
  );

  /** True when batch completed, including completion with warnings. */
  readonly isComplete = computed(
    () => this.terminalState()?.outcome === 'complete'
  );

  /** True when batch failed or was cancelled. */
  readonly isFailed = computed(
    () => this.terminalState()?.outcome === 'failed'
  );

  /** True when the completed batch carries explicit warnings. */
  readonly hasWarnings = computed(
    () => this.terminalState()?.hasWarnings ?? false
  );

  /** True when the batch was cancelled. */
  readonly isCancelled = computed(
    () => this.terminalState()?.cancelled ?? false
  );

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
    this.progressRevision = 0;

    // Fetch initial progress for crash recovery.
    const status = await this.refreshSnapshot(
      jobId,
      generation,
      this.lifecycleAbortController.signal
    );
    if (!this.isCurrent(jobId, generation)) return;
    if (status && getJobTerminalState(status)) return;
    this.openStream(jobId, generation);
  }

  private openStream(
    jobId: string,
    generation: number,
    reconcileAfterOpen?: AbortSignal
  ): EventSource | null {
    if (!this.isCurrent(jobId, generation) || this.eventSource) return null;

    const es = new EventSource(this.apiService.getJobProgressUrl(jobId), {
      withCredentials: true,
    });
    let handlingError = false;
    let reconciliationStarted = false;
    this.eventSource = es;

    es.onopen = () => {
      if (
        !reconcileAfterOpen ||
        reconciliationStarted ||
        reconcileAfterOpen.aborted ||
        this.eventSource !== es ||
        !this.isCurrent(jobId, generation)
      ) {
        return;
      }
      reconciliationStarted = true;
      void this.reconcileAfterSubscription(
        jobId,
        generation,
        reconcileAfterOpen,
        es
      );
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

        if (this.handleEvent(envelope)) {
          this.progressRevision++;
          this.reconnectAttempts = 0;
          if (this.terminalState()) {
            this.stopTerminalStream(jobId, generation, es);
          }
        }
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

    return es;
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
    if (status && getJobTerminalState(status)) {
      this.jobStore.incrementJobListVersion();
      return;
    }
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;

    const delay = RECONNECT_BASE_DELAY_MS * 2 ** this.reconnectAttempts;
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openStream(jobId, generation, abortSignal);
    }, delay);
  }

  private async reconcileAfterSubscription(
    jobId: string,
    generation: number,
    abortSignal: AbortSignal,
    source: EventSource
  ): Promise<void> {
    const expectedRevision = this.progressRevision;
    const status = await this.refreshSnapshot(
      jobId,
      generation,
      abortSignal,
      expectedRevision,
      source
    );
    if (this.eventSource !== source || !this.isCurrent(jobId, generation)) {
      return;
    }
    if (status && getJobTerminalState(status)) {
      source.close();
      this.eventSource = null;
      this.jobStore.incrementJobListVersion();
    }
  }

  private async refreshSnapshot(
    jobId: string,
    generation: number,
    abortSignal: AbortSignal,
    expectedRevision?: number,
    expectedSource?: EventSource
  ): Promise<JobStatus | null> {
    if (abortSignal.aborted) return null;
    try {
      const data = await firstValueFrom(
        this.apiService
          .getJobProgress(jobId)
          .pipe(takeUntil(fromEvent(abortSignal, 'abort')))
      );
      if (!this.isCurrent(jobId, generation)) return null;
      if (
        (expectedRevision !== undefined &&
          this.progressRevision !== expectedRevision) ||
        (expectedSource !== undefined && this.eventSource !== expectedSource)
      ) {
        return null;
      }
      this.progress.update((current) => ({
        ...current,
        total: data.total_rows,
        processed: data.processed_rows,
        successful: data.successful_rows,
        failed: data.failed_rows,
        totalCostCents: data.total_cost_cents ?? 0,
        dutiesTaxesCents:
          data.total_duties_taxes_cents === undefined
            ? current.dutiesTaxesCents
            : data.total_duties_taxes_cents ?? undefined,
        internationalCount:
          data.international_row_count ?? current.internationalCount,
        rowFailures: data.row_failures ?? current.rowFailures,
        omittedFailureCount:
          data.omitted_failure_count ?? current.omittedFailureCount,
        status: data.status,
      }));
      this.progressRevision++;
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

  private stopTerminalStream(
    jobId: string,
    generation: number,
    source: EventSource
  ): void {
    if (this.eventSource !== source || !this.isCurrent(jobId, generation)) {
      return;
    }
    source.close();
    this.eventSource = null;
    this.lifecycleAbortController?.abort();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.jobStore.incrementJobListVersion();
  }

  // ---------------------------------------------------------------------------
  // Event handlers
  // ---------------------------------------------------------------------------

  private handleEvent(data: unknown): boolean {
    if (!data || typeof data !== 'object') return false;
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
          omittedFailureCount: 0,
        }));
        return true;

      case 'row_started':
        this.progress.update((p) => ({
          ...p,
          currentRow: (eventData['row_number'] as number) ?? null,
        }));
        return true;

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
        return true;

      case 'row_failed': {
        const diagnostic = eventData['diagnostic'] as
          | SafeTerminalRowDiagnostic
          | undefined;
        const omittedFailureCount = eventData['omitted_failure_count'];
        if (!diagnostic && typeof omittedFailureCount !== 'number')
          return false;
        const error: SafeTerminalDiagnostic | null = diagnostic
          ? {
              error_code: diagnostic.error_code,
              error_category: diagnostic.error_category,
              message: diagnostic.message,
            }
          : null;
        this.progress.update((p) => ({
          ...p,
          processed: p.successful + p.failed + 1,
          failed: p.failed + 1,
          currentRow: null,
          error: error ?? p.error,
          rowFailures: diagnostic
            ? [...p.rowFailures.slice(0, 19), diagnostic]
            : p.rowFailures,
          omittedFailureCount:
            typeof omittedFailureCount === 'number'
              ? Math.max(p.omittedFailureCount, omittedFailureCount)
              : p.omittedFailureCount + (p.rowFailures.length >= 20 ? 1 : 0),
        }));
        return true;
      }

      case 'batch_completed':
        this.progress.update((p) => ({
          ...p,
          status: resolveJobTerminalStatus(eventData['status'], 'complete'),
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
        return true;

      case 'batch_failed':
        this.progress.update((p) => ({
          ...p,
          status: resolveJobTerminalStatus(eventData['status'], 'failed'),
          processed: (eventData['processed'] as number) ?? p.processed,
          dutiesTaxesCents:
            (eventData['duties_taxes_cents'] as number | undefined) ??
            p.dutiesTaxesCents,
          internationalCount:
            (eventData['international_row_count'] as number | undefined) ??
            p.internationalCount,
          error:
            (eventData['diagnostic'] as SafeTerminalDiagnostic | undefined) ??
            p.error,
          currentRow: null,
        }));
        return true;

      default:
        return false;
    }
  }
}
