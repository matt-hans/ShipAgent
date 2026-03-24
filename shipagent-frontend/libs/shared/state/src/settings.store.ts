/**
 * SettingsStore — Application settings and credential status.
 *
 * Holds the app settings singleton fetched from the backend and the
 * credential status (which keys are configured in the keychain).
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';
import type { AppSettings, CredentialStatus } from '@shipagent/shared-types';

export interface SettingsState {
  /** The application settings singleton (null until fetched). */
  appSettings: AppSettings | null;
  /** Credential status for each key (null until fetched). */
  credentialStatus: CredentialStatus | null;
  /** Whether the onboarding wizard has been completed. */
  onboardingCompleted: boolean;
}

const initialState: SettingsState = {
  appSettings: null,
  credentialStatus: null,
  onboardingCompleted: false,
};

export const SettingsStore = signalStore(
  { providedIn: 'root' },
  withState<SettingsState>(initialState),
  withMethods((store) => ({
    /** Update the app settings singleton. */
    setAppSettings(settings: AppSettings | null): void {
      patchState(store, {
        appSettings: settings,
        onboardingCompleted: settings?.onboarding_completed ?? false,
      });
    },

    /** Update the credential status. */
    setCredentialStatus(status: CredentialStatus | null): void {
      patchState(store, { credentialStatus: status });
    },

    /** Mark onboarding as completed. */
    setOnboardingCompleted(value: boolean): void {
      patchState(store, { onboardingCompleted: value });
    },
  })),
);
