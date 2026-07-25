/** Production Tauri sidecar handoff and browser API-base selection. */

export interface ShellBootstrapLocation {
  readonly protocol: string;
  readonly hostname: string;
  readonly port: string;
  replace(url: string): void;
}

function isPackagedTauriOrigin(location: ShellBootstrapLocation): boolean {
  return (
    location.protocol === 'tauri:' ||
    (location.protocol === 'http:' && location.hostname === 'tauri.localhost')
  );
}

/**
 * Whether frontend code is on a Tauri-local origin that may use native IPC.
 *
 * The loopback sidecar shell is intentionally remote from Tauri's capability
 * perspective and must never use native commands.
 */
export function canUseTauriIpc(
  location: ShellBootstrapLocation,
  hasTauriGlobal: boolean
): boolean {
  if (!hasTauriGlobal) {
    return false;
  }
  return (
    isPackagedTauriOrigin(location) ||
    (location.protocol === 'http:' &&
      location.hostname === 'localhost' &&
      location.port === '4200')
  );
}

/**
 * Compute the browser API base URL.
 *
 * Native Federation development has no proxy passthrough, so its fixed shell
 * origin uses the separately started development backend. Production shells,
 * including the Tauri sidecar reload, always use a relative same-origin URL.
 */
export function computeApiBaseUrl(
  location: ShellBootstrapLocation = window.location
): string {
  return location.hostname === 'localhost' && location.port === '4200'
    ? 'http://localhost:8000/api/v1'
    : '/api/v1';
}
