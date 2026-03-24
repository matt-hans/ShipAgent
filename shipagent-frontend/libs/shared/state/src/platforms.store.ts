/**
 * PlatformsStore — External platform connection state.
 *
 * Tracks the connection status for all external platforms (Shopify, Amazon,
 * WooCommerce, SAP, Oracle). Provides a version counter for triggering
 * re-fetches of connection status across remotes.
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';
import type { ProviderConnectionInfo } from '@shipagent/shared-types';

export interface PlatformsState {
  /**
   * Map of provider connection key to connection info.
   * Key is the provider connection_key (e.g., 'ups', 'shopify').
   */
  connections: Record<string, ProviderConnectionInfo>;
  /**
   * Incremented whenever platform connections may have changed.
   * Components watch this to know when to re-fetch.
   */
  providerConnectionsVersion: number;
}

const initialState: PlatformsState = {
  connections: {},
  providerConnectionsVersion: 0,
};

export const PlatformsStore = signalStore(
  { providedIn: 'root' },
  withState<PlatformsState>(initialState),
  withMethods((store) => ({
    /** Set a platform connection by its connection key. */
    setConnection(platform: string, connection: ProviderConnectionInfo): void {
      patchState(store, (s) => ({
        connections: { ...s.connections, [platform]: connection },
      }));
    },

    /** Remove a platform connection by its connection key. */
    removeConnection(platform: string): void {
      patchState(store, (s) => {
        const updated = { ...s.connections };
        delete updated[platform];
        return { connections: updated };
      });
    },

    /** Increment the version counter to trigger a connection status re-fetch. */
    incrementProviderConnectionsVersion(): void {
      patchState(store, (s) => ({
        providerConnectionsVersion: s.providerConnectionsVersion + 1,
      }));
    },
  })),
);
