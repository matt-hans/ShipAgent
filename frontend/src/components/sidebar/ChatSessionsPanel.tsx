/**
 * Chat sessions panel for the sidebar.
 *
 * Lists persistent conversation sessions grouped by recency.
 * Supports session switching, deletion, and new chat creation.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { cn, formatTimeAgo } from '@/lib/utils';
import { listConversations, deleteConversation, getConversationMessages, exportConversation } from '@/lib/api';
import type { ChatSessionSummary, PersistedMessage, SessionContext } from '@/types/api';
import type { ConversationMessage } from '@/hooks/useAppState';
import { TrashIcon, PlusIcon, DownloadIcon } from '@/components/ui/icons';

/** Mode badge for session items. */
function ModeBadge({ mode }: { mode: string }) {
  return (
    <span className={cn(
      'text-[9px] font-mono px-1.5 py-0.5 rounded',
      mode === 'interactive'
        ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
        : 'bg-primary/10 text-primary border border-primary/20'
    )}>
      {mode === 'interactive' ? 'Single Shipment' : 'Batch'}
    </span>
  );
}

const MS_PER_DAY = 86_400_000;

/** Group sessions by relative date. */
function groupByDate(sessions: ChatSessionSummary[]): Record<string, ChatSessionSummary[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - MS_PER_DAY);
  const weekAgo = new Date(today.getTime() - 7 * MS_PER_DAY);

  const groups: Record<string, ChatSessionSummary[]> = {};

  for (const session of sessions) {
    const date = new Date(session.created_at);
    let group: string;
    if (date >= today) group = 'Today';
    else if (date >= yesterday) group = 'Yesterday';
    else if (date >= weekAgo) group = 'Previous 7 Days';
    else group = 'Older';

    if (!groups[group]) groups[group] = [];
    groups[group].push(session);
  }

  return groups;
}

interface ChatSessionsPanelProps {
  onLoadSession: (
    sessionId: string,
    mode: 'batch' | 'interactive',
    messages: ConversationMessage[],
    contextData?: SessionContext | null,
  ) => void;
  onNewChat: () => void;
  activeSessionId?: string | null;
}

export function ChatSessionsPanel({
  onLoadSession,
  onNewChat,
  activeSessionId,
}: ChatSessionsPanelProps) {
  const { chatSessionsVersion, setChatSessions } = useAppState();
  const [sessions, setSessions] = React.useState<ChatSessionSummary[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [deletingId, setDeletingId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const loadSessions = React.useCallback(async () => {
    try {
      setError(null);
      const data = await listConversations();
      setSessions(data);
      setChatSessions(data);
    } catch (err) {
      console.error('Failed to load chat sessions:', err);
      setError('Failed to load sessions');
    } finally {
      setIsLoading(false);
    }
  }, [setChatSessions]);

  React.useEffect(() => {
    loadSessions();
  }, [loadSessions, chatSessionsVersion]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setDeletingId(sessionId);
    setError(null);
    try {
      await deleteConversation(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    } catch (err) {
      console.error('Failed to delete session:', err);
      setError('Failed to delete session');
    } finally {
      setDeletingId(null);
    }
  };

  const handleExport = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setError(null);
    try {
      await exportConversation(sessionId);
    } catch (err) {
      console.error('Failed to export session:', err);
      setError('Export failed');
    }
  };

  const handleSelect = async (session: ChatSessionSummary) => {
    if (session.id === activeSessionId) return;
    setError(null);
    try {
      const detail = await getConversationMessages(session.id);
      const messages: ConversationMessage[] = detail.messages.map((m: PersistedMessage) => ({
        id: m.id,
        role: m.role === 'assistant' ? 'system' : m.role as 'user' | 'system',
        content: m.content,
        timestamp: new Date(m.created_at),
        metadata: m.metadata ? m.metadata as ConversationMessage['metadata'] : undefined,
      }));
      onLoadSession(session.id, session.mode as 'batch' | 'interactive', messages, detail.session.context_data || null);
    } catch (err) {
      console.error('Failed to load session:', err);
      setError('Failed to load session');
    }
  };

  const grouped = groupByDate(sessions);
  const groupOrder = ['Today', 'Yesterday', 'Previous 7 Days', 'Older'];

  if (isLoading) {
    return (
      <div className="p-3 space-y-2">
        <div className="h-4 w-24 bg-slate-800 rounded shimmer" />
        <div className="h-10 bg-slate-800 rounded shimmer" />
        <div className="h-10 bg-slate-800 rounded shimmer" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-300">Chat Sessions</span>
        <button
          onClick={onNewChat}
          className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
          title="New chat"
        >
          <PlusIcon className="w-3 h-3" />
          New Chat
        </button>
      </div>

      {error && (
        <p className="text-[10px] text-red-400 bg-red-500/10 px-2 py-1 rounded">
          {error}
        </p>
      )}

      <div className="space-y-3 flex-1 overflow-y-auto scrollable">
        {sessions.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-4">
            No conversations yet. Start typing to begin.
          </p>
        ) : (
          groupOrder.map((group) => {
            const items = grouped[group];
            if (!items || items.length === 0) return null;
            return (
              <div key={group}>
                <p className="text-[10px] font-mono text-slate-600 uppercase tracking-wider mb-1.5">
                  {group}
                </p>
                <div className="space-y-1">
                  {items.map((session) => (
                    <div
                      key={session.id}
                      className={cn(
                        'group relative w-full text-left p-2 rounded-md transition-colors cursor-pointer',
                        'border border-transparent',
                        activeSessionId === session.id
                          ? 'bg-primary/10 border-primary/30'
                          : 'hover:bg-slate-800/50'
                      )}
                      onClick={() => handleSelect(session)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-slate-200 line-clamp-1">
                            {session.title || 'New conversation...'}
                          </p>
                          <div className="flex items-center gap-1.5 mt-1">
                            <ModeBadge mode={session.mode} />
                            <span className="text-[10px] font-mono text-slate-500">
                              {formatTimeAgo(session.updated_at || session.created_at)}
                            </span>
                          </div>
                        </div>
                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => handleExport(e, session.id)}
                            className="p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300"
                            title="Export"
                          >
                            <DownloadIcon className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => handleDelete(e, session.id)}
                            disabled={deletingId === session.id}
                            className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
                            title="Delete"
                          >
                            <TrashIcon className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
