/**
 * CommandCenter - Conversational interface for issuing shipping commands.
 *
 * Features:
 * - Chat-style conversation thread
 * - Command input with autocomplete
 * - Preview cards inline in conversation
 * - Progress display during execution
 * - Elicitation for clarifying questions
 */

import * as React from 'react';
import { useAppState, type ConversationMessage } from '@/hooks/useAppState';
import { useJobProgress } from '@/hooks/useJobProgress';
import { useExternalSources } from '@/hooks/useExternalSources';
import { cn } from '@/lib/utils';
import { submitCommand, waitForPreview, confirmJob, cancelJob, getJob, getMergedLabelsUrl } from '@/lib/api';
import type { Job, BatchPreview, PreviewRow, OrderData } from '@/types/api';
import { ShipAgentLogo } from '@/components/ui/ShipAgentLogo';
import { LabelPreview } from '@/components/LabelPreview';
import { JobDetailPanel } from '@/components/JobDetailPanel';

interface CommandCenterProps {
  activeJob: Job | null;
}

// Icons
function SendIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M22 2L11 13" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M22 2L15 22L11 13L2 9L22 2Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StopIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <rect x="6" y="6" width="12" height="12" rx="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <line x1="18" y1="6" x2="6" y2="18" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="6" y1="6" x2="18" y2="18" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="7 10 12 15 17 10" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="15" x2="12" y2="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PackageIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M16.5 9.4l-9-5.19" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="22.08" x2="12" y2="12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="6 9 12 15 18 9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MapPinIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function UserIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

// Format currency from cents
function formatCurrency(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

// Format relative time
function formatRelativeTime(date: Date): string {
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);

  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'Just now';
}

// Message components
function SystemMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 animate-fade-in-up">
      {/* Avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="flex-1 space-y-2">
        <div className="message-system">
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{message.content}</p>
        </div>

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="flex gap-3 justify-end animate-fade-in-up">
      <div className="flex-1 space-y-2 flex flex-col items-end">
        <div className="message-user">
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        </div>

        <span className="text-[10px] font-mono text-slate-500">
          {formatRelativeTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-cyan-600/20 border border-cyan-500/30 flex items-center justify-center">
        <PackageIcon className="w-4 h-4 text-cyan-400" />
      </div>

      <div className="message-system py-3">
        <div className="typing-indicator">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

// Shopping cart icon for customer
function ShoppingCartIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <circle cx="9" cy="21" r="1" />
      <circle cx="20" cy="21" r="1" />
      <path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Expanded shipment details component
function ShipmentDetails({ orderData }: { orderData: OrderData }) {
  // Check if customer is different from recipient (e.g., gift order)
  const isDifferentRecipient = orderData.customer_name !== orderData.ship_to_name;

  return (
    <div className="px-4 py-3 bg-slate-800/30 border-t border-slate-800 animate-fade-in">
      <div className="grid grid-cols-2 gap-4">
        {/* Customer Info (Order Placer) */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider">
            <ShoppingCartIcon className="w-3 h-3" />
            <span>Customer (Ordered By)</span>
          </div>
          <div className="space-y-0.5">
            <p className="text-sm text-slate-200">{orderData.customer_name}</p>
            {orderData.customer_email && (
              <p className="text-[10px] font-mono text-slate-500">{orderData.customer_email}</p>
            )}
          </div>
        </div>

        {/* Recipient Info (Ship To) */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider">
            <UserIcon className="w-3 h-3" />
            <span>Recipient (Ship To)</span>
            {isDifferentRecipient && (
              <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 text-[8px] font-medium">
                GIFT
              </span>
            )}
          </div>
          <div className="space-y-0.5">
            <p className="text-sm text-slate-200">{orderData.ship_to_name}</p>
            {orderData.ship_to_company && (
              <p className="text-xs text-slate-400">{orderData.ship_to_company}</p>
            )}
            {orderData.ship_to_phone && (
              <p className="text-[10px] font-mono text-slate-500">{orderData.ship_to_phone}</p>
            )}
          </div>
        </div>
      </div>

      {/* Address Info */}
      <div className="mt-3 pt-3 border-t border-slate-800/50">
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider mb-2">
          <MapPinIcon className="w-3 h-3" />
          <span>Shipping Address</span>
        </div>
        <div className="space-y-0.5">
          <p className="text-sm text-slate-200">{orderData.ship_to_address1}</p>
          {orderData.ship_to_address2 && (
            <p className="text-sm text-slate-300">{orderData.ship_to_address2}</p>
          )}
          <p className="text-sm text-slate-300">
            {orderData.ship_to_city}, {orderData.ship_to_state} {orderData.ship_to_postal_code}
          </p>
          <p className="text-[10px] font-mono text-slate-500">{orderData.ship_to_country}</p>
        </div>
      </div>

      {/* Order Reference */}
      <div className="mt-3 pt-3 border-t border-slate-800/50 flex items-center gap-4">
        {orderData.order_number && (
          <span className="text-[10px] font-mono text-slate-500">
            Order #<span className="text-slate-400">{orderData.order_number}</span>
          </span>
        )}
        <span className="text-[10px] font-mono text-slate-500">
          ID: <span className="text-slate-400">{orderData.order_id}</span>
        </span>
      </div>
    </div>
  );
}

// Shipment row component with expand/collapse
function ShipmentRow({
  row,
  isExpanded,
  onToggle,
}: {
  row: PreviewRow;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const hasDetails = !!row.order_data;
  const customerName = row.order_data?.customer_name;
  const recipientName = row.recipient_name;
  const isDifferentRecipient = customerName && customerName !== recipientName;

  return (
    <div className="border-b border-slate-800 last:border-0">
      <button
        onClick={hasDetails ? onToggle : undefined}
        className={cn(
          'w-full flex items-center justify-between px-3 py-2.5 text-xs transition-colors',
          hasDetails && 'hover:bg-slate-800/30 cursor-pointer',
          !hasDetails && 'cursor-default',
          isExpanded && 'bg-slate-800/20'
        )}
      >
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {hasDetails && (
            <ChevronDownIcon
              className={cn(
                'w-3.5 h-3.5 text-slate-500 transition-transform flex-shrink-0',
                isExpanded && 'rotate-180'
              )}
            />
          )}
          <div className="flex-1 min-w-0 text-left">
            {/* Show customer name first if different from recipient */}
            {isDifferentRecipient ? (
              <>
                <div className="flex items-center gap-2">
                  <span className="text-slate-400 text-[10px]">Customer:</span>
                  <span className="text-slate-300 font-medium truncate">{customerName}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 text-[10px]">Ship to:</span>
                  <span className="text-slate-200 font-medium truncate">{recipientName}</span>
                  <span className="px-1 py-0.5 rounded bg-amber-500/20 text-amber-400 text-[8px] font-medium">
                    GIFT
                  </span>
                </div>
                <span className="text-slate-500 text-[10px]">{row.city_state}</span>
              </>
            ) : (
              <>
                <span className="text-slate-200 font-medium truncate block">{recipientName}</span>
                <span className="text-slate-500 text-[10px]">{row.city_state}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="font-mono text-slate-400 text-[10px]">{row.service}</span>
          <span className="font-mono text-amber-400 font-medium">{formatCurrency(row.estimated_cost_cents)}</span>
        </div>
      </button>

      {/* Expanded details */}
      {isExpanded && row.order_data && (
        <ShipmentDetails orderData={row.order_data} />
      )}
    </div>
  );
}

// Preview card component
function PreviewCard({
  preview,
  onConfirm,
  onCancel,
  isConfirming,
}: {
  preview: BatchPreview;
  onConfirm: () => void;
  onCancel: () => void;
  isConfirming: boolean;
}) {
  const [expandedRows, setExpandedRows] = React.useState<Set<number>>(new Set());

  const toggleRow = (rowNumber: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(rowNumber)) {
        next.delete(rowNumber);
      } else {
        next.add(rowNumber);
      }
      return next;
    });
  };

  return (
    <div className="card-premium p-4 space-y-4 animate-scale-in border-gradient">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">Shipment Preview</h3>
        <span className="badge badge-info">Ready</span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.total_rows}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Total Rows</p>
        </div>
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-amber-400">
            {formatCurrency(preview.total_estimated_cost_cents)}
          </p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Est. Cost</p>
        </div>
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.rows_with_warnings}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Warnings</p>
        </div>
      </div>

      {/* Sample rows */}
      {preview.preview_rows.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Sample Shipments</p>
            {preview.preview_rows.some(r => r.order_data) && (
              <p className="text-[10px] text-slate-600">Click to expand</p>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto rounded-md border border-slate-800 scrollable">
            {preview.preview_rows.slice(0, 10).map((row) => (
              <ShipmentRow
                key={row.row_number}
                row={row}
                isExpanded={expandedRows.has(row.row_number)}
                onToggle={() => toggleRow(row.row_number)}
              />
            ))}
          </div>
          {preview.additional_rows > 0 && (
            <p className="text-[10px] text-center text-slate-500">
              +{preview.additional_rows} more rows
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button
          onClick={onCancel}
          disabled={isConfirming}
          className="flex-1 btn-secondary py-2.5 flex items-center justify-center gap-2"
        >
          <XIcon className="w-4 h-4" />
          <span>Cancel</span>
        </button>
        <button
          onClick={onConfirm}
          disabled={isConfirming}
          className="flex-1 btn-primary py-2.5 flex items-center justify-center gap-2"
        >
          {isConfirming ? (
            <>
              <span className="w-4 h-4 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
              <span>Confirming...</span>
            </>
          ) : (
            <>
              <CheckIcon className="w-4 h-4" />
              <span>Confirm & Execute</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// Progress display component
function ProgressDisplay({ jobId, onComplete }: { jobId: string; onComplete?: () => void }) {
  const { progress } = useJobProgress(jobId);
  const completeFiredRef = React.useRef(false);

  const percentage = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
  const isRunning = progress.status === 'running';
  const isComplete = progress.status === 'completed';
  const isFailed = progress.status === 'failed';

  // Fire onComplete callback once when status transitions to completed
  React.useEffect(() => {
    if (isComplete && !completeFiredRef.current && onComplete) {
      completeFiredRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  return (
    <div className={cn(
      'card-premium p-4 space-y-4',
      isRunning && 'scan-line',
      isComplete && 'border-success/30',
      isFailed && 'border-error/30'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">
          {isComplete ? 'Batch Complete' : isFailed ? 'Batch Failed' : 'Processing Shipments'}
        </h3>
        <span className={cn(
          'badge',
          isComplete && 'badge-success',
          isFailed && 'badge-error',
          isRunning && 'badge-info'
        )}>
          {progress.status}
        </span>
      </div>

      {/* Progress bar */}
      <div className="space-y-2">
        <div className="progress-bar">
          <div
            className={cn('progress-bar-fill', isRunning && 'animated')}
            style={{ width: `${percentage}%` }}
          />
        </div>
        <div className="flex justify-between text-xs font-mono">
          <span className="text-slate-400">
            {progress.processed} / {progress.total} rows
          </span>
          <span className="text-slate-400">{percentage}%</span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-2">
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-slate-100">{progress.total}</p>
          <p className="text-[10px] font-mono text-slate-500">Total</p>
        </div>
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-success">{progress.successful}</p>
          <p className="text-[10px] font-mono text-slate-500">Success</p>
        </div>
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-error">{progress.failed}</p>
          <p className="text-[10px] font-mono text-slate-500">Failed</p>
        </div>
        <div className="p-2 rounded bg-slate-800/50 text-center">
          <p className="text-lg font-semibold text-amber-400">
            {formatCurrency(progress.totalCostCents)}
          </p>
          <p className="text-[10px] font-mono text-slate-500">Cost</p>
        </div>
      </div>

      {/* Error message if failed */}
      {isFailed && progress.error && (
        <div className="p-3 rounded-lg bg-error/10 border border-error/30">
          <p className="text-xs font-mono text-error">
            {progress.error.code}: {progress.error.message}
          </p>
        </div>
      )}

      {/* Download button if complete */}
      {isComplete && (
        <button
          onClick={() => window.open(getMergedLabelsUrl(jobId), '_blank')}
          className="w-full btn-primary py-2.5 flex items-center justify-center gap-2"
        >
          <DownloadIcon className="w-4 h-4" />
          <span>Download All Labels (PDF)</span>
        </button>
      )}
    </div>
  );
}

// Welcome message with workflow steps
function WelcomeMessage({ onExampleClick }: { onExampleClick?: (text: string) => void }) {
  const { dataSource } = useAppState();
  const { state: externalState } = useExternalSources();

  // Check if Shopify is connected via environment
  const shopifyEnvConnected = externalState.shopifyEnvStatus?.valid === true;
  const shopifyStoreName = externalState.shopifyEnvStatus?.store_name || externalState.shopifyEnvStatus?.store_url;

  // Consider connected if either local dataSource OR Shopify env is connected
  const isConnected = dataSource || shopifyEnvConnected;

  const examples = [
    { text: 'Ship all California orders using UPS Ground', desc: 'Filter by state' },
    { text: "Ship today's pending orders with 2nd Day Air", desc: 'Filter by status & date' },
    { text: 'Create shipments for orders over $100', desc: 'Filter by amount' },
  ];

  // Not connected - show getting started workflow
  if (!isConnected) {
    return (
      <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center mb-4">
          <ShipAgentLogo className="w-12 h-12" primaryColor="#f59e0b"  />
        </div>

        <h2 className="text-xl font-semibold text-slate-100 mb-2">
          Welcome to ShipAgent
        </h2>

        <p className="text-sm text-slate-400 max-w-md mb-6">
          Natural language batch shipment processing powered by AI.
          <br />
          Connect a data source from the sidebar to get started.
        </p>

        {/* Workflow steps */}
        <div className="grid grid-cols-3 gap-4 w-full max-w-lg mb-6">
          {[
            { step: '1', title: 'Connect', desc: 'File, database, or platform' },
            { step: '2', title: 'Describe', desc: 'Natural language command' },
            { step: '3', title: 'Ship', desc: 'Preview, approve, execute' },
          ].map((item) => (
            <div key={item.step} className="text-center">
              <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto mb-2">
                <span className="text-xs font-mono text-amber-400">{item.step}</span>
              </div>
              <p className="text-xs font-medium text-slate-200">{item.title}</p>
              <p className="text-[10px] text-slate-500">{item.desc}</p>
            </div>
          ))}
        </div>

        {/* Example commands (preview) */}
        <div className="space-y-2 w-full max-w-md opacity-50">
          <p className="text-[10px] font-mono text-slate-600 uppercase tracking-wider">Example commands</p>
          <div className="space-y-1.5">
            {examples.map((example, i) => (
              <div
                key={i}
                className="px-3 py-2 rounded-lg bg-slate-800/30 border border-slate-800/50 text-left"
              >
                <p className="text-xs text-slate-500">"{example.text}"</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Connected - ready to ship
  // Determine what data source to display
  const sourceDisplay = dataSource
    ? { name: dataSource.type.toUpperCase(), detail: dataSource.row_count ? `${dataSource.row_count.toLocaleString()} rows` : null }
    : shopifyEnvConnected
    ? { name: 'SHOPIFY', detail: shopifyStoreName || null }
    : { name: 'Unknown', detail: null };

  return (
    <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-success/10 border border-success/30 flex items-center justify-center mb-4">
        <ShipAgentLogo className="w-12 h-12" primaryColor="#22c55e"  />
      </div>

      <h2 className="text-xl font-semibold text-slate-100 mb-2">
        Ready to Ship
      </h2>

      <p className="text-sm text-slate-400 max-w-md mb-2">
        Connected to <span className="text-amber-400 font-medium">{sourceDisplay.name}</span>
        {sourceDisplay.detail && (
          <> · <span className="text-slate-500">{sourceDisplay.detail}</span></>
        )}
      </p>

      <p className="text-xs text-slate-500 max-w-md mb-6">
        Describe what you want to ship in natural language. ShipAgent will parse your intent,
        filter your data, and generate a preview for your approval.
      </p>

      {/* Clickable examples */}
      <div className="space-y-3 w-full max-w-md">
        <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Click to try</p>
        <div className="space-y-2">
          {examples.map((example, i) => (
            <button
              key={i}
              onClick={() => onExampleClick?.(example.text)}
              className="w-full px-4 py-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-left hover:bg-slate-800 hover:border-slate-600 transition-colors group"
            >
              <p className="text-sm text-slate-300 group-hover:text-slate-100">"{example.text}"</p>
              <p className="text-[10px] text-slate-600 mt-0.5">{example.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// Main CommandCenter component
export function CommandCenter({ activeJob }: CommandCenterProps) {
  const {
    dataSource,
    conversation,
    addMessage,
    isProcessing,
    setIsProcessing,
    setActiveJob,
    refreshJobList,
  } = useAppState();

  const { state: externalState } = useExternalSources();

  // Check if Shopify is connected via environment
  const shopifyEnvConnected = externalState.shopifyEnvStatus?.valid === true;

  // Consider connected if either local dataSource OR Shopify env is connected
  const hasDataSource = !!dataSource || shopifyEnvConnected;

  const [inputValue, setInputValue] = React.useState('');
  const [preview, setPreview] = React.useState<BatchPreview | null>(null);
  const [currentJobId, setCurrentJobId] = React.useState<string | null>(null);
  const [isConfirming, setIsConfirming] = React.useState(false);
  const [executingJobId, setExecutingJobId] = React.useState<string | null>(null);
  const [showLabelPreview, setShowLabelPreview] = React.useState(false);

  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation, preview, executingJobId]);

  // Handle command submit
  const handleSubmit = async () => {
    const command = inputValue.trim();
    if (!command || isProcessing || !hasDataSource) return;

    setInputValue('');
    setIsProcessing(true);

    // Add user message
    addMessage({ role: 'user', content: command });

    try {
      // Submit command to backend
      const result = await submitCommand(command);
      setCurrentJobId(result.job_id);

      // Wait for processing and fetch preview
      // This polls until rows are ready (background task completes)
      const previewData = await waitForPreview(result.job_id);
      setPreview(previewData);

      // Add system response
      addMessage({
        role: 'system',
        content: `Found ${previewData.total_rows} matching rows. Estimated cost: ${formatCurrency(previewData.total_estimated_cost_cents)}.\n\nReview the preview below and confirm to proceed.`,
        metadata: {
          jobId: result.job_id,
          action: 'preview',
          preview: {
            rowCount: previewData.total_rows,
            estimatedCost: previewData.total_estimated_cost_cents,
            warnings: previewData.rows_with_warnings,
          },
        },
      });
    } catch (err) {
      addMessage({
        role: 'system',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to process command'}`,
        metadata: { action: 'error' },
      });
    } finally {
      setIsProcessing(false);
    }
  };

  // Handle confirm
  const handleConfirm = async () => {
    if (!currentJobId) return;

    setIsConfirming(true);
    try {
      await confirmJob(currentJobId);
      setExecutingJobId(currentJobId);
      setPreview(null);

      addMessage({
        role: 'system',
        content: 'Batch confirmed. Processing shipments...',
        metadata: { jobId: currentJobId, action: 'execute' },
      });

      // Fetch job and set as active
      const job = await getJob(currentJobId);
      setActiveJob(job);
    } catch (err) {
      addMessage({
        role: 'system',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to confirm batch'}`,
        metadata: { action: 'error' },
      });
    } finally {
      setIsConfirming(false);
    }
  };

  // Handle cancel
  const handleCancel = async () => {
    if (!currentJobId) return;

    try {
      await cancelJob(currentJobId);
      setPreview(null);
      setCurrentJobId(null);

      addMessage({
        role: 'system',
        content: 'Batch cancelled. You can enter a new command.',
      });
    } catch (err) {
      console.error('Failed to cancel:', err);
    }
  };

  // Handle key press
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Show job detail panel when a sidebar job is selected and no active conversation
  const showJobDetail = activeJob && conversation.length === 0 && !preview && !executingJobId;

  if (showJobDetail) {
    return (
      <JobDetailPanel
        job={activeJob}
        onBack={() => setActiveJob(null)}
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto scrollable p-6">
        {conversation.length === 0 && !preview && !executingJobId ? (
          <WelcomeMessage onExampleClick={(text) => setInputValue(text)} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {conversation.map((message) => (
              message.role === 'user' ? (
                <UserMessage key={message.id} message={message} />
              ) : (
                <SystemMessage key={message.id} message={message} />
              )
            ))}

            {/* Preview card */}
            {preview && !executingJobId && (
              <div className="pl-11">
                <PreviewCard
                  preview={preview}
                  onConfirm={handleConfirm}
                  onCancel={handleCancel}
                  isConfirming={isConfirming}
                />
              </div>
            )}

            {/* Progress display */}
            {executingJobId && (
              <div className="pl-11">
                <ProgressDisplay
                  jobId={executingJobId}
                  onComplete={() => {
                    setShowLabelPreview(true);
                    refreshJobList();
                  }}
                />
              </div>
            )}

            {/* Typing indicator */}
            {isProcessing && <TypingIndicator />}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-slate-800 px-4 py-3 bg-void-900/50 backdrop-blur">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  !hasDataSource
                    ? 'Connect a data source to begin...'
                    : 'Enter a shipping command...'
                }
                disabled={!hasDataSource || isProcessing || !!preview}
                className={cn(
                  'input-command pr-12',
                  (!hasDataSource || isProcessing || !!preview) && 'opacity-50 cursor-not-allowed'
                )}
              />

              {/* Character count */}
              {inputValue.length > 0 && (
                <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] font-mono text-slate-500">
                  {inputValue.length}
                </span>
              )}
            </div>

            <button
              onClick={handleSubmit}
              disabled={!inputValue.trim() || !hasDataSource || isProcessing || !!preview}
              className={cn(
                'btn-primary px-4',
                (!inputValue.trim() || !hasDataSource || isProcessing || !!preview) && 'opacity-50 cursor-not-allowed'
              )}
            >
              {isProcessing ? (
                <span className="w-4 h-4 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
              ) : executingJobId ? (
                <StopIcon className="w-4 h-4" />
              ) : (
                <SendIcon className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Help text - single line */}
          <p className="text-[10px] font-mono text-slate-500 mt-1.5">
            {hasDataSource
              ? 'Describe what you want to ship in natural language'
              : 'Connect a data source from the sidebar'} · Press <kbd className="px-1 py-0.5 rounded bg-slate-800 border border-slate-700">Enter</kbd> to send
          </p>
        </div>
      </div>

      {/* Label preview modal - shown on batch completion */}
      {executingJobId && (
        <LabelPreview
          pdfUrl={getMergedLabelsUrl(executingJobId)}
          title="Batch Labels"
          isOpen={showLabelPreview}
          onClose={() => setShowLabelPreview(false)}
        />
      )}
    </div>
  );
}

export default CommandCenter;
