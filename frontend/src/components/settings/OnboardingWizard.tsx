/**
 * Full-screen onboarding wizard shown on first launch.
 *
 * Three steps:
 * 1. Anthropic API Key (required)
 * 2. UPS Credentials (optional)
 * 3. Shipper Address (optional)
 *
 * On completion, calls POST /settings/onboarding/complete.
 */

import * as React from 'react';
import { useAppState } from '@/hooks/useAppState';
import * as api from '@/lib/api';

type Step = 1 | 2 | 3;

export function OnboardingWizard() {
  const { refreshAppSettings, refreshCredentialStatus } = useAppState();

  const [step, setStep] = React.useState<Step>(1);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Step 1: API Key
  const [apiKey, setApiKey] = React.useState('');

  // Step 2: UPS Credentials
  const [upsClientId, setUpsClientId] = React.useState('');
  const [upsClientSecret, setUpsClientSecret] = React.useState('');

  // Step 3: Shipper Address
  const [shipperName, setShipperName] = React.useState('');
  const [shipperPhone, setShipperPhone] = React.useState('');
  const [shipperAddress1, setShipperAddress1] = React.useState('');
  const [shipperAddress2, setShipperAddress2] = React.useState('');
  const [shipperCity, setShipperCity] = React.useState('');
  const [shipperState, setShipperState] = React.useState('');
  const [shipperZip, setShipperZip] = React.useState('');
  const [shipperCountry, setShipperCountry] = React.useState('US');

  const saveStep1 = async () => {
    if (!apiKey.trim()) {
      setError('Anthropic API key is required to continue.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.setCredential('ANTHROPIC_API_KEY', apiKey.trim());
      setStep(2);
    } catch (e: any) {
      setError(e.message || 'Failed to save API key.');
    } finally {
      setSaving(false);
    }
  };

  const saveStep2 = async () => {
    setSaving(true);
    setError(null);
    try {
      if (upsClientId.trim()) {
        await api.setCredential('UPS_CLIENT_ID', upsClientId.trim());
      }
      if (upsClientSecret.trim()) {
        await api.setCredential('UPS_CLIENT_SECRET', upsClientSecret.trim());
      }
      setStep(3);
    } catch (e: any) {
      setError(e.message || 'Failed to save UPS credentials.');
    } finally {
      setSaving(false);
    }
  };

  const finishOnboarding = async () => {
    setSaving(true);
    setError(null);
    try {
      // Save shipper address if any field is filled
      const hasAddress = shipperName || shipperAddress1 || shipperCity;
      if (hasAddress) {
        await api.updateSettings({
          shipper_name: shipperName || null,
          shipper_phone: shipperPhone || null,
          shipper_address1: shipperAddress1 || null,
          shipper_address2: shipperAddress2 || null,
          shipper_city: shipperCity || null,
          shipper_state: shipperState || null,
          shipper_zip: shipperZip || null,
          shipper_country: shipperCountry || null,
        });
      }
      await api.completeOnboarding();
      await refreshAppSettings();
      await refreshCredentialStatus();
    } catch (e: any) {
      setError(e.message || 'Failed to complete onboarding.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
      <div className="w-full max-w-lg mx-auto px-6">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-foreground font-serif mb-2">
            Welcome to ShipAgent
          </h1>
          <p className="text-muted-foreground">
            Let's get you set up. This takes about a minute.
          </p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {[1, 2, 3].map((s) => (
            <div
              key={s}
              className={`h-2 rounded-full transition-all ${
                s === step
                  ? 'w-8 bg-accent'
                  : s < step
                    ? 'w-2 bg-accent/50'
                    : 'w-2 bg-muted'
              }`}
            />
          ))}
          <span className="ml-3 text-xs text-muted-foreground">
            {step}/3
          </span>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm">
            {error}
          </div>
        )}

        {/* Step 1: API Key */}
        {step === 1 && (
          <div className="card-premium p-6">
            <h2 className="text-lg font-semibold text-foreground mb-1">
              Anthropic API Key
            </h2>
            <p className="text-sm text-muted-foreground mb-4">
              ShipAgent uses Claude to understand your shipping commands.
              Your key is stored securely in the system keychain.
            </p>
            <label className="block text-sm font-medium text-foreground mb-1.5">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-ant-..."
              className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
              autoFocus
            />
            <div className="flex justify-end mt-6">
              <button
                onClick={saveStep1}
                disabled={saving || !apiKey.trim()}
                className="btn-primary px-6 py-2 text-sm disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save & Continue'}
              </button>
            </div>
          </div>
        )}

        {/* Step 2: UPS Credentials */}
        {step === 2 && (
          <div className="card-premium p-6">
            <h2 className="text-lg font-semibold text-foreground mb-1">
              UPS Credentials
            </h2>
            <p className="text-sm text-muted-foreground mb-4">
              Connect your UPS account to create shipments.
              You can skip this and add credentials later in Settings.
            </p>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">
                  Client ID
                </label>
                <input
                  type="text"
                  value={upsClientId}
                  onChange={(e) => setUpsClientId(e.target.value)}
                  placeholder="Your UPS Client ID"
                  className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">
                  Client Secret
                </label>
                <input
                  type="password"
                  value={upsClientSecret}
                  onChange={(e) => setUpsClientSecret(e.target.value)}
                  placeholder="Your UPS Client Secret"
                  className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
            </div>
            <div className="flex justify-between mt-6">
              <button
                onClick={() => setStep(3)}
                className="btn-secondary px-4 py-2 text-sm"
              >
                Skip
              </button>
              <button
                onClick={saveStep2}
                disabled={saving}
                className="btn-primary px-6 py-2 text-sm disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save & Continue'}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Shipper Address */}
        {step === 3 && (
          <div className="card-premium p-6">
            <h2 className="text-lg font-semibold text-foreground mb-1">
              Shipper Address
            </h2>
            <p className="text-sm text-muted-foreground mb-4">
              Default return address for your shipments.
              You can skip this and set it later.
            </p>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Name</label>
                  <input
                    type="text"
                    value={shipperName}
                    onChange={(e) => setShipperName(e.target.value)}
                    placeholder="Company Name"
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                    autoFocus
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Phone</label>
                  <input
                    type="tel"
                    value={shipperPhone}
                    onChange={(e) => setShipperPhone(e.target.value)}
                    placeholder="555-123-4567"
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Address Line 1</label>
                <input
                  type="text"
                  value={shipperAddress1}
                  onChange={(e) => setShipperAddress1(e.target.value)}
                  placeholder="123 Main St"
                  className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Address Line 2</label>
                <input
                  type="text"
                  value={shipperAddress2}
                  onChange={(e) => setShipperAddress2(e.target.value)}
                  placeholder="Suite 100"
                  className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">City</label>
                  <input
                    type="text"
                    value={shipperCity}
                    onChange={(e) => setShipperCity(e.target.value)}
                    placeholder="City"
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">State</label>
                  <input
                    type="text"
                    value={shipperState}
                    onChange={(e) => setShipperState(e.target.value)}
                    placeholder="CA"
                    maxLength={2}
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">ZIP</label>
                  <input
                    type="text"
                    value={shipperZip}
                    onChange={(e) => setShipperZip(e.target.value)}
                    placeholder="90210"
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Country</label>
                <input
                  type="text"
                  value={shipperCountry}
                  onChange={(e) => setShipperCountry(e.target.value)}
                  placeholder="US"
                  maxLength={2}
                  className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
              </div>
            </div>
            <div className="flex justify-between mt-6">
              <button
                onClick={finishOnboarding}
                disabled={saving}
                className="btn-secondary px-4 py-2 text-sm disabled:opacity-50"
              >
                {saving ? 'Finishing...' : 'Skip'}
              </button>
              <button
                onClick={finishOnboarding}
                disabled={saving}
                className="btn-primary px-6 py-2 text-sm disabled:opacity-50"
              >
                {saving ? 'Finishing...' : 'Get Started'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
