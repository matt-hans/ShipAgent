/**
 * Hook for managing agent-driven SSE conversation lifecycle.
 *
 * Creates a conversation session, sends messages via the REST API,
 * and listens for agent events via SSE.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import {
  createConversation,
  sendConversationMessage,
  getConversationStreamUrl,
  deleteConversation,
} from '@/lib/api';
import type { AgentEventType } from '@/types/api';

/** A single event received from the agent SSE stream. */
export interface ConversationEvent {
  id: string;
  type: AgentEventType;
  data: Record<string, unknown>;
  timestamp: Date;
}

/** Return type of the useConversation hook. */
export interface UseConversationReturn {
  /** Current session ID (null before first message). */
  sessionId: string | null;
  /** All events received in this session. */
  events: ConversationEvent[];
  /** Whether the SSE stream is connected. */
  isConnected: boolean;
  /** Whether the agent is currently processing a message. */
  isProcessing: boolean;
  /** Whether a session is currently being created (in-flight createConversation). */
  isCreatingSession: boolean;
  /** Send a user message to the agent. Creates session on first call. */
  sendMessage: (content: string, interactiveShipping?: boolean) => Promise<void>;
  /** Reset the conversation — close SSE, delete session, clear events. */
  reset: () => Promise<void>;
  /** Clear events without resetting the session. */
  clearEvents: () => void;
}

let eventCounter = 0;

/**
 * Hook that manages the full conversation lifecycle with the agent.
 *
 * On first sendMessage call, creates a conversation session and connects
 * to the SSE stream. Subsequent messages reuse the same session. Agent
 * events are accumulated in the events array for rendering.
 */
export function useConversation(): UseConversationReturn {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<ConversationEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isCreatingSession, setIsCreatingSession] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sessionGenerationRef = useRef(0);
  /** Tracks the interactive_shipping mode the current session was created with. */
  const sessionModeRef = useRef<boolean | null>(null);
  /** Mutex: serialises session creation to prevent concurrent createConversation calls. */
  const creatingSessionPromiseRef = useRef<Promise<string> | null>(null);

  // Keep ref in sync with state for use in callbacks
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  /** Connect to the SSE stream for a session. */
  const connectSSE = useCallback((sid: string) => {
    // Close existing connection if any
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const url = getConversationStreamUrl(sid);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    // Capture generation at connection time for stale-event guard
    const currentGen = sessionGenerationRef.current;

    es.onopen = () => {
      setIsConnected(true);
    };

    es.onmessage = (messageEvent) => {
      // Stale-event guard: ignore events from a previous session generation
      if (sessionGenerationRef.current !== currentGen) return;

      try {
        const parsed = JSON.parse(messageEvent.data);
        const eventType = parsed.event as AgentEventType;

        // Handle end signal
        if (eventType === 'done') {
          setIsProcessing(false);
          return;
        }

        // Skip pings
        if (eventType === 'ping') {
          return;
        }

        const newEvent: ConversationEvent = {
          id: `evt-${++eventCounter}`,
          type: eventType,
          data: parsed.data || {},
          timestamp: new Date(),
        };

        setEvents((prev) => [...prev, newEvent]);
      } catch {
        // Ignore unparseable messages
      }
    };

    es.onerror = () => {
      setIsConnected(false);
      // EventSource auto-reconnects, but mark disconnected
    };
  }, []);

  /** Ensure a session exists and SSE is connected.
   *
   * Uses a mutex (creatingSessionPromiseRef) so that concurrent callers
   * share the same in-flight createConversation request instead of racing.
   * Tracks the mode the session was created with (sessionModeRef) so that
   * a mode mismatch triggers a reset + recreation.
   */
  const ensureSession = useCallback(async (interactiveShipping: boolean): Promise<string> => {
    // If a session already exists with the correct mode, reuse it.
    if (sessionIdRef.current && sessionModeRef.current === interactiveShipping) {
      return sessionIdRef.current;
    }

    // If a creation is already in-flight, wait for it.
    if (creatingSessionPromiseRef.current) {
      return creatingSessionPromiseRef.current;
    }

    // Create session (mutex-protected).
    const promise = (async () => {
      setIsCreatingSession(true);
      try {
        const resp = await createConversation({ interactive_shipping: interactiveShipping });
        const sid = resp.session_id;
        setSessionId(sid);
        sessionIdRef.current = sid;
        sessionModeRef.current = interactiveShipping;
        connectSSE(sid);
        return sid;
      } finally {
        setIsCreatingSession(false);
        creatingSessionPromiseRef.current = null;
      }
    })();

    creatingSessionPromiseRef.current = promise;
    return promise;
  }, [connectSSE]);

  /** Send a user message to the agent. */
  const sendMessage = useCallback(async (content: string, interactiveShipping: boolean = false) => {
    if (!content.trim()) return;

    setIsProcessing(true);

    try {
      const sid = await ensureSession(interactiveShipping);
      await sendConversationMessage(sid, content);
    } catch (err) {
      // Push error event so the UI can display it
      const errorEvent: ConversationEvent = {
        id: `evt-${++eventCounter}`,
        type: 'error',
        data: { message: err instanceof Error ? err.message : 'Failed to send message' },
        timestamp: new Date(),
      };
      setEvents((prev) => [...prev, errorEvent]);
      setIsProcessing(false);
    }
  }, [ensureSession]);

  /** Reset the conversation — close SSE, delete session, clear state. */
  const reset = useCallback(async () => {
    // Increment generation to invalidate any in-flight SSE events
    sessionGenerationRef.current += 1;

    // Close SSE
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    // Delete session (best-effort)
    const sid = sessionIdRef.current;
    if (sid) {
      try {
        await deleteConversation(sid);
      } catch {
        // Non-critical — session will expire on server
      }
    }

    setSessionId(null);
    sessionIdRef.current = null;
    sessionModeRef.current = null;
    setEvents([]);
    setIsConnected(false);
    setIsProcessing(false);
  }, []);

  /** Clear transient events without resetting the session. */
  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  return {
    sessionId,
    events,
    isConnected,
    isProcessing,
    isCreatingSession,
    sendMessage,
    reset,
    clearEvents,
  };
}
