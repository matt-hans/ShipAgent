/**
 * Chat history flyout panel.
 *
 * Slides in from the right edge, displaying the ChatSessionsPanel.
 * Auto-closes when a session is selected.
 */

import { X } from 'lucide-react';
import { useAppState } from '@/hooks/useAppState';
import { ChatSessionsPanel } from '@/components/sidebar/ChatSessionsPanel';
import type { ConversationMessage } from '@/hooks/useAppState';
import type { SessionContext } from '@/types/api';

interface ChatHistoryFlyoutProps {
  onLoadSession: (sessionId: string, mode: 'batch' | 'interactive', messages: ConversationMessage[], contextData?: SessionContext | null) => void;
  onNewChat: () => void;
  activeSessionId?: string | null;
}

export function ChatHistoryFlyout({ onLoadSession, onNewChat, activeSessionId }: ChatHistoryFlyoutProps) {
  const { chatHistoryFlyoutOpen, setChatHistoryFlyoutOpen } = useAppState();

  if (!chatHistoryFlyoutOpen) return null;

  const handleLoadSession = (sessionId: string, mode: 'batch' | 'interactive', messages: ConversationMessage[], contextData?: SessionContext | null) => {
    onLoadSession(sessionId, mode, messages, contextData);
    setChatHistoryFlyoutOpen(false);
  };

  const handleNewChat = () => {
    onNewChat();
    setChatHistoryFlyoutOpen(false);
  };

  return (
    <>
      <div
        className="chat-history-backdrop"
        onClick={() => setChatHistoryFlyoutOpen(false)}
      />

      <aside className="chat-history-flyout">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">Chat History</h2>
          <button
            onClick={() => setChatHistoryFlyoutOpen(false)}
            className="p-1 rounded-md hover:bg-muted transition-colors"
            aria-label="Close chat history"
          >
            <X className="h-5 w-5 text-muted-foreground" />
          </button>
        </div>

        <div className="chat-history-flyout-content">
          <ChatSessionsPanel
            onLoadSession={handleLoadSession}
            onNewChat={handleNewChat}
            activeSessionId={activeSessionId}
          />
        </div>
      </aside>
    </>
  );
}

export default ChatHistoryFlyout;
