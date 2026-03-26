/**
 * Tauri sidecar port resolution.
 *
 * Reads the dynamic sidecar port set by the Rust backend after spawning
 * the Python sidecar. The port is stored in window.__SHIPAGENT_PORT__.
 *
 * Port validation enforces the IANA ephemeral range (1024-65535)
 * to prevent connecting to well-known service ports (CWE-693).
 */

const TAURI_CORE = '@tauri-apps/api/core';

/**
 * Initialize the sidecar and resolve the backend port.
 *
 * In Tauri mode: invokes the 'start_sidecar' Rust command and stores
 * the port in window.__SHIPAGENT_PORT__.
 * In Vite dev mode: no-op (returns null).
 *
 * @returns Resolved port number, or null if not in Tauri mode.
 */
export async function resolveSidecarPort(): Promise<number | null> {
  if (typeof window === 'undefined' || !window.__TAURI__) {
    return null;
  }

  // Dynamically import to avoid Vite static analysis errors when
  // @tauri-apps/api is not installed.
  const tauriCore = await import(/* @vite-ignore */ TAURI_CORE) as { invoke: (cmd: string) => Promise<unknown> };
  const port = (await tauriCore.invoke('start_sidecar')) as number;

  // Validate the port is in the IANA ephemeral range.
  if (port < 1024 || port > 65535) {
    throw new Error(`Sidecar reported invalid port: ${port}`);
  }

  window.__SHIPAGENT_PORT__ = port;
  return port;
}

/**
 * Compute the API base URL from the sidecar port.
 *
 * In Tauri mode: http://127.0.0.1:{port}/api/v1
 * In Vite dev mode: /api/v1 (proxied by Vite to localhost:8000)
 */
export function computeApiBaseUrl(): string {
  const port = window.__SHIPAGENT_PORT__;
  return port ? `http://127.0.0.1:${port}/api/v1` : '/api/v1';
}
