import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Placeholder remote entry component for settings-remote.
 * This will be replaced with SettingsFlyoutComponent + OnboardingWizardComponent in Phase 9 Plan 04.
 */
@Component({
  selector: 'app-settings-remote-entry',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card-premium p-4">
      <p class="text-muted-foreground">Settings Remote — placeholder (Plan 04 will implement SettingsFlyoutComponent)</p>
    </div>
  `,
})
export class RemoteEntryComponent {}
