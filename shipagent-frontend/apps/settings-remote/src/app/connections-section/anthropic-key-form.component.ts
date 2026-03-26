/**
 * AnthropicKeyFormComponent — Credential form for updating the Anthropic API key.
 *
 * Port of AnthropicKeyForm.tsx React component.
 * Simple password input with save button. Calls the keyring-backed credential endpoint.
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
  selector: 'app-anthropic-key-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="space-y-3 pt-1">
      <div class="space-y-1">
        <label class="text-[11px] font-medium text-muted-foreground">
          API Key
        </label>
        <input
          type="password"
          [(ngModel)]="apiKey"
          placeholder="sk-ant-..."
          class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
      </div>

      @if (error()) {
        <p class="text-[11px] text-destructive bg-destructive/10 px-2.5 py-1.5 rounded-md">
          {{ error() }}
        </p>
      }

      @if (success()) {
        <p class="text-[11px] text-success bg-success/10 px-2.5 py-1.5 rounded-md">
          {{ success() }}
        </p>
      }

      <button
        (click)="onSave()"
        [disabled]="saving() || !apiKey.trim()"
        class="w-full text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
      >
        @if (saving()) {
          <span class="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin"></span>
        }
        {{ saving() ? 'Saving...' : 'Update API Key' }}
      </button>
    </div>
  `,
})
export class AnthropicKeyFormComponent {
  private readonly apiService = inject(ApiService);

  @Output() saved = new EventEmitter<void>();

  apiKey = '';
  saving = signal(false);
  error = signal<string | null>(null);
  success = signal<string | null>(null);

  async onSave(): Promise<void> {
    if (!this.apiKey.trim()) {
      this.error.set('API key is required.');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    this.success.set(null);
    try {
      await firstValueFrom(
        this.apiService.putCredential('ANTHROPIC_API_KEY', this.apiKey.trim()),
      );
      this.success.set('API key updated successfully.');
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
