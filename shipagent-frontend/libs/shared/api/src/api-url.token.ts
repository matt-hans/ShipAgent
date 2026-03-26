/**
 * API_BASE_URL InjectionToken
 *
 * Provides the API base URL as an Angular Signal, allowing dynamic
 * updates when the Tauri sidecar port is discovered at runtime.
 *
 * Usage in providers:
 * ```typescript
 * import { signal } from '@angular/core';
 * import { API_BASE_URL } from '@shipagent/shared-api';
 *
 * // In Vite dev mode (proxied):
 * { provide: API_BASE_URL, useFactory: () => signal('/api/v1') }
 *
 * // In Tauri mode (resolved dynamically):
 * { provide: API_BASE_URL, useFactory: () => signal(`http://127.0.0.1:${port}/api/v1`) }
 * ```
 */

import { InjectionToken, Signal } from '@angular/core';

/**
 * InjectionToken for the API base URL signal.
 *
 * Consumers inject this token and call it as a function to get the
 * current base URL. The shell provides this token; all remotes consume it.
 */
export const API_BASE_URL = new InjectionToken<Signal<string>>('API_BASE_URL');
