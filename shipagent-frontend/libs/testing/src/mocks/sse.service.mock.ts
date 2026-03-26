/**
 * SseService mock for unit tests.
 *
 * Provides a controllable Subject for simulating SSE events in tests.
 * Use emit() to push events into the stream. Use complete()/error() to
 * simulate stream end or error conditions.
 */

import { Subject, Observable } from 'rxjs';

/** Raw SSE event shape as emitted by SseService. */
export interface RawSseEvent {
  event: string;
  data: unknown;
}

/**
 * Mock SseService for unit and integration tests.
 *
 * @example
 * ```typescript
 * const mockSse = createMockSseService();
 *
 * // In your test:
 * mockSse.emit({ event: 'agent_message', data: { content: 'Hello' } });
 * mockSse.complete();
 * ```
 */
export interface MockSseService {
  /** The underlying subject — used for control. */
  readonly subject: Subject<RawSseEvent>;
  /** Connect to a conversation SSE stream (returns the observable subject). */
  connect: jasmine.Spy<(url: string) => Observable<RawSseEvent>>;
  /** Disconnect from the current SSE stream. */
  disconnect: jasmine.Spy<() => void>;
  /** Emit an event into the mock stream. */
  emit(event: RawSseEvent): void;
  /** Complete the mock stream (simulates server closing connection). */
  complete(): void;
  /** Emit an error into the mock stream. */
  error(err: unknown): void;
}

/**
 * Create a mock SseService.
 */
export function createMockSseService(): MockSseService {
  const subject = new Subject<RawSseEvent>();

  const mock: MockSseService = {
    subject,
    connect: jasmine
      .createSpy('connect')
      .and.callFake(() => subject.asObservable()),
    disconnect: jasmine.createSpy('disconnect'),
    emit: (event: RawSseEvent) => subject.next(event),
    complete: () => subject.complete(),
    error: (err: unknown) => subject.error(err),
  };

  return mock;
}
