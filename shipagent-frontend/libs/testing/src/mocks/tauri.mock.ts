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
    __SHIPAGENT_PORT__?: number;
  }
}

/**
 * Simulate a Tauri environment by injecting __TAURI__ and optionally
 * setting the sidecar port.
 *
 * @param port - Optional sidecar port to inject (defaults to 8000).
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
  const originalPort = window.__SHIPAGENT_PORT__;

  window.__TAURI__ = { version: '2.0.0-test' };
  window.__SHIPAGENT_PORT__ = port;

  return () => {
    if (originalTauri !== undefined) {
      window.__TAURI__ = originalTauri;
    } else {
      delete window.__TAURI__;
    }

    if (originalPort !== undefined) {
      window.__SHIPAGENT_PORT__ = originalPort;
    } else {
      delete window.__SHIPAGENT_PORT__;
    }
  };
}

/**
 * Ensure the Tauri environment stubs are removed.
 * Call in afterEach() when not using mockTauriEnvironment().
 */
export function clearTauriEnvironment(): void {
  delete window.__TAURI__;
  delete window.__SHIPAGENT_PORT__;
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
 * spyOn(window.__TAURI__ as any, 'invoke').and.callFake(invoke);
 * ```
 */
export function createMockTauriInvoke(
  responses: Record<string, unknown> = {},
): (command: string, args?: unknown) => Promise<unknown> {
  return async (command: string) => {
    if (command in responses) {
      return responses[command];
    }
    throw new Error(`Tauri mock: no response configured for command "${command}"`);
  };
}
