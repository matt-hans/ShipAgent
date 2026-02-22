/**
 * Shipment Behaviour Section - Settings accordion section.
 *
 * Contains:
 * - Warning handling preference
 * - Default batch concurrency
 * - Default shipper address
 *
 * All values persist to the Settings DB via api.updateSettings().
 */

import * as React from 'react';
import { ChevronDown, FileOutput, AlertTriangle, Gauge, MapPin } from 'lucide-react';
import { useAppState } from '@/hooks/useAppState';
import { updateSettings } from '@/lib/api';
import { cn } from '@/lib/utils';

interface ShipmentBehaviourSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function ShipmentBehaviourSection({
  isOpen,
  onToggle,
}: ShipmentBehaviourSectionProps) {
  const {
    warningPreference,
    setWarningPreference,
    appSettings,
    refreshAppSettings,
  } = useAppState();

  const [concurrency, setConcurrency] = React.useState(
    appSettings?.batch_concurrency ?? 5,
  );

  // Sync concurrency slider when appSettings changes
  React.useEffect(() => {
    if (appSettings?.batch_concurrency != null) {
      setConcurrency(appSettings.batch_concurrency);
    }
  }, [appSettings?.batch_concurrency]);

  const saveConcurrency = React.useCallback(
    async (value: number) => {
      setConcurrency(value);
      try {
        await updateSettings({ batch_concurrency: value });
        refreshAppSettings();
      } catch (err) {
        console.error('Failed to save concurrency:', err);
      }
    },
    [refreshAppSettings],
  );

  // Shipper address fields
  const [shipperDirty, setShipperDirty] = React.useState(false);
  const [shipperFields, setShipperFields] = React.useState({
    shipper_name: '',
    shipper_phone: '',
    shipper_address1: '',
    shipper_address2: '',
    shipper_city: '',
    shipper_state: '',
    shipper_zip: '',
    shipper_country: 'US',
  });

  // Sync shipper fields from appSettings on load
  React.useEffect(() => {
    if (appSettings) {
      setShipperFields({
        shipper_name: appSettings.shipper_name ?? '',
        shipper_phone: appSettings.shipper_phone ?? '',
        shipper_address1: appSettings.shipper_address1 ?? '',
        shipper_address2: appSettings.shipper_address2 ?? '',
        shipper_city: appSettings.shipper_city ?? '',
        shipper_state: appSettings.shipper_state ?? '',
        shipper_zip: appSettings.shipper_zip ?? '',
        shipper_country: appSettings.shipper_country ?? 'US',
      });
      setShipperDirty(false);
    }
  }, [appSettings]);

  const handleShipperChange = (field: string, value: string) => {
    setShipperFields((prev) => ({ ...prev, [field]: value }));
    setShipperDirty(true);
  };

  const saveShipperAddress = async () => {
    try {
      await updateSettings(shipperFields);
      setShipperDirty(false);
      refreshAppSettings();
    } catch (err) {
      console.error('Failed to save shipper address:', err);
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
          <FileOutput className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-foreground">Shipment Behaviour</span>
        </div>
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''
            }`}
        />
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-5">
          {/* Warning handling */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              <label className="text-sm font-medium text-foreground">
                Warning Rows
              </label>
            </div>

            <div className="space-y-1.5">
              {[
                { value: 'ask', label: 'Ask me each time', desc: 'Show options when rows have warnings' },
                { value: 'ship-all', label: 'Always try all rows', desc: 'Ship everything, failures handled per-row' },
                { value: 'skip-warnings', label: 'Skip warning rows', desc: 'Auto-exclude rows that failed rate validation' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setWarningPreference(opt.value as any)}
                  className={cn(
                    'w-full text-left px-3 py-2 rounded-md text-xs transition-colors border',
                    warningPreference === opt.value
                      ? opt.value === 'ship-all'
                        ? 'bg-info/10 border-info/30 text-info'
                        : opt.value === 'skip-warnings'
                          ? 'bg-warning/10 border-warning/30 text-warning'
                          : 'bg-primary/10 border-primary/30 text-primary'
                      : 'border-transparent text-slate-400 hover:bg-muted/50'
                  )}
                >
                  <span className="font-medium">{opt.label}</span>
                  <p className={cn(
                    "text-[10px] mt-0.5",
                    warningPreference === opt.value ? "opacity-90" : "text-slate-500"
                  )}>
                    {opt.desc}
                  </p>
                </button>
              ))}
            </div>
          </div>

          {/* Batch concurrency */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Gauge className="h-4 w-4 text-muted-foreground" />
              <label className="text-sm font-medium text-foreground">
                Batch Concurrency
              </label>
              <span className="text-xs text-muted-foreground ml-auto tabular-nums">
                {concurrency}
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={20}
              value={concurrency}
              onChange={(e) => saveConcurrency(Number(e.target.value))}
              className="w-full accent-primary h-1.5"
            />
            <p className="text-[10px] text-slate-500">
              Max simultaneous shipment API calls during batch execution
            </p>
          </div>

          {/* Default shipper address */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <MapPin className="h-4 w-4 text-muted-foreground" />
              <label className="text-sm font-medium text-foreground">
                Default Shipper Address
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                placeholder="Company Name"
                value={shipperFields.shipper_name}
                onChange={(e) => handleShipperChange('shipper_name', e.target.value)}
                className="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                placeholder="Phone"
                value={shipperFields.shipper_phone}
                onChange={(e) => handleShipperChange('shipper_phone', e.target.value)}
                className="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                placeholder="Address Line 1"
                value={shipperFields.shipper_address1}
                onChange={(e) => handleShipperChange('shipper_address1', e.target.value)}
                className="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                placeholder="Address Line 2"
                value={shipperFields.shipper_address2}
                onChange={(e) => handleShipperChange('shipper_address2', e.target.value)}
                className="col-span-2 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <input
                type="text"
                placeholder="City"
                value={shipperFields.shipper_city}
                onChange={(e) => handleShipperChange('shipper_city', e.target.value)}
                className="rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="State"
                  value={shipperFields.shipper_state}
                  onChange={(e) => handleShipperChange('shipper_state', e.target.value)}
                  className="w-16 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
                />
                <input
                  type="text"
                  placeholder="ZIP"
                  value={shipperFields.shipper_zip}
                  onChange={(e) => handleShipperChange('shipper_zip', e.target.value)}
                  className="flex-1 rounded-md border border-border bg-muted/30 px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
                />
              </div>
            </div>

            {shipperDirty && (
              <button
                onClick={saveShipperAddress}
                className="btn-primary text-xs w-full"
              >
                Save Shipper Address
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default ShipmentBehaviourSection;
