/**
 * UpsConnectFormComponent — Credential form for UPS provider connections.
 *
 * Port of UPSConnectForm.tsx React component.
 * Fields: Client ID, Client Secret, Account Number (optional).
 * Environment toggle: Test (CIE) / Production.
 * Auto-validates after save via PlatformsService.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import type { ProviderConnectionInfo } from '@shipagent/shared-types';

type UPSEnvironment = 'test' | 'production';

@Component({
  selector: 'app-ups-connect-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    @if (!showForm()) {
      <button
        (click)="showForm.set(true)"
        class="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        {{ existingConnections.length > 0 ? '+ Add or replace credentials' : '+ Connect UPS' }}
      </button>
    } @else {
      <div class="space-y-3 pt-1">
        <!-- Environment toggle -->
        <div class="space-y-1.5">
          <label class="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            Environment
          </label>
          <div class="flex gap-1.5">
            @for (env of environments; track env) {
              <button
                (click)="environment.set(env)"
                class="flex-1 text-xs py-1.5 px-2 rounded-md border transition-colors"
                [class]="environment() === env
                  ? (env === 'production'
                      ? 'bg-success/10 border-success/30 text-success'
                      : 'bg-info/10 border-info/30 text-info')
                  : 'border-border text-muted-foreground hover:bg-muted/50'"
              >
                {{ env === 'test' ? 'Test (CIE)' : 'Production' }}
                @if (hasExistingForEnv(env) && environment() !== env) {
                  <span class="ml-1 text-[9px] opacity-60">●</span>
                }
              </button>
            }
          </div>
        </div>

        @if (environment()) {
          @if (existingForEnv()) {
            <p class="text-[10px] text-warning">
              Saving will replace the existing {{ environment() }} credentials.
            </p>
          }

          <div class="space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground">Client ID</label>
            <input
              type="text"
              [(ngModel)]="clientId"
              placeholder="Enter UPS Client ID"
              class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>

          <div class="space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground">Client Secret</label>
            <input
              type="password"
              [(ngModel)]="clientSecret"
              placeholder="Enter UPS Client Secret"
              class="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>

          <div class="space-y-1">
            <label class="text-[11px] font-medium text-muted-foreground">
              Account Number <span class="text-muted-foreground/50">(optional)</span>
            </label>
            <input
              type="text"
              [(ngModel)]="accountNumber"
              placeholder="6-digit UPS account number"
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
              [disabled]="saving() || !clientId.trim() || !clientSecret.trim()"
              class="flex-1 text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
            >
              @if (saving()) {
                <span class="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin"></span>
              }
              {{ saving() ? 'Saving & Validating...' : (existingForEnv() ? 'Replace Credentials' : 'Save & Validate') }}
            </button>
            <button
              (click)="cancelForm()"
              class="text-xs py-1.5 px-3 rounded-md border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
            >
              Cancel
            </button>
          </div>
        }
      </div>
    }
  `,
})
export class UpsConnectFormComponent implements OnChanges {
  private readonly apiService = inject(ApiService);

  @Input() existingConnections: ProviderConnectionInfo[] = [];
  @Output() saved = new EventEmitter<void>();

  environments: UPSEnvironment[] = ['test', 'production'];

  showForm = signal(false);
  environment = signal<UPSEnvironment | null>(null);
  clientId = '';
  clientSecret = '';
  accountNumber = '';
  saving = signal(false);
  error = signal<string | null>(null);
  success = signal<string | null>(null);

  ngOnChanges(): void {
    // Reset form when existingConnections changes (e.g., after save)
    if (this.existingConnections.length === 0 && !this.showForm()) {
      this.showForm.set(false);
    }
  }

  existingForEnv(): ProviderConnectionInfo | undefined {
    const env = this.environment();
    return env
      ? this.existingConnections.find((c) => c.environment === env)
      : undefined;
  }

  hasExistingForEnv(env: string): boolean {
    return this.existingConnections.some((c) => c.environment === env);
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.error.set(null);
    this.success.set(null);
    this.environment.set(null);
  }

  async onSave(): Promise<void> {
    const env = this.environment();
    if (!env) {
      this.error.set('Select an environment (Test or Production).');
      return;
    }
    if (!this.clientId.trim() || !this.clientSecret.trim()) {
      this.error.set('Client ID and Client Secret are required.');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    this.success.set(null);
    try {
      const credentials: Record<string, string> = {
        client_id: this.clientId.trim(),
        client_secret: this.clientSecret.trim(),
      };
      if (this.accountNumber.trim()) {
        credentials['account_number'] = this.accountNumber.trim();
      }

      const saveResult = await firstValueFrom(
        this.apiService.saveProviderCredentials('ups', {
          auth_mode: 'client_credentials',
          credentials,
          metadata: this.accountNumber.trim()
            ? { account_number: this.accountNumber.trim() }
            : {},
          display_name: `UPS ${env === 'test' ? 'Test (CIE)' : 'Production'}`,
          environment: env,
        }),
      );

      // Auto-validate
      const validation = await firstValueFrom(
        this.apiService.validateProviderConnection(saveResult.connection_key),
      );

      if (validation.valid) {
        // Auto-set active environment when saving the first connection
        const otherEnvConnected = this.existingConnections.some(
          (c) => c.environment !== env && c.status === 'connected',
        );
        if (!otherEnvConnected) {
          try {
            await firstValueFrom(
              this.apiService.patchSettings({ ups_environment: env }),
            );
          } catch {
            /* non-critical */
          }
        }
        this.success.set(validation.message);
        this.clientId = '';
        this.clientSecret = '';
        this.accountNumber = '';
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
