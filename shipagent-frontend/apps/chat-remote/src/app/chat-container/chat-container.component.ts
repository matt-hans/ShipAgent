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
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { provideMarkdown } from 'ngx-markdown';
import { ConversationStore, DataSourceStore } from '@shipagent/shared-state';
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

@Component({
  selector: 'app-chat-container',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
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
  ],
  template: `
    <div class="flex flex-col h-full bg-background overflow-hidden">
      <!-- Data source or interactive mode banner -->
      @if (conversationStore.interactiveShipping()) {
        <app-interactive-mode-banner />
      } @else if (dataSourceStore.activeSourceType()) {
        <app-active-source-banner />
      }

      <!-- Message list -->
      <app-message-list
        #messageList
        class="flex-1 overflow-hidden flex flex-col"
        [interactiveShipping]="conversationStore.interactiveShipping()"
        (exampleClick)="handleExampleClick($event)"
      />

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
      <div class="border-t border-border/50 bg-card/30 p-3">
        <div class="flex items-end gap-2">
          <textarea
            #inputTextarea
            class="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground resize-none outline-none min-h-[40px] max-h-[200px] py-2 px-3 rounded-lg border border-border/50 focus:border-primary/50 transition-colors"
            placeholder="Enter a command..."
            [disabled]="conversationStore.isStreaming()"
            [value]="inputValue()"
            (input)="inputValue.set($any($event.target).value)"
            (keydown)="handleKeyDown($event)"
            rows="1"
          ></textarea>

          <button
            class="btn-primary px-4 py-2 flex-shrink-0"
            [disabled]="!inputValue().trim() || conversationStore.isStreaming()"
            (click)="handleSubmit()"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  `,
})
export class ChatContainerComponent implements OnInit, OnDestroy {
  @ViewChild('messageList') private messageList?: MessageListComponent;

  readonly conversationStore = inject(ConversationStore);
  readonly dataSourceStore = inject(DataSourceStore);
  readonly eventProcessorService = inject(EventProcessorService);
  private readonly chatActions = inject(ChatActionsService);
  private readonly domainCardBridge = inject(DomainCardBridgeService);
  private readonly injector = inject(Injector);

  readonly inputValue = signal('');

  // Track messages length to trigger scroll
  private lastMessageCount = 0;

  constructor() {
    // Auto-scroll on new messages using effect
    effect(() => {
      const count = this.conversationStore.messages().length;
      if (count !== this.lastMessageCount) {
        this.lastMessageCount = count;
        this.messageList?.markNeedsScroll();
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
