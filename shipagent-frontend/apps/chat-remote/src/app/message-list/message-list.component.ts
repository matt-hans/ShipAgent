/**
 * MessageListComponent — Scrollable container for the conversation thread.
 *
 * Renders messages from ConversationStore using appropriate sub-components
 * based on message role and metadata. Domain card messages are resolved
 * via DomainCardBridgeService and rendered with NgComponentOutlet.
 *
 * Auto-scrolls to the bottom on new messages.
 */

import {
  AfterViewChecked,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  Type,
  ViewChild,
  inject,
} from '@angular/core';
import { CommonModule, NgComponentOutlet } from '@angular/common';
import { ConversationStore } from '@shipagent/shared-state';
import type { ConversationMessage } from '@shipagent/shared-types';
import { DomainCardBridgeService } from '../../services/domain-card-bridge.service';
import { JobProgressSseService } from '../../services/job-progress-sse.service';
import { SystemMessageComponent } from '../messages/system-message.component';
import { UserMessageComponent } from '../messages/user-message.component';
import { TypingIndicatorComponent } from '../messages/typing-indicator.component';
import { WelcomeMessageComponent } from '../messages/welcome-message.component';
import { BatchPreviewComponent } from '../batch-preview/batch-preview.component';
import { ProgressDisplayComponent } from '../progress-display/progress-display.component';
import { CompletionArtifactComponent } from '../completion-artifact/completion-artifact.component';

/** Resolved domain card for NgComponentOutlet. */
interface DomainCardEntry {
  component: Type<unknown>;
  inputs: Record<string, unknown>;
}

@Component({
  selector: 'app-message-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    NgComponentOutlet,
    SystemMessageComponent,
    UserMessageComponent,
    TypingIndicatorComponent,
    WelcomeMessageComponent,
    BatchPreviewComponent,
    ProgressDisplayComponent,
    CompletionArtifactComponent,
  ],
  styles: [`
    .message-list-scroll {
      overflow-y: auto;
      overflow-x: hidden;
      scroll-behavior: smooth;
    }
  `],
  template: `
    <div
      #scrollContainer
      class="message-list-scroll flex-1 px-4 py-4 space-y-4"
    >
      <!-- Welcome screen when no messages -->
      @if (messages().length === 0 && !isStreaming()) {
        <app-welcome-message
          [interactiveShipping]="interactiveShipping"
          (exampleClick)="exampleClick.emit($event)"
        />
      }

      <!-- Message list -->
      @for (message of messages(); track message.id) {
        @if (isUserMessage(message)) {
          <app-user-message [message]="message" />
        } @else if (isSystemMessage(message)) {
          <app-system-message [message]="message" />
        } @else if (isPreviewMessage(message)) {
          <!-- Render preview card inline in the conversation flow -->
          <div class="max-w-3xl mx-auto animate-fade-in">
            <app-batch-preview
              [preview]="$any(message.metadata?.['preview'])"
              [isConfirming]="false"
              (confirm)="previewConfirm.emit(message.metadata?.['preview'])"
              (cancel)="previewCancel.emit(message.metadata?.['preview'])"
              (refine)="previewRefine.emit($event)"
            />
          </div>
        } @else if (isCompletionMessage(message)) {
          <!-- Render completion artifact inline -->
          <div class="max-w-3xl mx-auto animate-fade-in">
            <app-completion-artifact [message]="message" (viewLabels)="viewLabels.emit($event)" />
          </div>
        } @else if (isDomainCardMessage(message)) {
          @if (resolveDomainCard(message); as entry) {
            <ng-container *ngComponentOutlet="entry.component; inputs: entry.inputs" />
          }
        } @else if (isErrorMessage(message)) {
          <div class="card-premium border-error/30 p-3 text-sm font-mono text-error">
            {{ message.content }}
          </div>
        }
      }

      <!-- Progress display during batch execution -->
      @if (executingJobId) {
        <div class="max-w-3xl mx-auto animate-fade-in">
          <app-progress-display
            [jobId]="executingJobId"
            (complete)="progressComplete.emit()"
            (failed)="progressFailed.emit()"
            (viewLabels)="viewLabels.emit($event)"
          />
        </div>
      }

      <!-- Typing indicator while streaming -->
      @if (isStreaming() && messages().length > 0) {
        <app-typing-indicator />
      }

      <!-- Scroll anchor -->
      <div #scrollAnchor></div>
    </div>
  `,
})
export class MessageListComponent implements AfterViewChecked, OnChanges {
  @ViewChild('scrollAnchor') private scrollAnchor!: ElementRef<HTMLDivElement>;

  @Input() interactiveShipping = false;
  @Input() executingJobId: string | null = null;
  @Output() exampleClick = new EventEmitter<string>();
  @Output() previewConfirm = new EventEmitter<any>();
  @Output() previewCancel = new EventEmitter<any>();
  @Output() previewRefine = new EventEmitter<string>();
  @Output() progressComplete = new EventEmitter<void>();
  @Output() progressFailed = new EventEmitter<void>();
  @Output() viewLabels = new EventEmitter<string>();

  private readonly domainCardBridge = inject(DomainCardBridgeService);
  readonly conversationStore = inject(ConversationStore);

  /** Expose progress service so parent can read final progress snapshot. */
  readonly progressService = inject(JobProgressSseService);

  private shouldScrollToBottom = false;

  /** Signals proxied from store for template use. */
  readonly messages = this.conversationStore.messages;
  readonly isStreaming = this.conversationStore.isStreaming;

  ngOnChanges(_changes: SimpleChanges): void {
    this.shouldScrollToBottom = true;
  }

  ngAfterViewChecked(): void {
    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  /** Called externally when new messages arrive. */
  markNeedsScroll(): void {
    this.shouldScrollToBottom = true;
  }

  private scrollToBottom(): void {
    try {
      if (this.scrollAnchor?.nativeElement) {
        this.scrollAnchor.nativeElement.scrollIntoView({ behavior: 'smooth', block: 'end' });
      }
    } catch {
      // Ignore scroll errors
    }
  }

  // ---------------------------------------------------------------------------
  // Message type guards
  // ---------------------------------------------------------------------------

  isUserMessage(msg: ConversationMessage): boolean {
    return msg.role === 'user';
  }

  isSystemMessage(msg: ConversationMessage): boolean {
    if (msg.role === 'assistant') return true;
    if (msg.role === 'system') {
      const metaType = msg.metadata?.['type'];
      // Messages with no metadata type, or with 'status' type, render as system messages.
      return !metaType || metaType === 'status';
    }
    return false;
  }

  isPreviewMessage(msg: ConversationMessage): boolean {
    return msg.metadata?.['type'] === 'preview_ready';
  }

  isCompletionMessage(msg: ConversationMessage): boolean {
    return msg.metadata?.['type'] === 'completion';
  }

  isDomainCardMessage(msg: ConversationMessage): boolean {
    return msg.metadata?.['type'] === 'domain_card';
  }

  isErrorMessage(msg: ConversationMessage): boolean {
    return msg.metadata?.['type'] === 'error';
  }

  /** Resolve a domain card component and its inputs for NgComponentOutlet. */
  resolveDomainCard(msg: ConversationMessage): DomainCardEntry | null {
    const cardType = msg.metadata?.['cardType'] as string | undefined;
    if (!cardType) return null;

    const component = this.domainCardBridge.resolve(cardType);
    if (!component) return null;

    return {
      component,
      inputs: { data: msg.metadata?.['data'] ?? {}, cardType },
    };
  }
}
