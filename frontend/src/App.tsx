/**
 * ShipAgent v2.0 - Refined Industrial Command Center
 *
 * A sophisticated hybrid interface combining conversational AI fluidity
 * with precision engineering controls.
 */

import * as React from 'react';
import { CommandCenter, type CommandCenterHandle } from '@/components/CommandCenter';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { SettingsFlyout } from '@/components/settings/SettingsFlyout';
import { useAppState, AppStateProvider } from '@/hooks/useAppState';
import type { ConversationMessage } from '@/hooks/useAppState';

function AppContent() {
  const {
    activeJob,
    setActiveJob,
    sidebarCollapsed,
    setSidebarCollapsed,
    conversationSessionId,
  } = useAppState();

  const commandCenterRef = React.useRef<CommandCenterHandle>(null);

  const handleLoadSession = React.useCallback(
    (sessionId: string, mode: 'batch' | 'interactive', messages: ConversationMessage[]) => {
      commandCenterRef.current?.loadSession(sessionId, mode, messages);
    },
    [],
  );

  const handleNewChat = React.useCallback(() => {
    commandCenterRef.current?.newChat();
  }, []);

  return (
    <div className="h-screen flex flex-col bg-background overflow-hidden">
      <Header />

      <div className="flex-1 flex overflow-hidden relative">
        {/* Sidebar - Data sources, job history, quick actions */}
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
          onSelectJob={setActiveJob}
          activeJobId={activeJob?.id}
          onLoadSession={handleLoadSession}
          onNewChat={handleNewChat}
          activeSessionId={conversationSessionId}
        />

        {/* Main content - Conversational command interface */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <CommandCenter ref={commandCenterRef} activeJob={activeJob} />
        </main>

        {/* Settings flyout - Overlays on desktop, pushes on mobile */}
        <SettingsFlyout />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AppStateProvider>
      <AppContent />
    </AppStateProvider>
  );
}
