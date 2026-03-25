/**
 * PickupPreviewComponent
 *
 * Port of React PickupPreviewCard.tsx.
 * Displays pickup schedule preview with confirm/cancel actions.
 * Domain color: pickup/purple via card-domain-pickup CSS class.
 */

import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  inject,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  CheckIconComponent,
  MapPinIconComponent,
  UserIconComponent,
} from '@shipagent/shared-ui';
import { ApiService } from '@shipagent/shared-api';
import { ConversationStore } from '@shipagent/shared-state';
import type { PickupPreview } from '@shipagent/shared-types';

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
  selector: 'app-pickup-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CheckIconComponent, MapPinIconComponent, UserIconComponent],
  template: `
    <div class="card-premium p-5 animate-scale-in max-w-lg border-l-4 card-domain-pickup">
      <!-- Header -->
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-semibold text-white">Pickup Preview</h3>
        <span class="badge badge-info">READY</span>
      </div>

      <!-- Address + Contact grid -->
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="bg-slate-800/50 rounded-lg p-3">
          <div class="flex items-center gap-1.5 mb-2">
            <sa-icon-map-pin class="w-3.5 h-3.5 text-slate-400" />
            <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Pickup Address</span>
          </div>
          <div class="space-y-0.5 text-sm text-slate-200">
            <p>{{ data.address_line }}</p>
            <p class="text-slate-300">{{ data.city }}, {{ data.state }} {{ data.postal_code }}</p>
            <p class="text-[10px] font-mono text-slate-500">{{ data.country_code }}</p>
          </div>
        </div>

        <div class="bg-slate-800/50 rounded-lg p-3">
          <div class="flex items-center gap-1.5 mb-2">
            <sa-icon-user class="w-3.5 h-3.5 text-slate-400" />
            <span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Contact</span>
          </div>
          <div class="space-y-0.5 text-sm text-slate-200">
            <p class="font-medium">{{ data.contact_name }}</p>
            <p class="text-slate-400 text-xs font-mono">{{ data.phone_number }}</p>
          </div>
        </div>
      </div>

      <!-- Schedule row -->
      <div class="grid grid-cols-3 gap-3 mb-4">
        <div class="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p class="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Date</p>
          <p class="text-sm font-semibold text-white">{{ formatDate(data.pickup_date) }}</p>
        </div>
        <div class="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p class="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Ready</p>
          <p class="text-sm font-semibold text-white">{{ formatTime(data.ready_time) }}</p>
        </div>
        <div class="bg-slate-800/50 rounded-lg p-2.5 text-center">
          <p class="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">Close</p>
          <p class="text-sm font-semibold text-white">{{ formatTime(data.close_time) }}</p>
        </div>
      </div>

      <!-- Rate breakdown -->
      @if (data.charges && data.charges.length > 0) {
        <div class="mb-4 rounded-lg border border-slate-700/50 overflow-hidden">
          <div class="px-3 py-2 bg-slate-800/30">
            <p class="text-[10px] font-medium text-slate-400 uppercase tracking-wider">Rate Breakdown</p>
          </div>
          <div class="divide-y divide-slate-800">
            @for (charge of data.charges; track $index) {
              <div class="flex items-center justify-between px-3 py-2 text-sm">
                <span class="text-slate-300">{{ charge.chargeLabel }}</span>
                <span class="font-mono text-slate-200">\${{ charge.chargeAmount }}</span>
              </div>
            }
          </div>
        </div>
      }

      <!-- Grand total -->
      <div class="bg-gradient-to-r from-purple-500/10 to-purple-500/5 border border-purple-500/20 rounded-lg p-3 mb-4 text-center">
        <p class="text-[10px] font-medium text-purple-400 uppercase tracking-wider mb-1">Estimated Cost</p>
        <p class="text-2xl font-bold text-purple-400">\${{ data.grand_total }}</p>
      </div>

      <!-- Actions (hidden after confirm) -->
      @if (isDone()) {
        <div class="flex items-center gap-2 bg-success/10 border border-success/30 rounded-lg px-3 py-2">
          <sa-icon-check class="w-4 h-4 text-success" />
          <span class="text-sm text-success">Pickup scheduling requested — see response below.</span>
        </div>
      } @else {
        <div class="flex gap-3">
          <button
            (click)="onCancel.emit()"
            [disabled]="isConfirming()"
            class="btn-secondary flex-1 h-9 text-sm"
          >
            Cancel
          </button>
          <button
            (click)="handleConfirm()"
            [disabled]="isConfirming()"
            class="btn-primary flex-1 h-9 text-sm flex items-center justify-center gap-2"
          >
            @if (isConfirming()) {
              <span class="animate-spin h-3.5 w-3.5 border-2 border-white/20 border-t-white rounded-full"></span>
              <span>Scheduling...</span>
            } @else {
              <sa-icon-check class="w-3.5 h-3.5" />
              <span>Confirm &amp; Schedule</span>
            }
          </button>
        </div>
      }
    </div>
  `,
})
export class PickupPreviewComponent {
  @Input({ required: true }) data!: PickupPreview;
  @Output() onConfirm = new EventEmitter<void>();
  @Output() onCancel = new EventEmitter<void>();

  private readonly apiService = inject(ApiService);
  private readonly conversationStore = inject(ConversationStore);

  readonly isConfirming = signal(false);
  readonly isDone = signal(false);

  protected formatDate = formatPickupDate;
  protected formatTime = formatTime;

  /**
   * Confirm pickup by sending a message to the agent — matches React logic.
   * React: conv.sendMessage("Confirmed. Schedule the pickup with confirmed=true. confirmation_token=XXX")
   */
  async handleConfirm(): Promise<void> {
    this.isConfirming.set(true);
    try {
      const sid = this.conversationStore.sessionId();
      if (!sid) throw new Error('No active session');

      const tokenClause = (this.data as any).confirmation_token
        ? ` confirmation_token=${(this.data as any).confirmation_token}`
        : '';
      const msg = `Confirmed. Schedule the pickup with confirmed=true.${tokenClause}`;

      // Append user message optimistically
      this.conversationStore.appendMessage({
        id: `user-pickup-${Date.now()}`,
        role: 'user',
        content: msg,
        timestamp: new Date().toISOString(),
      });
      this.conversationStore.setStreaming(true);

      await firstValueFrom(this.apiService.sendMessage(sid, msg));
      this.isDone.set(true);
    } catch (err) {
      console.error('[PickupPreview] Confirm failed:', err);
      this.conversationStore.appendMessage({
        id: `err-pickup-${Date.now()}`,
        role: 'system',
        content: `Pickup scheduling failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
        timestamp: new Date().toISOString(),
        metadata: { type: 'error' },
      });
    } finally {
      this.isConfirming.set(false);
    }
  }
}
