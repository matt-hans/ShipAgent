/**
 * Sidebar shell - data source and history layout wrapper.
 */

import { useAppState } from '@/hooks/useAppState';
import { cn } from '@/lib/utils';
import type { Job } from '@/types/api';
import { ChevronIcon, HardDriveIcon, HistoryIcon } from '@/components/ui/icons';
import { ShopifyIcon, DataSourceIcon } from '@/components/ui/brand-icons';
import { DataSourceSection } from '@/components/sidebar/DataSourcePanel';
import { JobHistorySection } from '@/components/sidebar/JobHistoryPanel';
interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onSelectJob: (job: Job | null) => void;
  activeJobId?: string;
}

export function Sidebar({ collapsed, onToggle, onSelectJob, activeJobId }: SidebarProps) {
  const { activeSourceType, activeSourceInfo } = useAppState();

  const hasDataSource = activeSourceType !== null;

  // Determine connection label for tooltip
  const connectionLabel = activeSourceInfo
    ? `Active: ${activeSourceInfo.label}`
    : 'Connect data source';

  return (
    <aside
      className={cn(
        'app-sidebar flex flex-col transition-all duration-300 ease-out',
        collapsed ? 'w-16' : 'w-80'
      )}
    >
      {/* Collapsed state - icon buttons */}
      {collapsed && (
        <div className="flex-1 flex flex-col items-center pt-3 gap-2">
          <button
            onClick={onToggle}
            className={cn(
              'w-10 h-10 flex items-center justify-center rounded-lg transition-colors',
              hasDataSource ? 'bg-primary/20 text-primary' : 'bg-slate-800 text-slate-500 hover:text-slate-300'
            )}
            title={connectionLabel}
          >
            {activeSourceType === 'shopify' ? (
              <div className="relative">
                <ShopifyIcon className="w-5 h-5 text-[#5BBF3D]" />
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-success rounded-full" />
              </div>
            ) : activeSourceType === 'local' ? (
              <div className="relative">
                <HardDriveIcon className="w-5 h-5 text-primary" />
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-success rounded-full" />
              </div>
            ) : (
              <DataSourceIcon className="w-5 h-5" connected={false} />
            )}
          </button>
          <button
            onClick={onToggle}
            className="w-10 h-10 flex items-center justify-center rounded-lg bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
            title="Job history"
          >
            <HistoryIcon className="w-5 h-5" />
          </button>
        </div>
      )}

      {/* Expanded content */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto scrollable">
          {/* Data Source Section */}
          <div className="border-b border-slate-800">
            <DataSourceSection />
          </div>

          {/* Job History Section */}
          <div>
            <JobHistorySection onSelectJob={onSelectJob} activeJobId={activeJobId} />
          </div>
        </div>
      )}

      {/* Collapse Toggle */}
      <div className="mt-auto p-3 border-t border-slate-800">
        <button
          onClick={onToggle}
          className="w-full flex items-center justify-center gap-2 py-2 rounded-md hover:bg-slate-800 transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <ChevronIcon
            direction={collapsed ? 'right' : 'left'}
            className="w-4 h-4 text-slate-500"
          />
          {!collapsed && (
            <span className="text-xs text-slate-500">Collapse</span>
          )}
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
