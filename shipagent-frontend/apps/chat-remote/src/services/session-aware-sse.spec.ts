import { NgZone, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import {
  API_BASE_URL,
  ApiService,
  BrowserSessionState,
  BrowserSessionTransportService,
} from '@shipagent/shared-api';
import { JobStore } from '@shipagent/shared-state';
import { SseService } from '@shipagent/shared-sse';
import type { BrowserSessionStatus } from '@shipagent/shared-types';
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
        .mockReturnValue('/api/v1/jobs/job-1/progress/stream'),
    };

    TestBed.configureTestingModule({
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
        {
          provide: NgZone,
          useValue: { run: (callback: () => unknown) => callback() },
        },
      ],
    });
  });

  afterEach(() => {
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
    expect(ControlledEventSource.instances).toHaveLength(1);
  });
});
