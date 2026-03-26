/**
 * DataSourceStore — Connected data source state.
 *
 * Tracks the currently connected data source (local file or platform),
 * the active source type, and the write-back toggle preference.
 * writeBackEnabled is persisted to localStorage via withStorageSync.
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';
import { withStorageSync } from '@angular-architects/ngrx-toolkit';
import type { DataSourceInfo } from '@shipagent/shared-types';

/** Identifies which data source type is currently active. */
export type SourceType = 'local' | 'shopify' | 'amazon';

/** Cached local source config for one-click reconnect after switching to Shopify. */
export interface LocalSourceConfig {
  type: 'csv' | 'excel' | 'database';
  file_path?: string;
}

export interface DataSourceState {
  /** The currently connected data source info (null when disconnected). */
  dataSource: DataSourceInfo | null;
  /** The active source category (local file, shopify, or amazon). */
  activeSourceType: SourceType | null;
  /** Human-readable description of the active source. */
  activeSourceInfo: string;
  /** Whether tracking numbers should be written back to the source file. */
  writeBackEnabled: boolean;
  /** Cached local config for reconnect after switching to a platform source. */
  cachedLocalConfig: LocalSourceConfig | null;
}

const initialState: DataSourceState = {
  dataSource: null,
  activeSourceType: null,
  activeSourceInfo: '',
  writeBackEnabled: true,
  cachedLocalConfig: null,
};

export const DataSourceStore = signalStore(
  { providedIn: 'root' },
  withState<DataSourceState>(initialState),
  // Persist only writeBackEnabled — runtime state is not persisted.
  withStorageSync({
    key: 'shipagent_datasource',
    select: (state: DataSourceState) => ({ writeBackEnabled: state.writeBackEnabled }),
  }),
  withMethods((store) => ({
    /** Set the connected data source. */
    setDataSource(ds: DataSourceInfo | null): void {
      patchState(store, { dataSource: ds });
    },

    /** Clear the connected data source. */
    clearDataSource(): void {
      patchState(store, { dataSource: null, activeSourceType: null, activeSourceInfo: '' });
    },

    /** Set the active source type. */
    setActiveSourceType(type: SourceType | null): void {
      patchState(store, { activeSourceType: type });
    },

    /** Set the human-readable source info string. */
    setActiveSourceInfo(info: string): void {
      patchState(store, { activeSourceInfo: info });
    },

    /** Enable or disable write-back of tracking numbers to source. */
    setWriteBackEnabled(value: boolean): void {
      patchState(store, { writeBackEnabled: value });
    },

    /** Cache the local source config for reconnect after switching to platform. */
    setCachedLocalConfig(config: LocalSourceConfig | null): void {
      patchState(store, { cachedLocalConfig: config });
    },
  })),
);
