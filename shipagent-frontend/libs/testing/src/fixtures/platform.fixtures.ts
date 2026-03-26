/**
 * Platform connection test fixtures.
 */

import type {
  PlatformConnection,
  ListConnectionsResponse,
  ProviderConnectionInfo,
} from '@shipagent/shared-types';

export const platformFixtures = {
  /** Shopify connection (connected). */
  shopifyConnected: (): PlatformConnection => ({
    platform: 'shopify',
    store_url: 'mystore.myshopify.com',
    status: 'connected',
    last_connected: '2026-03-24T09:00:00Z',
    error_message: null,
  }),

  /** Shopify connection (disconnected). */
  shopifyDisconnected: (): PlatformConnection => ({
    platform: 'shopify',
    store_url: null,
    status: 'disconnected',
    last_connected: null,
    error_message: null,
  }),

  /** Amazon connection (connected). */
  amazonConnected: (): PlatformConnection => ({
    platform: 'amazon',
    store_url: 'amazon.com',
    status: 'connected',
    last_connected: '2026-03-24T08:00:00Z',
    error_message: null,
  }),

  /** WooCommerce connection (error state). */
  wooCommerceError: (): PlatformConnection => ({
    platform: 'woocommerce',
    store_url: 'myshop.com',
    status: 'error',
    last_connected: '2026-03-20T12:00:00Z',
    error_message: 'Invalid consumer key',
  }),

  /** List connections response with all platforms. */
  listConnectionsResponse: (): ListConnectionsResponse => ({
    connections: [
      {
        platform: 'shopify',
        store_url: 'mystore.myshopify.com',
        status: 'connected',
        last_connected: '2026-03-24T09:00:00Z',
        error_message: null,
      },
      {
        platform: 'amazon',
        store_url: null,
        status: 'disconnected',
        last_connected: null,
        error_message: null,
      },
    ],
    count: 2,
  }),

  /** UPS provider connection info (configured). */
  upsProviderConnection: (): ProviderConnectionInfo => ({
    id: 'conn-ups-001',
    connection_key: 'ups:sandbox:default',
    provider: 'ups',
    display_name: 'UPS (Sandbox)',
    auth_mode: 'client_credentials',
    environment: 'sandbox',
    status: 'configured',
    metadata: {},
    last_validated_at: '2026-03-24T08:00:00Z',
    last_error_code: null,
    error_message: null,
    runtime_usable: true,
    runtime_reason: null,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-24T08:00:00Z',
  }),

  /** Shopify provider connection info (configured). */
  shopifyProviderConnection: (): ProviderConnectionInfo => ({
    id: 'conn-shopify-001',
    connection_key: 'shopify:production:default',
    provider: 'shopify',
    display_name: 'Shopify (My Store)',
    auth_mode: 'legacy_token',
    environment: 'production',
    status: 'configured',
    metadata: { store_url: 'mystore.myshopify.com' },
    last_validated_at: '2026-03-24T09:00:00Z',
    last_error_code: null,
    error_message: null,
    runtime_usable: true,
    runtime_reason: null,
    created_at: '2026-03-10T00:00:00Z',
    updated_at: '2026-03-24T09:00:00Z',
  }),

  /** Amazon provider connection info (needs reconnect). */
  amazonProviderConnection: (): ProviderConnectionInfo => ({
    id: 'conn-amazon-001',
    connection_key: 'amazon:production:default',
    provider: 'amazon',
    display_name: 'Amazon SP-API',
    auth_mode: 'sp_api',
    environment: 'production',
    status: 'needs_reconnect',
    metadata: { marketplace_id: 'ATVPDKIKX0DER' },
    last_validated_at: '2026-02-01T00:00:00Z',
    last_error_code: 'E-5001',
    error_message: 'Refresh token expired',
    runtime_usable: false,
    runtime_reason: 'Token refresh required',
    created_at: '2026-02-01T00:00:00Z',
    updated_at: '2026-03-20T00:00:00Z',
  }),
};
