/**
 * React hook for managing external platform connections.
 *
 * Provides state management and API interactions for connecting to
 * external platforms (Shopify, WooCommerce, SAP, Oracle).
 */

import { useState, useEffect, useCallback } from 'react';
import {
  listConnections,
  connectPlatform,
  disconnectPlatform,
  testConnection,
  listPlatformOrders,
  getShopifyEnvStatus,
} from '@/lib/api';
import type {
  PlatformConnection,
  PlatformType,
  ExternalOrder,
  ConnectionStatus,
  ShopifyEnvStatus,
} from '@/types/api';

/** State for a single platform. */
export interface PlatformState {
  connection: PlatformConnection | null;
  isConnecting: boolean;
  isDisconnecting: boolean;
  isTesting: boolean;
  error: string | null;
  orders: ExternalOrder[];
  isLoadingOrders: boolean;
  ordersError: string | null;
}

/** Initial state for a platform. */
const initialPlatformState: PlatformState = {
  connection: null,
  isConnecting: false,
  isDisconnecting: false,
  isTesting: false,
  error: null,
  orders: [],
  isLoadingOrders: false,
  ordersError: null,
};

/** Global state for all platforms. */
export interface ExternalSourcesState {
  platforms: Record<PlatformType, PlatformState>;
  isLoading: boolean;
  error: string | null;
  /** Shopify environment status (auto-detected credentials). */
  shopifyEnvStatus: ShopifyEnvStatus | null;
  /** True while checking Shopify environment status. */
  isCheckingEnv: boolean;
}

/** Hook return type. */
export interface UseExternalSourcesReturn {
  /** Current state of all platforms. */
  state: ExternalSourcesState;

  /** Connect to a platform. */
  connect: (
    platform: PlatformType,
    credentials: Record<string, unknown>,
    storeUrl?: string
  ) => Promise<boolean>;

  /** Disconnect from a platform. */
  disconnect: (platform: PlatformType) => Promise<boolean>;

  /** Test a platform connection. */
  test: (platform: PlatformType) => Promise<boolean>;

  /** Fetch orders from a platform. */
  fetchOrders: (
    platform: PlatformType,
    filters?: {
      status?: string;
      limit?: number;
      offset?: number;
    }
  ) => Promise<ExternalOrder[]>;

  /** Refresh all connections. */
  refresh: () => Promise<void>;

  /** Get connection status for a platform. */
  getConnectionStatus: (platform: PlatformType) => ConnectionStatus | 'disconnected';

  /** Check if a platform is connected. */
  isConnected: (platform: PlatformType) => boolean;

  /** Check Shopify environment status. */
  checkShopifyEnv: () => Promise<ShopifyEnvStatus | null>;
}

/** All supported platforms. */
const ALL_PLATFORMS: PlatformType[] = ['shopify', 'woocommerce', 'sap', 'oracle'];

/** Initial state for all platforms (constant, created once). */
const INITIAL_PLATFORMS: Record<PlatformType, PlatformState> = ALL_PLATFORMS.reduce(
  (acc, platform) => ({
    ...acc,
    [platform]: { ...initialPlatformState },
  }),
  {} as Record<PlatformType, PlatformState>
);

/**
 * Hook for managing external platform connections.
 *
 * Provides state management, connection handling, and order fetching
 * for all supported external platforms.
 *
 * @example
 * ```tsx
 * function ConnectionsPanel() {
 *   const {
 *     state,
 *     connect,
 *     disconnect,
 *     isConnected,
 *   } = useExternalSources();
 *
 *   const handleConnect = async () => {
 *     const success = await connect('shopify', {
 *       access_token: 'shpat_...',
 *     }, 'mystore.myshopify.com');
 *
 *     if (success) {
 *       console.log('Connected!');
 *     }
 *   };
 *
 *   return (
 *     <div>
 *       <button onClick={handleConnect}>
 *         {isConnected('shopify') ? 'Connected' : 'Connect'}
 *       </button>
 *     </div>
 *   );
 * }
 * ```
 */
export function useExternalSources(): UseExternalSourcesReturn {
  const [state, setState] = useState<ExternalSourcesState>({
    platforms: INITIAL_PLATFORMS,
    isLoading: true,
    error: null,
    shopifyEnvStatus: null,
    isCheckingEnv: false,
  });

  // Helper to update a single platform's state
  const updatePlatformState = useCallback(
    (platform: PlatformType, update: Partial<PlatformState>) => {
      setState((prev) => ({
        ...prev,
        platforms: {
          ...prev.platforms,
          [platform]: {
            ...prev.platforms[platform],
            ...update,
          },
        },
      }));
    },
    []
  );

  // Load initial connections
  const refresh = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await listConnections();

      // Reset all platforms first
      const newPlatforms: Record<PlatformType, PlatformState> = {
        shopify: { ...initialPlatformState },
        woocommerce: { ...initialPlatformState },
        sap: { ...initialPlatformState },
        oracle: { ...initialPlatformState },
      };

      // Update with actual connections
      for (const connection of response.connections) {
        const platform = connection.platform as PlatformType;
        if (platform in newPlatforms) {
          newPlatforms[platform] = {
            ...initialPlatformState,
            connection,
          };
        }
      }

      setState((prev) => ({
        ...prev,
        platforms: newPlatforms,
        isLoading: false,
        error: null,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to load connections',
      }));
    }
  }, []);

  // Load connections on mount
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Connect to a platform
  const connect = useCallback(
    async (
      platform: PlatformType,
      credentials: Record<string, unknown>,
      storeUrl?: string
    ): Promise<boolean> => {
      updatePlatformState(platform, { isConnecting: true, error: null });

      try {
        const response = await connectPlatform(platform, credentials, storeUrl);

        if (response.success) {
          // Refresh to get the updated connection state
          await refresh();
          return true;
        } else {
          updatePlatformState(platform, {
            isConnecting: false,
            error: response.error || 'Connection failed',
          });
          return false;
        }
      } catch (err) {
        updatePlatformState(platform, {
          isConnecting: false,
          error: err instanceof Error ? err.message : 'Connection failed',
        });
        return false;
      }
    },
    [updatePlatformState, refresh]
  );

  // Disconnect from a platform
  const disconnect = useCallback(
    async (platform: PlatformType): Promise<boolean> => {
      updatePlatformState(platform, { isDisconnecting: true, error: null });

      try {
        await disconnectPlatform(platform);
        updatePlatformState(platform, {
          connection: null,
          isDisconnecting: false,
          orders: [],
        });
        return true;
      } catch (err) {
        updatePlatformState(platform, {
          isDisconnecting: false,
          error: err instanceof Error ? err.message : 'Disconnect failed',
        });
        return false;
      }
    },
    [updatePlatformState]
  );

  // Test a platform connection
  const test = useCallback(
    async (platform: PlatformType): Promise<boolean> => {
      updatePlatformState(platform, { isTesting: true, error: null });

      try {
        const response = await testConnection(platform);
        updatePlatformState(platform, { isTesting: false });
        return response.success;
      } catch (err) {
        updatePlatformState(platform, {
          isTesting: false,
          error: err instanceof Error ? err.message : 'Test failed',
        });
        return false;
      }
    },
    [updatePlatformState]
  );

  // Fetch orders from a platform
  const fetchOrders = useCallback(
    async (
      platform: PlatformType,
      filters?: {
        status?: string;
        limit?: number;
        offset?: number;
      }
    ): Promise<ExternalOrder[]> => {
      updatePlatformState(platform, { isLoadingOrders: true, ordersError: null });

      try {
        const response = await listPlatformOrders(platform, filters);

        if (response.success) {
          updatePlatformState(platform, {
            orders: response.orders,
            isLoadingOrders: false,
          });
          return response.orders;
        } else {
          updatePlatformState(platform, {
            isLoadingOrders: false,
            ordersError: response.error || 'Failed to fetch orders',
          });
          return [];
        }
      } catch (err) {
        updatePlatformState(platform, {
          isLoadingOrders: false,
          ordersError: err instanceof Error ? err.message : 'Failed to fetch orders',
        });
        return [];
      }
    },
    [updatePlatformState]
  );

  // Get connection status for a platform
  const getConnectionStatus = useCallback(
    (platform: PlatformType): ConnectionStatus | 'disconnected' => {
      const connection = state.platforms[platform]?.connection;
      return connection?.status || 'disconnected';
    },
    [state.platforms]
  );

  // Check if a platform is connected
  const isConnected = useCallback(
    (platform: PlatformType): boolean => {
      return getConnectionStatus(platform) === 'connected';
    },
    [getConnectionStatus]
  );

  // Check Shopify environment status
  const checkShopifyEnv = useCallback(async (): Promise<ShopifyEnvStatus | null> => {
    setState((prev) => ({ ...prev, isCheckingEnv: true }));

    try {
      const status = await getShopifyEnvStatus();
      setState((prev) => ({
        ...prev,
        shopifyEnvStatus: status,
        isCheckingEnv: false,
      }));

      // If valid, update Shopify platform state
      if (status.valid) {
        updatePlatformState('shopify', {
          connection: {
            platform: 'shopify',
            store_url: status.store_url,
            status: 'connected',
            last_connected: new Date().toISOString(),
            error_message: null,
          },
        });
      }

      return status;
    } catch (err) {
      setState((prev) => ({
        ...prev,
        shopifyEnvStatus: {
          configured: false,
          valid: false,
          store_url: null,
          store_name: null,
          error: err instanceof Error ? err.message : 'Failed to check Shopify env',
        },
        isCheckingEnv: false,
      }));
      return null;
    }
  }, [updatePlatformState]);

  // Check Shopify environment status on mount
  useEffect(() => {
    checkShopifyEnv();
  }, [checkShopifyEnv]);

  return {
    state,
    connect,
    disconnect,
    test,
    fetchOrders,
    refresh,
    getConnectionStatus,
    isConnected,
    checkShopifyEnv,
  };
}

export default useExternalSources;
