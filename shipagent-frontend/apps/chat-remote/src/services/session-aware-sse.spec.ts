import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
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

    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
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

    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(1);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(2);
    expect(ControlledEventSource.instances).toHaveLength(2);
  });

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
      source.emitError();
      source.emitError();
      await vi.advanceTimersByTimeAsync(10_000);
    }

    expect(apiMock.getBrowserSessionStatus).toHaveBeenCalledTimes(4);
    expect(apiMock.getJobProgress).toHaveBeenCalledTimes(5);
    expect(ControlledEventSource.instances).toHaveLength(4);
    expect(
      ControlledEventSource.instances.filter(
        (source) => source.readyState !== ControlledEventSource.CLOSED
      )
    ).toHaveLength(0);
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
