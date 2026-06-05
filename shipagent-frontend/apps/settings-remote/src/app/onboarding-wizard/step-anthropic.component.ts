/**
 * StepAnthropicComponent — Onboarding Step 1: model provider API key.
 *
 * Collects and saves a model provider API key via the keyring-backed credential
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
        Model Provider API Key
      </h2>
      <p class="text-sm text-muted-foreground mb-4">
        ShipAgent uses your selected model provider to understand shipping commands.
        Your key is stored securely in the system keychain.
      </p>

      @if (credentialStatus(); as status) {
        <div class="mb-4 p-2 rounded-md text-xs"
          [class]="hasConfiguredModelKey(status)
            ? 'bg-success/10 text-success border border-success/30'
            : 'bg-muted text-muted-foreground border border-border'">
          @if (hasConfiguredModelKey(status)) {
            Model provider key is currently configured.
          } @else {
            No model provider key configured yet.
          }
        </div>
      }

      <label
        for="onboarding-model-provider-key"
        class="block text-sm font-medium text-foreground mb-1.5"
      >
        Provider
      </label>
      <select
        id="onboarding-model-provider-key"
        [(ngModel)]="credentialKey"
        class="w-full mb-3 px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
      >
        @for (option of providerOptions; track option.key) {
          <option [value]="option.key">{{ option.label }}</option>
        }
      </select>

      <label
        for="onboarding-model-provider-api-key"
        class="block text-sm font-medium text-foreground mb-1.5"
      >
        API Key
      </label>
      <input
        id="onboarding-model-provider-api-key"
        type="password"
        [(ngModel)]="apiKey"
        [placeholder]="selectedPlaceholder()"
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
  credentialKey = 'ANTHROPIC_API_KEY';
  providerOptions = [
    { key: 'ANTHROPIC_API_KEY', label: 'Anthropic', placeholder: 'sk-ant-...' },
    { key: 'OPENAI_API_KEY', label: 'OpenAI', placeholder: 'sk-...' },
    { key: 'GEMINI_API_KEY', label: 'Gemini', placeholder: 'AI...' },
  ];
  saving = signal(false);
  error = signal<string | null>(null);
  credentialStatus = signal<CredentialStatus | null>(null);

  ngOnInit(): void {
    if (this.initialStatus) {
      this.credentialStatus.set(this.initialStatus);
    }
  }

  hasConfiguredModelKey(status: CredentialStatus): boolean {
    return status.anthropic_api_key || status.openai_api_key || status.gemini_api_key;
  }

  selectedPlaceholder(): string {
    return this.providerOptions.find((option) => option.key === this.credentialKey)
      ?.placeholder ?? 'API key';
  }

  async onSave(): Promise<void> {
    if (!this.apiKey.trim()) {
      this.error.set('A model provider API key is required to continue.');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(
        this.apiService.putCredential(this.credentialKey, this.apiKey.trim()),
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
