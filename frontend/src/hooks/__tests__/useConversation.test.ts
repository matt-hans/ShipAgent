/**
 * Regression tests for useConversation hook.
 *
 * Covers race conditions identified in PR review:
 * - P1: Toggle during in-flight createConversation (epoch guard)
 * - P1: Stale create resolution after reset
 * - P2: Mode mismatch orphan cleanup
 * - P2: Reset awaits in-flight creation
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useConversation } from '../useConversation';

// ---------- Mocks ----------

// Track every deleteConversation call for orphan detection.
const deletedSessions: string[] = [];

// Controllable createConversation: callers can resolve/reject on demand.
let createResolvers: Array<{
  resolve: (v: { session_id: string }) => void;
  reject: (e: Error) => void;
}> = [];
let createCallCount = 0;

vi.mock('@/lib/api', () => ({
  createConversation: vi.fn(
    () =>
      new Promise<{ session_id: string }>((resolve, reject) => {
        createCallCount++;
        createResolvers.push({ resolve, reject });
      }),
  ),
  sendConversationMessage: vi.fn(async () => ({ session_id: 'test' })),
  getConversationStreamUrl: vi.fn((sid: string) => `/mock-stream/${sid}`),
  deleteConversation: vi.fn(async (sid: string) => {
    deletedSessions.push(sid);
  }),
}));

// Stub EventSource so connectSSE doesn't throw.
class MockEventSource {
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  close = vi.fn();
  constructor(url: string) {
    this.url = url;
  }
}

vi.stubGlobal('EventSource', MockEventSource);

// ---------- Helpers ----------

/** Resolve the Nth createConversation call (0-indexed). */
function resolveCreate(index: number, sessionId: string) {
  const resolver = createResolvers[index];
  if (!resolver) throw new Error(`No create call at index ${index}`);
  resolver.resolve({ session_id: sessionId });
}

beforeEach(() => {
  deletedSessions.length = 0;
  createResolvers = [];
  createCallCount = 0;
  vi.clearAllMocks();
});

// ---------- Tests ----------

describe('useConversation — race safety', () => {
  describe('P1: epoch guard — reset during in-flight createConversation', () => {
    it('discards a session created after reset fires', async () => {
      const { result } = renderHook(() => useConversation());

      // 1. Start session creation (does not resolve yet).
      let sendPromise: Promise<void>;
      await act(async () => {
        sendPromise = result.current.sendMessage('hello', false);
      });

      expect(createCallCount).toBe(1);
      expect(result.current.isCreatingSession).toBe(true);

      // 2. Reset fires while createConversation is in-flight.
      //    This increments the generation counter.
      let resetPromise: Promise<void>;
      await act(async () => {
        resetPromise = result.current.reset();
      });

      // 3. Now the in-flight createConversation resolves with a session ID.
      //    The epoch guard should detect the stale generation and delete it.
      await act(async () => {
        resolveCreate(0, 'stale-session-123');
        // Let both promises settle.
        await Promise.allSettled([sendPromise!, resetPromise!]);
      });

      // The stale session must have been deleted (epoch guard cleanup).
      expect(deletedSessions).toContain('stale-session-123');
      // No session should be committed.
      expect(result.current.sessionId).toBeNull();
    });

    it('does not connect SSE for a stale session', async () => {
      const { result } = renderHook(() => useConversation());

      let sendPromise: Promise<void>;
      await act(async () => {
        sendPromise = result.current.sendMessage('hello', false);
      });

      await act(async () => {
        result.current.reset();
      });

      // Resolve stale creation.
      await act(async () => {
        resolveCreate(0, 'stale-sse-test');
        await sendPromise!.catch(() => {});
      });

      // Session was discarded — isConnected should be false.
      expect(result.current.isConnected).toBe(false);
      expect(result.current.sessionId).toBeNull();
    });
  });

  describe('P2: mode mismatch — old session cleanup', () => {
    it('deletes old session before creating one with new mode', async () => {
      const { result } = renderHook(() => useConversation());

      // 1. Create a session with interactive_shipping=false.
      let sendPromise: Promise<void>;
      await act(async () => {
        sendPromise = result.current.sendMessage('batch command', false);
      });
      await act(async () => {
        resolveCreate(0, 'old-session-batch');
        await sendPromise!;
      });

      expect(result.current.sessionId).toBe('old-session-batch');

      // 2. Send a message with interactive_shipping=true (mode mismatch).
      //    ensureSession should tear down old-session-batch first.
      await act(async () => {
        sendPromise = result.current.sendMessage('ship one box', true);
      });

      // The old session should have been deleted.
      expect(deletedSessions).toContain('old-session-batch');

      // 3. Resolve the new session creation.
      await act(async () => {
        resolveCreate(1, 'new-session-interactive');
        await sendPromise!;
      });

      expect(result.current.sessionId).toBe('new-session-interactive');
    });

    it('does not leave orphaned sessions on mode switch', async () => {
      const { result } = renderHook(() => useConversation());

      // Create session A (mode false).
      let p: Promise<void>;
      await act(async () => {
        p = result.current.sendMessage('cmd1', false);
      });
      await act(async () => {
        resolveCreate(0, 'session-A');
        await p!;
      });

      // Switch to mode true — triggers teardown of A.
      await act(async () => {
        p = result.current.sendMessage('cmd2', true);
      });
      await act(async () => {
        resolveCreate(1, 'session-B');
        await p!;
      });

      // Switch back to mode false — triggers teardown of B.
      await act(async () => {
        p = result.current.sendMessage('cmd3', false);
      });
      await act(async () => {
        resolveCreate(2, 'session-C');
        await p!;
      });

      // Both A and B should have been deleted, only C is alive.
      expect(deletedSessions).toContain('session-A');
      expect(deletedSessions).toContain('session-B');
      expect(deletedSessions).not.toContain('session-C');
      expect(result.current.sessionId).toBe('session-C');
    });
  });

  describe('reset() — in-flight creation handling', () => {
    it('awaits in-flight creation and swallows the abort error', async () => {
      const { result } = renderHook(() => useConversation());

      // Start a creation.
      let sendPromise: Promise<void>;
      await act(async () => {
        sendPromise = result.current.sendMessage('hello', false);
      });

      expect(result.current.isCreatingSession).toBe(true);

      // Reset while creation is in-flight.
      let resetSettled = false;
      let resetPromise: Promise<void>;
      await act(async () => {
        resetPromise = result.current.reset().then(() => {
          resetSettled = true;
        });
      });

      // Reset should NOT have settled yet because it's awaiting the in-flight promise.
      expect(resetSettled).toBe(false);

      // Resolve the in-flight creation — epoch guard will reject it.
      await act(async () => {
        resolveCreate(0, 'inflight-session');
        await Promise.allSettled([sendPromise!, resetPromise!]);
      });

      // Reset should now have settled.
      expect(resetSettled).toBe(true);
      // The session was cleaned up by the epoch guard.
      expect(deletedSessions).toContain('inflight-session');
      expect(result.current.sessionId).toBeNull();
    });

    it('clears isCreatingSession after in-flight promise settles', async () => {
      const { result } = renderHook(() => useConversation());

      await act(async () => {
        result.current.sendMessage('hi', false);
      });
      expect(result.current.isCreatingSession).toBe(true);

      await act(async () => {
        const p = result.current.reset();
        resolveCreate(0, 'cleared-session');
        await p;
      });

      expect(result.current.isCreatingSession).toBe(false);
    });
  });

  describe('sendMessage — error surfacing on abort', () => {
    it('surfaces an error event when ensureSession is aborted by reset', async () => {
      const { result } = renderHook(() => useConversation());

      let sendPromise: Promise<void>;
      await act(async () => {
        sendPromise = result.current.sendMessage('hello', false);
      });

      // Reset to advance generation.
      await act(async () => {
        result.current.reset();
      });

      // Resolve the stale creation.
      await act(async () => {
        resolveCreate(0, 'aborted-session');
        await sendPromise!.catch(() => {});
      });

      // An error event should have been pushed because ensureSession threw.
      const errorEvents = result.current.events.filter((e) => e.type === 'error');
      expect(errorEvents.length).toBeGreaterThanOrEqual(1);
      const errorMsg = errorEvents[0]?.data?.message as string;
      expect(errorMsg).toContain('aborted');
    });
  });

  describe('session reuse — same mode skips creation', () => {
    it('reuses existing session for same mode', async () => {
      const { result } = renderHook(() => useConversation());

      // Create initial session.
      let p: Promise<void>;
      await act(async () => {
        p = result.current.sendMessage('cmd1', false);
      });
      await act(async () => {
        resolveCreate(0, 'reuse-session');
        await p!;
      });

      // Second message with same mode — should NOT trigger createConversation.
      await act(async () => {
        await result.current.sendMessage('cmd2', false);
      });

      // Only 1 createConversation call total.
      expect(createCallCount).toBe(1);
      expect(result.current.sessionId).toBe('reuse-session');
    });
  });
});
