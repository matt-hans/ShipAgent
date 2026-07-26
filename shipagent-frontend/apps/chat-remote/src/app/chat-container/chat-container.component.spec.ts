import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import { SseService } from '@shipagent/shared-sse';
import { ChatActionsService } from '../../services/chat-actions.service';
import { ConversationSessionService } from '../../services/conversation-session.service';
import { ConversationSseService } from '../../services/conversation-sse.service';
import { DomainCardBridgeService } from '../../services/domain-card-bridge.service';
import { EventProcessorService } from '../../services/event-processor.service';
import type { JobProgressSnapshot } from '../../services/job-progress-sse.service';
import { ChatContainerComponent } from './chat-container.component';

class LocalStorageShim implements Storage {
  private readonly store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }

  key(index: number): string | null {
    const keys = Array.from(this.store.keys());
    return index < keys.length ? keys[index] : null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: new LocalStorageShim(),
    writable: true,
    configurable: true,
  });
});

function failedProgress(): JobProgressSnapshot {
  return {
    total: 4,
    processed: 3,
    successful: 2,
    failed: 1,
    totalCostCents: 2400,
    dutiesTaxesCents: 315,
    internationalCount: 1,
    status: 'failed',
    error: {
      error_code: 'E-4001',
      error_category: 'system',
      message: 'The row could not be processed because of a system error.',
    },
    rowFailures: [
      {
        row_number: 3,
        error_code: 'E-3003',
        error_category: 'ups_api',
        message: 'The carrier could not process this shipment.',
      },
    ],
    omittedFailureCount: 0,
    currentRow: 4,
    lastTrackingNumber: '1ZRECOVERED',
  };
}

function cancelledProgress(): JobProgressSnapshot {
  return {
    ...failedProgress(),
    status: 'cancelled',
    error: {
      error_code: 'E-4001',
      error_category: 'system',
      message: 'The row could not be processed because of a system error.',
    },
    currentRow: 2,
    lastTrackingNumber: '1ZBEFORECANCEL',
  };
}

function completedProgress(
  status: 'completed' | 'completed_with_warnings'
): JobProgressSnapshot {
  return {
    ...failedProgress(),
    processed: 4,
    successful: 4,
    failed: 0,
    status,
    error: null,
    rowFailures: [],
    currentRow: null,
    lastTrackingNumber: '1ZCOMPLETE',
  };
}

describe('ChatContainerComponent terminal artifact persistence', () => {
  let component: ChatContainerComponent;
  let apiService: {
    saveArtifact: ReturnType<typeof vi.fn>;
    sendMessage: ReturnType<typeof vi.fn>;
    getMergedLabelsUrl: ReturnType<typeof vi.fn>;
  };
  let conversationStore: InstanceType<typeof ConversationStore>;

  beforeEach(() => {
    apiService = {
      saveArtifact: vi.fn().mockReturnValue(of(undefined)),
      sendMessage: vi.fn().mockReturnValue(of(undefined)),
      getMergedLabelsUrl: vi.fn().mockReturnValue('/labels/job.pdf'),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: apiService },
        ConversationSseService,
        ConversationSessionService,
        EventProcessorService,
        ChatActionsService,
        DomainCardBridgeService,
        {
          provide: SseService,
          useValue: { connect: vi.fn(), disconnect: vi.fn() },
        },
      ],
    });

    component = TestBed.runInInjectionContext(
      () => new ChatContainerComponent()
    );
    conversationStore = TestBed.inject(ConversationStore);
    conversationStore.setSessionId('session-1');
  });

  afterEach(() => {
    conversationStore.reset();
    localStorage.clear();
    vi.restoreAllMocks();
    TestBed.resetTestingModule();
  });

  it('persists recovered failed metadata before clearing execution state', () => {
    const progress = failedProgress();
    Object.defineProperty(component, 'messageList', {
      value: {
        progressService: { progress: () => progress },
        markNeedsScroll: vi.fn(),
      },
      configurable: true,
    });
    component.executingJobId.set('job-failed');
    apiService.saveArtifact.mockImplementation(() => {
      expect(component.executingJobId()).toBe('job-failed');
      return of(undefined);
    });

    component.handleProgressFailed();

    const appended = conversationStore.messages()[0];
    expect(apiService.saveArtifact).toHaveBeenCalledWith(
      'session-1',
      '',
      appended.metadata
    );
    expect(appended.metadata).toMatchObject({
      type: 'completion',
      jobId: 'job-failed',
      completion: {
        status: 'failed',
        outcome: 'failed',
        cancelled: false,
        statusMessage: 'Batch failed.',
        error: progress.error,
        row_failures: progress.rowFailures,
        omitted_failure_count: 0,
      },
    });
    expect(component.executingJobId()).toBeNull();
  });

  it('persists recovered cancellation diagnostics and user-visible messaging', () => {
    const progress = cancelledProgress();
    Object.defineProperty(component, 'messageList', {
      value: {
        progressService: { progress: () => progress },
        markNeedsScroll: vi.fn(),
      },
      configurable: true,
    });
    component.executingJobId.set('job-cancelled');
    apiService.saveArtifact.mockImplementation(() => {
      expect(component.executingJobId()).toBe('job-cancelled');
      return of(undefined);
    });

    component.handleProgressFailed();

    const appended = conversationStore.messages()[0];
    expect(apiService.saveArtifact).toHaveBeenCalledWith(
      'session-1',
      '',
      appended.metadata
    );
    expect(appended.metadata).toMatchObject({
      type: 'completion',
      jobId: 'job-cancelled',
      completion: {
        status: 'cancelled',
        outcome: 'failed',
        cancelled: true,
        statusMessage: 'Batch cancelled. You can enter a new command.',
        error: progress.error,
        row_failures: progress.rowFailures,
        omitted_failure_count: 0,
      },
    });
    expect(component.executingJobId()).toBeNull();
  });

  it.each([
    ['completed', false, 'Batch completed.'],
    ['completed_with_warnings', true, 'Batch completed with warnings.'],
  ] as const)(
    'preserves the shared persistence path for %s',
    (status, hasWarnings, statusMessage) => {
      const progress = completedProgress(status);
      Object.defineProperty(component, 'messageList', {
        value: {
          progressService: { progress: () => progress },
          markNeedsScroll: vi.fn(),
        },
        configurable: true,
      });
      component.executingJobId.set(`job-${status}`);

      component.handleProgressComplete();

      const appended = conversationStore.messages()[0];
      expect(apiService.saveArtifact).toHaveBeenCalledWith(
        'session-1',
        '',
        appended.metadata
      );
      expect(appended.metadata).toMatchObject({
        type: 'completion',
        jobId: `job-${status}`,
        completion: {
          status,
          outcome: 'complete',
          hasWarnings,
          cancelled: false,
          statusMessage,
        },
      });
      expect(component.showLabelPreview()).toBe(true);
      expect(component.executingJobId()).toBeNull();
    }
  );

  it('clears execution state without logging sensitive persistence errors', () => {
    const progress = failedProgress();
    const sensitiveError =
      'Bearer private-token for recipient row and 1ZPRIVATE';
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    apiService.saveArtifact.mockReturnValue(
      throwError(() => new Error(sensitiveError))
    );
    Object.defineProperty(component, 'messageList', {
      value: {
        progressService: { progress: () => progress },
        markNeedsScroll: vi.fn(),
      },
      configurable: true,
    });
    component.executingJobId.set('job-persist-error');

    component.handleProgressFailed();

    expect(conversationStore.messages()).toHaveLength(1);
    expect(component.executingJobId()).toBeNull();
    expect(warn).toHaveBeenCalledWith('Failed to persist terminal artifact.');
    expect(JSON.stringify(warn.mock.calls)).not.toContain(sensitiveError);
    expect(JSON.stringify(warn.mock.calls)).not.toContain('1ZPRIVATE');
  });
});
