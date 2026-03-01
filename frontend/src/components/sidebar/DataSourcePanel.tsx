/**
 * Data source management panel for the sidebar.
 *
 * Handles local file import (CSV/Excel), database connections,
 * federated platform integration (Shopify, Amazon, etc.), and source switching.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { cn } from '@/lib/utils';
import {
  disconnectDataSource,
  importDataSource,
  uploadDataSource,
  getSavedDataSources,
  reconnectSavedSource,
  getDataSourceStatus,
} from '@/lib/api';
import type { DataSourceInfo, DataSourceType, FederatedPlatform } from '@/types/api';
import { RecentSourcesModal } from '@/components/RecentSourcesModal';
import { toDataSourceColumns } from '@/components/sidebar/dataSourceMappers';
import { HardDriveIcon, InfoIcon } from '@/components/ui/icons';
import {
  ShopifyIcon,
  AmazonIcon,
  WooCommerceIcon,
  SAPIcon,
  OracleIcon,
  PlatformIcon,
} from '@/components/ui/brand-icons';
import { Switch } from '@/components/ui/switch';

/** Extracts a display filename from a DataSourceInfo. */
export function extractFileName(ds: DataSourceInfo): string | null {
  const path = ds.csv_path || ds.excel_path || ds.file_path;
  if (!path) return null;
  const segments = path.split('/');
  return segments[segments.length - 1] || null;
}

/** Brand color for each known platform. */
const PLATFORM_COLORS: Record<string, string> = {
  shopify: '#5BBF3D',
  amazon: '#FF9900',
  woocommerce: '#7F54B3',
  sap: '#0070F2',
  oracle: '#C74634',
};

/** Icon component for each known platform. Falls back to generic. */
function getPlatformIcon(platformId: string, className?: string) {
  const icons: Record<string, React.FC<{ className?: string }>> = {
    shopify: ShopifyIcon,
    amazon: AmazonIcon,
    woocommerce: WooCommerceIcon,
    sap: SAPIcon,
    oracle: OracleIcon,
  };
  const Icon = icons[platformId] || PlatformIcon;
  return <Icon className={className} />;
}

/** Connection status badge for a platform card. */
function PlatformStatusBadge({
  platform,
  isActive,
  interactiveShipping,
}: {
  platform: FederatedPlatform;
  isActive: boolean;
  interactiveShipping: boolean;
}) {
  if (platform.connection_status === 'syncing') {
    return <span className="text-[10px] font-mono text-slate-500">Syncing...</span>;
  }
  if (isActive && interactiveShipping) {
    return <span className="badge badge-neutral text-[9px]">STANDBY</span>;
  }
  if (isActive) {
    return <span className="badge badge-success text-[9px]">ACTIVE</span>;
  }
  if (platform.connection_status === 'synced') {
    return (
      <span className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
        <span className="text-[10px] font-mono text-slate-500">Available</span>
      </span>
    );
  }
  if (!platform.has_credentials) {
    return (
      <span className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
        <span className="text-[10px] font-mono text-slate-500">Not configured</span>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
      <span className="text-[10px] font-mono text-slate-500">Needs sync</span>
    </span>
  );
}

/** Single platform card with toggle-to-activate behavior. */
function PlatformCard({
  platform,
  interactiveShipping,
  onToggle,
  isToggling,
}: {
  platform: FederatedPlatform;
  interactiveShipping: boolean;
  onToggle: (platformId: string) => void;
  isToggling: boolean;
}) {
  const isActive = platform.is_active;
  const color = PLATFORM_COLORS[platform.platform_id] || '#94a3b8';
  const canToggle = (platform.connection_status === 'synced' || isActive || platform.has_credentials) && !isToggling;

  return (
    <div
      className={cn(
        'rounded-lg border overflow-hidden transition-colors',
        isActive && interactiveShipping
          ? 'border-l-4 border-l-slate-500 border-slate-600/30 bg-slate-800/20'
          : isActive
            ? 'border-l-4 bg-opacity-5'
            : 'border-slate-800'
      )}
      style={
        isActive && !interactiveShipping
          ? {
              borderLeftColor: color,
              borderColor: `${color}30`,
              backgroundColor: `${color}0D`,
            }
          : undefined
      }
    >
      <div className="flex items-center justify-between p-2.5 bg-slate-800/30">
        <div className="flex items-center gap-2">
          {getPlatformIcon(
            platform.platform_id,
            cn('w-5 h-5', isActive ? undefined : 'opacity-50'),
          )}
          <span
            className={cn(
              'text-xs font-medium',
              platform.has_credentials ? 'text-slate-200' : 'text-slate-400',
            )}
          >
            {platform.display_name}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isToggling ? (
            <span className="text-[10px] font-mono text-slate-500">
              {platform.connection_status !== 'synced' && !isActive ? 'Syncing...' : 'Updating...'}
            </span>
          ) : (
            <PlatformStatusBadge
              platform={platform}
              isActive={isActive}
              interactiveShipping={interactiveShipping}
            />
          )}
          {(canToggle || isToggling) && (
            <Switch
              checked={isActive}
              onCheckedChange={() => onToggle(platform.platform_id)}
              disabled={isToggling}
              className="scale-75"
            />
          )}
        </div>
      </div>

      {/* Active platform detail row */}
      {isActive && (
        <div
          className={cn('p-2.5 border-t', interactiveShipping ? 'border-slate-700' : '')}
          style={
            !interactiveShipping ? { borderColor: `${color}33` } : undefined
          }
        >
          <p className="text-xs text-slate-300">
            {platform.account_label || platform.display_name}
          </p>
          <p className="text-[10px] font-mono text-slate-500 mt-0.5">
            {interactiveShipping
              ? 'Available in batch mode'
              : platform.last_sync_row_count != null
                ? `${platform.last_sync_row_count.toLocaleString()} orders`
                : 'Connected'}
          </p>
        </div>
      )}

      {/* Not configured — link to Settings */}
      {!platform.has_credentials && !isActive && (
        <NotConfiguredFooter platformId={platform.platform_id} />
      )}
    </div>
  );
}

/** Footer for unconfigured platforms linking to settings. */
function NotConfiguredFooter({ platformId }: { platformId: string }) {
  const { setSettingsFlyoutOpen } = useAppState();
  const name =
    platformId.charAt(0).toUpperCase() + platformId.slice(1);

  return (
    <div className="p-2.5 border-t border-slate-800">
      <button
        onClick={() => setSettingsFlyoutOpen(true)}
        className="text-[10px] font-medium text-primary hover:underline"
      >
        Connect {name} in Settings &rarr;
      </button>
    </div>
  );
}

// Data Source Section - Unified view with platform cards + local source
export function DataSourceSection() {
  const {
    dataSource, setDataSource,
    activeSourceType, setActiveSourceType,
    setActiveSourceInfo,
    cachedLocalConfig, setCachedLocalConfig,
    interactiveShipping,
    writeBackEnabled, setWriteBackEnabled,
    setPendingChatMessage,
    federatedPlatforms,
    federatedPlatformsLoading,
    togglePlatformActive,
  } = useAppState();
  const [isConnecting, setIsConnecting] = React.useState(false);
  const [togglingPlatformId, setTogglingPlatformId] = React.useState<string | null>(null);
  const [showDbForm, setShowDbForm] = React.useState(false);
  const [dbConnectionString, setDbConnectionString] = React.useState('');
  const [backendSourceType, setBackendSourceType] = React.useState<string | null>(null);

  // Recent sources modal
  const [showRecentSources, setShowRecentSources] = React.useState(false);

  // File picker ref and state
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [importError, setImportError] = React.useState<string | null>(null);

  // Enabled platforms only (compile-time enabled flag)
  const enabledPlatforms = React.useMemo(
    () => federatedPlatforms.filter((p) => p.enabled),
    [federatedPlatforms],
  );

  // Any platform is active?
  const hasActivePlatform = enabledPlatforms.some((p) => p.is_active);

  React.useEffect(() => {
    let isCancelled = false;

    const hydrateSourceStatus = async () => {
      try {
        const status = await getDataSourceStatus();
        if (isCancelled) return;

        if (!status.connected) {
          setBackendSourceType(null);
          return;
        }

        const sourceType = String(status.source_type || '').toLowerCase();
        setBackendSourceType(sourceType || null);

        const KNOWN_TYPES = new Set<string>(['csv', 'excel', 'json', 'xml', 'fixed_width', 'edi', 'database']);
        if (KNOWN_TYPES.has(sourceType)) {
          const localType = sourceType as DataSourceType;
          const path = status.file_path || undefined;
          setDataSource({
            type: localType,
            status: 'connected' as const,
            row_count: status.row_count,
            column_count: status.columns?.length,
            columns: status.columns ? toDataSourceColumns(status.columns) : undefined,
            connected_at: new Date().toISOString(),
            csv_path: localType === 'csv' ? path : undefined,
            excel_path: localType === 'excel' ? path : undefined,
            file_path: KNOWN_TYPES.has(localType) && localType !== 'csv' && localType !== 'excel' && localType !== 'database' ? path : undefined,
          });
        }
      } catch {
        // Best-effort hydration; keep current UI state on failure.
      }
    };

    void hydrateSourceStatus();
    return () => {
      isCancelled = true;
    };
  }, [setDataSource]);

  // --- Derive active source from existing state ---
  React.useEffect(() => {
    if (dataSource?.status === 'connected') {
      setActiveSourceType('local');
      setActiveSourceInfo({
        type: 'local',
        label: extractFileName(dataSource) || dataSource.type.toUpperCase(),
        detail: `${dataSource.row_count?.toLocaleString() ?? '?'} rows`,
        sourceKind: dataSource.type === 'database' ? 'database' : 'file',
      });
    } else if (hasActivePlatform) {
      const activePlats = enabledPlatforms.filter((p) => p.is_active);
      const label = activePlats.map((p) => p.display_name).join(', ');
      setActiveSourceType('shopify'); // Keep existing type for compatibility
      setActiveSourceInfo({
        type: 'shopify',
        label,
        detail: 'Connected',
        sourceKind: 'shopify',
      });
    } else {
      setActiveSourceType(null);
      setActiveSourceInfo(null);
    }
  }, [
    dataSource,
    hasActivePlatform,
    enabledPlatforms,
    setActiveSourceType,
    setActiveSourceInfo,
  ]);

  // --- Platform toggle handler ---
  const handleTogglePlatform = async (platformId: string) => {
    setImportError(null);
    setTogglingPlatformId(platformId);
    try {
      await togglePlatformActive(platformId);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Failed to toggle platform');
    } finally {
      setTogglingPlatformId(null);
    }
  };

  /** Open native file picker for CSV or Excel. */
  const openFilePicker = (accept: string) => {
    setImportError(null);
    if (fileInputRef.current) {
      fileInputRef.current.accept = accept;
      fileInputRef.current.value = '';
      fileInputRef.current.click();
    }
  };

  /** Handle file selection from native file picker — uploads to backend. */
  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    const EXCEL_EXTS = new Set(['xlsx', 'xls']);
    const fileType: 'csv' | 'excel' = EXCEL_EXTS.has(ext) ? 'excel' : 'csv';

    setIsConnecting(true);
    setImportError(null);
    try {
      const result = await uploadDataSource(file);

      if (result.status === 'error') {
        setImportError(result.error || 'Import failed');
        return;
      }

      // Fixed-width files need agent-driven column setup — route to chat
      if (result.status === 'pending_agent_setup' && result.file_path) {
        setPendingChatMessage(
          `I uploaded ${file.name} as a fixed-width file (${result.file_path}). ` +
          `Please help me define the column layout.`
        );
        return;
      }

      const source: DataSourceInfo = {
        type: fileType,
        status: 'connected' as const,
        row_count: result.row_count,
        column_count: result.columns.length,
        columns: toDataSourceColumns(result.columns),
        connected_at: new Date().toISOString(),
        csv_path: fileType === 'csv' ? file.name : undefined,
        excel_path: fileType === 'excel' ? file.name : undefined,
      };
      setDataSource(source);
      setBackendSourceType(result.source_type || fileType);
      setCachedLocalConfig({ type: fileType, file_path: file.name });
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setIsConnecting(false);
    }
  };

  /** Reconnect a previously used local source via the saved-sources API. */
  const handleReconnectLocal = async () => {
    if (!cachedLocalConfig?.file_path) return;

    setIsConnecting(true);
    setImportError(null);
    try {
      const saved = await getSavedDataSources();
      const fileName = cachedLocalConfig.file_path.split('/').pop()?.toLowerCase();
      const match = saved.sources.find((s) =>
        s.name.toLowerCase() === fileName
      );
      if (!match) {
        const accept = cachedLocalConfig.type === 'csv' ? '.csv' : '.xlsx,.xls';
        openFilePicker(accept);
        return;
      }

      const result = await reconnectSavedSource(match.id);
      const source: DataSourceInfo = {
        type: match.source_type,
        status: 'connected' as const,
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        csv_path: match.source_type === 'csv' ? match.file_path ?? undefined : undefined,
        excel_path: match.source_type === 'excel' ? match.file_path ?? undefined : undefined,
        file_path: match.file_path ?? undefined,
      };
      setDataSource(source);
      setBackendSourceType(match.source_type);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      setIsConnecting(false);
    }
  };

  // Database connection handler
  const handleDbConnect = async () => {
    if (!dbConnectionString.trim()) return;

    setIsConnecting(true);
    setImportError(null);
    try {
      const result = await importDataSource({
        type: 'database',
        connection_string: dbConnectionString.trim(),
        query: 'SELECT * FROM shipments',
      });

      if (result.status === 'error') {
        setImportError(result.error || 'Connection failed');
        return;
      }

      const source: DataSourceInfo = {
        type: 'database',
        status: 'connected' as const,
        row_count: result.row_count,
        column_count: result.columns.length,
        columns: toDataSourceColumns(result.columns),
        connected_at: new Date().toISOString(),
      };
      setDataSource(source);
      setBackendSourceType('database');
      setCachedLocalConfig({ type: 'database' });
      setDbConnectionString('');
      setShowDbForm(false);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnectDataSource();
    } catch {
      // Ignore errors - clear local state anyway
    }
    setDataSource(null);
    setBackendSourceType(null);
    setCachedLocalConfig(null);
    setImportError(null);
  };

  // Derived state for card rendering
  const isLocalActive = activeSourceType === 'local';
  const localFileName = dataSource ? (extractFileName(dataSource) || dataSource.type.toUpperCase()) : null;

  return (
    <div className="p-3 space-y-3">
      <span className="text-xs font-medium text-slate-300">Data Sources</span>

      {/* === PLATFORM CARDS === */}
      {federatedPlatformsLoading ? (
        <div className="rounded-lg border border-slate-800 p-3">
          <p className="text-[10px] font-mono text-slate-500 text-center">Loading platforms...</p>
        </div>
      ) : (
        enabledPlatforms.map((platform) => (
          <PlatformCard
            key={platform.platform_id}
            platform={platform}
            interactiveShipping={interactiveShipping}
            onToggle={handleTogglePlatform}
            isToggling={togglingPlatformId === platform.platform_id}
          />
        ))
      )}

      {/* === LOCAL DATA SOURCE CARD === */}
      {dataSource?.status === 'connected' && (
        <div className={cn(
          'rounded-lg border overflow-hidden transition-colors',
          isLocalActive && interactiveShipping
            ? 'border-l-4 border-l-slate-500 border-slate-600/30 bg-slate-800/20'
            : isLocalActive
              ? 'border-l-4 border-l-primary border-primary/30 bg-primary/5'
              : 'border-slate-800'
        )}>
          <div className="flex items-center justify-between p-2.5">
            <div className="flex items-center gap-2">
              <HardDriveIcon className="w-4 h-4 text-slate-400" />
              <span className="text-xs font-medium text-slate-200">{localFileName}</span>
            </div>
            <div className="flex items-center gap-2">
              {isLocalActive && interactiveShipping ? (
                <span className="badge badge-neutral text-[9px]">STANDBY</span>
              ) : isLocalActive ? (
                <span className="badge badge-success text-[9px]">ACTIVE</span>
              ) : (
                <span className="text-[10px] font-mono text-slate-500">Available</span>
              )}
            </div>
          </div>
          <div className="px-2.5 pb-2.5 flex items-center justify-between">
            <div className="flex gap-4 text-[10px] font-mono">
              <span className="text-slate-500">
                Rows: <span className={isLocalActive && !interactiveShipping ? 'text-success' : 'text-slate-400'}>{dataSource.row_count?.toLocaleString() || '...'}</span>
              </span>
              <span className="text-slate-500">
                Cols: <span className="text-slate-300">{dataSource.column_count}</span>
              </span>
            </div>
            <button
              onClick={handleDisconnect}
              className="text-[10px] font-mono text-error hover:underline"
            >
              Disconnect
            </button>
          </div>
          {isLocalActive && interactiveShipping && (
            <div className="px-2.5 pb-2 -mt-1">
              <p className="text-[10px] font-mono text-slate-500">Available in batch mode</p>
            </div>
          )}
        </div>
      )}

      {/* === CACHED RECONNECT CARD === */}
      {!dataSource && cachedLocalConfig?.file_path && (
        <div className="rounded-lg border border-dashed border-slate-700 p-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <HardDriveIcon className="w-4 h-4 text-slate-500" />
              <span className="text-xs text-slate-400 truncate">
                {cachedLocalConfig.file_path.split('/').pop()}
              </span>
            </div>
            <button
              onClick={handleReconnectLocal}
              disabled={isConnecting}
              className="text-[10px] font-medium text-primary hover:underline disabled:opacity-50"
            >
              {isConnecting ? 'Reconnecting...' : 'Reconnect'}
            </button>
          </div>
        </div>
      )}

      {/* === WRITE-BACK TOGGLE === */}
      {activeSourceType && !interactiveShipping && (
        <div className="flex items-center justify-between px-3 py-2 mt-1 rounded-md bg-card/50 border border-slate-800/50">
          <div className="flex items-center gap-1.5">
            <label
              htmlFor="write-back-toggle"
              className="text-[11px] text-muted-foreground select-none"
            >
              Sync tracking info
            </label>
            <div className="relative group">
              <InfoIcon className="w-3.5 h-3.5 text-slate-500 cursor-help" />
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1.5 bg-slate-800 text-slate-100 text-[10px] rounded shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-150 w-40 text-center leading-relaxed z-50">
                Automatically updates tracking numbers on the original data source.
              </div>
            </div>
          </div>
          <Switch
            id="write-back-toggle"
            checked={writeBackEnabled}
            onCheckedChange={setWriteBackEnabled}
          />
        </div>
      )}

      {/* Hidden file input for native file picker */}
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileSelected}
      />

      {/* === IMPORT BUTTONS === */}
      {!dataSource?.status && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <HardDriveIcon className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Import Data Source</span>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => { setShowDbForm(false); openFilePicker('.csv,.tsv,.txt,.ssv,.dat,.xlsx,.xls,.json,.xml,.edi,.x12,.fwf'); }}
              disabled={isConnecting}
              className="flex-1 py-2 px-3 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300 transition-colors text-xs font-medium disabled:opacity-50"
            >
              Import File
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
          <p className="text-[10px] text-slate-500 mt-0.5">CSV, TSV, Excel, JSON, XML, EDI, and more</p>

          <button
            onClick={() => setShowRecentSources(true)}
            className="w-full py-1.5 text-[11px] font-medium rounded-md border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300 transition-colors"
          >
            Saved Sources
          </button>

          {/* Database connection form */}
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

          {/* Error display */}
          {importError && (
            <p className="text-[10px] font-mono text-error p-2 rounded bg-error/10">{importError}</p>
          )}

          {isConnecting && !importError && (
            <p className="text-[10px] font-mono text-slate-500 text-center">Importing...</p>
          )}
        </div>
      )}

      {/* Error display (when data source is connected but platform toggle fails) */}
      {dataSource?.status === 'connected' && importError && (
        <p className="text-[10px] font-mono text-error p-2 rounded bg-error/10">{importError}</p>
      )}

      {/* Recent Sources Modal */}
      <RecentSourcesModal
        open={showRecentSources}
        onClose={() => setShowRecentSources(false)}
        onReconnected={(info) => {
          setDataSource(info);
          setShowRecentSources(false);
        }}
      />
    </div>
  );
}
