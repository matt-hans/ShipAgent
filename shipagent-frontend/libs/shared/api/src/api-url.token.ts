/**
 * API_BASE_URL InjectionToken
 *
 * Provides the API base URL as an Angular Signal.
 *
 * Usage in providers:
 * ```typescript
 * import { signal } from '@angular/core';
 * import { API_BASE_URL } from '@shipagent/shared-api';
 *
 * // In Vite dev mode (proxied):
 * { provide: API_BASE_URL, useFactory: () => signal('/api/v1') }
 *
 * // In production web and the sidecar-served Tauri shell:
 * { provide: API_BASE_URL, useFactory: () => signal('/api/v1') }
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
