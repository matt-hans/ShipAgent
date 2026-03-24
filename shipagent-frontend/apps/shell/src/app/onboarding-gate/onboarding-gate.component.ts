/**
 * OnboardingGateComponent — Full-screen overlay for first-run setup.
 *
 * Reads SettingsStore.onboardingCompleted() — when false, loads the
 * OnboardingWizard from settings-remote and renders it as a full-screen overlay.
 * Once onboarding completes (store signal flips to true), the overlay disappears.
 *
 * The OnboardingWizard remote is loaded lazily on first render.
 */
import {
  ChangeDetectionStrategy,
  Component,
  Injector,
  NgZone,
  OnInit,
  Type,
  inject,
  signal,
} from '@angular/core';
import { NgComponentOutlet } from '@angular/common';
import { SettingsStore } from '@shipagent/shared-state';
import { RemoteLoaderService } from '../remote-loader.service';

@Component({
  selector: 'app-onboarding-gate',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgComponentOutlet],
  template: `
    @if (!settingsStore.onboardingCompleted()) {
      <!-- Full-screen overlay -->
      <div
        class="fixed inset-0 z-50 bg-background flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-label="First-run setup wizard"
      >
        @if (wizardComponent()) {
          <ng-container
            [ngComponentOutlet]="wizardComponent()!"
            [ngComponentOutletInjector]="wizardInjector()"
          />
        } @else {
          <!-- Loading state while wizard remote fetches -->
          <div class="flex flex-col items-center gap-4">
            <div class="w-12 h-12 rounded-full border-4 border-primary border-t-transparent animate-spin"></div>
            <p class="text-sm text-muted-foreground">Setting up ShipAgent...</p>
          </div>
        }
      </div>
    }
  `,
})
export class OnboardingGateComponent implements OnInit {
  protected readonly settingsStore = inject(SettingsStore);
  private readonly remoteLoader = inject(RemoteLoaderService);
  private readonly injector = inject(Injector);
  private readonly ngZone = inject(NgZone);

  protected readonly wizardComponent = signal<Type<unknown> | null>(null);
  protected readonly wizardInjector = signal<Injector>(this.injector);

  ngOnInit(): void {
    // Only load wizard if onboarding is not yet complete
    if (!this.settingsStore.onboardingCompleted()) {
      this.loadWizard();
    }
  }

  private async loadWizard(): Promise<void> {
    try {
      const entry = await this.remoteLoader.loadOnboardingWizard();
      const childInjector = entry.providers?.length
        ? Injector.create({
            providers: entry.providers as Parameters<typeof Injector.create>[0]['providers'],
            parent: this.injector,
          })
        : this.injector;
      this.ngZone.run(() => {
        this.wizardInjector.set(childInjector);
        this.wizardComponent.set(entry.component);
      });
    } catch (err) {
      // settings-remote not yet built — onboarding gate will show loading spinner
      // The user can still skip onboarding by configuring the backend directly.
      console.warn('[shell] settings-remote (OnboardingWizard) not available:', err);
    }
  }
}
