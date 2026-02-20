/**
 * Address Book Section - Settings accordion section.
 *
 * Shows saved contact count with link to open full Address Book modal.
 * Modal is rendered at App-level to avoid unmount when flyout closes.
 */

import { ChevronDown, BookUser, Plus, ExternalLink } from 'lucide-react';
import { useAppState } from '@/hooks/useAppState';

interface AddressBookSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function AddressBookSection({
  isOpen,
  onToggle,
}: AddressBookSectionProps) {
  const { contacts, setSettingsFlyoutOpen, setAddressBookModalOpen } = useAppState();

  const handleOpenModal = () => {
    // Close flyout and open modal (modal is rendered at App level)
    setSettingsFlyoutOpen(false);
    setAddressBookModalOpen(true);
  };

  const shipToCount = contacts.filter((c) => c.use_as_ship_to).length;
  const shipperCount = contacts.filter((c) => c.use_as_shipper).length;

  return (
    <div className="settings-section">
      <button
        className="settings-section-header"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          <BookUser className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-foreground">Address Book</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {contacts.length} contacts
          </span>
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${
              isOpen ? 'rotate-180' : ''
            }`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-3">
          {/* Stats */}
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span>{shipToCount} ship-to addresses</span>
            <span>{shipperCount} shippers</span>
          </div>

          {/* Open Address Book button */}
          <button
            onClick={handleOpenModal}
            className="w-full flex items-center justify-between px-3 py-2 rounded-md bg-muted hover:bg-muted/80 transition-colors"
          >
            <span className="text-sm text-foreground">Manage contacts</span>
            <ExternalLink className="h-4 w-4 text-muted-foreground" />
          </button>

          {/* Quick add button */}
          <button
            onClick={handleOpenModal}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md border border-dashed border-border hover:border-primary hover:bg-primary/5 transition-colors"
          >
            <Plus className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Add new contact</span>
          </button>
        </div>
      )}
    </div>
  );
}

export default AddressBookSection;
