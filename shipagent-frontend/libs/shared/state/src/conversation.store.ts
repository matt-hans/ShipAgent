/**
 * ConversationStore — Active conversation session state.
 *
 * Manages the current agent conversation session, message history,
 * interactive shipping mode, and warning preferences. The chatSessionsVersion
 * counter is a volatile signal used to trigger sidebar refreshes — it is
 * intentionally excluded from localStorage persistence.
 *
 * Persistence (via withStorageSync):
 *   - interactiveShipping → 'shipagent_conversation' key
 *   - warningPreference → 'shipagent_conversation' key
 *   - chatSessionsVersion is NOT persisted (volatile counter)
 */

import { computed } from '@angular/core';
import {
  signalStore,
  withState,
  withMethods,
  withComputed,
  patchState,
} from '@ngrx/signals';
import { withStorageSync } from '@angular-architects/ngrx-toolkit';
import type { ConversationMessage, WarningPreference } from '@shipagent/shared-types';

export interface ConversationState {
  /** The active agent session ID (null when no session exists). */
  sessionId: string | null;
  /** Ordered list of messages in the current conversation. */
  messages: ConversationMessage[];
  /** Whether the SSE stream is currently active. */
  isStreaming: boolean;
  /** A pending message to auto-inject into the chat (from sidebar). */
  pendingMessage: string;
  /** Whether interactive (single-shipment) mode is enabled. */
  interactiveShipping: boolean;
  /** How to handle rows with address warnings. */
  warningPreference: WarningPreference;
  /**
   * Volatile counter incremented whenever chat sessions change.
   * Used to trigger sidebar re-fetches. NOT persisted to localStorage.
   */
  chatSessionsVersion: number;
}

const initialState: ConversationState = {
  sessionId: null,
  messages: [],
  isStreaming: false,
  pendingMessage: '',
  interactiveShipping: false,
  warningPreference: 'ask',
  chatSessionsVersion: 0,
};

export const ConversationStore = signalStore(
  { providedIn: 'root' },
  withState<ConversationState>(initialState),
  // Persist only interactiveShipping and warningPreference — chatSessionsVersion is volatile.
  withStorageSync({
    key: 'shipagent_conversation',
    select: (state: ConversationState) => ({
      interactiveShipping: state.interactiveShipping,
      warningPreference: state.warningPreference,
    }),
  }),
  withComputed((store) => ({
    /** True when there is an active agent session. */
    hasActiveSession: computed(() => store.sessionId() !== null),
  })),
  withMethods((store) => ({
    /** Set the active session ID. */
    setSessionId(id: string | null): void {
      patchState(store, { sessionId: id });
    },

    /** Update the streaming state. */
    setStreaming(value: boolean): void {
      patchState(store, { isStreaming: value });
    },

    /** Append a single message to the conversation. */
    appendMessage(msg: ConversationMessage): void {
      patchState(store, (s) => ({ messages: [...s.messages, msg] }));
    },

    /** Replace all messages (e.g., when loading session history). */
    setMessages(msgs: ConversationMessage[]): void {
      patchState(store, { messages: msgs });
    },

    /** Clear the message history. */
    clearMessages(): void {
      patchState(store, { messages: [] });
    },

    /** Set the pending message to inject into the chat input. */
    setPendingMessage(msg: string): void {
      patchState(store, { pendingMessage: msg });
    },

    /** Toggle or set interactive shipping mode. */
    setInteractiveShipping(value: boolean): void {
      patchState(store, { interactiveShipping: value });
    },

    /** Set the warning row handling preference. */
    setWarningPreference(value: WarningPreference): void {
      patchState(store, { warningPreference: value });
    },

    /**
     * Increment the chatSessionsVersion counter.
     * Used to signal the sidebar to re-fetch the session list.
     * This counter is not persisted.
     */
    incrementChatSessionsVersion(): void {
      patchState(store, (s) => ({
        chatSessionsVersion: s.chatSessionsVersion + 1,
      }));
    },

    /** Reset session-scoped state (messages, streaming, sessionId). */
    reset(): void {
      patchState(store, {
        sessionId: null,
        messages: [],
        isStreaming: false,
        pendingMessage: '',
      });
    },
  })),
);
