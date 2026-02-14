/**
 * Modal for browsing and reconnecting previously used data sources.
 *
 * Features:
 * - Search by source name
 * - Filter by type (All / CSV / Excel / Database)
 * - One-click reconnect for file-based sources
 * - Connection string input for database sources
 * - Individual and bulk delete
 */

import * as React from 'react';
import { cn, formatTimeAgo } from '@/lib/utils';
import {
  getSavedDataSources,
  reconnectSavedSource,
  deleteSavedSource,
  bulkDeleteSavedSources,
} from '@/lib/api';
import type { SavedDataSource, DataSourceInfo } from '@/types/api';
import { SearchIcon, FileIcon, DatabaseIcon, TrashIcon, XIcon } from '@/components/ui/icons';

interface RecentSourcesModalProps {
  open: boolean;
  onClose: () => void;
  onReconnected: (info: DataSourceInfo) => void;
}

// --- Helpers ---

function sourceIcon(type: string) {
  if (type === 'database') return <DatabaseIcon className="w-4 h-4 text-amber-400" />;
  return <FileIcon className="w-4 h-4 text-cyan-400" />;
}

function typeLabel(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

// --- Component ---

export function RecentSourcesModal({ open, onClose, onReconnected }: RecentSourcesModalProps) {
  const [sources, setSources] = React.useState<SavedDataSource[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [search, setSearch] = React.useState('');
  const [typeFilter, setTypeFilter] = React.useState<string>('all');
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [reconnectingId, setReconnectingId] = React.useState<string | null>(null);
  const [dbConnStr, setDbConnStr] = React.useState('');
  const [dbSourceId, setDbSourceId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Fetch sources when modal opens
  React.useEffect(() => {
    if (!open) return;
    setIsLoading(true);
    setError(null);
    setSelected(new Set());
    setDbSourceId(null);
    setDbConnStr('');
    getSavedDataSources()
      .then((res) => setSources(res.sources))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load sources'))
      .finally(() => setIsLoading(false));
  }, [open]);

  // Filter
  const filtered = React.useMemo(() => {
    return sources.filter((s) => {
      const matchesSearch = !search || s.name.toLowerCase().includes(search.toLowerCase());
      const matchesType = typeFilter === 'all' || s.source_type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [sources, search, typeFilter]);

  // Selection
  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((s) => s.id)));
    }
  };

  // Reconnect
  const handleReconnect = async (source: SavedDataSource) => {
    if (source.source_type === 'database') {
      setDbSourceId(source.id);
      setDbConnStr('');
      return;
    }

    setReconnectingId(source.id);
    setError(null);
    try {
      const result = await reconnectSavedSource(source.id);
      const info: DataSourceInfo = {
        type: source.source_type as 'csv' | 'excel',
        status: 'connected',
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        csv_path: source.source_type === 'csv' ? source.file_path ?? undefined : undefined,
        excel_path: source.source_type === 'excel' ? source.file_path ?? undefined : undefined,
        excel_sheet: source.sheet_name ?? undefined,
      };
      onReconnected(info);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      setReconnectingId(null);
    }
  };

  const handleDbReconnect = async () => {
    if (!dbSourceId || !dbConnStr.trim()) return;

    setReconnectingId(dbSourceId);
    setError(null);
    try {
      const source = sources.find((s) => s.id === dbSourceId);
      const result = await reconnectSavedSource(dbSourceId, dbConnStr.trim());
      const info: DataSourceInfo = {
        type: 'database',
        status: 'connected',
        row_count: result.row_count,
        column_count: result.column_count,
        connected_at: new Date().toISOString(),
        database_query: source?.db_query ?? undefined,
      };
      onReconnected(info);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reconnect failed');
    } finally {
      setReconnectingId(null);
    }
  };

  // Delete
  const handleDelete = async (id: string) => {
    try {
      await deleteSavedSource(id);
      setSources((prev) => prev.filter((s) => s.id !== id));
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (dbSourceId === id) {
        setDbSourceId(null);
        setDbConnStr('');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  const handleBulkDelete = async () => {
    if (selected.size === 0) return;
    try {
      await bulkDeleteSavedSources(Array.from(selected));
      setSources((prev) => prev.filter((s) => !selected.has(s.id)));
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk delete failed');
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-lg mx-4 rounded-xl border border-slate-700 bg-void-900 shadow-2xl flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-100">Recent Data Sources</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors">
            <XIcon className="w-4 h-4" />
          </button>
        </div>

        {/* Search + Filters */}
        <div className="px-5 pt-4 pb-2 space-y-3">
          <div className="relative">
            <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search sources..."
              className="w-full pl-8 pr-3 py-2 text-xs font-mono rounded-md bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
            />
          </div>
          <div className="flex gap-1.5">
            {['all', 'csv', 'excel', 'database'].map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={cn(
                  'px-2.5 py-1 text-[10px] font-mono rounded-full transition-colors',
                  typeFilter === t
                    ? 'bg-primary/20 text-primary border border-primary/30'
                    : 'text-slate-500 hover:text-slate-300 border border-transparent'
                )}
              >
                {t === 'all' ? 'All' : typeLabel(t)}
              </button>
            ))}
          </div>
        </div>

        {/* Source List */}
        <div className="flex-1 overflow-y-auto px-5 py-2 scrollable min-h-0">
          {isLoading ? (
            <div className="space-y-2 py-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-14 bg-slate-800 rounded-lg shimmer" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-slate-500">
              <DatabaseIcon className="w-8 h-8 mb-3 opacity-40" />
              <p className="text-xs">
                {sources.length === 0 ? 'No saved sources yet' : 'No sources match filters'}
              </p>
              <p className="text-[10px] mt-1 text-slate-600">
                {sources.length === 0 ? 'Connect a data source and it will appear here' : 'Try a different search or filter'}
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {filtered.map((source) => (
                <div
                  key={source.id}
                  className={cn(
                    'group flex items-center gap-3 p-3 rounded-lg border transition-colors',
                    selected.has(source.id)
                      ? 'border-primary/30 bg-primary/5'
                      : 'border-transparent hover:bg-slate-800/50'
                  )}
                >
                  {/* Checkbox */}
                  <input
                    type="checkbox"
                    checked={selected.has(source.id)}
                    onChange={() => toggleSelect(source.id)}
                    className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-primary focus:ring-0 focus:ring-offset-0 cursor-pointer flex-shrink-0"
                  />

                  {/* Icon */}
                  <div className="flex-shrink-0">{sourceIcon(source.source_type)}</div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-slate-200 truncate">{source.name}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[10px] font-mono text-slate-500">
                        {source.row_count.toLocaleString()} rows
                      </span>
                      <span className="text-slate-700">·</span>
                      <span className="text-[10px] font-mono text-slate-500">
                        {formatTimeAgo(source.last_used_at)}
                      </span>
                      <span className="text-slate-700">·</span>
                      <span className={cn(
                        'text-[9px] font-mono uppercase',
                        source.source_type === 'csv' ? 'text-cyan-500' :
                        source.source_type === 'excel' ? 'text-green-500' :
                        'text-amber-500'
                      )}>
                        {source.source_type}
                      </span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button
                      onClick={() => handleReconnect(source)}
                      disabled={reconnectingId === source.id}
                      className="px-3 py-1.5 text-[10px] font-medium rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20 transition-colors disabled:opacity-50"
                    >
                      {reconnectingId === source.id ? 'Connecting...' :
                       source.source_type === 'database' ? 'Connect' : 'Reconnect'}
                    </button>
                    <button
                      onClick={() => handleDelete(source.id)}
                      className="p-1.5 rounded opacity-0 group-hover:opacity-100 hover:bg-error/20 text-slate-500 hover:text-error transition-all"
                      title="Delete"
                    >
                      <TrashIcon className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Database connection string input (shown when a DB source is selected) */}
        {dbSourceId && (
          <div className="px-5 py-3 border-t border-slate-800">
            <p className="text-[10px] font-mono text-slate-500 mb-2">
              Enter connection string for {sources.find((s) => s.id === dbSourceId)?.name}
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={dbConnStr}
                onChange={(e) => setDbConnStr(e.target.value)}
                placeholder="postgresql://user:pass@host:5432/db"
                className="flex-1 px-2.5 py-1.5 text-xs font-mono rounded bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-primary"
                onKeyDown={(e) => e.key === 'Enter' && handleDbReconnect()}
              />
              <button
                onClick={handleDbReconnect}
                disabled={!dbConnStr.trim() || reconnectingId === dbSourceId}
                className="px-4 py-1.5 text-xs font-medium rounded btn-primary disabled:opacity-50"
              >
                {reconnectingId === dbSourceId ? 'Connecting...' : 'Connect'}
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="px-5 py-2">
            <p className="text-[10px] font-mono text-error p-2 rounded bg-error/10">{error}</p>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-slate-800">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={filtered.length > 0 && selected.size === filtered.length}
                onChange={toggleSelectAll}
                className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-primary focus:ring-0 focus:ring-offset-0 cursor-pointer"
                disabled={filtered.length === 0}
              />
              <span className="text-[10px] font-mono text-slate-500">Select all</span>
            </label>
            {selected.size > 0 && (
              <button
                onClick={handleBulkDelete}
                className="text-[10px] font-medium text-error hover:underline"
              >
                Delete {selected.size}
              </button>
            )}
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium rounded border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default RecentSourcesModal;
