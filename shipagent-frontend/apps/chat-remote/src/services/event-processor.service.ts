/**
 * EventProcessorService — Tracks active tool calls for ToolCallChip display.
 *
 * Maintains the currently active tool call signal extracted from SSE events.
 * Chat-container subscribes to conversation SSE events and calls into this
 * service to update the active tool state.
 *
 * Provided at component level (not root).
 */

import { Injectable, signal, computed } from '@angular/core';

/** Active tool call state. */
export interface ActiveToolCall {
  toolName: string;
  toolUseId: string;
}

@Injectable()
export class EventProcessorService {
  private readonly activeToolCallSignal = signal<ActiveToolCall | null>(null);

  /** The currently executing tool call (null when no tool is active). */
  readonly activeToolCall = computed(() => this.activeToolCallSignal());

  /** Whether a tool is currently executing. */
  readonly isToolActive = computed(() => this.activeToolCallSignal() !== null);

  /** Set the active tool call from a tool_call SSE event. */
  setActiveToolCall(toolName: string, toolUseId: string): void {
    this.activeToolCallSignal.set({ toolName, toolUseId });
  }

  /**
   * Clear the active tool call (e.g., on tool_result or done event).
   * Call this when the SSE stream emits 'done' or a tool result is received.
   */
  clearActiveToolCall(): void {
    this.activeToolCallSignal.set(null);
  }
}
