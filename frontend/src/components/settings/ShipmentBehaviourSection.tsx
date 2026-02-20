/**
 * Shipment Behaviour Section - Settings accordion section.
 *
 * Contains:
 * - Write-back toggle
 * - Warning handling preference
 * - Default service selection (future)
 */

import { ChevronDown, FileOutput, AlertTriangle } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { useAppState } from '@/hooks/useAppState';

interface ShipmentBehaviourSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function ShipmentBehaviourSection({
  isOpen,
  onToggle,
}: ShipmentBehaviourSectionProps) {
  const {
    writeBackEnabled,
    setWriteBackEnabled,
    warningPreference,
    setWarningPreference,
  } = useAppState();

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
          className={`h-4 w-4 text-muted-foreground transition-transform ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-4">
          {/* Write-back toggle */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <label className="text-sm font-medium text-foreground">
                Write-back tracking numbers
              </label>
              <p className="text-xs text-muted-foreground">
                Automatically update source with tracking numbers after shipment
              </p>
            </div>
            <Switch
              checked={writeBackEnabled}
              onCheckedChange={setWriteBackEnabled}
            />
          </div>

          {/* Warning handling */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              <label className="text-sm font-medium text-foreground">
                Rows with warnings
              </label>
            </div>
            <div className="flex gap-2">
              {(['ask', 'ship-all', 'skip-warnings'] as const).map((pref) => (
                <button
                  key={pref}
                  onClick={() => setWarningPreference(pref)}
                  className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                    warningPreference === pref
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/80'
                  }`}
                >
                  {pref === 'ask' && 'Ask each time'}
                  {pref === 'ship-all' && 'Ship all'}
                  {pref === 'skip-warnings' && 'Skip warnings'}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ShipmentBehaviourSection;
