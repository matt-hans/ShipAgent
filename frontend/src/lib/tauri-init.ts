/**
 * Tauri sidecar initialization.
 *
 * Called once on app startup to launch the Python backend and
 * discover the dynamically assigned port. Sets window.__SHIPAGENT_PORT__
 * which api.ts reads for the API base URL.
 */
// Indirection prevents Vite's static import analysis from failing when
// @tauri-apps packages are not installed (e.g. plain `npm run dev`).
const TAURI_CORE = '@tauri-apps/api/core';

export async function initSidecar(): Promise<void> {
  // Only run inside Tauri — skip in Vite dev mode
  if (!(window as any).__TAURI__) return;

  const { invoke } = await import(/* @vite-ignore */ TAURI_CORE);
  const port = Number(await invoke('start_sidecar'));

  // Validate the discovered port is in the IANA ephemeral range (CWE-693).
  // Prevents the frontend from connecting to well-known service ports
  // if the sidecar reports an unexpected value.
  if (!Number.isFinite(port) || port < 1024 || port > 65535) {
    throw new Error(`Sidecar reported invalid port: ${port}`);
  }

  (window as any).__SHIPAGENT_PORT__ = port;
}
