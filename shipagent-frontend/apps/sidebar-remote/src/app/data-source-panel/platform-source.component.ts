/**
 * PlatformSourceComponent
 *
 * Shows connected external platform sources (Shopify, Amazon).
 * Allows switching the active data source to a platform connection.
 * Port of Shopify/Amazon card sections from React DataSourcePanel.tsx.
 */

import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  effect,
  inject,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { DataSourceStore, PlatformsStore } from '@shipagent/shared-state';
import { ShopifyIconComponent, AmazonIconComponent } from '@shipagent/shared-ui';

@Component({
  selector: 'sa-platform-source',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ShopifyIconComponent, AmazonIconComponent],
  template: `
    <div class="space-y-3">

      <!-- === SHOPIFY CARD === -->
      @if (shopifyAvailable()) {
        <div
          class="rounded-lg border overflow-hidden transition-colors"
          [class.border-l-4]="isShopifyActive()"
          [class.border-l-green-500]="isShopifyActive()"
          [class.border-green-500]="isShopifyActive()"
          [class.border-opacity-30]="isShopifyActive()"
          [class.border-slate-800]="!isShopifyActive()"
        >
          <div class="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div class="flex items-center gap-2">
              <sa-brand-shopify class="w-5 h-5 text-[#5BBF3D]" />
              <span class="text-xs font-medium text-slate-200">Shopify</span>
            </div>
            <div>
              @if (isShopifyActive()) {
                <span class="badge badge-success text-[9px]">ACTIVE</span>
              } @else {
                <span class="flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
                  <span class="text-[10px] font-mono text-slate-500">Available</span>
                </span>
              }
            </div>
          </div>

          @if (isShopifyActive()) {
            <div class="p-2.5 border-t border-green-500/20">
              <p class="text-xs text-slate-300">{{ shopifyDisplayName() }}</p>
              <p class="text-[10px] font-mono text-slate-500 mt-0.5">Connected</p>
            </div>
          } @else {
            <div class="p-2.5 border-t border-slate-800">
              <p class="text-[10px] text-slate-500 mb-2">{{ shopifyDisplayName() }}</p>
              <button
                class="w-full py-1.5 text-xs font-medium rounded border border-[#5BBF3D]/40 text-[#5BBF3D] hover:bg-[#5BBF3D]/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                [disabled]="isConnecting()"
                (click)="handleSwitchToShopify()"
              >
                @if (isConnecting()) { Activating... } @else { Use Shopify }
              </button>
            </div>
          }
        </div>
      } @else {
        <!-- Shopify not configured -->
        <div class="rounded-lg border border-slate-800 overflow-hidden">
          <div class="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div class="flex items-center gap-2">
              <sa-brand-shopify class="w-5 h-5 text-[#5BBF3D]/50" />
              <span class="text-xs font-medium text-slate-400">Shopify</span>
            </div>
            <span class="flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 rounded-full bg-slate-600"></span>
              <span class="text-[10px] font-mono text-slate-500">Not configured</span>
            </span>
          </div>
          <div class="p-2.5 border-t border-slate-800">
            <p class="text-[10px] font-medium text-[#96BF48] cursor-default">Connect Shopify in Settings</p>
          </div>
        </div>
      }

      <!-- === AMAZON CARD === -->
      @if (amazonAvailable()) {
        <div
          class="rounded-lg border overflow-hidden transition-colors"
          [class.border-l-4]="isAmazonActive()"
          [class.border-l-amber-500]="isAmazonActive()"
          [class.border-amber-500]="isAmazonActive()"
          [class.border-opacity-30]="isAmazonActive()"
          [class.border-slate-800]="!isAmazonActive()"
        >
          <div class="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div class="flex items-center gap-2">
              <sa-brand-amazon class="w-5 h-5 text-[#FF9900]" />
              <span class="text-xs font-medium text-slate-200">Amazon</span>
            </div>
            <div>
              @if (isAmazonActive()) {
                <span class="badge badge-success text-[9px]">ACTIVE</span>
              } @else {
                <span class="flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
                  <span class="text-[10px] font-mono text-slate-500">Available</span>
                </span>
              }
            </div>
          </div>

          @if (isAmazonActive()) {
            <div class="p-2.5 border-t border-amber-500/20">
              <p class="text-xs text-slate-300">{{ amazonDisplayName() }}</p>
              <p class="text-[10px] font-mono text-slate-500 mt-0.5">Connected</p>
            </div>
          } @else {
            <div class="p-2.5 border-t border-slate-800">
              <p class="text-[10px] text-slate-500 mb-2">{{ amazonDisplayName() }}</p>
              <button
                class="w-full py-1.5 text-xs font-medium rounded border border-[#FF9900]/40 text-[#FF9900] hover:bg-[#FF9900]/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                [disabled]="isConnecting()"
                (click)="handleSwitchToAmazon()"
              >
                @if (isConnecting()) { Activating... } @else { Use Amazon }
              </button>
            </div>
          }
        </div>
      } @else {
        <!-- Amazon not configured -->
        <div class="rounded-lg border border-slate-800 overflow-hidden">
          <div class="flex items-center justify-between p-2.5 bg-slate-800/30">
            <div class="flex items-center gap-2">
              <sa-brand-amazon class="w-5 h-5 text-[#FF9900]/50" />
              <span class="text-xs font-medium text-slate-400">Amazon</span>
            </div>
            <span class="flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 rounded-full bg-slate-600"></span>
              <span class="text-[10px] font-mono text-slate-500">Not configured</span>
            </span>
          </div>
          <div class="p-2.5 border-t border-slate-800">
            <p class="text-[10px] font-medium text-[#FF9900] cursor-default">Connect Amazon in Settings</p>
          </div>
        </div>
      }

      <!-- Error display -->
      @if (connectError()) {
        <p class="text-[10px] font-mono text-red-400 p-2 rounded bg-red-500/10">{{ connectError() }}</p>
      }
    </div>
  `,
})
export class PlatformSourceComponent implements OnInit {
  private readonly apiService = inject(ApiService);
  private readonly dataSourceStore = inject(DataSourceStore);
  private readonly platformsStore = inject(PlatformsStore);

  readonly isConnecting = signal(false);
  readonly connectError = signal<string | null>(null);

  constructor() {
    // Re-fetch when providerConnectionsVersion changes (settings flyout saved creds).
    // effect() must be in constructor (injection context), not ngOnInit.
    effect(() => {
      this.platformsStore.providerConnectionsVersion();
      this.fetchConnections();
    });
  }

  ngOnInit(): void {
    this.fetchConnections();
  }

  private fetchConnections(): void {
    this.apiService.listProviderConnections().subscribe({
      next: (connections) => {
        for (const conn of connections) {
          // Key by provider (e.g. 'shopify'), NOT connection_key
          // (e.g. 'shopify:matthansdev.myshopify.com') — components
          // look up connections()['shopify'], not the full key.
          const key = (conn as any).provider ?? conn.connection_key;
          this.platformsStore.setConnection(key, conn);
        }
      },
      error: (err) => console.warn('[PlatformSource] Failed to fetch connections:', err),
    });
  }

  /** Whether Shopify is configured and runtime-usable. */
  shopifyAvailable(): boolean {
    const conn = this.platformsStore.connections()['shopify'];
    return !!conn?.runtime_usable;
  }

  /** Whether Shopify is the active data source. */
  isShopifyActive(): boolean {
    return this.dataSourceStore.activeSourceType() === 'shopify';
  }

  /** Display name for Shopify connection. */
  shopifyDisplayName(): string {
    const conn = this.platformsStore.connections()['shopify'];
    return conn?.display_name ?? 'Shopify Store';
  }

  /** Whether Amazon is configured and runtime-usable. */
  amazonAvailable(): boolean {
    const conn = this.platformsStore.connections()['amazon'];
    return !!conn?.runtime_usable;
  }

  /** Whether Amazon is the active data source. */
  isAmazonActive(): boolean {
    return this.dataSourceStore.activeSourceType() === 'amazon';
  }

  /** Display name for Amazon connection. */
  amazonDisplayName(): string {
    const conn = this.platformsStore.connections()['amazon'];
    return conn?.display_name ?? 'Amazon Seller';
  }

  /**
   * Activate Shopify as the data source.
   * Calls POST /platforms/shopify/activate — connects, fetches orders,
   * and imports them as a data source in one call.
   * Matches React: activateShopify() in api.ts.
   */
  async handleSwitchToShopify(): Promise<void> {
    this.connectError.set(null);
    this.isConnecting.set(true);
    try {
      const result = await firstValueFrom(this.apiService.activateShopify());
      if (!result.success) {
        this.connectError.set(result.error ?? 'Failed to activate Shopify');
        return;
      }
      // Cache local config before clearing
      const current = this.dataSourceStore.dataSource();
      if (current) {
        this.dataSourceStore.setCachedLocalConfig({
          type: current.type as 'csv' | 'excel' | 'database',
          file_path: current.csv_path ?? current.excel_path,
        });
      }
      this.dataSourceStore.setDataSource(null);
      this.dataSourceStore.setActiveSourceType('shopify');
      this.dataSourceStore.setActiveSourceInfo(
        this.shopifyDisplayName() || 'Shopify',
      );
    } catch (err) {
      this.connectError.set(err instanceof Error ? err.message : 'Failed to activate Shopify');
    } finally {
      this.isConnecting.set(false);
    }
  }

  /** Switch the active data source to Amazon. */
  async handleSwitchToAmazon(): Promise<void> {
    this.connectError.set(null);
    this.isConnecting.set(true);
    try {
      const result = await firstValueFrom(this.apiService.activateAmazon());
      if (!result.success) {
        this.connectError.set(result.error ?? 'Failed to activate Amazon');
        return;
      }
      const current = this.dataSourceStore.dataSource();
      if (current) {
        this.dataSourceStore.setCachedLocalConfig({
          type: current.type as 'csv' | 'excel' | 'database',
          file_path: current.csv_path ?? current.excel_path,
        });
      }
      this.dataSourceStore.setDataSource(null);
      this.dataSourceStore.setActiveSourceType('amazon');
      this.dataSourceStore.setActiveSourceInfo('Amazon');
    } catch (err) {
      this.connectError.set(err instanceof Error ? err.message : 'Failed to activate Amazon');
    } finally {
      this.isConnecting.set(false);
    }
  }
}
