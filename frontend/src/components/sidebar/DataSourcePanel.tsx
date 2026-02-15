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
import { disconnectDataSource, importDataSource, uploadDataSource, getSavedDataSources, reconnectSavedSource } from '@/lib/api';
import type { DataSourceInfo, PlatformType } from '@/types/api';
import { RecentSourcesModal } from '@/components/RecentSourcesModal';
import { toDataSourceColumns } from '@/components/sidebar/dataSourceMappers';
import { HardDriveIcon, EyeIcon, EyeOffIcon } from '@/components/ui/icons';
import { ShopifyIcon } from '@/components/ui/brand-icons';

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
  } = useAppState();
  const { state: externalState, connect: connectExternal } = useExternalSources();
  const [isConnecting, setIsConnecting] = React.useState(false);
  const [showShopifyForm, setShowShopifyForm] = React.useState(false);
  const [showDbForm, setShowDbForm] = React.useState(false);
  const [dbConnectionString, setDbConnectionString] = React.useState('');

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
  const shopifyStoreName = shopifyEnvStatus?.store_name || shopifyEnvStatus?.store_url;

  // Recent sources modal
  const [showRecentSources, setShowRecentSources] = React.useState(false);

  // File picker ref and state
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [importError, setImportError] = React.useState<string | null>(null);

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
    } else if (shopifyEnvConnected) {
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
  }, [dataSource, shopifyEnvConnected, shopifyStoreName, setActiveSourceType, setActiveSourceInfo]);

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

    const ext = file.name.split('.').pop()?.toLowerCase();
    const fileType: 'csv' | 'excel' = ext === 'csv' ? 'csv' : 'excel';

    setIsConnecting(true);
    setImportError(null);
    try {
      const result = await uploadDataSource(file);

      if (result.status === 'error') {
        setImportError(result.error || 'Import failed');
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
      setCachedLocalConfig({ type: 'database' });
      setDbConnectionString('');
      setShowDbForm(false);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setIsConnecting(false);
    }
  };

  // Shopify connection (manual form) — delegates to useExternalSources hook
  const handleShopifyConnect = async () => {
    if (!shopifyStoreUrl.trim() || !shopifyAccessToken.trim()) return;

    setIsConnecting(true);
    setShopifyError(null);

    try {
      let storeUrl = shopifyStoreUrl.trim();
      if (!storeUrl.includes('.myshopify.com')) {
        storeUrl = `${storeUrl}.myshopify.com`;
      }
      storeUrl = storeUrl.replace(/^https?:\/\//, '');

      const success = await connectExternal(
        'shopify' as PlatformType,
        { access_token: shopifyAccessToken.trim() },
        storeUrl
      );

      if (success) {
        setShopifyStoreUrl('');
        setShopifyAccessToken('');
        setShowShopifyForm(false);
      } else {
        setShopifyError('Failed to connect to Shopify');
      }
    } catch (err) {
      setShopifyError(err instanceof Error ? err.message : 'Connection failed');
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
      {(shopifyEnvConnected || shopifyEnvStatus?.configured || showShopifyForm) && (
        <div className={cn(
          'rounded-lg border overflow-hidden transition-colors',
          isShopifyActive
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
              ) : shopifyEnvConnected && isShopifyActive ? (
                <span className="badge badge-success text-[9px]">ACTIVE</span>
              ) : shopifyEnvConnected ? (
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                  <span className="text-[10px] font-mono text-slate-500">Available</span>
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
          </div>

          {/* Active Shopify info */}
          {shopifyEnvConnected && isShopifyActive && (
            <div className="p-2.5 border-t border-[#5BBF3D]/20">
              <p className="text-xs text-slate-300">
                {shopifyStoreName}
              </p>
              <p className="text-[10px] font-mono text-slate-500 mt-0.5">
                Auto-detected from environment
              </p>
            </div>
          )}

          {/* Shopify available but not active — show "Use Shopify" button */}
          {shopifyEnvConnected && !isShopifyActive && (
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
                  <input
                    type="text"
                    value={shopifyStoreUrl}
                    onChange={(e) => setShopifyStoreUrl(e.target.value)}
                    placeholder="mystore.myshopify.com"
                    className="w-full px-2.5 py-1.5 text-xs font-mono rounded bg-void-900 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-[#96BF48]"
                  />
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
      )}

      {/* === LOCAL DATA SOURCE CARD === */}
      {dataSource?.status === 'connected' && (
        <div className={cn(
          'rounded-lg border overflow-hidden transition-colors',
          isLocalActive
            ? 'border-l-4 border-l-primary border-primary/30 bg-primary/5'
            : 'border-slate-800'
        )}>
          <div className="flex items-center justify-between p-2.5">
            <div className="flex items-center gap-2">
              <HardDriveIcon className="w-4 h-4 text-slate-400" />
              <span className="text-xs font-medium text-slate-200">{localFileName}</span>
            </div>
            <div className="flex items-center gap-2">
              {isLocalActive ? (
                <span className="badge badge-success text-[9px]">ACTIVE</span>
              ) : (
                <span className="text-[10px] font-mono text-slate-500">Available</span>
              )}
            </div>
          </div>
          <div className="px-2.5 pb-2.5 flex items-center justify-between">
            <div className="flex gap-4 text-[10px] font-mono">
              <span className="text-slate-500">
                Rows: <span className={isLocalActive ? 'text-success' : 'text-slate-400'}>{dataSource.row_count?.toLocaleString() || '...'}</span>
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
              onClick={() => { setShowDbForm(false); openFilePicker('.csv'); }}
              disabled={isConnecting}
              className="flex-1 py-2 px-3 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300 transition-colors text-xs font-medium disabled:opacity-50"
            >
              CSV
            </button>
            <button
              onClick={() => { setShowDbForm(false); openFilePicker('.xlsx,.xls'); }}
              disabled={isConnecting}
              className="flex-1 py-2 px-3 rounded-lg border border-slate-700 bg-slate-800/50 hover:bg-slate-800 hover:border-slate-600 text-slate-300 transition-colors text-xs font-medium disabled:opacity-50"
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
