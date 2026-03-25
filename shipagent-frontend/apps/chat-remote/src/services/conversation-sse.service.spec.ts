/**
 * ConversationSseService integration tests.
 *
 * Verifies the critical SSE event → store mapping:
 *   agent_message   → message added to ConversationStore
 *   preview_ready   → preview message in ConversationStore + jobStore.jobListVersion incremented
 *   done            → streaming cleared + chatSessionsVersion incremented
 *   domain events   → domain card messages in ConversationStore
 *   error           → error message in ConversationStore
 *   ping            → ignored (no store changes)
 *
 * Uses plain Vitest mocks (vi.fn) — no jasmine dependency.
 * Uses synchronous RxJS Subject emission — no fakeAsync/zone.js/testing required.
 */

import { TestBed } from '@angular/core/testing';
import { Subject, Observable } from 'rxjs';
import { vi, beforeAll } from 'vitest';
import { ConversationSseService } from './conversation-sse.service';
import { ConversationStore, JobStore } from '@shipagent/shared-state';
import { SseService } from '@shipagent/shared-sse';
import { ApiService } from '@shipagent/shared-api';

// ---------------------------------------------------------------------------
// Node 25 localStorage shim — required for withStorageSync (ConversationStore)
// ---------------------------------------------------------------------------
class LocalStorageShim implements Storage {
  private readonly store = new Map<string, string>();
  get length(): number { return this.store.size; }
  clear(): void { this.store.clear(); }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  key(index: number): string | null {
    const keys = Array.from(this.store.keys());
    return index < keys.length ? keys[index] : null;
  }
  removeItem(key: string): void { this.store.delete(key); }
  setItem(key: string, value: string): void { this.store.set(key, value); }
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: new LocalStorageShim(),
    writable: true,
    configurable: true,
  });
});

/** Minimal shape matching what ConversationSseService reads from SseService events. */
interface SseEvent {
  type: string;
  data: unknown;
}

/**
 * Creates a controllable mock SseService backed by a Subject.
 * emit(type, data) synchronously pushes an event into the stream —
 * RxJS Subject is synchronous by default, so no async/tick needed.
 */
function createSseMock() {
  const subject = new Subject<SseEvent>();
  const mock = {
    subject,
    connect: vi.fn((): Observable<SseEvent> => subject.asObservable()),
    disconnect: vi.fn(),
    emit: (type: string, data: unknown) => subject.next({ type, data }),
  };
  return mock;
}

/** Creates a minimal mock ApiService. */
function createApiMock() {
  return {
    getStreamUrl: vi.fn((sessionId: string) => `/api/v1/conversations/${sessionId}/stream`),
  };
}

describe('ConversationSseService — SSE → store mapping', () => {
  let service: ConversationSseService;
  let sseMock: ReturnType<typeof createSseMock>;
  let conversationStore: InstanceType<typeof ConversationStore>;
  let jobStore: InstanceType<typeof JobStore>;

  beforeEach(() => {
    sseMock = createSseMock();
    const apiMock = createApiMock();

    TestBed.configureTestingModule({
      providers: [
        ConversationSseService,
        { provide: SseService, useValue: sseMock },
        { provide: ApiService, useValue: apiMock },
      ],
    });

    service = TestBed.inject(ConversationSseService);
    conversationStore = TestBed.inject(ConversationStore);
    jobStore = TestBed.inject(JobStore);

    // Connect to the stream — this subscribes the service to sseMock.subject
    service.connectToStream('test-session');
  });

  afterEach(() => {
    service.disconnect();
  });

  // -------------------------------------------------------------------------
  // agent_message
  // -------------------------------------------------------------------------

  describe('agent_message event', () => {
    it('should append an assistant message to ConversationStore', () => {
      const countBefore = conversationStore.messages().length;

      // RxJS Subject.next() is synchronous — no await/tick needed
      sseMock.emit('agent_message', { content: 'Hello from the agent' });

      const messages = conversationStore.messages();
      expect(messages.length).toBe(countBefore + 1);
      const last = messages[messages.length - 1];
      expect(last.role).toBe('assistant');
      expect(last.content).toBe('Hello from the agent');
    });

    it('should accept the "message" field as content fallback', () => {
      sseMock.emit('agent_message', { message: 'Fallback content' });

      const messages = conversationStore.messages();
      const last = messages[messages.length - 1];
      expect(last.content).toBe('Fallback content');
    });

    it('should ignore agent_message with empty content', () => {
      const countBefore = conversationStore.messages().length;

      sseMock.emit('agent_message', { content: '' });

      expect(conversationStore.messages().length).toBe(countBefore);
    });
  });

  // -------------------------------------------------------------------------
  // preview_ready
  // -------------------------------------------------------------------------

  describe('preview_ready event', () => {
    it('should append a system preview message to ConversationStore', () => {
      const countBefore = conversationStore.messages().length;

      sseMock.emit('preview_ready', { job_id: 'job-123', preview: { rows: [] } });

      const messages = conversationStore.messages();
      expect(messages.length).toBe(countBefore + 1);
      const last = messages[messages.length - 1];
      expect(last.role).toBe('system');
      expect(last.metadata?.['type']).toBe('preview_ready');
    });

    it('should increment jobStore.jobListVersion on preview_ready', () => {
      const versionBefore = jobStore.jobListVersion();

      sseMock.emit('preview_ready', { job_id: 'job-123' });

      expect(jobStore.jobListVersion()).toBe(versionBefore + 1);
    });

    it('should include the raw preview data in the message metadata', () => {
      const previewData = { job_id: 'job-123', total_rows: 5 };

      sseMock.emit('preview_ready', previewData);

      const messages = conversationStore.messages();
      const last = messages[messages.length - 1];
      expect(last.metadata?.['preview']).toEqual(previewData);
    });
  });

  // -------------------------------------------------------------------------
  // done
  // -------------------------------------------------------------------------

  describe('done event', () => {
    it('should set isStreaming to false', () => {
      conversationStore.setStreaming(true);
      expect(conversationStore.isStreaming()).toBe(true);

      sseMock.emit('done', {});

      expect(conversationStore.isStreaming()).toBe(false);
    });

    it('should increment chatSessionsVersion', () => {
      const versionBefore = conversationStore.chatSessionsVersion();

      sseMock.emit('done', {});

      expect(conversationStore.chatSessionsVersion()).toBe(versionBefore + 1);
    });

    it('should NOT add a message for the done event', () => {
      const countBefore = conversationStore.messages().length;

      sseMock.emit('done', {});

      expect(conversationStore.messages().length).toBe(countBefore);
    });
  });

  // -------------------------------------------------------------------------
  // domain events
  // -------------------------------------------------------------------------

  describe('domain events', () => {
    const domainEventTypes = [
      'pickup_preview',
      'pickup_result',
      'location_result',
      'landed_cost_result',
      'paperless_upload_prompt',
      'paperless_result',
      'tracking_result',
      'contact_saved',
    ];

    for (const eventType of domainEventTypes) {
      it(`should append a domain_card message for "${eventType}"`, () => {
        const countBefore = conversationStore.messages().length;

        sseMock.emit(eventType, { payload: { test: true } });

        const messages = conversationStore.messages();
        expect(messages.length).toBe(countBefore + 1);
        const last = messages[messages.length - 1];
        expect(last.role).toBe('system');
        expect(last.metadata?.['type']).toBe('domain_card');
        expect(last.metadata?.['cardType']).toBe(eventType);
      });
    }
  });

  // -------------------------------------------------------------------------
  // error
  // -------------------------------------------------------------------------

  describe('error event', () => {
    it('should append an error message with metadata.type = "error"', () => {
      const countBefore = conversationStore.messages().length;

      sseMock.emit('error', { message: 'Something went wrong' });

      const messages = conversationStore.messages();
      expect(messages.length).toBe(countBefore + 1);
      const last = messages[messages.length - 1];
      expect(last.role).toBe('system');
      expect(last.content).toBe('Something went wrong');
      expect(last.metadata?.['type']).toBe('error');
    });

    it('should fall back to "An error occurred" when message is missing', () => {
      sseMock.emit('error', {});

      const messages = conversationStore.messages();
      const last = messages[messages.length - 1];
      expect(last.content).toBe('An error occurred');
    });

    it('should accept the "error" field as the message fallback', () => {
      sseMock.emit('error', { error: 'E-1001: Source not found' });

      const messages = conversationStore.messages();
      const last = messages[messages.length - 1];
      expect(last.content).toBe('E-1001: Source not found');
    });
  });

  // -------------------------------------------------------------------------
  // ping
  // -------------------------------------------------------------------------

  describe('ping event', () => {
    it('should not modify the conversation store', () => {
      const countBefore = conversationStore.messages().length;
      const chatVersionBefore = conversationStore.chatSessionsVersion();
      const jobVersionBefore = jobStore.jobListVersion();

      sseMock.emit('ping', {});

      expect(conversationStore.messages().length).toBe(countBefore);
      expect(conversationStore.chatSessionsVersion()).toBe(chatVersionBefore);
      expect(jobStore.jobListVersion()).toBe(jobVersionBefore);
    });
  });

  // -------------------------------------------------------------------------
  // Unknown events
  // -------------------------------------------------------------------------

  describe('unknown events', () => {
    it('should silently ignore unknown event types', () => {
      const countBefore = conversationStore.messages().length;

      sseMock.emit('some_future_event', { x: 1 });

      expect(conversationStore.messages().length).toBe(countBefore);
    });
  });

  // -------------------------------------------------------------------------
  // connectToStream / disconnect
  // -------------------------------------------------------------------------

  describe('connectToStream()', () => {
    it('should call SseService.connect with the stream URL', () => {
      expect(sseMock.connect).toHaveBeenCalledWith(
        '/api/v1/conversations/test-session/stream',
      );
    });

    it('should call SseService.disconnect before reconnecting on a second call', () => {
      service.connectToStream('new-session');
      expect(sseMock.disconnect).toHaveBeenCalled();
    });
  });

  describe('disconnect()', () => {
    it('should stop processing events after disconnect()', () => {
      service.disconnect();
      const countBefore = conversationStore.messages().length;

      // Emit after disconnect — the subscription is closed, so no handler runs
      sseMock.emit('agent_message', { content: 'After disconnect' });

      expect(conversationStore.messages().length).toBe(countBefore);
    });
  });
});
