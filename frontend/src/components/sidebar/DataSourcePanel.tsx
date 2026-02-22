/**
 * Data source management panel for the sidebar.
 *
 * Handles local file import (CSV/Excel), database connections,
 * Shopify platform integration, and source switching.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import { useExternalSources } from '@/hooks/useExternalSources';
import { cn } from '@/lib/utils';
import {
  disconnectDataSource,
  importDataSource,
  uploadDataSource,
  getSavedDataSources,
  reconnectSavedSource,
  getDataSourceStatus,
} from '@/lib/api';
import type { DataSourceInfo } from '@/types/api';
import { RecentSourcesModal } from '@/components/RecentSourcesModal';
import { toDataSourceColumns } from '@/components/sidebar/dataSourceMappers';
import { HardDriveIcon, InfoIcon } from '@/components/ui/icons';
import { ShopifyIcon } from '@/components/ui/brand-icons';
import { Switch } from '@/components/ui/switch';

/** Extracts a display filename from a DataSourceInfo. */
export function extractFileName(ds: DataSourceInfo): string | null {
  const path = ds.csv_path || ds.excel_path;
  if (!path) return null;
  const segments = path.split('/');
  return segments[segments.length - 1] || null;
}

// Data Source Section - Unified view with radio-card active/inactive pattern
export function DataSourceSection() {
  const {
    dataSource, setDataSource,
    activeSourceType, setActiveSourceType,
    setActiveSourceInfo,
    cachedLocalConfig, setCachedLocalConfig,
    interactiveShipping,
    writeBackEnabled, setWriteBackEnabled,
    setPendingChatMessage,
  } = useAppState();
  const { state: externalState } = useExternalSources();
  const {
    providerConnections,
    setSettingsFlyoutOpen,
  } = useAppState();
  const [isConnecting, setIsConnecting] = React.useState(false);
  const [showDbForm, setShowDbForm] = React.useState(false);
  const [dbConnectionString, setDbConnectionString] = React.useState('');
  const [backendSourceType, setBackendSourceType] = React.useState<string | null>(null);

  // Shopify availability derived from provider connections (server-side runtime_usable)
  const shopifyConnection = providerConnections.find(
    (c) => c.provider === 'shopify' && c.runtime_usable
  );
  const shopifyAvailable = !!shopifyConnection;

  // Also check env-based Shopify for backward compatibility during migration
  const shopifyEnvStatus = externalState.shopifyEnvStatus;
  const isCheckingShopifyEnv = externalState.isCheckingEnv;
  const shopifyEnvConnected = shopifyEnvStatus?.valid === true;
  const shopifyStoreName = shopifyConnection?.display_name
    || shopifyEnvStatus?.store_name
    || shopifyEnvStatus?.store_url;

  // Recent sources modal
  const [showRecentSources, setShowRecentSources] = React.useState(false);

  // File picker ref and state
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [importError, setImportError] = React.useState<string | null>(null);

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

        if (sourceType === 'csv' || sourceType === 'excel' || sourceType === 'database') {
          const localType = sourceType as 'csv' | 'excel' | 'database';
          const path = status.file_path || undefined;
          setDataSource({
            type: localType,
            status: 'connected',
            row_count: status.row_count,
            column_count: status.columns?.length,
            columns: status.columns ? toDataSourceColumns(status.columns) : undefined,
            connected_at: new Date().toISOString(),
            csv_path: localType === 'csv' ? path : undefined,
            excel_path: localType === 'excel' ? path : undefined,
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
    } else if (backendSourceType === 'shopify' || (!backendSourceType && (shopifyAvailable || shopifyEnvConnected))) {
      setActiveSourceType('shopify');
      setActiveSourceInfo({
        type: 'shopify',
        label: 'Shopify',
        detail: shopifyStoreName || 'Connected',
        sourceKind: 'shopify',
      });
    } else {
      setActiveSourceType(null);
      setActiveSourceInfo(null);
    }
  }, [
    dataSource,
    backendSourceType,
    shopifyAvailable,
    shopifyEnvConnected,
    shopifyStoreName,
    setActiveSourceType,
    setActiveSourceInfo,
  ]);

  // --- Source switching handlers ---

  /** Switch to Shopify: disconnect local source so backend routes to Shopify. */
  const handleSwitchToShopify = async () => {
    if (dataSource) {
      setCachedLocalConfig({
        type: dataSource.type as 'csv' | 'excel' | 'database',
        file_path: dataSource.csv_path || dataSource.excel_path,
      });
    }
    try { await disconnectDataSource(); } catch { /* best-effort */ }
    setDataSource(null);
    setBackendSourceType(null);
    // useEffect will set Shopify as active
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
    // Map to a broad category for local state — backend handles format routing
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
      // Look up the saved source by matching file name
      const saved = await getSavedDataSources();
      const fileName = cachedLocalConfig.file_path.split('/').pop()?.toLowerCase();
      const match = saved.sources.find((s) =>
        s.name.toLowerCase() === fileName
      );
      if (!match) {
        // Fallback: open file picker if saved source not found
        const accept = cachedLocalConfig.type === 'csv' ? '.csv' : '.xlsx,.xls';
        openFilePicker(accept);
        return;
      }

      const result = await reconnectSavedSource(match.id);
      const source: DataSourceInfo = {
        type: match.source_type as 'csv' | 'excel',
        status: 'connected' as const,
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        csv_path: match.source_type === 'csv' ? match.file_path ?? undefined : undefined,
        excel_path: match.source_type === 'excel' ? match.file_path ?? undefined : undefined,
      };
      setDataSource(source);
      setBackendSourceType(match.source_type);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      setIsConnecting(false);
    }
  };

  // Database connection handler — calls backend import API
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
  const isShopifyActive = activeSourceType === 'shopify';
  const localFileName = dataSource ? (extractFileName(dataSource) || dataSource.type.toUpperCase()) : null;

  return (
    <div className="p-3 space-y-3">
      <span className="text-xs font-medium text-slate-300">Data Sources</span>

      {/* === SHOPIFY CARD === */}
      {(shopifyAvailable || shopifyEnvConnected) ? (
        <div className={cn(
          'rounded-lg border overflow-hidden transition-colors',
          isShopifyActive && interactiveShipping
            ? 'border-l-4 border-l-slate-500 border-slate-600/30 bg-slate-800/20'
            : isShopifyActive
              ? 'border-l-4 border-l-[#5BBF3D] border-[#5BBF3D]/30 bg-[#5BBF3D]/5'
              : 'border-slate-800'
        )}>
          <div className="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div className="flex items-center gap-2">
              <ShopifyIcon className="w-5 h-5 text-[#5BBF3D]" />
              <span className="text-xs font-medium text-slate-200">Shopify</span>
            </div>
            <div className="flex items-center gap-2">
              {isCheckingShopifyEnv ? (
                <span className="text-[10px] font-mono text-slate-500">Checking...</span>
              ) : isShopifyActive && interactiveShipping ? (
                <span className="badge badge-neutral text-[9px]">STANDBY</span>
              ) : isShopifyActive ? (
                <span className="badge badge-success text-[9px]">ACTIVE</span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  <span className="text-[10px] font-mono text-slate-500">Available</span>
                </span>
              )}
            </div>
          </div>

          {/* Active Shopify info */}
          {isShopifyActive && (
            <div className={cn('p-2.5 border-t', interactiveShipping ? 'border-slate-700' : 'border-[#5BBF3D]/20')}>
              <p className="text-xs text-slate-300">
                {shopifyStoreName}
              </p>
              <p className="text-[10px] font-mono text-slate-500 mt-0.5">
                {interactiveShipping ? 'Available in batch mode' : 'Connected'}
              </p>
            </div>
          )}

          {/* Shopify available but not active — show "Use Shopify" button */}
          {!isShopifyActive && (
            <div className="p-2.5 border-t border-slate-800">
              <p className="text-[10px] text-slate-500 mb-2">
                {shopifyStoreName}
              </p>
              <button
                onClick={handleSwitchToShopify}
                className="w-full py-1.5 text-xs font-medium rounded border border-[#5BBF3D]/40 text-[#5BBF3D] hover:bg-[#5BBF3D]/10 transition-colors"
              >
                Use Shopify
              </button>
            </div>
          )}
        </div>
      ) : (
        /* Not configured — direct to Settings */
        <div className="rounded-lg border border-slate-800 overflow-hidden">
          <div className="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div className="flex items-center gap-2">
              <ShopifyIcon className="w-5 h-5 text-[#5BBF3D]/50" />
              <span className="text-xs font-medium text-slate-400">Shopify</span>
            </div>
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-600" />
              <span className="text-[10px] font-mono text-slate-500">Not configured</span>
            </span>
          </div>
          <div className="p-2.5 border-t border-slate-800">
            <button
              onClick={() => setSettingsFlyoutOpen(true)}
              className="text-[10px] font-medium text-[#96BF48] hover:underline"
            >
              Connect Shopify in Settings →
            </button>
          </div>
        </div>
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
