import { Injectable, signal } from '@angular/core';

/**
 * Shared notification channel for browser-session expiry.
 *
 * A monotonically increasing signal preserves distinct expiry events without
 * retaining credentials or coupling remotes to shell lifecycle state.
 */
@Injectable({ providedIn: 'root' })
export class BrowserSessionState {
  private readonly expiration = signal(0);

  readonly expirationVersion = this.expiration.asReadonly();

  markExpired(): void {
    this.expiration.update((version) => version + 1);
  }
}
