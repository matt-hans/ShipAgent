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
import { confirmJob, cancelJob, getJob, getMergedLabelsUrl, skipRows } from '@/lib/api';
import { useConversation, type ConversationEvent } from '@/hooks/useConversation';
import type { Job, BatchPreview, PreviewRow, OrderData } from '@/types/api';
import { Package } from 'lucide-react';
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

function EditIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function GearIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" strokeLinecap="round" strokeLinejoin="round" />
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

// Settings popover for warning row preference
function SettingsPopover() {
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
function ShipmentList({
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
interface ConfirmOptions {
  skipWarningRows?: boolean;
  warningRowNumbers?: number[];
}

// Preview card component
function PreviewCard({
  preview,
  onConfirm,
  onCancel,
  isConfirming,
  onRefine,
  isRefining,
  warningPreference,
}: {
  preview: BatchPreview;
  onConfirm: (opts?: ConfirmOptions) => void;
  onCancel: () => void;
  isConfirming: boolean;
  onRefine: (text: string) => void;
  isRefining: boolean;
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
        <span className="badge badge-info">Ready</span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.total_rows}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Total Rows</p>
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
            disabled={isRefining || isConfirming}
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
              disabled={isRefining}
              className="flex-1 px-3 py-2 text-xs bg-slate-800/70 border border-slate-700 rounded-md text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/25 disabled:opacity-50"
            />
            <button
              onClick={handleRefinementSubmit}
              disabled={!refinementInput.trim() || isRefining}
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
              disabled={isRefining}
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
function ProgressDisplay({ jobId, onComplete, onFailed }: {
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

function parseRefinedName(name: string | undefined): { base: string; refinements: string[]; overflow: number } {
  if (!name || !name.includes(' → ')) return { base: name || '', refinements: [], overflow: 0 };
  const parts = name.split(' → ');
  const base = parts[0];
  const allRefinements = parts.slice(1);
  const overflow = Math.max(0, allRefinements.length - MAX_VISIBLE_REFINEMENTS);
  const refinements = allRefinements.slice(0, MAX_VISIBLE_REFINEMENTS);
  return { base, refinements, overflow };
}

function CompletionArtifact({ message, onViewLabels }: {
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
function BannerShopifyIcon({ className }: { className?: string }) {
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

function BannerHardDriveIcon({ className }: { className?: string }) {
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
function ToolCallChip({ event }: { event: ConversationEvent }) {
  const toolName = (event.data.tool_name as string) || 'tool';
  // Humanize tool names: "batch_preview_tool" → "Batch Preview"
  const label = toolName
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
function ActiveSourceBanner() {
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

// Welcome message with workflow steps
function WelcomeMessage({ onExampleClick }: { onExampleClick?: (text: string) => void }) {
  const { activeSourceInfo } = useAppState();
  const isConnected = !!activeSourceInfo;

  const examples = [
    { text: 'Ship all California orders using UPS Ground', desc: 'Filter by state' },
    { text: "Ship today's pending orders with 2nd Day Air", desc: 'Filter by status & date' },
    { text: 'Create shipments for orders over $100', desc: 'Filter by amount' },
  ];

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

// Main CommandCenter component
export function CommandCenter({ activeJob }: CommandCenterProps) {
  const {
    conversation,
    addMessage,
    isProcessing,
    setIsProcessing,
    setActiveJob,
    refreshJobList,
    activeSourceType,
    warningPreference,
    setConversationSessionId,
  } = useAppState();

  const hasDataSource = activeSourceType !== null;

  // Agent-driven conversation hook
  const conv = useConversation();

  const [inputValue, setInputValue] = React.useState('');
  const [preview, setPreview] = React.useState<BatchPreview | null>(null);
  const [currentJobId, setCurrentJobId] = React.useState<string | null>(null);
  const [isConfirming, setIsConfirming] = React.useState(false);
  const [executingJobId, setExecutingJobId] = React.useState<string | null>(null);
  const [showLabelPreview, setShowLabelPreview] = React.useState(false);
  const [labelPreviewJobId, setLabelPreviewJobId] = React.useState<string | null>(null);
  const [isRefining, setIsRefining] = React.useState(false);

  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const lastCommandRef = React.useRef<string>('');
  const lastJobNameRef = React.useRef<string>('');

  // Sync conversation session ID to AppState
  React.useEffect(() => {
    setConversationSessionId(conv.sessionId);
  }, [conv.sessionId, setConversationSessionId]);

  // Render agent events as conversation messages
  const lastProcessedEventRef = React.useRef(0);
  React.useEffect(() => {
    const newEvents = conv.events.slice(lastProcessedEventRef.current);
    lastProcessedEventRef.current = conv.events.length;

    for (const event of newEvents) {
      if (event.type === 'agent_message') {
        const text = (event.data.text as string) || '';
        if (text) {
          addMessage({ role: 'system', content: text });
        }
      } else if (event.type === 'preview_ready') {
        const previewData = event.data as unknown as BatchPreview;
        setPreview(previewData);
        setCurrentJobId(previewData.job_id);
        refreshJobList();
      } else if (event.type === 'error') {
        const msg = (event.data.message as string) || 'Agent error';
        addMessage({
          role: 'system',
          content: `Error: ${msg}`,
          metadata: { action: 'error' },
        });
      }
    }
  }, [conv.events, addMessage]);

  // Sync processing state from conversation hook
  React.useEffect(() => {
    setIsProcessing(conv.isProcessing);
  }, [conv.isProcessing, setIsProcessing]);

  // Auto-scroll to bottom (includes activeJob so returning from job detail scrolls down)
  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation, preview, executingJobId, activeJob, conv.events]);

  // Handle command submit — uses agent-driven conversation flow
  const handleSubmit = async () => {
    const command = inputValue.trim();
    if (!command || isProcessing || !hasDataSource) return;

    lastCommandRef.current = command;
    setInputValue('');

    // Add user message
    addMessage({ role: 'user', content: command });

    // Send via agent conversation — the hook manages SSE events,
    // which are rendered as system messages via the effect above
    await conv.sendMessage(command);
  };

  // Handle confirm with optional row skipping
  const handleConfirm = async (opts?: ConfirmOptions) => {
    if (!currentJobId) return;

    setIsConfirming(true);
    // refinement state cleared
    try {
      // Skip warning rows if explicitly requested or if preference is 'skip-warnings'
      if (opts?.skipWarningRows && opts.warningRowNumbers?.length) {
        await skipRows(currentJobId, opts.warningRowNumbers);
      }

      await confirmJob(currentJobId);
      setExecutingJobId(currentJobId);
      setPreview(null);

      addMessage({
        role: 'system',
        content: opts?.skipWarningRows
          ? `Batch confirmed. Skipped ${opts.warningRowNumbers?.length ?? 0} warning row(s). Processing remaining shipments...`
          : 'Batch confirmed. Processing shipments...',
        metadata: { jobId: currentJobId, action: 'execute' },
      });

      // Fetch job to capture its display name (includes → refinements)
      const job = await getJob(currentJobId);
      lastJobNameRef.current = job.name || '';
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

    // refinement state cleared
    try {
      await cancelJob(currentJobId);
      setPreview(null);
      setCurrentJobId(null);
      refreshJobList();

      addMessage({
        role: 'system',
        content: 'Batch cancelled. You can enter a new command.',
      });
    } catch (err) {
      console.error('Failed to cancel:', err);
    }
  };

  // Handle refinement — send as a follow-up conversation message
  const handleRefine = async (refinementText: string) => {
    if (!refinementText.trim() || isRefining) return;

    setIsRefining(true);
    try {
      // Send refinement through the agent conversation
      await conv.sendMessage(refinementText.trim());
    } catch (err) {
      addMessage({
        role: 'system',
        content: `Refinement failed: ${err instanceof Error ? err.message : 'Unknown error'}.`,
        metadata: { action: 'error' },
      });
    } finally {
      setIsRefining(false);
    }
  };

  // Handle key press
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Show job detail panel when a sidebar job is selected (takes priority over conversation)
  const showJobDetail = activeJob && !preview && !executingJobId;

  if (showJobDetail) {
    return (
      <JobDetailPanel
        job={activeJob}
        onBack={() => {
          // Clear any lingering label preview state before returning to chat
          // so the modal doesn't flash open on re-render
          setShowLabelPreview(false);
          setLabelPreviewJobId(null);
          setActiveJob(null);
        }}
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      <ActiveSourceBanner />
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto scrollable p-6">
        {conversation.length === 0 && !preview && !executingJobId ? (
          <WelcomeMessage onExampleClick={(text) => setInputValue(text)} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {conversation.map((message) => (
              message.metadata?.action === 'complete' ? (
                <div key={message.id} className="pl-11">
                  <CompletionArtifact
                    message={message}
                    onViewLabels={(jobId) => {
                      setLabelPreviewJobId(jobId);
                      setShowLabelPreview(true);
                    }}
                  />
                </div>
              ) : message.role === 'user' ? (
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
                  onConfirm={(opts) => {
                    // Apply preference-based auto-behavior for non-'ask' modes
                    if (warningPreference === 'ship-all') {
                      handleConfirm();
                    } else if (warningPreference === 'skip-warnings') {
                      const warnRows = preview.preview_rows.filter(
                        (r) => r.warnings?.length
                      );
                      if (warnRows.length > 0) {
                        handleConfirm({
                          skipWarningRows: true,
                          warningRowNumbers: warnRows.map((r) => r.row_number),
                        });
                      } else {
                        handleConfirm();
                      }
                    } else {
                      // 'ask' mode — pass through from gate
                      handleConfirm(opts);
                    }
                  }}
                  onCancel={handleCancel}
                  isConfirming={isConfirming}
                  onRefine={handleRefine}
                  isRefining={isRefining}
                  warningPreference={warningPreference}
                />
              </div>
            )}

            {/* Progress display */}
            {executingJobId && (
              <div className="pl-11">
                <ProgressDisplay
                  jobId={executingJobId}
                  onComplete={(data) => {
                    addMessage({
                      role: 'system',
                      content: '',
                      metadata: {
                        jobId: executingJobId,
                        action: 'complete' as const,
                        completion: {
                          command: lastCommandRef.current,
                          jobName: lastJobNameRef.current || undefined,
                          totalRows: data.total,
                          successful: data.successful,
                          failed: data.failed,
                          totalCostCents: data.totalCostCents,
                          rowFailures: data.rowFailures.length > 0 ? data.rowFailures : undefined,
                        },
                      },
                    });
                    setLabelPreviewJobId(executingJobId);
                    setShowLabelPreview(true);
                    setExecutingJobId(null);
                    setCurrentJobId(null);
                    setActiveJob(null);
                    refreshJobList();
                  }}
                  onFailed={(data) => {
                    addMessage({
                      role: 'system',
                      content: '',
                      metadata: {
                        jobId: executingJobId,
                        action: 'complete' as const,
                        completion: {
                          command: lastCommandRef.current,
                          jobName: lastJobNameRef.current || undefined,
                          totalRows: data.total,
                          successful: data.successful,
                          failed: data.failed,
                          totalCostCents: data.totalCostCents,
                          rowFailures: data.rowFailures.length > 0 ? data.rowFailures : undefined,
                        },
                      },
                    });
                    if (data.successful > 0) {
                      setLabelPreviewJobId(executingJobId);
                      setShowLabelPreview(true);
                    }
                    setExecutingJobId(null);
                    setCurrentJobId(null);
                    setActiveJob(null);
                    refreshJobList();
                  }}
                />
              </div>
            )}

            {/* Agent tool call chips — shown while processing */}
            {conv.isProcessing && conv.events
              .filter((e) => e.type === 'tool_call')
              .slice(-3)
              .map((e) => (
                <ToolCallChip key={e.id} event={e} />
              ))
            }

            {/* Typing indicator — shown during initial processing or refinement */}
            {isProcessing && <TypingIndicator />}
            {isRefining && (
              <div className="flex gap-3 animate-fade-in">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-primary/20 to-primary/30 border border-primary/30 flex items-center justify-center">
                  <EditIcon className="w-4 h-4 text-primary animate-pulse" />
                </div>
                <div className="message-system py-3">
                  <div className="flex items-center gap-2">
                    <span className="w-3.5 h-3.5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                    <span className="text-xs text-slate-400">Recalculating rates...</span>
                  </div>
                </div>
              </div>
            )}

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
                disabled={!hasDataSource || isProcessing || !!preview || !!executingJobId}
                className={cn(
                  'input-command pr-12',
                  (!hasDataSource || isProcessing || !!preview || !!executingJobId) && 'opacity-50 cursor-not-allowed'
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
              disabled={!inputValue.trim() || !hasDataSource || isProcessing || !!preview || !!executingJobId}
              className={cn(
                'btn-primary px-4',
                (!inputValue.trim() || !hasDataSource || isProcessing || !!preview || !!executingJobId) && 'opacity-50 cursor-not-allowed'
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

      {/* Label preview modal - shown on batch completion or artifact click */}
      {labelPreviewJobId && (
        <LabelPreview
          pdfUrl={getMergedLabelsUrl(labelPreviewJobId)}
          title="Batch Labels"
          isOpen={showLabelPreview}
          onClose={() => {
            setShowLabelPreview(false);
            setLabelPreviewJobId(null);
          }}
        />
      )}
    </div>
  );
}

export default CommandCenter;
