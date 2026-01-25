/**
 * React hook for consuming Server-Sent Events.
 *
 * Creates an EventSource connection and provides parsed events,
 * connection status, and error handling.
 */

import { useEffect, useState, useCallback, useRef } from 'react';

/** Generic SSE event structure. */
export interface SSEEvent<T = unknown> {
  event: string;
  data: T;
}

/** State returned by the useSSE hook. */
export interface SSEState<T> {
  /** The most recent event received. */
  lastEvent: SSEEvent<T> | null;
  /** Array of all events received since connection. */
  events: SSEEvent<T>[];
  /** Whether the connection is currently open. */
  isConnected: boolean;
  /** Any error that occurred. */
  error: Error | null;
  /** Manually close the connection. */
  disconnect: () => void;
  /** Clear accumulated events. */
  clearEvents: () => void;
}

/**
 * Hook for consuming Server-Sent Events.
 *
 * @param url - The SSE endpoint URL, or null to disable.
 * @returns SSE state including events, connection status, and controls.
 *
 * @example
 * ```tsx
 * const { lastEvent, isConnected, error } = useSSE<ProgressEvent>(
 *   jobId ? `/api/v1/jobs/${jobId}/progress/stream` : null
 * );
 *
 * useEffect(() => {
 *   if (lastEvent?.event === 'row_completed') {
 *     console.log('Row completed:', lastEvent.data);
 *   }
 * }, [lastEvent]);
 * ```
 */
export function useSSE<T = unknown>(url: string | null): SSEState<T> {
  const [lastEvent, setLastEvent] = useState<SSEEvent<T> | null>(null);
  const [events, setEvents] = useState<SSEEvent<T>[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    }
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
    setLastEvent(null);
  }, []);

  useEffect(() => {
    // Don't connect if no URL provided
    if (!url) {
      disconnect();
      return;
    }

    // Close any existing connection
    disconnect();

    // Reset state for new connection
    setError(null);
    setLastEvent(null);
    setEvents([]);

    // Create new EventSource
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    // Handle connection open
    eventSource.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    // Handle messages
    // EventSource with named events sends them to specific listeners,
    // but for generic handling we need to listen to each event type.
    // Since we don't know event names in advance, we use the generic handler.
    eventSource.onmessage = (messageEvent) => {
      try {
        // Parse the event data
        const rawData = messageEvent.data;
        // The data might be JSON or empty (for pings)
        let parsedData: T;
        if (rawData && rawData !== '') {
          parsedData = JSON.parse(rawData);
        } else {
          parsedData = '' as T;
        }

        // Determine event type from the parsed data or default
        // Our backend sends { event: string, data: {...} } format
        const eventType =
          typeof parsedData === 'object' &&
          parsedData !== null &&
          'event' in parsedData
            ? (parsedData as { event: string }).event
            : 'message';

        const sseEvent: SSEEvent<T> = {
          event: eventType,
          data: parsedData,
        };

        setLastEvent(sseEvent);
        setEvents((prev) => [...prev, sseEvent]);
      } catch (parseError) {
        console.error('Failed to parse SSE event:', parseError);
      }
    };

    // Handle errors
    eventSource.onerror = (errorEvent) => {
      // EventSource automatically reconnects on error
      // We only set error state but keep isConnected based on readyState
      if (eventSource.readyState === EventSource.CLOSED) {
        setIsConnected(false);
        setError(new Error('SSE connection closed'));
      } else if (eventSource.readyState === EventSource.CONNECTING) {
        // Reconnecting, not a permanent error
        console.warn('SSE reconnecting...', errorEvent);
      }
    };

    // Cleanup on unmount or URL change
    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [url, disconnect]);

  return {
    lastEvent,
    events,
    isConnected,
    error,
    disconnect,
    clearEvents,
  };
}

export default useSSE;
