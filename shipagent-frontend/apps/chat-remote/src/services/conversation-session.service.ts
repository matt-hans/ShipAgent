/**
 * ConversationSessionService — Session lifecycle management.
 *
 * Manages the creation, teardown, and restoration of agent conversation
 * sessions. Provides:
 *   - Mutex: prevents concurrent createConversation API calls from racing.
 *   - Generation guard: epoch counter that invalidates stale SSE events.
 *   - Mode tracking: detects interactive_shipping mode mismatches and resets.
 *
 * CRITICAL: Provided at the chat-container component level (not root) so
 * its lifecycle is tied to the chat remote's component tree.
 */

import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import { ConversationSseService } from './conversation-sse.service';
import type { PersistedMessage } from '@shipagent/shared-types';

@Injectable()
export class ConversationSessionService implements OnDestroy {
  private readonly apiService = inject(ApiService);
  private readonly conversationStore = inject(ConversationStore);
  private readonly conversationSseService = inject(ConversationSseService);

  /** Tracks the interactive_shipping mode the current session was created with. */
  private sessionMode: boolean | null = null;

  /** Mutex: serialises session creation to prevent concurrent createConversation calls. */
  private creatingSessionPromise: Promise<string> | null = null;

  /**
   * Generation counter. Incremented on reset/loadSession.
   * SSE services capture the generation at connect time; events
   * from a prior generation are discarded.
   */
  readonly generation = signal(0);

  /** Whether a session is currently being created. */
  readonly isCreatingSession = signal(false);

  ngOnDestroy(): void {
    // Close SSE but don't delete the session — it persists in the DB.
    this.conversationSseService.disconnect();
  }

  /**
   * Ensure a conversation session exists with the correct mode.
   *
   * If a session already exists with the matching mode, returns immediately.
   * On mode mismatch, tears down the old session before creating a new one.
   * Uses a promise-based mutex to prevent concurrent createConversation calls.
   */
  async ensureSession(interactiveShipping: boolean): Promise<string> {
    const currentSessionId = this.conversationStore.sessionId();

    // Reuse existing session if mode matches.
    if (currentSessionId && this.sessionMode === interactiveShipping) {
      return currentSessionId;
    }

    // Mode mismatch — tear down the old session before creating a new one.
    if (currentSessionId && this.sessionMode !== interactiveShipping) {
      const oldSid = currentSessionId;
      this.sessionMode = null;
      this.conversationStore.setSessionId(null);
      this.conversationSseService.disconnect();
      try {
        await firstValueFrom(this.apiService.deleteConversation(oldSid));
      } catch {
        // Non-critical — old session will expire on server.
      }
    }

    // If a creation is already in-flight, share that promise.
    if (this.creatingSessionPromise) {
      return this.creatingSessionPromise;
    }

    // Capture generation before the async call.
    const genAtStart = this.generation();

    const promise = (async () => {
      this.isCreatingSession.set(true);
      try {
        const resp = await firstValueFrom(
          this.apiService.createConversation({ interactive_shipping: interactiveShipping }),
        );
        const sid = resp.session_id;

        // Epoch guard: if generation advanced, a reset() fired mid-flight.
        if (this.generation() !== genAtStart) {
          try {
            await firstValueFrom(this.apiService.deleteConversation(sid));
          } catch {
            // Non-critical cleanup.
          }
          throw new Error('Session creation aborted by concurrent reset');
        }

        this.conversationStore.setSessionId(sid);
        this.sessionMode = interactiveShipping;
        this.conversationSseService.connectToStream(sid);
        return sid;
      } finally {
        this.isCreatingSession.set(false);
        this.creatingSessionPromise = null;
      }
    })();

    this.creatingSessionPromise = promise;
    return promise;
  }

  /**
   * Switch to a persisted session — close SSE, load history, reconnect stream.
   * Does NOT delete the previous session.
   */
  async loadSession(
    sessionId: string,
    mode: 'batch' | 'interactive',
    messages: PersistedMessage[],
  ): Promise<void> {
    this.conversationSseService.disconnect();
    this.generation.update((g) => g + 1);

    // Map persisted messages to ConversationMessages.
    const mapped = messages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.created_at,
      metadata: m.metadata ?? undefined,
    }));

    this.conversationStore.setMessages(mapped);
    this.conversationStore.setSessionId(sessionId);
    this.sessionMode = mode === 'interactive';
    this.conversationStore.setStreaming(false);

    this.conversationSseService.connectToStream(sessionId);
  }

  /**
   * Start a fresh chat — close SSE for current session without deleting it.
   * The old session remains in the DB and the sidebar.
   */
  async startNewChat(): Promise<void> {
    this.conversationSseService.disconnect();
    this.generation.update((g) => g + 1);
    this.creatingSessionPromise = null;
    this.sessionMode = null;
    this.conversationStore.reset();
  }

  /**
   * Full teardown — close SSE, delete current session via API, clear state.
   *
   * If a createConversation call is in-flight, the generation increment
   * causes the epoch guard to abort and delete the stale session.
   */
  async reset(): Promise<void> {
    this.generation.update((g) => g + 1);
    this.conversationSseService.disconnect();

    // Wait for any in-flight creation to settle (epoch guard will delete it).
    const inflight = this.creatingSessionPromise;
    if (inflight) {
      this.creatingSessionPromise = null;
      try {
        await inflight;
      } catch {
        // Expected — epoch guard throws on stale generation.
      }
    }

    const sid = this.conversationStore.sessionId();
    if (sid) {
      try {
        await firstValueFrom(this.apiService.deleteConversation(sid));
      } catch {
        // Non-critical.
      }
    }

    this.sessionMode = null;
    this.conversationStore.reset();
  }
}
