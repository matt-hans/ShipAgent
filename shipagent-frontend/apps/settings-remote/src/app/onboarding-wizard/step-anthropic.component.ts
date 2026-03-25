/**
 * StepAnthropicComponent — Onboarding Step 1: Anthropic API key.
 *
 * Collects and saves the Anthropic API key via the keyring-backed credential
 * endpoint. Shows current credential status.
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
import type { CredentialStatus } from '@shipagent/shared-types';

@Component({
  selector: 'app-step-anthropic',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="card-premium p-6">
      <h2 class="text-lg font-semibold text-foreground mb-1">
        Anthropic API Key
      </h2>
      <p class="text-sm text-muted-foreground mb-4">
        ShipAgent uses Claude to understand your shipping commands.
        Your key is stored securely in the system keychain.
      </p>

      @if (credentialStatus(); as status) {
        <div class="mb-4 p-2 rounded-md text-xs"
          [class]="status.anthropic_api_key
            ? 'bg-success/10 text-success border border-success/30'
            : 'bg-muted text-muted-foreground border border-border'">
          @if (status.anthropic_api_key) {
            API key is currently configured.
          } @else {
            No API key configured yet.
          }
        </div>
      }

      <label class="block text-sm font-medium text-foreground mb-1.5">
        API Key
      </label>
      <input
        type="password"
        [(ngModel)]="apiKey"
        placeholder="sk-ant-..."
        class="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
      />

      @if (error()) {
        <div class="mt-3 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm">
          {{ error() }}
        </div>
      }

      <div class="flex justify-end mt-6">
        <button
          (click)="onSave()"
          [disabled]="saving() || !apiKey.trim()"
          class="btn-primary px-6 py-2 text-sm disabled:opacity-50"
        >
          {{ saving() ? 'Saving...' : 'Save & Continue' }}
        </button>
      </div>
    </div>
  `,
})
export class StepAnthropicComponent implements OnInit {
  private readonly apiService = inject(ApiService);

  @Input() initialStatus: CredentialStatus | null = null;
  @Output() saved = new EventEmitter<void>();

  apiKey = '';
  saving = signal(false);
  error = signal<string | null>(null);
  credentialStatus = signal<CredentialStatus | null>(null);

  ngOnInit(): void {
    if (this.initialStatus) {
      this.credentialStatus.set(this.initialStatus);
    }
  }

  async onSave(): Promise<void> {
    if (!this.apiKey.trim()) {
      this.error.set('Anthropic API key is required to continue.');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(
        this.apiService.putCredential('ANTHROPIC_API_KEY', this.apiKey.trim()),
      );
      this.apiKey = '';
      this.saved.emit();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save API key.';
      this.error.set(msg);
    } finally {
      this.saving.set(false);
    }
  }
}
