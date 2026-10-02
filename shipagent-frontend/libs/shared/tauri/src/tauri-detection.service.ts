/**
 * TauriDetectionService
 *
 * Detects whether the app is running inside the Tauri desktop wrapper
 * and exposes signals for reactive consumption.
 */

import { computed, Injectable, signal } from '@angular/core';
import { canUseTauriIpc } from './port-resolver';

/** Extends Window with Tauri-injected globals. */
declare global {
  interface Window {
    __TAURI__?: unknown;
  }
}

@Injectable({ providedIn: 'root' })
export class TauriDetectionService {
  /**
   * True only on a Tauri-local origin where native IPC is permitted.
   *
   * The production sidecar-served shell is deliberately false even if the
   * WebView injects a Tauri global into remote content.
   */
  readonly isTauri = signal(
    canUseTauriIpc(window.location, window.__TAURI__ !== undefined)
  );

  /**
   * True only during the packaged custom-protocol bootstrap.
   */
  readonly isBundled = computed(
    () => this.isTauri() && window.location.port !== '4200'
  );
}
