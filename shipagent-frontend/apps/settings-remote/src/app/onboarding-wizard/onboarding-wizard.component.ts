/**
 * OnboardingWizardComponent — Full-screen onboarding wizard.
 *
 * Port of OnboardingWizard.tsx React component.
 * Three steps:
 *   1. Anthropic API Key (required)
 *   2. UPS Credentials (optional — can skip)
 *   3. Shipper Address (optional — can skip)
 *
 * On step 3 completion (or skip): calls completeOnboarding(), updates SettingsStore.
 */

import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { SettingsStore } from '@shipagent/shared-state';
import { StepAnthropicComponent } from './step-anthropic.component';
import { StepUpsComponent } from './step-ups.component';
import { StepShipperComponent } from './step-shipper.component';

type Step = 1 | 2 | 3;

@Component({
  selector: 'app-onboarding-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [StepAnthropicComponent, StepUpsComponent, StepShipperComponent],
  template: `
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-background">
      <div class="w-full max-w-lg mx-auto px-6">
        <!-- Header -->
        <div class="text-center mb-8">
          <h1 class="text-3xl font-bold text-foreground font-serif mb-2">
            Welcome to ShipAgent
          </h1>
          <p class="text-muted-foreground">
            Let's get you set up. This takes about a minute.
          </p>
        </div>

        <!-- Step indicator -->
        <div class="flex items-center justify-center gap-2 mb-8">
          @for (s of [1, 2, 3]; track s) {
            <div
              class="h-2 rounded-full transition-all"
              [class]="s === step()
                ? 'w-8 bg-accent'
                : s < step()
                  ? 'w-2 bg-accent/50'
                  : 'w-2 bg-muted'"
            ></div>
          }
          <span class="ml-3 text-xs text-muted-foreground">
            {{ step() }}/3
          </span>
        </div>

        <!-- Step 1: Anthropic API Key -->
        @if (step() === 1) {
          <app-step-anthropic
            [initialStatus]="credentialStatus()"
            (saved)="onStep1Saved()"
          />
        }

        <!-- Step 2: UPS Credentials -->
        @if (step() === 2) {
          <app-step-ups
            (saved)="onStep2Saved()"
            (skip)="onStep2Skip()"
          />
        }

        <!-- Step 3: Shipper Address -->
        @if (step() === 3) {
          <app-step-shipper
            [existingSettings]="appSettings()"
            (finished)="onFinish()"
          />
        }
      </div>
    </div>
  `,
})
export class OnboardingWizardComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly settingsStore = inject(SettingsStore);

  step = signal<Step>(1);
  credentialStatus = this.settingsStore.credentialStatus;
  appSettings = this.settingsStore.appSettings;

  ngOnInit(): void {
    // Refresh credential status on mount so step 1 shows current state
    firstValueFrom(this.apiService.getCredentialStatus())
      .then((status) => this.settingsStore.setCredentialStatus(status))
      .catch(() => {
        /* non-critical */
      });
  }

  onStep1Saved(): void {
    this.step.set(2);
    // Refresh status to show updated state
    firstValueFrom(this.apiService.getCredentialStatus())
      .then((status) => this.settingsStore.setCredentialStatus(status))
      .catch(() => {
        /* non-critical */
      });
  }

  onStep2Saved(): void {
    this.step.set(3);
  }

  onStep2Skip(): void {
    this.step.set(3);
  }

  async onFinish(): Promise<void> {
    try {
      await firstValueFrom(this.apiService.completeOnboarding());
    } catch (e) {
      console.error('Failed to complete onboarding:', e);
    }

    // Best-effort refresh — onboarding is already complete in DB
    try {
      const settings = await firstValueFrom(this.apiService.getSettings());
      this.settingsStore.setAppSettings(settings);
    } catch {
      /* non-critical */
    }

    // Mark onboarding complete in store to dismiss the overlay
    this.settingsStore.setOnboardingCompleted(true);

    try {
      const status = await firstValueFrom(this.apiService.getCredentialStatus());
      this.settingsStore.setCredentialStatus(status);
    } catch {
      /* non-critical */
    }
  }
}
