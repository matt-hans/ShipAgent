/**
 * StepShipperComponent — Onboarding Step 3: Shipper address.
 *
 * Collects shipper address fields and saves them via patchSettings.
 * Pre-populated from existing settings if available.
 * Skip is always available — address can be set later.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import type { AppSettings } from '@shipagent/shared-types';

@Component({
  selector: 'app-step-shipper',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="card-premium p-6">
      <h2 class="text-lg font-semibold text-foreground mb-1">
        Shipper Address
      </h2>
      <p class="text-sm text-muted-foreground mb-4">
        Default return address for your shipments.
        You can skip this and set it later.
      </p>

      <div class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-sm font-medium text-foreground mb-1">Company Name</label>
            <input
              type="text"
              [(ngModel)]="shipperName"
              placeholder="Acme Corp"
              class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1">Contact Name</label>
            <input
              type="text"
              [(ngModel)]="shipperAttentionName"
              placeholder="Jane Smith"
              class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1">Phone</label>
          <input
            type="tel"
            [(ngModel)]="shipperPhone"
            placeholder="555-123-4567"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1">Address Line 1</label>
          <input
            type="text"
            [(ngModel)]="shipperAddress1"
            placeholder="123 Main St"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1">Address Line 2</label>
          <input
            type="text"
            [(ngModel)]="shipperAddress2"
            placeholder="Suite 100"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <label class="block text-sm font-medium text-foreground mb-1">City</label>
            <input
              type="text"
              [(ngModel)]="shipperCity"
              placeholder="City"
              class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1">State</label>
            <input
              type="text"
              [(ngModel)]="shipperState"
              placeholder="CA"
              maxlength="2"
              class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-foreground mb-1">ZIP</label>
            <input
              type="text"
              [(ngModel)]="shipperZip"
              placeholder="90210"
              class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1">Country</label>
          <select
            [(ngModel)]="shipperCountry"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          >
            <option value="US">US — United States</option>
            <option value="CA">CA — Canada</option>
            <option value="MX">MX — Mexico</option>
          </select>
        </div>
      </div>

      @if (error()) {
        <div class="mt-3 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm">
          {{ error() }}
        </div>
      }

      <div class="flex justify-between mt-6">
        <button
          (click)="skipFinish()"
          [disabled]="saving()"
          class="btn-secondary px-4 py-2 text-sm disabled:opacity-50"
        >
          {{ saving() ? 'Finishing...' : 'Skip' }}
        </button>
        <button
          (click)="onFinish()"
          [disabled]="saving()"
          class="btn-primary px-6 py-2 text-sm disabled:opacity-50"
        >
          {{ saving() ? 'Finishing...' : 'Get Started' }}
        </button>
      </div>
    </div>
  `,
})
export class StepShipperComponent implements OnInit {
  private readonly apiService = inject(ApiService);

  @Input() existingSettings: AppSettings | null = null;
  @Output() finished = new EventEmitter<void>();

  shipperName = '';
  shipperAttentionName = '';
  shipperPhone = '';
  shipperAddress1 = '';
  shipperAddress2 = '';
  shipperCity = '';
  shipperState = '';
  shipperZip = '';
  shipperCountry = 'US';

  saving = signal(false);
  error = signal<string | null>(null);

  ngOnInit(): void {
    if (this.existingSettings) {
      this.shipperName = this.existingSettings.shipper_name ?? '';
      this.shipperAttentionName = this.existingSettings.shipper_attention_name ?? '';
      this.shipperPhone = this.existingSettings.shipper_phone ?? '';
      this.shipperAddress1 = this.existingSettings.shipper_address1 ?? '';
      this.shipperAddress2 = this.existingSettings.shipper_address2 ?? '';
      this.shipperCity = this.existingSettings.shipper_city ?? '';
      this.shipperState = this.existingSettings.shipper_state ?? '';
      this.shipperZip = this.existingSettings.shipper_zip ?? '';
      this.shipperCountry = this.existingSettings.shipper_country ?? 'US';
    }
  }

  /** Skip without saving address — complete onboarding immediately. */
  skipFinish(): void {
    this.finished.emit();
  }

  /** Save address then complete onboarding. */
  async onFinish(): Promise<void> {
    this.saving.set(true);
    this.error.set(null);

    const hasAddress =
      this.shipperName ||
      this.shipperAttentionName ||
      this.shipperAddress1 ||
      this.shipperCity;

    if (hasAddress) {
      try {
        await firstValueFrom(
          this.apiService.patchSettings({
            shipper_name: this.shipperName || null,
            shipper_attention_name: this.shipperAttentionName || null,
            shipper_phone: this.shipperPhone || null,
            shipper_address1: this.shipperAddress1 || null,
            shipper_address2: this.shipperAddress2 || null,
            shipper_city: this.shipperCity || null,
            shipper_state: this.shipperState || null,
            shipper_zip: this.shipperZip || null,
            shipper_country: this.shipperCountry || null,
          }),
        );
      } catch (addrErr) {
        // Non-blocking: address save failure should not block onboarding completion
        console.warn('Shipper address save failed (non-blocking):', addrErr);
      }
    }

    this.saving.set(false);
    this.finished.emit();
  }
}
