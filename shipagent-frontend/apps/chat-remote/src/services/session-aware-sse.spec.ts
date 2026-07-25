import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Observable, Subject, of, throwError } from 'rxjs';
import {
  API_BASE_URL,
  ApiService,
  BrowserSessionState,
  BrowserSessionTransportService,
} from '@shipagent/shared-api';
import { JobStore } from '@shipagent/shared-state';
import { SseService } from '@shipagent/shared-sse';
import type { BrowserSessionStatus } from '@shipagent/shared-types';
import { ProgressDisplayComponent } from '../app/progress-display/progress-display.component';
import { buildJobCompletionMetadata } from './job-completion-metadata';
import { JobProgressSseService } from './job-progress-sse.service';

class ControlledEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: ControlledEventSource[] = [];

  readonly withCredentials: boolean;
  readyState = ControlledEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readonly close = vi.fn(() => {
    this.readyState = ControlledEventSource.CLOSED;
  });

  constructor(readonly url: string, init?: EventSourceInit) {
    this.withCredentials = init?.withCredentials ?? false;
    ControlledEventSource.instances.push(this);
  }

  emitOpen(): void {
    this.readyState = ControlledEventSource.OPEN;
    this.onopen?.(new Event('open'));
  }

  emitError(): void {
    this.onerror?.(new Event('error'));
  }

  emitMessage(payload: unknown): void {
    this.onmessage?.(
      new MessageEvent('message', { data: JSON.stringify(payload) })
    );
  }
}

describe('session-aware EventSource transports', () => {
  let sessionStatus: BrowserSessionStatus;
  let apiMock: {
    getBrowserSessionStatus: ReturnType<typeof vi.fn>;
    getJobProgress: ReturnType<typeof vi.fn>;
    getJobProgressUrl: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    ControlledEventSource.instances = [];
    vi.stubGlobal(
      'EventSource',
      ControlledEventSource as unknown as typeof EventSource
    );
    sessionStatus = {
      required: true,
      authenticated: false,
      csrf_token: null,
    };
    apiMock = {
      getBrowserSessionStatus: vi
        .fn()
        .mockImplementation(() => of(sessionStatus)),
      getJobProgress: vi.fn().mockReturnValue(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 2,
          processed_rows: 0,
          successful_rows: 0,
          failed_rows: 0,
          total_cost_cents: 0,
        })
      ),
      getJobProgressUrl: vi
        .fn()
        .mockImplementation(
          (jobId: string) => `/api/v1/jobs/${jobId}/progress/stream`
        ),
    };

    TestBed.configureTestingModule({
      imports: [ProgressDisplayComponent],
      providers: [
        SseService,
        JobProgressSseService,
        BrowserSessionTransportService,
        { provide: API_BASE_URL, useValue: signal('/api/v1') },
        { provide: ApiService, useValue: apiMock },
        {
          provide: JobStore,
          useValue: { incrementJobListVersion: vi.fn() },
        },
      ],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('closes and completes shared SSE after one confirmed expiry check', async () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    const sse = TestBed.inject(SseService);
    const errors: unknown[] = [];
    let completions = 0;
    sse.connect('/api/v1/conversations/session-1/stream').subscribe({
      error: (error: unknown) => errors.push(error),
      complete: () => completions++,
    });

    const source = ControlledEventSource.instances[0];
    expect(source.withCredentials).toBe(true);
    source.emitError();

    await vi.waitFor(() => {
      expect(browserSession.expirationVersion()).toBe(1);
      expect(completions).toBe(1);
    });
    source.emitError();
    await Promise.resolve();

    expect(source.close).toHaveBeenCalledTimes(1);
    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(ControlledEventSource.instances).toHaveLength(1);
    expect(errors).toEqual([]);
  });

  it('emits one ordinary shared SSE error when authentication remains valid', async () => {
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const browserSession = TestBed.inject(BrowserSessionState);
    const sse = TestBed.inject(SseService);
    const errors: unknown[] = [];
    sse.connect('/api/v1/conversations/session-1/stream').subscribe({
      error: (error: unknown) => errors.push(error),
    });

    const source = ControlledEventSource.instances[0];
    source.emitError();

    await vi.waitFor(() => {
      expect(errors).toHaveLength(1);
    });
    source.emitError();
    await Promise.resolve();

    expect(source.close).toHaveBeenCalledTimes(1);
    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(browserSession.expirationVersion()).toBe(0);
  });

  it('cancels a delayed old-stream session check before a replacement can be re-authenticated', async () => {
    let deliverOldStatus: (status: BrowserSessionStatus) => void = () =>
      undefined;
    let oldStatusCheckCancelled = false;
    apiMock.getBrowserSessionStatus.mockReturnValue(
      new Observable<BrowserSessionStatus>((subscriber) => {
        deliverOldStatus = (status) => {
          subscriber.next(status);
          subscriber.complete();
        };
        return () => {
          oldStatusCheckCancelled = true;
        };
      })
    );
    const browserSession = TestBed.inject(BrowserSessionState);
    const sse = TestBed.inject(SseService);
    const oldSubscription = sse
      .connect('/api/v1/conversations/old/stream')
      .subscribe();

    ControlledEventSource.instances[0].emitError();
    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);

    const replacementSubscription = sse
      .connect('/api/v1/conversations/new/stream')
      .subscribe();
    expect(oldStatusCheckCancelled).toBe(true);

    browserSession.markExpired();
    browserSession.applySessionStatus({
      required: true,
      authenticated: true,
      csrf_token: 'v1.new-session',
    });
    const expirationAfterReauthentication = browserSession.expirationVersion();

    deliverOldStatus({
      required: true,
      authenticated: false,
      csrf_token: null,
    });
    await Promise.resolve();

    expect(browserSession.csrfToken()).toBe('v1.new-session');
    expect(browserSession.expirationVersion()).toBe(
      expirationAfterReauthentication
    );

    oldSubscription.unsubscribe();
    replacementSubscription.unsubscribe();
  });

  it.each(['unsubscribe', 'disconnect', 'destroy'] as const)(
    'cancels a delayed shared SSE session check on %s',
    async (lifecycleAction) => {
      let deliverOldStatus: (status: BrowserSessionStatus) => void = () =>
        undefined;
      let statusCheckCancelled = false;
      apiMock.getBrowserSessionStatus.mockReturnValue(
        new Observable<BrowserSessionStatus>((subscriber) => {
          deliverOldStatus = (status) => {
            subscriber.next(status);
            subscriber.complete();
          };
          return () => {
            statusCheckCancelled = true;
          };
        })
      );
      const browserSession = TestBed.inject(BrowserSessionState);
      const sse = TestBed.inject(SseService);
      const subscription = sse
        .connect('/api/v1/conversations/old/stream')
        .subscribe();
      ControlledEventSource.instances[0].emitError();

      if (lifecycleAction === 'unsubscribe') {
        subscription.unsubscribe();
      } else if (lifecycleAction === 'disconnect') {
        sse.disconnect();
      } else {
        sse.ngOnDestroy();
      }
      expect(statusCheckCancelled).toBe(true);

      browserSession.applySessionStatus({
        required: true,
        authenticated: true,
        csrf_token: 'v1.current-session',
      });
      const currentExpiration = browserSession.expirationVersion();
      deliverOldStatus({
        required: true,
        authenticated: false,
        csrf_token: null,
      });
      await Promise.resolve();

      expect(browserSession.csrfToken()).toBe('v1.current-session');
      expect(browserSession.expirationVersion()).toBe(currentExpiration);
      subscription.unsubscribe();
    }
  );

  it('ignores callbacks from a replaced shared SSE generation', () => {
    const sse = TestBed.inject(SseService);
    const staleEvents: unknown[] = [];
    const currentEvents: unknown[] = [];
    const staleSubscription = sse
      .connect('/api/v1/conversations/old/stream')
      .subscribe((event) => staleEvents.push(event));
    const staleSource = ControlledEventSource.instances[0];

    const currentSubscription = sse
      .connect('/api/v1/conversations/new/stream')
      .subscribe((event) => currentEvents.push(event));
    const currentSource = ControlledEventSource.instances[1];

    staleSource.emitOpen();
    staleSource.emitMessage({ event: 'delta', data: { stale: true } });
    expect(sse.connectionState()).toBe('connecting');
    expect(staleEvents).toEqual([]);

    currentSource.emitOpen();
    currentSource.emitMessage({ event: 'delta', data: { current: true } });
    expect(sse.connectionState()).toBe('connected');
    expect(currentEvents).toEqual([{ type: 'delta', data: { current: true } }]);

    staleSubscription.unsubscribe();
    currentSubscription.unsubscribe();
  });

  it('applies the same one-check expiry guard to job progress SSE', async () => {
    const browserSession = TestBed.inject(BrowserSessionState);
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    const source = ControlledEventSource.instances[0];
    expect(source.withCredentials).toBe(true);
    source.emitError();

    await vi.waitFor(() => {
      expect(browserSession.expirationVersion()).toBe(1);
    });
    source.emitError();
    await Promise.resolve();

    expect(source.close).toHaveBeenCalledTimes(1);
    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(1);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });

  it('refreshes the progress snapshot before reconnecting once after an authenticated transient error', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    ControlledEventSource.instances[0].emitError();
    await vi.runAllTimersAsync();
    ControlledEventSource.instances[1].emitOpen();
    await vi.advanceTimersByTimeAsync(0);

    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(3);
    expect(ControlledEventSource.instances).toHaveLength(2);
    expect(ControlledEventSource.instances[0].close).toHaveBeenCalledTimes(1);
    expect(ControlledEventSource.instances[1].url).toBe(
      '/api/v1/jobs/job-1/progress/stream'
    );
  });

  it('conservatively refreshes and reconnects when session status is transiently unavailable', async () => {
    vi.useFakeTimers();
    apiMock.getBrowserSessionStatus.mockReturnValue(
      throwError(() => new Error('temporary status outage'))
    );
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    ControlledEventSource.instances[0].emitError();
    await vi.runAllTimersAsync();
    ControlledEventSource.instances[1].emitOpen();
    await vi.advanceTimersByTimeAsync(0);

    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(3);
    expect(ControlledEventSource.instances).toHaveLength(2);
  });

  it('emits warning metadata from an initial completed-with-warnings snapshot without opening a stream', async () => {
    apiMock.getJobProgress.mockReturnValue(
      of({
        job_id: 'job-1',
        status: 'completed_with_warnings',
        total_rows: 2,
        processed_rows: 2,
        successful_rows: 2,
        failed_rows: 0,
        total_cost_cents: 2400,
      })
    );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const completed = vi.fn();
    fixture.componentInstance.complete.subscribe(completed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.waitFor(() => {
      expect(completed).toHaveBeenCalledTimes(1);
    });

    expect(completed).toHaveBeenCalledWith({
      status: 'completed_with_warnings',
      outcome: 'complete',
      hasWarnings: true,
      cancelled: false,
      message: 'Batch completed with warnings.',
    });
    expect(ControlledEventSource.instances).toHaveLength(0);
  });

  it('emits warning metadata and stops recovery for a live completed-with-warnings frame', async () => {
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const completed = vi.fn();
    fixture.componentInstance.complete.subscribe(completed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.waitFor(() => {
      expect(ControlledEventSource.instances).toHaveLength(1);
    });
    const source = ControlledEventSource.instances[0];

    source.emitMessage({
      event: 'batch_completed',
      data: {
        job_id: 'job-1',
        status: 'completed_with_warnings',
        total_rows: 2,
        successful: 2,
        total_cost_cents: 2400,
      },
    });
    await vi.waitFor(() => {
      expect(completed).toHaveBeenCalledTimes(1);
    });

    expect(completed).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'completed_with_warnings',
        outcome: 'complete',
        hasWarnings: true,
      })
    );
    expect(source.close).toHaveBeenCalledTimes(1);

    source.emitError();
    await Promise.resolve();
    expect(apiMock.getBrowserSessionStatus).not.toHaveBeenCalled();
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(1);
  });

  it('emits warning metadata from a missed completed-with-warnings recovery snapshot', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    apiMock.getJobProgress
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 2,
          processed_rows: 1,
          successful_rows: 1,
          failed_rows: 0,
          total_cost_cents: 1200,
        })
      )
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'completed_with_warnings',
          total_rows: 2,
          processed_rows: 2,
          successful_rows: 2,
          failed_rows: 0,
          total_cost_cents: 2400,
        })
      );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const completed = vi.fn();
    fixture.componentInstance.complete.subscribe(completed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);

    ControlledEventSource.instances[0].emitError();
    await vi.runAllTimersAsync();

    expect(completed).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'completed_with_warnings',
        hasWarnings: true,
      })
    );
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });

  it('emits cancellation metadata from an initial cancelled snapshot without opening a stream', async () => {
    apiMock.getJobProgress.mockReturnValue(
      of({
        job_id: 'job-1',
        status: 'cancelled',
        total_rows: 2,
        processed_rows: 0,
        successful_rows: 0,
        failed_rows: 0,
        total_cost_cents: 0,
      })
    );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const failed = vi.fn();
    fixture.componentInstance.failed.subscribe(failed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.waitFor(() => {
      expect(failed).toHaveBeenCalledTimes(1);
    });

    expect(failed).toHaveBeenCalledWith({
      status: 'cancelled',
      outcome: 'failed',
      hasWarnings: false,
      cancelled: true,
      message: 'Batch cancelled. You can enter a new command.',
    });
    expect(ControlledEventSource.instances).toHaveLength(0);
  });

  it('emits cancellation metadata and stops recovery for a live cancelled frame', async () => {
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const failed = vi.fn();
    fixture.componentInstance.failed.subscribe(failed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.waitFor(() => {
      expect(ControlledEventSource.instances).toHaveLength(1);
    });
    const source = ControlledEventSource.instances[0];

    source.emitMessage({
      event: 'batch_failed',
      data: {
        job_id: 'job-1',
        status: 'cancelled',
        error_code: 'E-CANCELLED',
        error_message: 'Batch cancelled.',
        processed: 0,
      },
    });
    await vi.waitFor(() => {
      expect(failed).toHaveBeenCalledTimes(1);
    });

    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'cancelled',
        outcome: 'failed',
        cancelled: true,
      })
    );
    expect(source.close).toHaveBeenCalledTimes(1);

    source.emitError();
    await Promise.resolve();
    expect(apiMock.getBrowserSessionStatus).not.toHaveBeenCalled();
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(1);
  });

  it('emits cancellation metadata from a missed cancelled recovery snapshot', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    apiMock.getJobProgress
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 2,
          processed_rows: 0,
          successful_rows: 0,
          failed_rows: 0,
          total_cost_cents: 0,
        })
      )
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'cancelled',
          total_rows: 2,
          processed_rows: 0,
          successful_rows: 0,
          failed_rows: 0,
          total_cost_cents: 0,
        })
      );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const failed = vi.fn();
    fixture.componentInstance.failed.subscribe(failed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);

    ControlledEventSource.instances[0].emitError();
    await vi.runAllTimersAsync();

    expect(failed).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'cancelled',
        cancelled: true,
      })
    );
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });

  it.each([
    [
      'completed_with_warnings',
      {
        outcome: 'complete',
        hasWarnings: true,
        cancelled: false,
        statusMessage: 'Batch completed with warnings.',
      },
    ],
    [
      'cancelled',
      {
        outcome: 'failed',
        hasWarnings: false,
        cancelled: true,
        statusMessage: 'Batch cancelled. You can enter a new command.',
      },
    ],
  ] as const)(
    'persists explicit terminal metadata for %s component output',
    (status, expected) => {
      const metadata = buildJobCompletionMetadata('job-1', {
        total: 2,
        processed: 2,
        successful: status === 'cancelled' ? 0 : 2,
        failed: 0,
        totalCostCents: status === 'cancelled' ? 0 : 2400,
        dutiesTaxesCents: undefined,
        internationalCount: undefined,
        status,
        error: null,
        rowFailures: [],
        currentRow: null,
        lastTrackingNumber: null,
      });

      expect(metadata['completion']).toMatchObject({
        status,
        ...expected,
      });
    }
  );

  it('emits completion from a missed terminal snapshot without reopening the stream', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    apiMock.getJobProgress
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 2,
          processed_rows: 1,
          successful_rows: 1,
          failed_rows: 0,
          total_cost_cents: 1200,
        })
      )
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'completed',
          total_rows: 2,
          processed_rows: 2,
          successful_rows: 2,
          failed_rows: 0,
          total_cost_cents: 2400,
        })
      );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const completed = vi.fn();
    fixture.componentInstance.complete.subscribe(completed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);

    ControlledEventSource.instances[0].emitError();
    await vi.runAllTimersAsync();
    fixture.detectChanges();

    expect(fixture.componentInstance.progressService.progress().status).toBe(
      'completed'
    );
    expect(completed).toHaveBeenCalledTimes(1);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });

  it('emits failure from a missed terminal snapshot without reopening the stream', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    apiMock.getJobProgress
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 2,
          processed_rows: 1,
          successful_rows: 1,
          failed_rows: 0,
          total_cost_cents: 1200,
        })
      )
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'failed',
          total_rows: 2,
          processed_rows: 1,
          successful_rows: 1,
          failed_rows: 1,
          total_cost_cents: 1200,
        })
      );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const failed = vi.fn();
    fixture.componentInstance.failed.subscribe(failed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);

    ControlledEventSource.instances[0].emitError();
    await vi.runAllTimersAsync();
    fixture.detectChanges();

    expect(fixture.componentInstance.progressService.progress().status).toBe(
      'failed'
    );
    expect(failed).toHaveBeenCalledTimes(1);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });

  it('reconciles terminal progress after the replacement stream subscribes', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const runningSnapshot = {
      job_id: 'job-1',
      status: 'running',
      total_rows: 2,
      processed_rows: 1,
      successful_rows: 1,
      failed_rows: 0,
      total_cost_cents: 1200,
    };
    apiMock.getJobProgress
      .mockReturnValueOnce(of(runningSnapshot))
      .mockReturnValueOnce(of(runningSnapshot))
      .mockImplementationOnce(() => {
        expect(ControlledEventSource.instances).toHaveLength(2);
        return of({
          job_id: 'job-1',
          status: 'completed',
          total_rows: 2,
          processed_rows: 2,
          successful_rows: 2,
          failed_rows: 0,
          total_cost_cents: 2400,
        });
      });
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    const completed = vi.fn();
    fixture.componentInstance.complete.subscribe(completed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);

    ControlledEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(0);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
    expect(ControlledEventSource.instances).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(250);
    fixture.detectChanges();

    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
    expect(ControlledEventSource.instances).toHaveLength(2);

    ControlledEventSource.instances[1].emitOpen();
    ControlledEventSource.instances[1].emitOpen();
    await vi.advanceTimersByTimeAsync(0);
    fixture.detectChanges();

    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(3);
    expect(ControlledEventSource.instances[1].close).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.progressService.progress().status).toBe(
      'completed'
    );
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('does not let stale post-subscription reconciliation override a newer frame', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const runningSnapshot = {
      job_id: 'job-1',
      status: 'running',
      total_rows: 2,
      processed_rows: 1,
      successful_rows: 1,
      failed_rows: 0,
      total_cost_cents: 1200,
    };
    const reconciliation = new Subject<typeof runningSnapshot>();
    apiMock.getJobProgress
      .mockReturnValueOnce(of(runningSnapshot))
      .mockReturnValueOnce(of(runningSnapshot))
      .mockReturnValueOnce(reconciliation);
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    ControlledEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(250);
    expect(ControlledEventSource.instances).toHaveLength(2);

    ControlledEventSource.instances[1].emitOpen();
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(3);
    ControlledEventSource.instances[1].emitMessage({
      event: 'row_completed',
      data: {
        job_id: 'job-1',
        row_number: 2,
        tracking_number: '1Z-CURRENT',
        cost_cents: 1300,
      },
    });
    reconciliation.next(runningSnapshot);
    reconciliation.complete();
    await Promise.resolve();

    expect(progress.progress().processed).toBe(2);
    expect(progress.progress().successful).toBe(2);
    expect(progress.progress().totalCostCents).toBe(2500);
    expect(progress.progress().lastTrackingNumber).toBe('1Z-CURRENT');
  });

  it('preserves event-only diagnostics through running and failed recovery snapshots', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    apiMock.getJobProgress
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 4,
          processed_rows: 0,
          successful_rows: 0,
          failed_rows: 0,
          total_cost_cents: 0,
        })
      )
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 4,
          processed_rows: 2,
          successful_rows: 1,
          failed_rows: 1,
          total_cost_cents: 1300,
        })
      )
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'failed',
          total_rows: 4,
          processed_rows: 3,
          successful_rows: 1,
          failed_rows: 2,
          total_cost_cents: 1300,
        })
      );
    const fixture = TestBed.createComponent(ProgressDisplayComponent);
    let emittedMetadata: Record<string, unknown> | undefined;
    const failed = vi.fn(() => {
      emittedMetadata = buildJobCompletionMetadata(
        'job-1',
        fixture.componentInstance.progressService.progress()
      );
    });
    fixture.componentInstance.failed.subscribe(failed);
    fixture.componentRef.setInput('jobId', 'job-1');
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(0);
    const source = ControlledEventSource.instances[0];

    source.emitMessage({
      event: 'row_completed',
      data: {
        job_id: 'job-1',
        row_number: 1,
        tracking_number: '1Z-PRIOR',
        cost_cents: 1300,
      },
    });
    source.emitMessage({
      event: 'row_failed',
      data: {
        job_id: 'job-1',
        row_number: 2,
        error_code: 'E-ROW',
        error_message: 'Recipient review required',
      },
    });
    source.emitMessage({
      event: 'row_started',
      data: { job_id: 'job-1', row_number: 3 },
    });
    source.emitError();
    await vi.runAllTimersAsync();
    ControlledEventSource.instances[1].emitOpen();
    await vi.advanceTimersByTimeAsync(0);
    fixture.detectChanges();

    expect(fixture.componentInstance.progressService.progress()).toEqual({
      total: 4,
      processed: 3,
      successful: 1,
      failed: 2,
      totalCostCents: 1300,
      dutiesTaxesCents: undefined,
      internationalCount: undefined,
      status: 'failed',
      error: {
        code: 'E-ROW',
        message: 'Recipient review required',
      },
      rowFailures: [
        {
          rowNumber: 2,
          errorCode: 'E-ROW',
          errorMessage: 'Recipient review required',
        },
      ],
      currentRow: 3,
      lastTrackingNumber: '1Z-PRIOR',
    });
    expect(failed).toHaveBeenCalledTimes(1);
    expect(emittedMetadata).toMatchObject({
      type: 'completion',
      jobId: 'job-1',
      completion: {
        error: {
          code: 'E-ROW',
          message: 'Recipient review required',
        },
        rowFailures: [
          {
            rowNumber: 2,
            errorCode: 'E-ROW',
            errorMessage: 'Recipient review required',
          },
        ],
        currentRow: 3,
        lastTrackingNumber: '1Z-PRIOR',
      },
    });
  });

  it('bounds repeated transient failures without duplicate streams or checks', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    for (let failure = 0; failure < 4; failure++) {
      const source = ControlledEventSource.instances.at(-1);
      if (!source) throw new Error('Expected an active progress stream');
      source.emitOpen();
      await vi.advanceTimersByTimeAsync(0);
      source.emitError();
      source.emitError();
      await vi.advanceTimersByTimeAsync(10_000);
    }

    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(4);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(8);
    expect(ControlledEventSource.instances).toHaveLength(4);
    expect(
      ControlledEventSource.instances.filter(
        (source) => source.readyState !== ControlledEventSource.CLOSED
      )
    ).toHaveLength(0);
  });

  it('does not reset the retry budget for repeated open then error handshakes', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    for (let failure = 0; failure < 4; failure++) {
      const source = ControlledEventSource.instances.at(-1);
      if (!source) throw new Error('Expected an active progress stream');
      source.emitOpen();
      source.emitError();
      source.emitError();
      await vi.advanceTimersByTimeAsync(10_000);
    }

    expect(ControlledEventSource.instances).toHaveLength(4);
    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(4);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(8);
    expect(vi.getTimerCount()).toBe(0);
    expect(
      ControlledEventSource.instances.filter(
        (source) => source.readyState !== ControlledEventSource.CLOSED
      )
    ).toHaveLength(0);
  });

  it('resets the retry budget after a meaningful progress frame', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');

    ControlledEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(10_000);
    ControlledEventSource.instances[1].emitError();
    await vi.advanceTimersByTimeAsync(10_000);

    ControlledEventSource.instances[2].emitMessage({
      event: 'row_started',
      data: { job_id: 'job-1', row_number: 2 },
    });
    expect(progress.progress().currentRow).toBe(2);

    ControlledEventSource.instances[2].emitError();
    await vi.advanceTimersByTimeAsync(10_000);
    ControlledEventSource.instances[3].emitError();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(ControlledEventSource.instances).toHaveLength(5);
  });

  it('cancels a stale session check when the active job changes', async () => {
    vi.useFakeTimers();
    let staleStatusCheckUnsubscribed = false;
    apiMock.getBrowserSessionStatus.mockReturnValue(
      new Observable<BrowserSessionStatus>(() => {
        return () => {
          staleStatusCheckUnsubscribed = true;
        };
      })
    );
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');
    ControlledEventSource.instances[0].emitError();

    await progress.connectToJobProgress('job-2');
    await vi.runAllTimersAsync();

    expect(staleStatusCheckUnsubscribed).toBe(true);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
    expect(ControlledEventSource.instances).toHaveLength(2);
    expect(ControlledEventSource.instances[1].url).toBe(
      '/api/v1/jobs/job-2/progress/stream'
    );
  });

  it('cancels a scheduled reconnect when the active job changes', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');
    ControlledEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1);

    await progress.connectToJobProgress('job-2');
    await vi.runAllTimersAsync();

    expect(vi.getTimerCount()).toBe(0);
    expect(ControlledEventSource.instances).toHaveLength(2);
    expect(ControlledEventSource.instances[1].url).toBe(
      '/api/v1/jobs/job-2/progress/stream'
    );
  });

  it('ignores progress events from a closed job generation', async () => {
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');
    const staleSource = ControlledEventSource.instances[0];

    await progress.connectToJobProgress('job-2');
    staleSource.emitMessage({
      event: 'batch_completed',
      data: {
        total_rows: 2,
        successful: 2,
        total_cost_cents: 2400,
      },
    });
    staleSource.emitError();
    await Promise.resolve();

    expect(progress.progress().status).toBe('running');
    expect(apiMock.getBrowserSessionStatus).not.toHaveBeenCalled();
    expect(ControlledEventSource.instances).toHaveLength(2);
  });

  it('cancels a pending recovery snapshot when destroyed', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    let staleSnapshotUnsubscribed = false;
    apiMock.getJobProgress
      .mockReturnValueOnce(
        of({
          job_id: 'job-1',
          status: 'running',
          total_rows: 2,
          processed_rows: 0,
          successful_rows: 0,
          failed_rows: 0,
          total_cost_cents: 0,
        })
      )
      .mockReturnValueOnce(
        new Observable(() => {
          return () => {
            staleSnapshotUnsubscribed = true;
          };
        })
      );
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');
    ControlledEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(0);

    progress.ngOnDestroy();
    await vi.runAllTimersAsync();

    expect(staleSnapshotUnsubscribed).toBe(true);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });

  it('cancels a scheduled reconnect when destroyed', async () => {
    vi.useFakeTimers();
    sessionStatus = {
      required: true,
      authenticated: true,
      csrf_token: 'v1.still-valid',
    };
    const progress = TestBed.inject(JobProgressSseService);
    await progress.connectToJobProgress('job-1');
    ControlledEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1);

    progress.ngOnDestroy();
    await vi.runAllTimersAsync();

    expect(vi.getTimerCount()).toBe(0);
    expect(ControlledEventSource.instances).toHaveLength(1);
  });
});
