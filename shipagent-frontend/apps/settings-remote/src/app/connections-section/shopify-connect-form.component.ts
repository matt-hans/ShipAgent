/**
 * ShopifyConnectFormComponent — Credential form for Shopify provider.
 *
 * Port of ShopifyConnectForm.tsx React component.
 * Store domain + access token. Auto-validates after save.
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

/** Normalize a Shopify domain to bare hostname. */
function normalizeDomain(raw: string): string {
  let d = raw.trim();
  d = d.replace(/^https?:\/\//, '');
  d = d.replace(/\/+$/, '');
  return d;
}

/** Validate domain looks like *.myshopify.com. */
function isValidDomain(domain: string): boolean {
  return /^[\w-]+\.myshopify\.com$/.test(normalizeDomain(domain));
}

@Component({
  selector: 'app-shopify-connect-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    @if (!showForm()) {
      <button
        (click)="showForm.set(true)"
        class="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        {{ existingConnection ? '+ Replace credentials' : '+ Connect Shopify' }}
      </button>
    } @else {
      <div class="space-y-3 pt-1">
        @if (existingConnection) {
          <p class="text-[10px] text-warning">
            Saving will replace the existing Shopify credentials.
          </p>
        }

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground">Store Domain</label>
          <input
            type="text"
            [(ngModel)]="storeDomain"
            (blur)="onDomainBlur()"
            placeholder="your-store.myshopify.com"
            class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
          @if (domainError()) {
            <p class="text-[10px] text-destructive">{{ domainError() }}</p>
          }
        </div>

        <div class="space-y-1">
          <label class="text-[11px] font-medium text-muted-foreground">Admin API Access Token</label>
          <input
            type="password"
            [(ngModel)]="accessToken"
            placeholder="shpat_..."
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

        <div class="flex gap-2">
          <button
            (click)="onSave()"
            [disabled]="saving() || !storeDomain.trim() || !accessToken.trim()"
            class="flex-1 text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
          >
            @if (saving()) {
              <span class="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin"></span>
            }
            {{ saving() ? 'Saving & Validating...' : (existingConnection ? 'Replace Credentials' : 'Save & Validate') }}
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
export class ShopifyConnectFormComponent {
  private readonly apiService = inject(ApiService);

  @Input() existingConnection: ProviderConnectionInfo | null = null;
  @Output() saved = new EventEmitter<void>();

  showForm = signal(false);
  storeDomain = '';
  accessToken = '';
  domainError = signal<string | null>(null);
  saving = signal(false);
  error = signal<string | null>(null);
  success = signal<string | null>(null);

  onDomainBlur(): void {
    if (this.storeDomain.trim() && !isValidDomain(this.storeDomain)) {
      this.domainError.set('Domain must be in the format store-name.myshopify.com');
    } else {
      this.domainError.set(null);
    }
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.error.set(null);
    this.success.set(null);
    this.domainError.set(null);
  }

  async onSave(): Promise<void> {
    const normalized = normalizeDomain(this.storeDomain);
    if (!isValidDomain(this.storeDomain)) {
      this.domainError.set('Domain must be in the format store-name.myshopify.com');
      return;
    }
    if (!this.accessToken.trim()) {
      this.error.set('Access token is required.');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    this.success.set(null);
    try {
      const saveResult = await firstValueFrom(
        this.apiService.saveProviderCredentials('shopify', {
          auth_mode: 'legacy_token',
          credentials: { access_token: this.accessToken.trim() },
          metadata: { store_domain: normalized },
          display_name: normalized,
        }),
      );

      const validation = await firstValueFrom(
        this.apiService.validateProviderConnection(saveResult.connection_key),
      );

      if (validation.valid) {
        this.success.set(validation.message);
        this.storeDomain = '';
        this.accessToken = '';
        this.showForm.set(false);
      } else {
        this.error.set(validation.message);
      }
      this.saved.emit();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save credentials';
      this.error.set(msg);
    } finally {
      this.saving.set(false);
    }
  }
}
