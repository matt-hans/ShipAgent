/**
 * ConnectionsSectionComponent — Settings accordion section for provider connections.
 *
 * Port of ConnectionsSection.tsx React component.
 * Renders model-provider credentials plus UPS, Shopify, and Amazon connections.
 * Reads credential and connection state from SettingsStore and PlatformsStore.
 */

import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnInit,
  Output,
  EventEmitter,
  inject,
  signal,
  computed,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { SettingsStore, PlatformsStore } from '@shipagent/shared-state';
import { PlatformsService } from '../../services/platforms.service';
import { ProviderCardComponent } from './provider-card.component';
import { AnthropicKeyFormComponent } from './anthropic-key-form.component';
import { ShopifyConnectFormComponent } from './shopify-connect-form.component';
import { AmazonConnectFormComponent } from './amazon-connect-form.component';
import { UpsConnectFormComponent } from './ups-connect-form.component';
import type { ProviderConnectionInfo } from '@shipagent/shared-types';

@Component({
  selector: 'app-connections-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ProviderCardComponent,
    AnthropicKeyFormComponent,
    ShopifyConnectFormComponent,
    AmazonConnectFormComponent,
    UpsConnectFormComponent,
  ],
  template: `
    <div class="settings-section">
      <!-- Section header -->
      <button
        class="settings-section-header"
        (click)="toggled.emit()"
        [attr.aria-expanded]="isOpen"
      >
        <div class="flex items-center gap-2">
          <!-- Plug icon -->
          <svg class="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 6L6 18"></path><path d="M6 6l12 12"></path>
          </svg>
          <span class="font-medium text-foreground">Connections</span>
          @if (totalConfigured() > 0) {
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-success/15 text-success border border-success/30">
              {{ totalConfigured() }} active
            </span>
          }
          @if (connectionsLoading()) {
            <span class="block w-3 h-3 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin"></span>
          }
        </div>
        <!-- Chevron -->
        <svg
          class="h-4 w-4 text-muted-foreground transition-transform"
          [class.rotate-180]="isOpen"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      @if (isOpen) {
        <div class="settings-section-content space-y-2">

          <!-- Model provider API keys -->
          <div class="rounded-lg border border-border overflow-hidden">
            <button
              class="w-full flex items-center justify-between px-3 py-2.5 hover:bg-muted/30 transition-colors"
              (click)="toggleProvider('model-providers')"
            >
              <div class="flex items-center gap-2">
                <!-- Key icon -->
                <svg class="h-4 w-4 text-[#D97706]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"></path>
                </svg>
                <span class="text-xs font-medium text-foreground">Model Providers</span>
                @if (configuredModelProviderCount() > 0) {
                  <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-success/15 text-success border border-success/30">
                    {{ configuredModelProviderCount() }} configured
                  </span>
                } @else {
                  <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-warning/15 text-warning border border-warning/30">
                    Not configured
                  </span>
                }
              </div>
              <svg
                class="h-3.5 w-3.5 text-muted-foreground transition-transform"
                [class.rotate-180]="openProvider() === 'model-providers'"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round"
              >
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
            @if (openProvider() === 'model-providers') {
              <div class="px-3 pb-3 border-t border-border">
                <app-anthropic-key-form
                  (saved)="onCredentialSaved()"
                />
              </div>
            }
          </div>

          <!-- UPS Provider -->
          <app-provider-card
            providerName="UPS"
            [connections]="upsConnections()"
            [isOpen]="openProvider() === 'ups'"
            [activeEnvironment]="activeUpsEnv()"
            (toggled)="toggleProvider('ups')"
            (deleteRequest)="handleDelete($event)"
            (disconnectRequest)="handleDisconnect($event)"
            (validated)="refreshConnections()"
          >
            <ng-container slot="icon">
              <!-- UPS shield icon -->
              <svg class="h-4 w-4 text-[#FFB500]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
              </svg>
            </ng-container>

            <!-- UPS environment toggle (shown when connected) -->
            @if (upsConnections().some(isConnected)) {
              <div class="space-y-1.5">
                <label class="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  Active Environment
                </label>
                <div class="flex gap-1.5">
                  @for (env of ['test', 'production']; track env) {
                    <button
                      (click)="handleEnvSwitch(env)"
                      [disabled]="envSwitching()"
                      class="flex-1 text-xs py-1.5 px-2 rounded-md border transition-colors"
                      [class]="getEnvButtonClass(env)"
                    >
                      {{ env === 'test' ? 'Test (CIE)' : 'Production' }}
                      @if (isActiveEnv(env)) {
                        <span class="ml-1 text-[9px]">
                          {{ envSwitching() ? '...' : '(active)' }}
                        </span>
                      }
                    </button>
                  }
                </div>
                <p class="text-[10px] text-muted-foreground">
                  Same credentials, different API endpoints. New conversations use the selected environment.
                </p>
              </div>
            }
            <app-ups-connect-form
              [existingConnections]="upsConnections()"
              (saved)="refreshConnections()"
            />
          </app-provider-card>

          <!-- Shopify Provider -->
          <app-provider-card
            providerName="Shopify"
            [connections]="shopifyConnections()"
            [isOpen]="openProvider() === 'shopify'"
            (toggled)="toggleProvider('shopify')"
            (deleteRequest)="handleDelete($event)"
            (disconnectRequest)="handleDisconnect($event)"
            (validated)="refreshConnections()"
          >
            <ng-container slot="icon">
              <!-- Shopify icon (green S) -->
              <svg class="h-4 w-4 text-[#5BBF3D]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
              </svg>
            </ng-container>
            <app-shopify-connect-form
              [existingConnection]="shopifyConnections()[0] ?? null"
              (saved)="refreshConnections()"
            />
          </app-provider-card>

          <!-- Amazon Provider -->
          <app-provider-card
            providerName="Amazon"
            [connections]="amazonConnections()"
            [isOpen]="openProvider() === 'amazon'"
            (toggled)="toggleProvider('amazon')"
            (deleteRequest)="handleDelete($event)"
            (disconnectRequest)="handleDisconnect($event)"
            (validated)="refreshConnections()"
          >
            <ng-container slot="icon">
              <!-- Amazon icon -->
              <svg class="h-4 w-4 text-[#FF9900]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="16"></line>
                <line x1="8" y1="12" x2="16" y2="12"></line>
              </svg>
            </ng-container>
            <app-amazon-connect-form
              [existingConnection]="amazonConnections()[0] ?? null"
              (saved)="refreshConnections()"
            />
          </app-provider-card>

        </div>
      }
    </div>
  `,
})
export class ConnectionsSectionComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly settingsStore = inject(SettingsStore);
  private readonly platformsStore = inject(PlatformsStore);
  private readonly platformsService = inject(PlatformsService);

  @Input() isOpen = false;
  @Output() toggled = new EventEmitter<void>();

  openProvider = signal<string | null>(null);
  connectionsLoading = signal(false);
  envSwitching = signal(false);

  // Computed from SettingsStore
  credentialStatus = this.settingsStore.credentialStatus;
  appSettings = this.settingsStore.appSettings;

  // Computed connection lists from PlatformsStore
  allConnections = computed(() => Object.values(this.platformsStore.connections()));

  upsConnections = computed(() =>
    this.allConnections().filter((c: ProviderConnectionInfo) => c.provider === 'ups'),
  );

  shopifyConnections = computed(() =>
    this.allConnections().filter((c: ProviderConnectionInfo) => c.provider === 'shopify'),
  );

  amazonConnections = computed(() =>
    this.allConnections().filter((c: ProviderConnectionInfo) => c.provider === 'amazon'),
  );

  activeUpsEnv = computed(() => {
    const settings = this.settingsStore.appSettings();
    return (settings?.ups_environment as 'test' | 'production' | null) ?? null;
  });

  totalConfigured = computed(() => {
    const platformsConfigured = this.allConnections().filter(
      (c: ProviderConnectionInfo) => c.status !== 'disconnected',
    ).length;
    return platformsConfigured + this.configuredModelProviderCount();
  });

  ngOnInit(): void {
    this.loadInitialState();
  }

  private async loadInitialState(): Promise<void> {
    this.connectionsLoading.set(true);
    try {
      await Promise.all([
        this.refreshConnections(),
        firstValueFrom(this.apiService.getCredentialStatus()).then((status) =>
          this.settingsStore.setCredentialStatus(status),
        ),
      ]);
    } catch {
      // Non-critical load failure — keep existing state
    } finally {
      this.connectionsLoading.set(false);
    }
  }

  async refreshConnections(): Promise<void> {
    await this.platformsService.refreshConnections();
    // Also refresh settings to get latest ups_environment
    try {
      const settings = await firstValueFrom(this.apiService.getSettings());
      this.settingsStore.setAppSettings(settings);
    } catch {
      /* non-critical */
    }
  }

  toggleProvider(provider: string): void {
    this.openProvider.update((current) => (current === provider ? null : provider));
  }

  async handleDelete(connectionKey: string): Promise<void> {
    await this.platformsService.deleteProviderConnection(connectionKey);
    await this.refreshConnections();
  }

  async handleDisconnect(connectionKey: string): Promise<void> {
    await this.platformsService.disconnectProviderConnection(connectionKey);
    await this.refreshConnections();
  }

  async handleEnvSwitch(env: string): Promise<void> {
    const currentEnv = this.activeUpsEnv();
    if (env === currentEnv || this.envSwitching()) return;
    this.envSwitching.set(true);
    try {
      await firstValueFrom(this.apiService.patchSettings({ ups_environment: env }));
      const settings = await firstValueFrom(this.apiService.getSettings());
      this.settingsStore.setAppSettings(settings);
    } finally {
      this.envSwitching.set(false);
    }
  }

  isConnected(conn: ProviderConnectionInfo): boolean {
    return conn.status === 'connected';
  }

  isActiveEnv(env: string): boolean {
    const active = this.activeUpsEnv();
    return active === env || (!active && env === 'production');
  }

  getEnvButtonClass(env: string): string {
    const isActive = this.isActiveEnv(env);
    const isSwitching = this.envSwitching();
    const activeClasses = env === 'production'
      ? 'bg-success/10 border-success/40 text-success font-medium'
      : 'bg-info/10 border-info/40 text-info font-medium';
    const inactiveClasses = 'border-border text-muted-foreground hover:bg-muted/50';
    const disabledClasses = isSwitching ? ' opacity-50 cursor-not-allowed' : '';
    return (isActive ? activeClasses : inactiveClasses) + disabledClasses;
  }

  onCredentialSaved(): void {
    // Refresh credential status after saving a model provider key.
    firstValueFrom(this.apiService.getCredentialStatus())
      .then((status) => this.settingsStore.setCredentialStatus(status))
      .catch(() => { /* non-critical */ });
  }

  configuredModelProviderCount(): number {
    const status = this.settingsStore.credentialStatus();
    if (!status) return 0;
    return [
      status.anthropic_api_key,
      status.openai_api_key,
      status.gemini_api_key,
    ].filter(Boolean).length;
  }
}
