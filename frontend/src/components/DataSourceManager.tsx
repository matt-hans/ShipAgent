/**
 * DataSourceManager component for managing data source connections.
 *
 * Industrial Terminal aesthetic - technical panel for connecting
 * file sources, databases, and external platforms via MCP Gateway.
 *
 * All operations flow through: Frontend → FastAPI → OrchestrationAgent → MCP Tools
 */

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type {
  DataSourceInfo,
  ColumnMetadata,
  CsvImportConfig,
  ExcelImportConfig,
  DatabaseImportConfig,
} from '@/types/api';

/** Extended source types including future integrations. */
type ExtendedSourceType =
  | 'csv'
  | 'excel'
  | 'edi'
  | 'postgresql'
  | 'mysql'
  | 'shopify'
  | 'woocommerce'
  | 'sap'
  | 'oracle';

/** Source category for grouping. */
type SourceCategory = 'files' | 'databases' | 'platforms';

/** Source configuration metadata. */
interface SourceConfig {
  id: ExtendedSourceType;
  name: string;
  description: string;
  category: SourceCategory;
  icon: React.ReactNode;
  implemented: boolean;
}

export interface DataSourceManagerProps {
  /** Currently connected data source info. */
  dataSource: DataSourceInfo | null;
  /** Callback when data source is connected. */
  onConnect: (config: CsvImportConfig | ExcelImportConfig | DatabaseImportConfig) => Promise<void>;
  /** Callback when data source is disconnected. */
  onDisconnect: () => void;
  /** Optional additional class name. */
  className?: string;
}

/**
 * File icon for CSV/Excel sources.
 */
function FileIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

/**
 * EDI document icon.
 */
function EdiIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M7 7h10M7 12h10M7 17h4" />
    </svg>
  );
}

/**
 * Shopping cart icon for e-commerce platforms.
 */
function CartIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="8" cy="21" r="1" />
      <circle cx="19" cy="21" r="1" />
      <path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12" />
    </svg>
  );
}

/**
 * Building icon for enterprise systems.
 */
function EnterpriseIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect x="4" y="2" width="16" height="20" rx="2" />
      <path d="M9 22v-4h6v4M8 6h.01M16 6h.01M12 6h.01M8 10h.01M16 10h.01M12 10h.01M8 14h.01M16 14h.01M12 14h.01" />
    </svg>
  );
}

/**
 * Feature flags for MVP.
 * Set to true to show source type in UI.
 */
const FEATURE_FLAGS: Record<ExtendedSourceType, boolean> = {
  // Core file sources - always enabled
  csv: true,
  excel: true,
  edi: false,        // Deferred to v2
  // Database sources - always enabled
  postgresql: true,
  mysql: true,
  // External platforms - only Shopify for MVP
  shopify: true,
  woocommerce: false, // Deferred to v2
  sap: false,         // Deferred to v2
  oracle: false,      // Deferred to v2
};

/** All source configurations (filtered by feature flags in component). */
const ALL_SOURCE_CONFIGS: SourceConfig[] = [
  // File Sources
  {
    id: 'csv',
    name: 'CSV',
    description: 'Import comma-separated values via MCP Gateway',
    category: 'files',
    icon: <FileIcon className="h-5 w-5" />,
    implemented: true,
  },
  {
    id: 'excel',
    name: 'Excel',
    description: 'Import .xlsx spreadsheets via MCP Gateway',
    category: 'files',
    icon: <FileIcon className="h-5 w-5" />,
    implemented: true,
  },
  {
    id: 'edi',
    name: 'EDI',
    description: 'EDI X12/EDIFACT documents via MCP Gateway',
    category: 'files',
    icon: <EdiIcon className="h-5 w-5" />,
    implemented: false,
  },
  // Database Sources
  {
    id: 'postgresql',
    name: 'PostgreSQL',
    description: 'Connect to PostgreSQL via MCP Gateway',
    category: 'databases',
    icon: <DatabaseIcon className="h-5 w-5" />,
    implemented: true,
  },
  {
    id: 'mysql',
    name: 'MySQL',
    description: 'Connect to MySQL via MCP Gateway',
    category: 'databases',
    icon: <DatabaseIcon className="h-5 w-5" />,
    implemented: true,
  },
  // Platform Integrations
  {
    id: 'shopify',
    name: 'Shopify',
    description: 'Sync orders from Shopify via MCP Gateway',
    category: 'platforms',
    icon: <CartIcon className="h-5 w-5" />,
    implemented: false,
  },
  {
    id: 'woocommerce',
    name: 'WooCommerce',
    description: 'Sync orders from WooCommerce via MCP Gateway',
    category: 'platforms',
    icon: <CartIcon className="h-5 w-5" />,
    implemented: false,
  },
  {
    id: 'sap',
    name: 'SAP',
    description: 'Connect to SAP via MCP Gateway',
    category: 'platforms',
    icon: <EnterpriseIcon className="h-5 w-5" />,
    implemented: false,
  },
  {
    id: 'oracle',
    name: 'Oracle',
    description: 'Connect to Oracle ERP via MCP Gateway',
    category: 'platforms',
    icon: <EnterpriseIcon className="h-5 w-5" />,
    implemented: false,
  },
];

/** Source configs filtered by feature flags. */
const SOURCE_CONFIGS = ALL_SOURCE_CONFIGS.filter(s => FEATURE_FLAGS[s.id]);

/**
 * Database icon.
 */
function DatabaseIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5V19A9 3 0 0 0 21 19V5" />
      <path d="M3 12A9 3 0 0 0 21 12" />
    </svg>
  );
}

/**
 * Disconnect icon.
 */
function DisconnectIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4" />
      <polyline points="9 9 15 9" />
      <path d="M15 15h6" />
    </svg>
  );
}

/**
 * Column type badge color.
 */
function getColumnTypeColor(type: string): string {
  if (type.includes('INT')) return 'bg-route-500/20 text-route-400 border border-route-500/30';
  if (type.includes('VARCHAR') || type.includes('TEXT')) return 'bg-signal-500/20 text-signal-400 border border-signal-500/30';
  if (type.includes('DATE') || type.includes('TIMESTAMP')) return 'bg-status-hold/20 text-status-hold border border-status-hold/30';
  if (type.includes('DECIMAL') || type.includes('DOUBLE')) return 'bg-status-go/20 text-status-go border border-status-go/30';
  if (type.includes('BOOLEAN')) return 'bg-purple-500/20 text-purple-400 border border-purple-500/30';
  return 'bg-steel-700 text-steel-300';
}

/**
 * CSV import form.
 */
function CsvImportForm({
  onSubmit,
  isSubmitting,
}: {
  onSubmit: (config: CsvImportConfig) => Promise<void>;
  isSubmitting: boolean;
}) {
  const [filePath, setFilePath] = React.useState('');
  const [delimiter, setDelimiter] = React.useState(',');
  const [header, setHeader] = React.useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filePath.trim()) return;
    await onSubmit({ filePath: filePath.trim(), delimiter, header });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          File Path
        </label>
        <Input
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
          placeholder="/path/to/your/orders.csv"
          className="font-mono-display text-sm"
          disabled={isSubmitting}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
            Delimiter
          </label>
          <select
            value={delimiter}
            onChange={(e) => setDelimiter(e.target.value)}
            className="w-full h-10 px-3 rounded-sm bg-warehouse-800 border border-steel-700 font-mono-display text-sm text-steel-100 focus:ring-2 focus:ring-signal-500/50"
            disabled={isSubmitting}
          >
            <option value=",">Comma (,)</option>
            <option value=";">Semicolon (;)</option>
            <option value="\t">Tab</option>
            <option value="|">Pipe (|)</option>
          </select>
        </div>

        <div className="space-y-2">
          <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
            Header Row
          </label>
          <select
            value={header ? 'true' : 'false'}
            onChange={(e) => setHeader(e.target.value === 'true')}
            className="w-full h-10 px-3 rounded-sm bg-warehouse-800 border border-steel-700 font-mono-display text-sm text-steel-100 focus:ring-2 focus:ring-signal-500/50"
            disabled={isSubmitting}
          >
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </div>
      </div>

      <Button
        type="submit"
        disabled={!filePath.trim() || isSubmitting}
        className="w-full btn-industrial font-mono-display text-sm uppercase tracking-wider"
      >
        {isSubmitting ? 'Connecting...' : 'Connect CSV Source'}
      </Button>
    </form>
  );
}

/**
 * Excel import form.
 */
function ExcelImportForm({
  onSubmit,
  isSubmitting,
}: {
  onSubmit: (config: ExcelImportConfig) => Promise<void>;
  isSubmitting: boolean;
}) {
  const [filePath, setFilePath] = React.useState('');
  const [sheet, setSheet] = React.useState('');
  const [header, setHeader] = React.useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filePath.trim()) return;
    await onSubmit({
      filePath: filePath.trim(),
      sheet: sheet.trim() || undefined,
      header
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          File Path
        </label>
        <Input
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
          placeholder="/path/to/your/orders.xlsx"
          className="font-mono-display text-sm"
          disabled={isSubmitting}
        />
      </div>

      <div className="space-y-2">
        <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          Sheet Name (optional)
        </label>
        <Input
          value={sheet}
          onChange={(e) => setSheet(e.target.value)}
          placeholder="Leave empty for first sheet"
          className="font-mono-display text-sm"
          disabled={isSubmitting}
        />
        <p className="font-mono-display text-[10px] text-steel-600">
          If specified, imports from this sheet. Otherwise uses the first sheet.
        </p>
      </div>

      <div className="space-y-2">
        <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          Header Row
        </label>
        <select
          value={header ? 'true' : 'false'}
          onChange={(e) => setHeader(e.target.value === 'true')}
          className="w-full h-10 px-3 rounded-sm bg-warehouse-800 border border-steel-700 font-mono-display text-sm text-steel-100 focus:ring-2 focus:ring-signal-500/50"
          disabled={isSubmitting}
        >
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>

      <Button
        type="submit"
        disabled={!filePath.trim() || isSubmitting}
        className="w-full btn-industrial font-mono-display text-sm uppercase tracking-wider"
      >
        {isSubmitting ? 'Connecting...' : 'Connect Excel Source'}
      </Button>
    </form>
  );
}

/**
 * Database import form - supports PostgreSQL and MySQL.
 */
function DatabaseImportForm({
  onSubmit,
  isSubmitting,
  dbType = 'postgresql',
}: {
  onSubmit: (config: DatabaseImportConfig) => Promise<void>;
  isSubmitting: boolean;
  dbType?: 'postgresql' | 'mysql';
}) {
  const [connectionString, setConnectionString] = React.useState('');
  const [query, setQuery] = React.useState('');
  const [schema, setSchema] = React.useState(dbType === 'mysql' ? '' : 'public');

  const placeholder = dbType === 'postgresql'
    ? 'postgresql://user:pass@host:5432/database'
    : 'mysql://user:pass@host:3306/database';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!connectionString.trim() || !query.trim()) return;
    await onSubmit({
      connectionString: connectionString.trim(),
      query: query.trim(),
      schema: schema.trim() || (dbType === 'mysql' ? undefined : 'public')
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          Connection String
        </label>
        <Input
          value={connectionString}
          onChange={(e) => setConnectionString(e.target.value)}
          placeholder={placeholder}
          className="font-mono-display text-sm"
          type="password"
          disabled={isSubmitting}
        />
        <p className="font-mono-display text-[10px] text-steel-600">
          {dbType === 'postgresql'
            ? 'Format: postgresql://user:pass@host:5432/dbname'
            : 'Format: mysql://user:pass@host:3306/dbname'
          }
        </p>
      </div>

      <div className="space-y-2">
        <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          SQL Query
        </label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="SELECT * FROM orders WHERE status = 'pending'"
          className="w-full h-24 px-3 py-2 rounded-sm bg-warehouse-800 border border-steel-700 font-mono-display text-sm text-steel-100 focus:ring-2 focus:ring-signal-500/50 resize-none"
          disabled={isSubmitting}
        />
      </div>

      {dbType === 'postgresql' && (
        <div className="space-y-2">
          <label className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
            Schema
          </label>
          <Input
            value={schema}
            onChange={(e) => setSchema(e.target.value)}
            placeholder="public"
            className="font-mono-display text-sm"
            disabled={isSubmitting}
          />
        </div>
      )}

      <Button
        type="submit"
        disabled={!connectionString.trim() || !query.trim() || isSubmitting}
        className="w-full btn-industrial font-mono-display text-sm uppercase tracking-wider"
      >
        {isSubmitting ? 'Connecting...' : `Connect ${dbType === 'postgresql' ? 'PostgreSQL' : 'MySQL'}`}
      </Button>
    </form>
  );
}

/**
 * Schema preview table.
 */
function SchemaPreview({
  columns,
  rowCount,
}: {
  columns: ColumnMetadata[];
  rowCount: number;
}) {
  const hasWarnings = columns.some(col => col.warnings.length > 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono-display text-xs text-steel-500 uppercase tracking-wider">
          Discovered Schema
        </p>
        <div className="flex items-center gap-3">
          <span className="font-mono-display text-xs text-steel-400">
            {columns.length} COLUMNS
          </span>
          <span className="font-mono-display text-xs text-status-go">
            {rowCount.toLocaleString()} ROWS
          </span>
        </div>
      </div>

      <div className="border border-steel-700 rounded-sm overflow-hidden">
        <div className="max-h-48 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-warehouse-800 sticky top-0">
              <tr className="text-left">
                <th className="px-3 py-2 font-mono-display text-xs text-steel-500 uppercase">
                  Column
                </th>
                <th className="px-3 py-2 font-mono-display text-xs text-steel-500 uppercase">
                  Type
                </th>
                <th className="px-3 py-2 font-mono-display text-xs text-steel-500 uppercase text-center">
                  Nullable
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-steel-700/50">
              {columns.map((col, i) => (
                <tr
                  key={i}
                  className={cn(
                    'hover:bg-warehouse-800/50',
                    col.warnings.length > 0 && 'bg-status-hold/5'
                  )}
                >
                  <td className="px-3 py-2 font-mono-display text-xs text-steel-200">
                    {col.name}
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn(
                      'inline-flex px-2 py-0.5 rounded text-[10px] font-mono-display font-medium',
                      getColumnTypeColor(col.type)
                    )}>
                      {col.type}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={cn(
                      'inline-flex items-center justify-center w-5 h-5 rounded text-[10px]',
                      col.nullable
                        ? 'bg-steel-700 text-steel-400'
                        : 'bg-status-stop/20 text-status-stop'
                    )}>
                      {col.nullable ? 'Y' : 'N'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {hasWarnings && (
        <div className="p-3 rounded-sm bg-status-hold/5 border border-status-hold/20">
          <p className="font-mono-display text-xs text-status-hold mb-2">
            ⚠ SCHEMA WARNINGS DETECTED
          </p>
          <ul className="space-y-1">
            {columns
              .filter(col => col.warnings.length > 0)
              .flatMap(col => col.warnings.map((w, i) => (
                <li key={`${col.name}-${i}`} className="font-mono-display text-[10px] text-steel-400">
                  • {col.name}: {w}
                </li>
              )))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * Source card component for individual data source selection.
 */
function SourceCard({
  config,
  isSelected,
  onClick,
  disabled,
}: {
  config: SourceConfig;
  isSelected: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || !config.implemented}
      className={cn(
        'relative p-3 rounded-sm border text-left transition-all',
        config.implemented
          ? isSelected
            ? 'bg-signal-500/10 border-signal-500/50 ring-1 ring-signal-500/30'
            : 'bg-warehouse-800 border-steel-700 hover:border-steel-600 hover:bg-warehouse-700'
          : 'bg-warehouse-800/50 border-steel-800 opacity-60 cursor-not-allowed'
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn(
          'p-2 rounded-sm',
          config.implemented
            ? isSelected
              ? 'bg-signal-500/20 text-signal-400'
              : 'bg-steel-700 text-steel-400'
            : 'bg-steel-800 text-steel-600'
        )}>
          {config.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn(
              'font-mono-display text-sm font-medium',
              config.implemented ? 'text-steel-200' : 'text-steel-500'
            )}>
              {config.name}
            </span>
            {!config.implemented && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-mono-display bg-steel-700 text-steel-400">
                SOON
              </span>
            )}
          </div>
          <p className="font-mono-display text-[10px] text-steel-500 mt-0.5 truncate">
            {config.description}
          </p>
        </div>
      </div>
      {isSelected && config.implemented && (
        <div className="absolute top-2 right-2">
          <svg className="h-4 w-4 text-signal-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
        </div>
      )}
    </button>
  );
}

/**
 * DataSourceManager provides UI for connecting and managing data sources.
 *
 * Features:
 * - Grid of all supported source types (9 total)
 * - Forms for implemented types (CSV, Excel, PostgreSQL, MySQL)
 * - Coming soon indicators for future integrations
 * - Schema preview after connection
 * - All operations route through MCP Gateway
 */
export function DataSourceManager({
  dataSource,
  onConnect,
  onDisconnect,
  className,
}: DataSourceManagerProps) {
  const [selectedSource, setSelectedSource] = React.useState<ExtendedSourceType>('csv');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleConnect = async (config: CsvImportConfig | ExcelImportConfig | DatabaseImportConfig) => {
    setIsSubmitting(true);
    setError(null);
    try {
      await onConnect(config);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect data source');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Group sources by category
  const filesSources = SOURCE_CONFIGS.filter(s => s.category === 'files');
  const databaseSources = SOURCE_CONFIGS.filter(s => s.category === 'databases');
  const platformSources = SOURCE_CONFIGS.filter(s => s.category === 'platforms');

  const selectedConfig = SOURCE_CONFIGS.find(s => s.id === selectedSource);

  return (
    <Card className={cn('card-industrial', className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn(
              'p-2 rounded-sm border',
              dataSource?.status === 'connected'
                ? 'bg-status-go/10 border-status-go/30'
                : 'bg-steel-800 border-steel-700'
            )}>
              {dataSource?.status === 'connected' ? (
                <svg className="h-4 w-4 text-status-go" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <DatabaseIcon className="h-4 w-4 text-steel-400" />
              )}
            </div>
            <div>
              <CardTitle className="font-display text-lg">
                Data Sources
              </CardTitle>
              <CardDescription className="font-mono-display text-xs">
                {dataSource?.status === 'connected'
                  ? `Connected: ${dataSource.type.toUpperCase()} • ${dataSource.row_count?.toLocaleString()} rows`
                  : 'Select a source type to connect via MCP Gateway'
                }
              </CardDescription>
            </div>
          </div>

          {dataSource?.status === 'connected' && (
            <Button
              onClick={onDisconnect}
              variant="ghost"
              size="sm"
              className="font-mono-display text-xs uppercase text-status-stop hover:text-status-stop hover:bg-status-stop/10"
            >
              <DisconnectIcon className="h-3 w-3 mr-1" />
              Disconnect
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Connection status indicator */}
        {dataSource?.status === 'connected' ? (
          <div className="space-y-4">
            {/* Source details */}
            <div className="p-3 rounded-sm bg-status-go/5 border border-status-go/20">
              <div className="flex items-center gap-2 mb-2">
                <div className="h-2 w-2 rounded-full bg-status-go animate-pulse" />
                <span className="font-mono-display text-xs text-status-go uppercase tracking-wider">
                  Connected via MCP Gateway
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs font-mono-display">
                <div>
                  <span className="text-steel-500">Type:</span>{' '}
                  <span className="text-steel-300">{dataSource.type.toUpperCase()}</span>
                </div>
                <div>
                  <span className="text-steel-500">Rows:</span>{' '}
                  <span className="text-status-go">{dataSource.row_count?.toLocaleString()}</span>
                </div>
                {dataSource.csv_path && (
                  <div className="col-span-2">
                    <span className="text-steel-500">Path:</span>{' '}
                    <span className="text-steel-300">{dataSource.csv_path}</span>
                  </div>
                )}
                {dataSource.excel_path && (
                  <div className="col-span-2">
                    <span className="text-steel-500">Path:</span>{' '}
                    <span className="text-steel-300">{dataSource.excel_path}</span>
                  </div>
                )}
                {dataSource.excel_sheet && (
                  <div className="col-span-2">
                    <span className="text-steel-500">Sheet:</span>{' '}
                    <span className="text-steel-300">{dataSource.excel_sheet}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Schema preview */}
            {dataSource.columns && dataSource.row_count && (
              <SchemaPreview columns={dataSource.columns} rowCount={dataSource.row_count} />
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {/* Source type selection grid */}
            <div className="space-y-3">
              {/* File Sources */}
              <div>
                <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-wider mb-2">
                  File Sources
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {filesSources.map((source) => (
                    <SourceCard
                      key={source.id}
                      config={source}
                      isSelected={selectedSource === source.id}
                      onClick={() => setSelectedSource(source.id)}
                      disabled={isSubmitting}
                    />
                  ))}
                </div>
              </div>

              {/* Database Sources */}
              <div>
                <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-wider mb-2">
                  Databases
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {databaseSources.map((source) => (
                    <SourceCard
                      key={source.id}
                      config={source}
                      isSelected={selectedSource === source.id}
                      onClick={() => setSelectedSource(source.id)}
                      disabled={isSubmitting}
                    />
                  ))}
                </div>
              </div>

              {/* Platform Sources */}
              <div>
                <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-wider mb-2">
                  Platforms
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {platformSources.map((source) => (
                    <SourceCard
                      key={source.id}
                      config={source}
                      isSelected={selectedSource === source.id}
                      onClick={() => setSelectedSource(source.id)}
                      disabled={isSubmitting}
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* Form for selected source */}
            {selectedConfig?.implemented && (
              <div className="pt-2 border-t border-steel-700">
                <p className="font-mono-display text-xs text-steel-400 mb-3">
                  Configure {selectedConfig.name} connection:
                </p>
                {selectedSource === 'csv' && (
                  <CsvImportForm onSubmit={handleConnect} isSubmitting={isSubmitting} />
                )}
                {selectedSource === 'excel' && (
                  <ExcelImportForm onSubmit={handleConnect} isSubmitting={isSubmitting} />
                )}
                {selectedSource === 'postgresql' && (
                  <DatabaseImportForm onSubmit={handleConnect} isSubmitting={isSubmitting} dbType="postgresql" />
                )}
                {selectedSource === 'mysql' && (
                  <DatabaseImportForm onSubmit={handleConnect} isSubmitting={isSubmitting} dbType="mysql" />
                )}
              </div>
            )}

            {/* Coming soon message for unimplemented sources */}
            {selectedConfig && !selectedConfig.implemented && (
              <div className="pt-2 border-t border-steel-700">
                <div className="p-4 rounded-sm bg-warehouse-800/50 border border-steel-700/50 text-center">
                  <p className="font-mono-display text-sm text-steel-400">
                    {selectedConfig.name} integration coming soon
                  </p>
                  <p className="font-mono-display text-[10px] text-steel-600 mt-1">
                    This source will be available via MCP Gateway in a future release
                  </p>
                </div>
              </div>
            )}

            {/* Error display */}
            {error && (
              <div className="p-3 rounded-sm bg-status-stop/5 border border-status-stop/20">
                <p className="font-mono-display text-xs text-status-stop">
                  ERROR: {error}
                </p>
              </div>
            )}

            {/* Help text */}
            <div className="p-3 rounded-sm bg-warehouse-800/50 border border-steel-700/50">
              <p className="font-mono-display text-[10px] text-steel-500 uppercase tracking-wider mb-1">
                MCP Gateway Architecture
              </p>
              <ul className="space-y-1 font-mono-display text-[10px] text-steel-400">
                <li>• All connections route through OrchestrationAgent</li>
                <li>• File paths should be absolute paths on the server</li>
                <li>• Database credentials are used once and NOT stored</li>
                <li>• Large datasets (&gt;10K rows) may require filters</li>
              </ul>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default DataSourceManager;
