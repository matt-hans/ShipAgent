/**
 * Models for the SSE (Server-Sent Events) service.
 * Defines the raw event structure, connection state, and configuration options.
 */

/** Generic raw SSE event emitted by the service. */
export interface RawSseEvent {
  /** The event type as reported by the server. */
  type: string;
  /** Parsed JSON payload from the SSE data field. */
  data: unknown;
}

/** Connection lifecycle states for the EventSource. */
export type SseConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error';

/** Configuration options for the SSE connection. */
export interface SseConfig {
  /** Whether to attempt reconnection on error (default: false — EventSource reconnects natively). */
  reconnect?: boolean;
  /** Maximum number of manual reconnect attempts (default: 3). */
  maxRetries?: number;
  /** Base delay in milliseconds for exponential backoff (default: 1000). */
  baseDelay?: number;
}
