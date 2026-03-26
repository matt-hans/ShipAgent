/**
 * ChatSessionsPanelComponent
 *
 * Lists persistent conversation sessions grouped by date recency.
 * Supports session switching, deletion, bulk clear, new chat, export, and rename.
 * Port of React ChatSessionsPanel.tsx.
 *
 * Key behavior: watches conversationStore.chatSessionsVersion() via effect()
 * to know when to re-fetch the session list after SSE 'done' events.
 * Date groupings match React: Today / Yesterday / Previous 7 Days / Older.
 */

import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import {
  TrashIconComponent,
  PlusIconComponent,
  DownloadIconComponent,
  TimeAgoPipe,
} from '@shipagent/shared-ui';
import type { ChatSessionSummary } from '@shipagent/shared-types';

const MS_PER_DAY = 86_400_000;
const GROUP_ORDER = ['Today', 'Yesterday', 'Previous 7 Days', 'Older'] as const;
type DateGroup = typeof GROUP_ORDER[number];

/** Group sessions by relative date: Today / Yesterday / Previous 7 Days / Older. */
function groupByDate(sessions: ChatSessionSummary[]): Record<DateGroup, ChatSessionSummary[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - MS_PER_DAY);
  const weekAgo = new Date(today.getTime() - 7 * MS_PER_DAY);

  const groups: Record<DateGroup, ChatSessionSummary[]> = {
    'Today': [],
    'Yesterday': [],
    'Previous 7 Days': [],
    'Older': [],
  };

  for (const session of sessions) {
    const date = new Date(session.created_at);
    if (date >= today) {
      groups['Today'].push(session);
    } else if (date >= yesterday) {
      groups['Yesterday'].push(session);
    } else if (date >= weekAgo) {
      groups['Previous 7 Days'].push(session);
    } else {
      groups['Older'].push(session);
    }
  }

  return groups;
}

@Component({
  selector: 'sa-chat-sessions-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TrashIconComponent,
    PlusIconComponent,
    DownloadIconComponent,
    TimeAgoPipe,
  ],
  template: `
    <div class="p-3 space-y-3">
      <!-- Header row -->
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium text-slate-300">Chat Sessions</span>
        <div class="flex items-center gap-1.5">
          <!-- Clear all button (only shown when sessions exist) -->
          @if (sessions().length > 0) {
            <button
              [class]="clearAllBtnClass()"
              [disabled]="isClearingAll()"
              [title]="confirmClearAll() ? 'Click again to confirm' : 'Clear all chats'"
              (click)="handleClearAll()"
            >
              <sa-icon-trash class="w-3 h-3" />
              {{ confirmClearAll() ? 'Confirm' : 'Clear All' }}
            </button>
          }

          <!-- New chat button -->
          <button
            class="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
            title="New chat"
            (click)="handleNewChat()"
          >
            <sa-icon-plus class="w-3 h-3" />
            New Chat
          </button>
        </div>
      </div>

      <!-- Error message -->
      @if (error()) {
        <p class="text-[10px] text-red-400 bg-red-500/10 px-2 py-1 rounded">{{ error() }}</p>
      }

      <!-- Loading skeleton -->
      @if (isLoading()) {
        <div class="space-y-2">
          <div class="h-10 bg-slate-800 rounded animate-pulse"></div>
          <div class="h-10 bg-slate-800 rounded animate-pulse"></div>
          <div class="h-10 bg-slate-800 rounded animate-pulse"></div>
        </div>
      }

      <!-- Session list grouped by date -->
      @if (!isLoading()) {
        <div class="space-y-3 flex-1 overflow-y-auto">
          @if (sessions().length === 0) {
            <p class="text-xs text-slate-500 text-center py-4">
              No conversations yet. Start typing to begin.
            </p>
          }

          @for (group of GROUP_ORDER; track group) {
            @if (getGroup(group).length > 0) {
              <div>
                <p class="text-[10px] font-mono text-slate-600 uppercase tracking-wider mb-1.5">{{ group }}</p>
                <div class="space-y-1">
                  @for (session of getGroup(group); track session.id) {
                    <div
                      [class]="sessionCardClass(session)"
                      (click)="handleSelectSession(session)"
                    >
                      <div class="flex items-start justify-between gap-2">
                        <div class="flex-1 min-w-0">
                          <!-- Editable title inline -->
                          @if (editingSessionId() === session.id) {
                            <input
                              type="text"
                              class="w-full text-xs text-slate-100 bg-slate-800 border border-primary/50 rounded px-1 py-0.5 focus:outline-none"
                              [value]="editingTitle()"
                              (input)="editingTitle.set($any($event.target).value)"
                              (keydown.enter)="commitRename(session.id)"
                              (keydown.escape)="cancelRename()"
                              (blur)="commitRename(session.id)"
                            />
                          } @else {
                            <p
                              class="text-xs text-slate-200 line-clamp-1"
                              (dblclick)="startRename(session)"
                            >
                              {{ session.title || 'New conversation...' }}
                            </p>
                          }

                          <div class="flex items-center gap-1.5 mt-1">
                            <!-- Mode badge -->
                            <span
                              [class]="modeBadgeClass(session)"
                            >
                              {{ session.mode === 'interactive' ? 'Single Shipment' : 'Batch' }}
                            </span>
                            <span class="text-[10px] font-mono text-slate-500">
                              {{ (session.updated_at || session.created_at) | timeAgo }}
                            </span>
                          </div>
                        </div>

                        <!-- Action buttons (hover-reveal) -->
                        <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            class="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300"
                            title="Export"
                            (click)="handleExport($event, session.id)"
                          >
                            <sa-icon-download class="w-3 h-3" />
                          </button>
                          <button
                            class="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
                            title="Delete"
                            [disabled]="deletingId() === session.id"
                            (click)="handleDelete($event, session.id)"
                          >
                            <sa-icon-trash class="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  }
                </div>
              </div>
            }
          }
        </div>
      }
    </div>
  `,
})
export class ChatSessionsPanelComponent implements OnInit {
  readonly conversationStore = inject(ConversationStore);
  private readonly apiService = inject(ApiService);

  readonly sessions = signal<ChatSessionSummary[]>([]);
  readonly isLoading = signal(true);
  readonly deletingId = signal<string | null>(null);
  readonly isClearingAll = signal(false);
  readonly confirmClearAll = signal(false);
  readonly error = signal<string | null>(null);
  readonly editingSessionId = signal<string | null>(null);
  readonly editingTitle = signal('');

  readonly GROUP_ORDER = GROUP_ORDER;

  /** Build class string for Clear All button (Tailwind v4 opacity syntax). */
  clearAllBtnClass(): string {
    const base = 'flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded transition-colors';
    if (this.confirmClearAll()) {
      return `${base} bg-red-500/20 text-red-400 hover:bg-red-500/30`;
    }
    return `${base} bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-300`;
  }

  /** Build class string for session card (Tailwind v4 opacity syntax). */
  sessionCardClass(session: any): string {
    const base = 'group relative w-full text-left p-2 rounded-md transition-colors cursor-pointer border';
    if (this.conversationStore.sessionId() === session.id) {
      return `${base} bg-primary/10 border-primary/30`;
    }
    return `${base} border-transparent hover:bg-slate-800/50`;
  }

  /** Build class string for mode badge (Tailwind v4 opacity syntax). */
  modeBadgeClass(session: any): string {
    const base = 'text-[9px] font-mono px-1.5 py-0.5 rounded border';
    if (session.mode === 'interactive') {
      return `${base} bg-amber-500/10 text-amber-400 border-amber-500/20`;
    }
    return `${base} bg-primary/10 text-primary border-primary/20`;
  }

  private confirmClearTimer: ReturnType<typeof setTimeout> | null = null;
  private groupedCache = signal<Record<DateGroup, ChatSessionSummary[]>>({
    'Today': [],
    'Yesterday': [],
    'Previous 7 Days': [],
    'Older': [],
  });

  constructor() {
    // Re-fetch sessions whenever chatSessionsVersion changes.
    // chatSessionsVersion is incremented after SSE 'done' events.
    effect(() => {
      this.conversationStore.chatSessionsVersion();
      void this.loadSessions();
    });
  }

  ngOnInit(): void {
    void this.loadSessions();
  }

  /** Get sessions for a specific date group. */
  getGroup(group: DateGroup): ChatSessionSummary[] {
    return this.groupedCache()[group];
  }

  /**
   * Select a session: fetch message history and request restore via the store.
   *
   * Instead of directly writing sessionId/messages to the store (which bypasses
   * ConversationSessionService's SSE reconnection and mode tracking), we set
   * pendingSessionRestore. chat-remote's ChatContainerComponent watches this
   * signal and calls sessionService.loadSession() to properly tear down the
   * old SSE, set sessionMode, and reconnect.
   */
  async handleSelectSession(session: ChatSessionSummary): Promise<void> {
    if (this.conversationStore.sessionId() === session.id) return;
    this.error.set(null);
    try {
      const detail = await firstValueFrom(this.apiService.getConversationMessages(session.id));
      this.conversationStore.setPendingSessionRestore({
        sessionId: session.id,
        mode: session.mode === 'interactive' ? 'interactive' : 'batch',
        messages: detail.messages,
      });
    } catch (err) {
      console.error('Failed to load session:', err);
      this.error.set('Failed to load session');
    }
  }

  /** Start a new chat by resetting conversation store. */
  handleNewChat(): void {
    this.conversationStore.reset();
  }

  /** Export a conversation session as JSON (browser download). */
  async handleExport(event: MouseEvent, sessionId: string): Promise<void> {
    event.stopPropagation();
    this.error.set(null);
    try {
      const blob = await firstValueFrom(this.apiService.exportConversation(sessionId));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `conversation-${sessionId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export session:', err);
      this.error.set('Export failed');
    }
  }

  /** Delete a single session. */
  async handleDelete(event: MouseEvent, sessionId: string): Promise<void> {
    event.stopPropagation();
    this.deletingId.set(sessionId);
    this.error.set(null);
    try {
      await firstValueFrom(this.apiService.deleteConversation(sessionId));
      this.sessions.update((prev) => prev.filter((s) => s.id !== sessionId));
      this.updateGroupedCache();
      // Reset conversation if deleted session was active
      if (this.conversationStore.sessionId() === sessionId) {
        this.conversationStore.reset();
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
      this.error.set('Failed to delete session');
    } finally {
      this.deletingId.set(null);
    }
  }

  /** Clear all sessions (with two-click confirmation). */
  async handleClearAll(): Promise<void> {
    if (!this.confirmClearAll()) {
      this.confirmClearAll.set(true);
      this.confirmClearTimer = setTimeout(() => this.confirmClearAll.set(false), 3000);
      return;
    }
    if (this.confirmClearTimer) clearTimeout(this.confirmClearTimer);
    this.isClearingAll.set(true);
    this.confirmClearAll.set(false);
    this.error.set(null);
    try {
      await firstValueFrom(this.apiService.deleteAllConversations());
      this.sessions.set([]);
      this.updateGroupedCache();
      this.conversationStore.reset();
    } catch (err) {
      console.error('Failed to clear all sessions:', err);
      this.error.set('Failed to clear history');
    } finally {
      this.isClearingAll.set(false);
    }
  }

  /** Start inline rename for a session (double-click title). */
  startRename(session: ChatSessionSummary): void {
    this.editingSessionId.set(session.id);
    this.editingTitle.set(session.title ?? '');
  }

  /** Commit the renamed title to the API. */
  async commitRename(sessionId: string): Promise<void> {
    const title = this.editingTitle().trim();
    this.editingSessionId.set(null);
    if (!title) return;
    try {
      await firstValueFrom(this.apiService.renameConversation(sessionId, title));
      this.sessions.update((prev) =>
        prev.map((s) => s.id === sessionId ? { ...s, title } : s),
      );
      this.updateGroupedCache();
    } catch (err) {
      console.error('Failed to rename session:', err);
    }
  }

  /** Cancel inline rename without saving. */
  cancelRename(): void {
    this.editingSessionId.set(null);
    this.editingTitle.set('');
  }

  private async loadSessions(): Promise<void> {
    this.error.set(null);
    try {
      const data = await firstValueFrom(this.apiService.getConversations());
      this.sessions.set(data);
      this.updateGroupedCache();
    } catch (err) {
      console.error('Failed to load chat sessions:', err);
      this.error.set('Failed to load sessions');
    } finally {
      this.isLoading.set(false);
    }
  }

  private updateGroupedCache(): void {
    this.groupedCache.set(groupByDate(this.sessions()));
  }
}
