/**
 * Settings flyout panel - Collapsible settings UI.
 *
 * Features:
 * - Slides in from right, 360px wide
 * - Three accordion sections: Shipment Behaviour, Address Book, Custom Commands
 * - Pushes chat on >=1024px, overlays with backdrop on <1024px
 */

import * as React from 'react';
import { X } from 'lucide-react';
import { useAppState } from '@/hooks/useAppState';
import { ShipmentBehaviourSection } from './ShipmentBehaviourSection';
import { AddressBookSection } from './AddressBookSection';
import { CustomCommandsSection } from './CustomCommandsSection';

export function SettingsFlyout() {
  const { settingsFlyoutOpen, setSettingsFlyoutOpen } = useAppState();
  const [openSection, setOpenSection] = React.useState<string | null>('shipment');

  if (!settingsFlyoutOpen) return null;

  const toggleSection = (section: string) => {
    setOpenSection(openSection === section ? null : section);
  };

  return (
    <>
      {/* Backdrop for mobile */}
      <div
        className="settings-backdrop lg:hidden"
        onClick={() => setSettingsFlyoutOpen(false)}
      />

      {/* Flyout panel */}
      <aside className="settings-flyout">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">Settings</h2>
          <button
            onClick={() => setSettingsFlyoutOpen(false)}
            className="p-1 rounded-md hover:bg-muted transition-colors"
            aria-label="Close settings"
          >
            <X className="h-5 w-5 text-muted-foreground" />
          </button>
        </div>

        <div className="settings-flyout-content">
          {/* Shipment Behaviour Section */}
          <ShipmentBehaviourSection
            isOpen={openSection === 'shipment'}
            onToggle={() => toggleSection('shipment')}
          />

          {/* Address Book Section */}
          <AddressBookSection
            isOpen={openSection === 'address'}
            onToggle={() => toggleSection('address')}
          />

          {/* Custom Commands Section */}
          <CustomCommandsSection
            isOpen={openSection === 'commands'}
            onToggle={() => toggleSection('commands')}
          />
        </div>
      </aside>
    </>
  );
}

export default SettingsFlyout;
