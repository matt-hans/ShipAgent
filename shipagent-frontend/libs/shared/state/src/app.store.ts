/**
 * AppStore — Global UI flags.
 *
 * Manages sidebar state, settings flyout visibility, and processing indicators.
 * Provided as a root singleton so all remotes share the same UI state.
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';

export interface AppState {
  /** Whether the sidebar panel is collapsed. */
  sidebarCollapsed: boolean;
  /** Whether the settings flyout is open. */
  settingsFlyoutOpen: boolean;
  /** Whether a global async operation is in progress. */
  isProcessing: boolean;
  /** Prevents interactive-shipping toggle changes while a session reset is in-flight. */
  isToggleLocked: boolean;
}

const initialState: AppState = {
  sidebarCollapsed: false,
  settingsFlyoutOpen: false,
  isProcessing: false,
  isToggleLocked: false,
};

export const AppStore = signalStore(
  { providedIn: 'root' },
  withState<AppState>(initialState),
  withMethods((store) => ({
    /** Toggle sidebar between collapsed and expanded. */
    toggleSidebar(): void {
      patchState(store, (s) => ({ sidebarCollapsed: !s.sidebarCollapsed }));
    },

    /** Open the settings flyout panel. */
    openSettings(): void {
      patchState(store, { settingsFlyoutOpen: true });
    },

    /** Close the settings flyout panel. */
    closeSettings(): void {
      patchState(store, { settingsFlyoutOpen: false });
    },

    /** Set the global processing state. */
    setProcessing(value: boolean): void {
      patchState(store, { isProcessing: value });
    },

    /** Set the toggle lock state to prevent race conditions during session resets. */
    setToggleLocked(value: boolean): void {
      patchState(store, { isToggleLocked: value });
    },
  })),
);
