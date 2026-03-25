/**
 * ConversationSessionService integration tests.
 *
 * Tests:
 *   - Mutex: concurrent ensureSession() calls result in a single API call
 *   - Generation guard: generation increments on reset/loadSession
 *   - Mode tracking: mode mismatch triggers session teardown + recreate
 *   - loadSession(): sets sessionId, loads messages, reconnects SSE
 *   - reset(): closes SSE, deletes session, clears store
 *
 * Uses plain Vitest mocks (vi.fn) — no jasmine dependency.
 */

import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi, beforeAll } from 'vitest';
import { ConversationSessionService } from './conversation-session.service';
import { ConversationSseService } from './conversation-sse.service';
import { ConversationStore } from '@shipagent/shared-state';
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

/** Creates a minimal mock ConversationSseService. */
function createMockSseService() {
  return {
    connectToStream: vi.fn(),
    disconnect: vi.fn(),
    ngOnDestroy: vi.fn(),
  };
}

/** Creates a minimal mock ApiService. */
function createMockApiService(sessionId = 'session-abc') {
  return {
    createConversation: vi.fn().mockReturnValue(
      of({ session_id: sessionId, created_at: new Date().toISOString() }),
    ),
    deleteConversation: vi.fn().mockReturnValue(of(undefined)),
    getConversationMessages: vi.fn().mockReturnValue(of({ messages: [] })),
  };
}

describe('ConversationSessionService', () => {
  let service: ConversationSessionService;
  let mockApi: ReturnType<typeof createMockApiService>;
  let mockSseService: ReturnType<typeof createMockSseService>;
  let conversationStore: InstanceType<typeof ConversationStore>;

  beforeEach(() => {
    mockApi = createMockApiService();
    mockSseService = createMockSseService();

    TestBed.configureTestingModule({
      providers: [
        ConversationSessionService,
        { provide: ApiService, useValue: mockApi },
        { provide: ConversationSseService, useValue: mockSseService },
      ],
    });

    service = TestBed.inject(ConversationSessionService);
    conversationStore = TestBed.inject(ConversationStore);
  });

  afterEach(() => {
    conversationStore.reset();
  });

  // -------------------------------------------------------------------------
  // ensureSession — basic
  // -------------------------------------------------------------------------

  describe('ensureSession()', () => {
    it('should create a new session when no session exists', async () => {
      const sessionId = await service.ensureSession(false);

      expect(sessionId).toBe('session-abc');
      expect(mockApi.createConversation).toHaveBeenCalledTimes(1);
      expect(conversationStore.sessionId()).toBe('session-abc');
    });

    it('should connect to SSE stream after session creation', async () => {
      await service.ensureSession(false);

      expect(mockSseService.connectToStream).toHaveBeenCalledWith('session-abc');
    });

    it('should reuse the existing session when mode matches', async () => {
      await service.ensureSession(false);
      vi.clearAllMocks();
      mockApi.createConversation = vi.fn().mockReturnValue(of({ session_id: 'should-not-call', created_at: '' }));

      const sessionId2 = await service.ensureSession(false);

      expect(sessionId2).toBe('session-abc');
      expect(mockApi.createConversation).not.toHaveBeenCalled();
    });

    it('should set isCreatingSession to false after creation completes', async () => {
      await service.ensureSession(false);
      expect(service.isCreatingSession()).toBe(false);
    });
  });

  // -------------------------------------------------------------------------
  // Mutex: concurrent ensureSession() calls
  // -------------------------------------------------------------------------

  describe('mutex — concurrent ensureSession()', () => {
    it('should call createConversation exactly once for concurrent calls', async () => {
      const p1 = service.ensureSession(false);
      const p2 = service.ensureSession(false);
      const p3 = service.ensureSession(false);

      const [sid1, sid2, sid3] = await Promise.all([p1, p2, p3]);

      expect(sid1).toBe('session-abc');
      expect(sid2).toBe('session-abc');
      expect(sid3).toBe('session-abc');
      expect(mockApi.createConversation).toHaveBeenCalledTimes(1);
    });
  });

  // -------------------------------------------------------------------------
  // Mode mismatch → session teardown + recreate
  // -------------------------------------------------------------------------

  describe('mode mismatch', () => {
    it('should delete old session and create a new one on mode change', async () => {
      await service.ensureSession(false);
      expect(conversationStore.sessionId()).toBe('session-abc');

      // Set up second session response
      mockApi.createConversation = vi.fn().mockReturnValue(
        of({ session_id: 'session-xyz', created_at: new Date().toISOString() }),
      );
      mockApi.deleteConversation = vi.fn().mockReturnValue(of(undefined));

      const newSid = await service.ensureSession(true);

      expect(newSid).toBe('session-xyz');
      expect(mockApi.deleteConversation).toHaveBeenCalledWith('session-abc');
      expect(conversationStore.sessionId()).toBe('session-xyz');
    });

    it('should disconnect SSE on mode mismatch', async () => {
      await service.ensureSession(false);
      mockApi.createConversation = vi.fn().mockReturnValue(
        of({ session_id: 'session-xyz', created_at: new Date().toISOString() }),
      );

      await service.ensureSession(true);

      expect(mockSseService.disconnect).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Generation guard
  // -------------------------------------------------------------------------

  describe('generation guard', () => {
    it('should start at generation 0', () => {
      expect(service.generation()).toBe(0);
    });

    it('should increment generation on startNewChat()', async () => {
      await service.startNewChat();
      expect(service.generation()).toBe(1);
    });

    it('should increment generation on reset()', async () => {
      await service.reset();
      expect(service.generation()).toBe(1);
    });

    it('should increment generation on loadSession()', async () => {
      await service.loadSession('s-1', 'batch', []);
      expect(service.generation()).toBe(1);
    });
  });

  // -------------------------------------------------------------------------
  // loadSession()
  // -------------------------------------------------------------------------

  describe('loadSession()', () => {
    it('should set the session ID in the store', async () => {
      await service.loadSession('persisted-session', 'batch', []);
      expect(conversationStore.sessionId()).toBe('persisted-session');
    });

    it('should map persisted messages to ConversationMessage format', async () => {
      const persistedMessages = [
        {
          id: 'msg-1',
          role: 'user' as const,
          content: 'Hello',
          created_at: '2026-01-01T00:00:00Z',
          metadata: null,
          message_type: 'text' as const,
          sequence: 1,
        },
        {
          id: 'msg-2',
          role: 'assistant' as const,
          content: 'Hi there',
          created_at: '2026-01-01T00:00:01Z',
          metadata: null,
          message_type: 'text' as const,
          sequence: 2,
        },
      ];

      await service.loadSession('persisted-session', 'batch', persistedMessages);

      const messages = conversationStore.messages();
      expect(messages.length).toBe(2);
      expect(messages[0].id).toBe('msg-1');
      expect(messages[0].content).toBe('Hello');
      expect(messages[1].content).toBe('Hi there');
    });

    it('should reconnect SSE after loading the session', async () => {
      await service.loadSession('persisted-session', 'batch', []);
      expect(mockSseService.connectToStream).toHaveBeenCalledWith('persisted-session');
    });

    it('should disconnect existing SSE before loading', async () => {
      await service.loadSession('persisted-session', 'batch', []);
      expect(mockSseService.disconnect).toHaveBeenCalled();
    });

    it('should set isStreaming to false', async () => {
      conversationStore.setStreaming(true);
      await service.loadSession('persisted-session', 'batch', []);
      expect(conversationStore.isStreaming()).toBe(false);
    });
  });

  // -------------------------------------------------------------------------
  // startNewChat()
  // -------------------------------------------------------------------------

  describe('startNewChat()', () => {
    it('should disconnect SSE', async () => {
      await service.startNewChat();
      expect(mockSseService.disconnect).toHaveBeenCalled();
    });

    it('should reset the conversation store', async () => {
      conversationStore.setSessionId('old-session');
      conversationStore.appendMessage({ id: 'm1', role: 'user', content: 'test', timestamp: '' });

      await service.startNewChat();

      expect(conversationStore.sessionId()).toBeNull();
      expect(conversationStore.messages().length).toBe(0);
    });

    it('should NOT call deleteConversation', async () => {
      await service.ensureSession(false);
      vi.clearAllMocks();
      mockApi.deleteConversation = vi.fn().mockReturnValue(of(undefined));

      await service.startNewChat();

      expect(mockApi.deleteConversation).not.toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // reset()
  // -------------------------------------------------------------------------

  describe('reset()', () => {
    it('should delete the current session from the API', async () => {
      await service.ensureSession(false);
      vi.clearAllMocks();
      mockApi.deleteConversation = vi.fn().mockReturnValue(of(undefined));

      await service.reset();

      expect(mockApi.deleteConversation).toHaveBeenCalledWith('session-abc');
    });

    it('should disconnect SSE', async () => {
      await service.reset();
      expect(mockSseService.disconnect).toHaveBeenCalled();
    });

    it('should reset the conversation store', async () => {
      conversationStore.setSessionId('some-session');
      await service.reset();
      expect(conversationStore.sessionId()).toBeNull();
    });

    it('should resolve without throwing when no session exists', async () => {
      await expect(service.reset()).resolves.toBeUndefined();
    });
  });
});
