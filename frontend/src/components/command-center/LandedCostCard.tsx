/**
 * Inline card for landed cost estimation results in the chat thread.
 *
 * Shows duty/tax/fees breakdown per commodity with indigo domain border.
 * Accepts LandedCostResult as props.
 */

import { cn } from '@/lib/utils';
import type { LandedCostResult } from '@/types/api';

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
                <th className="text-right py-1.5 px-3">Taxes</th>
                <th className="text-right py-1.5 pl-3">Fees</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.commodityId} className="border-b border-border/50">
                  <td className="py-1.5 pr-3 text-muted-foreground">#{item.commodityId}</td>
                  <td className="py-1.5 px-3 text-right text-foreground">${item.duties}</td>
                  <td className="py-1.5 px-3 text-right text-foreground">${item.taxes}</td>
                  <td className="py-1.5 pl-3 text-right text-foreground">${item.fees}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Total */}
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <span className="text-xs font-medium text-muted-foreground">Total Landed Cost</span>
        <span className="text-sm font-semibold text-foreground">
          ${data.totalLandedCost} {data.currencyCode}
        </span>
      </div>
    </div>
  );
}
