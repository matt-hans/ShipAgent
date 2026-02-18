/**
 * Inline card for landed cost estimation results in the chat thread.
 *
 * Renders a dedicated landed-cost artifact with:
 * - shipment summary (lane, units, declared value)
 * - shipment-level totals
 * - brokerage fee line-items
 * - per-commodity duty/tax/fee breakdown
 */

import { cn } from '@/lib/utils';
import type { LandedCostResult } from '@/types/api';
import { PackageIcon } from '@/components/ui/icons';

/** Parse numeric-like values safely. */
function parseMoney(value: string | number | undefined): number | null {
  if (value === undefined || value === null || value === '') return null;
  const num = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(num) ? num : null;
}

/** Format numeric-like values with currency fallback. */
function fmtAmount(value: string | number | undefined, currency: string): string {
  const num = parseMoney(value);
  if (num === null) return `0.00 ${currency}`;
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(num);
  } catch {
    return `${num.toFixed(2)} ${currency}`;
  }
}

/** Compact label for lane display (e.g., US -> GB). */
function formatLane(exportCode?: string, importCode?: string): string {
  const from = (exportCode || '').trim();
  const to = (importCode || '').trim();
  if (!from && !to) return '';
  if (!from) return `-> ${to}`;
  if (!to) return `${from} ->`;
  return `${from} -> ${to}`;
}

export function LandedCostCard({ data }: { data: LandedCostResult }) {
  const summary = data.requestSummary;
  const currency = (summary?.currencyCode || data.currencyCode || 'USD').toUpperCase();
  const lane = formatLane(summary?.exportCountryCode, summary?.importCountryCode || data.importCountryCode);
  const brokerageItems = data.brokerageFeeItems ?? [];
  const hasCommodityHs = data.items.some((i) => Boolean(i.hsCode));
  const totals = [
    summary ? { label: 'Declared Value', value: summary.declaredMerchandiseValue } : null,
    { label: 'Duties', value: data.totalDuties },
    { label: 'VAT / Taxes', value: data.totalVAT },
    { label: 'Brokerage', value: data.totalBrokerageFees },
  ].filter(
    (entry): entry is { label: string; value: string | undefined } => entry !== null
  );

  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-landed-cost')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <PackageIcon className="w-4 h-4 text-[var(--color-domain-landed-cost)]" />
          <h4 className="text-sm font-medium text-foreground">Landed Cost Estimate</h4>
        </div>
        <span className="badge badge-info">ESTIMATE</span>
      </div>

      {/* Shipment summary */}
      {(summary || lane || data.shipmentId) && (
        <div className="rounded-md border border-border/50 bg-muted/30 px-3 py-2 space-y-1">
          {lane && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Route</span>
              <span className="font-mono text-foreground">{lane}</span>
            </div>
          )}
          {summary && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Commodities / Units</span>
              <span className="font-mono text-foreground">
                {summary.commodityCount} / {summary.totalUnits}
              </span>
            </div>
          )}
          {data.shipmentId && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Shipment ID</span>
              <span className="font-mono text-foreground truncate max-w-[12rem]">{data.shipmentId}</span>
            </div>
          )}
        </div>
      )}

      {/* Shipment-level totals */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {totals.map((entry) => (
          <div key={entry.label} className="rounded-md border border-border/40 bg-background/40 px-2 py-1.5">
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{entry.label}</p>
            <p className="text-xs font-semibold text-foreground">
              {fmtAmount(entry.value, currency)}
            </p>
          </div>
        ))}
      </div>

      {/* Brokerage fee line-items */}
      {brokerageItems.length > 0 && (
        <div className="rounded-md border border-border/40 overflow-hidden">
          <div className="px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground bg-muted/30">
            Brokerage Fees
          </div>
          {brokerageItems.map((fee, index) => (
            <div
              key={`${fee.chargeName}-${index}`}
              className="flex items-center justify-between px-3 py-2 text-xs border-t border-border/30 first:border-t-0"
            >
              <span className="text-muted-foreground">{fee.chargeName}</span>
              <span className="font-mono text-foreground">{fmtAmount(fee.chargeAmount, currency)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Per-commodity breakdown table */}
      {data.items.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border/40">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-muted-foreground border-b border-border bg-muted/20">
                <th className="text-left py-2 px-3">Item</th>
                <th className="text-right py-2 px-3">Duties</th>
                <th className="text-right py-2 px-3">VAT/Taxes</th>
                <th className="text-right py-2 px-3">Fees</th>
                {hasCommodityHs && (
                  <th className="text-right py-2 px-3">HS Code</th>
                )}
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.commodityId} className="border-b border-border/30 last:border-b-0">
                  <td className="py-2 px-3 text-muted-foreground">#{item.commodityId}</td>
                  <td className="py-2 px-3 text-right text-foreground">
                    {fmtAmount(item.duties, currency)}
                  </td>
                  <td className="py-2 px-3 text-right text-foreground">
                    {fmtAmount(item.taxes, currency)}
                  </td>
                  <td className="py-2 px-3 text-right text-foreground">
                    {fmtAmount(item.fees, currency)}
                  </td>
                  {hasCommodityHs && (
                    <td className="py-2 px-3 text-right text-muted-foreground">
                      {item.hsCode || '-'}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Grand total */}
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <span className="text-xs font-medium text-muted-foreground">Total Landed Cost</span>
        <span className="text-sm font-semibold text-foreground">
          {fmtAmount(data.totalLandedCost, currency)}
        </span>
      </div>
    </div>
  );
}
