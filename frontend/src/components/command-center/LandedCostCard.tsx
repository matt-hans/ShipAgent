/**
 * Inline card for landed cost estimation results in the chat thread.
 *
 * Shows duty/tax/fees breakdown per commodity plus shipment-level
 * totals with indigo domain border.  Accepts LandedCostResult as props.
 */

import { cn } from '@/lib/utils';
import type { LandedCostResult } from '@/types/api';

/** Format a numeric string with the given currency code. */
function fmtAmount(value: string | undefined, currency: string): string {
  if (!value || value === '0') return `0.00 ${currency}`;
  const num = parseFloat(value);
  if (isNaN(num)) return `${value} ${currency}`;
  return `${num.toFixed(2)} ${currency}`;
}

export function LandedCostCard({ data }: { data: LandedCostResult }) {
  return (
    <div className={cn('card-premium p-4 space-y-3 border-l-4 card-domain-landed-cost')}>
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">Landed Cost Estimate</h4>
        <span className="badge badge-info">
          {data.currencyCode}
        </span>
      </div>

      {/* Per-commodity breakdown table */}
      {data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-muted-foreground border-b border-border">
                <th className="text-left py-1.5 pr-3">Item</th>
                <th className="text-right py-1.5 px-3">Duties</th>
                <th className="text-right py-1.5 px-3">VAT/Taxes</th>
                <th className="text-right py-1.5 px-3">Fees</th>
                {data.items.some((i) => i.hsCode) && (
                  <th className="text-right py-1.5 pl-3">HS Code</th>
                )}
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.commodityId} className="border-b border-border/50">
                  <td className="py-1.5 pr-3 text-muted-foreground">#{item.commodityId}</td>
                  <td className="py-1.5 px-3 text-right text-foreground">
                    {fmtAmount(item.duties, data.currencyCode)}
                  </td>
                  <td className="py-1.5 px-3 text-right text-foreground">
                    {fmtAmount(item.taxes, data.currencyCode)}
                  </td>
                  <td className="py-1.5 px-3 text-right text-foreground">
                    {fmtAmount(item.fees, data.currencyCode)}
                  </td>
                  {data.items.some((i) => i.hsCode) && (
                    <td className="py-1.5 pl-3 text-right text-muted-foreground">
                      {item.hsCode || '-'}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Shipment-level summary */}
      {(data.totalDuties || data.totalVAT || data.totalBrokerageFees) && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          {data.totalDuties && (
            <div className="text-center">
              <span className="text-muted-foreground block">Duties</span>
              <span className="font-medium text-foreground">
                {fmtAmount(data.totalDuties, data.currencyCode)}
              </span>
            </div>
          )}
          {data.totalVAT && (
            <div className="text-center">
              <span className="text-muted-foreground block">VAT</span>
              <span className="font-medium text-foreground">
                {fmtAmount(data.totalVAT, data.currencyCode)}
              </span>
            </div>
          )}
          {data.totalBrokerageFees && (
            <div className="text-center">
              <span className="text-muted-foreground block">Brokerage</span>
              <span className="font-medium text-foreground">
                {fmtAmount(data.totalBrokerageFees, data.currencyCode)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Grand total */}
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <span className="text-xs font-medium text-muted-foreground">Total Landed Cost</span>
        <span className="text-sm font-semibold text-foreground">
          {fmtAmount(data.totalLandedCost, data.currencyCode)}
        </span>
      </div>
    </div>
  );
}
