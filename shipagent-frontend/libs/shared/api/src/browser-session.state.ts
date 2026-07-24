import { Injectable, signal } from '@angular/core';
import type { BrowserSessionStatus } from '@shipagent/shared-types';

/**
 * Shared notification channel for browser-session expiry.
 *
 * A monotonically increasing signal preserves distinct expiry events without
 * retaining credentials or coupling remotes to shell lifecycle state. The
 * session-bound CSRF token is held only in this in-memory service.
 */
@Injectable({ providedIn: 'root' })
export class BrowserSessionState {
  private readonly expiration = signal(0);
  private readonly csrf = signal<string | null>(null);

  readonly expirationVersion = this.expiration.asReadonly();
  readonly csrfToken = this.csrf.asReadonly();

  applySessionStatus(status: BrowserSessionStatus): void {
    this.csrf.set(
      status.authenticated && typeof status.csrf_token === 'string'
        ? status.csrf_token
        : null
    );
  }

  markExpired(): void {
    this.csrf.set(null);
    this.expiration.update((version) => version + 1);
  }
}
