/**
 * HeaderComponent — Application header.
 *
 * Port of React Header.tsx.
 * Features:
 *   - ShipAgent logo + wordmark on the left
 *   - Interactive shipping toggle (Single Shipment mode) on the right
 *
 * Reads: conversationStore.interactiveShipping(), appStore.isToggleLocked()
 * Writes: conversationStore.setInteractiveShipping()
 */
import {
  ChangeDetectionStrategy,
  Component,
  inject,
} from '@angular/core';
import { AppStore, ConversationStore } from '@shipagent/shared-state';
import { ShipAgentLogoComponent } from '@shipagent/shared-ui';

@Component({
  selector: 'app-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ShipAgentLogoComponent],
  template: `
    <header class="app-header">
      <!-- Gradient accent line at top -->
      <div class="h-[1px] bg-gradient-to-r from-transparent via-accent/50 to-transparent"></div>

      <div class="container-wide h-12 flex items-center justify-between">
        <!-- Logo and branding -->
        <div class="flex items-center gap-2">
          <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <sa-shipagent-logo class="h-4 w-4" primaryColor="white" />
          </div>
          <span class="text-lg font-semibold text-foreground">ShipAgent</span>
        </div>

        <!-- Right side: interactive shipping toggle -->
        <div class="flex items-center gap-3">
          <div class="flex items-center gap-2">
            <label
              for="interactive-shipping-toggle"
              class="text-xs text-slate-400 cursor-pointer select-none"
            >
              Single Shipment
            </label>

            <!-- Switch implementation matching React's Switch component -->
            <button
              id="interactive-shipping-toggle"
              role="switch"
              [attr.aria-checked]="conversationStore.interactiveShipping()"
              [disabled]="appStore.isToggleLocked()"
              (click)="onToggleInteractiveShipping()"
              class="relative inline-flex h-5 w-9 cursor-pointer rounded-full border-2 border-transparent
                     transition-colors duration-200 ease-in-out focus-visible:outline-none
                     focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
                     disabled:cursor-not-allowed disabled:opacity-50"
              [class.bg-primary]="conversationStore.interactiveShipping()"
              [class.bg-input]="!conversationStore.interactiveShipping()"
            >
              <span
                class="pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg
                       ring-0 transition-transform duration-200 ease-in-out"
                [class.translate-x-4]="conversationStore.interactiveShipping()"
                [class.translate-x-0]="!conversationStore.interactiveShipping()"
              ></span>
            </button>
          </div>
        </div>
      </div>
    </header>
  `,
})
export class HeaderComponent {
  protected readonly conversationStore = inject(ConversationStore);
  protected readonly appStore = inject(AppStore);

  /** Toggle interactive shipping mode. */
  onToggleInteractiveShipping(): void {
    if (this.appStore.isToggleLocked()) return;
    this.conversationStore.setInteractiveShipping(
      !this.conversationStore.interactiveShipping(),
    );
  }
}
