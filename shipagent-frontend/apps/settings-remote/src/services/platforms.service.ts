/**
 * PlatformsService — External platform connection management.
 *
 * Angular port of useExternalSources.ts React hook.
 * Component-scoped in settings-remote (do not provide in root).
 *
 * Manages platform connections for Shopify, Amazon, UPS, WooCommerce.
 * Updates PlatformsStore on all state changes.
 */

import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import { PlatformsStore } from '@shipagent/shared-state';
import type {
  PlatformType,
  ProviderConnectionInfo,
  ShopifyEnvStatus,
  AmazonEnvStatus,
} from '@shipagent/shared-types';

@Injectable()
export class PlatformsService {
  private readonly apiService = inject(ApiService);
  private readonly platformsStore = inject(PlatformsStore);

  /**
   * Connect to a platform with the given credentials.
   * Updates PlatformsStore on success.
   */
  async connectPlatform(
    platform: PlatformType,
    credentials: Record<string, unknown>,
    storeUrl?: string,
  ): Promise<boolean> {
    try {
      const response = await firstValueFrom(
        this.apiService.connectPlatform(platform, credentials, storeUrl),
      );
      if (response.success) {
        await this.refreshConnections();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }

  /**
   * Disconnect from a platform.
   * Removes platform from PlatformsStore.
   */
  async disconnectPlatform(platform: PlatformType): Promise<boolean> {
    try {
      await firstValueFrom(this.apiService.disconnectPlatform(platform));
      this.platformsStore.removeConnection(platform);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Test a platform connection.
   */
  async testConnection(platform: PlatformType): Promise<boolean> {
    try {
      const result = await firstValueFrom(
        this.apiService.testPlatformConnection(platform),
      );
      return result.success;
    } catch {
      return false;
    }
  }

  /**
   * Fetch orders from a platform.
   */
  async fetchOrders(
    platform: PlatformType,
    filters?: { status?: string; limit?: number; offset?: number },
  ): Promise<unknown[]> {
    try {
      const response = await firstValueFrom(
        this.apiService.getPlatformOrders(platform, filters),
      );
      return response.orders ?? [];
    } catch {
      return [];
    }
  }

  /**
   * Check Shopify environment status (auto-reconnect after restart).
   */
  async checkShopifyEnv(): Promise<ShopifyEnvStatus | null> {
    try {
      const status = await firstValueFrom(
        this.apiService.getPlatformEnvStatus('shopify'),
      );
      if (status.valid && status.store_url) {
        // Update store with the detected connection
        const connection: ProviderConnectionInfo = {
          id: 'shopify',
          connection_key: 'shopify',
          provider: 'shopify',
          display_name: status.store_name ?? status.store_url ?? 'Shopify',
          auth_mode: 'legacy_token',
          environment: null,
          status: 'connected',
          metadata: {},
          last_validated_at: new Date().toISOString(),
          last_error_code: null,
          error_message: null,
          runtime_usable: true,
          runtime_reason: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        this.platformsStore.setConnection('shopify', connection);
      }
      return status as ShopifyEnvStatus;
    } catch {
      return null;
    }
  }

  /**
   * Check Amazon environment status (auto-reconnect after restart).
   */
  async checkAmazonEnv(): Promise<AmazonEnvStatus | null> {
    try {
      const status = await firstValueFrom(
        this.apiService.getPlatformEnvStatus('amazon'),
      );
      if (status.valid) {
        const connection: ProviderConnectionInfo = {
          id: 'amazon',
          connection_key: 'amazon',
          provider: 'amazon',
          display_name: (status as AmazonEnvStatus).seller_name ?? 'Amazon',
          auth_mode: 'sp_api',
          environment: null,
          status: 'connected',
          metadata: {},
          last_validated_at: new Date().toISOString(),
          last_error_code: null,
          error_message: null,
          runtime_usable: true,
          runtime_reason: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        this.platformsStore.setConnection('amazon', connection);
      }
      return status as AmazonEnvStatus;
    } catch {
      return null;
    }
  }

  /**
   * Refresh all platform connection statuses from the backend.
   * Updates PlatformsStore with the latest state.
   */
  async refreshConnections(): Promise<void> {
    try {
      const response = await firstValueFrom(
        this.apiService.listProviderConnections(),
      );
      // Reset and re-populate store
      for (const conn of response) {
        this.platformsStore.setConnection(conn.connection_key, conn);
      }
      this.platformsStore.incrementProviderConnectionsVersion();
    } catch {
      // Non-fatal: store keeps existing state
    }
  }

  /**
   * Save provider credentials and auto-validate.
   * Returns the connection key on success.
   */
  async saveProviderCredentials(
    provider: string,
    payload: {
      auth_mode: string;
      credentials: Record<string, string>;
      metadata: Record<string, unknown>;
      display_name: string;
      environment?: string;
    },
  ): Promise<{ connection_key: string; is_new: boolean } | null> {
    try {
      const result = await firstValueFrom(
        this.apiService.saveProviderCredentials(provider, payload as any),
      );
      await this.refreshConnections();
      return result;
    } catch {
      return null;
    }
  }

  /**
   * Validate saved provider credentials against the real provider API.
   */
  async validateProviderConnection(connectionKey: string): Promise<{
    valid: boolean;
    message: string;
  } | null> {
    try {
      const result = await firstValueFrom(
        this.apiService.validateProviderConnection(connectionKey),
      );
      return { valid: result.valid, message: result.message };
    } catch {
      return null;
    }
  }

  /**
   * Delete a provider connection permanently.
   */
  async deleteProviderConnection(connectionKey: string): Promise<boolean> {
    try {
      await firstValueFrom(
        this.apiService.deleteProviderConnection(connectionKey),
      );
      this.platformsStore.removeConnection(connectionKey);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Disconnect a provider connection (preserves credentials).
   */
  async disconnectProviderConnection(connectionKey: string): Promise<boolean> {
    try {
      const result = await firstValueFrom(
        this.apiService.disconnectProvider(connectionKey),
      );
      this.platformsStore.setConnection(connectionKey, result);
      return true;
    } catch {
      return false;
    }
  }
}
