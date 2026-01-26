/**
 * ShipAgent v2.0 - Refined Industrial Command Center
 *
 * A sophisticated hybrid interface combining conversational AI fluidity
 * with precision engineering controls.
 */

import { CommandCenter } from '@/components/CommandCenter';
import { Sidebar } from '@/components/layout/Sidebar';
import { Header } from '@/components/layout/Header';
import { useAppState, AppStateProvider } from '@/hooks/useAppState';

function AppContent() {
  const { activeJob, setActiveJob, sidebarCollapsed, setSidebarCollapsed } = useAppState();

  return (
    <div className="app-layout">
      <Header />

      <div className="app-main">
        {/* Sidebar - Data sources, job history, quick actions */}
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
          onSelectJob={setActiveJob}
          activeJobId={activeJob?.id}
        />

        {/* Main content - Conversational command interface */}
        <main className="app-content">
          <CommandCenter activeJob={activeJob} />
        </main>
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
