/**
 * JobStore unit tests.
 *
 * Verifies:
 *   - incrementJobListVersion() changes the version signal
 *   - setActiveJob() / clearActiveJob() manage the active job
 *   - Initial state is correct
 *
 * NOTE: These tests are designed to be run from any app that includes
 * libs/shared/state/src in its tsconfig.spec.json include paths.
 */

import { TestBed } from '@angular/core/testing';
import { JobStore } from './job.store';
import type { Job } from '@shipagent/shared-types';

/** Minimal Job fixture for testing. */
function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    name: 'Test Job',
    description: null,
    original_command: 'Ship all orders',
    status: 'pending',
    mode: 'confirm',
    total_rows: 10,
    processed_rows: 0,
    successful_rows: 0,
    failed_rows: 0,
    total_cost_cents: null,
    error_code: null,
    error_message: null,
    created_at: '2026-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('JobStore', () => {
  let store: InstanceType<typeof JobStore>;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(JobStore);
  });

  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  describe('initial state', () => {
    it('should have activeJob = null', () => {
      expect(store.activeJob()).toBeNull();
    });

    it('should have jobListVersion = 0', () => {
      expect(store.jobListVersion()).toBe(0);
    });
  });

  // -------------------------------------------------------------------------
  // incrementJobListVersion
  // -------------------------------------------------------------------------

  describe('incrementJobListVersion()', () => {
    it('should increment jobListVersion by 1', () => {
      store.incrementJobListVersion();
      expect(store.jobListVersion()).toBe(1);
    });

    it('should increment correctly on multiple calls', () => {
      store.incrementJobListVersion();
      store.incrementJobListVersion();
      store.incrementJobListVersion();
      expect(store.jobListVersion()).toBe(3);
    });

    it('should return a different value after each call', () => {
      const before = store.jobListVersion();
      store.incrementJobListVersion();
      const after = store.jobListVersion();
      expect(after).not.toBe(before);
    });
  });

  // -------------------------------------------------------------------------
  // setActiveJob
  // -------------------------------------------------------------------------

  describe('setActiveJob()', () => {
    it('should set the active job', () => {
      const job = makeJob({ id: 'job-abc', status: 'completed' });
      store.setActiveJob(job);
      expect(store.activeJob()).toEqual(job);
    });

    it('should replace the previous active job', () => {
      store.setActiveJob(makeJob({ id: 'job-1' }));
      store.setActiveJob(makeJob({ id: 'job-2' }));
      expect(store.activeJob()?.id).toBe('job-2');
    });

    it('should accept null to deselect', () => {
      store.setActiveJob(makeJob());
      store.setActiveJob(null);
      expect(store.activeJob()).toBeNull();
    });
  });

  // -------------------------------------------------------------------------
  // clearActiveJob
  // -------------------------------------------------------------------------

  describe('clearActiveJob()', () => {
    it('should set activeJob to null', () => {
      store.setActiveJob(makeJob());
      store.clearActiveJob();
      expect(store.activeJob()).toBeNull();
    });

    it('should be safe to call when no job is active', () => {
      expect(() => store.clearActiveJob()).not.toThrow();
      expect(store.activeJob()).toBeNull();
    });
  });

  // -------------------------------------------------------------------------
  // Cross-remote simulation: jobListVersion used to trigger sidebar refresh
  // -------------------------------------------------------------------------

  describe('cross-remote data flow simulation', () => {
    it('should reflect incrementJobListVersion() changes immediately (signal)', () => {
      const versionBefore = store.jobListVersion();
      store.incrementJobListVersion();
      const versionAfter = store.jobListVersion();

      expect(versionAfter).toBe(versionBefore + 1);
    });

    it('should return the same root singleton when injected multiple times', () => {
      const store2 = TestBed.inject(JobStore);
      expect(store2).toBe(store);
    });
  });
});
