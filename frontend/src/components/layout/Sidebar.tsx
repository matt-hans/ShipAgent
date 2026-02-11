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
import { useExternalSources } from '@/hooks/useExternalSources';
import { cn } from '@/lib/utils';
import { getJobs, deleteJob, connectPlatform, disconnectPlatform, getMergedLabelsUrl } from '@/lib/api';
import type { Job, JobSummary, DataSourceInfo, PlatformType } from '@/types/api';

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
    <svg viewBox="0 0 24 24" fill="none" className={className}>
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="18"
        fontWeight="700"
        fill="currentColor"
      >
        S
      </text>
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

function TrashIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <polyline points="3 6 5 6 21 6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="10" y1="11" x2="10" y2="17" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="14" y1="11" x2="14" y2="17" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PrinterIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <polyline points="6 9 6 2 18 2 18 9" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="6" y="14" width="12" height="8" strokeLinecap="round" strokeLinejoin="round" />
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

// Data Source Section - Unified view with sections
function DataSourceSection() {
  const { dataSource, setDataSource } = useAppState();
  const { state: externalState } = useExternalSources();
  const [isConnecting, setIsConnecting] = React.useState(false);
  const [showShopifyForm, setShowShopifyForm] = React.useState(false);
  const [showDbForm, setShowDbForm] = React.useState(false);
  const [dbConnectionString, setDbConnectionString] = React.useState('');
  const csvInputRef = React.useRef<HTMLInputElement>(null);
  const excelInputRef = React.useRef<HTMLInputElement>(null);

  // Shopify-specific state (for manual entry fallback)
  const [shopifyStoreUrl, setShopifyStoreUrl] = React.useState('');
  const [shopifyAccessToken, setShopifyAccessToken] = React.useState('');
  const [showToken, setShowToken] = React.useState(false);
  const [shopifyError, setShopifyError] = React.useState<string | null>(null);

  // Auto-detected Shopify status from environment
  const shopifyEnvStatus = externalState.shopifyEnvStatus;
  const isCheckingShopifyEnv = externalState.isCheckingEnv;

  // Check if Shopify is connected via environment
  const shopifyEnvConnected = shopifyEnvStatus?.valid === true;

  // File selection handler - connects immediately after file selection
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>, fileType: 'csv' | 'excel') => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsConnecting(true);
    try {
      // Simulated connection - in real app, call backend API via MCP Gateway
      const mockSource: DataSourceInfo = {
        type: fileType,
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
        csv_path: fileType === 'csv' ? file.name : undefined,
        excel_path: fileType === 'excel' ? file.name : undefined,
      };
      setDataSource(mockSource);
    } finally {
      setIsConnecting(false);
      // Reset input so same file can be selected again
      e.target.value = '';
    }
  };

  // Database connection handler
  const handleDbConnect = async () => {
    if (!dbConnectionString.trim()) return;

    setIsConnecting(true);
    try {
      // Simulated connection - in real app, call backend API via MCP Gateway
      const mockSource: DataSourceInfo = {
        type: 'database',
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
      };
      setDataSource(mockSource);
      setDbConnectionString('');
      setShowDbForm(false);
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
        setShowShopifyForm(false);
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

  return (
    <div className="p-3 space-y-4">
      <span className="text-xs font-medium text-slate-300">Data Sources</span>

      {/* === EXTERNAL PLATFORMS SECTION === */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <CloudIcon className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">External Platforms</span>
        </div>

        {/* Shopify Status Card */}
        <div className="rounded-lg border border-slate-800 overflow-hidden">
          <div className="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div className="flex items-center gap-2">
              <ShopifyIcon className="w-5 h-5 text-[#5BBF3D]" />
              <span className="text-xs font-medium text-slate-200">Shopify</span>
            </div>
            {isCheckingShopifyEnv ? (
              <span className="text-[10px] font-mono text-slate-500">Checking...</span>
            ) : shopifyEnvConnected ? (
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                <span className="text-[10px] font-mono text-success">Connected</span>
              </span>
            ) : shopifyEnvStatus?.configured ? (
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-error" />
                <span className="text-[10px] font-mono text-error">Invalid</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                <span className="text-[10px] font-mono text-slate-500">Not configured</span>
              </span>
            )}
          </div>

          {/* Connected state */}
          {shopifyEnvConnected && (
            <div className="p-2.5 border-t border-slate-800">
              <p className="text-xs text-slate-300">
                {shopifyEnvStatus?.store_name || shopifyEnvStatus?.store_url}
              </p>
              <p className="text-[10px] font-mono text-slate-500 mt-0.5">
                Auto-detected from environment
              </p>
            </div>
          )}

          {/* Invalid credentials */}
          {!isCheckingShopifyEnv && shopifyEnvStatus?.configured && !shopifyEnvStatus?.valid && (
            <div className="p-2.5 border-t border-slate-800">
              <p className="text-[10px] font-mono text-slate-400 mb-2">
                {shopifyEnvStatus.error || 'Authentication failed'}
              </p>
              <p className="text-[10px] text-slate-500">
                Check .env credentials
              </p>
            </div>
          )}

          {/* Not configured - show setup hint or form */}
          {!isCheckingShopifyEnv && !shopifyEnvStatus?.configured && (
            <div className="p-2.5 border-t border-slate-800">
              {!showShopifyForm ? (
                <div className="space-y-2">
                  <p className="text-[10px] text-slate-500">
                    Add SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN to .env
                  </p>
                  <button
                    onClick={() => setShowShopifyForm(true)}
                    className="text-[10px] font-medium text-[#96BF48] hover:underline"
                  >
                    Or enter credentials manually →
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {/* Store URL */}
                  <input
                    type="text"
                    value={shopifyStoreUrl}
                    onChange={(e) => setShopifyStoreUrl(e.target.value)}
                    placeholder="mystore.myshopify.com"
                    className="w-full px-2.5 py-1.5 text-xs font-mono rounded bg-void-900 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-[#96BF48]"
                  />
                  {/* Access Token */}
                  <div className="relative">
                    <input
                      type={showToken ? 'text' : 'password'}
                      value={shopifyAccessToken}
                      onChange={(e) => setShopifyAccessToken(e.target.value)}
                      placeholder="shpat_xxxxxxxxxxxxx"
                      className="w-full px-2.5 py-1.5 pr-8 text-xs font-mono rounded bg-void-900 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-[#96BF48]"
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken(!showToken)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                    >
                      {showToken ? <EyeOffIcon className="w-3.5 h-3.5" /> : <EyeIcon className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  {shopifyError && (
                    <p className="text-[10px] font-mono text-error">{shopifyError}</p>
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={() => setShowShopifyForm(false)}
                      className="flex-1 py-1.5 text-xs font-medium rounded border border-slate-700 text-slate-400 hover:text-slate-200"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleShopifyConnect}
                      disabled={!shopifyStoreUrl.trim() || !shopifyAccessToken.trim() || isConnecting}
                      className="flex-1 py-1.5 text-xs font-medium rounded text-white disabled:opacity-50"
                      style={{ backgroundColor: '#96BF48' }}
                    >
                      {isConnecting ? 'Connecting...' : 'Connect'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* === LOCAL FILES SECTION === */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <HardDriveIcon className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Local Files</span>
        </div>

        {/* Connected local data source */}
        {dataSource?.status === 'connected' && (
          <div className="rounded-lg border border-success/30 bg-success/5 p-2.5">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                <span className="text-xs font-medium text-slate-200">{dataSource.type.toUpperCase()}</span>
              </div>
              <button
                onClick={handleDisconnect}
                className="text-[10px] font-mono text-error hover:underline"
              >
                Disconnect
              </button>
            </div>
            <div className="flex gap-4 text-[10px] font-mono">
              <span className="text-slate-500">
                Rows: <span className="text-success">{dataSource.row_count?.toLocaleString() || '...'}</span>
              </span>
              <span className="text-slate-500">
                Cols: <span className="text-slate-300">{dataSource.column_count}</span>
              </span>
            </div>
          </div>
        )}

        {/* File picker buttons - minimalist design */}
        {!dataSource?.status && (
          <>
            {/* Hidden file inputs */}
            <input
              type="file"
              ref={csvInputRef}
              onChange={(e) => handleFileSelect(e, 'csv')}
              accept=".csv"
              className="hidden"
            />
            <input
              type="file"
              ref={excelInputRef}
              onChange={(e) => handleFileSelect(e, 'excel')}
              accept=".xlsx,.xls"
              className="hidden"
            />

            {/* File type buttons */}
            <div className="flex gap-2">
              <button
                onClick={() => csvInputRef.current?.click()}
                disabled={isConnecting}
                className="flex-1 py-2 px-3 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 transition-colors text-xs font-medium text-slate-300 disabled:opacity-50"
              >
                CSV
              </button>
              <button
                onClick={() => excelInputRef.current?.click()}
                disabled={isConnecting}
                className="flex-1 py-2 px-3 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 transition-colors text-xs font-medium text-slate-300 disabled:opacity-50"
              >
                Excel
              </button>
              <button
                onClick={() => setShowDbForm(!showDbForm)}
                disabled={isConnecting}
                className={cn(
                  'flex-1 py-2 px-3 rounded-lg border transition-colors text-xs font-medium disabled:opacity-50',
                  showDbForm
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300'
                )}
              >
                Database
              </button>
            </div>

            {/* Database connection form (only shows when DB selected) */}
            {showDbForm && (
              <div className="space-y-2 pt-1">
                <input
                  type="text"
                  value={dbConnectionString}
                  onChange={(e) => setDbConnectionString(e.target.value)}
                  placeholder="postgresql://user:pass@host:5432/db"
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded bg-void-900 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
                />
                <button
                  onClick={handleDbConnect}
                  disabled={!dbConnectionString.trim() || isConnecting}
                  className="w-full btn-primary py-1.5 text-xs font-medium disabled:opacity-50"
                >
                  {isConnecting ? 'Connecting...' : 'Connect'}
                </button>
              </div>
            )}

            {isConnecting && (
              <p className="text-[10px] font-mono text-slate-500 text-center">Connecting...</p>
            )}
          </>
        )}
      </div>
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
  const { jobListVersion } = useAppState();
  const [jobs, setJobs] = React.useState<JobSummary[]>([]);
  const [search, setSearch] = React.useState('');
  const [filter, setFilter] = React.useState<string>('all');
  const [isLoading, setIsLoading] = React.useState(true);
  const [deletingJobId, setDeletingJobId] = React.useState<string | null>(null);

  // Load job history
  const loadJobs = React.useCallback(async () => {
    try {
      const jobsData = await getJobs({ limit: 20 });
      setJobs(jobsData.jobs);
    } catch (err) {
      console.error('Failed to load history:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Re-fetch when jobListVersion changes (triggered by batch completion)
  React.useEffect(() => {
    loadJobs();
  }, [loadJobs, jobListVersion]);

  // Delete job handler
  const handleDeleteJob = async (e: React.MouseEvent, jobId: string) => {
    e.stopPropagation(); // Prevent selecting the job
    setDeletingJobId(jobId);
    try {
      await deleteJob(jobId);
      // Remove from local state
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
      // Clear selection if deleted job was active
      if (activeJobId === jobId) {
        onSelectJob(null);
      }
    } catch (err) {
      console.error('Failed to delete job:', err);
    } finally {
      setDeletingJobId(null);
    }
  };

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
        <span className="text-xs font-medium text-slate-300">Shipment History</span>
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
          className="w-full pl-8 pr-3 py-2 text-xs font-mono rounded-md bg-void-900 border border-slate-800 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
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
            <div
              key={job.id}
              className={cn(
                'group relative w-full text-left p-2.5 rounded-md transition-colors cursor-pointer',
                'border border-transparent',
                activeJobId === job.id
                  ? 'bg-primary/10 border-primary/30'
                  : 'hover:bg-slate-800/50'
              )}
              onClick={() => onSelectJob(job as Job)}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs text-slate-200 line-clamp-2 flex-1">
                  {job.original_command || job.name || 'Untitled job'}
                </p>
                <div className="flex items-center gap-1.5">
                  <StatusBadge status={job.status} />
                  {job.status === 'completed' && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(getMergedLabelsUrl(job.id), '_blank');
                      }}
                      className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-cyan-500/20 text-slate-500 hover:text-cyan-400"
                      title="Reprint labels"
                    >
                      <PrinterIcon className="w-3.5 h-3.5" />
                    </button>
                  )}
                  <button
                    onClick={(e) => handleDeleteJob(e, job.id)}
                    disabled={deletingJobId === job.id}
                    className={cn(
                      'p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity',
                      'hover:bg-error/20 text-slate-500 hover:text-error',
                      deletingJobId === job.id && 'opacity-100 animate-pulse'
                    )}
                    title="Delete job"
                  >
                    <TrashIcon className="w-3.5 h-3.5" />
                  </button>
                </div>
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
            </div>
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
  const { state: externalState } = useExternalSources();

  // Check if any data source is connected (local or Shopify env)
  const shopifyEnvConnected = externalState.shopifyEnvStatus?.valid === true;
  const hasDataSource = !!dataSource || shopifyEnvConnected;

  // Determine connection label for tooltip
  const connectionLabel = dataSource
    ? `Connected: ${dataSource.type.toUpperCase()}`
    : shopifyEnvConnected
    ? `Connected: Shopify`
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
            <DataSourceIcon className="w-5 h-5" connected={hasDataSource} />
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
