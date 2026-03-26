/**
 * TauriDetectionService
 *
 * Detects whether the app is running inside the Tauri desktop wrapper
 * and exposes signals for reactive consumption.
 */

import { Injectable, signal, computed } from '@angular/core';

/** Extends Window with Tauri-injected globals. */
declare global {
  interface Window {
    __TAURI__?: unknown;
    __SHIPAGENT_PORT__?: number;
  }
}

@Injectable({ providedIn: 'root' })
export class TauriDetectionService {
  /**
   * True when the app is running inside the Tauri desktop wrapper.
   * Determined once at construction time — does not change during app lifetime.
   */
  readonly isTauri = signal(this.detectTauri());

  /**
   * True when running as a bundled Tauri app (Tauri present + port injected).
   * False in Vite dev mode even if TAURI globals are stubbed.
   */
  readonly isBundled = computed(
    () => this.isTauri() && window.__SHIPAGENT_PORT__ !== undefined,
  );

  /**
   * The dynamically assigned sidecar port, or null if not in Tauri mode.
   */
  readonly sidecarPort = signal<number | null>(
    window.__SHIPAGENT_PORT__ ?? null,
  );

  private detectTauri(): boolean {
    return typeof window !== 'undefined' && window.__TAURI__ !== undefined;
  }
}
