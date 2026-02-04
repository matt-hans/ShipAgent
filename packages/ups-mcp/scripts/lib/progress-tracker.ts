/**
 * Progress Tracker
 *
 * Manages state persistence for resumable order generation.
 * - Persists state to .shopify-test-orders-state.json
 * - Tracks created order IDs for cleanup
 * - Enables resume after interruption
 */

import { readFileSync, writeFileSync, existsSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import type { ProgressState, OrderError } from "./types.js";

/**
 * State file name
 */
const STATE_FILE_NAME = ".shopify-test-orders-state.json";

/**
 * Progress Tracker for resumable order generation
 *
 * Usage:
 * ```typescript
 * const tracker = new ProgressTracker('/path/to/project');
 *
 * // Start new session
 * tracker.initialize({ targetCount: 1000, seed: 12345 });
 *
 * // Record progress
 * tracker.recordSuccess(index, orderId);
 * tracker.recordError(index, 'API Error');
 *
 * // Resume
 * const state = tracker.load();
 * console.log(`Resuming from index ${state.nextIndex}`);
 * ```
 */
export class ProgressTracker {
  private readonly stateFilePath: string;
  private state: ProgressState | null = null;

  /**
   * Creates a new ProgressTracker
   *
   * @param baseDir - Directory to store state file
   */
  constructor(baseDir: string) {
    this.stateFilePath = join(baseDir, STATE_FILE_NAME);
  }

  /**
   * Checks if a state file exists
   */
  hasState(): boolean {
    return existsSync(this.stateFilePath);
  }

  /**
   * Loads existing state from disk
   *
   * @returns Progress state or null if not found
   */
  load(): ProgressState | null {
    if (!this.hasState()) {
      return null;
    }

    try {
      const content = readFileSync(this.stateFilePath, "utf-8");
      this.state = JSON.parse(content) as ProgressState;
      return this.state;
    } catch (error) {
      console.error("Failed to load state file:", error);
      return null;
    }
  }

  /**
   * Initializes a new progress tracking session
   *
   * @param config - Session configuration
   * @returns Initialized state
   */
  initialize(config: { targetCount: number; seed: number }): ProgressState {
    const now = new Date().toISOString();

    this.state = {
      version: 1,
      sessionId: crypto.randomUUID(),
      targetCount: config.targetCount,
      createdOrderIds: [],
      nextIndex: 0,
      errors: [],
      startedAt: now,
      updatedAt: now,
      completed: false,
      seed: config.seed,
    };

    this.save();
    return this.state;
  }

  /**
   * Gets current state
   */
  getState(): ProgressState | null {
    return this.state;
  }

  /**
   * Records successful order creation
   *
   * @param index - Order index
   * @param orderId - Created order ID
   */
  recordSuccess(index: number, orderId: number): void {
    if (!this.state) {
      throw new Error("Progress tracker not initialized");
    }

    this.state.createdOrderIds.push(orderId);
    this.state.nextIndex = index + 1;
    this.state.updatedAt = new Date().toISOString();

    // Save periodically (every 10 orders) or always in small batches
    if (this.state.createdOrderIds.length % 10 === 0 || this.state.targetCount < 100) {
      this.save();
    }
  }

  /**
   * Records order creation error
   *
   * @param index - Order index that failed
   * @param message - Error message
   */
  recordError(index: number, message: string): void {
    if (!this.state) {
      throw new Error("Progress tracker not initialized");
    }

    const error: OrderError = {
      index,
      message,
      timestamp: new Date().toISOString(),
    };

    this.state.errors.push(error);
    this.state.nextIndex = index + 1;
    this.state.updatedAt = new Date().toISOString();
    this.save();
  }

  /**
   * Marks generation as complete
   */
  markComplete(): void {
    if (!this.state) {
      throw new Error("Progress tracker not initialized");
    }

    this.state.completed = true;
    this.state.updatedAt = new Date().toISOString();
    this.save();
  }

  /**
   * Forces save of current state
   */
  save(): void {
    if (!this.state) {
      return;
    }

    try {
      writeFileSync(this.stateFilePath, JSON.stringify(this.state, null, 2), "utf-8");
    } catch (error) {
      console.error("Failed to save state file:", error);
    }
  }

  /**
   * Deletes the state file
   */
  delete(): void {
    if (this.hasState()) {
      try {
        unlinkSync(this.stateFilePath);
        this.state = null;
      } catch (error) {
        console.error("Failed to delete state file:", error);
      }
    }
  }

  /**
   * Gets progress statistics
   */
  getStats(): {
    total: number;
    created: number;
    errors: number;
    remaining: number;
    percentComplete: number;
  } | null {
    if (!this.state) {
      return null;
    }

    const created = this.state.createdOrderIds.length;
    const errors = this.state.errors.length;
    const remaining = this.state.targetCount - this.state.nextIndex;
    const percentComplete = Math.round((this.state.nextIndex / this.state.targetCount) * 100);

    return {
      total: this.state.targetCount,
      created,
      errors,
      remaining,
      percentComplete,
    };
  }

  /**
   * Gets created order IDs for cleanup
   */
  getOrderIds(): number[] {
    return this.state?.createdOrderIds || [];
  }

  /**
   * Formats status for display
   */
  formatStatus(): string {
    const state = this.state;
    if (!state) {
      return "No active session";
    }

    const stats = this.getStats()!;
    const elapsed = new Date(state.updatedAt).getTime() - new Date(state.startedAt).getTime();
    const elapsedMins = Math.round(elapsed / 60000);

    const lines = [
      `Session: ${state.sessionId}`,
      `Status: ${state.completed ? "Complete" : "In Progress"}`,
      `Progress: ${stats.created}/${stats.total} orders (${stats.percentComplete}%)`,
      `Errors: ${stats.errors}`,
      `Started: ${state.startedAt}`,
      `Duration: ${elapsedMins} minutes`,
      `Seed: ${state.seed}`,
    ];

    if (state.errors.length > 0) {
      lines.push("", "Recent Errors:");
      state.errors.slice(-5).forEach((err) => {
        lines.push(`  [${err.index}] ${err.message}`);
      });
    }

    return lines.join("\n");
  }
}

/**
 * Gets the default progress tracker (in package directory)
 */
export function getDefaultTracker(): ProgressTracker {
  const packageDir = new URL("../..", import.meta.url).pathname;
  return new ProgressTracker(packageDir);
}
