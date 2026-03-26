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
import { EventProcessorService } from './event-processor.service';
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
  private readonly eventProcessor = inject(EventProcessorService);

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
        this.handleAgentDelta(d);
        break;

      case 'tool_call':
        this.eventProcessor.setActiveToolCall(
          (d['tool_name'] as string | undefined) ?? (d['name'] as string | undefined) ?? 'unknown',
          (d['tool_use_id'] as string | undefined) ?? (d['id'] as string | undefined) ?? '',
        );
        break;
      case 'agent_thinking':
        // Thinking events are informational — no action needed.
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
        // Reset streaming delta state.
        this.streamingMsgId = null;
        this.streamingText = '';
        // Clear any active tool call.
        this.eventProcessor.clearActiveToolCall();
        // CRITICAL: Increment chatSessionsVersion to trigger sidebar refresh.
        this.conversationStore.setStreaming(false);
        this.conversationStore.incrementChatSessionsVersion();
        break;

      default:
        // Unknown event types are silently ignored.
        break;
    }
  }

  /** ID of the current streaming message being accumulated from deltas. */
  private streamingMsgId: string | null = null;
  private streamingText = '';

  private handleAgentMessage(data: Record<string, unknown>): void {
    // Backend sends agent text in 'text' field (see conversations.py:577).
    const content =
      (data['text'] as string | undefined) ??
      (data['content'] as string | undefined) ??
      (data['message'] as string | undefined) ??
      '';
    if (!content) return;

    // If we were streaming deltas, finalize that message with the complete text.
    if (this.streamingMsgId) {
      this.updateStreamingMessage(content);
      this.streamingMsgId = null;
      this.streamingText = '';
      return;
    }

    const msg: ConversationMessage = {
      id: nextMsgId(),
      role: 'assistant',
      content,
      timestamp: new Date().toISOString(),
    };
    this.conversationStore.appendMessage(msg);
  }

  /**
   * Handle streaming text deltas — accumulate into a single assistant message.
   * Creates the message on first delta, updates in-place on subsequent deltas.
   */
  private handleAgentDelta(data: Record<string, unknown>): void {
    const text = (data['text'] as string | undefined) ?? '';
    if (!text) return;

    this.streamingText += text;

    if (!this.streamingMsgId) {
      // First delta — create the message
      this.streamingMsgId = nextMsgId();
      const msg: ConversationMessage = {
        id: this.streamingMsgId,
        role: 'assistant',
        content: this.streamingText,
        timestamp: new Date().toISOString(),
      };
      this.conversationStore.appendMessage(msg);
    } else {
      // Subsequent deltas — update the existing message in-place
      this.updateStreamingMessage(this.streamingText);
    }
  }

  /** Update the content of the current streaming message. */
  private updateStreamingMessage(content: string): void {
    if (!this.streamingMsgId) return;
    const messages = this.conversationStore.messages();
    const updated = messages.map(m =>
      m.id === this.streamingMsgId ? { ...m, content } : m
    );
    this.conversationStore.setMessages(updated);
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
