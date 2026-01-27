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
import { getJobs, connectPlatform, disconnectPlatform } from '@/lib/api';
import type { Job, JobSummary, DataSourceInfo, PlatformType } from '@/types/api';

/** Source category - Local files or External platforms. */
type SourceCategory = 'local' | 'external';

/** Local source types. */
type LocalSourceType = 'csv' | 'excel' | 'database';

/** Local source metadata. */
const LOCAL_SOURCES: Record<LocalSourceType, { label: string; placeholder: string; help: string; hasFileBrowser: boolean }> = {
  csv: {
    label: 'CSV',
    placeholder: 'Path to file...',
    help: 'Upload a CSV file or enter the path on the server.',
    hasFileBrowser: true,
  },
  excel: {
    label: 'EXCEL',
    placeholder: 'Path to file...',
    help: 'Upload an Excel file (.xlsx) to import data.',
    hasFileBrowser: true,
  },
  database: {
    label: 'DATABASE',
    placeholder: 'Connection string...',
    help: 'postgresql://user:pass@host:5432/dbname',
    hasFileBrowser: false,
  },
};

/* Future: more external platforms like WooCommerce, SAP, Oracle */

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

function HardDriveIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M22 12H2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="6" y1="16" x2="6.01" y2="16" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="10" y1="16" x2="10.01" y2="16" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CloudIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M18 10h-1.26A8 8 0 109 20h9a5 5 0 000-10z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ShopifyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M15.337 3.415c-.022-.165-.122-.247-.247-.255-.124-.008-2.794-.206-2.794-.206l-1.874-1.874c-.206-.206-.618-.144-.782-.082-.008 0-.412.124-.824.247-.082-.247-.247-.577-.454-.907C7.96.082 7.136 0 6.52 0 4.853.04 3.226 1.38 2.567 3.54c-.866 2.834-1.38 5.08-1.38 5.08l5.41 1.134s.866-5.08 1.133-6.627c.082-.515.577-.824 1.05-.865.495-.041 1.009-.082 1.503-.123.495-.041.99-.082 1.483-.123.537-.041 1.05-.082 1.503-.082-.041-.33-.082-.66-.124-.99zm-3.62 1.174c-.412.123-.866.247-1.38.412l.082-.577c.165-1.174.618-1.916 1.298-2.39-.041.865-.041 1.73 0 2.555zm-1.957-1.38c.082-.577.206-1.133.371-1.627.66.33 1.215.988 1.462 1.874-.577.165-1.215.371-1.833.536.041-.288.082-.536.082-.783h-.082zM9.01 2.546c.247 0 .495.041.701.123-.288.824-.495 1.833-.577 2.834-.66.206-1.298.371-1.916.577C7.588 4.34 8.163 2.628 9.01 2.546z"/>
      <path d="M15.09 3.16c-.124 0-.33.082-.495.082-1.421 3.374-3.49 6.955-5.863 10.328.66.165 1.298.33 1.916.495.618.165 1.174.288 1.586.371-.165.742-.33 1.421-.495 2.06-.165.66-.288 1.257-.371 1.792h4.028c.33-2.555.783-5.71 1.339-9.414.33-2.184.618-3.95.824-5.287-.825-.206-1.586-.371-2.47-.427z"/>
    </svg>
  );
}

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="1" y1="1" x2="23" y2="23" strokeLinecap="round" strokeLinejoin="round" />
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
  const [category, setCategory] = React.useState<SourceCategory>('local');
  const [localTab, setLocalTab] = React.useState<LocalSourceType>('csv');
  const [filePath, setFilePath] = React.useState('');
  const [isConnecting, setIsConnecting] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // Shopify-specific state
  const [shopifyStoreUrl, setShopifyStoreUrl] = React.useState('');
  const [shopifyAccessToken, setShopifyAccessToken] = React.useState('');
  const [showToken, setShowToken] = React.useState(false);
  const [shopifyError, setShopifyError] = React.useState<string | null>(null);

  const currentLocalMeta = LOCAL_SOURCES[localTab];

  // Local source connection
  const handleLocalConnect = async () => {
    if (!filePath.trim()) return;

    setIsConnecting(true);
    try {
      // Simulated connection - in real app, call backend API via MCP Gateway
      const mockSource: DataSourceInfo = {
        type: localTab,
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
        csv_path: localTab === 'csv' ? filePath : undefined,
        excel_path: localTab === 'excel' ? filePath : undefined,
      };
      setDataSource(mockSource);
      setFilePath('');
    } finally {
      setIsConnecting(false);
    }
  };

  // Shopify connection
  const handleShopifyConnect = async () => {
    if (!shopifyStoreUrl.trim() || !shopifyAccessToken.trim()) return;

    setIsConnecting(true);
    setShopifyError(null);

    try {
      // Format store URL (ensure it's just the domain)
      let storeUrl = shopifyStoreUrl.trim();
      if (!storeUrl.includes('.myshopify.com')) {
        storeUrl = `${storeUrl}.myshopify.com`;
      }
      storeUrl = storeUrl.replace(/^https?:\/\//, '');

      // Call the backend API to connect to Shopify
      const result = await connectPlatform(
        'shopify' as PlatformType,
        { access_token: shopifyAccessToken.trim() },
        storeUrl
      );

      if (result.success) {
        // Set as connected data source (mock for now - backend will handle actual data)
        const mockSource: DataSourceInfo = {
          type: 'csv', // Backend will expose Shopify as a data source
          status: 'connected' as const,
          row_count: 0, // Will be populated after fetching orders
          column_count: 12,
          columns: [
            { name: 'order_id', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'order_number', type: 'VARCHAR' as const, nullable: true, warnings: [] },
            { name: 'customer_name', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'ship_to_name', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'ship_to_address1', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'ship_to_city', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'ship_to_state', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'ship_to_postal_code', type: 'VARCHAR' as const, nullable: false, warnings: [] },
            { name: 'ship_to_country', type: 'VARCHAR' as const, nullable: false, warnings: [] },
          ],
          connected_at: new Date().toISOString(),
        };
        setDataSource(mockSource);
        // Clear form
        setShopifyStoreUrl('');
        setShopifyAccessToken('');
      } else {
        setShopifyError(result.error || 'Failed to connect to Shopify');
      }
    } catch (err) {
      setShopifyError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      // If it was a Shopify connection, disconnect via API
      await disconnectPlatform('shopify' as PlatformType);
    } catch {
      // Ignore errors - clear local state anyway
    }
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

  // Connected state view
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
            <span className="text-xs font-mono text-success">Connected via MCP Gateway</span>
          </div>
          <div className="space-y-1 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-slate-500">Type</span>
              <span className="text-slate-300">{dataSource.type.toUpperCase()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Rows</span>
              <span className="text-success">{dataSource.row_count?.toLocaleString() || 'Loading...'}</span>
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

      {/* Category toggle - Local vs External */}
      <div className="grid grid-cols-2 rounded-md bg-slate-900 p-0.5 border border-slate-800">
        <button
          onClick={() => setCategory('local')}
          className={cn(
            'flex items-center justify-center gap-1.5 px-3 py-2 text-[11px] font-medium rounded-sm transition-colors',
            category === 'local'
              ? 'bg-slate-700 text-slate-100'
              : 'text-slate-400 hover:text-slate-200'
          )}
        >
          <HardDriveIcon className="w-3.5 h-3.5" />
          Local
        </button>
        <button
          onClick={() => setCategory('external')}
          className={cn(
            'flex items-center justify-center gap-1.5 px-3 py-2 text-[11px] font-medium rounded-sm transition-colors',
            category === 'external'
              ? 'bg-slate-700 text-slate-100'
              : 'text-slate-400 hover:text-slate-200'
          )}
        >
          <CloudIcon className="w-3.5 h-3.5" />
          External
        </button>
      </div>

      {/* Local source tabs and form */}
      {category === 'local' && (
        <>
          {/* Local source tabs */}
          <div className="grid grid-cols-3 rounded-md bg-slate-900 p-0.5 border border-slate-800">
            {(Object.keys(LOCAL_SOURCES) as LocalSourceType[]).map((tab) => {
              const meta = LOCAL_SOURCES[tab];
              return (
                <button
                  key={tab}
                  onClick={() => setLocalTab(tab)}
                  className={cn(
                    'px-2 py-1.5 text-[10px] font-mono rounded-sm transition-colors',
                    localTab === tab
                      ? 'bg-amber-500 text-void-950'
                      : 'text-slate-400 hover:text-slate-200'
                  )}
                >
                  {meta.label}
                </button>
              );
            })}
          </div>

          {/* Local source input */}
          <div className="space-y-2">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept={localTab === 'csv' ? '.csv' : localTab === 'excel' ? '.xlsx,.xls' : undefined}
              className="hidden"
            />

            <div className="flex gap-2">
              <input
                type="text"
                value={filePath}
                onChange={(e) => setFilePath(e.target.value)}
                placeholder={currentLocalMeta.placeholder}
                className="flex-1 px-3 py-2 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-amber-500"
              />
              {currentLocalMeta.hasFileBrowser && (
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
              onClick={handleLocalConnect}
              disabled={!filePath.trim() || isConnecting}
              className="w-full btn-primary py-2 text-xs font-medium disabled:opacity-50"
            >
              {isConnecting ? 'Connecting...' : 'Connect'}
            </button>
          </div>

          {/* Help text */}
          <p className="text-[10px] font-mono text-slate-500">
            {currentLocalMeta.help}
          </p>
        </>
      )}

      {/* External platforms (Shopify) */}
      {category === 'external' && (
        <>
          {/* Shopify header */}
          <div className="flex items-center gap-2 p-2 rounded-md bg-[#96BF48]/10 border border-[#96BF48]/20">
            <ShopifyIcon className="w-5 h-5 text-[#96BF48]" />
            <span className="text-xs font-medium text-[#96BF48]">Shopify</span>
          </div>

          {/* Shopify credentials form */}
          <div className="space-y-2">
            {/* Store URL */}
            <div className="space-y-1">
              <label className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                Store URL
              </label>
              <input
                type="text"
                value={shopifyStoreUrl}
                onChange={(e) => setShopifyStoreUrl(e.target.value)}
                placeholder="mystore.myshopify.com"
                className="w-full px-3 py-2 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-[#96BF48]"
              />
            </div>

            {/* Access Token */}
            <div className="space-y-1">
              <label className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                Admin API Access Token
              </label>
              <div className="relative">
                <input
                  type={showToken ? 'text' : 'password'}
                  value={shopifyAccessToken}
                  onChange={(e) => setShopifyAccessToken(e.target.value)}
                  placeholder="shpat_xxxxxxxxxxxxxxxxxxxxx"
                  className="w-full px-3 py-2 pr-10 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-[#96BF48]"
                />
                <button
                  type="button"
                  onClick={() => setShowToken(!showToken)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 hover:text-slate-300"
                  title={showToken ? 'Hide token' : 'Show token'}
                >
                  {showToken ? (
                    <EyeOffIcon className="w-4 h-4" />
                  ) : (
                    <EyeIcon className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            {/* Error message */}
            {shopifyError && (
              <div className="p-2 rounded-md bg-error/10 border border-error/20">
                <p className="text-[10px] font-mono text-error">{shopifyError}</p>
              </div>
            )}

            <button
              onClick={handleShopifyConnect}
              disabled={!shopifyStoreUrl.trim() || !shopifyAccessToken.trim() || isConnecting}
              className="w-full btn-primary py-2 text-xs font-medium disabled:opacity-50"
              style={{ backgroundColor: '#96BF48' }}
            >
              {isConnecting ? 'Connecting...' : 'Connect to Shopify'}
            </button>
          </div>

          {/* Help text */}
          <p className="text-[10px] font-mono text-slate-500">
            Get your Admin API access token from Shopify Admin → Settings → Apps → Develop apps.
          </p>
        </>
      )}
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
