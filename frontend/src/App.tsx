/**
 * ShipAgent v2.0 - Refined Industrial Command Center
 *
 * A sophisticated hybrid interface combining conversational AI fluidity
 * with precision engineering controls.
 */

import { CommandCenter } from '@/components/CommandCenter';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { SettingsFlyout } from '@/components/settings/SettingsFlyout';
import { useAppState, AppStateProvider } from '@/hooks/useAppState';

function AppContent() {
  const { activeJob, setActiveJob, sidebarCollapsed, setSidebarCollapsed } = useAppState();

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
        />

        {/* Main content - Conversational command interface */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <CommandCenter activeJob={activeJob} />
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
