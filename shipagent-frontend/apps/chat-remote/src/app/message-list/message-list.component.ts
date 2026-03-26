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
  signal,
} from '@angular/core';
import { CommonModule, NgComponentOutlet } from '@angular/common';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import type { ConversationMessage } from '@shipagent/shared-types';
import { DomainCardBridgeService } from '../../services/domain-card-bridge.service';
import { JobProgressSseService } from '../../services/job-progress-sse.service';
import { SystemMessageComponent } from '../messages/system-message.component';
import { UserMessageComponent } from '../messages/user-message.component';
import { TypingIndicatorComponent } from '../messages/typing-indicator.component';
import { WelcomeMessageComponent } from '../messages/welcome-message.component';
import { BatchPreviewComponent } from '../batch-preview/batch-preview.component';
import { InteractivePreviewComponent } from '../interactive-preview/interactive-preview.component';
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
    InteractivePreviewComponent,
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
          <!-- Render preview card inline — pick interactive or batch variant -->
          <div class="max-w-3xl mx-auto animate-fade-in">
            @if ($any(message.metadata?.['preview'])?.interactive) {
              <app-interactive-preview
                [preview]="$any(message.metadata?.['preview'])"
                [isConfirming]="false"
                [readOnly]="isHistoricalPreview(message)"
                (confirm)="handleInteractiveConfirm(message, $event)"
                (cancel)="previewCancel.emit($any(message.metadata?.['preview']))"
                (refine)="previewRefine.emit($event)"
              />
            } @else {
              <app-batch-preview
                [preview]="$any(message.metadata?.['preview'])"
                [isConfirming]="false"
                [readOnly]="isHistoricalPreview(message)"
                (confirm)="previewConfirm.emit($any(message.metadata?.['preview']))"
                (cancel)="previewCancel.emit($any(message.metadata?.['preview']))"
                (refine)="previewRefine.emit($event)"
              />
            }
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
  @Output() previewConfirm = new EventEmitter<Record<string, unknown>>();
  @Output() previewCancel = new EventEmitter<Record<string, unknown>>();
  @Output() previewRefine = new EventEmitter<string>();
  @Output() progressComplete = new EventEmitter<void>();
  @Output() progressFailed = new EventEmitter<void>();
  @Output() viewLabels = new EventEmitter<string>();

  private readonly domainCardBridge = inject(DomainCardBridgeService);
  private readonly apiService = inject(ApiService);
  readonly conversationStore = inject(ConversationStore);

  /** Expose progress service so parent can read final progress snapshot. */
  readonly progressService = inject(JobProgressSseService);

  /** Job IDs confirmed as non-pending by the backend (for historical preview detection). */
  private readonly completedJobIds = signal<Set<string>>(new Set());

  private shouldScrollToBottom = false;

  /** Signals proxied from store for template use. */
  readonly messages = this.conversationStore.messages;
  readonly isStreaming = this.conversationStore.isStreaming;

  /** Track which job IDs we have already checked to avoid redundant API calls. */
  private checkedJobIds = new Set<string>();

  ngOnChanges(_changes: SimpleChanges): void {
    this.shouldScrollToBottom = true;
    this.checkPreviewJobStatuses();
  }

  /**
   * For each preview message, check the backend job status.
   * If the job is no longer pending, mark it as completed so the preview
   * renders in read-only mode even when no subsequent messages exist.
   */
  private checkPreviewJobStatuses(): void {
    const msgs = this.messages();
    const previewJobIds = msgs
      .filter(m => m.metadata?.['type'] === 'preview_ready')
      .map(m => (m.metadata?.['preview'] as Record<string, unknown> | undefined)?.['job_id'] as string | undefined)
      .filter((id): id is string => !!id && !this.checkedJobIds.has(id));

    for (const jobId of previewJobIds) {
      this.checkedJobIds.add(jobId);
      this.apiService.getJob(jobId).subscribe({
        next: (job) => {
          if (job.status !== 'pending') {
            this.completedJobIds.update(s => {
              const next = new Set(s);
              next.add(jobId);
              return next;
            });
          }
        },
        error: () => {
          // Job not found — treat as completed (stale preview).
          this.completedJobIds.update(s => {
            const next = new Set(s);
            next.add(jobId);
            return next;
          });
        },
      });
    }
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
    // Exclude messages with artifact metadata — they have their own renderers.
    const metaType = msg.metadata?.['type'];
    if (metaType === 'preview_ready' || metaType === 'completion' ||
        metaType === 'domain_card' || metaType === 'error') {
      return false;
    }
    if (msg.role === 'assistant') return true;
    if (msg.role === 'system') {
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

  /**
   * Determine whether a preview message is historical (already confirmed/completed).
   *
   * Checks if any subsequent message indicates the job was confirmed or completed.
   * When true, the preview renders in read-only mode without action buttons.
   */
  isHistoricalPreview(message: ConversationMessage): boolean {
    const jobId = (message.metadata?.['preview'] as Record<string, unknown> | undefined)?.['job_id'];
    if (!jobId) return false;

    // Check backend-verified completed jobs first.
    if (this.completedJobIds().has(jobId as string)) return true;

    // Fall back to checking subsequent messages for confirmation evidence.
    const msgs = this.messages();
    const idx = msgs.indexOf(message);
    for (let i = idx + 1; i < msgs.length; i++) {
      const meta = msgs[i].metadata;
      if (!meta) continue;
      if (meta['type'] === 'completion' && meta['jobId'] === jobId) return true;
      if (meta['type'] === 'status' && meta['action'] === 'execute' && meta['jobId'] === jobId) return true;
    }
    return false;
  }

  /** Handle interactive preview confirm — merges selected service code into preview data. */
  handleInteractiveConfirm(message: ConversationMessage, event: { selectedServiceCode?: string }): void {
    const preview = message.metadata?.['preview'] ?? {};
    this.previewConfirm.emit({ ...preview, selected_service_code: event.selectedServiceCode });
  }

  /** Resolve a domain card component and its inputs for NgComponentOutlet. */
  resolveDomainCard(msg: ConversationMessage): DomainCardEntry | null {
    const cardType = msg.metadata?.['cardType'] as string | undefined;
    if (!cardType) return null;

    const component = this.domainCardBridge.resolve(cardType);
    if (!component) return null;

    return {
      component,
      inputs: {
        data: msg.metadata?.['data'] ?? {},
        cardType,
        sessionId: this.conversationStore.sessionId() ?? '',
      },
    };
  }
}
