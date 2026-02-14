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
import { useAppState, type ConversationMessage, type WarningPreference } from '@/hooks/useAppState';
import { useJobProgress } from '@/hooks/useJobProgress';
import { cn } from '@/lib/utils';
import { getMergedLabelsUrl } from '@/lib/api';
import type { ConversationEvent } from '@/hooks/useConversation';
import type { BatchPreview, PreviewRow, OrderData } from '@/types/api';
import { Package } from 'lucide-react';

// Icons
export function SendIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M22 2L11 13" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M22 2L15 22L11 13L2 9L22 2Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function StopIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <rect x="6" y="6" width="12" height="12" rx="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CheckIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function XIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <line x1="18" y1="6" x2="6" y2="18" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="6" y1="6" x2="18" y2="18" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="7 10 12 15 17 10" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="15" x2="12" y2="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PackageIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M16.5 9.4l-9-5.19" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="22.08" x2="12" y2="12" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <polyline points="6 9 12 15 18 9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function EditIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function GearIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function MapPinIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

export function UserIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

// Format currency from cents
export function formatCurrency(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

// Format relative time
export function formatRelativeTime(date: Date): string {
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);

  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'Just now';
}

// Message components
export function SystemMessage({ message }: { message: ConversationMessage }) {
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

export function UserMessage({ message }: { message: ConversationMessage }) {
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

export function TypingIndicator() {
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
export function ShoppingCartIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <circle cx="9" cy="21" r="1" />
      <circle cx="20" cy="21" r="1" />
      <path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Settings popover for warning row preference
export function SettingsPopover() {
  const { warningPreference, setWarningPreference } = useAppState();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  // Close on outside click
  React.useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const options: { value: WarningPreference; label: string; desc: string }[] = [
    { value: 'ask', label: 'Ask me each time', desc: 'Show options when rows have warnings' },
    { value: 'ship-all', label: 'Always try all rows', desc: 'Ship everything, failures handled per-row' },
    { value: 'skip-warnings', label: 'Skip warning rows', desc: 'Auto-exclude rows that failed rate validation' },
  ];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-1.5 rounded hover:bg-slate-800 transition-colors"
        title="Shipment settings"
      >
        <GearIcon className="w-4 h-4 text-slate-400" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-72 card-premium p-2 z-50 shadow-xl">
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider px-2 py-1">
            Warning Rows
          </p>
          {options.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setWarningPreference(opt.value); setOpen(false); }}
              className={cn(
                'w-full text-left px-3 py-2 rounded text-xs transition-colors',
                warningPreference === opt.value
                  ? 'bg-primary/10 text-primary'
                  : 'text-slate-300 hover:bg-slate-800'
              )}
            >
              <span className="font-medium">{opt.label}</span>
              <p className="text-[10px] text-slate-500 mt-0.5">{opt.desc}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Expanded shipment details component
export function ShipmentDetails({ orderData }: { orderData: OrderData }) {
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
              <span className="ml-1 px-1.5 py-0.5 rounded bg-primary/20 text-primary text-[8px] font-medium">
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
export function ShipmentRow({
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
                  <span className="px-1 py-0.5 rounded bg-primary/20 text-primary text-[8px] font-medium">
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
          {row.warnings?.length > 0 ? (
            <span className="font-mono text-amber-400 font-medium">$0.00</span>
          ) : (
            <span className="font-mono text-primary font-medium">{formatCurrency(row.estimated_cost_cents)}</span>
          )}
        </div>
      </button>

      {/* Rate error / warning */}
      {row.warnings?.length > 0 && (
        <div className="px-3 pb-2 ml-6">
          {row.warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-[10px] text-amber-400/90 bg-amber-400/5 rounded px-2 py-1.5">
              <span className="flex-shrink-0 mt-px">&#9888;</span>
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Expanded details */}
      {isExpanded && row.order_data && (
        <ShipmentDetails orderData={row.order_data} />
      )}
    </div>
  );
}

// Number of rows visible before expanding
const COLLAPSED_ROW_COUNT = 6;

// Shipment list with expand/collapse for viewing all rows
export function ShipmentList({
  rows,
  expandedRows,
  onToggleRow,
}: {
  rows: PreviewRow[];
  expandedRows: Set<number>;
  onToggleRow: (rowNumber: number) => void;
}) {
  const [isListExpanded, setIsListExpanded] = React.useState(false);
  const visibleRows = isListExpanded ? rows : rows.slice(0, COLLAPSED_ROW_COUNT);
  const canExpand = rows.length > COLLAPSED_ROW_COUNT;

  return (
    <div className="space-y-0">
      <div className={cn(
        'overflow-y-auto rounded-md border border-slate-800 scrollable',
        isListExpanded ? 'max-h-[60vh]' : 'max-h-none'
      )}>
        {visibleRows.map((row) => (
          <ShipmentRow
            key={row.row_number}
            row={row}
            isExpanded={expandedRows.has(row.row_number)}
            onToggle={() => onToggleRow(row.row_number)}
          />
        ))}
      </div>
      {canExpand && (
        <button
          onClick={() => setIsListExpanded(!isListExpanded)}
          className="w-full py-2 text-[11px] font-medium text-slate-400 hover:text-primary transition-colors flex items-center justify-center gap-1.5"
        >
          <ChevronDownIcon className={cn(
            'w-3.5 h-3.5 transition-transform',
            isListExpanded && 'rotate-180'
          )} />
          <span>
            {isListExpanded
              ? 'Show less'
              : `Show all ${rows.length} shipments`}
          </span>
        </button>
      )}
    </div>
  );
}

/** Options passed from the warning gate to handleConfirm. */
export interface ConfirmOptions {
  skipWarningRows?: boolean;
  warningRowNumbers?: number[];
}

// Preview card component
export function PreviewCard({
  preview,
  onConfirm,
  onCancel,
  isConfirming,
  onRefine,
  isRefining,
  isProcessing,
  warningPreference,
}: {
  preview: BatchPreview;
  onConfirm: (opts?: ConfirmOptions) => void;
  onCancel: () => void;
  isConfirming: boolean;
  onRefine: (text: string) => void;
  isRefining: boolean;
  isProcessing: boolean;
  warningPreference: WarningPreference;
}) {
  const [expandedRows, setExpandedRows] = React.useState<Set<number>>(new Set());
  const [showRefinement, setShowRefinement] = React.useState(false);
  const [refinementInput, setRefinementInput] = React.useState('');
  const [showWarningGate, setShowWarningGate] = React.useState(false);
  const refinementInputRef = React.useRef<HTMLInputElement>(null);

  const warningRows = preview.preview_rows.filter(
    (r) => r.warnings && r.warnings.length > 0
  );
  const hasWarnings = warningRows.length > 0;

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

  // Auto-focus the refinement input when it becomes visible
  React.useEffect(() => {
    if (showRefinement && refinementInputRef.current) {
      refinementInputRef.current.focus();
    }
  }, [showRefinement]);

  const handleRefinementSubmit = () => {
    if (!refinementInput.trim() || isRefining) return;
    onRefine(refinementInput.trim());
    setRefinementInput('');
    setShowRefinement(false);
  };

  const handleRefinementKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleRefinementSubmit();
    } else if (e.key === 'Escape') {
      setShowRefinement(false);
      setRefinementInput('');
    }
  };

  return (
    <div className={cn(
      'card-premium p-4 space-y-4 animate-scale-in border-gradient transition-opacity',
      isRefining && 'opacity-70'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">Shipment Preview</h3>
        {isRefining ? (
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border border-primary/30 bg-primary/10 text-[10px] font-mono text-primary">
            <span className="w-2.5 h-2.5 border border-primary/40 border-t-primary rounded-full animate-spin" />
            Refining...
          </span>
        ) : (
          <span className="badge badge-info">Ready</span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.total_rows}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Total Shipments</p>
        </div>
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-primary">
            {formatCurrency(preview.total_estimated_cost_cents)}
          </p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Est. Cost</p>
        </div>
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.rows_with_warnings}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Warnings</p>
        </div>
      </div>

      {preview.additional_rows > 0 && (
        <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700/50">
          <p className="text-[11px] font-mono text-slate-400">
            Rated {preview.preview_rows.length} row(s) directly. Remaining {preview.additional_rows} row(s) are estimated.
          </p>
        </div>
      )}

      {/* Shipment rows */}
      {preview.preview_rows.length > 0 && (
        <ShipmentList
          rows={preview.preview_rows}
          expandedRows={expandedRows}
          onToggleRow={toggleRow}
        />
      )}

      {/* Refinement section */}
      <div className="space-y-2">
        {!showRefinement ? (
          <button
            onClick={() => setShowRefinement(true)}
            disabled={isRefining || isConfirming || isProcessing}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <EditIcon className="w-3.5 h-3.5" />
            <span>Refine this shipment</span>
          </button>
        ) : (
          <div className="flex gap-2">
            <input
              ref={refinementInputRef}
              type="text"
              value={refinementInput}
              onChange={(e) => setRefinementInput(e.target.value)}
              onKeyDown={handleRefinementKeyDown}
              placeholder='e.g. "change to 2nd Day Air"'
              disabled={isRefining || isProcessing}
              className="flex-1 px-3 py-2 text-xs bg-slate-800/70 border border-slate-700 rounded-md text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/25 disabled:opacity-50"
            />
            <button
              onClick={handleRefinementSubmit}
              disabled={!refinementInput.trim() || isRefining || isProcessing}
              className="px-3 py-2 text-xs btn-primary flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRefining ? (
                <span className="w-3.5 h-3.5 border-2 border-void-950/30 border-t-void-950 rounded-full animate-spin" />
              ) : (
                <span>Apply</span>
              )}
            </button>
            <button
              onClick={() => { setShowRefinement(false); setRefinementInput(''); }}
              disabled={isRefining || isProcessing}
              className="px-2 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
            >
              <XIcon className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Actions — warning gate or standard buttons */}
      {showWarningGate ? (
        <div className="space-y-3 pt-2">
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <p className="text-xs font-medium text-amber-400 mb-2">
              {warningRows.length} row{warningRows.length !== 1 ? 's have' : ' has'} warnings:
            </p>
            <div className="space-y-1 max-h-[80px] overflow-y-auto scrollable">
              {warningRows.map((r) => (
                <div key={r.row_number} className="text-[10px] font-mono text-amber-400/80">
                  Row {r.row_number}: {r.warnings?.[0]}
                </div>
              ))}
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => setShowWarningGate(false)}
              className="flex-1 btn-secondary py-2.5 text-sm"
            >
              Back
            </button>
            <button
              onClick={() => onConfirm({
                skipWarningRows: true,
                warningRowNumbers: warningRows.map((r) => r.row_number),
              })}
              disabled={isConfirming}
              className="flex-1 btn-secondary py-2.5 text-sm border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            >
              Skip {warningRows.length} Row{warningRows.length !== 1 ? 's' : ''}
            </button>
            <button
              onClick={() => onConfirm({ skipWarningRows: false })}
              disabled={isConfirming}
              className="flex-1 btn-primary py-2.5 text-sm"
            >
              Ship All
            </button>
          </div>
          <p className="text-[10px] text-slate-500 text-center">
            Set a default in the <span className="text-primary">settings gear</span> above
          </p>
        </div>
      ) : (
        <div className="flex gap-3 pt-2">
          <button
            onClick={onCancel}
            disabled={isConfirming || isRefining}
            className="flex-1 btn-secondary py-2.5 flex items-center justify-center gap-2"
          >
            <XIcon className="w-4 h-4" />
            <span>Cancel</span>
          </button>
          <button
            onClick={() => {
              // If warnings exist and preference is 'ask', show warning gate
              if (hasWarnings && warningPreference === 'ask') {
                setShowWarningGate(true);
              } else {
                // 'ship-all' or 'skip-warnings' or no warnings — pass through
                onConfirm();
              }
            }}
            disabled={isConfirming || isRefining}
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
      )}
    </div>
  );
}

// Interactive preview card for single ad-hoc shipments
export function InteractivePreviewCard({
  preview,
  onConfirm,
  onCancel,
  isConfirming,
  isProcessing,
}: {
  preview: BatchPreview;
  onConfirm: (opts?: ConfirmOptions) => void;
  onCancel: () => void;
  isConfirming: boolean;
  isProcessing: boolean;
}) {
  const [showPayload, setShowPayload] = React.useState(false);
  const { shipper, ship_to: shipTo } = preview;
  const hasWarnings = preview.preview_rows?.some(r => r.warnings?.length > 0);

  return (
    <div className="card-premium p-5 animate-scale-in max-w-lg">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <PackageIcon className="w-5 h-5 text-blue-400" />
          <h3 className="text-base font-semibold text-white">Shipment Preview</h3>
        </div>
        <span className="badge-info text-xs px-2 py-0.5">Ready</span>
      </div>

      {/* Ship From / Ship To */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {/* Ship From */}
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <MapPinIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Ship From</span>
          </div>
          {shipper ? (
            <div className="space-y-0.5 text-sm text-slate-200">
              <p className="font-medium">{shipper.name}</p>
              <p className="text-slate-300">{shipper.addressLine1}</p>
              {shipper.addressLine2 && <p className="text-slate-300">{shipper.addressLine2}</p>}
              <p className="text-slate-300">
                {shipper.city}, {shipper.stateProvinceCode} {shipper.postalCode}
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-400">From config</p>
          )}
        </div>

        {/* Ship To */}
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <UserIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Ship To</span>
          </div>
          {shipTo ? (
            <div className="space-y-0.5 text-sm text-slate-200">
              <p className="font-medium">{shipTo.name}</p>
              <p className="text-slate-300">{shipTo.address1}</p>
              {shipTo.address2 && <p className="text-slate-300">{shipTo.address2}</p>}
              <p className="text-slate-300">
                {shipTo.city}, {shipTo.state} {shipTo.postal_code}
              </p>
              {shipTo.phone && (
                <p className="text-slate-400 text-xs mt-1">{shipTo.phone}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-400">--</p>
          )}
        </div>
      </div>

      {/* Service / Weight / Account */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Service</p>
          <p className="text-sm font-semibold text-white">{preview.service_name || 'UPS Ground'}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Weight</p>
          <p className="text-sm font-semibold text-white">{preview.weight_lbs ?? 1.0} lbs</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Account</p>
          <p className="text-sm font-semibold text-white font-mono">{preview.account_number || '****'}</p>
        </div>
      </div>

      {/* Estimated Cost */}
      <div className="bg-gradient-to-r from-emerald-500/10 to-emerald-500/5 border border-emerald-500/20 rounded-lg p-3 mb-4 text-center">
        <p className="text-[10px] font-medium text-emerald-400 uppercase tracking-wider mb-1">Estimated Cost</p>
        <p className="text-2xl font-bold text-emerald-400">
          {formatCurrency(preview.total_estimated_cost_cents)}
        </p>
      </div>

      {/* Warning (if rate failed) */}
      {hasWarnings && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 mb-4">
          <p className="text-sm text-amber-300 font-medium mb-1">Rating Warning</p>
          {preview.preview_rows?.map((r, i) =>
            r.warnings?.map((w, j) => (
              <p key={`${i}-${j}`} className="text-xs text-amber-200/80">{w}</p>
            ))
          )}
        </div>
      )}

      {/* Expandable Full Payload */}
      {preview.resolved_payload && (
        <div className="mb-4">
          <button
            onClick={() => setShowPayload(!showPayload)}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ChevronDownIcon className={cn('w-3.5 h-3.5 transition-transform', showPayload && 'rotate-180')} />
            <span>Full Payload</span>
          </button>
          {showPayload && (
            <pre className="mt-2 bg-slate-900/80 border border-slate-700/50 rounded-lg p-3 text-xs text-slate-300 overflow-x-auto max-h-64 overflow-y-auto font-mono">
              {JSON.stringify(preview.resolved_payload, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onCancel}
          disabled={isConfirming || isProcessing}
          className="btn-secondary flex-1 h-9 text-sm"
        >
          Cancel
        </button>
        <button
          onClick={() => onConfirm()}
          disabled={isConfirming || isProcessing}
          className="btn-primary flex-1 h-9 text-sm flex items-center justify-center gap-2"
        >
          {isConfirming ? (
            <>
              <span className="animate-spin h-3.5 w-3.5 border-2 border-white/20 border-t-white rounded-full" />
              <span>Confirming...</span>
            </>
          ) : (
            <>
              <CheckIcon className="w-3.5 h-3.5" />
              <span>Confirm & Ship</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// Per-row failure detail for callbacks
interface RowFailureInfo {
  rowNumber: number;
  errorCode: string;
  errorMessage: string;
}

// Progress data passed to completion callbacks
interface ProgressData {
  total: number;
  successful: number;
  failed: number;
  totalCostCents: number;
  rowFailures: RowFailureInfo[];
}

// Progress display component
export function ProgressDisplay({ jobId, onComplete, onFailed }: {
  jobId: string;
  onComplete?: (data: ProgressData) => void;
  onFailed?: (data: ProgressData) => void;
}) {
  const { progress } = useJobProgress(jobId);
  const completeFiredRef = React.useRef(false);
  const failFiredRef = React.useRef(false);

  const percentage = progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;
  const isRunning = progress.status === 'running';
  const isComplete = progress.status === 'completed';
  const isFailed = progress.status === 'failed';

  // Fire onComplete callback once when status transitions to completed
  React.useEffect(() => {
    if (isComplete && !completeFiredRef.current && onComplete) {
      completeFiredRef.current = true;
      onComplete({
        total: progress.total,
        successful: progress.successful,
        failed: progress.failed,
        totalCostCents: progress.totalCostCents,
        rowFailures: progress.rowFailures,
      });
    }
  }, [isComplete, onComplete, progress]);

  // Fire onFailed callback once when status transitions to failed
  React.useEffect(() => {
    if (isFailed && !failFiredRef.current && onFailed) {
      failFiredRef.current = true;
      onFailed({
        total: progress.total,
        successful: progress.successful,
        failed: progress.failed,
        totalCostCents: progress.totalCostCents,
        rowFailures: progress.rowFailures,
      });
    }
  }, [isFailed, onFailed, progress]);

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
          <p className="text-lg font-semibold text-primary">
            {formatCurrency(progress.totalCostCents)}
          </p>
          <p className="text-[10px] font-mono text-slate-500">Cost</p>
        </div>
      </div>

      {/* Per-row failure details */}
      {(progress.rowFailures?.length ?? 0) > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-error/90">
            {progress.rowFailures.length} row{progress.rowFailures.length !== 1 ? 's' : ''} failed:
          </p>
          <div className="max-h-[120px] overflow-y-auto scrollable space-y-1">
            {progress.rowFailures.map((f) => (
              <div key={f.rowNumber} className="p-2 rounded bg-error/10 border border-error/20 flex items-start gap-2">
                <span className="text-[10px] font-mono text-error/70 flex-shrink-0 mt-px">
                  Row {f.rowNumber}
                </span>
                <span className="text-[10px] font-mono text-error/90 break-all">
                  {f.errorMessage}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Batch-level error (when no per-row details available) */}
      {isFailed && progress.error && (progress.rowFailures?.length ?? 0) === 0 && (
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

// Completion artifact - compact inline card for completed batches
/**
 * Parse a job name that may contain → delimiters into base command and refinements.
 * Returns { base, refinements } where refinements is capped at MAX_VISIBLE_REFINEMENTS.
 * If more refinements exist, the last visible entry is replaced with "+N more".
 */
const MAX_VISIBLE_REFINEMENTS = 3;

export function parseRefinedName(name: string | undefined): { base: string; refinements: string[]; overflow: number } {
  if (!name || !name.includes(' → ')) return { base: name || '', refinements: [], overflow: 0 };
  const parts = name.split(' → ');
  const base = parts[0];
  const allRefinements = parts.slice(1);
  const overflow = Math.max(0, allRefinements.length - MAX_VISIBLE_REFINEMENTS);
  const refinements = allRefinements.slice(0, MAX_VISIBLE_REFINEMENTS);
  return { base, refinements, overflow };
}

export function CompletionArtifact({ message, onViewLabels }: {
  message: ConversationMessage;
  onViewLabels: (jobId: string) => void;
}) {
  const meta = message.metadata?.completion;
  const jobId = message.metadata?.jobId;
  if (!meta || !jobId) return null;

  const allFailed = meta.successful === 0 && meta.failed > 0;
  const hasFailures = meta.failed > 0;
  const borderColor = allFailed ? 'border-l-error' : hasFailures ? 'border-l-warning' : 'border-l-success';
  const badgeClass = allFailed ? 'badge-error' : hasFailures ? 'badge-warning' : 'badge-success';
  const badgeText = allFailed ? 'FAILED' : hasFailures ? 'PARTIAL' : 'COMPLETED';

  // Use job name (→ format) when available, fall back to raw command
  const displayName = meta.jobName || `Command: ${meta.command}`;
  const { base, refinements, overflow } = parseRefinedName(displayName);
  const baseDisplay = base.startsWith('Command: ') ? base.slice(9) : base;

  return (
    <div className={cn(
      'card-premium p-4 space-y-3 border-l-4',
      borderColor
    )}>
      <div className="flex justify-end">
        <span className={cn('badge', badgeClass)}>{badgeText}</span>
      </div>

      <div className="space-y-1">
        <p className="text-xs text-slate-400 italic truncate">&ldquo;{baseDisplay}&rdquo;</p>
        {refinements.map((ref, i) => (
          <p key={i} className="text-[11px] text-primary/80 truncate">
            &rarr; {ref}
          </p>
        ))}
        {overflow > 0 && (
          <p className="text-[10px] text-slate-500 italic">
            +{overflow} more refinement{overflow !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 text-xs font-mono text-slate-400">
        <span>{meta.successful} shipment{meta.successful !== 1 ? 's' : ''}</span>
        <span className="text-slate-600">&middot;</span>
        <span className="text-primary">{formatCurrency(meta.totalCostCents)}</span>
        {meta.failed > 0 && (
          <>
            <span className="text-slate-600">&middot;</span>
            <span className="text-error">{meta.failed} failed</span>
          </>
        )}
      </div>

      {/* Per-row failure details */}
      {meta.rowFailures && meta.rowFailures.length > 0 && (
        <div className="space-y-1 max-h-[100px] overflow-y-auto scrollable">
          {meta.rowFailures.map((f) => (
            <div key={f.rowNumber} className="flex items-start gap-2 px-2 py-1.5 rounded bg-error/10 border border-error/20">
              <span className="text-[10px] font-mono text-error/70 flex-shrink-0 mt-px">
                Row {f.rowNumber}
              </span>
              <span className="text-[10px] font-mono text-error/90 break-all">
                {f.errorMessage}
              </span>
            </div>
          ))}
        </div>
      )}

      {!allFailed && (
        <button
          onClick={() => onViewLabels(jobId)}
          className="w-full btn-primary py-2 flex items-center justify-center gap-2 text-sm"
        >
          <DownloadIcon className="w-3.5 h-3.5" />
          <span>View Labels (PDF)</span>
        </button>
      )}
    </div>
  );
}

// Icons for the active source banner
export function BannerShopifyIcon({ className }: { className?: string }) {
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

export function BannerHardDriveIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className={className}>
      <path d="M22 12H2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="6" y1="16" x2="6.01" y2="16" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="10" y1="16" x2="10.01" y2="16" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Collapsible chip showing an agent tool call. */
export function ToolCallChip({ event }: { event: ConversationEvent }) {
  const toolName = (event.data.tool_name as string) || 'tool';
  // Humanize tool names: "mcp__orchestrator__batch_preview_tool" → "Batch Preview"
  const label = toolName
    .replace(/^mcp__\w+__/, '')
    .replace(/_tool$/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/10 to-cyan-600/10 border border-cyan-500/20 flex items-center justify-center">
        <GearIcon className="w-3.5 h-3.5 text-cyan-400/60" />
      </div>
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/50 border border-slate-700/50">
        <span className="w-2 h-2 rounded-full bg-cyan-400/50 animate-pulse" />
        <span className="text-[11px] font-mono text-slate-400">{label}</span>
      </div>
    </div>
  );
}

/** Compact banner showing the currently active data source at the top of the chat area. */
export function ActiveSourceBanner() {
  const { activeSourceInfo } = useAppState();

  // Always show the banner for the settings gear, even without a data source
  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border/50 bg-card/30">
      {activeSourceInfo && (
        <>
          <span className="w-1.5 h-1.5 rounded-full bg-success flex-shrink-0" />
          {activeSourceInfo.sourceKind === 'shopify' ? (
            <BannerShopifyIcon className="w-3.5 h-3.5 text-[#5BBF3D]" />
          ) : (
            <BannerHardDriveIcon className="w-3.5 h-3.5 text-slate-400" />
          )}
          <span className="text-xs font-medium text-slate-300">
            {activeSourceInfo.label}
          </span>
          <span className="text-slate-600">&middot;</span>
          <span className="text-[10px] font-mono text-slate-500">
            {activeSourceInfo.detail}
          </span>
        </>
      )}
      <div className="ml-auto">
        <SettingsPopover />
      </div>
    </div>
  );
}

/** Compact banner shown when interactive shipping mode is active. */
export function InteractiveModeBanner() {
  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-amber-500/20 bg-amber-500/5">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
      <span className="text-xs font-medium text-amber-200">Interactive Shipping (Ad-hoc)</span>
      <span className="text-amber-700">&middot;</span>
      <span className="text-[10px] font-mono text-amber-300/90">Batch commands disabled</span>
    </div>
  );
}

// Welcome message with workflow steps
export function WelcomeMessage({
  onExampleClick,
  interactiveShipping = false,
}: {
  onExampleClick?: (text: string) => void;
  interactiveShipping?: boolean;
}) {
  const { activeSourceInfo } = useAppState();
  const isConnected = !!activeSourceInfo;

  const batchExamples = [
    { text: 'Ship all California orders using UPS Ground', desc: 'Filter by state' },
    { text: "Ship today's pending orders with 2nd Day Air", desc: 'Filter by status & date' },
    { text: 'Create shipments for orders over $100', desc: 'Filter by amount' },
  ];

  const interactiveExamples = [
    { text: 'Ship a 5lb box to John Smith at 123 Main St, Springfield IL 62704 via Ground', desc: 'Single ad-hoc shipment' },
    { text: 'Create a Next Day Air shipment to 456 Oak Ave, Austin TX 78701', desc: 'Express shipment' },
  ];

  const examples = interactiveShipping ? interactiveExamples : batchExamples;

  if (interactiveShipping) {
    return (
      <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <Package className="h-6 w-6 text-primary-foreground" />
        </div>

        <h2 className="text-xl font-semibold text-foreground mb-2">
          Interactive Shipping
        </h2>

        <p className="text-sm text-slate-400 max-w-md mb-6">
          Create one shipment from scratch in natural language.
          <br />
          ShipAgent will ask for any missing required details.
        </p>

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

  // Not connected - show getting started workflow
  if (!isConnected) {
    return (
      <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
          <Package className="h-6 w-6 text-primary-foreground" />
        </div>

        <h2 className="text-xl font-semibold text-foreground mb-2">
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
                <span className="text-xs font-mono text-primary">{item.step}</span>
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
  return (
    <div className="flex flex-col items-center pt-12 text-center px-4 animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary mb-4">
        <Package className="h-6 w-6 text-primary-foreground" />
      </div>

      <h2 className="text-xl font-semibold text-foreground mb-2">
        Ready to Ship
      </h2>

      <p className="text-sm text-slate-400 max-w-md mb-2">
        Connected to <span className="text-primary font-medium">{activeSourceInfo!.label}</span>
        <> · <span className="text-slate-500">{activeSourceInfo!.detail}</span></>
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
