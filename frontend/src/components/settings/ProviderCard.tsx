/**
 * ProviderCard - Expandable card for a single provider connection.
 *
 * Shows provider name, status badge, runtime_usable indicator.
 * Expands to reveal the provider-specific credential form.
 */

import * as React from 'react';
import { ChevronDown, Trash2, Unplug } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ProviderConnectionInfo, ProviderConnectionStatus } from '@/types/api';

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

interface ProviderCardProps {
  /** Provider display name (e.g., "UPS", "Shopify") */
  providerName: string;
  /** Icon to render */
  icon: React.ReactNode;
  /** Existing connections for this provider */
  connections: ProviderConnectionInfo[];
  /** Whether the card content is expanded */
  isOpen: boolean;
  /** Toggle expand/collapse */
  onToggle: () => void;
  /** Called after delete succeeds */
  onDelete: (connectionKey: string) => Promise<void>;
  /** Called after disconnect succeeds */
  onDisconnect: (connectionKey: string) => Promise<void>;
  /** The credential form component */
  children: React.ReactNode;
}

export function ProviderCard({
  providerName,
  icon,
  connections,
  isOpen,
  onToggle,
  onDelete,
  onDisconnect,
  children,
}: ProviderCardProps) {
  const [pendingAction, setPendingAction] = React.useState<string | null>(null);
  const [confirmDeleteKey, setConfirmDeleteKey] = React.useState<string | null>(null);

  const configuredCount = connections.filter(
    (c) => c.status !== 'disconnected'
  ).length;
  const totalSlots = providerName === 'UPS' ? 2 : 1;

  const handleDisconnect = async (key: string) => {
    setPendingAction(`disconnect:${key}`);
    try {
      await onDisconnect(key);
    } finally {
      setPendingAction(null);
    }
  };

  const handleDelete = async (key: string) => {
    setPendingAction(`delete:${key}`);
    try {
      await onDelete(key);
    } finally {
      setPendingAction(null);
      setConfirmDeleteKey(null);
    }
  };

  return (
    <div className="settings-section">
      <button
        className="settings-section-header"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-medium text-foreground">{providerName}</span>
          {connections.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
              {configuredCount}/{totalSlots}
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-muted-foreground transition-transform',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-3">
          {/* Existing connections */}
          {connections.map((conn) => (
            <div
              key={conn.connection_key}
              className="flex items-center justify-between p-2 rounded-md bg-muted/30 border border-border"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-foreground truncate">
                    {conn.display_name || conn.connection_key}
                  </span>
                  <span
                    className={cn(
                      'text-[10px] px-1.5 py-0.5 rounded-full border',
                      STATUS_COLORS[conn.status]
                    )}
                  >
                    {STATUS_LABELS[conn.status]}
                  </span>
                </div>
                {conn.environment && (
                  <span className="text-[10px] text-muted-foreground">
                    {conn.environment}
                  </span>
                )}
                {!conn.runtime_usable && conn.runtime_reason && (
                  <p className="text-[10px] text-warning mt-0.5">
                    {conn.runtime_reason}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-1 ml-2">
                {conn.status !== 'disconnected' && (
                  <button
                    onClick={() => handleDisconnect(conn.connection_key)}
                    disabled={pendingAction !== null}
                    className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
                    title="Temporarily disable this connection. Credentials are preserved."
                  >
                    {pendingAction === `disconnect:${conn.connection_key}` ? (
                      <span className="block w-3.5 h-3.5 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Unplug className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}

                {confirmDeleteKey === conn.connection_key ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDelete(conn.connection_key)}
                      disabled={pendingAction !== null}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-destructive/20 text-destructive hover:bg-destructive/30 disabled:opacity-50"
                    >
                      {pendingAction === `delete:${conn.connection_key}` ? '...' : 'Confirm'}
                    </button>
                    <button
                      onClick={() => setConfirmDeleteKey(null)}
                      className="text-[10px] px-1.5 py-0.5 rounded text-muted-foreground hover:bg-muted"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteKey(conn.connection_key)}
                    disabled={pendingAction !== null}
                    className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-destructive disabled:opacity-50"
                    title="Permanently remove this connection and its stored credentials."
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}

          {/* Credential form */}
          {children}
        </div>
      )}
    </div>
  );
}

export default ProviderCard;
