/**
 * UPSConnectForm - Credential form for UPS provider connections.
 *
 * Fields: Client ID, Client Secret, Account Number (optional).
 * Environment tab toggle: Test / Production (required selection, no default).
 * Each environment submits as its own connection_key.
 * After save: auto-validates against UPS OAuth, shows result.
 */

import * as React from 'react';
import { cn } from '@/lib/utils';
import { saveProviderCredentials, validateProviderConnection } from '@/lib/api';
import type { ProviderConnectionInfo } from '@/types/api';

interface UPSConnectFormProps {
  existingConnections: ProviderConnectionInfo[];
  onSaved: () => void;
}

type UPSEnvironment = 'test' | 'production';

export function UPSConnectForm({ existingConnections, onSaved }: UPSConnectFormProps) {
  const [environment, setEnvironment] = React.useState<UPSEnvironment | null>(null);
  const [clientId, setClientId] = React.useState('');
  const [clientSecret, setClientSecret] = React.useState('');
  const [accountNumber, setAccountNumber] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);

  // Check if the selected environment already has a connection
  const existingForEnv = environment
    ? existingConnections.find((c) => c.environment === environment)
    : null;

  const handleSave = async () => {
    if (!environment) {
      setError('Select an environment (Test or Production).');
      return;
    }
    if (!clientId.trim() || !clientSecret.trim()) {
      setError('Client ID and Client Secret are required.');
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const saveResult = await saveProviderCredentials('ups', {
        auth_mode: 'client_credentials',
        credentials: {
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
          ...(accountNumber.trim() ? { account_number: accountNumber.trim() } : {}),
        },
        metadata: {
          ...(accountNumber.trim() ? { account_number: accountNumber.trim() } : {}),
        },
        display_name: `UPS ${environment === 'test' ? 'Test (CIE)' : 'Production'}`,
        environment: environment,
      });

      // Auto-validate: test credentials against UPS OAuth
      const connectionKey = saveResult.connection_key;
      const validation = await validateProviderConnection(connectionKey);

      if (validation.valid) {
        setSuccess(validation.message);
        setClientId('');
        setClientSecret('');
        setAccountNumber('');
        setShowForm(false);
      } else {
        setError(validation.message);
      }
      onSaved();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save credentials';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  // If connections exist and form is hidden, show "replace" option
  if (!showForm && existingConnections.length > 0) {
    return (
      <button
        onClick={() => setShowForm(true)}
        className="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        + Add or replace credentials
      </button>
    );
  }

  // If no connections and form is hidden, show "connect" prompt
  if (!showForm) {
    return (
      <button
        onClick={() => setShowForm(true)}
        className="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        + Connect UPS
      </button>
    );
  }

  return (
    <div className="space-y-3 pt-1">
      {/* Environment toggle */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
          Environment
        </label>
        <div className="flex gap-1.5">
          {(['test', 'production'] as const).map((env) => {
            const isActive = environment === env;
            const hasExisting = existingConnections.some((c) => c.environment === env);
            return (
              <button
                key={env}
                onClick={() => setEnvironment(env)}
                className={cn(
                  'flex-1 text-xs py-1.5 px-2 rounded-md border transition-colors',
                  isActive
                    ? env === 'production'
                      ? 'bg-success/10 border-success/30 text-success'
                      : 'bg-info/10 border-info/30 text-info'
                    : 'border-border text-muted-foreground hover:bg-muted/50'
                )}
              >
                {env === 'test' ? 'Test (CIE)' : 'Production'}
                {hasExisting && !isActive && (
                  <span className="ml-1 text-[9px] opacity-60">●</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {environment && (
        <>
          {existingForEnv && (
            <p className="text-[10px] text-warning">
              Saving will replace the existing {environment} credentials.
            </p>
          )}

          {/* Client ID */}
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">
              Client ID
            </label>
            <input
              type="text"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="Enter UPS Client ID"
              className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>

          {/* Client Secret */}
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">
              Client Secret
            </label>
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder="Enter UPS Client Secret"
              className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>

          {/* Account Number (optional) */}
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">
              Account Number <span className="text-muted-foreground/50">(optional)</span>
            </label>
            <input
              type="text"
              value={accountNumber}
              onChange={(e) => setAccountNumber(e.target.value)}
              placeholder="6-digit UPS account number"
              className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-[11px] text-destructive bg-destructive/10 px-2.5 py-1.5 rounded-md">
              {error}
            </p>
          )}

          {/* Success */}
          {success && (
            <p className="text-[11px] text-success bg-success/10 px-2.5 py-1.5 rounded-md">
              {success}
            </p>
          )}

          {/* Actions */}
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={saving || !clientId.trim() || !clientSecret.trim()}
              className="flex-1 text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
            >
              {saving && (
                <span className="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
              )}
              {saving ? 'Saving & Validating...' : existingForEnv ? 'Replace Credentials' : 'Save & Validate'}
            </button>
            <button
              onClick={() => {
                setShowForm(false);
                setError(null);
                setSuccess(null);
                setEnvironment(null);
              }}
              className="text-xs py-1.5 px-3 rounded-md border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default UPSConnectForm;
