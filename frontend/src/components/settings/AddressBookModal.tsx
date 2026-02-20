/**
 * AddressBookModal - Full contact management modal.
 *
 * Features:
 * - List view with search and tag filter
 * - Add/edit/delete contacts
 * - Uses shadcn Dialog
 */

import * as React from 'react';
import { Search, Plus, Edit2, Trash2, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAppState } from '@/hooks/useAppState';
import * as api from '@/lib/api';
import { ContactForm } from './ContactForm';
import type { Contact, ContactCreate, ContactUpdate } from '@/types/api';

interface AddressBookModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddressBookModal({ open, onOpenChange }: AddressBookModalProps) {
  const { contacts, refreshContacts } = useAppState();

  // State
  const [search, setSearch] = React.useState('');
  const [tagFilter, setTagFilter] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);
  const [editingContact, setEditingContact] = React.useState<Contact | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [deleteConfirm, setDeleteConfirm] = React.useState<string | null>(null);

  // Get unique tags from all contacts
  const allTags = React.useMemo(() => {
    const tagSet = new Set<string>();
    contacts.forEach((c) => c.tags?.forEach((t) => tagSet.add(t)));
    return Array.from(tagSet).sort();
  }, [contacts]);

  // Filter contacts
  const filteredContacts = React.useMemo(() => {
    return contacts.filter((c) => {
      // Search filter
      if (search) {
        const q = search.toLowerCase();
        const matchesSearch =
          c.handle.toLowerCase().includes(q) ||
          c.display_name.toLowerCase().includes(q) ||
          c.city.toLowerCase().includes(q) ||
          c.state_province.toLowerCase().includes(q);
        if (!matchesSearch) return false;
      }

      // Tag filter
      if (tagFilter && !c.tags?.includes(tagFilter)) {
        return false;
      }

      return true;
    });
  }, [contacts, search, tagFilter]);

  const handleAddNew = () => {
    setEditingContact(null);
    setShowForm(true);
  };

  const handleEdit = (contact: Contact) => {
    setEditingContact(contact);
    setShowForm(true);
  };

  const handleDelete = async (contactId: string) => {
    setIsLoading(true);
    try {
      await api.deleteContact(contactId);
      await refreshContacts();
      setDeleteConfirm(null);
    } catch (error) {
      console.error('Failed to delete contact:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFormSubmit = async (data: ContactCreate | ContactUpdate) => {
    setIsLoading(true);
    try {
      if (editingContact) {
        await api.updateContact(editingContact.id, data as ContactUpdate);
      } else {
        await api.createContact(data as ContactCreate);
      }
      await refreshContacts();
      setShowForm(false);
      setEditingContact(null);
    } catch (error) {
      console.error('Failed to save contact:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFormCancel = () => {
    setShowForm(false);
    setEditingContact(null);
  };

  // Reset state when modal closes
  React.useEffect(() => {
    if (!open) {
      setSearch('');
      setTagFilter(null);
      setShowForm(false);
      setEditingContact(null);
      setDeleteConfirm(null);
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {showForm ? (editingContact ? 'Edit Contact' : 'Add Contact') : 'Address Book'}
          </DialogTitle>
        </DialogHeader>

        {showForm ? (
          <ContactForm
            contact={editingContact}
            onSubmit={handleFormSubmit}
            onCancel={handleFormCancel}
            isLoading={isLoading}
          />
        ) : (
          <div className="flex-1 overflow-hidden flex flex-col gap-4">
            {/* Search and filters */}
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search contacts..."
                  className="pl-9"
                />
              </div>
              <Button onClick={handleAddNew}>
                <Plus className="h-4 w-4 mr-1" />
                Add
              </Button>
            </div>

            {/* Tag filter chips */}
            {allTags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setTagFilter(null)}
                  className={`px-2 py-0.5 rounded text-xs transition-colors ${
                    tagFilter === null
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted hover:bg-muted/80'
                  }`}
                >
                  All
                </button>
                {allTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => setTagFilter(tag)}
                    className={`px-2 py-0.5 rounded text-xs transition-colors ${
                      tagFilter === tag
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted hover:bg-muted/80'
                    }`}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}

            {/* Contact list */}
            <div className="flex-1 overflow-y-auto space-y-2">
              {filteredContacts.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  {search || tagFilter ? 'No contacts match your filters' : 'No contacts yet'}
                </div>
              ) : (
                filteredContacts.map((contact) => (
                  <div
                    key={contact.id}
                    className="flex items-start justify-between p-3 rounded-lg border border-border bg-card hover:bg-muted/30 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-primary">
                          @{contact.handle}
                        </span>
                        <span className="text-sm font-medium">
                          {contact.display_name}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {contact.address_line_1}
                        {contact.address_line_2 && `, ${contact.address_line_2}`}
                        <br />
                        {contact.city}, {contact.state_province} {contact.postal_code}
                        {contact.country_code !== 'US' && ` ${contact.country_code}`}
                      </div>
                      <div className="flex items-center gap-2 mt-1.5">
                        {contact.use_as_ship_to && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-domain-shipping/20 text-domain-shipping rounded">
                            ship-to
                          </span>
                        )}
                        {contact.use_as_shipper && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-domain-pickup/20 text-domain-pickup rounded">
                            shipper
                          </span>
                        )}
                        {contact.tags?.slice(0, 3).map((t) => (
                          <span
                            key={t}
                            className="text-[10px] px-1.5 py-0.5 bg-muted rounded"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 ml-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEdit(contact)}
                      >
                        <Edit2 className="h-4 w-4" />
                      </Button>
                      {deleteConfirm === contact.id ? (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => handleDelete(contact.id)}
                            disabled={isLoading}
                          >
                            Confirm
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeleteConfirm(null)}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setDeleteConfirm(contact.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Stats */}
            <div className="text-xs text-muted-foreground text-center pt-2 border-t">
              {filteredContacts.length} of {contacts.length} contacts
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default AddressBookModal;
