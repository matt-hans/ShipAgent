/**
 * JobStore — Active job and job list versioning.
 *
 * Tracks the currently selected/active batch job and provides a version
 * counter for triggering job list re-fetches across remotes.
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';
import type { Job } from '@shipagent/shared-types';

export interface JobState {
  /** The currently selected/active batch job (null if none selected). */
  activeJob: Job | null;
  /**
   * Incremented whenever the job list may have changed.
   * Components watch this to know when to re-fetch.
   */
  jobListVersion: number;
}

const initialState: JobState = {
  activeJob: null,
  jobListVersion: 0,
};

export const JobStore = signalStore(
  { providedIn: 'root' },
  withState<JobState>(initialState),
  withMethods((store) => ({
    /** Set the active job (or null to deselect). */
    setActiveJob(job: Job | null): void {
      patchState(store, { activeJob: job });
    },

    /** Clear the active job selection. */
    clearActiveJob(): void {
      patchState(store, { activeJob: null });
    },

    /** Increment the job list version to trigger a re-fetch. */
    incrementJobListVersion(): void {
      patchState(store, (s) => ({ jobListVersion: s.jobListVersion + 1 }));
    },
  })),
);
