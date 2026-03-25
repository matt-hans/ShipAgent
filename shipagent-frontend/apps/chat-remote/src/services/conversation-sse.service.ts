/**
 * ConversationSseService — Maps SSE events to conversation store updates.
 *
 * Consumes the agent conversation SSE stream and dispatches events to
 * the correct stores. This service is provided at component level (not root)
 * so its lifecycle is tied to the chat remote.
 *
 * SSE event mapping:
 *   agent_message        → conversationStore.appendMessage()
 *   preview_ready        → conversationStore.appendMessage() + jobStore.incrementJobListVersion()
 *   preview_partial      → skip (stability)
 *   domain events        → conversationStore.appendMessage() (as domain card messages)
 *   error                → conversationStore.appendMessage() (as error message)
 *   done                 → clear streaming + conversationStore.incrementChatSessionsVersion()
 *   ping                 → ignore (handled in SseService)
 */

import { Injectable, OnDestroy, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { SseService } from '@shipagent/shared-sse';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore, JobStore } from '@shipagent/shared-state';
import type { ConversationMessage } from '@shipagent/shared-types';

let msgCounter = 0;

/** Generate a stable unique ID for in-memory messages. */
function nextMsgId(): string {
  return `msg-${Date.now()}-${++msgCounter}`;
}

@Injectable()
export class ConversationSseService implements OnDestroy {
  private readonly sseService = inject(SseService);
  private readonly apiService = inject(ApiService);
  private readonly conversationStore = inject(ConversationStore);
  private readonly jobStore = inject(JobStore);

  private sseSubscription: Subscription | null = null;

  /**
   * Connect to the conversation SSE stream for the given session.
   * Closes any existing connection before opening a new one.
   */
  private currentSessionId: string | null = null;
  private reconnectAttempts = 0;
  private readonly MAX_RECONNECT_ATTEMPTS = 5;

  connectToStream(sessionId: string): void {
    this.disconnect();
    this.currentSessionId = sessionId;
    this.reconnectAttempts = 0;
    this.doConnect(sessionId);
  }

  private doConnect(sessionId: string): void {
    const url = this.apiService.getStreamUrl(sessionId);
    this.sseSubscription = this.sseService.connect(url).subscribe({
      next: (event) => {
        this.reconnectAttempts = 0; // Reset on successful event
        this.handleEvent(event.type, event.data);
      },
      error: (err: unknown) => {
        console.warn('[ConversationSseService] SSE error, attempting reconnect:', err);
        if (this.currentSessionId === sessionId && this.reconnectAttempts < this.MAX_RECONNECT_ATTEMPTS) {
          this.reconnectAttempts++;
          const delay = Math.min(1000 * this.reconnectAttempts, 5000);
          setTimeout(() => {
            if (this.currentSessionId === sessionId) {
              this.doConnect(sessionId);
            }
          }, delay);
        }
      },
    });
  }

  /** Disconnect the current SSE stream. */
  disconnect(): void {
    this.currentSessionId = null;
    this.sseSubscription?.unsubscribe();
    this.sseSubscription = null;
    this.sseService.disconnect();
  }

  ngOnDestroy(): void {
    this.disconnect();
  }

  // ---------------------------------------------------------------------------
  // Private event handlers
  // ---------------------------------------------------------------------------

  private handleEvent(type: string, data: unknown): void {
    const d = (data as Record<string, unknown>) ?? {};

    switch (type) {
      case 'agent_message':
        this.handleAgentMessage(d);
        break;

      case 'agent_message_delta':
        // Delta streaming — currently accumulate as separate message for simplicity.
        // TODO: In a future iteration, append to the last message in-place.
        break;

      case 'tool_call':
      case 'agent_thinking':
        // Handled by EventProcessorService for ToolCallChip display.
        break;

      case 'preview_ready':
        this.handlePreviewReady(d);
        break;

      case 'preview_partial':
        // Skip — stability improvement, avoids flickering preview cards.
        break;

      case 'pickup_preview':
      case 'pickup_result':
      case 'location_result':
      case 'landed_cost_result':
      case 'paperless_upload_prompt':
      case 'paperless_result':
      case 'tracking_result':
      case 'contact_saved':
        this.handleDomainEvent(type, d);
        break;

      case 'error':
        this.handleErrorEvent(d);
        break;

      case 'done':
        // CRITICAL: Increment chatSessionsVersion to trigger sidebar refresh.
        this.conversationStore.setStreaming(false);
        this.conversationStore.incrementChatSessionsVersion();
        break;

      default:
        // Unknown event types are silently ignored.
        break;
    }
  }

  private handleAgentMessage(data: Record<string, unknown>): void {
    // Backend sends agent text in 'text' field (see conversations.py:577).
    // Also check 'content' and 'message' for compatibility.
    const content =
      (data['text'] as string | undefined) ??
      (data['content'] as string | undefined) ??
      (data['message'] as string | undefined) ??
      '';
    if (!content) return;

    const msg: ConversationMessage = {
      id: nextMsgId(),
      role: 'assistant',
      content,
      timestamp: new Date().toISOString(),
    };
    this.conversationStore.appendMessage(msg);
  }

  private handlePreviewReady(data: Record<string, unknown>): void {
    // Store preview data as a system message with metadata so the message-list
    // can render the appropriate preview card.
    const msg: ConversationMessage = {
      id: nextMsgId(),
      role: 'system',
      content: '',
      timestamp: new Date().toISOString(),
      metadata: {
        type: 'preview_ready',
        preview: data,
      },
    };
    this.conversationStore.appendMessage(msg);
    // Trigger sidebar job list refresh.
    this.jobStore.incrementJobListVersion();
  }

  private handleDomainEvent(eventType: string, data: Record<string, unknown>): void {
    const msg: ConversationMessage = {
      id: nextMsgId(),
      role: 'system',
      content: '',
      timestamp: new Date().toISOString(),
      metadata: {
        type: 'domain_card',
        cardType: eventType,
        data,
      },
    };
    this.conversationStore.appendMessage(msg);
  }

  private handleErrorEvent(data: Record<string, unknown>): void {
    const errorMessage =
      (data['message'] as string | undefined) ??
      (data['error'] as string | undefined) ??
      'An error occurred';

    const msg: ConversationMessage = {
      id: nextMsgId(),
      role: 'system',
      content: errorMessage,
      timestamp: new Date().toISOString(),
      metadata: { type: 'error' },
    };
    this.conversationStore.appendMessage(msg);
  }
}
