/**
 * ChatHistoryFlyoutComponent
 *
 * Read-only overlay showing the full message history of the current
 * conversation session. Includes an export-to-JSON button.
 * Rendered by ChatContainerComponent when the clock icon is clicked.
 */

import {
  ChangeDetectionStrategy,
  Component,
  inject,
  input,
  OnChanges,
  output,
  signal,
  SimpleChanges,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import {
  XIconComponent,
  DownloadIconComponent,
} from '@shipagent/shared-ui';
import type { PersistedMessage } from '@shipagent/shared-types';

@Component({
  selector: 'app-chat-history-flyout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    XIconComponent,
    DownloadIconComponent,
  ],
  template: `
    @if (open()) {
      <!-- Backdrop -->
      <div
        class="fixed inset-0 z-40 bg-black/40"
        (click)="closed.emit()"
      ></div>

      <!-- Flyout panel -->
      <aside class="fixed right-0 top-0 h-full w-80 z-50 bg-slate-950 border-l border-slate-800 flex flex-col shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-slate-800 flex-shrink-0">
          <h2 class="text-sm font-semibold text-slate-100">Chat History</h2>
          <div class="flex items-center gap-2">
            @if (sessionId()) {
              <button
                class="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
                title="Export conversation"
                (click)="handleExport()"
              >
                <sa-icon-download class="w-4 h-4" />
              </button>
            }
            <button
              class="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
              aria-label="Close chat history"
              (click)="closed.emit()"
            >
              <sa-icon-x class="w-5 h-5" />
            </button>
          </div>
        </div>

        <!-- Messages -->
        <div class="flex-1 overflow-y-auto p-4 space-y-3">
          @if (isLoading()) {
            <div class="space-y-3">
              <div class="h-10 bg-slate-800 rounded animate-pulse"></div>
              <div class="h-16 bg-slate-800 rounded animate-pulse"></div>
              <div class="h-10 bg-slate-800 rounded animate-pulse"></div>
            </div>
          } @else if (error()) {
            <p class="text-xs text-red-400 text-center py-4">{{ error() }}</p>
          } @else if (messages().length === 0) {
            <p class="text-xs text-slate-500 text-center py-4">No messages in this session.</p>
          } @else {
            @for (msg of messages(); track msg.id) {
              <div
                class="flex"
                [class.justify-end]="msg.role === 'user'"
                [class.justify-start]="msg.role !== 'user'"
              >
                <div
                  class="max-w-[85%] px-3 py-2 rounded-lg text-xs leading-relaxed"
                  [class.bg-primary]="msg.role === 'user'"
                  [class.bg-opacity-20]="msg.role === 'user'"
                  [class.text-slate-100]="msg.role === 'user'"
                  [class.bg-slate-800]="msg.role !== 'user'"
                  [class.text-slate-200]="msg.role !== 'user'"
                >
                  {{ msg.content }}
                </div>
              </div>
            }
          }
        </div>
      </aside>
    }
  `,
})
export class ChatHistoryFlyoutComponent implements OnChanges {
  private readonly apiService = inject(ApiService);

  /** Whether the flyout is visible. */
  readonly open = input<boolean>(false);
  /** The session ID whose history to display. */
  readonly sessionId = input<string | null>(null);
  /** Emitted when the flyout is closed. */
  readonly closed = output<void>();

  readonly messages = signal<PersistedMessage[]>([]);
  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['open'] || changes['sessionId']) {
      const isOpen = this.open();
      const sid = this.sessionId();
      if (isOpen && sid) {
        void this.loadMessages(sid);
      } else if (!isOpen) {
        this.messages.set([]);
        this.error.set(null);
      }
    }
  }

  /** Export the conversation as JSON (browser download). */
  async handleExport(): Promise<void> {
    const sid = this.sessionId();
    if (!sid) return;
    try {
      const blob = await firstValueFrom(this.apiService.exportConversation(sid));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `conversation-${sid}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export conversation:', err);
      this.error.set('Export failed');
    }
  }

  private async loadMessages(sessionId: string): Promise<void> {
    this.isLoading.set(true);
    this.error.set(null);
    this.messages.set([]);
    try {
      const detail = await firstValueFrom(
        this.apiService.getConversationMessages(sessionId),
      );
      this.messages.set(detail.messages);
    } catch (err) {
      console.error('Failed to load message history:', err);
      this.error.set('Failed to load messages');
    } finally {
      this.isLoading.set(false);
    }
  }
}
