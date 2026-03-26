/**
 * SseService — Generic EventSource lifecycle manager.
 *
 * Wraps the browser EventSource API in an Observable-based interface with
 * proper cleanup on component/remote destroy. This service is intentionally
 * NOT providedIn: 'root' — it must be scoped to the consuming component so
 * that each component gets its own EventSource instance that is closed when
 * the component is destroyed.
 *
 * Usage:
 *   providers: [SseService]   // in component or route providers
 *   constructor(private sse: SseService) {}
 *   this.sse.connect(url).subscribe(event => { ... })
 */

import { Injectable, NgZone, OnDestroy, signal } from '@angular/core';
import { Observable } from 'rxjs';
import type { RawSseEvent, SseConfig, SseConnectionState } from './sse.models';

@Injectable()
export class SseService implements OnDestroy {
  private readonly ngZone: NgZone;

  constructor(ngZone: NgZone) {
    this.ngZone = ngZone;
  }
  /** Current connection state as a signal. */
  readonly connectionState = signal<SseConnectionState>('disconnected');

  private eventSource: EventSource | null = null;

  /**
   * Connect to an SSE endpoint and return an Observable of parsed events.
   * Automatically handles ping events (skips them). Closes any existing
   * connection before opening a new one.
   *
   * @param url The SSE endpoint URL.
   * @param _config Optional connection configuration (reserved for future use).
   * @returns Observable of RawSseEvent.
   */
  connect(url: string, _config?: SseConfig): Observable<RawSseEvent> {
    // Close any existing connection before opening a new one.
    this.disconnect();

    return new Observable<RawSseEvent>((observer) => {
      this.connectionState.set('connecting');

      const eventSource = new EventSource(url);
      this.eventSource = eventSource;

      eventSource.onopen = () => {
        this.connectionState.set('connected');
      };

      eventSource.onmessage = (event: MessageEvent) => {
        try {
          const rawData = event.data as string;

          // Skip empty/ping messages.
          if (!rawData || rawData.trim() === '') {
            return;
          }

          const parsed = JSON.parse(rawData) as unknown;

          // Determine event type from parsed data (backend sends { event, data } shape).
          let type = 'message';
          if (
            parsed !== null &&
            typeof parsed === 'object' &&
            'event' in (parsed as Record<string, unknown>)
          ) {
            const eventField = (parsed as Record<string, unknown>)['event'];
            if (typeof eventField === 'string') {
              type = eventField;
            }
          }

          // Skip keepalive ping events — they are infrastructure-only.
          if (type === 'ping') {
            return;
          }

          // Extract the inner 'data' field — backend sends { event, data } shape.
          // React useConversation.ts does `parsed.data || {}` (line 118).
          const innerData =
            parsed !== null &&
            typeof parsed === 'object' &&
            'data' in (parsed as Record<string, unknown>)
              ? (parsed as Record<string, unknown>)['data']
              : parsed;

          // Run inside NgZone so signal updates from event handlers
          // trigger Angular's change detection (OnPush + signals).
          this.ngZone.run(() => observer.next({ type, data: innerData }));
        } catch {
          // Ignore parse errors for malformed frames.
        }
      };

      eventSource.onerror = () => {
        this.ngZone.run(() => {
          if (eventSource.readyState === EventSource.CLOSED) {
            this.connectionState.set('error');
            observer.error(new Error('SSE connection closed'));
          } else if (eventSource.readyState === EventSource.CONNECTING) {
            this.connectionState.set('connecting');
          }
        });
      };

      // Teardown: called when the Observable is unsubscribed.
      return () => {
        this.disconnect();
      };
    });
  }

  /**
   * Disconnect the current EventSource connection.
   * Safe to call when no connection is active.
   */
  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      this.connectionState.set('disconnected');
    }
  }

  /** Angular lifecycle hook — ensures cleanup when the hosting component is destroyed. */
  ngOnDestroy(): void {
    this.disconnect();
  }
}
