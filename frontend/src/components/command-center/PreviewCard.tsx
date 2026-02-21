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

/* ──────────────────── Invoice Data Extraction ──────────────────── */

interface InvoiceProduct {
  description: string;
  commodityCode?: string;
  originCountry?: string;
  quantity?: string;
  unitValue?: string;
  lineTotal?: string;
}

interface InvoiceData {
  formType: string;
  invoiceNumber?: string;
  invoiceDate?: string;
  reasonForExport?: string;
  currencyCode?: string;
  products: InvoiceProduct[];
  invoiceTotal?: string;
  invoiceTotalCurrency?: string;
  freightCharges?: string;
  insuranceCharges?: string;
  termsOfShipment?: string;
  purchaseOrderNumber?: string;
  comments?: string;
  shipperName?: string;
  recipientName?: string;
}

/**
 * Extracts international invoice data from the simplified payload format.
 *
 * The resolved_payload uses a flat camelCase structure (not the nested UPS API
 * format). InternationalForms lives at `payload.internationalForms` and
 * InvoiceLineTotal at `payload.invoiceLineTotal`.
 */
function extractInvoiceData(payload: Record<string, unknown>): InvoiceData | null {
  try {
    // Simplified format: top-level camelCase keys
    const forms = payload.internationalForms as Record<string, unknown> | undefined;
    if (!forms) return null;

    const rawProducts = forms.Product as Record<string, unknown>[] | Record<string, unknown> | undefined;
    const productList = Array.isArray(rawProducts) ? rawProducts : rawProducts ? [rawProducts] : [];

    const products: InvoiceProduct[] = productList.map((p) => {
      const unit = p.Unit as Record<string, unknown> | undefined;
      // Unit.Value is a plain string (e.g. "50.00") in the simplified format,
      // not an object with MonetaryValue. Handle both shapes defensively.
      const rawValue = unit?.Value;
      const valueStr = typeof rawValue === 'string' ? rawValue
        : typeof rawValue === 'object' && rawValue ? (rawValue as Record<string, unknown>).MonetaryValue as string
        : undefined;
      const qtyStr = (unit?.Number as string) || undefined;
      return {
        description: (p.Description as string) || '',
        commodityCode: (p.CommodityCode as string) || undefined,
        originCountry: (p.OriginCountryCode as string) || undefined,
        quantity: qtyStr,
        unitValue: valueStr || undefined,
        lineTotal: valueStr && qtyStr
          ? (parseFloat(valueStr) * parseFloat(qtyStr)).toFixed(2)
          : undefined,
      };
    });

    const invoiceLineTotal = payload.invoiceLineTotal as Record<string, unknown> | undefined;
    const shipper = payload.shipper as Record<string, unknown> | undefined;
    const shipTo = payload.shipTo as Record<string, unknown> | undefined;

    const freightRaw = forms.FreightCharges;
    const freightVal = typeof freightRaw === 'string' ? freightRaw
      : (freightRaw as Record<string, unknown> | undefined)?.MonetaryValue as string | undefined;

    const insuranceRaw = forms.InsuranceCharges;
    const insuranceVal = typeof insuranceRaw === 'string' ? insuranceRaw
      : (insuranceRaw as Record<string, unknown> | undefined)?.MonetaryValue as string | undefined;

    return {
      formType: (forms.FormType as string) || '01',
      invoiceNumber: forms.InvoiceNumber as string | undefined,
      invoiceDate: forms.InvoiceDate as string | undefined,
      reasonForExport: forms.ReasonForExport as string | undefined,
      currencyCode: forms.CurrencyCode as string | undefined,
      products,
      invoiceTotal: (invoiceLineTotal?.monetaryValue as string) || undefined,
      invoiceTotalCurrency: (invoiceLineTotal?.currencyCode as string) || undefined,
      freightCharges: freightVal,
      insuranceCharges: insuranceVal,
      termsOfShipment: forms.TermsOfShipment as string | undefined,
      purchaseOrderNumber: forms.PurchaseOrderNumber as string | undefined,
      comments: forms.Comments as string | undefined,
      shipperName: (shipper?.name as string) || (shipper?.Name as string) || undefined,
      recipientName: (shipTo?.name as string) || (shipTo?.Name as string) || undefined,
    };
  } catch {
    return null;
  }
}

/* ──────────────────── Accessorial Extraction ──────────────────── */

/**
 * Simplified-format boolean flag keys → human-readable labels.
 * These are top-level camelCase keys on the resolved_payload.
 */
const SIMPLIFIED_ACCESSORIALS: [string, string][] = [
  ['saturdayDelivery', 'Saturday Delivery'],
  ['holdForPickup', 'Hold for Pickup'],
  ['liftGatePickup', 'Lift Gate Pickup'],
  ['liftGateDelivery', 'Lift Gate Delivery'],
  ['directDeliveryOnly', 'Direct Delivery Only'],
  ['deliverToAddresseeOnly', 'Addressee Only'],
  ['carbonNeutral', 'Carbon Neutral'],
  ['dropoffAtFacility', 'Drop-off at Facility'],
  ['insideDelivery', 'Inside Delivery'],
  ['shipperRelease', 'Shipper Release'],
];

/**
 * Extracts human-readable accessorial labels from the simplified payload.
 *
 * The resolved_payload uses flat camelCase boolean flags (e.g.
 * `saturdayDelivery: true`) and `deliveryConfirmation` as a string code.
 */
function extractAccessorials(payload: Record<string, unknown>): string[] {
  const labels: string[] = [];
  try {
    // Top-level boolean flags
    for (const [key, label] of SIMPLIFIED_ACCESSORIALS) {
      if (payload[key]) labels.push(label);
    }

    // Delivery confirmation: "1" = Signature, "2" = Adult Signature
    const dc = payload.deliveryConfirmation;
    if (dc === '1' || dc === 1) labels.push('Signature Required');
    else if (dc === '2' || dc === 2) labels.push('Adult Signature Required');

    // Notification email
    if (payload.notificationEmail) labels.push('Email Notification');

    // Package-level options
    const packages = payload.packages as Record<string, unknown>[] | undefined;
    if (Array.isArray(packages)) {
      for (const pkg of packages) {
        if (pkg.largePackage && !labels.includes('Large Package')) labels.push('Large Package');
        if (pkg.additionalHandling && !labels.includes('Additional Handling')) labels.push('Additional Handling');
        if (pkg.declaredValue && !labels.some(l => l.startsWith('Declared Value'))) {
          labels.push(`Declared Value: $${pkg.declaredValue}`);
        }
      }
    }
  } catch {
    // Gracefully return whatever we have
  }
  return labels;
}

/** Options passed from the warning gate to handleConfirm. */
export interface ConfirmOptions {
  skipWarningRows?: boolean;
  warningRowNumbers?: number[];
  selectedServiceCode?: string;
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
  readOnly,
}: {
  preview: BatchPreview;
  onConfirm: (opts?: ConfirmOptions) => void;
  onCancel: () => void;
  isConfirming: boolean;
  onRefine: (text: string) => void;
  isRefining: boolean;
  isProcessing: boolean;
  warningPreference: WarningPreference;
  readOnly?: boolean;
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
      {!readOnly && (
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
      )}

      {/* Actions — warning gate or standard buttons */}
      {!readOnly && (
      <>
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
      </>
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
  onSelectService,
  selectedServiceCode,
  isConfirming,
  isRefining,
  isProcessing,
  readOnly,
}: {
  preview: BatchPreview;
  onConfirm: (opts?: ConfirmOptions) => void;
  onCancel: () => void;
  onRefine: (text: string) => void;
  onSelectService?: (serviceCode: string) => void;
  selectedServiceCode?: string | null;
  isConfirming: boolean;
  isRefining: boolean;
  isProcessing: boolean;
  readOnly?: boolean;
}) {
  const [showPayload, setShowPayload] = React.useState(false);
  const [refinementInput, setRefinementInput] = React.useState('');
  const { shipper, ship_to: shipTo } = preview;
  const hasWarnings = preview.preview_rows?.some(r => r.warnings?.length > 0);
  const availableServices = preview.available_services || [];
  const refinementDisabled = isRefining || isConfirming || isProcessing;
  const effectiveServiceCode = selectedServiceCode || preview.service_code || null;
  const selectedService = availableServices.find((svc) => svc.code === effectiveServiceCode);
  const displayedServiceName = selectedService?.name || preview.service_name || 'UPS Ground';
  const displayedTotalCostCents = selectedService?.estimated_cost_cents ?? preview.total_estimated_cost_cents;
  const isInternational = !!(shipTo?.country && shipTo.country !== 'US');
  const accessorials = React.useMemo(
    () => preview.resolved_payload ? extractAccessorials(preview.resolved_payload) : [],
    [preview.resolved_payload]
  );
  const invoiceData = React.useMemo(
    () => preview.resolved_payload ? extractInvoiceData(preview.resolved_payload) : null,
    [preview.resolved_payload]
  );
  const [showInvoice, setShowInvoice] = React.useState(false);
  const [invoiceRefinementInput, setInvoiceRefinementInput] = React.useState('');

  const submitRefinement = () => {
    const text = refinementInput.trim();
    if (!text || refinementDisabled) return;
    onRefine(text);
    setRefinementInput('');
  };

  return (
    <div className="card-premium p-4 animate-scale-in max-w-lg">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <PackageIcon className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Shipment Preview</h3>
        </div>
        <span className="badge-info text-[10px] px-1.5 py-0.5">Ready</span>
      </div>

      {/* Ship From / Ship To */}
      <div className="grid grid-cols-2 gap-2 mb-2">
        <div className="bg-slate-800/50 rounded-lg px-2.5 py-2">
          <div className="flex items-center gap-1 mb-0.5">
            <MapPinIcon className="w-3 h-3 text-slate-500" />
            <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">From</span>
          </div>
          {shipper ? (
            <div className="text-xs text-slate-200 leading-snug">
              <p className="font-medium truncate">{shipper.name}</p>
              <p className="text-slate-400 truncate">
                {shipper.addressLine1}{shipper.addressLine2 ? `, ${shipper.addressLine2}` : ''}
              </p>
              <p className="text-slate-400">
                {shipper.city}, {shipper.stateProvinceCode} {shipper.postalCode}
              </p>
            </div>
          ) : (
            <p className="text-xs text-slate-400">From config</p>
          )}
        </div>

        <div className="bg-slate-800/50 rounded-lg px-2.5 py-2">
          <div className="flex items-center gap-1 mb-0.5">
            <UserIcon className="w-3 h-3 text-slate-500" />
            <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">To</span>
            {shipTo?.country && shipTo.country !== 'US' && (
              <CountryBadge country={shipTo.country} />
            )}
          </div>
          {shipTo ? (
            <div className="text-xs text-slate-200 leading-snug">
              <p className="font-medium truncate">{shipTo.name}</p>
              <p className="text-slate-400 truncate">
                {shipTo.address1}{shipTo.address2 ? `, ${shipTo.address2}` : ''}
              </p>
              <p className="text-slate-400">
                {shipTo.city}, {shipTo.state} {shipTo.postal_code}
              </p>
            </div>
          ) : (
            <p className="text-xs text-slate-400">--</p>
          )}
        </div>
      </div>

      {/* Service / Weight / Account */}
      <div className="flex items-center justify-between bg-slate-800/50 rounded-lg px-3 py-1.5 mb-2 text-xs">
        <div className="flex items-center gap-1">
          <span className="text-slate-500">Service:</span>
          <span className="font-medium text-white">{displayedServiceName}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-slate-500">Wt:</span>
          <span className="font-medium text-white">{preview.weight_lbs ?? 1.0} lbs</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-slate-500">Acct:</span>
          <span className="font-medium text-white font-mono">{preview.account_number || '****'}</span>
        </div>
      </div>

      {/* Accessorials */}
      {accessorials.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {accessorials.map((label) => (
            <span
              key={label}
              className="px-2 py-0.5 rounded-full bg-slate-700/60 border border-slate-600/40 text-[10px] text-slate-300"
            >
              {label}
            </span>
          ))}
        </div>
      )}

      {/* Available services from UPS Shop */}
      {availableServices.length > 0 && (
        <div className="mb-2 rounded-lg border border-slate-700/60 bg-slate-900/40 p-2">
          <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">
            Available Services
          </p>
          <div className="space-y-0.5 max-h-24 overflow-y-auto scrollable pr-1">
            {availableServices.map((svc) => {
              const isSelected = svc.code === effectiveServiceCode;
              const label = `${svc.name} (${svc.code})`;
              return (
                <button
                  key={svc.code}
                  type="button"
                  onClick={() => {
                    if (isSelected || refinementDisabled) return;
                    onSelectService?.(svc.code);
                  }}
                  disabled={refinementDisabled}
                  className={cn(
                    'w-full rounded-md border px-2 py-1 text-left transition-colors',
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
      <div className="bg-gradient-to-r from-emerald-500/10 to-emerald-500/5 border border-emerald-500/20 rounded-lg px-3 py-1.5 mb-2 flex items-center justify-between">
        <p className="text-[10px] font-medium text-emerald-400 uppercase tracking-wider">Estimated Cost</p>
        <p className="text-lg font-bold text-emerald-400">
          {formatCurrency(displayedTotalCostCents)}
        </p>
      </div>

      {/* View Invoice (international only) */}
      {isInternational && invoiceData && (
        <div className="flex justify-center mb-2">
          <button
            type="button"
            onClick={() => setShowInvoice(true)}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>View Invoice</span>
          </button>
        </div>
      )}

      {/* Warning (if rate failed) */}
      {hasWarnings && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-2 mb-2">
          <p className="text-sm text-amber-300 font-medium mb-1">Rating Warning</p>
          {preview.preview_rows?.map((r, i) =>
            r.warnings?.map((w, j) => (
              <p key={`${i}-${j}`} className="text-xs text-amber-200/80">{w}</p>
            ))
          )}
        </div>
      )}

      {/* Refinement input */}
      {!readOnly && (
      <div className="mb-2">
        <div className="flex gap-1.5">
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
            placeholder='Refine: e.g. "make it 3 lbs"'
            disabled={refinementDisabled}
            className="flex-1 px-2.5 py-1.5 text-xs bg-slate-800/70 border border-slate-700 rounded-md text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/25 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={submitRefinement}
            disabled={!refinementInput.trim() || refinementDisabled}
            className="px-2.5 py-1.5 text-xs btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRefining ? 'Applying...' : 'Apply'}
          </button>
        </div>
      </div>
      )}

      {/* Expandable Full Payload */}
      {preview.resolved_payload && (
        <div className="mb-2">
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
      {!readOnly && (
      <div className="flex gap-3">
        <button
          onClick={onCancel}
          disabled={isConfirming || isProcessing || isRefining}
          className="btn-secondary flex-1 h-9 text-sm"
        >
          Cancel
        </button>
        <button
          onClick={() => onConfirm({ selectedServiceCode: effectiveServiceCode || undefined })}
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
      )}

      {/* Invoice Details Modal */}
      {showInvoice && invoiceData && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setShowInvoice(false); }}
        >
          <div className="relative w-full max-w-md mx-4 max-h-[85vh] overflow-y-auto scrollable bg-slate-900 border border-slate-700/60 rounded-xl p-5 shadow-2xl">
            {/* Close button */}
            <button
              type="button"
              onClick={() => setShowInvoice(false)}
              className="absolute top-3 right-3 text-slate-400 hover:text-white transition-colors"
            >
              <XIcon className="w-4 h-4" />
            </button>

            {/* Modal header */}
            <div className="mb-4">
              <h4 className="text-sm font-semibold text-white">Commercial Invoice</h4>
              <div className="flex items-center gap-3 mt-1 text-[10px] font-mono text-slate-400">
                {invoiceData.invoiceNumber && <span>#{invoiceData.invoiceNumber}</span>}
                {invoiceData.invoiceDate && <span>{invoiceData.invoiceDate}</span>}
              </div>
            </div>

            {/* Parties */}
            {(invoiceData.shipperName || invoiceData.recipientName) && (
              <div className="grid grid-cols-2 gap-3 mb-4">
                {invoiceData.shipperName && (
                  <div>
                    <p className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-0.5">Shipper</p>
                    <p className="text-xs text-slate-200">{invoiceData.shipperName}</p>
                  </div>
                )}
                {invoiceData.recipientName && (
                  <div>
                    <p className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-0.5">Recipient</p>
                    <p className="text-xs text-slate-200">{invoiceData.recipientName}</p>
                  </div>
                )}
              </div>
            )}

            {/* Commodity table */}
            {invoiceData.products.length > 0 && (
              <div className="mb-4">
                <p className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5">Commodities</p>
                <div className="border border-slate-700/50 rounded-lg overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-slate-800/60 text-[10px] text-slate-400 uppercase tracking-wider">
                        <th className="text-left px-2.5 py-1.5 font-medium">Description</th>
                        <th className="text-left px-2 py-1.5 font-medium">HS Code</th>
                        <th className="text-center px-2 py-1.5 font-medium">Qty</th>
                        <th className="text-right px-2.5 py-1.5 font-medium">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {invoiceData.products.map((p, i) => (
                        <tr key={i} className="border-t border-slate-800/40">
                          <td className="px-2.5 py-1.5 text-slate-200">
                            <div>{p.description}</div>
                            {p.originCountry && (
                              <span className="text-[9px] text-slate-500">Origin: {p.originCountry}</span>
                            )}
                          </td>
                          <td className="px-2 py-1.5 font-mono text-slate-400 text-[10px]">
                            {p.commodityCode || '—'}
                          </td>
                          <td className="px-2 py-1.5 text-center text-slate-300">
                            {p.quantity || '—'}
                          </td>
                          <td className="px-2.5 py-1.5 text-right font-mono text-slate-300">
                            {p.lineTotal ? `$${p.lineTotal}` : p.unitValue ? `$${p.unitValue}` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Summary */}
            <div className="bg-slate-800/40 rounded-lg p-3 mb-4 space-y-1.5">
              {(invoiceData.invoiceTotal || invoiceData.invoiceTotalCurrency) && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Invoice Total</span>
                  <span className="font-mono text-white font-medium">
                    {invoiceData.invoiceTotal ? `$${invoiceData.invoiceTotal}` : '—'}
                    {invoiceData.invoiceTotalCurrency && (
                      <span className="text-slate-400 ml-1">{invoiceData.invoiceTotalCurrency}</span>
                    )}
                  </span>
                </div>
              )}
              {invoiceData.currencyCode && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Currency</span>
                  <span className="font-mono text-slate-200">{invoiceData.currencyCode}</span>
                </div>
              )}
              {invoiceData.reasonForExport && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Reason for Export</span>
                  <span className="text-slate-200">{invoiceData.reasonForExport}</span>
                </div>
              )}
            </div>

            {/* Footer metadata */}
            {(invoiceData.termsOfShipment || invoiceData.purchaseOrderNumber ||
              invoiceData.freightCharges || invoiceData.insuranceCharges || invoiceData.comments) && (
              <div className="space-y-1 mb-4 text-[10px] font-mono text-slate-400">
                {invoiceData.termsOfShipment && (
                  <div className="flex justify-between">
                    <span>Terms</span><span className="text-slate-300">{invoiceData.termsOfShipment}</span>
                  </div>
                )}
                {invoiceData.purchaseOrderNumber && (
                  <div className="flex justify-between">
                    <span>PO Number</span><span className="text-slate-300">{invoiceData.purchaseOrderNumber}</span>
                  </div>
                )}
                {invoiceData.freightCharges && (
                  <div className="flex justify-between">
                    <span>Freight Charges</span><span className="text-slate-300">${invoiceData.freightCharges}</span>
                  </div>
                )}
                {invoiceData.insuranceCharges && (
                  <div className="flex justify-between">
                    <span>Insurance Charges</span><span className="text-slate-300">${invoiceData.insuranceCharges}</span>
                  </div>
                )}
                {invoiceData.comments && (
                  <div>
                    <span className="block text-slate-500 mb-0.5">Comments</span>
                    <span className="text-slate-300">{invoiceData.comments}</span>
                  </div>
                )}
              </div>
            )}

            {/* Invoice refinement */}
            <div className="border-t border-slate-700/50 pt-3">
              <p className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
                Refine Invoice
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={invoiceRefinementInput}
                  onChange={(e) => setInvoiceRefinementInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      const text = invoiceRefinementInput.trim();
                      if (text && !refinementDisabled) {
                        onRefine(text);
                        setInvoiceRefinementInput('');
                      }
                    }
                  }}
                  placeholder='e.g. "change currency to CAD"'
                  disabled={refinementDisabled}
                  className="flex-1 px-3 py-1.5 text-xs bg-slate-800/70 border border-slate-700 rounded-md text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/25 disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => {
                    const text = invoiceRefinementInput.trim();
                    if (text && !refinementDisabled) {
                      onRefine(text);
                      setInvoiceRefinementInput('');
                    }
                  }}
                  disabled={!invoiceRefinementInput.trim() || refinementDisabled}
                  className="px-3 py-1.5 text-xs btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isRefining ? 'Applying...' : 'Apply'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
