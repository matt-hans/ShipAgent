/**
 * StepUpsComponent — Onboarding Step 2: UPS credentials.
 *
 * Collects UPS Client ID and Client Secret, saves them via the keyring-backed
 * credential endpoint. Account number is optional.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';

@Component({
  selector: 'app-step-ups',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="card-premium p-6">
      <h2 class="text-lg font-semibold text-foreground mb-1">
        UPS Credentials
      </h2>
      <p class="text-sm text-muted-foreground mb-4">
        Connect your UPS account to create shipments.
        You can skip this and add credentials later in Settings.
      </p>

      <div class="space-y-3">
        <div>
          <label class="block text-sm font-medium text-foreground mb-1.5">
            Client ID
          </label>
          <input
            type="text"
            [(ngModel)]="clientId"
            placeholder="Your UPS Client ID"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-foreground mb-1.5">
            Client Secret
          </label>
          <input
            type="password"
            [(ngModel)]="clientSecret"
            placeholder="Your UPS Client Secret"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-foreground mb-1.5">
            Account Number <span class="text-muted-foreground/50 text-xs">(optional)</span>
          </label>
          <input
            type="text"
            [(ngModel)]="accountNumber"
            placeholder="6-digit UPS account number"
            class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
          />
        </div>
      </div>

      @if (error()) {
        <div class="mt-3 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm">
          {{ error() }}
        </div>
      }

      <div class="flex justify-between mt-6">
        <button
          (click)="skip.emit()"
          class="btn-secondary px-4 py-2 text-sm"
        >
          Skip
        </button>
        <button
          (click)="onSave()"
          [disabled]="saving()"
          class="btn-primary px-6 py-2 text-sm disabled:opacity-50"
        >
          {{ saving() ? 'Saving...' : 'Save & Continue' }}
        </button>
      </div>
    </div>
  `,
})
export class StepUpsComponent {
  private readonly apiService = inject(ApiService);

  @Output() saved = new EventEmitter<void>();
  @Output() skip = new EventEmitter<void>();

  clientId = '';
  clientSecret = '';
  accountNumber = '';
  saving = signal(false);
  error = signal<string | null>(null);

  async onSave(): Promise<void> {
    this.saving.set(true);
    this.error.set(null);
    try {
      const saves: Promise<void>[] = [];
      if (this.clientId.trim()) {
        saves.push(
          firstValueFrom(
            this.apiService.putCredential('UPS_CLIENT_ID', this.clientId.trim()),
          ),
        );
      }
      if (this.clientSecret.trim()) {
        saves.push(
          firstValueFrom(
            this.apiService.putCredential('UPS_CLIENT_SECRET', this.clientSecret.trim()),
          ),
        );
      }
      if (saves.length > 0) {
        await Promise.all(saves);
      }
      this.clientId = '';
      this.clientSecret = '';
      this.accountNumber = '';
      this.saved.emit();
    } catch (e: unknown) {
      const msg =
        e instanceof Error
          ? e.message
          : 'Failed to save UPS credentials. Please try again.';
      this.error.set(msg);
    } finally {
      this.saving.set(false);
    }
  }
}
