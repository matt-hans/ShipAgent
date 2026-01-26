/**
 * Sidebar component - Data sources, job history, and quick actions.
 *
 * Features:
 * - Collapsible sidebar
 * - Data source manager with file browser
 * - Job history with search and filters
 * - Quick action buttons
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { cn } from '@/lib/utils';
import { getJobs } from '@/lib/api';
import type { Job, JobSummary, DataSourceType, DataSourceInfo } from '@/types/api';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onSelectJob: (job: Job | null) => void;
  activeJobId?: string;
}

// Icons
function ChevronIcon({ direction, className }: { direction: 'left' | 'right'; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      {direction === 'left' ? (
        <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  );
}

function FolderIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}


function SearchIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <circle cx="11" cy="11" r="8" />
      <path d="M21 21l-4.35-4.35" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}



// Status badge component
function StatusBadge({ status }: { status: string }) {
  const getStatusStyle = (s: string) => {
    switch (s) {
      case 'completed':
        return 'badge-success';
      case 'running':
        return 'badge-info';
      case 'failed':
        return 'badge-error';
      case 'pending':
        return 'badge-neutral';
      case 'cancelled':
        return 'badge-warning';
      default:
        return 'badge-neutral';
    }
  };

  return (
    <span className={cn('badge text-[10px]', getStatusStyle(status))}>
      {status}
    </span>
  );
}

// Data Source Section
function DataSourceSection() {
  const { dataSource, setDataSource } = useAppState();
  const [activeTab, setActiveTab] = React.useState<DataSourceType>('csv');
  const [filePath, setFilePath] = React.useState('');
  const [isConnecting, setIsConnecting] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleConnect = async () => {
    if (!filePath.trim()) return;

    setIsConnecting(true);
    try {
      // Simulated connection - in real app, call backend API
      const mockSource: DataSourceInfo = {
        type: activeTab,
        status: 'connected' as const,
        row_count: Math.floor(Math.random() * 5000) + 100,
        column_count: 8,
        columns: [
          { name: 'order_id', type: 'INTEGER' as const, nullable: false, warnings: [] },
          { name: 'recipient_name', type: 'VARCHAR' as const, nullable: false, warnings: [] },
          { name: 'address', type: 'VARCHAR' as const, nullable: false, warnings: [] },
          { name: 'city', type: 'VARCHAR' as const, nullable: false, warnings: [] },
          { name: 'state', type: 'VARCHAR' as const, nullable: false, warnings: [] },
          { name: 'zip', type: 'VARCHAR' as const, nullable: false, warnings: [] },
        ],
        connected_at: new Date().toISOString(),
        csv_path: activeTab === 'csv' ? filePath : undefined,
        excel_path: activeTab === 'excel' ? filePath : undefined,
      };
      setDataSource(mockSource);
      setFilePath('');
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = () => {
    setDataSource(null);
  };

  const handleFileBrowse = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setFilePath(file.name);
    }
  };

  if (dataSource?.status === 'connected') {
    return (
      <div className="p-3 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-slate-300">Data Source</span>
          <button
            onClick={handleDisconnect}
            className="text-[10px] font-mono text-error hover:underline"
          >
            Disconnect
          </button>
        </div>

        <div className="p-3 rounded-lg bg-success/5 border border-success/20">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-success pulse-glow" />
            <span className="text-xs font-mono text-success">Connected</span>
          </div>
          <div className="space-y-1 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-slate-500">Type</span>
              <span className="text-slate-300">{dataSource.type.toUpperCase()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Rows</span>
              <span className="text-success">{dataSource.row_count?.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Columns</span>
              <span className="text-slate-300">{dataSource.column_count}</span>
            </div>
          </div>
        </div>

        {/* Schema preview */}
        <div className="space-y-2">
          <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Schema</span>
          <div className="max-h-32 overflow-y-auto rounded-md border border-slate-800">
            {dataSource.columns?.map((col, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-2 py-1.5 text-xs border-b border-slate-800 last:border-0"
              >
                <span className="font-mono text-slate-300">{col.name}</span>
                <span className="font-mono text-slate-500 text-[10px]">{col.type}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <span className="text-xs font-medium text-slate-300">Connect Data Source</span>

      {/* Tab selector */}
      <div className="flex rounded-md bg-slate-900 p-0.5 border border-slate-800">
        {(['csv', 'excel', 'database'] as DataSourceType[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'flex-1 px-2 py-1.5 text-xs font-mono rounded-sm transition-colors',
              activeTab === tab
                ? 'bg-amber-500 text-void-950'
                : 'text-slate-400 hover:text-slate-200'
            )}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      {/* File input */}
      <div className="space-y-2">
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileSelect}
          accept={activeTab === 'csv' ? '.csv' : activeTab === 'excel' ? '.xlsx,.xls' : undefined}
          className="hidden"
        />

        <div className="flex gap-2">
          <input
            type="text"
            value={filePath}
            onChange={(e) => setFilePath(e.target.value)}
            placeholder={activeTab === 'database' ? 'Connection string...' : 'Path to file...'}
            className="flex-1 px-3 py-2 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-amber-500"
          />
          {activeTab !== 'database' && (
            <button
              onClick={handleFileBrowse}
              className="p-2 rounded-md bg-slate-800 border border-slate-700 hover:bg-slate-700 transition-colors"
              title="Browse files"
            >
              <FolderIcon className="w-4 h-4 text-slate-400" />
            </button>
          )}
        </div>

        <button
          onClick={handleConnect}
          disabled={!filePath.trim() || isConnecting}
          className="w-full btn-primary py-2 text-xs font-medium disabled:opacity-50"
        >
          {isConnecting ? 'Connecting...' : 'Connect'}
        </button>
      </div>

      {/* Help text */}
      <p className="text-[10px] font-mono text-slate-500">
        {activeTab === 'csv' && 'Upload a CSV file or enter the path on the server.'}
        {activeTab === 'excel' && 'Upload an Excel file (.xlsx) to import data.'}
        {activeTab === 'database' && 'postgresql://user:pass@host:5432/dbname'}
      </p>
    </div>
  );
}

// Job History Section
function JobHistorySection({
  onSelectJob,
  activeJobId,
}: {
  onSelectJob: (job: Job | null) => void;
  activeJobId?: string;
}) {
  const [jobs, setJobs] = React.useState<JobSummary[]>([]);
  const [search, setSearch] = React.useState('');
  const [filter, setFilter] = React.useState<string>('all');
  const [isLoading, setIsLoading] = React.useState(true);

  // Load job history
  React.useEffect(() => {
    const loadData = async () => {
      try {
        const jobsData = await getJobs({ limit: 20 });
        setJobs(jobsData.jobs);
      } catch (err) {
        console.error('Failed to load history:', err);
      } finally {
        setIsLoading(false);
      }
    };
    loadData();
  }, []);

  // Filter jobs
  const filteredJobs = React.useMemo(() => {
    return jobs.filter((job) => {
      const matchesSearch = !search || job.original_command?.toLowerCase().includes(search.toLowerCase());
      const matchesFilter = filter === 'all' || job.status === filter;
      return matchesSearch && matchesFilter;
    });
  }, [jobs, search, filter]);

  const formatTimeAgo = (date: string) => {
    const diff = Date.now() - new Date(date).getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'Just now';
  };

  if (isLoading) {
    return (
      <div className="p-3 space-y-2">
        <div className="h-4 w-24 bg-slate-800 rounded shimmer" />
        <div className="h-12 bg-slate-800 rounded shimmer" />
        <div className="h-12 bg-slate-800 rounded shimmer" />
        <div className="h-12 bg-slate-800 rounded shimmer" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-300">Job History</span>
        <span className="text-[10px] font-mono text-slate-500">{jobs.length} jobs</span>
      </div>

      {/* Search */}
      <div className="relative">
        <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search commands..."
          className="w-full pl-8 pr-3 py-2 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-amber-500"
        />
      </div>

      {/* Filter */}
      <div className="flex gap-1">
        {['all', 'completed', 'running', 'failed'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'px-2 py-1 text-[10px] font-mono rounded transition-colors',
              filter === f
                ? 'bg-slate-700 text-slate-100'
                : 'text-slate-500 hover:text-slate-300'
            )}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Job list */}
      <div className="space-y-1.5 max-h-[300px] overflow-y-auto scrollable">
        {filteredJobs.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-4">No jobs found</p>
        ) : (
          filteredJobs.map((job) => (
            <button
              key={job.id}
              onClick={() => onSelectJob(job as Job)}
              className={cn(
                'w-full text-left p-2.5 rounded-md transition-colors',
                'border border-transparent',
                activeJobId === job.id
                  ? 'bg-amber-500/10 border-amber-500/30'
                  : 'hover:bg-slate-800/50'
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs text-slate-200 line-clamp-2 flex-1">
                  {job.original_command || job.name || 'Untitled job'}
                </p>
                <StatusBadge status={job.status} />
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-[10px] font-mono text-slate-500">
                  {formatTimeAgo(job.created_at)}
                </span>
                {job.total_rows > 0 && (
                  <>
                    <span className="text-slate-700">·</span>
                    <span className="text-[10px] font-mono text-slate-500">
                      {job.successful_rows}/{job.total_rows} rows
                    </span>
                  </>
                )}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

// Mini icons for collapsed state
function DataSourceIcon({ className, connected }: { className?: string; connected?: boolean }) {
  return (
    <div className="relative">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
        <ellipse cx="12" cy="6" rx="8" ry="3" />
        <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
        <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
      </svg>
      {connected && (
        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-success rounded-full" />
      )}
    </div>
  );
}

function HistoryIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12,6 12,12 16,14" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Sidebar({ collapsed, onToggle, onSelectJob, activeJobId }: SidebarProps) {
  const { dataSource } = useAppState();

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
              dataSource ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-800 text-slate-500 hover:text-slate-300'
            )}
            title={dataSource ? `Connected: ${dataSource.type.toUpperCase()}` : 'Connect data source'}
          >
            <DataSourceIcon className="w-5 h-5" connected={!!dataSource} />
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
