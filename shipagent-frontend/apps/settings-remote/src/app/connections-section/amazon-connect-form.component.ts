/**
 * AmazonConnectFormComponent — Credential form for Amazon Selling Partner API.
 *
 * Port of AmazonConnectForm.tsx React component.
 * Collects SP-API credentials: LWA Client ID, Client Secret, Refresh Token, Marketplace.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import type { ProviderConnectionInfo } from '@shipagent/shared-types';

const MARKETPLACE_OPTIONS = [
  { id: 'ATVPDKIKX0DER', label: 'United States (ATVPDKIKX0DER)' },
  { id: 'A2EUQ1WTGCTBG2', label: 'Canada (A2EUQ1WTGCTBG2)' },
  { id: 'A1AM78C64UM0Y8', label: 'Mexico (A1AM78C64UM0Y8)' },
  { id: 'A1F83G8C2ARO7P', label: 'United Kingdom (A1F83G8C2ARO7P)' },
  { id: 'A1PA6795UKMFR9', label: 'Germany (A1PA6795UKMFR9)' },
];

@Component({
  selector: 'app-amazon-connect-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    @if (!showForm()) {
      <button
        (click)="showForm.set(true)"
        class="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        {{ existingConnection ? '+ Replace credentials' : '+ Connect Amazon' }}
      </button>
    } @else {
      <div class="space-y-3 pt-1">
        @if (existingConnection) {
          <p class="text-[10px] text-warning">
            Saving will replace the existing Amazon credentials.
          </p>
        }

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground">LWA Client ID</label>
          <input
            type="text"
            [(ngModel)]="clientId"
            placeholder="amzn1.application-oa2-client..."
            class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground">LWA Client Secret</label>
          <input
            type="password"
            [(ngModel)]="clientSecret"
            placeholder="amzn1.oa2-cs.v1..."
            class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground">Refresh Token</label>
          <input
            type="password"
            [(ngModel)]="refreshToken"
            placeholder="Atzr|..."
            class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground">Marketplace</label>
          <select
            [(ngModel)]="marketplaceId"
            class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
          >
            @for (marketplace of marketplaces; track marketplace.id) {
              <option [value]="marketplace.id">{{ marketplace.label }}</option>
            }
          </select>
        </div>

        <label class="flex items-center gap-2 text-[11px] text-muted-foreground">
          <input
            type="checkbox"
            [(ngModel)]="sandboxEnabled"
            class="rounded border-border bg-background"
          />
          Use Amazon SP-API sandbox endpoints
        </label>

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

        <div class="flex gap-2">
          <button
            (click)="onSave()"
            [disabled]="saving() || !canSave()"
            class="flex-1 text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
          >
            @if (saving()) {
              <span class="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin"></span>
            }
            {{ saving() ? 'Saving...' : (existingConnection ? 'Replace Credentials' : 'Save & Validate') }}
          </button>
          <button
            (click)="cancelForm()"
            class="text-xs py-1.5 px-3 rounded-md border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    }
  `,
})
export class AmazonConnectFormComponent {
  private readonly apiService = inject(ApiService);

  @Input() existingConnection: ProviderConnectionInfo | null = null;
  @Output() saved = new EventEmitter<void>();

  readonly marketplaces = MARKETPLACE_OPTIONS;

  showForm = signal(false);
  clientId = '';
  clientSecret = '';
  refreshToken = '';
  marketplaceId = MARKETPLACE_OPTIONS[0].id;
  sandboxEnabled = false;
  saving = signal(false);
  error = signal<string | null>(null);
  success = signal<string | null>(null);

  canSave(): boolean {
    return !!(
      this.clientId.trim() &&
      this.clientSecret.trim() &&
      this.refreshToken.trim() &&
      this.marketplaceId.trim()
    );
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.error.set(null);
    this.success.set(null);
  }

  async onSave(): Promise<void> {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.error.set(null);
    this.success.set(null);
    try {
      const marketplaceLabel =
        MARKETPLACE_OPTIONS.find((m) => m.id === this.marketplaceId)
          ?.label.split(' (')[0] ?? this.marketplaceId;

      const saveResult = await firstValueFrom(
        this.apiService.saveProviderCredentials('amazon', {
          auth_mode: 'sp_api',
          credentials: {
            client_id: this.clientId.trim(),
            client_secret: this.clientSecret.trim(),
            refresh_token: this.refreshToken.trim(),
            marketplace_id: this.marketplaceId.trim(),
            sandbox: this.sandboxEnabled ? 'true' : 'false',
          },
          metadata: { marketplace_id: this.marketplaceId.trim() },
          display_name: `Amazon ${marketplaceLabel}`,
        }),
      );

      try {
        const validation = await firstValueFrom(
          this.apiService.validateProviderConnection(saveResult.connection_key),
        );
        if (validation.valid) {
          this.success.set(validation.message);
        } else {
          this.success.set(`Credentials saved. ${validation.message}`);
        }
      } catch {
        this.success.set('Credentials saved and encrypted.');
      }

      this.clientId = '';
      this.clientSecret = '';
      this.refreshToken = '';
      this.sandboxEnabled = false;
      this.showForm.set(false);
      this.saved.emit();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save credentials';
      this.error.set(msg);
    } finally {
      this.saving.set(false);
    }
  }
}
