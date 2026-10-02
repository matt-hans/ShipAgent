/**
 * Tauri mock utilities for testing Tauri-aware components and services.
 *
 * Use these helpers to simulate running inside the Tauri desktop wrapper
 * without actually launching the app in Tauri mode.
 */

/** Extends Window with Tauri test globals. */
declare global {
  interface Window {
    __TAURI__?: unknown;
  }
}

/**
 * Simulate the trusted Tauri bootstrap origin and its start-sidecar command.
 *
 * @param port - Sidecar port returned by the native command (defaults to 8000).
 * @returns A cleanup function that removes the stubs when called.
 *
 * @example
 * ```typescript
 * let cleanupTauri: () => void;
 *
 * beforeEach(() => { cleanupTauri = mockTauriEnvironment(8999); });
 * afterEach(() => { cleanupTauri(); });
 * ```
 */
export function mockTauriEnvironment(port = 8000): () => void {
  const originalTauri = window.__TAURI__;

  window.__TAURI__ = {
    core: {
      invoke: createMockTauriInvoke({ start_sidecar: port }),
    },
  };

  return () => {
    if (originalTauri !== undefined) {
      window.__TAURI__ = originalTauri;
    } else {
      delete window.__TAURI__;
    }
  };
}

/**
 * Ensure the Tauri environment stubs are removed.
 * Call in afterEach() when not using mockTauriEnvironment().
 */
export function clearTauriEnvironment(): void {
  delete window.__TAURI__;
}

/**
 * Create a mock Tauri invoke function that returns predefined values.
 *
 * @param responses - Map of command name to return value.
 * @returns A mock invoke function.
 *
 * @example
 * ```typescript
 * const invoke = createMockTauriInvoke({ start_sidecar: 8999 });
 * window.__TAURI__ = { core: { invoke } };
 * ```
 */
export function createMockTauriInvoke(
  responses: Record<string, unknown> = {}
): (command: string, args?: unknown) => Promise<unknown> {
  return async (command: string) => {
    if (command in responses) {
      return responses[command];
    }
    throw new Error(
      `Tauri mock: no response configured for command "${command}"`
    );
  };
}
