/**
 * BatchPreviewComponent — Batch preview card with row table and cost summary.
 *
 * Shows preview rows with recipient, service, and cost details.
 * Defaults to collapsed state showing COLLAPSED_ROW_COUNT rows, with a
 * "Show all X rows" toggle button to expand. Includes confirm/cancel/refine
 * actions via PreviewActionsComponent.
 * Matches React's PreviewCard component (batch mode).
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
import { FormatCurrencyPipe, ChevronDownIconComponent } from '@shipagent/shared-ui';
import { PreviewActionsComponent } from '../preview-actions/preview-actions.component';
import type { BatchPreview, PreviewRow } from '@shipagent/shared-types';

/** Number of rows shown in collapsed state (matches React COLLAPSED_ROW_COUNT). */
const COLLAPSED_ROW_COUNT = 4;

@Component({
  selector: 'app-batch-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormatCurrencyPipe, ChevronDownIconComponent, PreviewActionsComponent],
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
              <tr class="border-b border-border/10 hover:bg-card/30">
                <td class="px-4 py-2 font-mono text-slate-500">{{ row.row_number }}</td>
                <td class="px-4 py-2">
                  <p class="text-slate-200">{{ row.recipient_name }}</p>
                  @if (row.city_state) {
                    <p class="text-slate-500">{{ row.city_state }}</p>
                  }
                  @if (row.warnings.length > 0) {
                    <div class="mt-0.5 space-y-0.5">
                      @for (warning of row.warnings; track $index) {
                        <p class="text-[10px] text-warning/80">{{ warning }}</p>
                      }
                    </div>
                  }
                </td>
                <td class="px-4 py-2 text-slate-300">{{ row.service || 'UPS Ground' }}</td>
                <td class="px-4 py-2 text-right font-mono">
                  @if (row.estimated_cost_cents > 0) {
                    <span class="text-primary">{{ row.estimated_cost_cents | formatCurrency }}</span>
                  } @else {
                    <span class="text-slate-500">&mdash;</span>
                  }
                </td>
              </tr>
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
}
