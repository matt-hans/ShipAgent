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
  const port = await invoke<number>('start_sidecar');
  (window as any).__SHIPAGENT_PORT__ = port;
}
