/**
 * AmazonConnectForm - Credential form for Amazon Selling Partner API.
 *
 * Collects LWA credentials (client_id, client_secret) and marketplace_id.
 * Refresh token is optional — sandbox apps use only LWA client credentials,
 * while production apps obtain a refresh token via the seller OAuth flow.
 * All credentials are encrypted (AES-256-GCM) on the backend before storage.
 */

import * as React from 'react';
import { saveProviderCredentials, validateProviderConnection } from '@/lib/api';
import type { ProviderConnectionInfo } from '@/types/api';

/** Common Amazon marketplace IDs for the dropdown. */
const MARKETPLACE_OPTIONS = [
  { id: 'ATVPDKIKX0DER', label: 'United States (ATVPDKIKX0DER)' },
  { id: 'A2EUQ1WTGCTBG2', label: 'Canada (A2EUQ1WTGCTBG2)' },
  { id: 'A1AM78C64UM0Y8', label: 'Mexico (A1AM78C64UM0Y8)' },
  { id: 'A1F83G8C2ARO7P', label: 'United Kingdom (A1F83G8C2ARO7P)' },
  { id: 'A1PA6795UKMFR9', label: 'Germany (A1PA6795UKMFR9)' },
] as const;

interface AmazonConnectFormProps {
  existingConnection: ProviderConnectionInfo | null;
  onSaved: () => void;
}

export function AmazonConnectForm({ existingConnection, onSaved }: AmazonConnectFormProps) {
  const [clientId, setClientId] = React.useState('');
  const [clientSecret, setClientSecret] = React.useState('');
  const [refreshToken, setRefreshToken] = React.useState('');
  const [marketplaceId, setMarketplaceId] = React.useState(MARKETPLACE_OPTIONS[0].id);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);

  const canSave = clientId.trim() && clientSecret.trim() && marketplaceId.trim();

  const handleSave = async () => {
    if (!canSave) return;

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const credentials: Record<string, string> = {
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
        marketplace_id: marketplaceId.trim(),
      };
      if (refreshToken.trim()) {
        credentials.refresh_token = refreshToken.trim();
      }

      const saveResult = await saveProviderCredentials('amazon', {
        auth_mode: 'sp_api',
        credentials,
        metadata: {
          marketplace_id: marketplaceId.trim(),
        },
        display_name: `Amazon ${MARKETPLACE_OPTIONS.find((m) => m.id === marketplaceId)?.label.split(' (')[0] || marketplaceId}`,
      });

      // Auto-validate if endpoint is wired up
      try {
        const validation = await validateProviderConnection(saveResult.connection_key);
        if (validation.valid) {
          setSuccess(validation.message);
        } else {
          setSuccess('Credentials saved. Validation returned: ' + validation.message);
        }
      } catch {
        // Validation endpoint may not exist yet for Amazon
        setSuccess('Credentials saved and encrypted.');
      }

      setClientId('');
      setClientSecret('');
      setRefreshToken('');
      setShowForm(false);
      onSaved();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save credentials';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  if (!showForm && existingConnection) {
    return (
      <button
        onClick={() => setShowForm(true)}
        className="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        + Replace credentials
      </button>
    );
  }

  if (!showForm) {
    return (
      <button
        onClick={() => setShowForm(true)}
        className="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        + Connect Amazon
      </button>
    );
  }

  return (
    <div className="space-y-3 pt-1">
      {existingConnection && (
        <p className="text-[10px] text-warning">
          Saving will replace the existing Amazon credentials.
        </p>
      )}

      {/* LWA Client ID */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          LWA Client ID
        </label>
        <input
          type="text"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder="amzn1.application-oa2-client...."
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
      </div>

      {/* LWA Client Secret */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          LWA Client Secret
        </label>
        <input
          type="password"
          value={clientSecret}
          onChange={(e) => setClientSecret(e.target.value)}
          placeholder="amzn1.oa2-cs.v1...."
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
      </div>

      {/* Marketplace */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          Marketplace
        </label>
        <select
          value={marketplaceId}
          onChange={(e) => setMarketplaceId(e.target.value)}
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
        >
          {MARKETPLACE_OPTIONS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      {/* LWA Refresh Token (optional) */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          Refresh Token <span className="text-muted-foreground/50">(optional)</span>
        </label>
        <input
          type="password"
          value={refreshToken}
          onChange={(e) => setRefreshToken(e.target.value)}
          placeholder="Atzr|..."
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
        <p className="text-[10px] text-muted-foreground">
          Not needed for sandbox. For production, obtained via Seller Central &rarr; Authorize.
        </p>
      </div>

      {error && (
        <p className="text-[11px] text-destructive bg-destructive/10 px-2.5 py-1.5 rounded-md">
          {error}
        </p>
      )}

      {success && (
        <p className="text-[11px] text-success bg-success/10 px-2.5 py-1.5 rounded-md">
          {success}
        </p>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !canSave}
          className="flex-1 text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
        >
          {saving && (
            <span className="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
          )}
          {saving ? 'Saving...' : existingConnection ? 'Replace Credentials' : 'Save & Validate'}
        </button>
        <button
          onClick={() => {
            setShowForm(false);
            setError(null);
            setSuccess(null);
          }}
          className="text-xs py-1.5 px-3 rounded-md border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default AmazonConnectForm;
