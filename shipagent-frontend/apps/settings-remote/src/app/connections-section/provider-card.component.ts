/**
 * ProviderCardComponent — Expandable card for a single provider connection.
 *
 * Port of ProviderCard.tsx React component.
 * Shows provider name, status badges, and expand/collapse for the credential form.
 */

import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '@shipagent/shared-api';
import type { ProviderConnectionInfo, ProviderConnectionStatus } from '@shipagent/shared-types';

const STATUS_LABELS: Record<ProviderConnectionStatus, string> = {
  configured: 'Configured',
  validating: 'Validating',
  connected: 'Connected',
  disconnected: 'Disconnected',
  error: 'Error',
  needs_reconnect: 'Needs Reconnect',
};

const STATUS_COLORS: Record<ProviderConnectionStatus, string> = {
  configured: 'bg-info/15 text-info border-info/30',
  validating: 'bg-info/15 text-info border-info/30',
  connected: 'bg-success/15 text-success border-success/30',
  disconnected: 'bg-muted text-muted-foreground border-border',
  error: 'bg-warning/15 text-warning border-warning/30',
  needs_reconnect: 'bg-warning/15 text-warning border-warning/30',
};

@Component({
  selector: 'app-provider-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  template: `
    <div class="rounded-lg border border-border overflow-hidden">
      <!-- Header -->
      <button
        class="w-full flex items-center justify-between px-3 py-2.5 hover:bg-muted/30 transition-colors"
        (click)="toggled.emit()"
        [attr.aria-expanded]="isOpen"
      >
        <div class="flex items-center gap-2">
          <ng-content select="[slot=icon]"></ng-content>
          <span class="text-xs font-medium text-foreground">{{ providerName }}</span>

          @if (activeEnvironment && configuredCount() > 0) {
            <span
              class="text-[10px] px-1.5 py-0.5 rounded-full border"
              [class]="activeEnvironment === 'production'
                ? 'bg-success/15 text-success border-success/30'
                : 'bg-info/15 text-info border-info/30'"
            >
              {{ activeEnvironment === 'test' ? 'Test' : 'Prod' }}
            </span>
          }

          @if (connections.length > 0 && !activeEnvironment) {
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
              {{ configuredCount() }}/{{ totalSlots() }}
            </span>
          }
        </div>
        <!-- Chevron -->
        <svg
          class="h-3.5 w-3.5 text-muted-foreground transition-transform"
          [class.rotate-180]="isOpen"
          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round"
        >
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      @if (isOpen) {
        <div class="px-3 pb-3 border-t border-border space-y-3 pt-2">
          <!-- Existing connections -->
          @for (conn of connections; track conn.connection_key) {
            <div class="flex items-center justify-between p-2 rounded-md bg-muted/30 border border-border">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-xs font-medium text-foreground truncate">
                    {{ conn.display_name || conn.connection_key }}
                  </span>
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded-full border"
                    [class]="getStatusColor(conn.status)"
                  >
                    {{ getStatusLabel(conn.status) }}
                  </span>
                </div>
                @if (conn.environment) {
                  <div class="flex items-center gap-1.5">
                    <span class="text-[10px] text-muted-foreground">{{ conn.environment }}</span>
                    @if (activeEnvironment && conn.environment === activeEnvironment && conn.status === 'connected') {
                      <span class="text-[9px] px-1 py-0.5 rounded bg-primary/15 text-primary border border-primary/30 font-medium">
                        Active
                      </span>
                    }
                  </div>
                }
                @if (!conn.runtime_usable && conn.runtime_reason) {
                  <p class="text-[10px] text-warning mt-0.5">{{ conn.runtime_reason }}</p>
                }
              </div>
              <div class="flex items-center gap-1 ml-2">
                @if (conn.status !== 'disconnected') {
                  <!-- Validate button -->
                  <button
                    (click)="handleValidate(conn.connection_key)"
                    [disabled]="pendingAction() !== null"
                    title="Test credentials against the provider API"
                    class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-primary disabled:opacity-50"
                  >
                    @if (pendingAction() === 'validate:' + conn.connection_key) {
                      <span class="block w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin"></span>
                    } @else {
                      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                      </svg>
                    }
                  </button>
                  <!-- Disconnect button -->
                  <button
                    (click)="handleDisconnect(conn.connection_key)"
                    [disabled]="pendingAction() !== null"
                    title="Temporarily disable this connection. Credentials are preserved."
                    class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
                  >
                    @if (pendingAction() === 'disconnect:' + conn.connection_key) {
                      <span class="block w-3.5 h-3.5 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin"></span>
                    } @else {
                      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M19 9l-7 7-7-7"></path>
                        <path d="M12 3v14"></path>
                        <path d="M5 21h14"></path>
                      </svg>
                    }
                  </button>
                }

                <!-- Delete confirmation -->
                @if (confirmDeleteKey() === conn.connection_key) {
                  <div class="flex items-center gap-1">
                    <button
                      (click)="handleDelete(conn.connection_key)"
                      [disabled]="pendingAction() !== null"
                      class="text-[10px] px-1.5 py-0.5 rounded bg-destructive/20 text-destructive hover:bg-destructive/30 disabled:opacity-50"
                    >
                      {{ pendingAction() === 'delete:' + conn.connection_key ? '...' : 'Confirm' }}
                    </button>
                    <button
                      (click)="confirmDeleteKey.set(null)"
                      class="text-[10px] px-1.5 py-0.5 rounded text-muted-foreground hover:bg-muted"
                    >
                      Cancel
                    </button>
                  </div>
                } @else {
                  <button
                    (click)="confirmDeleteKey.set(conn.connection_key)"
                    [disabled]="pendingAction() !== null"
                    title="Permanently remove this connection and its stored credentials."
                    class="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-destructive disabled:opacity-50"
                  >
                    <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="3 6 5 6 21 6"></polyline>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
                    </svg>
                  </button>
                }
              </div>
            </div>
          }

          <!-- Validation result -->
          @if (validationResult()) {
            <div
              class="text-[11px] px-2.5 py-1.5 rounded-md"
              [class]="validationResult()!.valid
                ? 'bg-success/10 text-success border border-success/30'
                : 'bg-destructive/10 text-destructive border border-destructive/30'"
            >
              {{ validationResult()!.message }}
            </div>
          }

          <!-- Credential form (ng-content) -->
          <ng-content></ng-content>
        </div>
      }
    </div>
  `,
})
export class ProviderCardComponent {
  private readonly apiService = inject(ApiService);

  @Input() providerName = '';
  @Input() connections: ProviderConnectionInfo[] = [];
  @Input() isOpen = false;
  @Input() activeEnvironment: string | null = null;

  @Output() toggled = new EventEmitter<void>();
  @Output() deleteRequest = new EventEmitter<string>();
  @Output() disconnectRequest = new EventEmitter<string>();
  @Output() validated = new EventEmitter<void>();

  pendingAction = signal<string | null>(null);
  confirmDeleteKey = signal<string | null>(null);
  validationResult = signal<{ key: string; valid: boolean; message: string } | null>(null);

  configuredCount(): number {
    return this.connections.filter((c) => c.status !== 'disconnected').length;
  }

  totalSlots(): number {
    return this.providerName === 'UPS' ? 2 : 1;
  }

  getStatusLabel(status: ProviderConnectionStatus): string {
    return STATUS_LABELS[status] ?? status;
  }

  getStatusColor(status: ProviderConnectionStatus): string {
    return STATUS_COLORS[status] ?? 'bg-muted text-muted-foreground border-border';
  }

  async handleValidate(key: string): Promise<void> {
    this.pendingAction.set(`validate:${key}`);
    this.validationResult.set(null);
    try {
      const result = await firstValueFrom(
        this.apiService.validateProviderConnection(key),
      );
      this.validationResult.set({ key, valid: result.valid, message: result.message });
      this.validated.emit();
    } catch {
      this.validationResult.set({ key, valid: false, message: 'Validation request failed.' });
    } finally {
      this.pendingAction.set(null);
    }
  }

  async handleDisconnect(key: string): Promise<void> {
    this.pendingAction.set(`disconnect:${key}`);
    try {
      this.disconnectRequest.emit(key);
    } finally {
      this.pendingAction.set(null);
    }
  }

  async handleDelete(key: string): Promise<void> {
    this.pendingAction.set(`delete:${key}`);
    try {
      this.deleteRequest.emit(key);
    } finally {
      this.pendingAction.set(null);
      this.confirmDeleteKey.set(null);
    }
  }
}
