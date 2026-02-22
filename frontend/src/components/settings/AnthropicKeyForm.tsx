/**
 * AnthropicKeyForm - Credential form for updating the Anthropic API key.
 *
 * Simple password input with save button. Calls the keyring-backed
 * credential endpoint to store the key securely.
 */

import * as React from 'react';
import { setCredential } from '@/lib/api';

interface AnthropicKeyFormProps {
  onSaved: () => void;
}

export function AnthropicKeyForm({ onSaved }: AnthropicKeyFormProps) {
  const [apiKey, setApiKey] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState<string | null>(null);

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setError('API key is required.');
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      await setCredential('ANTHROPIC_API_KEY', apiKey.trim());
      setSuccess('API key updated successfully.');
      setApiKey('');
      onSaved();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save API key.';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 pt-1">
      <div className="space-y-1">
        <label className="text-[11px] font-medium text-muted-foreground">
          API Key
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value);
            setError(null);
            setSuccess(null);
          }}
          placeholder="sk-ant-..."
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
        />
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

      <button
        onClick={handleSave}
        disabled={saving || !apiKey.trim()}
        className="w-full text-xs py-1.5 px-3 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
      >
        {saving && (
          <span className="block w-3 h-3 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
        )}
        {saving ? 'Saving...' : 'Update API Key'}
      </button>
    </div>
  );
}

export default AnthropicKeyForm;
