/**
 * SettingsFlyoutComponent — Slide-in settings panel from the right.
 *
 * Port of SettingsFlyout.tsx React component.
 * Accordion layout with 4 sections:
 *   1. Connections (provider credential management)
 *   2. Shipment Behaviour (agent model, concurrency, shipper address)
 *   3. Address Book (contact CRUD with search)
 *   4. Custom Commands (slash command CRUD)
 *
 * Closes on backdrop click or X button.
 * Reads open state from AppStore, closes via appStore.closeSettings().
 */

import {
  ChangeDetectionStrategy,
  Component,
  inject,
  signal,
} from '@angular/core';
import { AppStore } from '@shipagent/shared-state';
import { ConnectionsSectionComponent } from '../connections-section/connections-section.component';
import { ShipmentBehaviourSectionComponent } from '../shipment-behaviour-section/shipment-behaviour-section.component';
import { AddressBookSectionComponent } from '../address-book-section/address-book-section.component';
import { CustomCommandsSectionComponent } from '../custom-commands-section/custom-commands-section.component';

@Component({
  selector: 'app-settings-flyout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ConnectionsSectionComponent,
    ShipmentBehaviourSectionComponent,
    AddressBookSectionComponent,
    CustomCommandsSectionComponent,
  ],
  template: `
    <!-- Backdrop -->
    <div
      class="settings-backdrop"
      role="button"
      tabindex="0"
      (click)="close()"
      (keydown.enter)="close()"
    ></div>

    <!-- Flyout panel -->
    <aside class="settings-flyout">
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-border">
        <h2 class="text-lg font-semibold text-foreground">Settings</h2>
        <button
          (click)="close()"
          class="p-1 rounded-md hover:bg-muted transition-colors"
          aria-label="Close settings"
        >
          <!-- X icon -->
          <svg class="h-5 w-5 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <!-- Accordion sections -->
      <div class="settings-flyout-content">
        <!-- Connections -->
        <app-connections-section
          [isOpen]="openSection() === 'connections'"
          (onToggle)="toggleSection('connections')"
        />

        <!-- Shipment Behaviour -->
        <app-shipment-behaviour-section
          [isOpen]="openSection() === 'shipment'"
          (onToggle)="toggleSection('shipment')"
        />

        <!-- Address Book -->
        <app-address-book-section
          [isOpen]="openSection() === 'address'"
          (onToggle)="toggleSection('address')"
        />

        <!-- Custom Commands -->
        <app-custom-commands-section
          [isOpen]="openSection() === 'commands'"
          (onToggle)="toggleSection('commands')"
        />
      </div>
    </aside>
  `,
})
export class SettingsFlyoutComponent {
  private readonly appStore = inject(AppStore);

  openSection = signal<string | null>(null);

  close(): void {
    this.appStore.closeSettings();
  }

  toggleSection(section: string): void {
    this.openSection.update((current) => (current === section ? null : section));
  }
}
