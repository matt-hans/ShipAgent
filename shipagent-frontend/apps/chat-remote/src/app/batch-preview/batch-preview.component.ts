/**
 * BatchPreviewComponent — Batch preview card with row table and cost summary.
 *
 * Shows preview rows with recipient, service, and cost details.
 * Defaults to collapsed state showing COLLAPSED_ROW_COUNT rows, with a
 * "Show all X rows" toggle button to expand. Includes confirm/cancel/refine
 * actions via PreviewActionsComponent.
 *
 * Each row is expandable (chevron click) to reveal ShipmentDetails —
 * customer, recipient address, order reference — matching the React
 * PreviewCard's ShipmentDetails component.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormatCurrencyPipe,
  ChevronDownIconComponent,
  ShoppingCartIconComponent,
  UserIconComponent,
  MapPinIconComponent,
} from '@shipagent/shared-ui';
import { PreviewActionsComponent } from '../preview-actions/preview-actions.component';
import type { BatchPreview, PreviewRow } from '@shipagent/shared-types';

/** Number of rows shown in collapsed state (matches React COLLAPSED_ROW_COUNT). */
const COLLAPSED_ROW_COUNT = 4;

@Component({
  selector: 'app-batch-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormatCurrencyPipe,
    ChevronDownIconComponent,
    ShoppingCartIconComponent,
    UserIconComponent,
    MapPinIconComponent,
    PreviewActionsComponent,
  ],
  styles: [`
    .chevron-rotated {
      transform: rotate(180deg);
    }
    .row-list-collapsed {
      max-height: 15rem;
    }
    .row-list-expanded {
      max-height: 52vh;
    }
    .row-chevron {
      transition: transform 150ms ease;
    }
    .row-chevron-open {
      transform: rotate(180deg);
    }
    .detail-enter {
      animation: detailFadeIn 200ms ease-out;
    }
    @keyframes detailFadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  `],
  template: `
    <div class="card-premium overflow-hidden">
      <!-- Header -->
      <div class="px-4 pt-4 pb-3 border-b border-border/30">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200">Shipment Preview</h3>
          <div class="flex items-center gap-2">
            <span class="badge badge-info">
              {{ preview.total_rows }} row{{ preview.total_rows !== 1 ? 's' : '' }}
            </span>
            @if (preview.rows_with_warnings > 0) {
              <span class="badge badge-warning">
                {{ preview.rows_with_warnings }} warning{{ preview.rows_with_warnings !== 1 ? 's' : '' }}
              </span>
            }
          </div>
        </div>

        <!-- Cost summary -->
        <div class="mt-2 flex items-center gap-4 text-xs font-mono text-slate-400">
          <span>
            Est. cost:
            <span class="text-primary font-medium">
              {{ preview.total_estimated_cost_cents | formatCurrency }}
            </span>
          </span>
          @if (preview.total_duties_taxes_cents != null && preview.total_duties_taxes_cents > 0) {
            <span>
              + <span class="text-amber-400">{{ preview.total_duties_taxes_cents | formatCurrency }}</span> duties
            </span>
          }
          @if (preview.international_row_count != null && preview.international_row_count > 0) {
            <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[10px] font-medium">
              {{ preview.international_row_count }} INTL
            </span>
          }
        </div>

        <!-- Filter explanation -->
        @if (preview.filter_explanation) {
          <p class="mt-1.5 text-[11px] text-slate-500 italic">{{ preview.filter_explanation }}</p>
        }
      </div>

      <!-- Preview rows table -->
      <div class="overflow-x-auto overflow-y-auto rounded-md"
        [class.row-list-collapsed]="!isExpanded()"
        [class.row-list-expanded]="isExpanded()"
      >
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b border-border/20">
              <th class="px-4 py-2 text-left font-medium text-slate-500">#</th>
              <th class="px-4 py-2 text-left font-medium text-slate-500">Recipient</th>
              <th class="px-4 py-2 text-left font-medium text-slate-500">Service</th>
              <th class="px-4 py-2 text-right font-medium text-slate-500">Cost</th>
            </tr>
          </thead>
          <tbody>
            @for (row of visibleRows(); track row.row_number) {
              <!-- Main row -->
              <tr
                class="border-b border-border/10 transition-colors"
                [class.hover:bg-card/30]="hasOrderData(row)"
                [class.cursor-pointer]="hasOrderData(row)"
                [class.bg-slate-800/20]="isRowExpanded(row.row_number)"
                (click)="hasOrderData(row) && toggleRow(row.row_number)"
              >
                <td class="px-4 py-2 font-mono text-slate-500">
                  <div class="flex items-center gap-1.5">
                    @if (hasOrderData(row)) {
                      <sa-icon-chevron-down
                        class="w-3.5 h-3.5 text-slate-500 row-chevron flex-shrink-0"
                        [class.row-chevron-open]="isRowExpanded(row.row_number)"
                      />
                    }
                    {{ row.row_number }}
                  </div>
                </td>
                <td class="px-4 py-2">
                  @if (isDifferentRecipient(row)) {
                    <div class="flex items-center gap-2">
                      <span class="text-slate-400 text-[10px]">Customer:</span>
                      <span class="text-slate-300 font-medium truncate">{{ row.order_data?.customer_name }}</span>
                    </div>
                    <div class="flex items-center gap-2">
                      <span class="text-slate-500 text-[10px]">Ship to:</span>
                      <span class="text-slate-200 font-medium truncate">{{ row.recipient_name }}</span>
                      <span class="px-1 py-0.5 rounded bg-primary/20 text-primary text-[8px] font-medium">GIFT</span>
                      @if (row.destination_country && row.destination_country !== 'US') {
                        <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-bold">{{ row.destination_country }}</span>
                      }
                    </div>
                    @if (row.city_state) {
                      <span class="text-slate-500 text-[10px]">{{ row.city_state }}</span>
                    }
                  } @else {
                    <div class="flex items-center gap-2">
                      <span class="text-slate-200 font-medium truncate">{{ row.recipient_name }}</span>
                      @if (row.destination_country && row.destination_country !== 'US') {
                        <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[8px] font-bold">{{ row.destination_country }}</span>
                      }
                    </div>
                    @if (row.city_state) {
                      <p class="text-slate-500">{{ row.city_state }}</p>
                    }
                  }
                  @if (row.warnings.length > 0) {
                    <div class="mt-0.5 space-y-0.5">
                      @for (warning of row.warnings; track $index) {
                        <div class="flex items-start gap-2 text-[10px] text-amber-400/90 bg-amber-400/5 rounded px-2 py-1">
                          <span class="flex-shrink-0 mt-px">&#9888;</span>
                          <span>{{ warning }}</span>
                        </div>
                      }
                    </div>
                  }
                </td>
                <td class="px-4 py-2 text-slate-300 font-mono text-[10px]">{{ row.service || 'UPS Ground' }}</td>
                <td class="px-4 py-2 text-right font-mono">
                  @if (row.warnings.length > 0) {
                    <span class="text-amber-400 font-medium">$0.00</span>
                  } @else if (row.estimated_cost_cents > 0) {
                    <span class="text-primary font-medium">{{ row.estimated_cost_cents | formatCurrency }}</span>
                  } @else {
                    <span class="text-slate-500">&mdash;</span>
                  }
                </td>
              </tr>

              <!-- Expanded details row (ShipmentDetails) -->
              @if (isRowExpanded(row.row_number) && row.order_data) {
                <tr class="detail-enter">
                  <td colspan="4" class="px-4 py-3 bg-slate-800/30 border-t border-slate-800">
                    <div class="grid grid-cols-2 gap-4">
                      <!-- Customer Info (Order Placer) -->
                      <div class="space-y-2">
                        <div class="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                          <sa-icon-shopping-cart class="w-3 h-3" />
                          <span>Customer (Ordered By)</span>
                        </div>
                        <div class="space-y-0.5">
                          <p class="text-sm text-slate-200">{{ row.order_data.customer_name }}</p>
                          @if (row.order_data.customer_email) {
                            <p class="text-[10px] font-mono text-slate-500">{{ row.order_data.customer_email }}</p>
                          }
                        </div>
                      </div>

                      <!-- Recipient Info (Ship To) -->
                      <div class="space-y-2">
                        <div class="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                          <sa-icon-user class="w-3 h-3" />
                          <span>Recipient (Ship To)</span>
                          @if (isDifferentRecipient(row)) {
                            <span class="ml-1 px-1.5 py-0.5 rounded bg-primary/20 text-primary text-[8px] font-medium">GIFT</span>
                          }
                        </div>
                        <div class="space-y-0.5">
                          <p class="text-sm text-slate-200">{{ row.order_data.ship_to_name }}</p>
                          @if (row.order_data.ship_to_company) {
                            <p class="text-xs text-slate-400">{{ row.order_data.ship_to_company }}</p>
                          }
                          @if (row.order_data.ship_to_phone) {
                            <p class="text-[10px] font-mono text-slate-500">{{ row.order_data.ship_to_phone }}</p>
                          }
                        </div>
                      </div>
                    </div>

                    <!-- Address Info -->
                    <div class="mt-3 pt-3 border-t border-slate-800/50">
                      <div class="flex items-center gap-1.5 text-[10px] font-mono text-slate-500 uppercase tracking-wider mb-2">
                        <sa-icon-map-pin class="w-3 h-3" />
                        <span>Shipping Address</span>
                      </div>
                      <div class="space-y-0.5">
                        <p class="text-sm text-slate-200">{{ row.order_data.ship_to_address1 }}</p>
                        @if (row.order_data.ship_to_address2) {
                          <p class="text-sm text-slate-300">{{ row.order_data.ship_to_address2 }}</p>
                        }
                        <p class="text-sm text-slate-300">
                          {{ row.order_data.ship_to_city }}, {{ row.order_data.ship_to_state }} {{ row.order_data.ship_to_postal_code }}
                        </p>
                        <p class="text-[10px] font-mono text-slate-500">{{ row.order_data.ship_to_country }}</p>
                      </div>
                    </div>

                    <!-- Order Reference -->
                    <div class="mt-3 pt-3 border-t border-slate-800/50 flex items-center gap-4">
                      @if (row.order_data.order_number) {
                        <span class="text-[10px] font-mono text-slate-500">
                          Order #<span class="text-slate-400">{{ row.order_data.order_number }}</span>
                        </span>
                      }
                      <span class="text-[10px] font-mono text-slate-500">
                        ID: <span class="text-slate-400">{{ row.order_data.order_id }}</span>
                      </span>
                    </div>
                  </td>
                </tr>
              }
            }
          </tbody>
        </table>
      </div>

      <!-- Expand/collapse toggle -->
      @if (canExpand) {
        <button
          type="button"
          class="w-full py-2 text-[11px] font-medium text-slate-400 hover:text-primary transition-colors flex items-center justify-center gap-1.5 border-t border-border/10"
          (click)="toggleExpanded()"
        >
          <sa-icon-chevron-down
            class="w-3.5 h-3.5 transition-transform"
            [class.chevron-rotated]="isExpanded()"
          />
          <span>
            {{ isExpanded() ? 'Show less' : 'Show all ' + preview.preview_rows.length + ' shipments' }}
          </span>
        </button>
      }

      <!-- More rows indicator (rows beyond what the backend returned) -->
      @if (preview.additional_rows > 0) {
        <div class="px-4 py-2 text-center text-[11px] text-slate-500 border-t border-border/10">
          + {{ preview.additional_rows }} more row{{ preview.additional_rows !== 1 ? 's' : '' }} (not shown in preview)
        </div>
      }

      <!-- Actions -->
      <app-preview-actions
        [isConfirming]="isConfirming"
        (confirm)="confirm.emit()"
        (cancel)="cancel.emit()"
        (refine)="refine.emit($event)"
      />
    </div>
  `,
})
export class BatchPreviewComponent {
  @Input({ required: true }) preview!: BatchPreview;
  @Input() isConfirming = false;

  @Output() confirm = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();
  @Output() refine = new EventEmitter<string>();

  /** Whether the row list is expanded (shows all rows). */
  readonly isExpanded = signal(false);

  /** Set of row numbers whose detail section is expanded. */
  readonly expandedRows = signal<Set<number>>(new Set());

  /** Whether there are enough rows to show the expand/collapse toggle. */
  get canExpand(): boolean {
    return this.preview.preview_rows.length > COLLAPSED_ROW_COUNT;
  }

  /** Compute visible rows based on expanded state. */
  visibleRows(): PreviewRow[] {
    if (this.isExpanded()) {
      return this.preview.preview_rows;
    }
    return this.preview.preview_rows.slice(0, COLLAPSED_ROW_COUNT);
  }

  /** Toggle between collapsed and expanded states. */
  toggleExpanded(): void {
    this.isExpanded.set(!this.isExpanded());
  }

  /** Toggle a row's expanded detail section. */
  toggleRow(rowNumber: number): void {
    this.expandedRows.update(prev => {
      const next = new Set(prev);
      if (next.has(rowNumber)) {
        next.delete(rowNumber);
      } else {
        next.add(rowNumber);
      }
      return next;
    });
  }

  /** Check whether a row's detail section is expanded. */
  isRowExpanded(rowNumber: number): boolean {
    return this.expandedRows().has(rowNumber);
  }

  /** Check whether a row has order_data available for expansion. */
  hasOrderData(row: PreviewRow): boolean {
    return !!row.order_data;
  }

  /**
   * Check whether the customer and recipient are different people (gift order).
   * Matches React's isDifferentRecipient logic.
   */
  isDifferentRecipient(row: PreviewRow): boolean {
    if (!row.order_data) return false;
    const customerName = row.order_data.customer_name;
    const recipientName = row.recipient_name;
    return !!customerName && customerName !== recipientName;
  }
}
