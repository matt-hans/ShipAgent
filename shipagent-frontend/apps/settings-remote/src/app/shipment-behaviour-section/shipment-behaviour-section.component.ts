/**
 * ShipmentBehaviourSectionComponent — Settings accordion for agent and shipping behaviour.
 *
 * Port of ShipmentBehaviourSection.tsx React component.
 * Fields:
 * - Batch concurrency (range 1-20, debounced DB write)
 * - Agent model (dropdown: haiku, sonnet, opus)
 * - Default shipper address (all fields, saved on demand)
 *
 * Injects SettingsStore and ApiService.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
  OnInit,
  OnDestroy,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { SettingsStore } from '@shipagent/shared-state';

@Component({
  selector: 'app-shipment-behaviour-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="settings-section">
      <!-- Section header -->
      <button
        class="settings-section-header"
        (click)="onToggle.emit()"
        [attr.aria-expanded]="isOpen"
      >
        <div class="flex items-center gap-2">
          <!-- FileOutput icon -->
          <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 22h14a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <path d="M2 15h10"></path>
            <path d="M9 18l3-3-3-3"></path>
          </svg>
          <span class="font-medium text-foreground">Shipment Behaviour</span>
        </div>
        <!-- Chevron -->
        <svg
          class="h-4 w-4 text-muted-foreground transition-transform"
          [class.rotate-180]="isOpen"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      @if (isOpen) {
        <div class="settings-section-content space-y-5">
          @if (saveError()) {
            <div class="p-2 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-xs">
              {{ saveError() }}
            </div>
          }

          <!-- Batch concurrency -->
          <div class="space-y-3">
            <div class="flex items-center gap-2">
              <!-- Gauge icon -->
              <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path>
              </svg>
              <label class="text-sm font-medium text-foreground">
                Batch Concurrency
              </label>
              <span class="text-xs text-muted-foreground ml-auto tabular-nums">
                {{ concurrency() }}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="20"
              [value]="concurrency()"
              (input)="onConcurrencyInput($event)"
              class="w-full accent-primary h-1.5"
            />
            <p class="text-[10px] text-slate-500">
              Max simultaneous shipment API calls during batch execution
            </p>
          </div>

          <!-- Agent model -->
          <div class="space-y-3">
            <div class="flex items-center gap-2">
              <!-- CPU icon -->
              <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
                <rect x="9" y="9" width="6" height="6"></rect>
                <line x1="9" y1="1" x2="9" y2="4"></line>
                <line x1="15" y1="1" x2="15" y2="4"></line>
                <line x1="9" y1="20" x2="9" y2="23"></line>
                <line x1="15" y1="20" x2="15" y2="23"></line>
                <line x1="20" y1="9" x2="23" y2="9"></line>
                <line x1="20" y1="14" x2="23" y2="14"></line>
                <line x1="1" y1="9" x2="4" y2="9"></line>
                <line x1="1" y1="14" x2="4" y2="14"></line>
              </svg>
              <label class="text-sm font-medium text-foreground">
                Agent Model
              </label>
            </div>
            <select
              [(ngModel)]="agentModel"
              name="agentModel"
              (change)="saveAgentModel()"
              class="w-full rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
            >
              <option value="claude-haiku-4-5-20251001">Haiku 4.5 (default)</option>
              <option value="claude-sonnet-4-6">Sonnet 4.6</option>
              <option value="claude-opus-4-6">Opus 4.6</option>
            </select>
            <p class="text-[10px] text-slate-500">
              Changes apply to new conversations.
            </p>
          </div>

          <!-- Default shipper address -->
          <div class="space-y-3">
            <div class="flex items-center gap-2">
              <!-- MapPin icon -->
              <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                <circle cx="12" cy="10" r="3"></circle>
              </svg>
              <label class="text-sm font-medium text-foreground">
                Default Shipper Address
              </label>
            </div>

            <div class="grid grid-cols-2 gap-2">
              <input
                type="text"
                [(ngModel)]="shipperName"
                name="shipperName"
                placeholder="Company Name"
                (input)="markShipperDirty()"
                class="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                [(ngModel)]="shipperAttentionName"
                name="shipperAttentionName"
                placeholder="Contact Name"
                (input)="markShipperDirty()"
                class="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                [(ngModel)]="shipperPhone"
                name="shipperPhone"
                placeholder="Phone"
                (input)="markShipperDirty()"
                class="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                [(ngModel)]="shipperAddress1"
                name="shipperAddress1"
                placeholder="Address Line 1"
                (input)="markShipperDirty()"
                class="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                [(ngModel)]="shipperAddress2"
                name="shipperAddress2"
                placeholder="Address Line 2"
                (input)="markShipperDirty()"
                class="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                [(ngModel)]="shipperCity"
                name="shipperCity"
                placeholder="City"
                (input)="markShipperDirty()"
                class="rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <div class="flex gap-2">
                <input
                  type="text"
                  [(ngModel)]="shipperState"
                  name="shipperState"
                  placeholder="State"
                  (input)="markShipperDirty()"
                  class="w-16 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
                />
                <input
                  type="text"
                  [(ngModel)]="shipperZip"
                  name="shipperZip"
                  placeholder="ZIP"
                  (input)="markShipperDirty()"
                  class="flex-1 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
                />
              </div>
            </div>

            @if (shipperDirty()) {
              <button
                (click)="saveShipperAddress()"
                class="btn-primary text-xs w-full"
              >
                Save Shipper Address
              </button>
            }
          </div>
        </div>
      }
    </div>
  `,
})
export class ShipmentBehaviourSectionComponent implements OnInit, OnDestroy {
  private readonly apiService = inject(ApiService);
  private readonly settingsStore = inject(SettingsStore);

  @Input() isOpen = false;
  @Output() onToggle = new EventEmitter<void>();

  concurrency = signal(5);
  agentModel = 'claude-haiku-4-5-20251001';
  saveError = signal<string | null>(null);
  shipperDirty = signal(false);

  // Shipper address fields
  shipperName = '';
  shipperAttentionName = '';
  shipperPhone = '';
  shipperAddress1 = '';
  shipperAddress2 = '';
  shipperCity = '';
  shipperState = '';
  shipperZip = '';
  shipperCountry = 'US';

  private debounceTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    const settings = this.settingsStore.appSettings();
    if (settings) {
      this.syncFromSettings(settings);
    }
  }

  ngOnDestroy(): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
  }

  private syncFromSettings(settings: any): void {
    this.concurrency.set(settings.batch_concurrency ?? 5);
    this.agentModel = settings.agent_model ?? 'claude-haiku-4-5-20251001';
    this.shipperName = settings.shipper_name ?? '';
    this.shipperAttentionName = settings.shipper_attention_name ?? '';
    this.shipperPhone = settings.shipper_phone ?? '';
    this.shipperAddress1 = settings.shipper_address1 ?? '';
    this.shipperAddress2 = settings.shipper_address2 ?? '';
    this.shipperCity = settings.shipper_city ?? '';
    this.shipperState = settings.shipper_state ?? '';
    this.shipperZip = settings.shipper_zip ?? '';
    this.shipperCountry = settings.shipper_country ?? 'US';
    this.shipperDirty.set(false);
  }

  onConcurrencyInput(event: Event): void {
    const value = Number((event.target as HTMLInputElement).value);
    this.concurrency.set(value);
    this.saveConcurrencyDebounced(value);
  }

  private saveConcurrencyDebounced(value: number): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(async () => {
      try {
        const updated = await firstValueFrom(
          this.apiService.patchSettings({ batch_concurrency: value }),
        );
        this.settingsStore.setAppSettings(updated);
        this.saveError.set(null);
      } catch {
        this.saveError.set('Failed to save concurrency setting.');
      }
    }, 400);
  }

  async saveAgentModel(): Promise<void> {
    try {
      const updated = await firstValueFrom(
        this.apiService.patchSettings({ agent_model: this.agentModel }),
      );
      this.settingsStore.setAppSettings(updated);
      this.saveError.set(null);
    } catch {
      this.saveError.set('Failed to save agent model.');
    }
  }

  markShipperDirty(): void {
    this.shipperDirty.set(true);
  }

  async saveShipperAddress(): Promise<void> {
    try {
      const updated = await firstValueFrom(
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
        } as any),
      );
      this.settingsStore.setAppSettings(updated);
      this.shipperDirty.set(false);
      this.saveError.set(null);
    } catch {
      this.saveError.set('Failed to save shipper address.');
    }
  }
}
