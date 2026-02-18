/**
 * Preview card components for batch and interactive shipment previews.
 *
 * Includes shipment row details, expandable lists, refinement input,
 * and warning gate for rows with rate validation issues.
 */

import * as React from 'react';
import { cn, formatCurrency } from '@/lib/utils';
import type { BatchPreview, PreviewRow, OrderData, ChargeBreakdown } from '@/types/api';
import type { WarningPreference } from '@/hooks/useAppState';
import {
  ChevronDownIcon, CheckIcon, XIcon, EditIcon,
  ShoppingCartIcon, UserIcon, MapPinIcon, PackageIcon,
} from '@/components/ui/icons';

/** Options passed from the warning gate to handleConfirm. */
export interface ConfirmOptions {
  skipWarningRows?: boolean;
  warningRowNumbers?: number[];
}

/** Expanded shipment details (customer, recipient, address, order reference). */
export function ShipmentDetails({ orderData }: { orderData: OrderData }) {
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

/** Country badge for international destinations. */
function CountryBadge({ country }: { country: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-mono font-medium uppercase">
      {country}
    </span>
  );
}

/** Inline charge breakdown for international rows. */
function ChargeBreakdownDetail({ breakdown }: { breakdown: ChargeBreakdown }) {
  const transport = breakdown.transportationCharges;
  const duties = breakdown.dutiesAndTaxes;
  const brokerage = breakdown.brokerageCharges;

  return (
    <div className="px-3 pb-2 ml-6 space-y-0.5">
      {transport && (
        <div className="flex justify-between text-[10px] font-mono text-slate-400">
          <span>Transport</span>
          <span>${transport.monetaryValue}</span>
        </div>
      )}
      {duties && (
        <div className="flex justify-between text-[10px] font-mono text-amber-400/80">
          <span>Duties & Taxes</span>
          <span>${duties.monetaryValue}</span>
        </div>
      )}
      {brokerage && (
        <div className="flex justify-between text-[10px] font-mono text-slate-400">
          <span>Brokerage</span>
          <span>${brokerage.monetaryValue}</span>
        </div>
      )}
    </div>
  );
}

/** Collapsible filter explanation bar for batch preview transparency. */
function FilterExplanationBar({
  explanation,
  compiledFilter,
  filterAudit,
}: {
  explanation: string;
  compiledFilter?: string;
  filterAudit?: { spec_hash: string; compiled_hash: string; schema_signature: string; dict_version: string };
}) {
  const [showCompiled, setShowCompiled] = React.useState(false);

  return (
    <div
      className="rounded-lg bg-slate-800/40 border border-slate-700/50 px-3 py-2 space-y-1.5"
      data-spec-hash={filterAudit?.spec_hash}
      data-compiled-hash={filterAudit?.compiled_hash}
      data-schema-signature={filterAudit?.schema_signature}
      data-dict-version={filterAudit?.dict_version}
    >
      <p className="text-sm text-slate-300">{explanation}</p>
      {compiledFilter && (
        <>
          <button
            onClick={() => setShowCompiled(!showCompiled)}
            className="flex items-center gap-1 text-[10px] font-mono text-slate-500 hover:text-slate-300 transition-colors"
          >
            <ChevronDownIcon className={cn('w-3 h-3 transition-transform', showCompiled && 'rotate-180')} />
            <span>View compiled filter</span>
          </button>
          {showCompiled && (
            <pre className="mt-1 bg-slate-900/80 border border-slate-700/50 rounded px-2.5 py-2 text-[10px] font-mono text-slate-400 overflow-x-auto max-h-32 overflow-y-auto">
              {compiledFilter}
            </pre>
          )}
        </>
      )}
    </div>
  );
}

/** Single collapsible shipment row with warnings. */
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
          'w-full flex items-center justify-between px-3 py-2 text-xs transition-colors',
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
                  {row.destination_country && row.destination_country !== 'US' && (
                    <CountryBadge country={row.destination_country} />
                  )}
                </div>
                <span className="text-slate-500 text-[10px]">{row.city_state}</span>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <span className="text-slate-200 font-medium truncate">{recipientName}</span>
                  {row.destination_country && row.destination_country !== 'US' && (
                    <CountryBadge country={row.destination_country} />
                  )}
                </div>
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

      {/* International charge breakdown */}
      {row.charge_breakdown && (
        <ChargeBreakdownDetail breakdown={row.charge_breakdown} />
      )}

      {/* Expanded details */}
      {isExpanded && row.order_data && (
        <ShipmentDetails orderData={row.order_data} />
      )}
    </div>
  );
}

const COLLAPSED_ROW_COUNT = 4;

/** List of shipment rows with expand/collapse for larger batches. */
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
        isListExpanded ? 'max-h-[52vh]' : 'max-h-[15rem]'
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

/** Batch shipment preview card with refinement input + warning gate. */
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
  const sortedPreviewRows = React.useMemo(
    () => [...(preview.preview_rows || [])].sort((a, b) => a.row_number - b.row_number),
    [preview.preview_rows]
  );

  const warningRows = sortedPreviewRows.filter(
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
      'card-premium p-4 space-y-4 animate-scale-in border-gradient transition-opacity max-h-[72vh] overflow-y-auto scrollable',
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
      <div className={cn('grid gap-3', preview.international_row_count ? 'grid-cols-4' : 'grid-cols-3')}>
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
        {preview.international_row_count != null && preview.international_row_count > 0 && (
          <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-center">
            <p className="text-2xl font-semibold text-blue-400">{preview.international_row_count}</p>
            <p className="text-[10px] font-mono text-blue-400/70 uppercase tracking-wider">International</p>
          </div>
        )}
        <div className="p-3 rounded-lg bg-slate-800/50 text-center">
          <p className="text-2xl font-semibold text-slate-100">{preview.rows_with_warnings}</p>
          <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Warnings</p>
        </div>
      </div>

      {/* Filter explanation (batch mode transparency) */}
      {preview.filter_explanation && (
        <FilterExplanationBar
          explanation={preview.filter_explanation}
          compiledFilter={preview.compiled_filter}
          filterAudit={preview.filter_audit}
        />
      )}

      {preview.additional_rows > 0 && (
        <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700/50">
          <p className="text-[11px] font-mono text-slate-400">
            Rated {sortedPreviewRows.length} row(s) directly. Remaining {preview.additional_rows} row(s) are estimated.
          </p>
        </div>
      )}

      {/* Shipment rows */}
      {sortedPreviewRows.length > 0 && (
        <ShipmentList
          rows={sortedPreviewRows}
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
              if (hasWarnings && warningPreference === 'ask') {
                setShowWarningGate(true);
              } else {
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

/** Interactive preview card for single ad-hoc shipments. */
export function InteractivePreviewCard({
  preview,
  onConfirm,
  onCancel,
  onRefine,
  isConfirming,
  isRefining,
  isProcessing,
}: {
  preview: BatchPreview;
  onConfirm: (opts?: ConfirmOptions) => void;
  onCancel: () => void;
  onRefine: (text: string) => void;
  isConfirming: boolean;
  isRefining: boolean;
  isProcessing: boolean;
}) {
  const [showPayload, setShowPayload] = React.useState(false);
  const [refinementInput, setRefinementInput] = React.useState('');
  const { shipper, ship_to: shipTo } = preview;
  const hasWarnings = preview.preview_rows?.some(r => r.warnings?.length > 0);
  const availableServices = preview.available_services || [];
  const refinementDisabled = isRefining || isConfirming || isProcessing;

  const submitRefinement = () => {
    const text = refinementInput.trim();
    if (!text || refinementDisabled) return;
    onRefine(text);
    setRefinementInput('');
  };

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

        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <UserIcon className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Ship To</span>
          </div>
          {shipTo ? (
            <div className="space-y-0.5 text-sm text-slate-200">
              <div className="flex items-center gap-1.5">
                <p className="font-medium">{shipTo.name}</p>
                {shipTo.country && shipTo.country !== 'US' && (
                  <CountryBadge country={shipTo.country} />
                )}
              </div>
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

      {/* Available services from UPS Shop */}
      {availableServices.length > 0 && (
        <div className="mb-4 rounded-lg border border-slate-700/60 bg-slate-900/40 p-3">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
            Available Services
          </p>
          <div className="space-y-1.5 max-h-36 overflow-y-auto scrollable pr-1">
            {availableServices.map((svc) => {
              const isSelected = svc.code === preview.service_code || !!svc.selected;
              const label = `${svc.name} (${svc.code})`;
              return (
                <button
                  key={svc.code}
                  type="button"
                  onClick={() => {
                    if (isSelected || refinementDisabled) return;
                    onRefine(`Change service to ${svc.code} (${svc.name})`);
                  }}
                  disabled={refinementDisabled}
                  className={cn(
                    'w-full rounded-md border px-2.5 py-2 text-left transition-colors',
                    isSelected
                      ? 'border-primary/40 bg-primary/10'
                      : 'border-slate-700/70 bg-slate-800/40 hover:border-primary/30 hover:bg-slate-800/70',
                    refinementDisabled && 'opacity-60 cursor-not-allowed'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-slate-200">{label}</span>
                    <span className={cn('text-xs font-mono', isSelected ? 'text-primary' : 'text-slate-300')}>
                      {formatCurrency(svc.estimated_cost_cents)}
                    </span>
                  </div>
                  {svc.delivery_days && (
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      Est. transit: {svc.delivery_days} day{svc.delivery_days === '1' ? '' : 's'}
                    </p>
                  )}
                </button>
              );
            })}
          </div>
          {preview.service_selection_notice && (
            <p className="mt-2 text-[10px] text-slate-400">{preview.service_selection_notice}</p>
          )}
        </div>
      )}

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

      {/* Refinement input */}
      <div className="mb-4">
        <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
          Refine Shipment
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={refinementInput}
            onChange={(e) => setRefinementInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitRefinement();
              }
            }}
            placeholder='e.g. "make it 3 lbs"'
            disabled={refinementDisabled}
            className="flex-1 px-3 py-2 text-xs bg-slate-800/70 border border-slate-700 rounded-md text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/25 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={submitRefinement}
            disabled={!refinementInput.trim() || refinementDisabled}
            className="px-3 py-2 text-xs btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRefining ? 'Applying...' : 'Apply'}
          </button>
        </div>
      </div>

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
          disabled={isConfirming || isProcessing || isRefining}
          className="btn-secondary flex-1 h-9 text-sm"
        >
          Cancel
        </button>
        <button
          onClick={() => onConfirm()}
          disabled={isConfirming || isProcessing || isRefining}
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
