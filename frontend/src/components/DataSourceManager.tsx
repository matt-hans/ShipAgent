/**
 * DataSourceManager - Main component for managing all data sources.
 *
 * Provides a professional UI for connecting to and managing data sources:
 *
 * FILE SOURCES (via Data Source MCP):
 * - CSV files
 * - Excel files (.xlsx)
 * - EDI files (X12, EDIFACT)
 *
 * DATABASE SOURCES (via Data Source MCP):
 * - PostgreSQL
 * - MySQL
 *
 * EXTERNAL PLATFORMS (via External Sources MCP):
 * - Shopify
 * - WooCommerce
 * - SAP
 * - Oracle
 *
 * All operations are routed through the OrchestrationAgent which
 * invokes MCP tools via the Claude Agent SDK.
 */

import * as React from 'react';
import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { useExternalSources } from '@/hooks/useExternalSources';
import { importDataSource } from '@/lib/api';
import { useAppState } from '@/hooks/useAppState';
import type { ShopifyEnvStatus, DataSourceImportRequest } from '@/types/api';

// === Source Type Definitions ===

type SourceCategory = 'file' | 'database' | 'platform';

interface IconProps {
  className?: string;
  style?: React.CSSProperties;
}

interface SourceInfo {
  id: string;
  name: string;
  category: SourceCategory;
  description: string;
  icon: React.ComponentType<IconProps>;
  color: string;
  fields: FieldDefinition[];
}

interface FieldDefinition {
  key: string;
  label: string;
  type: 'text' | 'password' | 'file';
  placeholder: string;
  required: boolean;
  helpText?: string;
}

// === Icons ===

function CSVIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="16" y2="17" />
    </svg>
  );
}

function ExcelIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="M8 13h2" />
      <path d="M8 17h2" />
      <path d="M14 13h2" />
      <path d="M14 17h2" />
    </svg>
  );
}

function EDIIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M7 8h10" />
      <path d="M7 12h10" />
      <path d="M7 16h6" />
    </svg>
  );
}

function PostgreSQLIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
      <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
    </svg>
  );
}

function MySQLIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v12c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
      <path d="M4 12c0 1.657 3.582 3 8 3s8-1.343 8-3" />
    </svg>
  );
}

function ShopifyIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="currentColor">
      <path d="M15.337 3.415c-.022-.165-.183-.247-.304-.264-.121-.017-2.422-.175-2.422-.175s-1.612-1.595-1.79-1.772c-.178-.178-.524-.124-.659-.083-.019.005-.355.109-.925.284-.552-1.585-1.525-3.038-3.237-3.038h-.15C5.273-1.908 4.53-.88 4.03.293c-1.5.461-2.627.81-2.768.855C.637 1.335.609 1.362.553 1.925.513 2.343 0 16.757 0 16.757l11.237 2.108 6.097-1.319s-1.936-13.964-2-14.131zM9.165 2.93l-1.91.59c0-.025.005-.05.005-.075 0-1.165-.805-2.115-1.833-2.115-.023 0-.046.003-.07.004.433-.566.984-.847 1.436-.847 1.147 0 1.7 1.432 2.372 2.443zm-3.27 1.01c-1.002.309-2.097.648-3.196.988.309-1.186 1.126-2.363 2.136-2.833.395.461.707.99.942 1.572.039.091.079.182.118.273zm1.053-3.04c.063 0 .126.006.187.018-.794.374-1.645 1.317-2.004 3.205l-2.38.735C3.344 3.03 4.653 1.53 5.948 1.53c.334 0 .667.123 1 .37z"/>
      <path d="M15.033 3.151c-.121-.017-2.422-.175-2.422-.175s-1.612-1.595-1.79-1.772c-.066-.066-.152-.1-.243-.117L9.165 18.865l6.097-1.319s-1.936-13.964-2-14.131c-.022-.165-.183-.247-.229-.264z" fillOpacity="0.3"/>
    </svg>
  );
}

function WooCommerceIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="currentColor">
      <path d="M2.227 4.857A3.228 3.228 0 0 0 0 7.988v6.914c0 1.809 1.418 3.228 3.227 3.228h5.009l2.382 2.857.762-.857L8.999 18.13h11.774c1.809 0 3.227-1.419 3.227-3.228V7.988c0-1.809-1.418-3.131-3.227-3.131zm4.152 2.952c.475 0 .856.19 1.142.476.381.476.572 1.142.476 2.094-.095 1.047-.476 1.904-1.047 2.475-.38.38-.857.571-1.333.571-.475 0-.856-.19-1.142-.476-.38-.475-.571-1.142-.475-2.094.095-1.047.475-1.903 1.047-2.475.38-.38.856-.571 1.332-.571zm6.057 0c.476 0 .857.19 1.143.476.38.476.571 1.142.475 2.094-.095 1.047-.475 1.904-1.047 2.475-.38.38-.857.571-1.333.571-.475 0-.856-.19-1.142-.476-.38-.475-.571-1.142-.476-2.094.096-1.047.476-1.903 1.048-2.475.38-.38.856-.571 1.332-.571zm5.485.095c.19 0 .38.095.476.285l1.618 4.95.571-4.093c.096-.571.476-.952.952-.952.571 0 .952.476.857 1.047l-1.143 5.617c-.095.476-.38.857-.856.952h-.095c-.476 0-.857-.286-1.048-.667l-1.618-4.474-.19 1.238-.381 2.951c-.095.571-.475.952-.951.952-.572 0-.953-.476-.857-1.047l1.047-5.617c.095-.476.38-.857.856-.952h.762z"/>
    </svg>
  );
}

function SAPIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="currentColor">
      <path d="M0 6.727V17.27h24V6.727zm6.545 8.182H5.18l-1.636-3.818-1.637 3.818H.545l2.182-4.91H1.09V8.727h2.182l1.637 3.818L6.545 8.73h2.182v1.272H7.09zm6.545 0h-1.363v-1.273h1.363c.377 0 .682-.305.682-.682a.682.682 0 0 0-.682-.681h-1.363a2.046 2.046 0 0 1-2.045-2.046c0-1.13.916-2.045 2.045-2.045h2.046v1.272h-2.046a.682.682 0 0 0-.681.682c0 .376.305.681.681.681h1.363a2.046 2.046 0 0 1 0 4.092zm8.181 0h-1.363v-2.727h-2.727v2.727h-1.363V8.727h1.363v2.727h2.727V8.727h1.363z"/>
    </svg>
  );
}

function OracleIcon({ className, style }: IconProps) {
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="currentColor">
      <path d="M7.072 7.072C8.393 5.75 10.107 5 12 5s3.607.75 4.928 2.072S19 9.893 19 12s-.75 3.607-2.072 4.928S14.107 19 12 19s-3.607-.75-4.928-2.072S5 14.107 5 12s.75-3.607 2.072-4.928zM12 3C6.477 3 2 7.477 2 12s4.477 9 9 9h10v-2h-3.293A8.96 8.96 0 0 0 21 12c0-4.523-3.477-9-9-9z"/>
    </svg>
  );
}

// === Source Definitions ===

const SOURCES: SourceInfo[] = [
  // File Sources
  {
    id: 'csv',
    name: 'CSV File',
    category: 'file',
    description: 'Import shipment data from comma-separated files via MCP Gateway',
    icon: CSVIcon,
    color: 'var(--color-info)',
    fields: [
      {
        key: 'file_path',
        label: 'File Path',
        type: 'text',
        placeholder: '/path/to/orders.csv',
        required: true,
        helpText: 'Absolute path to the CSV file on the server',
      },
      {
        key: 'delimiter',
        label: 'Delimiter',
        type: 'text',
        placeholder: ',',
        required: false,
        helpText: 'Column separator (default: comma)',
      },
    ],
  },
  {
    id: 'excel',
    name: 'Excel File',
    category: 'file',
    description: 'Import shipment data from .xlsx spreadsheets via MCP Gateway',
    icon: ExcelIcon,
    color: 'var(--color-success)',
    fields: [
      {
        key: 'file_path',
        label: 'File Path',
        type: 'text',
        placeholder: '/path/to/orders.xlsx',
        required: true,
        helpText: 'Absolute path to the Excel file on the server',
      },
      {
        key: 'sheet',
        label: 'Sheet Name',
        type: 'text',
        placeholder: 'Sheet1',
        required: false,
        helpText: 'Leave empty to use the first sheet',
      },
    ],
  },
  {
    id: 'edi',
    name: 'EDI File',
    category: 'file',
    description: 'Import orders from X12 or EDIFACT documents via MCP Gateway',
    icon: EDIIcon,
    color: 'var(--color-muted-foreground)',
    fields: [
      {
        key: 'file_path',
        label: 'File Path',
        type: 'text',
        placeholder: '/path/to/orders.edi',
        required: true,
        helpText: 'Absolute path to the EDI file',
      },
      {
        key: 'format',
        label: 'Format',
        type: 'text',
        placeholder: 'x12 or edifact',
        required: false,
        helpText: 'Auto-detected if not specified',
      },
    ],
  },
  // Database Sources
  {
    id: 'postgresql',
    name: 'PostgreSQL',
    category: 'database',
    description: 'Connect to PostgreSQL databases via MCP Gateway',
    icon: PostgreSQLIcon,
    color: 'oklch(0.55 0.15 230)',
    fields: [
      {
        key: 'host',
        label: 'Host',
        type: 'text',
        placeholder: 'localhost',
        required: true,
      },
      {
        key: 'port',
        label: 'Port',
        type: 'text',
        placeholder: '5432',
        required: false,
      },
      {
        key: 'database',
        label: 'Database',
        type: 'text',
        placeholder: 'shipping',
        required: true,
      },
      {
        key: 'username',
        label: 'Username',
        type: 'text',
        placeholder: 'postgres',
        required: true,
      },
      {
        key: 'password',
        label: 'Password',
        type: 'password',
        placeholder: '••••••••',
        required: true,
      },
    ],
  },
  {
    id: 'mysql',
    name: 'MySQL',
    category: 'database',
    description: 'Connect to MySQL databases via MCP Gateway',
    icon: MySQLIcon,
    color: 'oklch(0.55 0.15 40)',
    fields: [
      {
        key: 'host',
        label: 'Host',
        type: 'text',
        placeholder: 'localhost',
        required: true,
      },
      {
        key: 'port',
        label: 'Port',
        type: 'text',
        placeholder: '3306',
        required: false,
      },
      {
        key: 'database',
        label: 'Database',
        type: 'text',
        placeholder: 'shipping',
        required: true,
      },
      {
        key: 'username',
        label: 'Username',
        type: 'text',
        placeholder: 'root',
        required: true,
      },
      {
        key: 'password',
        label: 'Password',
        type: 'password',
        placeholder: '••••••••',
        required: true,
      },
    ],
  },
  // External Platform Sources
  {
    id: 'shopify',
    name: 'Shopify',
    category: 'platform',
    description: 'Fetch orders from Shopify stores via MCP Gateway',
    icon: ShopifyIcon,
    color: 'var(--color-shopify)',
    fields: [
      {
        key: 'store_url',
        label: 'Store URL',
        type: 'text',
        placeholder: 'mystore.myshopify.com',
        required: true,
        helpText: 'Your Shopify store domain',
      },
      {
        key: 'access_token',
        label: 'Access Token',
        type: 'password',
        placeholder: 'shpat_xxxxxx',
        required: true,
        helpText: 'Admin API access token from your Shopify app',
      },
    ],
  },
  {
    id: 'woocommerce',
    name: 'WooCommerce',
    category: 'platform',
    description: 'Fetch orders from WooCommerce stores via MCP Gateway',
    icon: WooCommerceIcon,
    color: 'var(--color-woocommerce)',
    fields: [
      {
        key: 'store_url',
        label: 'Store URL',
        type: 'text',
        placeholder: 'https://mystore.com',
        required: true,
        helpText: 'Your WooCommerce site URL',
      },
      {
        key: 'consumer_key',
        label: 'Consumer Key',
        type: 'text',
        placeholder: 'ck_xxxxxx',
        required: true,
        helpText: 'REST API consumer key',
      },
      {
        key: 'consumer_secret',
        label: 'Consumer Secret',
        type: 'password',
        placeholder: 'cs_xxxxxx',
        required: true,
        helpText: 'REST API consumer secret',
      },
    ],
  },
  {
    id: 'sap',
    name: 'SAP',
    category: 'platform',
    description: 'Fetch orders from SAP systems via MCP Gateway',
    icon: SAPIcon,
    color: 'var(--color-sap)',
    fields: [
      {
        key: 'base_url',
        label: 'SAP Gateway URL',
        type: 'text',
        placeholder: 'https://sap.company.com/sap/opu/odata/sap',
        required: true,
        helpText: 'OData service endpoint',
      },
      {
        key: 'username',
        label: 'Username',
        type: 'text',
        placeholder: 'SAP_USER',
        required: true,
      },
      {
        key: 'password',
        label: 'Password',
        type: 'password',
        placeholder: '••••••••',
        required: true,
      },
      {
        key: 'client',
        label: 'Client',
        type: 'text',
        placeholder: '100',
        required: false,
        helpText: 'SAP client number',
      },
    ],
  },
  {
    id: 'oracle',
    name: 'Oracle',
    category: 'platform',
    description: 'Fetch orders from Oracle databases via MCP Gateway',
    icon: OracleIcon,
    color: 'var(--color-oracle)',
    fields: [
      {
        key: 'host',
        label: 'Host',
        type: 'text',
        placeholder: 'oracle.company.com',
        required: true,
      },
      {
        key: 'port',
        label: 'Port',
        type: 'text',
        placeholder: '1521',
        required: false,
      },
      {
        key: 'service_name',
        label: 'Service Name',
        type: 'text',
        placeholder: 'ORCL',
        required: true,
      },
      {
        key: 'username',
        label: 'Username',
        type: 'text',
        placeholder: 'shipping_user',
        required: true,
      },
      {
        key: 'password',
        label: 'Password',
        type: 'password',
        placeholder: '••••••••',
        required: true,
      },
    ],
  },
];

// === Component State ===

interface SourceState {
  isConnected: boolean;
  isConnecting: boolean;
  lastImported?: string;
  rowCount?: number;
  error?: string | null;
}

type SourceStates = Record<string, SourceState>;

const initialSourceState: SourceState = {
  isConnected: false,
  isConnecting: false,
  error: null,
};

// === Components ===

interface SourceCardProps {
  source: SourceInfo;
  state: SourceState;
  onConfigure: () => void;
  onDisconnect: () => void;
}

function SourceCard({ source, state, onConfigure, onDisconnect }: SourceCardProps) {
  const Icon = source.icon;

  return (
    <div
      className={cn(
        'platform-card group',
        state.isConnected && 'platform-card--connected'
      )}
      style={{ '--platform-color': source.color } as React.CSSProperties}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: `color-mix(in oklch, ${source.color} 15%, transparent)` }}
          >
            <Icon
              className="w-6 h-6"
              style={{ color: source.color }}
            />
          </div>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'status-dot',
                state.isConnected ? 'status-dot--connected' : 'status-dot--disconnected'
              )}
            />
            <span className="text-xs text-muted-foreground">
              {state.isConnecting ? 'Connecting...' : state.isConnected ? 'Connected' : 'Not configured'}
            </span>
          </div>
        </div>
        <CardTitle className="text-lg mt-3">{source.name}</CardTitle>
        <CardDescription className="text-sm">
          {source.description}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        {state.error && (
          <p className="text-xs text-destructive mb-3 p-2 rounded bg-destructive/10">
            {state.error}
          </p>
        )}
        {state.isConnected && state.lastImported && (
          <p className="text-xs text-muted-foreground mb-3">
            Last import: {state.lastImported}
            {state.rowCount !== undefined && ` (${state.rowCount} rows)`}
          </p>
        )}
        <div className="flex gap-2">
          {state.isConnected ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={onConfigure}
                className="flex-1"
              >
                Reimport
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onDisconnect}
                className="text-muted-foreground hover:text-destructive"
              >
                Clear
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              onClick={onConfigure}
              disabled={state.isConnecting}
              className="w-full"
              style={{
                backgroundColor: source.color,
                color: 'white',
              }}
            >
              {state.isConnecting ? 'Connecting...' : source.category === 'file' ? 'Import' : 'Connect'}
            </Button>
          )}
        </div>
      </CardContent>
    </div>
  );
}

// === Shopify Status Card ===

interface ShopifyStatusCardProps {
  source: SourceInfo;
  envStatus: ShopifyEnvStatus | null;
  isCheckingEnv: boolean;
  onRefresh: () => void;
}

function ShopifyStatusCard({ source, envStatus, isCheckingEnv, onRefresh }: ShopifyStatusCardProps) {
  const Icon = source.icon;

  // Determine status
  const isConnected = envStatus?.valid === true;
  const isConfigured = envStatus?.configured === true;
  const hasError = isConfigured && !isConnected;

  // Status display
  let statusText = 'Checking...';
  let statusDotClass = 'status-dot--disconnected';

  if (!isCheckingEnv) {
    if (isConnected) {
      statusText = 'Connected';
      statusDotClass = 'status-dot--connected';
    } else if (hasError) {
      statusText = 'Invalid credentials';
      statusDotClass = 'status-dot--error';
    } else {
      statusText = 'Not configured';
      statusDotClass = 'status-dot--disconnected';
    }
  }

  return (
    <div
      className={cn(
        'platform-card group',
        isConnected && 'platform-card--connected'
      )}
      style={{ '--platform-color': source.color } as React.CSSProperties}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: `color-mix(in oklch, ${source.color} 15%, transparent)` }}
          >
            <Icon
              className="w-6 h-6"
              style={{ color: source.color }}
            />
          </div>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'status-dot',
                statusDotClass
              )}
            />
            <span className="text-xs text-muted-foreground">
              {statusText}
            </span>
          </div>
        </div>
        <CardTitle className="text-lg mt-3">{source.name}</CardTitle>
        <CardDescription className="text-sm">
          {source.description}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Connection info based on status */}
        {isCheckingEnv && (
          <p className="text-xs text-muted-foreground mb-3 p-2 rounded bg-muted/50">
            Checking environment credentials...
          </p>
        )}

        {!isCheckingEnv && isConnected && envStatus && (
          <div className="space-y-2 mb-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
              <span className="font-medium text-foreground">
                {envStatus.store_name || envStatus.store_url}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              Configured via environment variables
            </p>
          </div>
        )}

        {!isCheckingEnv && hasError && envStatus?.error && (
          <div className="space-y-2 mb-3">
            <p className="text-xs text-destructive p-2 rounded bg-destructive/10">
              {envStatus.error}
            </p>
            <p className="text-xs text-muted-foreground">
              Check SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_DOMAIN in .env
            </p>
          </div>
        )}

        {!isCheckingEnv && !isConfigured && (
          <div className="space-y-2 mb-3">
            <p className="text-xs text-muted-foreground p-2 rounded bg-muted/50">
              Add credentials to .env file:
            </p>
            <code className="block text-xs p-2 rounded bg-muted font-mono">
              SHOPIFY_ACCESS_TOKEN=shpat_xxx<br />
              SHOPIFY_STORE_DOMAIN=store.myshopify.com
            </code>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          <Button
            variant={isConnected ? 'outline' : 'default'}
            size="sm"
            onClick={onRefresh}
            disabled={isCheckingEnv}
            className="w-full"
            style={!isConnected ? { backgroundColor: source.color, color: 'white' } : undefined}
          >
            {isCheckingEnv ? 'Checking...' : 'Refresh Status'}
          </Button>
        </div>
      </CardContent>
    </div>
  );
}

interface ConfigureDialogProps {
  source: SourceInfo | null;
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (sourceId: string, values: Record<string, string>) => Promise<void>;
  isSubmitting: boolean;
}

function ConfigureDialog({ source, isOpen, onClose, onSubmit, isSubmitting }: ConfigureDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  // Reset form when source changes
  useEffect(() => {
    if (source) {
      const initial: Record<string, string> = {};
      source.fields.forEach(field => {
        initial[field.key] = '';
      });
      setValues(initial);
      setError(null);
    }
  }, [source]);

  if (!source) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validate required fields
    const missingFields = source.fields
      .filter(f => f.required && !values[f.key]?.trim())
      .map(f => f.label);

    if (missingFields.length > 0) {
      setError(`Required fields: ${missingFields.join(', ')}`);
      return;
    }

    try {
      await onSubmit(source.id, values);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Configuration failed');
    }
  };

  const actionLabel = source.category === 'file' ? 'Import' : 'Connect';

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: `color-mix(in oklch, ${source.color} 15%, transparent)` }}
            >
              <source.icon className="w-5 h-5" style={{ color: source.color }} />
            </div>
            {actionLabel} {source.name}
          </DialogTitle>
          <DialogDescription>
            {source.category === 'file'
              ? 'Enter the file path to import data via MCP Gateway.'
              : 'Enter your credentials to connect via MCP Gateway.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          {source.fields.map((field) => (
            <div key={field.key} className="space-y-2">
              <label className="text-sm font-medium" htmlFor={field.key}>
                {field.label}
                {field.required && <span className="text-destructive ml-1">*</span>}
              </label>
              <Input
                id={field.key}
                type={field.type === 'password' ? 'password' : 'text'}
                placeholder={field.placeholder}
                value={values[field.key] || ''}
                onChange={(e) => setValues(prev => ({ ...prev, [field.key]: e.target.value }))}
                autoComplete={field.type === 'password' ? 'current-password' : 'off'}
              />
              {field.helpText && (
                <p className="text-xs text-muted-foreground">{field.helpText}</p>
              )}
            </div>
          ))}

          {error && (
            <p className="text-sm text-destructive p-2 rounded bg-destructive/10">
              {error}
            </p>
          )}

          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting}
              style={{ backgroundColor: source.color, color: 'white' }}
            >
              {isSubmitting ? `${actionLabel}ing...` : actionLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CategorySection({
  title,
  description,
  sources,
  states,
  onConfigure,
  onDisconnect,
  shopifyEnvStatus,
  isCheckingShopifyEnv,
  onRefreshShopify,
}: {
  title: string;
  description: string;
  sources: SourceInfo[];
  states: SourceStates;
  onConfigure: (source: SourceInfo) => void;
  onDisconnect: (sourceId: string) => void;
  shopifyEnvStatus?: ShopifyEnvStatus | null;
  isCheckingShopifyEnv?: boolean;
  onRefreshShopify?: () => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sources.map((source) => {
          // Use ShopifyStatusCard for Shopify
          if (source.id === 'shopify' && onRefreshShopify) {
            return (
              <ShopifyStatusCard
                key={source.id}
                source={source}
                envStatus={shopifyEnvStatus ?? null}
                isCheckingEnv={isCheckingShopifyEnv ?? false}
                onRefresh={onRefreshShopify}
              />
            );
          }

          return (
            <SourceCard
              key={source.id}
              source={source}
              state={states[source.id] || initialSourceState}
              onConfigure={() => onConfigure(source)}
              onDisconnect={() => onDisconnect(source.id)}
            />
          );
        })}
      </div>
    </div>
  );
}

// === Main Component ===

export function DataSourceManager() {
  const [states, setStates] = useState<SourceStates>(() => {
    const initial: SourceStates = {};
    SOURCES.forEach(s => {
      initial[s.id] = { ...initialSourceState };
    });
    return initial;
  });

  const [configureSource, setConfigureSource] = useState<SourceInfo | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Use external sources hook for Shopify env detection
  const { state: externalState, checkShopifyEnv } = useExternalSources();

  const fileSources = SOURCES.filter(s => s.category === 'file');
  const databaseSources = SOURCES.filter(s => s.category === 'database');
  const platformSources = SOURCES.filter(s => s.category === 'platform');

  const handleConfigure = (source: SourceInfo) => {
    setConfigureSource(source);
  };

  const handleCloseDialog = () => {
    setConfigureSource(null);
  };

  const handleDisconnect = (sourceId: string) => {
    setStates(prev => ({
      ...prev,
      [sourceId]: { ...initialSourceState },
    }));
  };

  // Access global state for data source tracking
  const { setDataSource } = useAppState();

  const handleSubmit = async (sourceId: string, values: Record<string, string>) => {
    setIsSubmitting(true);
    setStates(prev => ({
      ...prev,
      [sourceId]: { ...prev[sourceId], isConnecting: true, error: null },
    }));

    try {
      const source = SOURCES.find(s => s.id === sourceId);
      if (!source) throw new Error('Unknown source');

      if (source.category === 'file' && (sourceId === 'csv' || sourceId === 'excel')) {
        // Use the new data source import API for CSV/Excel
        const importConfig: DataSourceImportRequest = {
          type: sourceId as 'csv' | 'excel',
          file_path: values.file_path,
        };
        if (sourceId === 'csv' && values.delimiter && values.delimiter !== ',') {
          importConfig.delimiter = values.delimiter;
        }
        if (sourceId === 'excel' && values.sheet) {
          importConfig.sheet = values.sheet;
        }

        const result = await importDataSource(importConfig);

        if (result.status === 'error') {
          throw new Error(result.error || 'Import failed');
        }

        // Update global data source state
        setDataSource({
          type: sourceId,
          status: 'connected',
          row_count: result.row_count,
          column_count: result.columns.length,
          columns: result.columns.map(c => ({
            name: c.name,
            type: c.type as any,
            nullable: c.nullable,
            warnings: [],
          })),
          connected_at: new Date().toISOString(),
          csv_path: sourceId === 'csv' ? values.file_path : undefined,
          excel_path: sourceId === 'excel' ? values.file_path : undefined,
        });

        // Update local card state
        setStates(prev => ({
          ...prev,
          [sourceId]: {
            isConnected: true,
            isConnecting: false,
            lastImported: new Date().toLocaleString(),
            rowCount: result.row_count,
            error: null,
          },
        }));
      } else if (source.category === 'database') {
        // Database import via data source API
        const port = values.port || (sourceId === 'postgresql' ? '5432' : '3306');
        const connStr = `${sourceId === 'postgresql' ? 'postgresql' : 'mysql'}://${values.username}:${values.password}@${values.host}:${port}/${values.database}`;

        const result = await importDataSource({
          type: 'database',
          connection_string: connStr,
          query: `SELECT * FROM shipments`, // Default query — user can refine via NL
        });

        if (result.status === 'error') {
          throw new Error(result.error || 'Import failed');
        }

        setDataSource({
          type: 'database',
          status: 'connected',
          row_count: result.row_count,
          column_count: result.columns.length,
          columns: result.columns.map(c => ({
            name: c.name,
            type: c.type as any,
            nullable: c.nullable,
            warnings: [],
          })),
          connected_at: new Date().toISOString(),
        });

        setStates(prev => ({
          ...prev,
          [sourceId]: {
            isConnected: true,
            isConnecting: false,
            lastImported: new Date().toLocaleString(),
            rowCount: result.row_count,
            error: null,
          },
        }));
      } else {
        // External platform connections are managed via the Sidebar platform panel
        throw new Error('External platform connections should be managed via the Sidebar platform panel.');
      }
    } catch (err) {
      setStates(prev => ({
        ...prev,
        [sourceId]: {
          ...prev[sourceId],
          isConnecting: false,
          error: err instanceof Error ? err.message : 'Operation failed',
        },
      }));
      throw err;
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-8 animate-reveal" style={{ animationFillMode: 'forwards' }}>
      {/* File Sources */}
      <CategorySection
        title="File Sources"
        description="Import shipment data from local files processed by the Data Source MCP"
        sources={fileSources}
        states={states}
        onConfigure={handleConfigure}
        onDisconnect={handleDisconnect}
      />

      {/* Database Sources */}
      <CategorySection
        title="Database Sources"
        description="Connect to databases and import order data via the Data Source MCP"
        sources={databaseSources}
        states={states}
        onConfigure={handleConfigure}
        onDisconnect={handleDisconnect}
      />

      {/* External Platforms */}
      <CategorySection
        title="External Platforms"
        description="Connect to e-commerce platforms and ERP systems via the External Sources MCP"
        sources={platformSources}
        states={states}
        onConfigure={handleConfigure}
        onDisconnect={handleDisconnect}
        shopifyEnvStatus={externalState.shopifyEnvStatus}
        isCheckingShopifyEnv={externalState.isCheckingEnv}
        onRefreshShopify={checkShopifyEnv}
      />

      {/* Configure Dialog */}
      <ConfigureDialog
        source={configureSource}
        isOpen={configureSource !== null}
        onClose={handleCloseDialog}
        onSubmit={handleSubmit}
        isSubmitting={isSubmitting}
      />
    </div>
  );
}

export default DataSourceManager;
