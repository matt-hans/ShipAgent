/**
 * ChatContainerComponent — The main command center UI for ShipAgent.
 *
 * This is the primary user interaction surface. It coordinates:
 *   - SSE streaming from the agent conversation
 *   - Message list display with all message types
 *   - Preview cards (batch and interactive)
 *   - Progress display during batch execution
 *   - Completion artifacts with label downloads
 *   - Rich chat input with autocomplete
 *   - Cross-remote domain cards via DomainCardBridgeService
 *
 * Architecture: All services are provided at component level (not root)
 * so their lifecycles are tied to the chat remote's component tree.
 * When the shell unloads this remote, all SSE connections are closed.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Injector,
  OnDestroy,
  OnInit,
  ViewChild,
  inject,
  effect,
  signal,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { provideMarkdown } from 'ngx-markdown';
import { AppStore, ConversationStore, DataSourceStore, JobStore } from '@shipagent/shared-state';
import { ApiService } from '@shipagent/shared-api';
import { ConversationSseService } from '../../services/conversation-sse.service';
import { ConversationSessionService } from '../../services/conversation-session.service';
import { JobProgressSseService } from '../../services/job-progress-sse.service';
import { EventProcessorService } from '../../services/event-processor.service';
import { ChatActionsService } from '../../services/chat-actions.service';
import { DomainCardBridgeService } from '../../services/domain-card-bridge.service';
import { SseService } from '@shipagent/shared-sse';
import { MessageListComponent } from '../message-list/message-list.component';
import { ToolCallChipComponent } from '../tool-call-chip/tool-call-chip.component';
import { ActiveSourceBannerComponent } from '../messages/active-source-banner.component';
import { InteractiveModeBannerComponent } from '../messages/interactive-mode-banner.component';
import { RichChatInputComponent } from '../rich-chat-input/rich-chat-input.component';
// BatchPreviewComponent, ProgressDisplayComponent, CompletionArtifactComponent
// are imported by MessageListComponent — not needed here.
import { LabelPreviewModalComponent } from '../label-preview-modal/label-preview-modal.component';

@Component({
  selector: 'app-chat-container',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col flex-1 h-full overflow-hidden' },
  providers: [
    ConversationSseService,
    ConversationSessionService,
    JobProgressSseService,
    EventProcessorService,
    ChatActionsService,
    DomainCardBridgeService,
    SseService,
    provideMarkdown(),
  ],
  imports: [
    CommonModule,
    FormsModule,
    MessageListComponent,
    ToolCallChipComponent,
    ActiveSourceBannerComponent,
    InteractiveModeBannerComponent,
    LabelPreviewModalComponent,
    RichChatInputComponent,
  ],
  template: `
    <div class="flex flex-col h-full bg-background overflow-hidden">
      <!-- Data source or interactive mode banner -->
      @if (conversationStore.interactiveShipping()) {
        <app-interactive-mode-banner />
      } @else if (dataSourceStore.activeSourceType()) {
        <app-active-source-banner />
      }

      <!-- Message list + right-side action icons -->
      <div class="flex flex-1 overflow-hidden">
        <app-message-list
          #messageList
          class="flex-1 overflow-hidden flex flex-col"
          [interactiveShipping]="conversationStore.interactiveShipping()"
          [executingJobId]="executingJobId()"
          (exampleClick)="handleExampleClick($event)"
          (previewConfirm)="handleConfirmFromPreview($event)"
          (previewCancel)="handleCancelFromPreview($event)"
          (previewRefine)="handleRefine($event)"
          (progressComplete)="handleProgressComplete()"
          (progressFailed)="handleProgressFailed()"
          (viewLabels)="openLabelPreview($event)"
        />

        <!-- Right edge: action icons -->
        <div class="flex flex-col items-center pt-3 pr-1 gap-2">
          <button (click)="handleNewChat()" [disabled]="conversationStore.isStreaming()" class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-50" title="New chat">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <button (click)="openSettings()" class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors" title="Settings">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
          <button class="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors" title="Chat history">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </button>
        </div>
      </div>

      <!-- Active tool call chip -->
      @if (eventProcessorService.isToolActive()) {
        <div class="px-4 pb-1">
          <app-tool-call-chip
            [toolName]="formatToolName(eventProcessorService.activeToolCall()?.toolName ?? '')"
            [isActive]="true"
          />
        </div>
      }

      <!-- Chat input area -->
      <div class="border-t border-slate-800 px-4 py-3 bg-card/30 backdrop-blur">
        <div class="max-w-3xl mx-auto">
          <div class="flex items-end gap-2">
            <app-rich-chat-input
              class="flex-1"
              [value]="inputValue()"
              [placeholder]="inputPlaceholder()"
              [disabled]="conversationStore.isStreaming()"
              (valueChange)="inputValue.set($event)"
              (messageSent)="handleRichInputSubmit($event)"
            />

            <button
              class="btn-primary p-2.5 flex-shrink-0 rounded-lg"
              [disabled]="!inputValue().trim() || conversationStore.isStreaming()"
              (click)="handleSubmit()"
            >
              @if (conversationStore.isStreaming()) {
                <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                </svg>
              } @else {
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                </svg>
              }
            </button>
          </div>
          <p class="text-[10px] font-mono text-slate-500 mt-1.5">
            Use /commands and &#64;contacts for shortcuts · Press Enter to send
          </p>
        </div>
      </div>

      <!-- Label preview modal (rendered outside flow, uses fixed positioning) -->
      <app-label-preview-modal
        [pdfUrl]="labelPreviewUrl()"
        [isOpen]="showLabelPreview()"
        (close)="closeLabelPreview()"
      />
    </div>
  `,
})
export class ChatContainerComponent implements OnInit, OnDestroy {
  @ViewChild('messageList') private messageList?: MessageListComponent;

  readonly conversationStore = inject(ConversationStore);
  readonly dataSourceStore = inject(DataSourceStore);
  readonly eventProcessorService = inject(EventProcessorService);
  readonly chatActions = inject(ChatActionsService);
  private readonly sessionService = inject(ConversationSessionService);
  private readonly appStore = inject(AppStore);
  private readonly jobStore = inject(JobStore);
  private readonly apiService = inject(ApiService);
  private readonly domainCardBridge = inject(DomainCardBridgeService);
  private readonly injector = inject(Injector);

  readonly inputValue = signal('');

  /**
   * Job ID currently being executed (set after confirm, cleared on complete/fail).
   * When non-null, the ProgressDisplayComponent is shown in the message list.
   */
  readonly executingJobId = signal<string | null>(null);

  /** Whether the label preview modal is visible. */
  readonly showLabelPreview = signal(false);

  /** URL for the label PDF currently being previewed. */
  readonly labelPreviewUrl = signal('');

  /** Stored job name for the completion artifact (captured on confirm). */
  private lastJobName = '';

  /**
   * Active preview — computed from the last preview_ready message in the store.
   * Mirrors React's `preview` state in CommandCenter.tsx.
   * Returns null when no preview is pending (cleared after confirm/cancel).
   */
  readonly activePreview = computed(() => {
    const messages = this.conversationStore.messages();
    // Find the last preview_ready message
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.metadata?.['type'] === 'preview_ready') {
        return msg.metadata['preview'] as any;
      }
    }
    return null;
  });

  /** Context-aware placeholder driven by current mode and data source state. */
  protected readonly inputPlaceholder = computed(() => {
    if (this.conversationStore.interactiveShipping()) {
      return 'Describe one shipment from scratch...';
    }
    if (!this.dataSourceStore.activeSourceType()) {
      return 'Track a package, find locations, or connect a data source...';
    }
    return 'Enter a shipping command...';
  });

  // Track messages length to trigger scroll
  private lastMessageCount = 0;

  /**
   * Previous interactiveShipping value — used to detect mode changes.
   * Mirrors React's prevInteractiveRef.
   */
  private prevInteractiveMode: boolean | null = null;

  /** Whether a session reset triggered by mode switch is in-flight. */
  private isResettingSession = false;

  constructor() {
    // Auto-scroll on new messages using effect
    effect(() => {
      const count = this.conversationStore.messages().length;
      if (count !== this.lastMessageCount) {
        this.lastMessageCount = count;
        this.messageList?.markNeedsScroll();
      }
    });

    // Watch interactiveShipping changes and reset session.
    // Mirrors React's useEffect on interactiveShipping in CommandCenter.tsx.
    effect(() => {
      const current = this.conversationStore.interactiveShipping();

      // First run — initialise tracking variable.
      if (this.prevInteractiveMode === null) {
        this.prevInteractiveMode = current;
        return;
      }

      // No change — skip.
      if (this.prevInteractiveMode === current) return;
      this.prevInteractiveMode = current;

      // Only reset if there is an active or in-flight session.
      const hasSession = this.conversationStore.sessionId()
        || this.sessionService.isCreatingSession();
      if (!hasSession) return;

      // Confirm if there is in-progress work.
      if (this.activePreview() || this.conversationStore.isStreaming()) {
        const confirmed = window.confirm(
          'Switching mode resets your current session. Continue?',
        );
        if (!confirmed) {
          // Revert toggle — schedule to avoid recursive effect.
          queueMicrotask(() => {
            this.conversationStore.setInteractiveShipping(!current);
            this.prevInteractiveMode = !current;
          });
          return;
        }
      }

      // Perform the session reset.
      this.isResettingSession = true;
      this.appStore.setToggleLocked(true);
      this.sessionService.reset().then(() => {
        this.executingJobId.set(null);
        this.showLabelPreview.set(false);
        this.labelPreviewUrl.set('');
        this.lastJobName = '';
        this.isResettingSession = false;
        this.appStore.setToggleLocked(false);
      });
    });

    // Lock toggle while session creation is in-flight or agent is streaming.
    effect(() => {
      const creating = this.sessionService.isCreatingSession();
      const streaming = this.conversationStore.isStreaming();
      if (creating || streaming) {
        this.appStore.setToggleLocked(true);
      } else if (!this.isResettingSession) {
        this.appStore.setToggleLocked(false);
      }
    });
  }

  ngOnInit(): void {
    // Asynchronously load the domain card registry from domain-remote.
    // This is fire-and-forget — domain cards simply won't render if not loaded.
    this.domainCardBridge.initialize(this.injector);
  }

  ngOnDestroy(): void {
    // Services are provided at component level — their ngOnDestroy handles cleanup.
  }

  // ---------------------------------------------------------------------------
  // Action icon handlers
  // ---------------------------------------------------------------------------

  handleNewChat(): void {
    this.sessionService.startNewChat();
  }

  openSettings(): void {
    this.appStore.openSettings();
  }

  // ---------------------------------------------------------------------------
  // Label preview
  // ---------------------------------------------------------------------------

  /** Open the label preview modal for the given job's merged PDF. */
  openLabelPreview(jobId: string): void {
    this.labelPreviewUrl.set(this.apiService.getMergedLabelsUrl(jobId));
    this.showLabelPreview.set(true);
  }

  /** Close the label preview modal and clear the URL. */
  closeLabelPreview(): void {
    this.showLabelPreview.set(false);
    this.labelPreviewUrl.set('');
  }

  // ---------------------------------------------------------------------------
  // Preview actions (confirm / cancel / refine)
  // ---------------------------------------------------------------------------

  async handleConfirmFromPreview(previewData: any): Promise<void> {
    const jobId = previewData?.job_id as string | undefined;
    if (!jobId) return;
    const writeBack = this.dataSourceStore.writeBackEnabled();

    try {
      const selectedServiceCode = previewData?.selected_service_code as string | undefined;
      await this.chatActions.confirmJob(jobId, writeBack, selectedServiceCode);

      // Add confirmation message to chat.
      this.conversationStore.appendMessage({
        id: `sys-confirm-${Date.now()}`,
        role: 'system',
        content: 'Batch confirmed. Processing shipments...',
        timestamp: new Date().toISOString(),
        metadata: { type: 'status', jobId, action: 'execute' },
      });

      // Fetch job name for completion artifact display.
      this.apiService.getJob(jobId).subscribe({
        next: (job) => { this.lastJobName = job.name || ''; },
        error: () => { this.lastJobName = ''; },
      });

      // Activate progress display.
      this.executingJobId.set(jobId);
    } catch (err) {
      this.conversationStore.appendMessage({
        id: `err-confirm-${Date.now()}`,
        role: 'system',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to confirm batch'}`,
        timestamp: new Date().toISOString(),
        metadata: { type: 'error' },
      });
    }
  }

  async handleCancelFromPreview(previewData: any): Promise<void> {
    const jobId = previewData?.job_id as string | undefined;
    if (!jobId) return;

    try {
      await this.chatActions.cancelJob(jobId);
      this.conversationStore.appendMessage({
        id: `sys-cancel-${Date.now()}`,
        role: 'system',
        content: 'Batch cancelled. You can enter a new command.',
        timestamp: new Date().toISOString(),
      });
      this.jobStore.incrementJobListVersion();
    } catch (err) {
      console.error('Failed to cancel:', err);
    }
  }

  /**
   * Handle batch execution completion — add completion artifact message.
   * Called by the ProgressDisplayComponent's (complete) output.
   */
  handleProgressComplete(): void {
    const jobId = this.executingJobId();
    if (!jobId) return;

    const progressService = this.messageList?.progressService;
    if (!progressService) return;

    const p = progressService.progress();
    this.conversationStore.appendMessage({
      id: `completion-${Date.now()}`,
      role: 'system',
      content: '',
      timestamp: new Date().toISOString(),
      metadata: {
        type: 'completion',
        jobId,
        action: 'complete',
        completion: {
          jobName: this.lastJobName || undefined,
          successful: p.successful,
          failed: p.failed,
          totalCostCents: p.totalCostCents,
          dutiesTaxesCents: p.dutiesTaxesCents,
          internationalCount: p.internationalCount,
          rowFailures: p.rowFailures.length > 0 ? p.rowFailures : undefined,
        },
      },
    });

    // Persist the artifact to the conversation DB.
    const sid = this.conversationStore.sessionId();
    if (sid) {
      this.apiService.saveArtifact(sid, '', {
        type: 'completion',
        jobId,
        action: 'complete',
        completion: {
          jobName: this.lastJobName || undefined,
          successful: p.successful,
          failed: p.failed,
          totalCostCents: p.totalCostCents,
          dutiesTaxesCents: p.dutiesTaxesCents,
          internationalCount: p.internationalCount,
          rowFailures: p.rowFailures.length > 0 ? p.rowFailures : undefined,
        },
      }).subscribe({ error: (e) => console.warn('Failed to save artifact:', e) });
    }

    // Auto-open label preview after successful batch.
    if (p.successful > 0 && jobId) {
      this.openLabelPreview(jobId);
    }

    this.executingJobId.set(null);
    this.lastJobName = '';
    this.jobStore.incrementJobListVersion();

    // Notify the agent that execution completed so it doesn't keep asking
    // "would you like to confirm?" — this is a silent context update.
    const currentSid = this.conversationStore.sessionId();
    if (currentSid && p.successful > 0) {
      firstValueFrom(
        this.apiService.sendMessage(currentSid,
          `[System: Batch execution completed. ${p.successful} shipment(s) processed, labels generated. Job ${jobId} is done.]`
        )
      ).catch(() => { /* best-effort */ });
    }
  }

  /**
   * Handle batch execution failure — add completion artifact with failure data.
   * Called by the ProgressDisplayComponent's (failed) output.
   */
  handleProgressFailed(): void {
    const jobId = this.executingJobId();
    if (!jobId) return;

    const progressService = this.messageList?.progressService;
    if (!progressService) return;

    const p = progressService.progress();
    this.conversationStore.appendMessage({
      id: `completion-fail-${Date.now()}`,
      role: 'system',
      content: '',
      timestamp: new Date().toISOString(),
      metadata: {
        type: 'completion',
        jobId,
        action: 'complete',
        completion: {
          jobName: this.lastJobName || undefined,
          successful: p.successful,
          failed: p.failed,
          totalCostCents: p.totalCostCents,
          dutiesTaxesCents: p.dutiesTaxesCents,
          internationalCount: p.internationalCount,
          rowFailures: p.rowFailures.length > 0 ? p.rowFailures : undefined,
        },
      },
    });

    this.executingJobId.set(null);
    this.lastJobName = '';
    this.jobStore.incrementJobListVersion();
  }

  async handleRefine(text: string): Promise<void> {
    await this.chatActions.refineMessage(text);
  }

  // ---------------------------------------------------------------------------
  // Input handling
  // ---------------------------------------------------------------------------

  handleKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.handleSubmit();
    }
  }

  async handleSubmit(): Promise<void> {
    const text = this.inputValue().trim();
    if (!text || this.conversationStore.isStreaming()) return;

    this.inputValue.set('');
    await this.chatActions.sendMessage(text);
  }

  /** Called by RichChatInput when Enter is pressed — text is already expanded. */
  async handleRichInputSubmit(text: string): Promise<void> {
    if (!text.trim() || this.conversationStore.isStreaming()) return;
    this.inputValue.set('');
    await this.chatActions.sendMessage(text.trim());
  }

  handleExampleClick(text: string): void {
    this.inputValue.set(text);
    this.handleSubmit();
  }

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  /** Format a raw tool name for display (strip namespaces, underscores). */
  formatToolName(toolName: string): string {
    return toolName
      .replace(/^mcp__\w+__/, '')
      .replace(/_tool$/, '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }
}
