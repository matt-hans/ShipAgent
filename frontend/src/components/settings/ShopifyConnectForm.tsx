/**
 * ShopifyConnectForm - Credential form for Shopify provider.
 *
 * Phase 1: Legacy token mode only (store domain + access token).
 * Phase 2 will add radio selector for client credentials mode.
 *
 * Validates store domain against *.myshopify.com on blur.
 * Normalizes domain on submit (strips protocol, trailing slash).
 */

import * as React from 'react';
import { saveProviderCredentials } from '@/lib/api';
import type { ProviderConnectionInfo } from '@/types/api';

interface ShopifyConnectFormProps {
  existingConnection: ProviderConnectionInfo | null;
  onSaved: () => void;
}

/** Normalize a Shopify domain to bare hostname. */
function normalizeDomain(raw: string): string {
  let d = raw.trim();
  // Strip protocol
  d = d.replace(/^https?:\/\//, '');
  // Strip trailing slash
  d = d.replace(/\/+$/, '');
  return d;
}

/** Validate domain looks like *.myshopify.com. */
function isValidDomain(domain: string): boolean {
  const normalized = normalizeDomain(domain);
  return /^[\w-]+\.myshopify\.com$/.test(normalized);
}

export function ShopifyConnectForm({ existingConnection, onSaved }: ShopifyConnectFormProps) {
  const [storeDomain, setStoreDomain] = React.useState('');
  const [accessToken, setAccessToken] = React.useState('');
  const [domainError, setDomainError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);

  const handleDomainBlur = () => {
    if (storeDomain.trim() && !isValidDomain(storeDomain)) {
      setDomainError('Domain must be in the format store-name.myshopify.com');
    } else {
      setDomainError(null);
    }
  };

  const handleSave = async () => {
    const normalized = normalizeDomain(storeDomain);
    if (!isValidDomain(storeDomain)) {
      setDomainError('Domain must be in the format store-name.myshopify.com');
      return;
    }
    if (!accessToken.trim()) {
      setError('Access token is required.');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      await saveProviderCredentials('shopify', {
        auth_mode: 'legacy_token',
        credentials: {
          access_token: accessToken.trim(),
        },
        metadata: {
          store_domain: normalized,
        },
        display_name: normalized,
      });

      setStoreDomain('');
      setAccessToken('');
      setShowForm(false);
      onSaved();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save credentials';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  // If connection exists and form is hidden, show "replace" option
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

  // If no connection and form hidden, show "connect" prompt
  if (!showForm) {
    return (
      <button
        onClick={() => setShowForm(true)}
        className="w-full text-xs text-primary hover:text-primary/80 py-1.5 text-center transition-colors"
      >
        + Connect Shopify
      </button>
    );
  }

  return (
    <div className="space-y-3 pt-1">
      {existingConnection && (
        <p className="text-[10px] text-warning">
          Saving will replace the existing Shopify credentials.
        </p>
      )}

      {/* Store Domain */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          Store Domain
        </label>
        <input
          type="text"
          value={storeDomain}
          onChange={(e) => {
            setStoreDomain(e.target.value);
            if (domainError) setDomainError(null);
          }}
          onBlur={handleDomainBlur}
          placeholder="your-store.myshopify.com"
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
        {domainError && (
          <p className="text-[10px] text-destructive">{domainError}</p>
        )}
      </div>

      {/* Access Token */}
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          Admin API Access Token
        </label>
        <input
          type="password"
          value={accessToken}
          onChange={(e) => setAccessToken(e.target.value)}
          placeholder="shpat_..."
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
      </div>

      {/* Error */}
      {error && (
        <p className="text-[11px] text-destructive bg-destructive/10 px-2.5 py-1.5 rounded-md">
          {error}
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !storeDomain.trim() || !accessToken.trim()}
          className="flex-1 text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
        >
          {saving && (
            <span className="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
          )}
          {saving ? 'Saving...' : existingConnection ? 'Replace Credentials' : 'Save Credentials'}
        </button>
        <button
          onClick={() => {
            setShowForm(false);
            setError(null);
            setDomainError(null);
          }}
          className="text-xs py-1.5 px-3 rounded-md border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default ShopifyConnectForm;
