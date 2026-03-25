/**
 * InteractivePreviewComponent — Interactive (single shipment) preview card.
 *
 * Shows full address details, service, and cost for a single shipment.
 * Includes confirm/cancel/refine actions via PreviewActionsComponent.
 * Matches React's InteractivePreviewCard component.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormatCurrencyPipe } from '@shipagent/shared-ui';
import { PreviewActionsComponent } from '../preview-actions/preview-actions.component';
import type { BatchPreview } from '@shipagent/shared-types';

@Component({
  selector: 'app-interactive-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormatCurrencyPipe, PreviewActionsComponent],
  template: `
    <div class="card-premium overflow-hidden">
      <!-- Header -->
      <div class="px-4 pt-4 pb-3 border-b border-border/30">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200">Single Shipment Preview</h3>
          <span class="badge badge-info">Interactive</span>
        </div>
      </div>

      <div class="px-4 py-4 space-y-4">
        <!-- Service -->
        @if (preview.service_name || preview.service_code) {
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-400">Service</span>
            <span class="text-slate-200 font-medium">
              {{ preview.service_name || preview.service_code }}
            </span>
          </div>
        }

        <!-- Ship To -->
        @if (preview.ship_to) {
          <div>
            <p class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-1">Ship To</p>
            <div class="text-sm text-slate-300 space-y-0.5">
              <p class="font-medium text-slate-200">{{ preview.ship_to.name }}</p>
              @if (preview.ship_to.attention_name) {
                <p class="text-slate-400">Attn: {{ preview.ship_to.attention_name }}</p>
              }
              <p>{{ preview.ship_to.address1 }}</p>
              @if (preview.ship_to.address2) { <p>{{ preview.ship_to.address2 }}</p> }
              <p>{{ preview.ship_to.city }}, {{ preview.ship_to.state }} {{ preview.ship_to.postal_code }}</p>
              <p>{{ preview.ship_to.country }}</p>
              @if (preview.ship_to.phone) {
                <p class="text-slate-400">{{ preview.ship_to.phone }}</p>
              }
            </div>
          </div>
        }

        <!-- Package details -->
        <div class="flex items-center gap-4 text-xs font-mono text-slate-400">
          @if (preview.weight_lbs != null) {
            <span>{{ preview.weight_lbs }} lbs</span>
          }
          @if (preview.packaging_type) {
            <span>{{ preview.packaging_type }}</span>
          }
        </div>

        <!-- Cost estimate -->
        @if (preview.preview_rows.length > 0 && preview.preview_rows[0].estimated_cost_cents > 0) {
          <div class="flex items-center justify-between border-t border-border/30 pt-3">
            <span class="text-sm text-slate-400">Estimated Cost</span>
            <span class="text-sm font-semibold text-primary">
              {{ preview.preview_rows[0].estimated_cost_cents | formatCurrency }}
            </span>
          </div>
        }

        <!-- Available services (if multiple) -->
        @if (preview.available_services && preview.available_services.length > 1) {
          <div>
            <p class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
              Available Services
            </p>
            <div class="space-y-1.5">
              @for (svc of preview.available_services; track svc.code) {
                <div class="flex items-center justify-between px-3 py-1.5 rounded bg-card/50 border border-border/30">
                  <span class="text-xs text-slate-300">{{ svc.name }}</span>
                  @if (svc.description) {
                    <span class="text-[11px] font-mono text-slate-500">{{ svc.description }}</span>
                  }
                </div>
              }
            </div>
          </div>
        }
      </div>

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
export class InteractivePreviewComponent {
  @Input({ required: true }) preview!: BatchPreview;
  @Input() isConfirming = false;

  @Output() confirm = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();
  @Output() refine = new EventEmitter<string>();
}
