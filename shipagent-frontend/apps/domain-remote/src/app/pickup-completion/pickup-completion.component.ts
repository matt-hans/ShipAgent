/**
 * PickupCompletionComponent
 *
 * Port of React PickupCompletionCard.tsx.
 * Renders pickup operation result: scheduled, cancelled, or status.
 * Domain color: pickup/purple via card-domain-pickup CSS class.
 */

import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CheckIconComponent, XIconComponent } from '@shipagent/shared-ui';
import type { PickupResult } from '@shipagent/shared-types';

interface ActionMeta {
  label: string;
  badge: string;
  badgeClass: string;
}

const ACTION_META: Record<string, ActionMeta> = {
  scheduled: { label: 'Pickup Scheduled', badge: 'CONFIRMED', badgeClass: 'badge-success' },
  cancelled: { label: 'Pickup Cancelled', badge: 'CANCELLED', badgeClass: 'badge-error' },
  status: { label: 'Pickup Status', badge: 'STATUS', badgeClass: 'badge-neutral' },
  rated: { label: 'Pickup Rate', badge: 'RATE', badgeClass: 'badge-info' },
};

/** Format YYYYMMDD to "Feb 17, 2026" style display. */
function formatPickupDate(raw: string): string {
  if (!raw || raw.length !== 8) return raw ?? '';
  const y = parseInt(raw.slice(0, 4), 10);
  const m = parseInt(raw.slice(4, 6), 10) - 1;
  const d = parseInt(raw.slice(6, 8), 10);
  const date = new Date(y, m, d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format HHMM to "9:00 AM" style display. */
function formatTime(raw: string): string {
  if (!raw || raw.length !== 4) return raw ?? '';
  const h = parseInt(raw.slice(0, 2), 10);
  const mins = raw.slice(2, 4);
  const suffix = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${h12}:${mins} ${suffix}`;
}

@Component({
  selector: 'app-pickup-completion',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CheckIconComponent, XIconComponent],
  template: `
    <div class="card-premium p-4 space-y-3 border-l-4 card-domain-pickup">
      <!-- Header -->
      <div class="flex items-center justify-between">
        <h4 class="text-sm font-medium text-foreground">{{ meta.label }}</h4>
        <span class="badge {{ meta.badgeClass }}">{{ meta.badge }}</span>
      </div>

      <!-- Scheduled: PRN + details -->
      @if (data.action === 'scheduled') {
        @if (data.prn) {
          <div class="flex items-center gap-2 bg-slate-800/50 rounded-lg px-3 py-2">
            <sa-icon-check class="w-4 h-4 text-success flex-shrink-0" />
            <span class="text-xs text-muted-foreground">PRN:</span>
            <span class="text-sm font-mono font-semibold text-foreground">{{ data.prn }}</span>
          </div>
        }

        @if (data.address_line) {
          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-0.5">
              <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Address</p>
              <p class="text-xs text-slate-200">{{ data.address_line }}</p>
              <p class="text-xs text-slate-300">{{ data.city }}, {{ data.state }} {{ data.postal_code }}</p>
            </div>
            <div class="space-y-0.5">
              <p class="text-[10px] font-mono text-slate-500 uppercase tracking-wider">Contact</p>
              <p class="text-xs text-slate-200">{{ data.contact_name }}</p>
              <p class="text-xs text-slate-400 font-mono">{{ data.phone_number }}</p>
            </div>
          </div>
        }

        <div class="flex items-center gap-3 text-xs font-mono text-slate-400">
          @if (data.pickup_date) {
            <span>{{ formatDate(data.pickup_date) }}</span>
          }
          @if (data.ready_time && data.close_time) {
            <span class="text-slate-600">&middot;</span>
            <span>{{ formatTime(data.ready_time) }} – {{ formatTime(data.close_time) }}</span>
          }
          @if (data.grand_total) {
            <span class="text-slate-600">&middot;</span>
            <span class="text-purple-400">\${{ data.grand_total }}</span>
          }
        </div>
      }

      <!-- Cancelled -->
      @if (data.action === 'cancelled') {
        <div class="flex items-center gap-2 text-xs font-mono text-muted-foreground">
          <sa-icon-x class="w-3.5 h-3.5 text-destructive" />
          <span>Pickup cancelled successfully</span>
        </div>
      }

      <!-- Status: show pending pickups -->
      @if (data.action === 'status' && data.pickups && data.pickups.length > 0) {
        <div class="space-y-1.5">
          @for (pickup of data.pickups; track $index) {
            <div class="flex items-center justify-between text-xs font-mono px-2 py-1.5 rounded bg-muted">
              <span class="text-muted-foreground">PRN: {{ pickup.prn }}</span>
              <span class="text-foreground">{{ pickup.pickupDate }}</span>
            </div>
          }
        </div>
      }

      <!-- Status: no pending pickups -->
      @if (data.action === 'status' && (!data.pickups || data.pickups.length === 0)) {
        <p class="text-xs text-muted-foreground">No pending pickups found.</p>
      }
    </div>
  `,
})
export class PickupCompletionComponent {
  @Input({ required: true }) data!: PickupResult;

  protected formatDate = formatPickupDate;
  protected formatTime = formatTime;

  get meta(): ActionMeta {
    return ACTION_META[this.data?.action] ?? ACTION_META['status'];
  }
}
