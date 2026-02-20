/**
 * Header component - Branding header with interactive shipping toggle and settings.
 *
 * Features:
 * - Logo and app name
 * - Interactive shipping mode toggle (persisted via AppState)
 * - Settings gear button to open flyout
 */

import { Package, Settings } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { useAppState } from '@/hooks/useAppState';

export function Header() {
  const {
    interactiveShipping,
    setInteractiveShipping,
    isToggleLocked,
    settingsFlyoutOpen,
    setSettingsFlyoutOpen,
  } = useAppState();

  return (
    <header className="app-header">
      {/* Gradient accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-accent/50 to-transparent" />

      <div className="container-wide h-12 flex items-center justify-between">
        {/* Logo and branding */}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Package className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-semibold text-foreground">ShipAgent</span>
        </div>

        {/* Right side: toggle + settings */}
        <div className="flex items-center gap-4">
          {/* Interactive shipping toggle */}
          <div className="flex items-center gap-2">
            <label
              htmlFor="interactive-shipping-toggle"
              className="text-xs text-slate-400 cursor-pointer select-none"
            >
              Single Shipment
            </label>
            <Switch
              id="interactive-shipping-toggle"
              checked={interactiveShipping}
              onCheckedChange={setInteractiveShipping}
              disabled={isToggleLocked}
            />
          </div>

          {/* Settings button */}
          <button
            onClick={() => setSettingsFlyoutOpen(!settingsFlyoutOpen)}
            className={`p-2 rounded-md transition-colors ${
              settingsFlyoutOpen
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted text-muted-foreground hover:text-foreground'
            }`}
            aria-label="Open settings"
            aria-pressed={settingsFlyoutOpen}
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
}

export default Header;
