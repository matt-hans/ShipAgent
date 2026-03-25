/**
 * ChatActionsService — Action handlers for the chat UI.
 *
 * Coordinates user-initiated actions: sending messages, confirming jobs,
 * cancelling jobs, refining commands, and skipping failed rows.
 *
 * Provided at component level (not root).
 */

import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import { ConversationSessionService } from './conversation-session.service';

@Injectable()
export class ChatActionsService {
  private readonly apiService = inject(ApiService);
  private readonly conversationStore = inject(ConversationStore);
  private readonly sessionService = inject(ConversationSessionService);

  /** Whether a confirm/cancel action is in progress. */
  readonly isConfirming = signal(false);

  /**
   * Send a user message to the agent.
   *
   * 1. Ensures a session exists (creates one if needed, with mutex protection).
   * 2. Appends the user message to the local store.
   * 3. Sets streaming to true.
   * 4. Sends the message via REST API.
   */
  async sendMessage(text: string): Promise<void> {
    if (!text.trim()) return;

    const interactiveShipping = this.conversationStore.interactiveShipping();

    // Optimistically append user message.
    this.conversationStore.appendMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: text.trim(),
      timestamp: new Date().toISOString(),
    });

    this.conversationStore.setStreaming(true);

    try {
      const sid = await this.sessionService.ensureSession(interactiveShipping);
      await firstValueFrom(this.apiService.sendMessage(sid, text.trim()));
    } catch (err) {
      // Push error to the conversation store so the UI can display it.
      this.conversationStore.appendMessage({
        id: `err-${Date.now()}`,
        role: 'system',
        content: err instanceof Error ? err.message : 'Failed to send message',
        timestamp: new Date().toISOString(),
        metadata: { type: 'error' },
      });
      this.conversationStore.setStreaming(false);
    }
  }

  /**
   * Confirm a job for execution.
   */
  async confirmJob(
    jobId: string,
    writeBackEnabled = true,
    selectedServiceCode?: string,
  ): Promise<void> {
    this.isConfirming.set(true);
    try {
      await firstValueFrom(
        this.apiService.confirmJob(jobId, writeBackEnabled, selectedServiceCode),
      );
    } finally {
      this.isConfirming.set(false);
    }
  }

  /**
   * Cancel a job.
   */
  async cancelJob(jobId: string): Promise<void> {
    this.isConfirming.set(true);
    try {
      await firstValueFrom(this.apiService.cancelJob(jobId));
    } finally {
      this.isConfirming.set(false);
    }
  }

  /**
   * Send a refinement message — injects it as a user message.
   */
  async refineMessage(refinementText: string): Promise<void> {
    if (!refinementText.trim()) return;
    await this.sendMessage(refinementText.trim());
  }

  /**
   * Skip specified failed rows and resume the job.
   */
  async skipFailedRows(jobId: string, rowNumbers: number[]): Promise<void> {
    if (!rowNumbers.length) return;
    await firstValueFrom(this.apiService.skipFailedRows(jobId, rowNumbers));
  }
}
