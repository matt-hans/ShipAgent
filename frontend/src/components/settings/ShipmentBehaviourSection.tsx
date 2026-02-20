/**
 * Shipment Behaviour Section - Settings accordion section.
 *
 * Contains:
 * - Warning handling preference
 * - Default service selection (future)
 */

import { ChevronDown, FileOutput, AlertTriangle } from 'lucide-react';
import { useAppState } from '@/hooks/useAppState';
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
          className={`h-4 w-4 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''
            }`}
        />
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-4">
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
        </div>
      )}
    </div>
  );
}

export default ShipmentBehaviourSection;
