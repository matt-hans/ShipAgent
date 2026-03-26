/**
 * LandedCostCardComponent
 *
 * Port of React LandedCostCard.tsx.
 * Renders landed cost estimation with duties, taxes, fees breakdown.
 * Domain color: landed-cost/indigo via card-domain-landed-cost CSS class.
 * Uses component-level FormatCurrencyPipe for cost display.
 */

import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
} from '@angular/core';
import { PackageIconComponent } from '@shipagent/shared-ui';
import type { LandedCostResult } from '@shipagent/shared-types';

/** Parse numeric-like values safely. */
function parseMoney(value: string | number | undefined): number | null {
  if (value === undefined || value === null || (value as string) === '') return null;
  const num = typeof value === 'number' ? value : parseFloat(value as string);
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

interface TotalEntry {
  label: string;
  value: string | undefined;
}

@Component({
  selector: 'app-landed-cost-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PackageIconComponent],
  template: `
    <div class="card-premium p-4 space-y-3 border-l-4 card-domain-landed-cost">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <sa-icon-package class="w-4 h-4 text-[var(--color-domain-landed-cost)]" />
          <h4 class="text-sm font-medium text-foreground">Landed Cost Estimate</h4>
        </div>
        <span class="badge badge-info">ESTIMATE</span>
      </div>

      <!-- Shipment summary -->
      @if (summary || lane || data.shipmentId) {
        <div class="rounded-md border border-border/50 bg-muted/30 px-3 py-2 space-y-1">
          @if (lane) {
            <div class="flex items-center justify-between text-xs">
              <span class="text-muted-foreground">Route</span>
              <span class="font-mono text-foreground">{{ lane }}</span>
            </div>
          }
          @if (summary) {
            <div class="flex items-center justify-between text-xs">
              <span class="text-muted-foreground">Commodities / Units</span>
              <span class="font-mono text-foreground">{{ summary.commodityCount }} / {{ summary.totalUnits }}</span>
            </div>
          }
          @if (data.shipmentId) {
            <div class="flex items-center justify-between text-xs">
              <span class="text-muted-foreground">Shipment ID</span>
              <div class="min-w-0 flex items-center gap-2">
                <span class="font-mono text-foreground truncate max-w-[12rem]" [title]="data.shipmentId">
                  {{ data.shipmentId }}
                </span>
                <button
                  type="button"
                  (click)="copyShipmentId()"
                  class="px-1.5 py-0.5 rounded border border-border/50 text-[10px] font-mono text-muted-foreground hover:text-foreground hover:border-border transition-colors"
                  aria-label="Copy shipment ID"
                >
                  {{ copyState() === 'copied' ? 'Copied' : copyState() === 'error' ? 'Failed' : 'Copy' }}
                </button>
              </div>
            </div>
          }
          @if (data.transId) {
            <div class="flex items-center justify-between text-xs">
              <span class="text-muted-foreground">Trans ID</span>
              <span class="font-mono text-muted-foreground truncate max-w-[12rem]" [title]="data.transId">
                {{ data.transId }}
              </span>
            </div>
          }
        </div>
      }

      <!-- Shipment-level totals -->
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
        @for (entry of totals; track entry.label) {
          <div class="rounded-md border border-border/40 bg-background/40 px-2 py-1.5">
            <p class="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{{ entry.label }}</p>
            <p class="text-xs font-semibold text-foreground">{{ formatAmount(entry.value) }}</p>
          </div>
        }
      </div>

      <!-- Brokerage fee line-items -->
      @if (brokerageItems.length > 0) {
        <div class="rounded-md border border-border/40 overflow-hidden">
          <div class="px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground bg-muted/30">
            Brokerage Fees
          </div>
          @for (fee of brokerageItems; track $index) {
            <div class="flex items-center justify-between px-3 py-2 text-xs border-t border-border/30 first:border-t-0">
              <span class="text-muted-foreground">{{ fee.chargeName }}</span>
              <span class="font-mono text-foreground">{{ formatAmount(fee.chargeAmount) }}</span>
            </div>
          }
        </div>
      }

      <!-- Per-commodity breakdown table -->
      @if (data.items && data.items.length > 0) {
        <div class="overflow-x-auto rounded-md border border-border/40">
          <table class="w-full text-xs font-mono">
            <thead>
              <tr class="text-muted-foreground border-b border-border bg-muted/20">
                <th class="text-left py-2 px-3">Item</th>
                <th class="text-right py-2 px-3">Duties</th>
                <th class="text-right py-2 px-3">VAT/Taxes</th>
                <th class="text-right py-2 px-3">Fees</th>
                @if (hasItemTotalDutyAndTax) {
                  <th class="text-right py-2 px-3">Total</th>
                }
                @if (hasCommodityHs) {
                  <th class="text-right py-2 px-3">HS Code</th>
                }
                @if (hasNonCalculableItem) {
                  <th class="text-right py-2 px-3">Calculable</th>
                }
              </tr>
            </thead>
            <tbody>
              @for (item of data.items; track item.commodityId) {
                <tr class="border-b border-border/30 last:border-b-0">
                  <td class="py-2 px-3 text-muted-foreground">
                    @if (item.itemLabel) {
                      <div class="flex flex-col">
                        <span class="text-foreground truncate max-w-[12rem]" [title]="item.itemLabel">{{ item.itemLabel }}</span>
                        <span class="text-[10px] text-muted-foreground">#{{ item.commodityId }}</span>
                      </div>
                    } @else {
                      #{{ item.commodityId }}
                    }
                  </td>
                  <td class="py-2 px-3 text-right text-foreground">{{ formatAmount(item.duties) }}</td>
                  <td class="py-2 px-3 text-right text-foreground">{{ formatAmount(item.taxes) }}</td>
                  <td class="py-2 px-3 text-right text-foreground">{{ formatAmount(item.fees) }}</td>
                  @if (hasItemTotalDutyAndTax) {
                    <td class="py-2 px-3 text-right text-foreground">{{ formatAmount(item.totalDutyAndTax) }}</td>
                  }
                  @if (hasCommodityHs) {
                    <td class="py-2 px-3 text-right text-muted-foreground">{{ item.hsCode || '-' }}</td>
                  }
                  @if (hasNonCalculableItem) {
                    <td class="py-2 px-3 text-right text-muted-foreground">{{ item.isCalculable === false ? 'No' : 'Yes' }}</td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      <!-- Grand total -->
      <div class="flex items-center justify-between pt-2 border-t border-border">
        <span class="text-xs font-medium text-muted-foreground">Total Landed Cost</span>
        <span class="text-sm font-semibold text-foreground">{{ formatAmount(data.totalLandedCost) }}</span>
      </div>
    </div>
  `,
})
export class LandedCostCardComponent {
  @Input({ required: true }) data!: LandedCostResult;

  readonly copyState = signal<'idle' | 'copied' | 'error'>('idle');

  get currency(): string {
    return (this.data?.requestSummary?.currencyCode || this.data?.currencyCode || 'USD').toUpperCase();
  }

  get summary() {
    return this.data?.requestSummary;
  }

  get lane(): string {
    return formatLane(
      this.summary?.exportCountryCode,
      this.summary?.importCountryCode || this.data?.importCountryCode,
    );
  }

  get brokerageItems() {
    return this.data?.brokerageFeeItems ?? [];
  }

  get hasItemTotalDutyAndTax(): boolean {
    return this.data?.items?.some((i) => Boolean(i.totalDutyAndTax)) ?? false;
  }

  get hasCommodityHs(): boolean {
    return this.data?.items?.some((i) => Boolean(i.hsCode)) ?? false;
  }

  get hasNonCalculableItem(): boolean {
    return this.data?.items?.some((i) => i.isCalculable === false) ?? false;
  }

  get totals(): TotalEntry[] {
    const s = this.summary;
    return [
      s ? { label: 'Declared Value', value: s.declaredMerchandiseValue } : null,
      { label: 'Duties', value: this.data?.totalDuties },
      { label: 'VAT / Taxes', value: this.data?.totalVAT },
      { label: 'Duty + Tax Total', value: this.data?.totalDutyAndTax },
      { label: 'Commodity Tax/Fee', value: this.data?.totalCommodityLevelTaxesAndFees },
      { label: 'Shipment Tax/Fee', value: this.data?.totalShipmentLevelTaxesAndFees },
      { label: 'Brokerage', value: this.data?.totalBrokerageFees },
    ].filter((entry): entry is TotalEntry => entry !== null);
  }

  protected formatAmount(value: string | number | undefined): string {
    return fmtAmount(value, this.currency);
  }

  async copyShipmentId(): Promise<void> {
    if (!this.data.shipmentId || !navigator?.clipboard?.writeText) {
      this.copyState.set('error');
      window.setTimeout(() => this.copyState.set('idle'), 1400);
      return;
    }
    try {
      await navigator.clipboard.writeText(this.data.shipmentId);
      this.copyState.set('copied');
    } catch {
      this.copyState.set('error');
    }
    window.setTimeout(() => this.copyState.set('idle'), 1400);
  }
}
